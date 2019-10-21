"""
Wrappers for QBO OAuth sessions (around OAuth2Session, saving/retreiving tokens and other settings from persistent
storage to make it easier to call QBO APIs). Separate classes for autorize/token/api because the OAuth2Session
constuctors are a bit different and QBO is quite specific in terms of the requests (for example CLIENT_ID has to be
passed in when authorizing, but can't be when getting the token).
"""


import base64
import os
import json
import logging
from datetime import datetime
from requests_oauthlib import OAuth2Session
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError
from google.appengine.api import urlfetch
from google.appengine.ext import ndb

from app.clients import client_utils
from app.services.ndb_models import Org, OrgCredentials
from app.utils.sync_utils import (
    AuthCancelled,
    FailedToGetCompanyName,
    LINKING,
    MismatchingFileConnectionAttempt,
    RateLimitException,
    UnauthorizedApiCallException,
    InvalidGrantException,
    MissingProviderConfigException
)

TOKEN_URL = os.environ.get('QBO_TOKEN_URL')
AUTH_HOST = os.environ.get('QBO_AUTH_HOST')
API_HOST = os.environ.get('QBO_API_HOST')
SCOPES = ['com.intuit.quickbooks.accounting']
BASE_API_URI = os.environ.get('QBO_BASE_API_URI')
API_MINOR_VERSION = os.environ.get('QBO_API_MINOR_VERSION')


class QboAuthorizationSession(OAuth2Session):
    """
    Class that facilitates first step of the oAuth flow. Stores org details and gives a URL for user to go to in order
    to complete the authorisation.
    """

    def __init__(self, org_uid, provider_config, redirect_url):
        """
        Prepares the org for linking.

        Args:
            org_uid(str): org identifier
            provider_config(ProviderConfig): ndb model holding the provider config for the org
            redirect_url(str): the url to which the linker should send the user to after saving qbo tokens
        """
        org = Org.get_by_id(org_uid) or Org(id=org_uid, provider='qbo', provider_config=provider_config.key)

        # If this is a `relink`, check the org has a provider_config set
        if org.provider_config is None:
            org.provider_config = provider_config.key

        msg = "setting org status to linking (status {}) and saving redirect_url ({})'"
        logging.info(msg.format(LINKING, redirect_url))

        org.status = LINKING
        org.redirect_url = redirect_url
        org.put()

        callback_uri = client_utils.get_redirect_uri_for(org.provider)
        super(QboAuthorizationSession, self).__init__(
            provider_config.client_id,
            redirect_uri=callback_uri,
            scope=SCOPES,
            state=org_uid
        )

    def get_authorization_url(self):
        """
        Returns the url to which the user should be redirected to in order to complete the auth flow.

        Returns:
            str: url to which the user should be redirected to in order to complete the auth flow
        """
        authorization_url, _ = self.authorization_url(AUTH_HOST)
        return authorization_url


class QboTokenSession(OAuth2Session):
    """
    Class to facilitate exchange of auth code for access token.
    """

    def __init__(self, org_uid, callback_args):
        """
        Extracts QBO file details and access tokens from the QBO callback.

        Args:
            org_uid(str): org identifier
            redirect_uri(str): uri to which qbo sends tokens
            callback_args(dict): request parameters send by qbo
        """
        self.org_uid = org_uid
        self.callback_args = callback_args
        self.org = Org.get_by_id(org_uid)

        if callback_args.get('error') == 'access_denied':
            raise AuthCancelled(self.org)

        entity_id = callback_args.get('realmId')

        if self.org.entity_id and self.org.entity_id != entity_id:
            raise MismatchingFileConnectionAttempt(self.org)

        logging.info("saving entity_id '{}' for org '{}'".format(entity_id, org_uid))
        self.org.entity_id = entity_id
        self.org.put()

        super(QboTokenSession, self).__init__(
            redirect_uri=client_utils.get_redirect_uri_for(self.org.provider),
        )

    def get_and_save_token(self):
        """
        Fetches the access token from QBO with the given auth code. Also kicks off the sync of the org as it can be
        considered connected once the access token is obtained.
        """
        provider_config = self.org.provider_config.get()
        token = self.fetch_token(
            TOKEN_URL,
            code=self.callback_args.get('code'),
            headers={
                'Authorization': "Basic " + base64.b64encode(
                    provider_config.client_id + ":" + provider_config.client_secret
                ),
                'Accept': 'application/json',
                'content-type': 'application/x-www-form-urlencoded'
            }
        )
        parent = ndb.Key('Org', self.org_uid)
        OrgCredentials(parent=parent, id=self.org_uid, token=token).put()


class QboApiSession(OAuth2Session):
    """
    Class to facilitate making API calls to QBO.
    """

    def __init__(self, org_uid):
        """
        Prepares access token for API calls (gets it from datastore and refreshes as needed).

        Args:
            org_uid(str): org identifier
        """
        parent = ndb.Key('Org', org_uid)
        self.org_uid = org_uid
        org = parent.get_async()
        self.creds = OrgCredentials.get_by_id(org_uid, parent=parent)
        expires_at = datetime.utcfromtimestamp(self.creds.token['expires_at'])

        # TODO: this call and refresh_token function might not be needed as OAuth2Session can take auto_refresh_url
        # as a parameter and do this automatically
        provider_config_key = org.get_result().provider_config
        if provider_config_key is None:
            logging.warn("org `{}` does not have a provider config.".format(parent.id()))
            raise MissingProviderConfigException()
        else:
            self.provider_config = provider_config_key.get()
        if (expires_at - datetime.utcnow()).total_seconds() < 60:
            logging.info("access token for {} about to expire, refreshing".format(self.org_uid))
            self.refresh_token()

        super(QboApiSession, self).__init__(self.provider_config.client_id, token=self.creds.token)

    def refresh_token(self):
        """
        Refreshes the access token for the org.
        """
        try:
            token = OAuth2Session().refresh_token(
                token_url=TOKEN_URL,
                refresh_token=self.creds.token['refresh_token'],
                headers={
                    'Authorization': "Basic " + base64.b64encode(
                        self.provider_config.client_id + ":" + self.provider_config.client_secret
                    ),
                    'Accept': 'application/json',
                    'content-type': 'application/x-www-form-urlencoded'
                }
            )
        except InvalidGrantError:
            logging.warn("got InvalidGrantError exception on token refresh")
            raise InvalidGrantException()

        parent = ndb.Key('Org', self.org_uid)
        OrgCredentials(parent=parent, id=self.org_uid, token=token).put()
        self.creds = OrgCredentials.get_by_id(self.org_uid, parent=parent)

    def get_company_name(self):
        """
        Makes an API call to QBO and extracts the company name.

        Returns:
            str: company name
        """
        entity_id = Org.get_by_id(self.org_uid).entity_id
        url_template = "{}company/{}/companyinfo/{}?minorversion={}"
        url = url_template.format(BASE_API_URI, entity_id, entity_id, API_MINOR_VERSION)

        try:
            urlfetch.set_default_fetch_deadline(10)
            data = self.get(url, headers={'Accept': 'application/json'})
        except Exception:
            # we don't want this to interrupt the linking flow
            logging.warning("failed to get company name for entity {}".format(entity_id), exc_info=True)
            raise FailedToGetCompanyName()

        return data.get('CompanyInfo', {}).get('CompanyName')

    def request(self, method, url, data=None, headers=None, withhold_token=False, client_id=None, client_secret=None, **kwargs):
        """
        Overrides the OAuth2Session request method to handle QBO specific errors. Based on this handling here the parent
        sync loop decides if it should retry API calls.

        Returns:
            dict: data returned by qbo for an api call
        """
        response = super(QboApiSession, self).request(
            method,
            url,
            data=data,
            headers=headers,
            withhold_token=withhold_token,
            client_id=client_id,
            client_secret=client_secret,
            **kwargs
        )

        if response.status_code == 429:
            logging.info("got a 429 - {}".format(response.text))
            raise RateLimitException()

        if response.status_code == 401:
            raise UnauthorizedApiCallException()

        if response.status_code != 200:
            logging.info(u"got response with status: {}, and response: {}".format(response.status_code, response.text))
            raise ValueError("api call failed with code {}: url - {}".format(response.status_code, url))

        data = json.loads(response.text)

        if 'Fault' in data:
            raise ValueError("api call failed: url - {}, data - {}".format(url, data))

        return data

    def is_authenticated(self):
        """
        Provides on-demand checking of the ability to make API calls for an org.

        Args:
            org_uid(str): org identifier

        Returns:
            bool: true if api calls can be made, false if not
        """

        try:
            company_name = self.get_company_name()
        except Exception as e:
            logging.exception("got an error checking if auth is ok", e)
            return False

        return company_name is not None

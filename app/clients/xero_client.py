"""
Wrappers for Xero OAuth sessions. Note: This provider uses `Oauth1`
Sessions in Xero are instantiated differently based on whether it is a
partner app or public app. `Partner` apps require an RSA key (using RSA-SHA1 to sign requests)
and have refreshable tokens.
`Public` apps on the other hand sign requests with HMAC-SHA1 and don't have refreshable tokens
Note: Both application types tokens last for 30 minutes.
"""

import logging
import os

from google.appengine.api import urlfetch
from google.appengine.ext import ndb
import calendar
from app.clients import client_utils

from requests_oauthlib import OAuth1Session
from app.services.ndb_models import Org, OrgCredentials
from datetime import datetime, timedelta
from app.utils.sync_utils import (
    FailedToGetCompanyName,
    LINKING,
    MismatchingFileConnectionAttempt,
    ForbiddenApiCallException,
    RateLimitException,
    UnauthorizedApiCallException,
    DisconnectException,
    MissingProviderConfigException
)
import json as json_module

logging.getLogger("requests").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.INFO)

TOKEN_URL = os.environ.get('XERO_TOKEN_URL')
AUTH_HOST = os.environ.get('XERO_AUTH_HOST')
ACCESS_URL = os.environ.get('XERO_ACCESS_URL')
XERO_BASE_URI = os.environ.get('XERO_API_URL')

RSA = 'RSA-SHA1'
HMAC = 'HMAC-SHA1'
PARTNER = 'partner'


class XeroAuthorizationSession(OAuth1Session):
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
            redirect_url(str): the url to which the linker should send the user to after saving xero tokens
        """

        org = Org.get_by_id(org_uid) or Org(id=org_uid, provider='xerov2', provider_config=provider_config.key)

        # If this is a `relink`, check the org has a provider_config set
        if org.provider_config is None:
            org.provider_config = provider_config.key

        logging.info(
            "Provider secret = {} provider id {}".format(
                provider_config.client_secret,
                provider_config.client_id
            )
        )

        msg = "setting org status to linking (status {}) and saving redirect_url ({})'"
        logging.info(msg.format(LINKING, redirect_url))

        org.status = LINKING
        org.redirect_url = redirect_url
        org.put()

        rsa_key, rsa_method = _get_partner_session_attrs(provider_config)
        callback_uri = client_utils.get_redirect_uri_for(org.provider, org_uid)
        self.org_uid = org_uid

        super(XeroAuthorizationSession, self).__init__(
            client_key=provider_config.client_id,
            client_secret=provider_config.client_secret,
            callback_uri=callback_uri,
            rsa_key=rsa_key,
            signature_method=rsa_method
        )

    def get_authorization_url(self):
        """
        Returns the url to which the user should be redirected to in order to complete the auth flow.

        Returns:
            str: url to which the user should be redirected to in order to complete the auth flow
        """

        request_token = self.fetch_request_token(TOKEN_URL)
        authorization_url = self.authorization_url(AUTH_HOST)
        parent = ndb.Key('Org', self.org_uid)
        OrgCredentials(parent=parent, id=self.org_uid, token=request_token).put()
        return authorization_url


class XeroTokenSession(OAuth1Session):
    """
    Class to facilitate exchange of auth code for access token.
    """
    def __init__(self, org_uid, callback_args):
        """
        Third step of the Oauth1 flow. Processing the callback from Xero and
        using the callback params for fetching the access token.

        Args:
            org_uid(str): org identifier
            callback_args(dict): request parameters send by Xero
        """

        self.org_uid = org_uid
        self.callback_args = callback_args
        self.org = Org.get_by_id(org_uid)
        self.provider = self.org.provider_config.get()
        rsa_key, rsa_method = _get_partner_session_attrs(self.provider)
        request_token = OrgCredentials.get_by_id(self.org_uid, parent=self.org.key).token

        super(XeroTokenSession, self).__init__(
            self.provider.client_id,
            client_secret=self.provider.client_secret,
            resource_owner_key=callback_args['oauth_token'],
            resource_owner_secret=request_token.get('oauth_token_secret'),
            verifier=callback_args['oauth_verifier'],
            rsa_key=rsa_key,
            signature_method=rsa_method
        )

    def get_and_save_token(self):
        token = _process_token(self.fetch_access_token(ACCESS_URL))
        parent = ndb.Key('Org', self.org_uid)
        OrgCredentials(parent=parent, id=self.org_uid, token=token).put()

        # If the entity_id exists, this is a reconnect. Confirm the file connected is the same one.
        if self.org.entity_id:
            xero_session = XeroApiSession(self.org_uid)
            if xero_session.get_short_code() != self.org.entity_id:
                raise MismatchingFileConnectionAttempt(self.org)


class XeroApiSession(OAuth1Session):
    """
    Class to facilitate making API calls to Xero.
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

        self.current_token = self.creds.token
        expires_at = datetime.utcfromtimestamp((self.creds.token['expires_at']))

        self.org = org.get_result()
        provider_config_key = self.org.provider_config

        if provider_config_key is None:
            logging.warn("org `{}` does not have a provider config.".format(parent.id()))
            raise MissingProviderConfigException
        else:
            self.provider_config = provider_config_key.get()

        auth_attrs = json_module.loads(self.provider_config.additional_auth_attributes)

        if (expires_at - datetime.utcnow()).total_seconds() < 60:
            logging.info("access token for {} about to expire, refreshing".format(self.org_uid))

            if auth_attrs['application_type'] == PARTNER:
                self.refresh_token(auth_attrs['rsa_key'])
            else:
                logging.info("application type is `public`. Skipping refresh.")

        rsa_key, sig_method = _get_partner_session_attrs(self.provider_config)

        super(XeroApiSession, self).__init__(
            self.provider_config.client_id,
            client_secret=self.provider_config.client_secret,
            resource_owner_key=self.current_token['oauth_token'],
            resource_owner_secret=self.current_token.get('oauth_token_secret'),
            rsa_key=rsa_key,
            signature_method=sig_method
        )

    def refresh_token(self, rsa_key):
        """
        Refreshes the access token. This can only be done with Partner tokens,
        not public ones.

        Args:
            rsa_key (str): The RSA key
        """

        oauth = OAuth1Session(
            self.provider_config.client_id,
            client_secret=self.provider_config.client_secret,
            resource_owner_key=self.current_token['oauth_token'],
            resource_owner_secret=self.current_token.get('oauth_token_secret'),
            rsa_key=rsa_key,
            signature_method='RSA-SHA1'
        )

        try:
            resp = oauth.post(
                ACCESS_URL,
                params={'oauth_session_handle': self.current_token['oauth_session_handle']}
            )
        except Exception as e:
            logging.error("failed to refresh token", e)
            raise DisconnectException()

        self.current_token = _process_token(json_module.loads(resp.text))
        parent = ndb.Key('Org', self.org_uid)
        OrgCredentials(parent=parent, id=self.org_uid, token=self.current_token).put()

    def get_company_name(self):
        """
        Makes an API call to Xero and extracts the company name.

        Returns:
            str: company name
        """

        url = "{}/Organisations".format(XERO_BASE_URI)
        try:
            urlfetch.set_default_fetch_deadline(10)
            data = self.get(url, headers={'Accept': 'application/json'})
        except Exception:
            # we don't want this to interrupt the linking flow
            logging.warning("failed to get company name for org {}".format(self.org_uid), exc_info=True)
            raise FailedToGetCompanyName()
        data = data['Organisations'][0]

        # store ShortCode on first link.
        if self.org.entity_id is None:
            self.org.entity_id = data['ShortCode']
            self.org.put_async()

        return data.get('Name', {})

    def get_short_code(self):
        """
        Makes an API call to Xero and extracts the ShortCode

        Returns:
            str: The Company ShortCode
        """
        url = "{}/Organisations".format(XERO_BASE_URI)
        try:
            urlfetch.set_default_fetch_deadline(10)
            data = self.get(url, headers={'Accept': 'application/json'})
        except Exception:
            # we don't want this to interrupt the linking flow
            logging.warning("failed to get ShortCode for org {}".format(self.org_uid), exc_info=True)
            raise DisconnectException()

        return data['Organisations'][0]['ShortCode']

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

    def request(self, method, url,
            params=None, data=None, headers=None, cookies=None, files=None,
            auth=None, timeout=None, allow_redirects=True, proxies=None,
            hooks=None, stream=None, verify=None, cert=None, json=None):
        """
        Overrides the OAuth1Session request method to handle Xero specific errors. Based on this handling here the parent
        sync loop decides if it should retry API calls.

        Returns:
            dict: data returned by Xero for an api call
        """
        response = super(XeroApiSession, self).request(
            method,
            url,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            files=files,
            auth=auth,
            timeout=timeout,
            allow_redirects=allow_redirects,
            proxies=proxies,
            hooks=hooks,
            stream=stream,
            verify=verify,
            cert=cert,
            json=json
        )

        if response.status_code == 429:
            logging.info("got a 429 - {}".format(response.text))
            raise RateLimitException()

        elif response.status_code == 401:
            raise UnauthorizedApiCallException()

        elif response.status_code == 403:
            raise ForbiddenApiCallException()

        if response.status_code != 200:
            logging.info(u"got response with status: {}, and response: {}".format(response.status_code, response.text))
            raise ValueError("api call failed with code {}: url - {}".format(response.status_code, url))

        data = json_module.loads(response.text)

        return data


def _get_partner_session_attrs(provider_config):
    """
    Method to retrieve additional attributes to be used for the OAuth1Session depending
    on the application type being public or private.

    Public - No RSA key and HMAC-SHA1 (default signature method)
    Partner - RSA key to be used with RSA-SHA1 signature method

    Args:
        provider_config (ProviderConfig): The ProviderConfig containing the auth attributes

    Returns:
        (str, str): The RSA key and Signature Method
    """
    auth_attrs = json_module.loads(provider_config.additional_auth_attributes)

    if auth_attrs['application_type'] == PARTNER:
        return auth_attrs['rsa_key'], RSA
    else:
        return None, HMAC


def _process_token(token):
    """
    Sets the expired_at field on the retrieved access token

    Args:
        token (dict): The access token

    Returns:
        The updated access tocken
    """
    if 'oauth_expires_in' in token:
        expires_at = datetime.utcnow() + timedelta(seconds=int(token['oauth_expires_in']))
        token['expires_at'] = calendar.timegm(expires_at.utctimetuple())

    return token



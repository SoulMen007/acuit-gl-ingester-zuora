"""
Wrappers for Zura Auth sessions (around OAuth2Session, saving/retreiving tokens and other settings from persistent
storage to make it easier to call Zuora APIs).
Note: Currently Zuora uses basic authentication via username/password
"""


import os
import json as json_module
import logging
import calendar
from datetime import datetime, timedelta

from requests import Session, post
from google.appengine.ext import ndb

from app.clients import client_utils
from app.services.ndb_models import Org, OrgCredentials, UserCredentials
from app.utils.sync_utils import (
    LINKING,
    RateLimitException,
    UnauthorizedApiCallException,
    MissingProviderConfigException,
    ForbiddenApiCallException
)

BASE_API_URI = os.environ.get('ZUORA_BASE_API_URI')


class ZuoraAuthorizationSession:
    """
    Class that facilitates first step of the auth flow. Stores org details and gives a URL for user to go to in order
    to complete the authorisation.
    """

    def __init__(self, org_uid, provider_config, redirect_url):
        """
        Prepares the org for linking.

        Args:
            org_uid(str): org identifier
            provider_config(ProviderConfig): ndb model holding the provider config for the org
            redirect_url(str): the url to which the linker should send the user to after saving zuora tokens
        """

        org = Org.get_by_id(org_uid) or Org(id=org_uid, provider='zuora', provider_config=provider_config.key)

        # If this is a `relink`, check the org has a provider_config set
        if org.provider_config is None:
            org.provider_config = provider_config.key

        msg = "setting org status to linking (status {}) and saving redirect_url ({})'"
        logging.info(msg.format(LINKING, redirect_url))

        org.status = LINKING
        org.redirect_url = redirect_url
        org.put()

        self.org = org

    def get_authorization_url(self):
        """
        Returns the url to which the user should be redirected to in order to complete the auth flow.

        Returns:
            str: url to which the user should be redirected to in order to complete the auth flow
        """
        return client_utils.get_redirect_uri_for(self.org.provider, self.org.key.string_id())


class ZuoraTokenSession(Session):
    """Class to facilitate exchange of auth code for access token. Zuora uses a session cookie"""

    def __init__(self, org_uid, username, password):
        """
        Stores the users Zuora credentials into a UserCredentials ndb model
        Args:
            org_uid(str): org identifier
            username(str): zuora username
            password(str) zuora password
        """

        self.org_uid = org_uid
        parent = ndb.Key('Org', org_uid)
        self.user_creds = UserCredentials(parent=parent, id=org_uid, username=username, password=password)
        self.user_creds.put()
        # TODO: Handle errors (File mismatch etc..)

    def get_and_save_token(self):
        """Retrieves a session cookie from Zuora via the user credentials"""
        _get_session_cookie(self.user_creds)


class ZuoraApiSession(Session):
    """
    Class to facilitate making API calls to Zuora.
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

        provider_config_key = org.get_result().provider_config
        if provider_config_key is None:
            logging.warn("org `{}` does not have a provider config.".format(parent.id()))
            raise MissingProviderConfigException()
        else:
            self.provider_config = provider_config_key.get()

        if (expires_at - datetime.utcnow()).total_seconds() < 60:
            logging.info("access token for {} about to expire, refreshing".format(self.org_uid))
            self.refresh_token()
            self.access_token = self.creds.token['access_token']

        super(ZuoraApiSession, self).__init__()

    def refresh_token(self):
        """
        Refreshes the session cookie for the org
        """
        parent = ndb.Key('Org', self.org_uid)
        user_creds = UserCredentials.get_by_id(self.org_uid, parent=parent)

        _get_session_cookie(user_creds)
        self.creds = OrgCredentials.get_by_id(self.org_uid, parent=parent)

    def get_company_name(self):
        """
        Makes an API call to Zuora to get the CompanyName.

        Returns:
            str: company name
        """

        # TODO: Currently no way to fetch company info unless multi-tenant feature is enabled by zuora on the tenant
        return self.org_uid

    def is_authenticated(self):
        """
        Provides on-demand checking of the ability to make API calls for an org.

        Args:
            org_uid(str): org identifier

        Returns:
            bool: true if api calls can be made, false if not
        """

        url = '{}/accounting-codes'.format(BASE_API_URI)

        try:
            api_response = self.get(
                url,
                headers={
                    'Cookie': self.creds.token['access_token'],
                    'Accept': 'application/json'
                },
            )
        except Exception:
            logging.exception("got an error checking if auth is ok")
            return False

        return api_response['success'] is True

    def request(self, method, url,
                params=None, data=None, headers=None, cookies=None, files=None,
                auth=None, timeout=None, allow_redirects=True, proxies=None,
                hooks=None, stream=None, verify=None, cert=None, json=None):

        """
        Overrides the session request method to handle Zuora specific errors. Based on this handling here the parent
        sync loop decides if it should retry API calls. This method also adds the session cookie encapsulated by
        the ApiSession class to each request.

        Returns:
            dict: data returned by zuora for an api call
        """

        # Add session cookie to request
        if not headers:
            headers = {}

        headers['Cookie'] = self.creds.token['access_token']

        response = super(ZuoraApiSession, self).request(
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

def _get_session_cookie(user_creds):
    """ Method to fetch a session cookie from the Zuora API. A session cookies duration time can
    be set by the user. Since there is no way to find out what it has been set to,
    the duration has been set to the minimum (15 minutes). Any cookies which have a duration less
    than this, will be refreshed in the reconnect loop

    Args:
        user_creds(UserCredentials): The users credentials
    """
    session_cookie_url = '{}/connections'.format(BASE_API_URI)
    session_cookie_response = post(
        session_cookie_url,
        headers={
            'apiAccessKeyId': user_creds.username,
            'apiSecretAccessKey': user_creds.password,
            'Accept': 'application/json',
            'content-type': 'application/json'
        }
    )

    if session_cookie_response.status_code == 401:
        raise UnauthorizedApiCallException()

    session_cookie = session_cookie_response.headers.get('set-cookie')
    cookie_expiry = datetime.utcnow() + timedelta(minutes=14)
    cookie_expiry = calendar.timegm(cookie_expiry.utctimetuple())
    token = {'expires_at': cookie_expiry, 'access_token': session_cookie}
    parent = ndb.Key('Org', user_creds.key.id())
    OrgCredentials(parent=parent, id=user_creds.key.id(), token=token).put()

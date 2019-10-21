"""
Tests for the Xero API clients.
"""

import unittest
import json
from mock import patch, Mock

from google.appengine.ext import testbed

from app.clients.xero_client import XeroApiSession
from app.utils.sync_utils import UnauthorizedApiCallException, ForbiddenApiCallException
from app.services.ndb_models import Org, OrgCredentials, ProviderConfig
from app.services.adapter import adapter


class XeroClientTestCase(unittest.TestCase):
    """
    Tests for the Xero API clients.
    """

    def setUp(self):
        """
        Setup GAE testbed.
        """
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_memcache_stub()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_urlfetch_stub()
        self.test_provider_config = ProviderConfig(
                id='xerov2',
                provider="xerov2",
                app_family="local_host_family",
                client_id="test",
                client_secret="fyre",
                additional_auth_attributes=json.dumps({'application_type': 'public'})
            ).put()
        adapter.app.config['TESTING'] = True
        self.app = adapter.app.test_client()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    @patch('app.clients.xero_client.XeroApiSession.refresh_token', Mock())
    @patch('app.clients.xero_client.OAuth1Session', Mock())
    @patch('app.clients.xero_client.OAuth1Session.request')
    def test_request(self, request_mock):
        """
        Tests Xero API request error handling.

        Args:
            request_mock(Mock): mock of the xero api call response
        """
        org = Org(id='test', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'oauth_token': 'token', 'oauth_token_secret': 'secret'}).put()
        session = XeroApiSession('test')

        # successful response data comes through
        request_mock.return_value = Mock(status_code=200, text='{"key": "value"}')
        data = session.get("https://xero")
        self.assertEqual(data, {"key": "value"})

        # 401 response raises a custom exception
        request_mock.return_value = Mock(status_code=401)
        with self.assertRaises(UnauthorizedApiCallException):
            session.get("https://xero")

        request_mock.return_value = Mock(status_code=403)
        with self.assertRaises(ForbiddenApiCallException):
            session.get('https://xero')

        # non 200 and non 401 response raises an exception
        request_mock.return_value = Mock(status_code=500)
        with self.assertRaises(ValueError):
            session.get("https://xero")

    @patch('app.clients.xero_client.XeroApiSession.refresh_token', Mock())
    @patch('app.clients.xero_client.XeroApiSession.get')
    def test_is_authenticated(self, get_mock):
        """
        Tests how Xero client's on-demand auth check.
        """
        org = Org(id='test', provider_config=self.test_provider_config, entity_id='ShortCode').put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'oauth_token': 'token', 'oauth_token_secret': 'secret'}).put()

        # getting CompanyInfo means authenticated
        get_mock.return_value = {'Organisations': [{'Name': 'test'}]}
        xero_session = XeroApiSession('test')

        self.assertTrue(xero_session.is_authenticated())

        # no CompanyInfo means not authenticated
        get_mock.return_value = {'NotCompanyInfo': {}}
        self.assertFalse(xero_session.is_authenticated())

        # an exception means not authenticated
        get_mock.side_effect = UnauthorizedApiCallException()
        self.assertFalse(xero_session.is_authenticated())



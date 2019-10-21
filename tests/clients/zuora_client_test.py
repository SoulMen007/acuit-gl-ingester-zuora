"""
Tests for the Zuora API client.
"""

import unittest
from mock import patch, Mock

from google.appengine.ext import testbed

from app.clients.zuora_client import ZuoraApiSession
from app.utils.sync_utils import UnauthorizedApiCallException, ForbiddenApiCallException
from app.services.ndb_models import Org, OrgCredentials, ProviderConfig
from app.services.adapter import adapter


class ZuoraClientTestCase(unittest.TestCase):
    """
    Tests for the Zuora API client.
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
                id='zuora',
                provider="zuora",
                app_family="local_host_family",
            ).put()
        adapter.app.config['TESTING'] = True
        self.app = adapter.app.test_client()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    @patch('app.clients.zuora_client.ZuoraApiSession.refresh_token', Mock())
    @patch('app.clients.zuora_client.Session', Mock())
    @patch('app.clients.zuora_client.Session.request')
    def test_request(self, request_mock):
        """
        Tests Zuora API request error handling.

        Args:
            request_mock(Mock): mock of the zuora api call response
        """

        org = Org(id='test', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'access_token': 'token', 'oauth_token_secret': 'secret'}).put()
        session = ZuoraApiSession('test')

        # successful response data comes through
        request_mock.return_value = Mock(status_code=200, text='{"key": "value"}')
        data = session.get("https://zuora")
        self.assertEqual(data, {"key": "value"})

        # 401 response raises a custom exception
        request_mock.return_value = Mock(status_code=401)
        with self.assertRaises(UnauthorizedApiCallException):
            session.get("https://zuora")

        request_mock.return_value = Mock(status_code=403)
        with self.assertRaises(ForbiddenApiCallException):
            session.get('https://zuora')

        # non 200 and non 401 response raises an exception
        request_mock.return_value = Mock(status_code=500)
        with self.assertRaises(ValueError):
            session.get("https://zuora")

    @patch('app.clients.zuora_client.ZuoraApiSession.refresh_token', Mock())
    @patch('app.clients.zuora_client.ZuoraApiSession.get')
    def test_is_authenticated(self, get_mock):
        """
        Tests how Zuora client's on-demand auth check.
        """
        org = Org(id='test', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'access_token': 'token'}).put()

        # API endpoint returning success as true means we're authenticated
        get_mock.return_value = {'success': True}
        zuora_session = ZuoraApiSession('test')
        self.assertTrue(zuora_session.is_authenticated())

        # API endpoint returning success as false means not authenticated
        get_mock.return_value = {'success': False}
        self.assertFalse(zuora_session.is_authenticated())

        # an exception means not authenticated
        get_mock.side_effect = UnauthorizedApiCallException()
        self.assertFalse(zuora_session.is_authenticated())



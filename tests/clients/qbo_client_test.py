"""
Tests for the QBO API clients.
"""

import os
import unittest
from mock import patch, Mock

from google.appengine.ext import testbed
from google.appengine.api import taskqueue

from app.clients.qbo_client import QboApiSession
from app.utils.sync_utils import UnauthorizedApiCallException, InvalidGrantException
from app.services.ndb_models import Org, OrgCredentials, ProviderConfig
from app.services.adapter import adapter

class QboClientTestCase(unittest.TestCase):
    """
    Tests for the QBO API clients.
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
            id="qbo",
            provider="qbo",
            app_family="local_host_family",
            client_id="coopers_pale_ale",
            client_secret="ninja_300"
        ).put()

        adapter.app.config['TESTING'] = True
        self.app = adapter.app.test_client()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    @patch('app.clients.qbo_client.QboApiSession.refresh_token', Mock())
    @patch('app.clients.qbo_client.OAuth2Session', Mock())
    @patch('app.clients.qbo_client.OAuth2Session.request')
    def test_request(self, request_mock):
        """
        Tests QBO API request error handling.

        Args:
            request_mock(Mock): mock of the qbo api call response
        """
        org = Org(id='test', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'refresh_token': 'refresh'}).put()
        session = QboApiSession('test')

        # successful response data comes through
        request_mock.return_value = Mock(status_code=200, text='{"key": "value"}')
        data = session.get("https://qbo")
        self.assertEqual(data, {"key": "value"})

        # 401 response raises a custom exception
        request_mock.return_value = Mock(status_code=401)
        with self.assertRaises(UnauthorizedApiCallException):
            session.get("https://qbo")

        # non 200 and non 401 response raises an exception
        request_mock.return_value = Mock(status_code=500)
        with self.assertRaises(ValueError):
            session.get("https://qbo")

        # qbo notifies of some errors with 200 and Fault key in response
        request_mock.return_value = Mock(status_code=200, text='{"Fault": "wrong"}')
        with self.assertRaises(ValueError):
            session.get("https://qbo")

    @patch.dict(os.environ, {'QBO_BASE_API_URI': 'http://qbo', 'QBO_API_MINOR_VERSION': '1'})
    @patch('app.clients.qbo_client.QboApiSession.refresh_token', Mock())
    @patch('app.clients.qbo_client.QboApiSession.get')
    def test_is_authenticated(self, get_mock):
        """
        Tests how QBO client's on-demand auth check.
        """
        org = Org(id='test', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'refresh_token': 'refresh'}).put()

        # getting CompanyInfo means authenticated
        get_mock.return_value = {'CompanyInfo': {'CompanyName': 'jaja'}}
        qbo_session = QboApiSession('test')

        self.assertTrue(qbo_session.is_authenticated())

        # no CompanyInfo means not authenticated
        get_mock.return_value = {'NotCompanyInfo': {}}
        self.assertFalse(qbo_session.is_authenticated())

        # an exception means not authenticated
        get_mock.side_effect = UnauthorizedApiCallException()
        self.assertFalse(qbo_session.is_authenticated())

    @patch.dict(os.environ, {'QBO_BASE_API_URI': 'http://qbo', 'QBO_API_MINOR_VERSION': '1'})
    @patch('app.clients.qbo_client.QboApiSession.__init__', Mock(side_effect=InvalidGrantException()))
    @patch('app.services.adapter.adapter.sync_utils.mark_as_disconnected')
    def test_is_authenticated_invalid_grant(self, disconnected_mock):
        """
        Verifies that the InvalidGrantException in the long term reconnect loop does not throw an exception, but is
        interpreted as a disconnection.
        """
        org = Org(id='test', provider='qbo', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'refresh_token': 'refresh'}).put()

        response = self.app.post('/adapter/test/reconnect', headers={'X-AppEngine-TaskExecutionCount': 10})

        # InvalidGrantException should be treated as a disconnection, and no exception should be thrown
        self.assertEqual(response.status_code, 423)
        disconnected_mock.assert_not_called()

    @patch.dict(os.environ, {'QBO_BASE_API_URI': 'http://qbo', 'QBO_API_MINOR_VERSION': '1'})
    @patch('app.clients.qbo_client.QboApiSession.refresh_token', Mock())
    @patch('app.clients.qbo_client.OAuth2Session.request')
    def test_non_ascii_response(self, request_mock):
        """
        Ensures that the client can handle non-ascii response body (can break due to logging for example).

        Args:
            request_mock(Mock): a mock of the response
        """
        # setup an org
        org = Org(id='test', provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'refresh_token': 'refresh'}).put()

        # non-200 and non-ascii response
        request_mock.return_value = Mock(status_code=400, text=u'te\xa0st')

        # there should be no exception
        session = QboApiSession('test')
        with self.assertRaises(ValueError):
            session.request('GET', 'http://testurl.com')

        # 200 and non-ascii response
        request_mock.return_value = Mock(status_code=200, text=u'{"value": "te\xa0st"}')

        # there should be no exception
        session = QboApiSession('test')
        self.assertDictEqual(
            session.request('GET', 'http://testurl.com'),
            {"value": u"te\xa0st"}
        )

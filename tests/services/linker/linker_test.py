"""
Tests for the linker service.
"""

import os
import unittest
from mock import patch, Mock, call
from datetime import datetime
import json
from google.appengine.ext import testbed
import app.clients.client_utils as utils

from app.services.linker import linker
from app.utils.sync_utils import LINKING, CONNECTED, DISCONNECTED
from app.services.ndb_models import Org, OrgCredentials
from app.services.ndb_models import ProviderConfig

class LinkerTestCase(unittest.TestCase):
    """
    Tests for the linker service.
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

        linker.app.config['TESTING'] = True
        self.app = linker.app.test_client()
        self.provider_configs = {
            'qbo': ProviderConfig(
                id="qbo",
                provider="qbo",
                app_family="local_host_family",
                client_id="coopers_pale_ale",
                client_secret="ninja_300"
            ).put(),

            'xerov2': ProviderConfig(
                id='xerov2',
                provider="xerov2",
                app_family="local_host_family",
                client_id="test",
                client_secret="fyre",
                additional_auth_attributes=json.dumps({'application_type': 'public'})
            ).put(),

            'zuora': ProviderConfig(
                id='zuora',
                provider='zuora',
                app_family='local_host_family'
            ).put()
        }

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    @patch('app.services.linker.linker.publish_status')
    @patch('app.clients.qbo_client.QboAuthorizationSession.get_authorization_url', Mock(return_value="http://qbo"))
    def test_connect(self, publish_mock):
        """
        Tests the first step of the oauth flow authorisation.
        """

        response = self.app.post('/linker/qbo/test/connect?redirect_url=http://app&app_family=local_host_family')
        self.assertEqual(response.status_code, 302)

        # the user is redirected to the provider
        self.assertEqual(response.location, "http://qbo")

        # org is linking and status is published on pubsub
        self.assertEqual(Org.get_by_id('test').status, LINKING)

        # app redirect url is saved
        self.assertEqual(Org.get_by_id('test').redirect_url, "http://app")

    @patch('app.clients.zuora_client.ZuoraApiSession.refresh_token', Mock())
    @patch('app.clients.zuora_client.ZuoraApiSession.get_company_name', Mock(return_value='ACUIT'))
    @patch('app.services.linker.linker.publish_status')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.clients.zuora_client.ZuoraTokenSession.get_and_save_token')
    @patch('app.services.linker.linker.init_update')
    def test_basic_auth(self, init_update_mock, save_token_mock, connected_mock, publish_mock):
        """
        Tests username/password auth flow
        """

        org = Org(id='test', redirect_url="http://app", provider_config=self.provider_configs['zuora']).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'access_token': 'blah'}).put()
        response = self.app.post(
            '/linker/handle_login',
            data={
                'username': 'dont do dis',
                'password': 'noOneWillSeeThis',
                'provider': 'zuora',
                'org_uid': 'test'
            },
            content_type='application/x-www-form-urlencoded'
        )

        self.assertEqual(response.status_code, 302)

        # the user is redirected to the provider
        self.assertEqual(response.location, "http://app?data_source_name=ACUIT")

        # token is saved
        save_token_mock.assert_called_once()

        # and then org is connected (this publishes status as connected as well)
        connected_mock.assert_called_once()

        # and the initial sync has been kicked off
        init_update_mock.assert_called_once()

    @patch('app.clients.zuora_client.ZuoraApiSession.refresh_token', Mock())
    @patch('app.clients.zuora_client.ZuoraApiSession.get_company_name', Mock(return_value='ACUIT'))
    @patch('app.services.linker.linker.publish_status')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.clients.zuora_client.ZuoraTokenSession.get_and_save_token')
    @patch('app.services.linker.linker.init_update')
    def test_basic_auth_creds_provided_by_apigee(self, init_update_mock, save_token_mock, connected_mock, publish_mock):
        """
        Verifies that linking works correctly when user credentials are supplied from apigee via
        the connect endpoint
        """
        org = Org(provider='zuora', id='test', redirect_url="http://app", provider_config=self.provider_configs['zuora']).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'access_token': 'blah'}).put()

        response = self.app.post(
            '/linker/zuora/test/connect?redirect_url=http://app&app_family=local_host_family',
            json={
                'username': 'no',
                'password': 'lights'
            },
            content_type='application/json'
         )
        self.assertEqual(response.status_code, 302)

        # the user is redirected to the provider
        self.assertEqual(
            response.location,
            'http://app?data_source_name=ACUIT'
        )

        # org is linking and status is published on pubsub
        self.assertEqual(Org.get_by_id('test').status, LINKING)

        # app redirect url is saved
        self.assertEqual(Org.get_by_id('test').redirect_url, "http://app")

        # token is saved
        save_token_mock.assert_called_once()

        # and then org is connected (this publishes status as connected as well)
        connected_mock.assert_called_once()

        # and the initial sync has been kicked off
        init_update_mock.assert_called_once()

    @patch('app.clients.xero_client.XeroApiSession.refresh_token', Mock())
    @patch('app.clients.xero_client.XeroApiSession.get_company_name', Mock(return_value='ACUIT'))
    @patch('app.services.linker.linker.publish_status')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.clients.xero_client.XeroTokenSession.get_and_save_token')
    @patch('app.services.linker.linker.init_update')
    def test_oauth1(self, init_update_mock, save_token_mock, connected_mock, publish_mock):
        """
        Tests oauth1 token session flow
        """

        org = Org(id='test', redirect_url="http://app", provider_config=self.provider_configs['xerov2']).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0, 'oauth_token': 'blah', 'oauth_token_secret': 'doggo'}).put()
        response = self.app.get('/linker/test/oauth?oauth_verifier=123&oauth_token=blah')
        self.assertEqual(response.status_code, 302)

        # the user is redirected to the provider
        self.assertEqual(response.location, "http://app?data_source_name=ACUIT")

        # token is saved
        save_token_mock.assert_called_once()

        # and then org is connected (this publishes status as connected as well)
        connected_mock.assert_called_once()

        # and the initial sync has been kicked off
        init_update_mock.assert_called_once()

    @patch('app.clients.qbo_client.QboApiSession.refresh_token', Mock())
    @patch('app.clients.qbo_client.QboApiSession.get_company_name', Mock(return_value='ACUIT'))
    @patch('app.services.linker.linker.publish_status')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.clients.qbo_client.QboTokenSession.get_and_save_token')
    @patch('app.services.linker.linker.init_update')
    def test_oauth2(self, init_update_mock, save_token_mock, connected_mock, publish_mock):
        """
        Tests the first step of the oauth flow authorisation.
        """
        org = Org(id='test', redirect_url="http://app", provider_config=self.provider_configs['qbo']).put()
        OrgCredentials(id='test', parent=org, token={'expires_at': 0}).put()
        response = self.app.get('/linker/oauth?state=test')
        self.assertEqual(response.status_code, 302)

        # the user is redirected to the provider
        self.assertEqual(response.location, "http://app?data_source_name=ACUIT")

        # token is saved
        save_token_mock.assert_called_once()

        # and then org is connected (this publishes status as connected as well)
        connected_mock.assert_called_once()

        # and the initial sync has been kicked off
        init_update_mock.assert_called_once()

    @patch('app.services.linker.linker.mark_as_disconnected')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.services.linker.linker.publish_status', Mock())
    def test_mismatching_qbo_file(self, connected_mock, disconnected_mock):
        """
        Verifies that an org can't be reconnected to a different provider file (and that the redirect url can be a
        complex url, ie. can possibly carry app state and error handling appends error message to the redirect url).
        """
        Org(id='test', redirect_url="http://app?app_state=blah", entity_id='1', provider_config=self.provider_configs['qbo']).put()
        response = self.app.get('/linker/oauth?state=test&realmId=2')

        # user is redirected to the app with an error message
        self.assertEqual(response.status_code, 302)
        connected_mock.assert_not_called()
        disconnected_mock.assert_called_once()
        self.assertEqual(
            response.location,
            "http://app?app_state=blah&error_code=source_mismatch"
        )

    @patch('app.services.linker.linker.publish_status', Mock())
    @patch('app.services.linker.linker.mark_as_disconnected')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.clients.xero_client.XeroApiSession.get_short_code', Mock(return_value='vlg_wont_stop'))
    @patch('app.clients.xero_client.XeroTokenSession.fetch_access_token')
    def test_mismatching_xero_file(self, fetch_token_mock, connected_mock, disconnected_mock):
        """
        Verifies that a XeroOrg cannot be reconnected to a different file than its own. (i.e via mismatching ShortCodes)

        Args:
            fetch_token_mock (MagicMock): fetch_access_token mock
        """

        token = {'expires_at': 117, 'oauth_token': 'blah', 'oauth_token_secret': 'secret'}
        fetch_token_mock.return_value = token

        org = Org(id='test', redirect_url="http://app?app_state=blah", entity_id='vlg_pls_stop', provider_config=self.provider_configs['xerov2']).put()
        OrgCredentials(id='test', parent=org, token=token).put()

        response = self.app.get('/linker/test/oauth?oauth_verifier=123&oauth_token=blah')

        # user is redirected to the app with an error message
        self.assertEqual(response.status_code, 302)
        connected_mock.assert_not_called()
        disconnected_mock.assert_called_once()
        self.assertEqual(
            response.location,
            "http://app?app_state=blah&error_code=source_mismatch"
        )

    @patch('app.services.linker.linker.mark_as_disconnected')
    @patch('app.services.linker.linker.mark_as_connected')
    @patch('app.services.linker.linker.publish_status', Mock())
    def test_auth_cancelled(self, connected_mock, disconnected_mock):
        """
        Verifies that an AuthCancelled exception is exposed as 'cancelled' error code to the calling app.

        Args:
            disconnected_mock(Mock): mock of the function which marks an org disconnected
            publish_mock(Mock): mock of the function which publishes org status on pubsub
        """
        Org(id='test', redirect_url="http://app?app_state=test", provider_config=self.provider_configs['qbo']).put()
        response = self.app.get('/linker/oauth?state=test&error=access_denied')

        # user is redirected to the app with an error message
        self.assertEqual(response.status_code, 302)
        disconnected_mock.assert_called_once()
        connected_mock.assert_not_called()
        self.assertEqual(
            response.location,
            "http://app?app_state=test&error_code=cancelled"
        )

    def test_invalid_provider_connect(self):
        """
        Verifies that an invalid provider can't be used in the connect flow.
        """
        response = self.app.post('/linker/blah/test/connect?redirect_url=http://app&app_family=qbo_family')
        self.assertEqual(response.status_code, 404)

    @patch('app.utils.sync_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    @patch('app.utils.sync_utils.publish_status')
    def test_manual_provider_connection(self, publish_mock):
        """
        Verifies that an org with a manual provider can be connected.

        Args:
            publish_mock(Mock): mock of the function which publishes org status on pubsub
        """
        response = self.app.post('/linker/uploader/test/connect')

        # response is ok
        self.assertEqual(response.status_code, 204)

        # org properties are correct
        org = Org.get_by_id('test')
        self.assertEqual(org.provider, 'uploader')
        self.assertEqual(org.status, CONNECTED)
        self.assertEqual(org.linked_at, datetime(2010, 1, 1))
        self.assertEqual(org.connected_at, datetime(2010, 1, 1))

        # linked and connected statuses have been published on pubsub
        publish_mock.assert_has_calls([
            call('test', 'link_status', 'linked'),
            call('test', 'connection_status', 'connected')
        ])

    @patch('app.utils.sync_utils.publish_status')
    def test_disconnect(self, publish_mock):
        """
        Tests the explicit disconnection of an org when connected or already disconnected.
        """
        Org(id='test', status=CONNECTED).put()

        response = self.app.post('/linker/qbo/test/disconnect')
        self.assertEqual(response.status_code, 204)

        # org is disconnected
        self.assertEqual(Org.get_by_id('test').status, DISCONNECTED)

        # linked and connected statuses have been published on pubsub
        publish_mock.assert_has_calls([
            call('test', 'link_status', 'unlinked'),
            call('test', 'connection_status', 'disconnected')
        ])

        response = self.app.post('/linker/qbo/test/disconnect')

        self.assertEqual(response.status_code, 204)

    def test_no_provider_config(self):
        """
        Tests attempting to connect to an app family which does not have a provider config setup
        """
        response = self.app.post('/linker/qbo/test/connect?redirect_url=http://app&app_family=yeah_nah')
        self.assertEqual(response.status_code, 422)

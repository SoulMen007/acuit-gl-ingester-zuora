"""
Tests for the adapter service.
"""

import os
import unittest
import json
from datetime import datetime
from mock import patch, Mock

from google.appengine.ext import testbed
from google.appengine.api import taskqueue

from app.utils.sync_utils import (
    UnauthorizedApiCallException,
    MissingProviderConfigException,
    InvalidGrantException,
    RateLimitException,
    CONNECTED,
    DISCONNECTED
)
from app.services.adapter import adapter
from app.services.ndb_models import Org, OrgCredentials, OrgChangeset, ProviderConfig

class AdapterTestCase(unittest.TestCase):
    """
    Tests for the adapter service.
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

        root_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.testbed.init_taskqueue_stub(root_path=root_path + '/..')
        self.taskqueue = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)
        self.provider_configs = {
            'qbo': ProviderConfig(
                id='qbo',
                provider='qbo',
                app_family='local_host_family',
                client_id='coopers_pale_ale',
                client_secret='ninja_300'
            ).put()
        }

        adapter.app.config['TESTING'] = True
        self.app = adapter.app.test_client()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    def create_org(self, provider='qbo', status=CONNECTED, set_provider_config=True):
        """
        Utility method to create a dummy org.

        Args:
            provider(str): The provider of the org
            status(int): connection of the dummy org
            set_provider_config (bool): Whether to set the provider config
        """

        if set_provider_config:
            provider_config = self.provider_configs[provider]
        else:
            provider_config = None

        org = Org(provider=provider, id='test', status=status, provider_config=provider_config).put()

        OrgCredentials(id='test', parent=org, token={'expires_at': 0}).put()

    def test_status_endpoint(self):
        """
        A few test cases for the status endpoint.
        """
        Org(id='test1').put()
        response = self.app.get('/adapter/test1/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['connected'], False)
        self.assertEqual(response.json['synced'], False)
        self.assertEqual(response.json['updating'], False)
        self.assertEqual(response.json['synced_at'], None)

        Org(id='test2', status=2).put()
        response = self.app.get('/adapter/test2/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['connected'], True)

        Org(id='test3', status=2).put()
        OrgChangeset(org_uid='test3', publish_job_finished=True, publish_job_failed=False).put()
        response = self.app.get('/adapter/test3/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['synced'], True)

    @patch('app.sync_states.qbo.stages.AccountBalanceReportStage.next', Mock(return_value=(True, {})))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(return_value={}))
    def test_update_loop(self):
        """
        Tests that adapter schedules an update task until the sync is done. Mocks AccountBalanceReportStage because it
        attemps to fetch balances from the API.
        """
        self.create_org(provider='qbo')
        old_task_count = 0

        while True:
            update_call = self.app.post('/adapter/qbo/test/update')
            self.assertEqual(update_call.status_code, 204)

            new_task_count = len(self.taskqueue.get_filtered_tasks())

            if new_task_count == old_task_count:
                break

            if new_task_count > 100:
                self.fail("too many adapter calls, infinite loop maybe???")

            old_task_count = new_task_count

        self.assertEqual(new_task_count, 20)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(side_effect=UnauthorizedApiCallException))
    @patch('app.services.adapter.adapter.sync_utils.mark_as_disconnected')
    def test_disconnect_loop_auth_issue(self, disconnected_mock):
        """
        Tests that an org is disconnected after a repeated auth issues from the API.

        Args:
            disconnected_mock(Mock): disconnected handler function mock
        """
        self.create_org(status=CONNECTED)

        # no status change on the first task call
        self.app.post('/adapter/qbo/test/update', headers={'X-AppEngine-TaskExecutionCount': 1})
        disconnected_mock.assert_not_called()

        # org is disconnected on the 4th task call
        self.app.post('/adapter/qbo/test/update', headers={'X-AppEngine-TaskExecutionCount': 4})
        disconnected_mock.assert_called_once()

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(side_effect=InvalidGrantException))
    @patch('app.services.adapter.adapter.sync_utils.mark_as_disconnected')
    def test_disconnect_loop_invalid_grant(self, disconnected_mock):
        """
        Tests that an org is disconnected after a repeated auth issues from the API.

        Args:
            disconnected_mock(Mock): disconnected handler function mock
        """
        self.create_org(status=CONNECTED)

        # no status change on the first task call
        self.app.post('/adapter/qbo/test/update', headers={'X-AppEngine-TaskExecutionCount': 1})
        disconnected_mock.assert_not_called()

        # org is disconnected on the 4th task call
        self.app.post('/adapter/qbo/test/update', headers={'X-AppEngine-TaskExecutionCount': 4})
        disconnected_mock.assert_called_once()

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(return_value={}))
    @patch('app.services.adapter.adapter.sync_utils.init_update')
    @patch('app.services.adapter.adapter.sync_utils.mark_as_connected')
    @patch('app.clients.qbo_client.QboApiSession.is_authenticated')
    def test_reconnect_loop(self, auth_mock, connected_mock, init_update_mock):
        """
        Tests that the long term reconnect loop will reconnect an org (this endpoint is called by the same task).

        Args:
            auth_mock(Mock): mock of the function which checks for successful api call
            connected_mock(Mock): connected handler function mock
            init_update_mock(Mock): mock of the function to start org sync
        """

        # an unsuccesful api call should not reconnect, but do not resolve the task so reconnect gets tried again
        auth_mock.return_value = False
        self.create_org(status=DISCONNECTED)
        response = self.app.post('/adapter/test/reconnect', headers={'X-AppEngine-TaskExecutionCount': 10})
        self.assertEqual(response.status_code, 423)
        connected_mock.assert_not_called()
        init_update_mock.assert_not_called()

        # stop trying after a while (resolve the task)
        response = self.app.post('/adapter/test/reconnect', headers={'X-AppEngine-TaskExecutionCount': 43})
        self.assertEqual(response.status_code, 204)
        connected_mock.assert_not_called()
        init_update_mock.assert_not_called()

        # if api call works reconnect the org
        auth_mock.return_value = True
        response = self.app.post('/adapter/test/reconnect', headers={'X-AppEngine-TaskExecutionCount': 10})
        self.assertEqual(response.status_code, 204)
        connected_mock.assert_called_once()
        init_update_mock.assert_called_once()

        # an already connected org will get ignored
        connected_mock.reset_mock()
        init_update_mock.reset_mock()
        self.create_org(status=CONNECTED)
        response = self.app.post('/adapter/test/reconnect', headers={'X-AppEngine-TaskExecutionCount': 10})
        self.assertEqual(response.status_code, 204)
        connected_mock.assert_not_called()
        init_update_mock.assert_not_called()

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(side_effect=RateLimitException()))
    def test_rate_limit_handling(self):
        """
        Verifies that the adapter doesn't throw a 500 when the underlying API call is rate limited.
        """
        self.create_org(status=CONNECTED)
        response = self.app.post('/adapter/qbo/test/update')

        # 500 should not be returned by the adapter
        self.assertEqual(response.status_code, 429)

    @patch('app.services.adapter.adapter.sync_utils.init_update')
    @patch('app.services.adapter.adapter.sync_utils.mark_as_connected')
    def test_reconnect_on_org_with_no_config(self, connected_mock, init_update_mock):
        """
        Checks that the reconnect loop correctly handles orgs with missing ProviderConfigs

        Args:
            connected_mock(Mock): connected handler function mock
            init_update_mock(Mock): mock of the function to start org sync
        """

        os.environ['QBO_BASE_API_URI'] = 'test'
        os.environ['QBO_API_MINOR_VERSION'] = 'test'

        self.create_org(status=DISCONNECTED, set_provider_config=False)
        response = self.app.post('/adapter/test/reconnect', headers={'X-AppEngine-TaskExecutionCount': 10})
        self.assertEqual(response.status_code, 423)
        connected_mock.assert_not_called()
        init_update_mock.assert_not_called()

    @patch('app.sync_states.qbo.stages.AccountBalanceReportStage.next', Mock(return_value=(True, {})))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(return_value={}))
    @patch('app.services.adapter.adapter.sync_utils.mark_as_disconnected')
    def test_update_missing_provider_exception_handling(self, disconnected_mock):
        """
        Runs an update loop for an org with no ProviderConfig reference.
        This verifies that the MissingProviderConfigException is handled correctly.

        Args:
            disconnected_mock(Mock): disconnected handler function mock
        """

        # Check that a retry loop is triggered
        self.create_org(set_provider_config=False)
        retry_count = 0
        update_response = self.app.post('/adapter/qbo/test/update', headers={'X-AppEngine-TaskExecutionCount': retry_count})
        self.assertEqual(update_response.status_code, 503)
        disconnected_mock.assert_not_called()

        # Check that a reconnect loop is triggered when retry count > 3
        retry_count = 4
        update_response = self.app.post('/adapter/qbo/test/update', headers={'X-AppEngine-TaskExecutionCount': retry_count})
        self.assertEqual(update_response.status_code, 204)
        disconnected_mock.assert_called_once()


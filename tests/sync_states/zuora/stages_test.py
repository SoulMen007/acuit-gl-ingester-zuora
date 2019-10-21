import unittest
from mock import patch, Mock
from google.appengine.ext import testbed

from app.sync_states.zuora.ndb_models import ZuoraSyncData
from app.utils.sync_utils import CONNECTED
from app.sync_states.zuora.stages import ListApiStage, QUERY_MORE_URI
from app.services.ndb_models import Org, OrgCredentials, Item, ProviderConfig
from datetime import timedelta, datetime

LIST_API_STAGE = 0
INVOICE_ENDPOINT_INDEX = 0
INVOICE_ENDPOINT_NAME = 'Invoice'


class BaseTestCase(unittest.TestCase):
    """
    Base class for Zuora sync stage tests (holds some common utils for test setup).
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
            id="zuora",
            provider="zuora",
            app_family="local_host_family",
            client_id="vlg",
            client_secret="ninja_300"
        ).put()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    def create_org(self, status=CONNECTED, changeset=-1):
        """
        Utility method to create a dummy org.

        Args:
            status(int): connection of the dummy org
        """
        org = Org(id='test', status=status, changeset=changeset, provider_config=self.test_provider_config).put()
        OrgCredentials(id='test', parent=org, token={'access_token': 'hallo', 'expires_at': 0}).put()

    @staticmethod
    def post_mock_api_response(endpoint, how_many=1, more_pages=False):
        """
        Utility method to create a sample response from Zuora API for an endpoint.

        Args:
            endpoint(str): endpoint the mock response should be created for

        Returns:
            dict: mock response
        """

        starting_date = datetime(2000, 1, 1, 0, 0, 0)
        time_format = '%Y-%m-%dT%H:%M:%S.%f-07:00'

        response = {
            'size': '{}'.format(how_many),
            'done': '{}'.format(more_pages),
            'records': [
                {
                    'Id': '{}_{}'.format(endpoint, item),
                    'UpdatedDate': (starting_date + timedelta(days=item)).strftime(time_format)
                } for item in range(0, how_many)
            ]
        }

        if more_pages:
            response['queryLocator'] = 'cursor'

        return response

    @staticmethod
    def count_items():
        """
        Utility method which returns the number of items in Item datastore kind.

        Returns:
            int: the number of items in Item datastore kind
        """
        return len(Item.query().fetch(keys_only=True))


class ListApiStageTestCase(BaseTestCase):

    @patch('app.sync_states.zuora.stages.ZuoraApiSession.refresh_token', Mock())
    @patch('app.sync_states.zuora.stages.ZuoraApiSession.post')
    def test_endpoint_complete(self, post_mock):
        """
        Verifies that once an endpoint returns less data than requested, the sync moves onto the next endpoint.

        Args:
            post_mock(Mock): mock of the api post function
        """
        post_mock.return_value = self.post_mock_api_response(INVOICE_ENDPOINT_NAME, 50)
        self.create_org(status=CONNECTED)

        # set sync state so that the next pull will be invoice
        ZuoraSyncData(id='test', stage_index=LIST_API_STAGE, endpoint_index=INVOICE_ENDPOINT_INDEX).put()

        # run the sync
        stage = ListApiStage('test')
        stage.next(payload={})

        # one item should have been stored in Item
        self.assertEqual(self.count_items(), 50)

        # and start position should be reset but the endpoint_index should be increased
        sync_data = ZuoraSyncData.get_by_id('test')
        self.assertEqual(sync_data.cursor, None)
        self.assertEqual(sync_data.endpoint_index, INVOICE_ENDPOINT_INDEX + 1)

    @patch('app.sync_states.zuora.stages.ZuoraApiSession.refresh_token', Mock())
    @patch('app.sync_states.zuora.stages.ZuoraApiSession.post')
    def test_multiple_pages(self, post_mock):
        """
        Verifies that once an endpoint which returns 100 items they are saved and sync fetches the next page of the same
        endpoint.

        Args:
            post_mock(Mock): mock of the api post function
        """
        post_mock.return_value = self.post_mock_api_response(INVOICE_ENDPOINT_NAME, 100, True)
        self.create_org(status=CONNECTED)

        # set sync state so that the next pull will be invoice
        ZuoraSyncData(
            id='test',
            stage_index=LIST_API_STAGE,
            endpoint_index=INVOICE_ENDPOINT_INDEX,
        ).put()

        # run the sync
        stage = ListApiStage('test')
        complete, new_payload = stage.next(payload={})

        # all items should have been stored in Item
        self.assertEqual(self.count_items(), 100)

        # and start position should be shifted but the endpoint_index should stay the same
        sync_data = ZuoraSyncData.get_by_id('test')
        self.assertEqual(sync_data.cursor, 'cursor')
        self.assertEqual(sync_data.endpoint_index, INVOICE_ENDPOINT_INDEX)

        post_mock.reset_mock(return_value=True)
        post_mock.return_value = self.post_mock_api_response(INVOICE_ENDPOINT_NAME, 100, False)

        # Run the next stage with the new payload
        stage.next(payload=new_payload)

        # Check that `queryMore` endpoint is called with the queryLocator returned from the previous call
        post_mock.assert_called_once_with(
            QUERY_MORE_URI,
            json={'queryLocator': 'cursor'}
        )


    @patch('app.sync_states.zuora.stages.ZuoraApiSession.refresh_token', Mock())
    @patch('app.sync_states.zuora.stages.ZuoraApiSession.post')
    def test_get_max_updated_at(self, post_mock):
        """
        Checks that the max_updated_at field is calculated correctly and assigned to the marker for that endpoint
        at the end of the sync cycle

        Args:
            post_mock(Mock): mock of the api post function
        """

        post_mock.return_value = self.post_mock_api_response(INVOICE_ENDPOINT_NAME, 10, False)
        self.create_org(status=CONNECTED)

        ZuoraSyncData(
            id='test',
            stage_index=LIST_API_STAGE,
            endpoint_index=INVOICE_ENDPOINT_INDEX,
        ).put()

        # run the sync
        stage = ListApiStage('test')
        stage.next(payload={})

        # all items should have been stored in Item
        self.assertEqual(self.count_items(), 10)
        sync_data = ZuoraSyncData.get_by_id('test')

        # Check the marker for the endpoint is set to the correct date
        self.assertEqual(sync_data.markers[INVOICE_ENDPOINT_INDEX], '2000-01-10T00:00:00.000000-07:00')

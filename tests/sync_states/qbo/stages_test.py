"""
Tests for the QBO sync implementation (tests various stages of the sync process).
"""

import unittest
from mock import patch, Mock
import json
from datetime import datetime, date, timedelta

from google.appengine.ext import testbed
from google.appengine.api import taskqueue

from app.utils.sync_utils import CONNECTED
from app.sync_states.qbo.stages import ListApiStage, MissingItemsStage, JournalReportStage, AccountBalanceReportStage
from app.services.ndb_models import Org, OrgCredentials, Item, MissingItem, ProviderConfig
from app.sync_states.qbo.ndb_models import QboSyncData

LIST_API_STAGE = 1
ACCOUNT_ENDPOINT_NAME = 'Account'
COMPANY_INFO_ENDPOINT_NAME = 'CompanyInfo'
COMPANY_INFO_ENDPOINT_INDEX = 0
INVOICE_ENDPOINT_NAME = 'Invoice'
INVOICE_ENDPOINT_INDEX = 8


class BaseTestCase(unittest.TestCase):
    """
    Base class for QBO sync stage tests (holds some common utils for test setup).
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
        OrgCredentials(id='test', parent=org, token={'expires_at': 0}).put()

    @staticmethod
    def get_mock_api_response(endpoint, how_many=1):
        """
        Utility method to create a sample response from QBO API for an endpoint.

        Args:
            endpoint(str): endpoint the mock response should be created for

        Returns:
            dict: mock response
        """
        return {
            'QueryResponse': {
                endpoint: [{
                    'Id': '{}'.format(item),
                    'Name': '{} Item {}'.format(endpoint, item),
                    'TxnDate': '2000-01-01',
                    'Country': 'AU',
                    'MetaData': {
                        'LastUpdatedTime': '2000-01-01'
                    }
                } for item in range(0, how_many)]
            }
        }

    @staticmethod
    def count_items():
        """
        Utility method which returns the number of items in Item datastore kind.

        Returns:
            int: the number of items in Item datastore kind
        """
        return len(Item.query().fetch(keys_only=True))

    @staticmethod
    def count_missing_items():
        """
        Utility method which returns the number of items in MissingItem datastore kind.

        Returns:
            int: the number of items in Item datastore kind
        """
        return len(MissingItem.query().fetch(keys_only=True))


class ListApiStageTestCase(BaseTestCase):
    """
    Tests for the list API pull stage of the sync.
    """

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_endpoint_complete(self, get_mock):
        """
        Verifies that once an endpoint returns less data than requested, the sync moves onto the next endpoint.

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(INVOICE_ENDPOINT_NAME, 50)
        self.create_org(status=CONNECTED)

        # set sync state so that the next pull will be invoice
        QboSyncData(id='test', stage_index=LIST_API_STAGE, endpoint_index=INVOICE_ENDPOINT_INDEX).put()

        # run the sync
        stage = ListApiStage('test')
        stage.next(payload={})

        # one item should have been stored in Item
        self.assertEqual(self.count_items(), 50)

        # and start position should be reset but the endpoint_index should be increased
        sync_data = QboSyncData.get_by_id('test')
        self.assertEqual(sync_data.start_position, 1)
        self.assertEqual(sync_data.endpoint_index, INVOICE_ENDPOINT_INDEX + 1)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_multiple_pages(self, get_mock):
        """
        Verifies that once an endpoint which returns 100 items they are saved and sync fetches the next page of the same
        endpoint.

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(INVOICE_ENDPOINT_NAME, 100)
        self.create_org(status=CONNECTED)

        # set sync state so that the next pull will be invoice
        QboSyncData(
            id='test',
            stage_index=LIST_API_STAGE,
            endpoint_index=INVOICE_ENDPOINT_INDEX,
            start_position=1
        ).put()

        # run the sync
        stage = ListApiStage('test')
        stage.next(payload={})

        # all items should have been stored in Item
        self.assertEqual(self.count_items(), 100)

        # and start position should be shifted but the endpoint_index should stay the same
        sync_data = QboSyncData.get_by_id('test')
        self.assertEqual(sync_data.start_position, 101)
        self.assertEqual(sync_data.endpoint_index, INVOICE_ENDPOINT_INDEX)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_company_info_deduplication(self, get_mock):
        """
        Verifies that company info is not written to Item if it has not been changed since the last pull (qbo ignores
        LastUpdatedTime filter on this endpoint).

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(COMPANY_INFO_ENDPOINT_NAME)
        self.create_org(status=CONNECTED)

        # set sync state so that the next pull will be company info
        QboSyncData(id='test', stage_index=LIST_API_STAGE, endpoint_index=COMPANY_INFO_ENDPOINT_INDEX).put()

        # run the sync
        stage = ListApiStage('test')
        stage.next(payload={})

        # one item should have been stored in Item
        self.assertEqual(self.count_items(), 1)

        # now sync again
        QboSyncData(id='test', stage_index=LIST_API_STAGE, endpoint_index=COMPANY_INFO_ENDPOINT_INDEX).put()
        stage = ListApiStage('test')
        stage.next(payload={})

        # and there should be no additional rows despite the api returning company info again (because it is the same)
        self.assertEqual(self.count_items(), 1)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_country_extraction(self, get_mock):
        """
        Verifies that the file country is saved from the company info endpoint.

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(COMPANY_INFO_ENDPOINT_NAME)
        self.create_org(status=CONNECTED)

        # set sync state so that the next pull will be company info
        QboSyncData(id='test', stage_index=LIST_API_STAGE, endpoint_index=COMPANY_INFO_ENDPOINT_INDEX).put()

        # run the sync
        stage = ListApiStage('test')
        stage.next(payload={})

        # the country should be saved
        self.assertEqual(Org.get_by_id('test').country, 'AU')


class MissingItemsStageTestCase(BaseTestCase):
    """
    Tests for the missing item resolution stage of the sync.
    """

    def test_no_missing_items(self):
        """
        Verifies that if no missing items are found the stage is marked as completed.
        """
        self.create_org(status=CONNECTED)
        stage = MissingItemsStage('test')
        complete, _ = stage.next(payload={})
        self.assertTrue(complete)

    def test_missing_found_in_item(self):
        """
        Verifies that a missing item can be resolved from the Item.
        """
        self.create_org(status=CONNECTED)
        stage = MissingItemsStage('test')
        MissingItem(org_uid='test', missing_items=[{'type': 'Account', 'id': '1'}]).put()
        Item(org_uid='test', changeset=-1, endpoint='Account', item_id='1', data={'Id': '1'}).put()
        stage.next(payload={})

        # the missing item should be deleted and resolved item should added Item ready for next publish
        self.assertEqual(self.count_missing_items(), 0)
        self.assertEqual(self.count_items(), 2)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_missing_not_found_in_item(self, get_mock):
        """
        Verifies that if the missing item is not found in Item it will be retrieved from the api

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(ACCOUNT_ENDPOINT_NAME)
        self.create_org(status=CONNECTED)
        stage = MissingItemsStage('test')
        MissingItem(org_uid='test', missing_items=[{'type': 'Account', 'id': '1'}]).put()
        stage.next(payload={})

        # the missing item should be deleted and resolved item should added Item ready for next publish
        get_mock.assert_called_once()
        self.assertEqual(self.count_missing_items(), 0)
        self.assertEqual(self.count_items(), 1)

    def test_missing_without_payload_id(self):
        """
        Verifies that a missing item without the Id field in the data can be processed.
        """
        item_id = '1000_2010-01-01'
        Item(org_uid='test', changeset=-1, endpoint='AccountBalance', item_id=item_id, data={'Balance': '10'}).put()
        MissingItem(org_uid='test', missing_items=[{'type': 'AccountBalance', 'id': item_id}]).put()
        self.create_org(status=CONNECTED)
        stage = MissingItemsStage('test')
        stage.next(payload={})

        # the missing item should be deleted and resolved item should added Item ready for next publish
        self.assertEqual(self.count_missing_items(), 0)
        self.assertEqual(self.count_items(), 2)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_missing_not_found(self, get_mock):
        """
        Verifies that if the missing item is not found in Item or in the API it will be deleted, but not added to Item.

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(ACCOUNT_ENDPOINT_NAME, 0)
        self.create_org(status=CONNECTED)
        stage = MissingItemsStage('test')
        MissingItem(org_uid='test', missing_items=[{'type': 'Account', 'id': '1'}]).put()
        stage.next(payload={})

        # the missing item should be deleted and resolved item should added Item ready for next publish
        get_mock.assert_called_once()
        self.assertEqual(self.count_missing_items(), 0)
        self.assertEqual(self.count_items(), 0)

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_missing_without_id(self, get_mock):
        """
        Verifies that if the api lookup works with items which do not have an ID.

        Args:
            get_mock(Mock): mock of the api get function
        """
        get_mock.return_value = self.get_mock_api_response(COMPANY_INFO_ENDPOINT_NAME)
        self.create_org(status=CONNECTED)
        stage = MissingItemsStage('test')
        MissingItem(org_uid='test', missing_items=[{'type': 'CompanyInfo'}]).put()
        stage.next(payload={})

        # the missing item should be deleted and resolved item should added Item ready for next publish
        get_mock.assert_called_once()
        self.assertEqual(self.count_missing_items(), 0)
        self.assertEqual(self.count_items(), 1)


class JournalReportStageTestCase(BaseTestCase):
    """
    Tests for the missing item resolution stage of the sync.
    """

    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_journal_sync(self, get_mock):
        """
        Verifies that journals can be synthesised from the General Ledger report.

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/general_ledger_report.json') as report_contents:
            get_mock.return_value = json.load(report_contents)

        self.create_org(status=CONNECTED)
        QboSyncData(id='test', journal_dates=['2000-01-01']).put()
        stage = JournalReportStage('test')
        stage.next(payload={})

        # 7 journals should be saved
        self.assertEqual(self.count_items(), 7)

        # the journal date ingested should be deleted
        self.assertEqual(QboSyncData.get_by_id('test').journal_dates, [])


class AccountBalanceReportStageTestCase(BaseTestCase):
    """
    Tests for account balance sync.
    """

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2000, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_parsing(self, get_mock):
        """
        Verifies that account balances can be synthesised from the Trial Balance report.

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/trial_balance_report.json') as report_contents:
            get_mock.return_value = json.load(report_contents)

        # setup org and sync state
        self.create_org(status=CONNECTED, changeset=0)
        QboSyncData(id='test', account_balance_marker='2000-01-01').put()

        # run sync
        stage = AccountBalanceReportStage('test')
        stage.next(payload={})

        # there should be 15 account balances saved, but each twice (once for -1 changeset)
        self.assertEqual(self.count_items(), 30)

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_step(self, get_mock):
        """
        Verifies account balance sync state management (that balances are fetched backwards).

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/trial_balance_report.json') as report_contents:
            get_mock.return_value = json.load(report_contents)

        # setup org and sync state
        self.create_org(status=CONNECTED)
        QboSyncData(id='test', account_balance_marker='2000-01-01').put()

        # run sync
        stage = AccountBalanceReportStage('test')
        stage.next(payload={})

        # marker should be decremented for the next sync
        self.assertEqual(QboSyncData.get_by_id('test').account_balance_marker, '1999-12-31')

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_today(self, get_mock):
        """
        Verifies that today's account balance is not fetched if the day hasn't ticked over.

        Args:
            get_mock(Mock): a mock of the qbo api call function
        """
        get_mock.return_value = {'Rows': {'Row': []}}

        # setup org and sync state
        self.create_org(status=CONNECTED)
        QboSyncData(id='test', account_balance_initial_marker='2010-01-01').put()

        # run sync
        stage = AccountBalanceReportStage('test')
        stage.next(payload={})

        # balance has been pulled
        get_mock.assert_not_called()

        # marker should be left alone because it is org today
        self.assertEqual(QboSyncData.get_by_id('test').account_balance_initial_marker, '2010-01-01')

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_initial_sync(self, get_mock):
        """
        Verifies that only 2 years of balances are fetched on initial sync.

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/trial_balance_report.json') as report_contents:
            get_mock.return_value = json.load(report_contents)

        # setup org and sync state (marker is 3 years ago)
        self.create_org(status=CONNECTED, changeset=0)
        marker = (date(2010, 1, 1) - timedelta(days=3 * 365)).strftime('%Y-%m-%d')
        QboSyncData(id='test', account_balance_marker=marker).put()

        # run sync
        stage = AccountBalanceReportStage('test')
        complete, _ = stage.next(payload={})

        # stage should be completed
        self.assertTrue(complete)

        # marker is cleared
        self.assertIsNone(QboSyncData.get_by_id('test').account_balance_marker)

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_normal_sync(self, get_mock):
        """
        Verifies that more than 2 years of balances are fetched on non-initial sync.

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/trial_balance_report.json') as report_contents:
            get_mock.return_value = json.load(report_contents)

        # setup org and sync state
        self.create_org(status=CONNECTED, changeset=1)
        marker = (date(2010, 1, 1) - timedelta(days=3 * 365)).strftime('%Y-%m-%d')
        QboSyncData(id='test', account_balance_marker=marker).put()

        # run sync
        stage = AccountBalanceReportStage('test')
        complete, _ = stage.next(payload={})

        # stage should not be completed
        self.assertFalse(complete)

        # and marker should be incremented for the next sync
        self.assertEqual(QboSyncData.get_by_id('test').account_balance_marker, '2007-01-01')

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get', Mock(return_value={'Rows': {'Row': []}}))
    def test_account_balance_completion(self):
        """
        Verifies that once no balances are found in the report stage is reported as complete.
        """
        # setup org and sync state
        self.create_org(status=CONNECTED, changeset=1)
        QboSyncData(id='test', account_balance_marker='2000-01-01').put()

        # run sync (report is empty)
        stage = AccountBalanceReportStage('test')
        complete, _ = stage.next(payload={})

        # stage should be completed
        self.assertTrue(complete)

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_no_marker(self, get_mock):
        """
        Verifies that balances progress tracking can handle the case where there is no account balance marker (brand new
        file being connected, first sync)..

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/trial_balance_report.json') as report_contents:
            get_mock.return_value = json.load(report_contents)

        # setup org and sync state
        self.create_org(status=CONNECTED, changeset=1)
        QboSyncData(id='test').put()

        # run sync
        stage = AccountBalanceReportStage('test')
        complete, _ = stage.next(payload={})

        # stage should be completed
        self.assertFalse(complete)

        # marker is set to the next day to fetch
        self.assertEqual(QboSyncData.get_by_id('test').account_balance_marker, '2009-12-31')

    @patch('app.sync_states.qbo.stages.get_org_today', Mock(return_value=date(2010, 1, 1)))
    @patch('app.sync_states.qbo.stages.QboApiSession.refresh_token', Mock())
    @patch('app.sync_states.qbo.stages.QboApiSession.get')
    def test_account_balance_deduplication(self, get_mock):
        """
        Verifies that an account balance is fetched, but hasn't changed since the last fetch, doesn't get saved to Item.

        Args:
            get_mock(Mock): mock of the api get function
        """
        with open('tests/resources/trial_balance_report.json') as report_contents:
            sample_report = json.load(report_contents)

        get_mock.return_value = sample_report

        # setup org and sync state
        self.create_org(status=CONNECTED, changeset=0)
        QboSyncData(id='test', account_balance_marker='2010-01-01').put()

        # run sync
        stage = AccountBalanceReportStage('test')
        stage.next(payload={})

        # there should be 30 Items saved
        self.assertEqual(self.count_items(), 30)

        # setup next changeset and reset the marker to the same day (simulate the same day fetching again, but on the
        # next day update cycle)
        org = Org.get_by_id('test')
        org.changeset = 1
        org.put()
        QboSyncData(id='test', account_balance_marker='2010-01-01').put()

        # patch response mock so that one balance has changed
        sample_report['Rows']['Row'][0]['ColData'][1]['value'] = 100
        get_mock.return_value = sample_report

        # run sync
        stage = AccountBalanceReportStage('test')
        stage.next(payload={})

        # there should be 31 Items saved (one new balance for changeset 1)
        self.assertEqual(self.count_items(), 31)

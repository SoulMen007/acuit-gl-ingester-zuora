"""
Module for implementation of QBO sync stages. All the QBO-specific nasties should be here.
"""
import logging
import os
from datetime import datetime, timedelta
from itertools import groupby
from app.clients.qbo_client import QboApiSession
from app.services.ndb_models import Org, Item, MissingItem
from app.utils import sync_utils
from app.sync_states.qbo.ndb_models import QboSyncData
from app.sync_states.qbo.endpoints import (
    ENDPOINTS, SKIP_PAGINATION, SKIP_ID_IN_API_GET, TRANSACTIONAL_ENDPOINTS, HAS_ACTIVE_FLAG, JOURNAL_TXN_TYPE_TO_ENDPOINT_MAP
)
from app.sync_states.qbo.org_today import get_org_today

BASE_API_URI = os.environ.get('QBO_BASE_API_URI')
API_MINOR_VERSION = os.environ.get('QBO_API_MINOR_VERSION')
PAGE_SIZE = 100
START_OF_TIME = '1970-01-01T00:00:00'
INITIAL_ACCOUNT_BALANCE_SYNC_LIMIT = 365 * 2
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S+00:00'
CREATED_AT_FIELD_NAME = 'CreateTime'
UPDATED_AT_FIELD_NAME = 'LastUpdatedTime'


class ListApiStage(object):
    """
    Class which pulls all list endpoints for updated items (and pages through each endpoint) for an org.

    Additionally, this class sets journal and account balance target dates based on updated transactional items (for
    example, it watches invoice transaction dates when pulling updated invoices, and then sets target journal and
    account balance dates for subsequent ingestion stages to pull those items based on).
    """

    def __init__(self, org_uid):
        """
        Initialises the class.

        Args:
            org_uid(str): org identifier
        """
        self.org_uid = org_uid
        self.org = Org.get_by_id(org_uid)
        self.entity_id = self.org.entity_id
        self.api_url = "{}company/{}/query?minorversion={}".format(BASE_API_URI, self.entity_id, API_MINOR_VERSION)
        self.sync_data = QboSyncData.get_by_id(org_uid) or QboSyncData(id=org_uid, endpoint_index=0, start_position=1)

        if self.sync_data.endpoint_index == 0:
            logging.info("this is a start of a new changeset, starting to ingest all endpoints")

    def _get_url(self):
        """
        Builds a URL to fetch data for current sync state.

        Returns:
            str: URL (including the query parameter) for the data to be pulled from
        """
        endpoint = ENDPOINTS[self.sync_data.endpoint_index]
        marker = self.sync_data.markers.get(self.sync_data.endpoint_index, START_OF_TIME)

        query_template = "select * from {} where MetaData.LastUpdatedTime > '{}' "

        if endpoint in HAS_ACTIVE_FLAG:
            query_template = query_template + "and Active in (true, false) "

        query_template = query_template + "order by MetaData.LastUpdatedTime asc startposition {} maxresults {}"

        query = query_template.format(endpoint, marker, self.sync_data.start_position, PAGE_SIZE)
        url = self.api_url + '&query=' + query
        return url

    @staticmethod
    def _get_transaction_date(endpoint, item):
        """
        Extracts transaction date from an item (returns None if the item is not transactional).

        Args:
            item(dict): raw item from an API endpoint

        Returns:
            std, None: transaction date
        """
        if endpoint in TRANSACTIONAL_ENDPOINTS:
            return item['TxnDate']

    def is_new_company_info(self, company_info):
        """
        Checks if CompanyInfo response has changed since it was pulled the last time. Usually this is taken care of by
        the LastUpdatedTime filter on the API (only data which has been updated is returned), but CompanyInfo endpoint
        seems to return all the time.

        Args:
            company_info(dict): response from CompanyInfo endpoint

        Returns:
            bool: True if the company_info has changed since the last pull
        """
        company_info_updated_at = company_info.get('MetaData', {}).get('LastUpdatedTime')

        item = Item.query(Item.org_uid == self.org_uid, Item.endpoint == 'CompanyInfo', Item.changeset == -1).get()
        if item:
            item_updated_at = item.data.get('MetaData', {}).get('LastUpdatedTime')
            if company_info_updated_at and company_info_updated_at == item_updated_at:
                logging.info("CompanyInfo has not been updated, ignoring")
                return False

        return True

    def next(self, payload):
        """
        Pulls data from QBO API for the current sync step, stores the data into the endpoint cache, and stores the
        updated sync state ready for the next sync step.

        Args:
            payload(dict): a payload which has been given to the adaptor last time this function ran

        Returns:
            (bool, dict): a flag indicating if the sync has finished, and a payload to be passed in on next call
        """
        new_payload = {}
        max_updated_at = None

        endpoint = ENDPOINTS[self.sync_data.endpoint_index]
        logging.info("calling api for {}, endpoint {}".format(self.org_uid, endpoint))

        session = QboApiSession(self.org_uid)
        response = session.get(self._get_url(), headers={'Accept': 'application/json'})

        items = response.get('QueryResponse', {}).get(endpoint, [])
        logging.info("got {} items for endpoint {}".format(len(items), endpoint))

        if items:
            max_updated_at = items[-1]['MetaData']['LastUpdatedTime']

        item_objects = []

        for item in items:

            # grab the country as we need it to work out org's today
            if endpoint == 'CompanyInfo':
                self.org.country = item['Country']
                self.org.put()

            # CompanyInfo endpoint ignores LastUpdatedTime filter, we have to manually de-duplicate
            if endpoint != 'CompanyInfo' or self.is_new_company_info(items[0]):
                journal_date = self._get_transaction_date(endpoint, item)
                if journal_date:
                    dates = set(self.sync_data.journal_dates + [journal_date])
                    self.sync_data.journal_dates = dates

                item_objects.extend(
                    sync_utils.create_items(
                        self.org_uid,
                        self.org.provider,
                        self.org.changeset,
                        endpoint,
                        item['Id'],
                        item
                    )
                )

        sync_utils.save_items(item_objects)

        is_paginated = endpoint not in SKIP_PAGINATION
        has_more_items = len(items) == PAGE_SIZE

        if is_paginated and has_more_items:
            logging.info("{} is a paginated endpoint and there could be more pages".format(endpoint))
            self.sync_data.start_position = self.sync_data.start_position + len(items)
            new_payload['max_updated_at'] = max_updated_at
        else:
            logging.info("no more data expected for endpoint {}".format(endpoint))
            marker = max_updated_at or payload.get('max_updated_at')
            if marker:
                logging.info("setting updated_at marker for {} to {}".format(endpoint, marker))
                self.sync_data.markers[self.sync_data.endpoint_index] = marker
            self.sync_data.endpoint_index += 1
            self.sync_data.start_position = 1

        complete = self.sync_data.endpoint_index == len(ENDPOINTS)
        if complete:
            self.sync_data.endpoint_index = 0

        self.sync_data.put()
        complete = complete and not has_more_items

        return complete, new_payload


class MissingItemsStage(object):
    """
    Reads missing item bundles from MissingItem kind (written by stage 1 and 2 re-request), attempts to resolve each
    item in the bundle, and writes the resolved payloads to the Item kind with the current changeset number. The write
    to Item is only done if all items in the bundle can be resolved (log a warning otherwise).

    This implementation is capable of handling missing items for endpoint 'Journal' only by looking at the raw endpoint
    store (Item kind) and not by calling QBO API as the items for this endpoint are synthesised and can't be retrieved
    via the QBO API in generic fashion implemented in this class (the General Ledger report for the relevant day should
    be run and the particular journal synthesised if we wanted to add support for this). However, this should not be a
    problem because a journal is at the bottom of the dependency chain, so it will never be truly missing but merely
    included in the missing item bundle as the re-request will be made for something related to the journal (like an
    invoice). As this is the case the journal will already exist in Item kind and re-generation of this journal from the
    API will never be necessary.
    """

    def __init__(self, org_uid):
        """
        Initialises the class.

        Args:
            org_uid(str): org identifier
        """
        self.org_uid = org_uid
        self.org = Org.get_by_id(org_uid)
        self.entity_id = self.org.entity_id
        self.api_url = "{}company/{}/query?minorversion={}".format(BASE_API_URI, self.entity_id, API_MINOR_VERSION)

    def _get_url(self, endpoint, item_id):
        """
        Builds a URL to fetch data for current sync state. Handles both requests with an ID and without (some endpoints
        like CompanyInfo do not work with ID).

        Returns:
            str: URL for the data to be pulled from
        """
        if item_id:
            query = "select * from {} where Id = '{}'".format(endpoint, item_id)
        else:
            query = "select * from {}".format(endpoint)

        url = self.api_url + '&query=' + query
        return url

    def next(self, payload):
        """
        Processes one batch of missing items, saves them for publishing only if all can be resolved (resolution is
        attempted in the cache first, then via the API if not in cache).

        Args:
            payload(dict): a payload which has been given to the adaptor last time this function ran

        Returns:
            (bool, dict): a flag indicating if the sync has finished, and a payload to be passed in on next call
        """
        results = []
        missing_item = MissingItem.query(MissingItem.org_uid == self.org_uid).get()

        if not missing_item:
            logging.info("no missing items, nothing to process")
            return True, {}

        for item in missing_item.missing_items:
            logging.info("processing missing item: {}".format(item))

            # handle items which do not have an ID (CompanyInfo for example)
            if item['type'] in SKIP_ID_IN_API_GET:
                item_cache = Item.query(
                    Item.org_uid == self.org_uid,
                    Item.endpoint == item['type'],
                    Item.changeset == -1
                ).get()
            else:
                item_cache = Item.query(
                    Item.org_uid == self.org_uid,
                    Item.endpoint == item['type'],
                    Item.item_id == item['id'],
                    Item.changeset == -1
                ).get()

            if item_cache:
                data = item_cache.data
                item_id = item_cache.item_id
            else:
                logging.info("could not find {} with id {} in raw endpoint cache".format(item['type'], item.get('id')))
                session = QboApiSession(self.org_uid)
                data = session.get(self._get_url(item['type'], item.get('id')), headers={'Accept': 'application/json'})
                data = data.get('QueryResponse', {}).get(item['type'], {})

                if data:
                    data = data[0]
                    item_id = data['Id']
                else:
                    message_template = (
                        "could not find {} with id {} in the api either, "
                        "ignoring and deleting this missing item record"
                    )
                    logging.warning(message_template.format(item['type'], item.get('id')))
                    missing_item.key.delete()
                    return False, {}

            results.append({
                'endpoint': item['type'],
                'item_id': item_id,
                'data': data
            })

        item_objects = []

        for result in results:
            message = "saving resolved missing item into raw endpoint cache (type: {}, id: {})"
            logging.info(message.format(result['endpoint'], result['item_id']))

            item_objects.extend(
                sync_utils.create_items(
                    self.org_uid,
                    self.org.provider,
                    self.org.changeset,
                    result['endpoint'],
                    result['item_id'],
                    result['data']
                )
            )

        sync_utils.save_items(item_objects)

        logging.info("deleting missing item")
        missing_item.key.delete()

        return False, {}


class JournalReportStage(object):
    """
    Synthesises journals from General Ledger report.

    QBO does not have an endpoint which provides journals, so we create them from General Ledger report.
    """

    def __init__(self, org_uid):
        """
        Initialises the class.

        Args:
            org_uid(str): org identifier
        """
        self.org_uid = org_uid
        self.sync_data = QboSyncData.get_by_id(org_uid)
        self.org = Org.get_by_id(org_uid)
        self.entity_id = self.org.entity_id

    def _get_url(self, date):
        """
        Builds a URL to fetch data for current sync state.

        Returns:
            str: URL for the data to be pulled from
        """
        api_url = "{}company/{}/reports/GeneralLedger?minorversion=3".format(BASE_API_URI, self.entity_id)
        url = api_url + "&start_date={}&end_date={}".format(date, date)
        return url

    def next(self, payload):
        """
        Calls report API to get General Ledger report for a date (based on the state of the sync), extracts journal
        lines from the report and synthesises journals (which contain those extracted lines). The journal ID is created
        from the transaction type and transaction ID which caused the journal lines.
        """

        def add_journal_info(journal_line, account):
            """
            Adds journal properties to a journal line. These properties (under the 'group' key) can then be used to
            group these resulting objects and create an actual journal (just the lines need to be concatenated).
            """

            return {
                'group': {
                    'Id': "{}{}".format(JOURNAL_TXN_TYPE_TO_ENDPOINT_MAP[journal_line[1]['value']], journal_line[1]['id']),
                    'TransactionType': journal_line[1]['value'],
                    'TransactionId': journal_line[1]['id'],
                    'Date': journal_line[0]['value']
                },
                'Line': {
                    "AccountId": account['AccountId'],
                    "AccountName": account['AccountName'],
                    "Amount": journal_line[6]['value'],
                    "Description": journal_line[4]['value']
                }
            }

        def extract_lines(section, parent_section_account=None):
            """
            Extracts journal lines from the General Ledger report. This is recursive function as the journal lines
            appear nested under a variable number of accounts. The account is carried through the recursive calls as it
            can only be obtained from the parent section of the report (rather than the same section in which the lines
            appear.

            Args:
                section(list|dict): a section of the report, could be a header or a list of lines
                parent_section_account(str): the account for which the lines are for (if the section contains lines)

            Returns:
                list: a list of journal lines which could be deeply nested
            """
            if isinstance(section, list):
                return [extract_lines(subsection, parent_section_account) for subsection in section]
            elif isinstance(section, dict):
                if 'ColData' in section:
                    section_data = section['ColData']
                    if 'id' in section_data[1]:
                        return add_journal_info(section_data, parent_section_account)
                section_account = section.get('Header', {}).get('ColData')
                if section_account:
                    section_account = {
                        'AccountId': section_account[0].get('id'),
                        'AccountName': section_account[0].get('value')
                    }
                else:
                    section_account = None
                return [
                    extract_lines(subsection, section_account or parent_section_account)
                    for _, subsection in section.iteritems()
                ]

        def flatten(list_to_flatten):
            """
            Flattens a deeply nested list of objects ([x, [x, [x, x]]] -> [x, x, x, x])

            Args:
                list_to_flatten(list): the list to be flattened

            Returns:
                list: a flat list
            """
            if isinstance(list_to_flatten, list):
                return [sub_item for item in list_to_flatten for sub_item in flatten(item)]
            else:
                return [list_to_flatten]

        if not self.sync_data.journal_dates:
            return True, {}

        now_str = datetime.utcnow().strftime(TIMESTAMP_FORMAT)

        report_date = self.sync_data.journal_dates[0]
        logging.info("getting journals for {} (out of {})".format(report_date, len(self.sync_data.journal_dates)))

        session = QboApiSession(self.org_uid)
        response = session.get(self._get_url(report_date))

        report_items = flatten(extract_lines(response))

        report_items = [report_item for report_item in report_items if report_item]
        report_items = sorted(report_items, key=lambda x: x['group']['Id'])
        logging.info("have {} journal lines in total to save".format(len(report_items)))

        item_objects = []

        # the report is grouped by account, but we want to re-group by the properties which will define a journal (these
        # properties have been created by add_journal_info function and are under the 'group' key). we then concatenate
        # all the lines for the particular group and we get a journal ('group' will have journal properties, the
        # concatenated lines will be all the lines for the journal).
        for journal, lines in groupby(report_items, lambda x: x['group']):
            journal['Lines'] = [line['Line'] for line in lines]

            # synthesise created_at and updated_at fields for the journal
            # we have to 'make up' these values because qbo doesn't have journals. we could look up Item with changeset
            # of -1 and get the created_at value from there so it persists across updates of one journal, but this is
            # pretty expensive (get_multi blows the memory out as we can have a large number of journals for one day,
            # and fetching individually takes too long and costs a lot).
            journal[CREATED_AT_FIELD_NAME] = now_str
            journal[UPDATED_AT_FIELD_NAME] = now_str

            item_objects.extend(
                sync_utils.create_items(
                    self.org_uid,
                    self.org.provider,
                    self.org.changeset,
                    'Journal',
                    journal['Id'],
                    journal
                )
            )

            # clear item_objects periodically to keep memory usage low
            if len(item_objects) == 500:
                sync_utils.save_items(item_objects)
                del item_objects[:]

        sync_utils.save_items(item_objects)

        # save sync state
        self.sync_data.journal_dates = self.sync_data.journal_dates[1:]
        self.sync_data.put()

        return False, {}


class AccountBalanceReportStage(object):
    """
    Creates account balance items from the Trial Balance report.

    QBO does not provide a way of checking which historical balances may have been updated, so the full history is
    synced once per day (when the org's day ticks over). Only the last 2 years of balances are fetched on inital sync to
    speed it up.
    """

    def __init__(self, org_uid):
        """
        Initialises the class.

        Args:
            org_uid(str): org identifier
        """
        self.org_uid = org_uid
        self.sync_data = QboSyncData.get_by_id(org_uid)
        self.org = Org.get_by_id(org_uid)
        self.entity_id = self.org.entity_id

    def _get_url(self, date):
        """
        Builds a URL to fetch data for current sync state.

        Returns:
            str: URL for the data to be pulled from
        """
        api_url = "{}company/{}/reports/TrialBalance?minorversion=3".format(BASE_API_URI, self.entity_id)
        url = api_url + "&start_date=1970-01-01&end_date={}".format(date)
        return url

    def _get_initial_marker(self):
        """
        Utility function to format account_balance_initial_marker.

        Returns:
            date|None: account_balance_initial_marker formatted as date, if present
        """
        if self.sync_data.account_balance_initial_marker:
            return datetime.strptime(self.sync_data.account_balance_initial_marker, '%Y-%m-%d').date()

    @staticmethod
    def _is_updated(current_balance, new_balance):
        """
        Utility function to determine if an account balance has been updated.

        Args:
            current_balance(dict|None): balance from Item
            new_balance(dict): balance from an api call

        Returns:
            bool: indicator if the balance is new or has been updated
        """
        if not current_balance:
            return True

        return (
            current_balance.data['Credit'] != new_balance.data['Credit']
            or current_balance.data['Debit'] != new_balance.data['Debit']
        )

    def next(self, payload):
        """
        Calls report API to get Trial Balances report for a date (based on the state of the sync), extracts balances
        from the report and synthesises account balance items from those extracted balances. De-duplicates account
        balances which have not changed since the last sync (syncing all account balances is the only way to ensure we
        have accurate balances as QBO doesn't provide a way of monitoring for events which may have changed historical
        balances, and we de-duplicate so that the full history of balances insn't published every day).

        The account balance ID is created from the combination of account id and date the account balance is for.
        """
        org_today = get_org_today(self.org)
        now_str = datetime.utcnow().strftime(TIMESTAMP_FORMAT)

        if self.sync_data.account_balance_marker:
            logging.info("continuing a sync cycle which is in progress")
            marker = datetime.strptime(self.sync_data.account_balance_marker, '%Y-%m-%d').date()
            gap = (org_today - marker).days
        elif self._get_initial_marker() != org_today:
            logging.info("starting a new sync cycle")
            marker = org_today
            self.sync_data.account_balance_initial_marker = marker.strftime('%Y-%m-%d')
            gap = 0
        else:
            logging.info("not syncing (no sync in progress and org today hasn't ticked over)")
            return True, {}

        logging.info("fetching trial balance report for '{}'".format(marker))
        session = QboApiSession(self.org_uid)
        response = session.get(self._get_url(marker), headers={'Accept': 'application/json'})

        item_objects = []
        balance_count = 0
        for account in response.get('Rows', {}).get('Row', []):
            if 'ColData' in account:
                balance_count += 1
                balance_data = account['ColData']
                account_id = balance_data[0]['id']
                item_id = "{}_{}".format(account_id, marker)

                item = {
                    'Date': marker.strftime('%Y-%m-%d'),
                    'AccountId': account_id,
                    'AccountName': balance_data[0]['value'],
                    'Debit': balance_data[1]['value'],
                    'Credit': balance_data[2]['value']
                }

                # synthesise created_at and updated_at fields for the account balance
                # we can't really get the values for these fields from qbo as account balance is not a transactional
                # thing in their api, so we just use the time when the account balance was synthesised. this does mean
                # that if the same account balance (account and date combination) is generated twice, the created_at
                # will be different. we could look up the latest version of the balance in Item and use it's created_at
                # value, but it is too expensive to look up given large amounts of bank balances (due to re-fetches when
                # a transaction is updated and account balances change).
                item[CREATED_AT_FIELD_NAME] = now_str
                item[UPDATED_AT_FIELD_NAME] = now_str

                item_objects.extend(
                    sync_utils.create_items(
                        self.org_uid,
                        self.org.provider,
                        self.org.changeset,
                        'AccountBalance',
                        item_id,
                        item
                    )
                )

        logging.info("got {} balances".format(balance_count))

        current_balances = sync_utils.get_items(self.org_uid, -1, 'AccountBalance', [i.item_id for i in item_objects])
        current_balances_dict = {balance.item_id: balance for balance in current_balances if balance}

        new_item_objects = []

        for item in item_objects:
            current = current_balances_dict.get(item.item_id)
            if self._is_updated(current, item):
                new_item_objects.append(item)

        if new_item_objects:
            message = "saving {} new/updated account balance Items (includes -1 changeset)"
            logging.info(message.format(len(new_item_objects)))
            sync_utils.save_items(new_item_objects)
        else:
            logging.info("no new/updated account balances to save")

        should_stop = False
        if self.org.changeset == 0 and gap > 2 * 365:
            logging.info("stopping sync, reached 2 years for the initial changeset")
            should_stop = True
        elif balance_count == 0:
            logging.info("stopping sync, no balances found")
            should_stop = True

        if should_stop:
            self.sync_data.account_balance_marker = None
            self.sync_data.put()
            return True, {}

        next_marker = marker - timedelta(days=1)
        self.sync_data.account_balance_marker = next_marker.strftime('%Y-%m-%d')
        logging.info("setting the marker to '{}', asking for another fetch".format(next_marker))
        self.sync_data.put()

        return False, {}

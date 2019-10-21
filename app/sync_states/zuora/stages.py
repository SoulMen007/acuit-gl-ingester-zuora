import logging
import os

from app.clients.zuora_client import ZuoraApiSession
from app.services.ndb_models import Org
from app.sync_states.zuora.endpoints import ENDPOINTS, ENDPOINT_QUERY_FIELDS
from app.sync_states.zuora.ndb_models import ZuoraSyncData
from dateutil import parser

from app.utils import sync_utils

BASE_API_URI = os.environ.get('ZUORA_BASE_API_URI')
QUERY_URI = "{}/action/query".format(BASE_API_URI)
QUERY_MORE_URI = "{}/action/queryMore".format(BASE_API_URI)
START_OF_TIME = '1970-01-01T00:00:00'


class ListApiStage(object):
    """
    Class which pulls all list endpoints for updated items (and pages through each endpoint) for an org.
    There are 2 urls associated with this stage. One to provide an sql like query to retrieve data and
    another to retrieve the next page of data if there is any (determined via a queryLocator field present
    in the response).
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
        self.sync_data = ZuoraSyncData.get_by_id(org_uid) or ZuoraSyncData(id=org_uid, endpoint_index=0)

    def _get_query(self):
        """
        Builds a query to be used for fetching data for current sync state.

        Returns:
            str: The query to be used to pull the data from Zuora
        """

        endpoint = ENDPOINTS[self.sync_data.endpoint_index]
        marker = self.sync_data.markers.get(self.sync_data.endpoint_index, START_OF_TIME)

        query_string = "select " + ",".join(ENDPOINT_QUERY_FIELDS[endpoint])

        # ZOQL does not support the `order by` sorting
        query_string = query_string + " from {} where UpdatedDate > '{}'".format(
            endpoint,
            marker
        )

        return query_string

    def next(self, payload):
        """
        Pulls data from Zuora API for the current sync step, stores the data into the endpoint cache, and stores the
        updated sync state ready for the next sync step.

        Args:
            payload(dict): a payload which has been given to the adaptor last time this function ran

        Returns:
            (bool, dict): a flag indicating if the sync has finished, and a payload to be passed in on next call
        """

        session = ZuoraApiSession(self.org_uid)

        # There are 2 different endpoints for querying.
        # One which takes the initial query string and one which takes a cursor if there is another page of data.
        if self.sync_data.cursor:
            response = session.post(
                QUERY_MORE_URI,
                json={'queryLocator': self.sync_data.cursor}
            )
        else:
            response = session.post(
                QUERY_URI,
                json={'queryString': self._get_query()}
            )

        endpoint = ENDPOINTS[self.sync_data.endpoint_index]

        items = response.get('records', [])
        new_payload = {}
        has_more_items = False
        max_updated_at = None

        if items:
            # Parse datetime strings
            updated_dates = [parser.parse(item['UpdatedDate']) for item in items]

            # Retrieve the max UpdatedDate to use in the query for the next changeset
            max_updated_at = items[updated_dates.index(max(updated_dates))]['UpdatedDate']

        item_objects = []

        for item in items:
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

        # If there are more pages to fetch, store the cursor
        if 'queryLocator' in response:
            logging.info("There is another page of {}".format(endpoint))
            self.sync_data.cursor = response['queryLocator']
            new_payload['max_updated_at'] = max_updated_at

        else:
            logging.info("no more data expected for endpoint {}".format(endpoint))
            marker = max_updated_at or payload.get('max_updated_at')

            if marker:
                logging.info("setting updated_at marker for {} to {}".format(endpoint, marker))
                self.sync_data.markers[self.sync_data.endpoint_index] = marker

            self.sync_data.endpoint_index += 1
            self.sync_data.cursor = None

        complete = self.sync_data.endpoint_index == len(ENDPOINTS)

        if complete:
            self.sync_data.endpoint_index = 0

        self.sync_data.put()
        complete = complete and not has_more_items

        return complete, new_payload

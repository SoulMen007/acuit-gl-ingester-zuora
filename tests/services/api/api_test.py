"""
Tests for the api service.
"""

import unittest
from datetime import datetime
from app.services.api import api
from app.services.ndb_models import Org, OrgChangeset
from app.utils.sync_utils import CONNECTED, DISCONNECTED
from google.appengine.ext import testbed


class ApiTestCase(unittest.TestCase):
    """
    Tests for the api service.
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

        api.app.config['TESTING'] = True
        self.app = api.app.test_client()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    def test_status_endpoint(self):
        """
        A few test cases for the status endpoint.
        """
        link_date = datetime(2010, 1, 1)
        connect_date = datetime(2010, 1, 2)

        Org(id='test1', status=1, changeset=0, linked_at=link_date, connected_at=connect_date).put()
        response = self.app.get('/api/data_sources/test1/status')

        # 200 response
        self.assertEqual(response.status_code, 200)

        # meta contains data_source_id
        self.assertEqual(response.json['meta']['data_source_id'], 'test1')

        # link_status is present
        self.assertEqual(response.json['data'][0]['relationships']['link_status']['data']['id'], 'test1')
        self.assertEqual(response.json['included'][1]['attributes']['status'], 'unlinked')
        self.assertEqual(response.json['included'][1]['attributes']['linked_at'], '2010-01-01T00:00:00')

        # connect_status is present
        self.assertEqual(response.json['data'][0]['relationships']['connection_status']['data']['id'], 'test1')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'disconnected')
        self.assertEqual(response.json['included'][0]['attributes']['connected_at'], '2010-01-02T00:00:00')

        # last changeset data is present
        self.assertEqual(response.json['data'][0]['last_changeset_status']['data']['id'], 'test1_0')
        self.assertEqual(
            response.json['data'][0]['last_changeset_status']['links']['related'],
            '/data_sources/test1/changesets/0/status'
        )

        # test CONNECTED internal status
        Org(id='test2', status=2, changeset=0, linked_at=link_date, connected_at=connect_date).put()
        response = self.app.get('/api/data_sources/test2/status')
        self.assertEqual(response.json['included'][1]['attributes']['status'], 'linked')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'connected')

        # test DISCONNECTED internal status
        Org(id='test3', status=3, changeset=0, linked_at=link_date, connected_at=connect_date).put()
        response = self.app.get('/api/data_sources/test3/status')
        self.assertEqual(response.json['included'][1]['attributes']['status'], 'linked')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'disconnected')

        # ensure changeset -1 is not exposed as last_changeset_status
        Org(id='test4', status=2, changeset=-1, linked_at=link_date, connected_at=connect_date).put()
        response = self.app.get('/api/data_sources/test4/status')
        self.assertFalse('last_changeset_status' in response.json['data'][0])

        # test missing org
        response = self.app.get('/api/data_sources/blah/status')
        self.assertEqual(response.status_code, 200)

    def test_changeset_status_endpoint(self):
        """
        A few test cases for the changeset status endpoint.
        """
        # test missing org
        response = self.app.get('/api/data_sources/test0/changesets/0/status')
        self.assertEqual(response.json['errors'][0]['id'], 'test0_not_found')
        self.assertEqual(response.json['errors'][0]['code'], 'not_found')

        # test missing changeset
        Org(id='test1', changeset=10).put()
        response = self.app.get('/api/data_sources/test1/changesets/11/status')
        self.assertEqual(response.json['errors'][0]['id'], 'test1_11_not_found')
        self.assertEqual(response.json['errors'][0]['code'], 'not_found')

        # test synced
        Org(id='test2', changeset=11).put()
        OrgChangeset(
            id='test2',
            org_uid='test2',
            changeset=10,
            publish_job_running=False,
            publish_job_finished=True,
            publish_job_failed=False,
            publish_changeset_failed=False,
            publish_finished_at=datetime(2010, 1, 1)
        ).put()
        response = self.app.get('/api/data_sources/test2/changesets/10/status')
        self.assertEqual(response.json['meta']['data_source_id'], 'test2')
        self.assertEqual(response.json['data'][0]['relationships']['sync_status']['data']['id'], 'test2_10')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'synced')
        self.assertEqual(response.json['included'][0]['attributes']['synced_at'], '2010-01-01T00:00:00')

        # test syncing
        Org(id='test3', changeset=11).put()
        OrgChangeset(
            id='test3',
            org_uid='test3',
            changeset=10,
            publish_job_running=True,
            publish_job_finished=False,
            publish_job_failed=False,
            publish_changeset_failed=False
        ).put()
        response = self.app.get('/api/data_sources/test3/changesets/10/status')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'syncing')
        self.assertIsNone(response.json['included'][0]['attributes']['synced_at'])

        # test error
        Org(id='test4', changeset=11).put()
        OrgChangeset(
            id='test4',
            org_uid='test4',
            changeset=10,
            publish_job_running=False,
            publish_job_finished=True,
            publish_job_failed=True,
            publish_changeset_failed=True
        ).put()
        response = self.app.get('/api/data_sources/test4/changesets/10/status')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'error')
        self.assertIsNone(response.json['included'][0]['attributes']['synced_at'])

        # test ingestion in progress
        Org(id='test5', changeset=11, status=CONNECTED).put()
        response = self.app.get('/api/data_sources/test5/changesets/10/status')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'syncing')
        self.assertIsNone(response.json['included'][0]['attributes']['synced_at'])

        # test ingestion in error
        Org(id='test6', changeset=11, status=DISCONNECTED).put()
        response = self.app.get('/api/data_sources/test6/changesets/10/status')
        self.assertEqual(response.json['included'][0]['attributes']['status'], 'error')
        self.assertIsNone(response.json['included'][0]['attributes']['synced_at'])

"""
Tests for the pubsub utils.
"""

import unittest
import json
from datetime import datetime
from mock import patch, Mock
from app.utils.pubsub_utils import publish_status, publish_changeset_status
from app.services.ndb_models import Org, OrgChangeset
from google.appengine.ext import testbed


class PubsubUtilsTestCase(unittest.TestCase):
    """
    Tests for the pubsub utils.
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

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    @patch('app.utils.pubsub_utils.get_client')
    @patch('app.utils.pubsub_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    def test_status_publish_linked(self, client_mock):
        """
        Verifies the message published on pubsub when an org is linked.

        Args:
            client_mock(Mock): mock of the pubsub client
        """
        Org(id='test', linked_at=datetime(2010, 1, 2)).put()
        publish_status('test', 'link_status', 'linked')
        publish_mock = client_mock.return_value.topic.return_value.publish
        publish_mock.assert_called_with(
            json.dumps({
                "meta": {
                    "version": "2.0.0",
                    "data_source_id": "test",
                    "timestamp": "2010-01-01T00:00:00"
                },
                "data": [
                    {
                        "type": "link_status",
                        "id": "test",
                        "attributes": {
                            "status": "linked",
                            "linked_at": "2010-01-02T00:00:00"
                        }
                    }
                ]
            })
        )

    @patch('app.utils.pubsub_utils.get_client')
    @patch('app.utils.pubsub_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    def test_status_publish_connected(self, client_mock):
        """
        Verifies the message published on pubsub when an org is connected.

        Args:
            client_mock(Mock): mock of the pubsub client
        """
        Org(id='test', connected_at=datetime(2010, 1, 2)).put()
        publish_status('test', 'connection_status', 'connected')
        publish_mock = client_mock.return_value.topic.return_value.publish
        publish_mock.assert_called_with(
            json.dumps({
                "meta": {
                    "version": "2.0.0",
                    "data_source_id": "test",
                    "timestamp": "2010-01-01T00:00:00"
                },
                "data": [
                    {
                        "type": "connection_status",
                        "id": "test",
                        "attributes": {
                            "status": "connected",
                            "connected_at": "2010-01-02T00:00:00"
                        }
                    }
                ]
            })
        )

    @patch('app.utils.pubsub_utils.get_client')
    @patch('app.utils.pubsub_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    def test_changeset_status_published(self, client_mock):
        """
        Verifies the message published on pubsub when a changeset is synced.

        Args:
            client_mock(Mock): mock of the pubsub client
        """
        Org(id='test').put()
        OrgChangeset(org_uid='test', changeset=2, publish_finished_at=datetime(2010, 1, 2)).put()
        publish_changeset_status('test', 2, 'synced')
        publish_mock = client_mock.return_value.topic.return_value.publish
        publish_mock.assert_called_with(
            json.dumps({
                "meta": {
                    "version": "2.0.0",
                    "data_source_id": "test",
                    "timestamp": "2010-01-01T00:00:00"
                },
                "data": [
                    {
                        "type": "changeset_sync_status",
                        "id": "test_2",
                        "attributes": {
                            "status": "synced",
                            "changeset": 2,
                            "synced_at": "2010-01-02T00:00:00"
                        }
                    }
                ]
            })
        )

    @patch('app.utils.pubsub_utils.get_client')
    @patch('app.utils.pubsub_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    def test_changeset_status_syncing(self, client_mock):
        """
        Verifies the message published on pubsub when a changeset is syncing.

        Args:
            client_mock(Mock): mock of the pubsub client
        """
        Org(id='test').put()
        publish_changeset_status('test', 2, 'syncing')
        publish_mock = client_mock.return_value.topic.return_value.publish
        publish_mock.assert_called_with(
            json.dumps({
                "meta": {
                    "version": "2.0.0",
                    "data_source_id": "test",
                    "timestamp": "2010-01-01T00:00:00"
                },
                "data": [
                    {
                        "type": "changeset_sync_status",
                        "id": "test_2",
                        "attributes": {
                            "status": "syncing",
                            "changeset": 2,
                            "synced_at": None
                        }
                    }
                ]
            })
        )

    @patch('app.utils.pubsub_utils.get_client')
    @patch('app.utils.pubsub_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    def test_changeset_status_error(self, client_mock):
        """
        Verifies the message published on pubsub when a changeset is in error.

        Args:
            client_mock(Mock): mock of the pubsub client
        """
        Org(id='test').put()
        publish_changeset_status('test', 2, 'error')
        publish_mock = client_mock.return_value.topic.return_value.publish
        publish_mock.assert_called_with(
            json.dumps({
                "meta": {
                    "version": "2.0.0",
                    "data_source_id": "test",
                    "timestamp": "2010-01-01T00:00:00"
                },
                "data": [
                    {
                        "type": "changeset_sync_status",
                        "id": "test_2",
                        "attributes": {
                            "status": "error",
                            "changeset": 2,
                            "synced_at": None
                        }
                    }
                ]
            })
        )

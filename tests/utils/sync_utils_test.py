"""
Tests for sync management utils operations (provider agnostic).
"""

import unittest
import os
import json
from datetime import datetime, timedelta
from mock import patch, Mock, call

from google.appengine.ext import testbed

from app.utils.sync_utils import CONNECTED, DISCONNECTED, LINKING
from app.services.ndb_models import Org, OrgChangeset
from app.utils import sync_utils


class SyncUtilsTestCase(unittest.TestCase):
    """
    Tests for common sync management operations.
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
        self.testbed.init_taskqueue_stub(root_path=root_path)
        self.taskqueue = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    def test_init_all_updates(self):
        """
        Verifies that a sync cycle is initiated for connected orgs that haven't updated recently only,
        and are API provider orgs (as opposed to manual provider orgs).
        """
        Org(id='test1', status=CONNECTED, provider='qbo').put()  # yes
        Org(id='test2', status=CONNECTED, provider='qbo').put()  # yes
        Org(id='test3', status=DISCONNECTED, provider='qbo').put()  # no
        Org(id='test4', status=LINKING, provider='qbo').put()  # no
        Org(
            id='test5',
            status=CONNECTED,
            provider='qbo',
            last_update_cycle_completed_at=datetime.utcnow() - timedelta(hours=1)
        ).put()  # yes
        Org(
            id='test6',
            status=CONNECTED,
            provider='qbo',
            last_update_cycle_completed_at=datetime.utcnow()
        )  # no
        Org(
            id='test7',
            status=CONNECTED,
            provider='uploader'
        )  # no
        sync_utils.init_all_updates()
        task_count = len(self.taskqueue.get_filtered_tasks())

        self.assertEqual(task_count, 3)

    @patch('app.utils.sync_utils.publish_changeset_status')
    def test_init_update_new_org(self, publish_mock):
        """
        Tests how new changeset is initialised a new org (never synced).

        Args:
            publish_status_mock(Mock): pubsub publish function mock
        """
        Org(id='test', changeset_started_at=None, changeset_completed_at=None).put()

        sync_utils.init_update('test')
        org = Org.get_by_id('test')

        # changeset has been incremented
        self.assertEqual(org.changeset, 0)

        # and changeset timestamps are set
        self.assertIsNotNone(org.changeset_started_at)
        self.assertIsNone(org.changeset_completed_at)

        # and the update task has been created
        task_count = len(self.taskqueue.get_filtered_tasks())
        self.assertEqual(task_count, 1)

        # and changeset status is published
        publish_mock.assert_called_once_with('test', 0, 'syncing')

    @patch('app.utils.sync_utils.publish_changeset_status')
    def test_init_update_existing_org(self, publish_mock):
        """
        Tests how new changeset is initialised an existing org (previously synced).

        Args:
            publish_mock(Mock): mock of the changeset publish function
        """
        some_date = datetime.utcnow()
        Org(
            id='test',
            changeset=10,
            changeset_started_at=some_date,
            changeset_completed_at=some_date,
            last_update_cycle_completed_at=some_date - timedelta(hours=1)
        ).put()

        sync_utils.init_update('test')
        org = Org.get_by_id('test')

        # changeset has been incremented
        self.assertEqual(org.changeset, 11)

        # and changeset timestamps are set
        self.assertIsNotNone(org.changeset_started_at)
        self.assertIsNone(org.changeset_completed_at)

        # and the update task has been created
        task_count = len(self.taskqueue.get_filtered_tasks())
        self.assertEqual(task_count, 1)

        # and changeset status is published
        publish_mock.assert_called_once_with('test', 11, 'syncing')

    def test_init_update_in_progress_changeset(self):
        """
        Verifies that a new changeset is not created for an org with a sync in progress.
        """
        some_date = datetime.utcnow()
        Org(
            id='test',
            changeset=10,
            changeset_started_at=some_date,
            changeset_completed_at=None,
            update_cycle_active=True
        ).put()

        sync_utils.init_update('test')
        org = Org.get_by_id('test')

        # changeset has not been changed
        self.assertEqual(org.changeset, 10)

        # and changeset timestamps have not been changed
        self.assertIsNotNone(org.changeset_started_at)
        self.assertIsNone(org.changeset_completed_at)

        # and no new update task has been created
        task_count = len(self.taskqueue.get_filtered_tasks())
        self.assertEqual(task_count, 0)

    @patch('app.utils.sync_utils.publish_changeset_status')
    def test_init_update_inactive_update_cycle(self, publish_mock):
        """
        Verifies that a new changeset is not created for an org with a sync in progress with an active update cycle (ie.
        has a task on adapter-update).

        Args:
            publish_mock(Mock): mock of the changeset publish function
        """
        some_date = datetime.utcnow()
        Org(
            id='test',
            changeset=10,
            changeset_started_at=some_date,
            changeset_completed_at=None,
            update_cycle_active=False
        ).put()

        sync_utils.init_update('test')
        org = Org.get_by_id('test')

        # changeset has not been changed
        self.assertEqual(org.changeset, 10)

        # and changeset timestamps have not been changed
        self.assertIsNotNone(org.changeset_started_at)
        self.assertIsNone(org.changeset_completed_at)

        # and a new update task has been created because the update_cycle_active was false
        task_count = len(self.taskqueue.get_filtered_tasks())
        self.assertEqual(task_count, 1)

        # and changeset status is published
        publish_mock.assert_called_once_with('test', 10, 'syncing')

    @patch('app.utils.sync_utils.publish_status')
    def test_mark_disconnected(self, publish_status_mock):
        """
        Verifies that an org can be marked as disconnected.

        Args:
            publish_status_mock(Mock): pubsub publish function mock
        """
        Org(id='test', status=CONNECTED, update_cycle_active=True).put()
        sync_utils.mark_as_disconnected(org_uid='test', deactivate_update_cycle=False)

        # status should be changed and new status broadcast on pubsub
        org = Org.get_by_id('test')
        self.assertEqual(org.status, DISCONNECTED)
        self.assertEqual(org.update_cycle_active, True)
        publish_status_mock.assert_called_with('test', 'connection_status', 'disconnected')

    @patch('app.utils.sync_utils.publish_status')
    def test_mark_disconnected_deactivate(self, publish_status_mock):
        """
        Verifies that an org can be marked as disconnected with flagging of update cycle as inactive.

        Args:
            publish_status_mock(Mock): pubsub publish function mock
        """
        Org(id='test', status=CONNECTED, update_cycle_active=False).put()
        sync_utils.mark_as_disconnected(org_uid='test', deactivate_update_cycle=True)

        # status should be changed and new status broadcast on pubsub
        org = Org.get_by_id('test')
        self.assertEqual(org.status, DISCONNECTED)
        self.assertEqual(org.update_cycle_active, False)
        publish_status_mock.assert_called_with('test', 'connection_status', 'disconnected')

    @patch('app.utils.sync_utils.publish_status')
    def test_mark_connected(self, publish_status_mock):
        """
        Verifies that an org can be marked as connected.

        Args:
            publish_status_mock(Mock): pubsub publish function mock
        """
        Org(id='test', status=DISCONNECTED).put()
        sync_utils.mark_as_connected('test')

        # status should be changed and new status broadcast on pubsub
        org = Org.get_by_id('test')
        self.assertEqual(org.status, CONNECTED)

        # connected_at is updated, but linked_at is not
        self.assertIsNotNone(org.connected_at)
        self.assertIsNone(org.linked_at)

        # status change is published on pubsub
        publish_status_mock.assert_called_with('test', 'connection_status', 'connected')

    @patch('app.utils.sync_utils.publish_status')
    def test_mark_connected_linked(self, publish_status_mock):
        """
        Verifies that an org can be marked as connected.

        Args:
            publish_status_mock(Mock): pubsub publish function mock
        """
        Org(id='test', status=DISCONNECTED).put()
        sync_utils.mark_as_connected(org_uid='test', also_linked=True)

        # status should be changed
        org = Org.get_by_id('test')
        self.assertEqual(org.status, CONNECTED)

        # connected_at is updated, but linked_at is not
        self.assertIsNotNone(org.connected_at)
        self.assertIsNotNone(org.linked_at)

        # status change is published on pubsub
        self.assertEqual(publish_status_mock.call_count, 2)
        publish_status_mock.assert_has_calls([
            call('test', 'link_status', 'linked'),
            call('test', 'connection_status', 'connected')
        ])

    @patch('app.utils.sync_utils.datetime', Mock(utcnow=Mock(return_value=datetime(2010, 1, 1))))
    def test_complete_first_changeset(self):
        """
        Verifies that Org and OrgChangeset get updated to indicate that a changeset is complete.
        """
        started_at = datetime.now()

        org = Org(id='test', changeset=0, changeset_started_at=started_at).put()
        sync_utils.complete_changeset('test')

        # Org flags/timestamps are updated
        org = Org.get_by_id('test')
        self.assertEqual(org.changeset_completed_at, datetime(2010, 1, 1))
        self.assertEqual(org.last_update_cycle_completed_at, datetime(2010, 1, 1))
        self.assertFalse(org.update_cycle_active)

        # OrgChangeset record is added
        org_changeset = OrgChangeset.query().get()
        self.assertEqual(org_changeset.org_uid, 'test')
        self.assertEqual(org_changeset.changeset, 0)
        self.assertEqual(org_changeset.ingestion_started_at, started_at)
        self.assertEqual(org_changeset.ingestion_completed_at, datetime(2010, 1, 1))
        self.assertFalse(org_changeset.publish_job_running)
        self.assertFalse(org_changeset.publish_job_finished)
        self.assertEqual(org_changeset.publish_job_count, 0)

        # Publish task is queued for the first changeset
        self.assertEqual(len(self.taskqueue.get_filtered_tasks()), 1)
        self.assertEqual(
            self.taskqueue.get_filtered_tasks()[0].payload,
            json.dumps({"job_params": {"org_changeset_ids": [org_changeset.key.id()]}})
        )

    def test_complete_later_changeset(self):
        """
        Check that no new task is queued up after a non-initial sync.
        """
        org = Org(id='test', changeset=1, changeset_started_at=datetime.utcnow()).put()
        sync_utils.complete_changeset('test')

        # No task queued
        self.assertEqual(len(self.taskqueue.get_filtered_tasks()), 0)

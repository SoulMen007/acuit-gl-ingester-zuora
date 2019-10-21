"""
Tests for the orchestrator service.
"""

import os
import unittest
import json
from mock import patch, Mock, ANY, call

from google.appengine.ext import testbed
from google.appengine.api import taskqueue

from app.services.orchestrator import orchestrator
from app.services.ndb_models import Org, OrgChangeset


class OrchestratorTestCase(unittest.TestCase):
    """
    Tests for the orchestrator service.
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
        self.testbed.init_app_identity_stub()

        root_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.testbed.init_taskqueue_stub(root_path=root_path + '/..')
        self.taskqueue = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)

        orchestrator.app.config['TESTING'] = True
        self.app = orchestrator.app.test_client()

    def tearDown(self):
        """
        Deactivate GAE testbed when tests are finished.
        """
        self.testbed.deactivate()

    def test_publish(self):
        """
        Verifies that the correct changesets are being published.
        """
        # newly ingested changeset (publish not attempted yet)
        OrgChangeset(
            id='test0',
            org_uid='test0',
            changeset=0,
            publish_job_running=False,
            publish_job_finished=False,
            publish_job_count=0
        ).put()

        # the whole publish job failed (set by the orchestrator service based on dataflow api)
        OrgChangeset(
            id='test1',
            org_uid='test1',
            changeset=1,
            publish_job_running=False,
            publish_job_failed=True,
            publish_job_finished=True,
            publish_job_count=1
        ).put()

        # an individual changeset failed to be published (set by the publish job)
        OrgChangeset(
            id='test2',
            org_uid='test2',
            changeset=2,
            publish_job_running=False,
            publish_changeset_failed=True,
            publish_job_finished=True,
            publish_job_count=2
        ).put()

        # this changeset should not get published because its publish job is running
        OrgChangeset(
            id='test3',
            org_uid='test3',
            changeset=3,
            publish_job_running=True,
            publish_job_count=3
        ).put()

        # this changeset should not get published because its org is blacklisted
        Org(
            id='test4',
            publish_disabled=True
        ).put()
        OrgChangeset(
            id='test4',
            org_uid='test4',
            changeset=0,
            publish_job_running=False,
            publish_job_failed=True,
            publish_job_finished=True,
            publish_job_count=0
        ).put()

        # these changesets should not get published as there's already a job running for another changeset
        OrgChangeset(
            id='test5_a',
            org_uid='test5',
            changeset=5,
            publish_job_running=True,
            publish_job_failed=False,
            publish_job_finished=False,
            publish_job_count=0
        ).put()
        OrgChangeset(
            id='test5_b',
            org_uid='test5',
            changeset=6,
            publish_job_running=False,
            publish_job_failed=False,
            publish_job_finished=False,
            publish_job_count=0
        ).put()

        # one task is created if normal publish
        response = self.app.get('/orchestrator/publish')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(self.taskqueue.get_filtered_tasks()), 1)

        # one task per org is created if per_org publish is specifed
        response = self.app.post('/orchestrator/publish', data={'per_org': 1})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(self.taskqueue.get_filtered_tasks()), 1 + 3)  # 1 from last call, 3 from this call

    def test_publish_no_changesets(self):
        """
        Ensures that no publish is attempted if there are no changesets to be published because the org has a publish
        job running for a previous changeset.
        """
        # a changeset which is currently being published
        OrgChangeset(
            id='test0_1',
            org_uid='test0',
            changeset=1,
            publish_job_running=True,
            publish_job_failed=False,
            publish_job_finished=False,
            publish_job_count=0
        ).put()

        # a later changeset for the same org, but should be blocked from publishing because a
        # previous changeset is still running
        OrgChangeset(
            id='test0_2',
            org_uid='test0',
            changeset=2,
            publish_job_running=False,
            publish_job_failed=False,
            publish_job_finished=False,
            publish_job_count=0
        ).put()

        response = self.app.get('/orchestrator/publish')
        self.assertEqual(response.status_code, 204)

        # no publish tasks should be created because there is nothing to publish
        self.assertEqual(len(self.taskqueue.get_filtered_tasks()), 0)

    @patch('app.services.orchestrator.orchestrator.publish_changeset_status')
    @patch('app.services.orchestrator.orchestrator.start_template')
    def test_create_publish_job_task(self, dataflow_mock, publish_mock):
        """
        Verifies that the correct changesets are being published.

        Args:
            dataflow_mock(Mock): mock for kicking off dataflow publish job
            publish_mock(Mock): mock of the changeset publish function
        """
        dataflow_mock.return_value = {'id': 'job_1'}

        OrgChangeset(
            id='test0',
            org_uid='test0',
            changeset=0,
            publish_job_running=False,
            publish_job_count=0
        ).put()

        response = self.app.post(
            '/orchestrator/create_publish_job_task',
            data=json.dumps({
                'job_params': {
                    'org_changeset_ids': ['test0']
                }
            })
        )
        self.assertEqual(response.status_code, 204)

        job_params = {"orgChangesets": "test0:0"}
        dataflow_mock.assert_called_once()
        dataflow_mock.assert_called_once_with('sync', ANY, job_params)

        # fields for published org are updated
        changeset = OrgChangeset.get_by_id('test0')
        self.assertTrue(changeset.publish_job_running)
        self.assertFalse(changeset.publish_job_finished)
        self.assertFalse(changeset.publish_job_failed)
        self.assertEqual(changeset.publish_job_id, "job_1")
        self.assertIsNone(changeset.publish_job_status)
        self.assertEqual(changeset.publish_job_count, 1)

        # and changeset status is published
        publish_mock.assert_called_once_with('test0', 0, 'syncing')

    @patch('app.services.orchestrator.orchestrator.start_template', Mock(side_effect=ValueError))
    @patch('app.services.orchestrator.orchestrator.publish_changeset_status')
    def test_publish_failure(self, publish_mock):
        """
        Verifies that error org changeset status is published if publish job fails to be created.

        Args:
            publish_mock(Mock): mock of the changeset publish function
        """
        OrgChangeset(id='test0', org_uid='test0', changeset=0, publish_job_running=False).put()
        OrgChangeset(id='test1', org_uid='test1', changeset=0, publish_job_running=False).put()

        with self.assertRaises(ValueError):
            self.app.post(
                '/orchestrator/create_publish_job_task',
                data=json.dumps({
                    'job_params': {
                        'org_changeset_ids': ['test0', 'test1']
                    }
                })
            )

        self.assertEqual(len(self.taskqueue.get_filtered_tasks()), 0)

        self.assertEqual(publish_mock.call_count, 2)
        publish_mock.assert_has_calls([call('test0', 0, 'error'), call('test1', 0, 'error')])


    @patch('app.services.orchestrator.orchestrator.publish_changeset_status')
    @patch('app.services.orchestrator.orchestrator.get_job', Mock(return_value={'currentState': 'JOB_STATE_DONE'}))
    def test_update_changeset_success(self, publish_mock):
        """
        Verifies that changeset publish status is updated based on the dataflow api.

        Args:
            publish_mock(Mock): mock of the changeset publish function
        """
        OrgChangeset(id='test', org_uid='test', changeset=0, publish_job_running=True).put()

        response = self.app.get('/orchestrator/update_changesets')
        self.assertEqual(response.status_code, 204)

        # changeset has been marked as completed
        changeset = OrgChangeset.get_by_id('test')
        self.assertTrue(changeset.publish_job_finished)
        self.assertFalse(changeset.publish_job_running)
        self.assertFalse(changeset.publish_job_failed)
        self.assertEqual(changeset.publish_job_status, 'JOB_STATE_DONE')

        # and changeset status is published
        publish_mock.assert_called_once_with('test', 0, 'synced')

    @patch('app.services.orchestrator.orchestrator.publish_changeset_status')
    @patch('app.services.orchestrator.orchestrator.get_job', Mock(return_value={'currentState': 'JOB_STATE_FAILED'}))
    def test_update_changeset_failure(self, publish_mock):
        """
        Verifies that changeset publish status is updated based on the dataflow api.

        Args:
            publish_mock(Mock): mock of the changeset publish function
        """
        OrgChangeset(id='test', org_uid='test', changeset=0, publish_job_running=True).put()

        response = self.app.get('/orchestrator/update_changesets')
        self.assertEqual(response.status_code, 204)

        # changeset has been marked as completed
        changeset = OrgChangeset.get_by_id('test')
        self.assertTrue(changeset.publish_job_finished)
        self.assertFalse(changeset.publish_job_running)
        self.assertTrue(changeset.publish_job_failed)
        self.assertEqual(changeset.publish_job_status, 'JOB_STATE_FAILED')

        # and changeset status is published
        publish_mock.assert_called_once_with('test', 0, 'error')

    @patch('app.services.orchestrator.orchestrator.get_job', Mock(return_value={'currentState': 'JOB_STATE_RUNNING'}))
    def test_update_changeset_running(self):
        """
        Verifies that changeset publish status is updated based on the dataflow api.
        """
        OrgChangeset(id='test', publish_job_running=True).put()

        response = self.app.get('/orchestrator/update_changesets')
        self.assertEqual(response.status_code, 204)

        # changeset has been marked as completed
        changeset = OrgChangeset.get_by_id('test')
        self.assertFalse(changeset.publish_job_finished)
        self.assertTrue(changeset.publish_job_running)
        self.assertFalse(changeset.publish_job_failed)
        self.assertEqual(changeset.publish_job_status, 'JOB_STATE_RUNNING')



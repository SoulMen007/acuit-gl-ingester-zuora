"""
Tests for sync management utils operations (provider agnostic).
"""

import unittest
import os
from mock import patch

from google.appengine.ext import testbed
from google.appengine.api.taskqueue import Queue, Task

from app.utils.sync_utils import CONNECTED, DISCONNECTED
from app.services.ndb_models import Org
from app.utils import task_utils


class TaskUtilsTestCase(unittest.TestCase):
    """
    Tests for task utils
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

    @patch('app.utils.task_utils.taskqueue.MAX_TASKS_PER_ADD', 1)
    def test_query_to_tasks(self):
        """
        Verifies that multiple pages of tasks get queued up properly.
        """
        Org(id='test1', status=CONNECTED).put()
        Org(id='test2', status=CONNECTED).put()
        Org(id='test3', status=DISCONNECTED).put()

        count = task_utils.query_to_tasks(
            query=Org.query(Org.status == CONNECTED),
            queue=Queue('adapter-update'),
            task_generator=lambda key: Task(url='/something/{}'.format(key.string_id()))
        )

        self.assertEqual(count, 2)
        task_count = len(self.taskqueue.get_filtered_tasks())
        self.assertEqual(task_count, 2)

    @patch('app.utils.task_utils.taskqueue.MAX_TASKS_PER_ADD', 1)
    def test_items_to_tasks(self):
        """
        Verifies that multiple pages of tasks get queued up properly.
        """
        count = task_utils.items_to_tasks(
            items=[1, 2, 3],
            queue=Queue('adapter-update'),
            task_generator=lambda item: Task(url='/something/{}'.format(item))
        )

        self.assertEqual(count, 3)
        task_count = len(self.taskqueue.get_filtered_tasks())
        self.assertEqual(task_count, 3)

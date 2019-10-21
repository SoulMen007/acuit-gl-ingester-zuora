"""
Tests for sync management utils operations (provider agnostic).
"""

import unittest
import os
from mock import patch

from google.appengine.ext import testbed
from google.appengine.api.taskqueue import Queue, Task

from app.services.ndb_models import Org
from app.utils import datastore_utils


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

    @patch('app.utils.datastore_utils.DATASTORE_FETCH_PAGE_SIZE', 1)
    def test_items_to_tasks(self):
        """
        Verifies that multiple datastore page fetches result in properly emitted items.
        """
        Org(id='test1').put()
        Org(id='test2').put()
        Org(id='test3').put()

        emitted_orgs = []
        for org in datastore_utils.emit_items(Org.query()):
            emitted_orgs.append(org)

        orgs = Org.query().fetch()

        self.assertListEqual(orgs, emitted_orgs)

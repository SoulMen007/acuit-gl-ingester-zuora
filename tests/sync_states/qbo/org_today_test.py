"""
Tests for utilites for obtaining QBO org's today's date.
"""

import unittest

from app.services.ndb_models import Org
from app.sync_states.qbo.org_today import get_org_today, COUNTRY_TO_TIMEZONE


class OrgTodayTestCase(unittest.TestCase):
    """
    Tests for getting org's today date.
    """

    def test_all_timezones(self):
        """
        Verifies that all timezones in the lookup provided by QBO are valid.
        """
        for country, _ in COUNTRY_TO_TIMEZONE.iteritems():
            get_org_today(Org(id='test', country=country))

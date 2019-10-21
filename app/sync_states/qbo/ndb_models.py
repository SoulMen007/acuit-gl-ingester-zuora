from google.appengine.ext import ndb

class QboSyncData(ndb.Model):
    stage_index = ndb.IntegerProperty(default=0)
    endpoint_index = ndb.IntegerProperty(default=0)
    start_position = ndb.IntegerProperty(default=0)
    markers = ndb.PickleProperty(default={})
    journal_dates = ndb.StringProperty(repeated=True)
    account_balance_initial_marker = ndb.StringProperty()
    account_balance_marker = ndb.StringProperty()

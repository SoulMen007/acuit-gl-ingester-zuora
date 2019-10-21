from google.appengine.ext import ndb

class ZuoraSyncData(ndb.Model):
    stage_index = ndb.IntegerProperty(default=0)
    endpoint_index = ndb.IntegerProperty(default=0)
    cursor = ndb.StringProperty()
    markers = ndb.PickleProperty(default={})

from datetime import datetime

from google.appengine.ext import ndb


class Org(ndb.Model):
    _use_memcache = False
    provider_config = ndb.KeyProperty()
    redirect_url = ndb.StringProperty()
    entity_id = ndb.StringProperty()
    provider = ndb.StringProperty()
    status = ndb.IntegerProperty()
    linked_at = ndb.DateTimeProperty()
    connected_at = ndb.DateTimeProperty()
    country = ndb.StringProperty()
    changeset = ndb.IntegerProperty(default=-1)
    changeset_started_at = ndb.DateTimeProperty()
    changeset_completed_at = ndb.DateTimeProperty()
    update_cycle_active = ndb.BooleanProperty()
    publish_disabled = ndb.BooleanProperty()
    created_at = ndb.DateTimeProperty(auto_now_add=True)
    updated_at = ndb.DateTimeProperty(auto_now=True)
    last_update_cycle_completed_at = ndb.DateTimeProperty(default=datetime(1970, 1, 1))


class OrgCredentials(ndb.Model):
    _use_memcache = False
    token = ndb.PickleProperty()


class UserCredentials(ndb.Model):
    _use_memcache = False
    username = ndb.StringProperty()
    password = ndb.StringProperty()


class OrgChangeset(ndb.Model):
    _use_memcache = False
    org_uid = ndb.StringProperty()
    provider = ndb.StringProperty()
    changeset = ndb.IntegerProperty()
    ingestion_started_at = ndb.DateTimeProperty()
    ingestion_completed_at = ndb.DateTimeProperty()
    publish_started_at = ndb.DateTimeProperty()
    publish_job_id = ndb.StringProperty()
    publish_job_status = ndb.StringProperty()
    publish_job_running = ndb.BooleanProperty()
    publish_job_finished = ndb.BooleanProperty()
    publish_finished_at = ndb.DateTimeProperty()
    publish_job_failed = ndb.BooleanProperty()
    publish_changeset_failed = ndb.BooleanProperty()
    publish_job_count = ndb.IntegerProperty()


class Item(ndb.Model):
    org_uid = ndb.StringProperty()
    provider = ndb.StringProperty()
    changeset = ndb.IntegerProperty()
    endpoint = ndb.StringProperty()
    item_id = ndb.StringProperty()
    parent_id = ndb.StringProperty()  # Used if ingested items need a parent reference, not used for QBO
    data = ndb.JsonProperty()
    created_at = ndb.DateTimeProperty(auto_now_add=True)


class MissingItem(ndb.Model):
    org_uid = ndb.StringProperty()
    missing_items = ndb.JsonProperty()
    origin = ndb.StringProperty()
    changeset = ndb.IntegerProperty()
    created_at = ndb.DateTimeProperty()


class ProviderConfig(ndb.Model):
    """
    This class is intended to hold the provider configuration (partner keys etc) for an app family.
    """
    provider = ndb.StringProperty()
    app_family = ndb.StringProperty()
    client_id = ndb.StringProperty(indexed=False)
    client_secret = ndb.StringProperty(indexed=False)
    additional_auth_attributes = ndb.JsonProperty(indexed=False)

    @staticmethod
    def find(provider, app_family):
        return ProviderConfig.query(ProviderConfig.provider == provider, ProviderConfig.app_family == app_family).get()
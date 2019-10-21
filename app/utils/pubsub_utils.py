"""
Helper classes functions for interacting with the pubsub
"""

import logging
import json
from datetime import datetime
from google.cloud import pubsub
from app.services.ndb_models import Org, OrgChangeset


STATUS_TOPIC = 'gl2.status'

LINK_STATUS_TYPE = 'link_status'
LINK_STATUS_UNLINKED = 'unlinked'
LINK_STATUS_LINKED = 'linked'

CONNECT_STATUS_TYPE = 'connection_status'
CONNECT_STATUS_DISCONNECTED = 'disconnected'
CONNECT_STATUS_CONNECTED = 'connected'

CHANGESET_STATUS_SYNCING = 'syncing'
CHANGESET_STATUS_SYNCED = 'synced'
CHANGESET_STATUS_ERROR = 'error'

client = None


def get_client():
    """
    Singleton getter function for the pubsub client.

    Returns:
        PublisherClient: the client.
    """
    global client
    if client is None:
        client = pubsub.Client()
    return client


def publish_status(org_uid, status_type, status_value):
    """
    Utility function for publishing org status events on pubsub.

    Args:
        org_uid(str): org identifier
        status_type(str): status group (link_status or connect_status)
        status_value(str): status (eg. unlinked|linked, disconnected|connected)
    """
    topic = get_client().topic(STATUS_TOPIC)
    org = Org.get_by_id(org_uid)

    payload = {
        "meta": {
            "version": "2.0.0",
            "data_source_id": org_uid,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat()
        },
        "data": [
            {
                "type": status_type,
                "id": org_uid,
                "attributes": {
                    "status": status_value
                }
            }
        ]
    }

    attributes = payload['data'][0]['attributes']

    if status_type == LINK_STATUS_TYPE:
        if status_value == LINK_STATUS_LINKED:
            attributes['linked_at'] = org.linked_at.replace(microsecond=0).isoformat()
        else:
            attributes['linked_at'] = None

    if status_type == CONNECT_STATUS_TYPE:
        if status_value == CONNECT_STATUS_CONNECTED:
            attributes['connected_at'] = org.connected_at.replace(microsecond=0).isoformat()
        else:
            attributes['connected_at'] = None

    logging.info("publishing on status pubsub topic: {}".format(payload))

    topic.publish(json.dumps(payload))


def publish_changeset_status(org_uid, changeset, status_value):
    """
    Utility function for publishing org changeset status events on pubsub.

    Args:
        org_uid(str): org identifier
        changeset(int): update cycle identifier
        status_value(str): status (eg. syncing, synced, error)
    """
    topic = get_client().topic(STATUS_TOPIC)

    payload = {
        "meta": {
            "version": "2.0.0",
            "data_source_id": org_uid,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat()
        },
        "data": [
            {
                "type": "changeset_sync_status",
                "id": "{}_{}".format(org_uid, changeset),
                "attributes": {
                    "status": status_value,
                    "changeset": changeset,
                    "synced_at": None
                }
            }
        ]
    }

    attributes = payload['data'][0]['attributes']

    if status_value == CHANGESET_STATUS_SYNCED:
        org_changeset = OrgChangeset.query(OrgChangeset.org_uid == org_uid, OrgChangeset.changeset == changeset).get()
        attributes['synced_at'] = org_changeset.publish_finished_at.replace(microsecond=0).isoformat()

    logging.info("publishing on status pubsub topic: {}".format(payload))

    topic.publish(json.dumps(payload))

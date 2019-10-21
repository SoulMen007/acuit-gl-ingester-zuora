import logging

from app.services.ndb_models import Org, OrgChangeset
from app.utils.sync_utils import CONNECTED, DISCONNECTED
from app.utils.pubsub_utils import (
    CHANGESET_STATUS_ERROR,
    CHANGESET_STATUS_SYNCED,
    CHANGESET_STATUS_SYNCING,
    CONNECT_STATUS_CONNECTED,
    CONNECT_STATUS_DISCONNECTED,
    LINK_STATUS_LINKED,
    LINK_STATUS_UNLINKED
)


def get_last_changeset(org):
    """
    Gets the last changeset for an org.

    For orgs which are being ingested by the adapter service the last changeset is always Org.changeset, but some orgs
    are 'synced' via an external process (the 'uploader' provider for example). In this case the last changeset needs
    to be derived from OrgChangeset.

    Args:
        org(Org): the Org object
    """
    # org.changeset is the changeset currently being worked on (could be finished also, but it is the last)
    org_uid = org.key.string_id()
    org_changeset = OrgChangeset.query(OrgChangeset.org_uid == org_uid).order(-OrgChangeset.changeset).get()
    return max(org.changeset, org_changeset.changeset if org_changeset else -1)


def get_status_payload(org_uid):
    """
    Creates response body for org status API.

    Args:
        org_uid(str): org identifier

    Returns:
        dict: status response payload
    """
    org = Org.get_by_id(org_uid)

    if not org:
        payload = {
            "meta": {
                "version": "2.0.0",
            },
            "errors": [
                {
                    "id": "{}_not_found".format(org_uid),
                    "status": "404",
                    "code": "not_found",
                    "title": "Data Source not found",
                    "detail": "Data Source {} could not be found.".format(org_uid)
                }
            ]
        }

        logging.info("org {} not found - response {}".format(org_uid, payload))
        return payload

    # an org can only get to CONNECTED or DISCONNECTED status if it has been linked (this is because internally org
    # status is kept as one field which goes through LINKING|CONNECTED|DISCONNECTED statuses (might be worth splitting
    # these up into two fields at some point).
    link_status = LINK_STATUS_LINKED if org.status in [CONNECTED, DISCONNECTED] else LINK_STATUS_UNLINKED

    # connection status can be directly translated from the internal status to the api representation
    connection_status = CONNECT_STATUS_CONNECTED if org.status == CONNECTED else CONNECT_STATUS_DISCONNECTED

    last_changeset = get_last_changeset(org)

    # but do not show changeset -1 as it is an internal changeset
    show_last_changeset = last_changeset >= 0

    # linked_at and connected_at might not be populated yet
    linked_at = org.linked_at.replace(microsecond=0).isoformat() if org.linked_at else None
    connected_at = org.connected_at.replace(microsecond=0).isoformat() if org.connected_at else None

    payload = {
        "meta": {
            "version": "2.0.0",
            "data_source_id": org_uid
        },
        "data": [
            {
                "type": "data_source_status",
                "id": org_uid,
                "relationships": {
                    "connection_status": {
                        "data": {
                            "type": "connection_status",
                            "id": org_uid
                        }
                    },
                    "link_status": {
                        "data": {
                            "type": "link_status",
                            "id": org_uid
                        }
                    }
                }
            }
        ],
        "included": [
            {
                "type": "connection_status",
                "id": org_uid,
                "attributes": {
                    "status": connection_status,
                    "connected_at": connected_at
                }
            },
            {
                "type": "link_status",
                "id": org_uid,
                "attributes": {
                    "status": link_status,
                    "linked_at": linked_at
                }
            }
        ]
    }

    if show_last_changeset:
        payload['data'][0]['last_changeset_status'] = {
            "data": {
                "type": "changeset_status",
                "id": "{}_{}".format(org_uid, last_changeset)
            },
            "links": {
                "related": "/data_sources/{}/changesets/{}/status".format(org_uid, last_changeset)
            }
        }

    logging.info("status for {}: {}".format(org_uid, payload))

    return payload


def get_changeset_status_payload(org_uid, changeset):
    """
    Creates response body for changeset status API.

    Args:
        org_uid(str): org identifier
        changeset(int): update cycle identifier

    Returns:
        dict: changeset status response payload
    """
    changeset_id = "{}_{}".format(org_uid, changeset)
    status = "unknown"
    synced_at = None

    org = Org.get_by_id(org_uid)

    if not org:
        payload = {
            "meta": {
                "version": "2.0.0",
            },
            "errors": [
                {
                    "id": "{}_not_found".format(org_uid),
                    "status": "404",
                    "code": "not_found",
                    "title": "Data Source not found",
                    "detail": "Data Source {} could not be found.".format(org_uid)
                }
            ]
        }

        logging.info("org {}:{} not found - response {}".format(org_uid, changeset, payload))
        return payload

    if changeset > get_last_changeset(org):
        payload = {
            "meta": {
                "version": "2.0.0",
                "data_source_id": org_uid
            },
            "errors": [
                {
                    "id": "{}_{}_not_found".format(org_uid, changeset),
                    "status": "404",
                    "code": "not_found",
                    "title": "Changeset not found",
                    "detail": "Changeset {} could not be found for {}.".format(changeset, org_uid)
                }
            ]
        }

        logging.info("changeset {}:{} not found - response {}".format(org_uid, changeset, payload))
        return payload

    org_changeset = OrgChangeset.query(OrgChangeset.org_uid == org_uid, OrgChangeset.changeset == changeset).get()

    # if org_changeset exists means ingestion is done
    if org_changeset:
        # if published successfully it means synced
        finished = org_changeset.publish_job_finished and not org_changeset.publish_job_running
        successful = not org_changeset.publish_job_failed and not org_changeset.publish_changeset_failed

        if finished and successful:
            status = CHANGESET_STATUS_SYNCED
            synced_at = org_changeset.publish_finished_at.replace(microsecond=0).isoformat()
        else:
            if not finished:
                status = CHANGESET_STATUS_SYNCING
            else:
                status = CHANGESET_STATUS_ERROR

    # ingestion is still in progress
    else:
        if org.status == CONNECTED:
            status = CHANGESET_STATUS_SYNCING
        elif org.status == DISCONNECTED:
            status = CHANGESET_STATUS_ERROR

    # just in case we have a gap in the above logic (could indicate inconsistent org state also)
    if status == "unknown":
        logging.error("could not determine changeset status for {}:{}".format(org_uid, changeset))

    payload = {
        "meta": {
            "version": "2.0.0",
            "data_source_id": org_uid
        },
        "data": [
            {
                "type": "changeset_status",
                "id": changeset_id,
                "relationships": {
                    "sync_status": {
                        "data": {
                            "type": "changeset_sync_status",
                            "id": changeset_id
                        }
                    }
                }
            }
        ],
        "included": [
            {
                "type": "changeset_sync_status",
                "id": changeset_id,
                "attributes": {
                    "status": status,
                    "synced_at": synced_at
                }
            }
        ]
    }

    logging.info("changeset status for {}: {}".format(changeset_id, payload))

    return payload

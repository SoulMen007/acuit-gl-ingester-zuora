"""
Utilities for management of changeset lifecycle. This should be provider agnostic.
"""

import logging
import json
from datetime import datetime, timedelta
from google.appengine.ext import ndb
from app.services.ndb_models import Org, OrgChangeset, Item
from app.utils.pubsub_utils import (
    CHANGESET_STATUS_ERROR,
    CHANGESET_STATUS_SYNCING,
    CONNECT_STATUS_CONNECTED,
    CONNECT_STATUS_DISCONNECTED,
    CONNECT_STATUS_TYPE,
    LINK_STATUS_TYPE,
    LINK_STATUS_LINKED,
    LINK_STATUS_UNLINKED,
    publish_changeset_status,
    publish_status
)
from app.utils.providers import API_PROVIDERS, MANUAL_PROVIDERS
from app.utils.task_utils import query_to_tasks
from google.appengine.api import taskqueue
from google.appengine.api.taskqueue import Task, Queue


LINKING = 1
CONNECTED = 2
DISCONNECTED = 3

SYNC_INTERVAL = timedelta(minutes=60)


class RateLimitException(Exception):
    """
    Exception to indicate 429 response from gl
    """
    pass


class DisconnectException(Exception):
    """
    Exception to trap all errors which should trigger org disconnection after a few failures.
    """
    pass


class NotFoundException(Exception):
    """
    Raised when a resource (e.g. org) could not be found (404).
    """


class UnauthorizedApiCallException(DisconnectException):
    """
    Exception to indicate 401 response from gl
    """
    pass


class ForbiddenApiCallException(DisconnectException):
    """
    Exception to indicate 403 reponse from gl
    """
    pass


class InvalidGrantException(DisconnectException):
    """
    Exception to indicate invalid_grant response from gl
    """
    pass


class MissingProviderConfigException(DisconnectException):
    """
    Raised when an Org has no ProviderConfig
    """
    pass


class MismatchingFileConnectionAttempt(Exception):
    """
    Exception to indicate an org is being re-linked but the GL file being connected is different to the one the org was
    initially linked to. This is done to prevent mixing up data from different GL files inside one org.
    """
    def __init__(self, org):
        Exception.__init__(self)
        self.org = org


class FailedToGetCompanyName(Exception):
    """
    An exception representing failure to get company name during the linking process (the name gets passed back to the
    client).
    """
    pass


class FailedToGetIdentifier(Exception):
    """
    An exception representing failure to get the identifier for an org. (e.g ShortCode for Xero)
    """
    def __init__(self, org):
        Exception.__init__(self)
        self.org = org


class AuthCancelled(Exception):
    """
    An exception representing the user cancelling the oAuth flow when connecting their file.
    """
    def __init__(self, org):
        Exception.__init__(self)
        self.org = org


def create_manual_provider_org(org_uid, provider):
    """
    Creates the Org entry for a non-API based provider. Treates the org linked and connected.

    Args:
        org_uid(str): org identifier
        provider(str): data provider (eg. 'uploader')
    """
    now = datetime.utcnow()

    Org(
        id=org_uid,
        provider=provider,
        status=CONNECTED,
        linked_at=now,
        connected_at=now
    ).put()

    publish_status(org_uid, LINK_STATUS_TYPE, LINK_STATUS_LINKED)
    publish_status(org_uid, CONNECT_STATUS_TYPE, CONNECT_STATUS_CONNECTED)


def init_all_updates():
    """
    Initialises update cycle for each connected org by putting a task onto the update queue (which ends up calling
    init_new_changeset(org_uid)).
    """
    count = query_to_tasks(
        query=Org.query(
            Org.status == CONNECTED,
            Org.last_update_cycle_completed_at < datetime.utcnow() - SYNC_INTERVAL,
            Org.provider.IN(API_PROVIDERS)
        ).order(-Org.last_update_cycle_completed_at, Org.key), # Queries involving IN need to be ordered by key
        queue=Queue('adapter-update'),
        task_generator=lambda key: Task(url='/adapter/{}/init_update'.format(key.string_id())
    ))

    logging.info("queued {} tasks for a sync update".format(count))


@ndb.transactional(retries=0)
def init_update(org_uid):
    """
    Initialises update cycle for an org.

    This function will initialise a new changeset if no changeset is in progress, or resume the current changeset if
    there is one in progress. There are a few different states that an sync can be in, this function handles each of:
    - no changeset in progress: create a new changeset and create a task on adapter-update queue
    - a changeset in progress exists
      - no task exists on adapter-update queue (after getting auth issues for a while): create the task
      - a task exists on adapter-update queue (user does re-connects the org): no nothing

    A changeset is an increasing integer, identifying a sync cycle for an org (a sync cycle is a 'pull' of all endpoints
    for an org).

    This function is the only function which should be used to start/resume a new sync cycle. It ensures no current
    cycle is running before starting a new one, and does so by using a transaction which spans the database and task
    queue.  Ensuring that only one sync cycle is running at a time is important because there is nothing stopping two
    concurrent sync cycles trying to refresh org credentials at the same time and lose the refresh token (then the file
    can't be synced without user doing the auth flow again). A sync cycle pulls endpoints serially so there is no danger
    of refresh key corruption if only one sync cycle is running.
    """
    org = Org.get_by_id(org_uid)
    changeset = org.changeset

    is_finished = org.changeset_started_at and org.changeset_completed_at
    not_started = not org.changeset_started_at and not org.changeset_completed_at

    if is_finished or not_started:
        next_changeset = changeset + 1
        logging.info("initializing update cycle with changeset {} for org {}".format(next_changeset, org_uid))
        org.changeset = next_changeset
        org.changeset_started_at = datetime.utcnow()
        org.changeset_completed_at = None
        org.update_cycle_active = True
        org.put()

        taskqueue.add(
            queue_name='adapter-update',
            target='adapter',
            url='/adapter/{}/{}/update'.format(org.provider, org.key.string_id()),
            transactional=True
        )

        publish_changeset_status(org_uid, org.changeset, CHANGESET_STATUS_SYNCING)

    else:
        logging.info("update cycle in progress for org {} with changeset {}".format(org_uid, org.changeset))

        if org.update_cycle_active:
            logging.info("update cycle is active (update task exists), not adding a new one")
        else:
            logging.info("update cycle is not active (no update task exists), adding a new one")
            taskqueue.add(
                queue_name='adapter-update',
                target='adapter',
                url='/adapter/{}/{}/update'.format(org.provider, org.key.string_id()),
                transactional=True
            )
            org.update_cycle_active = True
            org.put()

            publish_changeset_status(org_uid, org.changeset, CHANGESET_STATUS_SYNCING)


def add_update_task(provider, org_uid, payload={}):
    """
    Utility function to put a task onto the update queue.

    Args:
        provider(str): The provider
        org_uid(str): org identifier
    """
    taskqueue.add(
        queue_name='adapter-update',
        target='adapter',
        url='/adapter/{}/{}/update'.format(provider, org_uid),
        params=payload
    )


@ndb.transactional(xg=True)
def complete_changeset(org_uid):
    """
    Marks a changeset complete by setting changeset_completed_at for an org in the Org datastore kind.  This is called
    once the provider specific sync manager indicates that there is no more data to be pulled.

    This function also writes the changeset record to OrgChangeset kind. OrgChangeset kind keeps record of all
    changesets (as opposed to Org kind which only tracks ingestion status the current changeset for an org).
    OrgChangeset is used by the orchestrator service to coordinate publishing of the completed changesets.

    In case this is the initial sync (first changeset), we kick off a separate publish job immediately for it.

    Args:
        org_uid(str): org identifier
    """
    now = datetime.utcnow()

    org = Org.get_by_id(org_uid)
    org.changeset_completed_at = now
    org.update_cycle_active = False
    org.last_update_cycle_completed_at = now
    org.put()

    changeset = OrgChangeset(
        org_uid=org_uid,
        provider='qbo',
        changeset=org.changeset,
        ingestion_started_at=org.changeset_started_at,
        ingestion_completed_at=now,
        publish_job_running=False,
        publish_job_finished=False,
        publish_job_count=0
    )

    changeset.put()

    if org.changeset == 0:
        taskqueue.add(
            queue_name='create-publish-job',
            target='orchestrator',
            url='/orchestrator/create_publish_job_task',
            payload=json.dumps({'job_params': {'org_changeset_ids': [changeset.key.id()]}}),
            transactional=True
        )
        logging.info("requesting publish after initial sync for org {}".format(org_uid))

    logging.info("completed changeset {} for org {}".format(org.changeset, org_uid))


def get_items(org_uid, changeset, endpoint, item_ids):
    """
    Retrieves Item objects in bulk for a given org/changeset/endpoint.

    Args:
        org_uid(str): org identifier
        changeset(int): update cycle identifier
        endpoint(str): endpoint which the item came from (eg. 'Invoice', 'Payment')
        item_ids(list(str)): list of item ids to retrieve

    Returns:
        list(Item): list of Item objects
    """
    keys = [
        ndb.Key(Item, "{}_{}_{}_{}".format(org_uid, changeset, endpoint, item_id))
        for item_id in item_ids
    ]
    return ndb.get_multi(keys)


def create_items(org_uid, provider, changeset, endpoint, item_id, data):
    """
    Creates items containing raw endpoint response ready to be saved into Item data kind (Item acts as raw endpoint
    cache and is heavily used by the normalisation part of the data ingestion pipeline, dependent items needed for
    normalisation are resolved from here as opposed to going back to the providers API).

    Two instances of Item are created: one with the actual changeset during which the items was ingested, and one with
    changeset of -1. This allows for the latest version of an item to be easily retrieved (an invoice might be ingested
    as part of one changeset, but if it gets updated it will get ingested again as part of another changeset).

    Args:
        org_uid(str): org identifier
        provider(str): data provider (eg. 'qbo', 'xerov2')
        changeset(int): update cycle identifier
        endpoint(str): endpoint which the item came from (eg. 'Invoice', 'Payment')
        item_id(str): id of the item as is in the source system (provider)
        data(object): item payload as provided by the provider's api (eg. output of the invoice endpoint)

    Returns:
        list(ndb.Model): a list of Item instances ready to be saved
    """
    datastore_item_id = "{}_{}_{}_{}".format(org_uid, changeset, endpoint, item_id)
    changeset_item = Item(
        id=datastore_item_id,
        org_uid=org_uid,
        provider=provider,
        changeset=changeset,
        endpoint=endpoint,
        item_id=item_id,
        data=data
    )

    latest_version_changeset = -1
    datastore_item_id = "{}_{}_{}_{}".format(org_uid, latest_version_changeset, endpoint, item_id)
    latest_version = Item(
        id=datastore_item_id,
        org_uid=org_uid,
        provider=provider,
        changeset=latest_version_changeset,
        endpoint=endpoint,
        item_id=item_id,
        data=data
    )

    return [changeset_item, latest_version]


def save_items(objects):
    """
    Saves a bunch of ndb objects to datastore as fast as possible.

    Args:
        objects(list(ndb.Model)): a list of ndb model class instances to save
    """
    ndb.put_multi(objects)


def is_changeset_in_progress(org):
    """
    Checks if an org has a changeset in progress.
     Args:
        org(Org): an Org object for which the check should be conducted
    """
    return org.changeset_started_at and not org.changeset_completed_at


@ndb.transactional
def mark_as_disconnected(org_uid, deactivate_update_cycle):
    """
    Flags an org as disconnected by changing its status to DISCONNECTED and completing current changeset. This is useful
    if the sync gives up because of authentication issues with the provider for example. This does not forcibly
    disconnect the org by deleting the auth keys.

    Publishes an error status for changeset currently being ingested.

    Args:
        org_uid(str): org identifier
        deactivate_update_cycle(bool): indicates if the update_cycle_active flag should be set to false
    """
    logging.info("marking the org as disconnected (status value {})".format(DISCONNECTED))
    org = Org.get_by_id(org_uid)
    org.status = DISCONNECTED

    if deactivate_update_cycle:
        org.update_cycle_active = False

    org.put()
    publish_status(org_uid, CONNECT_STATUS_TYPE, CONNECT_STATUS_DISCONNECTED)

    if is_changeset_in_progress(org):
        logging.info("publishing error changeset status for changeset {}:{}".format(org_uid, org.changeset))
        publish_changeset_status(org_uid, org.changeset, CHANGESET_STATUS_ERROR)


@ndb.transactional
def mark_as_connected(org_uid, also_linked=False):
    """
    Flags an org as connected. The org will get included in update cycles from this point.

    Args:
        org_uid(str): org identifier
    """
    logging.info("marking the org as connected (status value {})".format(CONNECTED))
    org = Org.get_by_id(org_uid)
    org.status = CONNECTED

    if also_linked:
        org.linked_at = datetime.utcnow()

    org.connected_at = datetime.utcnow()
    org.put()

    if also_linked:
        publish_status(org_uid, LINK_STATUS_TYPE, LINK_STATUS_LINKED)

    publish_status(org_uid, CONNECT_STATUS_TYPE, CONNECT_STATUS_CONNECTED)

    if is_changeset_in_progress(org):
        logging.info("publishing syncing changeset status for changeset {}:{}".format(org_uid, org.changeset))
        publish_changeset_status(org_uid, org.changeset, CHANGESET_STATUS_SYNCING)


def perform_disconnect(org_uid):
    logging.info("disconnecting the org explicitly")

    org = Org.get_by_id(org_uid)

    if not org:
        logging.info("org {} not found".format(org_uid))
        raise NotFoundException("org {} not found".format(org_uid))

    publish_status(org_uid, LINK_STATUS_TYPE, LINK_STATUS_UNLINKED)
    mark_as_disconnected(org_uid=org_uid, deactivate_update_cycle=False)

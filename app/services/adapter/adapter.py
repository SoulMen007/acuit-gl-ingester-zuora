"""
Flask app providing endpoints to execute steps of serial data sync. These are to be invoked by cron and task queues.
"""

import logging
from google.appengine.api import taskqueue
from flask import Flask, request, jsonify
from app.utils import sync_utils
from app.utils.auth import check_api_key, UnauthorizedError
from app.utils.sync_utils import DisconnectException, RateLimitException, CONNECTED
from app.clients import client_factory
from app.services.ndb_models import Org, OrgChangeset
from app.services.middlewares import AppEngineMiddleware

app = Flask(__name__)

# use the maximum urlfetch timeout, in case api takes a while to respond
app.wsgi_app = AppEngineMiddleware(app.wsgi_app, 60)


def prefix(route):
    """
    Helper to format a Flask route to work with dispatch.yaml.

    Args:
        route(str): route to be formatted

    Returns:
        str: formatted route to work with dispatch.yaml
    """
    return '/adapter{}'.format(route)


@app.route(prefix('/<string:org_uid>/status'))
@check_api_key
def status(org_uid):
    """
    Retrieve org status.

    Args:
        org_uid(str): org identifier

    Returns:
        (str, int): http response
    """
    def date_str(date):
        """
        Formats a date into a string (handles None values also).

        Args:
            date(date|datetime): date to be formatted

        Returns:
            str: formatted date
        """
        if date is None:
            return None

        return date.isoformat() + 'Z'

    org = Org.get_by_id(org_uid)

    if not org:
        logging.info("org {} not found".format(org_uid))
        return '', 404

    changeset = OrgChangeset.query(
            OrgChangeset.org_uid == org_uid,
            OrgChangeset.publish_job_finished == True,
            OrgChangeset.publish_job_failed == False
        ).order(
            -OrgChangeset.publish_finished_at
        ).fetch(1)

    # first publish happens only when all the data is ingested, so if the first publish happened the org is synced
    synced = False
    if changeset:
        synced = True

    # synced_at is the ingestion completion time of the last changeset that got published
    synced_at = None
    if changeset:
        synced_at = changeset[0].ingestion_completed_at

    status_payload = {
        'synced': synced,
        'synced_at': date_str(synced_at),
        'connected': org.status == CONNECTED,
        'updating': org.changeset_started_at is not None and org.changeset_completed_at is None,
        'source': org.provider,
        'id': org_uid
    }

    logging.info("org status: {}".format(status_payload))

    return jsonify(status_payload), 200

@app.route(prefix('/init_all_updates'))
def init_all_updates():
    """
    Endpoint that initiates data pull for all orgs.

    Under the covers it calls init_update endpoint via task queues for every org.

    Returns:
        (str, int): http response
    """
    logging.info("initializing update cycles for all connected orgs")
    sync_utils.init_all_updates()
    return '', 204


@app.route(prefix('/<string:org_uid>/init_update'), methods=['POST'])
def init_update(org_uid):
    """
    Endpoint that initiates data pull for a specific org.

    Under the covers it does bookkeeping for the org's changeset and invokes the update endpoint via task queues.

    Args:
        org_uid(str): org identifier

    Returns:
        (str, int): http response
    """
    logging.info("initializing update cycle for org {}".format(org_uid))
    sync_utils.init_update(org_uid)
    return '', 204


@app.route(prefix('/<string:provider>/<string:org_uid>/update'), methods=['POST'])
def update(provider, org_uid):
    """
    The main update loop for org updates.

    When invoked, this endpoint instantiates a provider-specific sync management class with an org identifier, and calls
    the next() method on the instance. The sync management class is expected to manage the state of the sync for the
    org. This endpoint calls itself via task queues, until the sync management class reports that the sync has been
    completed. If this task chain is terminating for watever reason, it is important that the update_cycle_active flag
    is set to false on the Org object.

    The sync management class can provide a payload to be carried over to the subsequent next() call.

    Args:
        org_uid(str): org identifier

    Returns:
        (str, int): http response
    """

    sync_state = client_factory.get_sync_state(provider)(org_uid)

    try:
        complete, next_payload = sync_state.next(request.form)

    except DisconnectException:

        # mark the org as disconnected if the api responds with a 401 for a while (4 attempts, which is around 15
        # minutes with retry config for this queue). this check is quite simple for now and non-401s can lead to a
        # disconnect because we're not keeping track of the reason for each task retry, but this seems unlikely to
        # happen and we will recover as there is a long-term re-connect attempt loop running on the 'reconnect' task
        # queue.

        exec_count = int(request.headers.get('X-AppEngine-TaskExecutionCount'))
        if exec_count > 3:
            logging.info("api calls are failing due to authorization errors, marking as disconnected")
            sync_utils.mark_as_disconnected(org_uid=org_uid, deactivate_update_cycle=True)
            taskqueue.add(queue_name='reconnect', target='adapter', url='/adapter/{}/reconnect'.format(org_uid))
            return '', 204

        logging.info("got an authorization error, will try again")
        return '', 503

    # allow sync management class to finalise the update loop
    if complete:
        sync_utils.complete_changeset(org_uid)
    else:
        sync_utils.add_update_task(provider, org_uid, next_payload)

    return '', 204


@app.route(prefix('/<string:org_uid>/reconnect'), methods=['POST'])
def reconnect(org_uid):
    """
    Endpoint to facilitate long term org re-connection loop.

    Normal update process will mark an org as disconnected after getting 401s from the gl api after about 15 minutes,
    but sometimes a gl just returns 401 for a while. This long-term re-connect loop will make an api call to the gl
    every few hours, and update the status of the org to connected if the api call is successful. from that point on
    normal update cycle will resume for this org.
    """
    org = Org.get_by_id(org_uid)

    # the user could have connected the org manually by now
    if org.status == CONNECTED:
        logging.info("org is connected, nothing to do, resolving this task")
        return '', 204

    # 42 attempts is about a week with the current queue config (4 hours between attempts)
    exec_count = int(request.headers.get('X-AppEngine-TaskExecutionCount'))
    if exec_count > 42:
        logging.info("reached maximum number of reconnect attempts, giving up")
        return '', 204

    logging.info("checking connection status (check number {})".format(exec_count))

    try:
        if client_factory.get_api_session(org.provider, org_uid).is_authenticated():
            logging.info("made a successful api call, marking the org as connected")
            sync_utils.mark_as_connected(org_uid)
            sync_utils.init_update(org_uid)
            return '', 204
    except DisconnectException as e:
        logging.exception("failed reconnecting to client.", e)

    logging.info("could not make a successful api call, leaving org as disconnected, will try again")
    return '', 423


@app.errorhandler(RateLimitException)
def handle_rate_limit_exception(error):
    """
    Error handler which returns a 429 response when rate limit is reached for a GL. This is done to prevent these rate
    limit exceptions from causing 500s as handling rate limits is part of regular operation.

    Args:
        error(Exception): the exception raised down the call stack somewhere

    Returns:
        (str, int): redirect back to the client if the redirect url is specified, or just json error if not
    """
    return '', 429


@app.errorhandler(UnauthorizedError)
def handle_unauthorized_error(error):
    """
    Handles UnauthorizedError exception.

    Args:
        error(Exception): the exception being handled

    Returns:
        (str, int): response body and status
    """
    msg = "This request could not be authorized. Please check that the 'Authorization' header is present and valid."
    return msg, 401

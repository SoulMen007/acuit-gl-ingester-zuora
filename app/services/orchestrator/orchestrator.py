"""
Service responsible for orchestration of publishing jobs.
"""

import logging
from datetime import datetime
from itertools import groupby
from operator import attrgetter
from google.appengine.ext import ndb
from google.appengine.ext.ndb import Key
from google.appengine.api.taskqueue import Task, Queue
from flask import Flask, request
from flask.json import dumps, loads
from app.utils.dataflow_utils import start_template, get_job
from app.utils.pubsub_utils import (
    CHANGESET_STATUS_ERROR,
    CHANGESET_STATUS_SYNCED,
    CHANGESET_STATUS_SYNCING,
    publish_changeset_status
)
from app.utils.task_utils import items_to_tasks
from app.utils.datastore_utils import emit_items
from app.services.ndb_models import Org, OrgChangeset


FINAL_STATES = ['JOB_STATE_DONE', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED', 'JOB_STATE_UPDATED', 'JOB_STATE_DRAINED']
SUCCESS_STATE = 'JOB_STATE_DONE'


app = Flask(__name__)


def prefix(route):
    """
    Helper to format a Flask route to work with dispatch.yaml.

    Args:
        route(str): route to be formatted

    Returns:
        str: formatted route to work with dispatch.yaml
    """
    return '/orchestrator{}'.format(route)


@app.route(prefix('/publish'), methods=['GET', 'POST'])
def start_publish():
    """
    Kicks off a dataflow template to publish normalised data. The jobs are created via a task queue task, passing the
    ID of the OrgChangesets which need to be published.

    This endpoint is invoked by a regular cron job or by a request from the admin UI, and takes an additional parameter
    which allows for each org to be published by a separate dataflow job (this is useful for isolation of an org which
    causes the whole publish job to fail).

    Returns:
        (str, int): http response
    """
    logging.info("about to kick off a publish dataflow job")

    per_org = request.form.get('per_org') == '1'
    if per_org:
        logging.info("publish job per org requested")

    # we want to publish changesets which:
    # - have newly been ingested (publish not running and not finished)
    # - OR have been attempted to be published but failed
    #   - due to the whole job failing
    #   - OR publish of the individual changeset failing
    org_changesets_query = OrgChangeset.query(
        ndb.OR(
            ndb.AND(
                OrgChangeset.publish_job_running == False,
                OrgChangeset.publish_job_finished == False
            ),
            ndb.AND(
                OrgChangeset.publish_job_running == False,
                OrgChangeset.publish_job_finished == True,
                ndb.OR(
                    OrgChangeset.publish_job_failed == True,
                    OrgChangeset.publish_changeset_failed == True
                )
            )
        )
    ).order(OrgChangeset.key)

    org_changesets = list(emit_items(org_changesets_query))

    # Query any currently running org changesets
    running_org_changesets_query = OrgChangeset.query(
        OrgChangeset.publish_job_running == True
    )
    running_org_changesets = list(emit_items(running_org_changesets_query))

    running_orgs = list(set([running_org_changeset.org_uid for running_org_changeset in running_org_changesets]))

    # Filter any org changesets that already have a running changeset for that org
    gated_org_changesets = filter(lambda oc: oc.org_uid not in running_orgs, org_changesets)

    if len(gated_org_changesets) != len(org_changesets):
        filtered_ocs = filter(lambda oc: oc.org_uid in running_orgs, org_changesets)
        filtered_oc_tuples = [(oc.org_uid, oc.changeset) for oc in filtered_ocs]

        logging.info("stopped these changesets from being published as job already running for the org: {}".format(
            filtered_oc_tuples
        ))

    if not gated_org_changesets:
        logging.info("nothing to publish")
        return '', 204

    # remove changesets for blacklisted orgs
    blacklisted_orgs = {}
    org_changesets_to_publish = []
    for org_changeset in gated_org_changesets:
        org = blacklisted_orgs.get(org_changeset.org_uid, Org.get_by_id(org_changeset.org_uid))
        if org and org.publish_disabled:
            blacklisted_orgs[org.key.string_id()] = org
        else:
            org_changesets_to_publish.append(org_changeset)

    to_publish = []

    if per_org:
        org_changesets_sorted = sorted(org_changesets_to_publish, key=attrgetter('org_uid'))
        for org_uid, changesets in groupby(org_changesets_sorted, key=attrgetter('org_uid')):
            to_publish.append({
                'org_uid': org_uid,
                'org_changeset_ids': [changeset.key.id() for changeset in changesets]
            })
    else:
        to_publish.append({
            'org_changeset_ids': [changeset.key.id() for changeset in org_changesets_to_publish]
        })

    logging.info("have {} publish tasks to create".format(len(to_publish)))

    items_to_tasks(
        items=to_publish,
        queue=Queue('create-publish-job'),
        task_generator=lambda item: Task(
            url='/orchestrator/create_publish_job_task',
            payload=dumps({'job_params': item})
        )
    )

    return '', 204


@app.route(prefix('/create_publish_job_task'), methods=['POST'])
def create_publish_job_task():
    """
    Creates dataflow publish jobs for each OrgChangeset specified in the request body.  The org/changeset pairs to be
    published are passed in as arguments to the dataflow job, and are determined by looking at OrgChangeset datastore
    kind.

    Returns:
        (str, int): http response
    """
    logging.info("got a request to create a publish job")

    job_params = loads(request.data).get('job_params', {})
    logging.info("job params in request: {}".format(job_params))

    now = datetime.utcnow()
    job_name = 'publish_job_{}'.format(now.isoformat())

    org_changeset_ids = job_params.get('org_changeset_ids', [])
    org_changesets = ndb.get_multi([Key(OrgChangeset, _id) for _id in org_changeset_ids])
    to_publish = ','.join(["{}:{}".format(row.org_uid, row.changeset) for row in org_changesets])
    job_params = {'orgChangesets': to_publish}
    logging.info("job params: {}".format(job_params))

    try:
        job_details = start_template('sync', job_name, job_params)
        job_id = job_details['id']
    except Exception as exc:
        logging.exception("failed to create dataflow job")

        for org_changeset in org_changesets:
            msg = "publishing error status for changeset {}:{} because dataflow job failed to be created"
            logging.info(msg.format(org_changeset.org_uid, org_changeset.changeset))
            publish_changeset_status(org_changeset.org_uid, org_changeset.changeset, CHANGESET_STATUS_ERROR)

        raise exc

    logging.info("job scheduled with id: {}".format(job_id))

    # mark the changesets as running
    for org_changeset in org_changesets:
        org_changeset.publish_job_running = True
        org_changeset.publish_job_finished = False
        org_changeset.publish_job_failed = False
        org_changeset.publish_changeset_failed = False
        org_changeset.publish_job_id = job_id
        org_changeset.publish_job_status = None
        org_changeset.publish_job_count += 1
        org_changeset.publish_started_at = now

        # publish changeset status of syncing because this changeset could be in error and is being retried
        publish_changeset_status(org_changeset.org_uid, org_changeset.changeset, CHANGESET_STATUS_SYNCING)

    ndb.put_multi(org_changesets)

    logging.info("job details saved in OrgChangeset")

    return '', 204


@app.route(prefix('/update_changesets'))
def update_changesets():
    """
    Updates OrgChangeset records based on status of the publish job.

    Returns:
        (str, int): http response
    """
    now = datetime.utcnow()
    statuses = {}
    org_changesets = OrgChangeset.query(OrgChangeset.publish_job_running == True).fetch()

    if not org_changesets:
        logging.info("no changesets to update")
        return '', 204

    for org_changeset in org_changesets:
        if org_changeset.publish_job_id not in statuses:
            try:
                statuses[org_changeset.publish_job_id] = get_job(org_changeset.publish_job_id)
            except Exception:
                logging.exception("failed to retrieve job status from dataflow api")
                statuses[org_changeset.publish_job_id] = {'currentState': 'STATUS_API_CALL_FAILED'}

        job_status = statuses[org_changeset.publish_job_id]
        job_status = job_status.get('currentState', 'STATUS_API_RESPONSE_ERROR')
        org_changeset.publish_job_status = job_status

        # update the changeset details if the publish job status will not change any more
        if job_status in FINAL_STATES:
            org_changeset.publish_job_finished = True
            org_changeset.publish_job_running = False
            org_changeset.publish_job_failed = job_status != SUCCESS_STATE
            org_changeset.publish_finished_at = now

            if job_status == SUCCESS_STATE:
                publish_changeset_status(org_changeset.org_uid, org_changeset.changeset, CHANGESET_STATUS_SYNCED)
            else:
                publish_changeset_status(org_changeset.org_uid, org_changeset.changeset, CHANGESET_STATUS_ERROR)

        logging.info("updating org changeset ({}, {}) with job status {}".format(
            org_changeset.org_uid,
            org_changeset.changeset,
            org_changeset.publish_job_status
        ))

        org_changeset.put()

    return '', 204


@app.route(prefix('/clean_old_changeset_items'))
def clean_historic_items():

    now = datetime.utcnow()
    job_name = 'cleanup_job_{}'.format(now.isoformat())

    job_params = {'dryRun': 'false'}
    job_details = start_template('cleanup', job_name, job_params)
    job_id = job_details['id']
    logging.info('job scheduled with id: {}'.format(job_id))

    return '', 204

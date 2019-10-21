"""
Flask app providing org management screens for admins.
"""

import logging
import os
from flask import Flask, request, redirect, flash, render_template, escape
from app.services.ndb_models import Org, OrgChangeset
from app.utils import sync_utils
from app.utils.sync_utils import CONNECTED
from google.appengine.datastore.datastore_query import Cursor
from google.appengine.api import taskqueue
from google.appengine.api.taskqueue import Queue, Task
from google.appengine.ext import ndb
from app.sync_states.qbo.endpoints import ENDPOINTS
from app.sync_states.qbo.ndb_models import QboSyncData
from app.utils.item_types import ITEM_TYPES
from app.utils.dataflow_utils import start_template
from app.utils.task_utils import query_to_tasks


app = Flask(__name__)
app.secret_key = "super secret key"


START_OF_TIME = '1970-01-01T00:00:00'


def prefix(route):
    """
    Helper to format a Flask route to work with dispatch.yaml.

    Args:
        route(str): route to be formatted

    Returns:
        str: formatted route to work with dispatch.yaml
    """
    return '/admin{}'.format(route)


def _get_changesets(orgs):
    """
    Gets a textual representation of current changeset status for a list of orgs.

    Args:
        orgs(list): a list of orgs for which status should be displayed

    Returns:
        dict: dict of textual changeset status, key'd by the org_uid
    """
    def to_desc(org):
        if org.changeset_completed_at:
            return 'complete'
        if org.changeset_started_at:
            return 'running'
        return 'not started'

    return {org.key.string_id(): "{} ({})".format(org.changeset, to_desc(org)) for org in orgs}


@app.route(prefix('/'), methods=['GET', 'POST'])
def org_list():
    """
    Renders the org listing page.

    Returns:
        (str, int): org listing page
    """
    cursor = Cursor(urlsafe=request.args.get('cursor'))
    orgs, next_cursor, more = Org.query().order(-Org.created_at).fetch_page(20, start_cursor=cursor)

    connect_org_uid = request.args.get('connect_org_uid')
    message = None

    if connect_org_uid:
        error_code = request.args.get('error_code')
        if error_code == 'cancelled':
            message = "Failed to connect {} - OAuth flow cancelled".format(connect_org_uid)
        if error_code == 'source_mismatch':
            message = "Failed to connect {} - attempt to re-connect to different file".format(connect_org_uid)
        if error_code == 'invalid_credentials':
            message = 'Failed to connect {} - Invalid username or password'.format(connect_org_uid)
        else:
            message = "{} has been connected".format(connect_org_uid)

    show_connect = os.environ.get('SHOW_CONNECT_BUTTON', False) == "1"

    return render_template(
        'org_list.html',
        orgs=orgs,
        next_cursor=next_cursor,
        more=more,
        changesets=_get_changesets(orgs),
        message=message,
        show_connect=show_connect
    ), 200


@app.route(prefix('/handle_connect_search'), methods=['POST'])
def handle_connect_search():
    """
    Handler for the org search/connect form. Ability to connect a new org provided here is to make local development
    easier (instead of hitting magic URLs in the browser).

    Returns:
        (str, int): search results page, or a redirect to provider for auth flow
    """

    provider = request.form.get("provider")

    # handle connect
    if request.form.get('connect'):
        org_uid = request.form.get('org_uid')

        if not org_uid:
            flash("Org UID is required")
            return redirect(prefix('/'))

        return redirect(
            "/linker/{}/{}/connect?redirect_url={}&app_family=local_host_family".format(
                provider,
                org_uid,
                "{}admin/?connect_org_uid={}".format(request.url_root, org_uid)
            )
        )

    # handle search
    elif request.form.get('search'):
        org_uid = request.form.get('org_uid')
        if not org_uid:
            flash("Org UID is required")
            return redirect(prefix('/'))
        else:
            org = Org.get_by_id(org_uid)
            if not org:
                orgs = []
                message = 'Org {} not found'.format(org_uid)
            else:
                orgs = [org]
                message = None

        return render_template(
            'org_list.html',
            orgs=orgs,
            next_cursor=None,
            more=False,
            changesets=_get_changesets(orgs),
            message=message
        ), 200

    return redirect(prefix('/'))


@app.route(prefix('/sync'), methods=['POST'])
def sync():
    """
    Kicks off a sync of one or all orgs.
    """
    if request.form.get('org_uid'):
        org_uid = request.form.get('org_uid')
        sync_utils.init_update(org_uid)
        flash("Sync for {} kicked off".format(org_uid))
        return redirect(prefix('/'))
    else:
        sync_utils.init_all_updates()
        flash("Sync for all orgs kicked off")
        return redirect(prefix('/commands'))


@app.route(prefix('/select_endpoints'), methods=['POST'])
def select_endpoints():
    """
    Renders a page with endpoint selection (for the purpose of 'resetting' these endpoints and getting all the data
    ingested from scratch for those).

    Returns:
        (str, int): endpoints select page
    """
    # TODO: ENDPOINTS is hard coded to qbo endpoints, this needs to be based on Org.provider
    return render_template('select_endpoints.html', endpoints=ENDPOINTS, org_uid=request.form.get('org_uid')), 200


@app.route(prefix('/reset_endpoints'), methods=['POST'])
def reset_endpoints():
    """
    Handler which creates reset endpoint tasks for selected endpoints/orgs.
    """
    endpoint_indexes = request.form.getlist('endpoint_index')
    org_uid = request.form.get('org_uid')

    if not endpoint_indexes:
        flash("At least one endpoint is required")
        return render_template('select_endpoints.html', endpoints=ENDPOINTS, org_uid=org_uid), 200

    if org_uid:
        taskqueue.add(
            target='admin',
            url='/admin/reset_endpoints_task/{}'.format(org_uid),
            params={'endpoint_index': endpoint_indexes}
        )

        flash("Kicked off reset of {} endpoints for {}".format(len(endpoint_indexes), org_uid))

        return redirect(prefix('/'))
    else:
        count = query_to_tasks(
            query=Org.query(Org.status == CONNECTED),
            queue=Queue('admin'),
            task_generator=lambda key: Task(
                url='/admin/reset_endpoints_task/{}'.format(key.string_id()),
                params={'endpoint_index': endpoint_indexes}
            )
        )

        flash("Kicked off reset of {} endpoints for {} orgs".format(len(endpoint_indexes), count))

        return redirect(prefix('/commands'))


@app.route(prefix('/reset_endpoints_task/<string:org_uid>'), methods=['POST'])
def reset_endpoints_task(org_uid):
    """
    Processes org reset task from the task queue (clears endpoint state to cause the next sync to fetch all the data,
    and creates a task on the update queue to kick of the sync cycle for the org).
    """
    org = Org.get_by_id(org_uid)

    if (org.changeset_started_at and not org.changeset_completed_at) or org.update_cycle_active:
        logging.info("org syncing at the moment, will try again later")
        return '', 423

    endpoint_indexes = request.form.getlist('endpoint_index')
    logging.info("resetting markers for org {} and endpoints {}".format(org_uid, endpoint_indexes))

    # TODO: this is a hack, this should be delegated to a qbo class, instantiated via a factory from the org provider
    sync_data = QboSyncData.get_by_id(org_uid)

    if not sync_data:
        logging.warning("could not find sync data")
        return '', 204

    for endpoint_index in [int(_index) for _index in endpoint_indexes]:
        sync_data.markers[endpoint_index] = START_OF_TIME

    sync_data.put()
    sync_utils.init_update(org_uid)

    return '', 204


@app.route(prefix('/select_item_types'), methods=['POST'])
def select_item_types():
    """
    Renders a page with canonical item type selection (for the purpose of 'replaying' these item types on the gl feed
    pubsub. This kicks off the publishing pipeline with selected orgs/item_types as parameters.
    """
    return render_template(
        'select_item_types.html',
        item_types=ITEM_TYPES,
        org_uid=request.form.get('org_uid'),
        action=request.form.get('action')
    ), 200


@app.route(prefix('/replay_item_types'), methods=['POST'])
def replay_item_types():
    """
    Kicks off dataflow replay job for the selected item types and one or all orgs.
    """
    item_types = request.form.getlist('item_type')
    org_uid = request.form.get('org_uid')
    template_name = request.form.get('action')

    if not item_types:
        flash("At least one item type is required")
        return render_template('select_item_types.html', item_types=ITEM_TYPES, org_uid=org_uid), 200

    job_params = {}
    job_params['datatypes'] = ','.join(item_types)

    if org_uid:
        job_params['orgs'] = org_uid
    else:
        job_params['orgs'] = ','.join([key.string_id() for key in Org.query().fetch(keys_only=True)])

    logging.info("starting dataflow template '{}' with params: {}".format(template_name, job_params))

    try:
        flash(escape(str(start_template(template_name, '{} all that is good'.format(template_name), job_params))))
    except Exception as e:
        logging.exception("failed to start dataflow template")
        flash("Failed to start dataflow template with error: {}".format(escape(str(e))))

    if org_uid:
        return redirect(prefix('/'))
    else:
        return redirect(prefix('/commands'))


@app.route(prefix('/changeset_list'), defaults={'org_uid': None})
@app.route(prefix('/changeset_list/<string:org_uid>'))
def changeset_list(org_uid):
    """
    Renders a page which shows all changesets and their status (ingestion and publish). Handles one org or all.

    Args:
        org_uid(str): org identifier

    Returns:
        (str, int): changeset listing page
    """
    cursor = Cursor(urlsafe=request.args.get('cursor'))
    failed = request.args.get('failed') == '1'

    query = OrgChangeset.query()

    if org_uid:
        query = query.filter(OrgChangeset.org_uid == org_uid)

    if failed:
        query = query.filter(
            ndb.OR(
                OrgChangeset.publish_job_failed == True,
                OrgChangeset.publish_changeset_failed == True
            )
        )

    # OR query can't sort by a field
    if failed:
        query = query.order(-OrgChangeset.key)
    else:
        query = query.order(-OrgChangeset.ingestion_completed_at)

    changesets, next_cursor, more = query.fetch_page(20, start_cursor=cursor)

    return render_template(
        'changeset_list.html',
        org_uid=org_uid,
        changesets=changesets,
        next_cursor=next_cursor,
        more=more,
        url_root=request.url_root,
        failed=request.args.get('failed', '0')
    ), 200


@app.route(prefix('/publish_per_org'), methods=['POST'])
def publish_per_org():
    """
    Handles a command to publish all changesets with a publish job per org.
    """
    taskqueue.add(
        queue_name='create-publish-job',
        target='orchestrator',
        url='/orchestrator/publish',
        params={'per_org': 1}
    )

    flash("Requesting publish jobs per org")
    return redirect(prefix('/'))


@app.route(prefix('/commands'))
def commands():
    """
    Renders a screen which allows for org management tasks to be started.

    Returns:
        (str, int): command listing page
    """
    return render_template('commands.html', endpoints=ENDPOINTS), 200

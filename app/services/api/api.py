"""
Flask app providing endpoints to execute steps of serial data sync. These are to be invoked by cron and task queues.
"""

import logging
from flask import Flask, jsonify
from app.utils.status_api import get_status_payload, get_changeset_status_payload
from app.utils.auth import check_api_key, UnauthorizedError
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
    return '/api{}'.format(route)


@app.route(prefix('/data_sources/<string:org_uid>/status'))
@check_api_key
def status(org_uid):
    """
    Retrieve org status.

    Args:
        org_uid(str): org identifier

    Returns:
        (str, int): http response
    """
    return jsonify(get_status_payload(org_uid)), 200


@app.route(prefix('/data_sources/<string:org_uid>/changesets/<int:changeset>/status'))
@check_api_key
def changeset_status(org_uid, changeset):
    """
    Retrieve org status.

    Args:
        org_uid(str): org identifier

    Returns:
        (str, int): http response
    """
    return jsonify(get_changeset_status_payload(org_uid, changeset)), 200


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

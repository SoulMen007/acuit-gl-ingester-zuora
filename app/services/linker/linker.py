"""
Flask app providing endpoints for connection of GLs files via 2 legged auth such as OAuth2.
"""
import json
import logging
import os
from flask import Flask, request, redirect, jsonify, render_template

from app.clients import client_factory
from app.utils.pubsub_utils import publish_status, LINK_STATUS_TYPE, LINK_STATUS_UNLINKED, LINK_STATUS_LINKED
from app.utils.auth import check_api_key, UnauthorizedError
from app.utils.url_utils import append_params
from app.utils.sync_utils import (
    AuthCancelled,
    MismatchingFileConnectionAttempt,
    FailedToGetCompanyName,
    NotFoundException,
    mark_as_connected,
    mark_as_disconnected,
    init_update,
    create_manual_provider_org,
    perform_disconnect,
    FailedToGetIdentifier,
    UnauthorizedApiCallException
)
from app.utils.providers import API_PROVIDERS, MANUAL_PROVIDERS
from app.services.ndb_models import ProviderConfig, Org, UserCredentials

app = Flask(__name__)


def prefix(route):
    """
    Helper to format a Flask route to work with dispatch.yaml.

    Args:
        route(str): route to be formatted

    Returns:
        str: formatted route to work with dispatch.yaml
    """
    return '/linker{}'.format(route)


@app.route(prefix('/<string:provider>/<string:org_uid>/connect'), methods=['GET', 'POST'])
@check_api_key
def connect(provider, org_uid):
    """
    The first endpoint to be invoked by a client wishing to connect a new data source. Redirects the client to the data
    provider authorisation and sets relevant org statuses. The client can pass in a redirect URL to which the user
    should be redirected to after the second step of the auth flow (this url is stored in datastore and used in the
    second step, ie. oauth function).

    Args:
        provider(str): the data provider to which org_uid should be connected to
        org_uid(str): org/connection identifier

    Returns:
        (str, int): redirect to data provider
    """
    logging.info("initiating connect for {} (provider {})".format(org_uid, provider))

    if provider in API_PROVIDERS:
        app_family = request.args.get('app_family')
        if not app_family:
            return 'No app family specified', 422

        provider_config = ProviderConfig.find(provider, app_family)
        if not provider_config:
            return 'No configuration found for provider {} and app family {}'.format(provider, app_family), 422

        session = client_factory.get_authorization_session(provider, org_uid, provider_config, request.args.get('redirect_url'))

        if request.data:
            data = json.loads(request.data)
            username = data.get('username')
            password = data.get('password')
            # No redirect to login page needed if username and password are supplied in body
            return basic_auth(provider, org_uid, username, password)
        else:
            return redirect(session.get_authorization_url())

    if provider in MANUAL_PROVIDERS:
        create_manual_provider_org(org_uid, provider)
        return '', 204

    logging.info("invalid provider '{}' for org '{}'".format(provider, org_uid))
    return '', 404


@app.route(prefix('/<string:provider>/<string:org_uid>/disconnect'), methods=['POST'])
@check_api_key
def disconnect(provider, org_uid):
    try:
        perform_disconnect(org_uid)
    except NotFoundException as ex:
        return ex.message, 404

    return '', 204


@app.route(prefix('/<string:provider>/<string:org_uid>/login'))
def login(provider, org_uid):
    """Renders login page for the provider"""
    return render_template('login.html', provider=provider, org_uid=org_uid), 200


@app.route(prefix('/handle_login'), methods=['POST'])
def handle_login():
    """
    Processes form data from the app hosted login page
    """

    username = request.form.get('username')
    password = request.form.get('password')
    provider = request.form.get('provider')
    org_uid = request.form.get('org_uid')

    return basic_auth(provider, org_uid, username, password)


def basic_auth(provider, org_uid, username, password):
    """
    Handles basic username/password auth flow.
    Users credentials (username/password) are stored in the UserCredentials kind
    TODO: This should be temporary! and only implemented in DEV until vault is integrated

    Args:
        provider(str): The provider
        org_uid(str): The org ID
        username(str): The username
        password(str): The password

    Returns:
        (str): Response text
    """

    # If authenticating for Zuora, get a session cookie and store in OrgCredentials
    if provider == 'zuora':

        # Multi-entity may be enabled, we need to specify it as a header when authenticating
        # TODO: Fix this to work with multiple entities once its figured out how it works.
        entity_id = None
        session = client_factory.get_token_session(provider, org_uid, username, password)

    try:
        session.get_and_save_token()
    except UnauthorizedApiCallException:
        logging.info("got an error - Invalid Credentials".format(provider))
        _abort_link(org_uid)
        return _respond(Org.get_by_id(org_uid), {'error_code': 'invalid_credentials'}, 'not okidoki')

    mark_as_connected(org_uid=org_uid, also_linked=True)

    try:
        data_source_name = client_factory.get_api_session(provider, org_uid).get_company_name()
    except FailedToGetCompanyName:
        # TODO: this should be sent to the client as an error code rather than an empty name
        data_source_name = None

    init_update(org_uid)
    return _respond(Org.get_by_id(org_uid), {'data_source_name': data_source_name}, 'okidoki')


@app.route(prefix('/<string:org_uid>/oauth'))
@app.route(prefix('/oauth'))
def oauth(org_uid=None):
    """
    Endpoint which handles the second step of the oAuth flow. This is where the data provider redirects the user to
    after they complete the auth flow. The payload contains tokens needed to start pulling data, and the state parameter
    identifies which org_uid the user is connecting (the state has been passed in the first step of the auth flow, ie.
    the connect function above).

    Returns:
        (str, int)|str: redirect back to the app if redirect url is supplied, otherwise just say okidoki
    """

    # TODO: Update redirect urls on qbo to include /qbo/
    provider = 'xerov2' if org_uid else 'qbo'
    org_uid = org_uid or request.args.get('state')

    logging.info("processing oauth callback for {}".format(org_uid))

    try:
        session = client_factory.get_token_session(provider, org_uid, request.args)
        session.get_and_save_token()
    except AuthCancelled as exc:
        logging.info("got an error - oauth flow cancelled")
        _abort_link(org_uid)
        return _respond(exc.org, {'error_code': 'cancelled'}, 'not okidoki')
    except MismatchingFileConnectionAttempt as exc:
        logging.info("got an error - mismatching file connection attempt")
        _abort_link(org_uid)
        return _respond(exc.org, {'error_code': 'source_mismatch'}, 'not okidoki')
    except FailedToGetIdentifier as exc:
        logging.info("got an error - failed to get org identifier from {}".format(provider))
        _abort_link(org_uid)
        return _respond(exc.org, {'error_code': 'failed_to_get_identifier'}, 'not okidoki')

    mark_as_connected(org_uid=org_uid, also_linked=True)

    try:
        data_source_name = client_factory.get_api_session(provider, org_uid).get_company_name()
    except FailedToGetCompanyName:
        # TODO: this should be sent to the client as an error code rather than an empty name
        data_source_name = None

    init_update(org_uid)
    return _respond(session.org, {'data_source_name': data_source_name}, 'okidoki')


@app.errorhandler(MismatchingFileConnectionAttempt)
def handle_mismatching_file_connection_attempt(error):
    """
    Error handler which extracts the error message from an exception and passes it back to the client as a parameter.

    Args:
        error(Exception): the exception raised down the call stack somewhere

    Returns:
        (str, int)|str: redirect back to the client if the redirect url is specified, or just json error if not
    """
    if error.org.redirect_url:
        redirect_url = append_params(error.org.redirect_url, {'error_msg': error.message})
        return redirect(redirect_url)
    return jsonify({"error_msg": error.message}), 400


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


def _respond(org, redirect_params, response_text):
    """
    Helper function to redirect back to the app or render a simple response, subject to org.redirect_url being set.

    Args:
        org(app.services.ndb_models.Org): org object
        redirect_params(dict): params to be appended to the redirect url
        response_text(str): text to render in case of no redirect url

    Returns:
        Response: redirect or response text
    """
    if org.redirect_url:
        redirect_url = append_params(org.redirect_url, redirect_params)
        return redirect(redirect_url)

    return response_text


def _abort_link(org_uid):
    """
    Aborts the in process link if an error occurs, disconnecting the org in the process.

    Args:
        org_uid (str): The org ID
    """

    publish_status(org_uid, LINK_STATUS_TYPE, LINK_STATUS_UNLINKED)
    mark_as_disconnected(org_uid=org_uid, deactivate_update_cycle=False)

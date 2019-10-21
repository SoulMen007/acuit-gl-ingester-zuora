"""
Placeholder app for default service.
"""

import logging
import datetime
import json

from flask import Flask, request, redirect
from google.appengine.api import app_identity
from google.appengine.api import urlfetch
import os
from app.services.ndb_models import ProviderConfig

app = Flask(__name__)


@app.route('/cloud-datastore-export')
def cloud_datastore_export():
    logging.info("starting export")

    access_token, _ = app_identity.get_access_token('https://www.googleapis.com/auth/datastore')

    app_id = app_identity.get_application_id()
    timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

    output_url_prefix = request.args.get('output_url_prefix')
    assert output_url_prefix and output_url_prefix.startswith('gs://')

    if output_url_prefix[-1] != '/':
        output_url_prefix += '/' + timestamp
    else:
        output_url_prefix += timestamp

    entity_filter = {
        'kinds': request.args['kind'].split(','),
        'namespace_ids': request.args.get('namespace_id')
    }

    request_data = {
        'project_id': app_id,
        'output_url_prefix': output_url_prefix,
        'entity_filter': entity_filter
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + access_token
    }

    url = 'https://datastore.googleapis.com/v1/projects/%s:export' % app_id

    logging.info("making api call (entity_filter: {}, request_data: {})".format(entity_filter, request_data))

    result = urlfetch.fetch(
        url=url,
        payload=json.dumps(request_data),
        method=urlfetch.POST,
        deadline=60,
        headers=headers
    )

    logging.info("got response with status '{}' and contents '{}'".format(result.status_code, result.content))

    job_state = json.loads(result.content).get('metadata', {}).get('common', {}).get('state')

    if result.status_code == 200 and job_state == "PROCESSING":
        logging.info("export started successfully")
        return '', 204

    logging.info("export failed to start")

    return '', 400


@app.route('/_ah/warmup')
def warmup():

    # Load datastore with provider configs if running locally
    if not os.getenv('SERVER_SOFTWARE', '').startswith('Google App Engine/'):

        if not ProviderConfig.get_by_id('qbo'):
            logging.info('Creating provider config for qbo')

            ProviderConfig(
                id='qbo',
                provider='qbo',
                app_family='local_host_family',
                client_id=os.environ.get('QBO_CLIENT_ID'),
                client_secret=os.environ.get('QBO_CLIENT_SECRET')
            ).put()

        if not ProviderConfig.get_by_id('xerov2'):
            logging.info('Creating provider config for xero')
            ProviderConfig(
                id='xerov2',
                provider='xerov2',
                app_family='local_host_family',
                client_id=os.environ.get('XERO_CONSUMER_KEY'),
                client_secret=os.environ.get('XERO_CONSUMER_SECRET'),
                additional_auth_attributes=json.dumps({'application_type': 'public'})
            ).put()

        if not ProviderConfig.get_by_id('zuora'):
            logging.info('Creating provider config for zuora')
            ProviderConfig(
                id='zuora',
                provider='zuora',
                app_family='local_host_family',
            ).put()

        return '', 204
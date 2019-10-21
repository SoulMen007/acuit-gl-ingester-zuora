"""
Helper classes functions for interacting with the dataflow api
"""
import os
import logging
from datetime import datetime

from google.appengine.api.app_identity import app_identity
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

client = None
gcs_dataflow_path = None

def get_client():
    """
    Singleton getter function for the dataflow api client.

    Returns:
        googleapiclient.discovery.Resource: the client.
    """
    global client
    if client is None:
        client = build('dataflow', 'v1b3')
    return client


def start_template(filename, job_name, params={}, retries=5):
    """
    Starts a dataflow template.

    Args:
        filename (str): The gcs filename for the template.
        job_name (str): The job name to use.
        params (dict): Job parameters.
        retries (int): Remaining retries. Set this to 0 to never retry.

    Returns:
        dict: The job response.
    """

    global gcs_dataflow_path
    if gcs_dataflow_path is None:
        gcs_dataflow_path = 'gs://{}/dataflow'.format(app_identity.get_default_gcs_bucket_name())

    body = {
        'jobName': job_name,
        'environment': {
            'tempLocation': '{}/temp_jobs'.format(gcs_dataflow_path)
        },
        'parameters': params
    }

    request = get_client().projects().locations().templates().launch(
        projectId=app_identity.get_application_id(),
        gcsPath='{}/templates/{}'.format(gcs_dataflow_path, filename),
        location=os.environ.get('DATAFLOW_REGION') or 'us-central1',
        body=body
    )

    logging.info('Starting template...')

    try:
        return request.execute().get('job', {})
    except HttpError as ex:
        if retries > 0:
            logging.warn('Retrying failed request ({} retries remaining)'.format(retries), exc_info=True)
            return start_template(filename, job_name, params, retries - 1)
        else:
            raise ex


def get_job(job_id):
    request = get_client().projects().locations().jobs().get(
        projectId=app_identity.get_application_id(),
        jobId=job_id,
        location=os.environ.get('DATAFLOW_REGION') or 'us-central1'
    )
    return request.execute()

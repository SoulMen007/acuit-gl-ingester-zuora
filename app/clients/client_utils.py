"""
Contains methods used by client classes
"""

import os

BASIC_AUTH_PROVIDERS = {'zuora'}
OAUTH1_PROVIDERS = {'xerov2'}
OAUTH2_PROVIDERS = {'qbo'}

OAUTH1_BASE_REDIRECT_URI = os.environ.get("OAUTH1_BASE_REDIRECT_URI")
OAUTH2_BASE_REDIRECT_URI = os.environ.get("OAUTH2_BASE_REDIRECT_URI")
LOGIN_BASE_REDIRECT_URI = os.environ.get("LOGIN_BASE_REDIRECT_URI")


def get_redirect_uri_for(provider, org_uid=None):
    """
    Returns the redirect URI which changes based on the OAUTH version.

    Args:
        provider (str): The provider (e.g qbo, xero)
        org_uid (str): The org uid

    Returns:
        (str) The redirect URI
    """

    if provider in OAUTH1_PROVIDERS:
        return OAUTH1_BASE_REDIRECT_URI.format(org_uid)
    elif provider in BASIC_AUTH_PROVIDERS:
        return LOGIN_BASE_REDIRECT_URI.format(provider, org_uid)
    else:
        return OAUTH2_BASE_REDIRECT_URI

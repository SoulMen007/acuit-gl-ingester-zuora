"""
This module defines the `check_api_key` function used to authenticate incoming requests.
"""

import logging
from functools import wraps
from flask import request
import os


class UnauthorizedError(Exception):
    """
    Error that occurs when authentication fails.
    """
    def __init__(self):
        super(UnauthorizedError, self).__init__(self)


def check_api_key(func):
    """ Decorator that checks incoming API keys and raises an exception should
        the incoming key be missing or not-matching

    Args:
        func (function): The function to be decorated.

    Returns:
        function: The decorated function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        """ Decorator wrapper."""

        api_key = os.environ.get('API_KEY')
        if not api_key:
            logging.warning("API_KEY not set - authorization not checked.")
        else:
            auth_header = request.headers.get('Authorization', '')

            if api_key not in auth_header:
                logging.warning("Authorization error: API key mismatch")
                raise UnauthorizedError()
        return func(*args, **kwargs)
    return wrapper

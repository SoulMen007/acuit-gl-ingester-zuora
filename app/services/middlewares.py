"""
Custom middlewares.
"""

from google.appengine.api import urlfetch


class AppEngineMiddleware:
    """
    This middleware is used to set the per-request urlfetch deadline, as per the
    Google recommendation:
    https://cloud.google.com/appengine/docs/python/issue-requests.
    The default is 5 seconds, which is not sufficient in many cases. Be aware
    that App Engine has a strict 60 second request handling deadlines for
    user requests and 10 minutes for taskqueue requests.
    """
    def __init__(self, app, urlfetch_deadline=15):
        self.app = app
        self.urlfetch_deadline = urlfetch_deadline

    def __call__(self, environ, start_response):
        urlfetch.set_default_fetch_deadline(self.urlfetch_deadline)
        return self.app(environ, start_response)

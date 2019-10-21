import urllib
import urlparse


def append_params(url, params):
    """Appends URL parameters"""
    enc_params = urllib.urlencode(params)
    params_join = '&' if urlparse.urlparse(url).query else '?'
    return '{}{}{}'.format(url, params_join, enc_params)

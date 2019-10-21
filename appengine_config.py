from google.appengine.ext import vendor

# Add any libraries installed in the "lib" folder.
vendor.add('lib')

from requests_toolbelt.adapters import appengine

# Monkey patch newer versions of requests library to work with appengine.
# http://stackoverflow.com/questions/9762685/using-the-requests-python-library-in-google-app-engine
appengine.monkeypatch()

# Monkey patch oauthlib to make PyXero use pycrypto instead of cryptography.
_jwtrs1 = None


def new_jwt_rs1_signing_algorithm():
    global _jwtrs1
    if _jwtrs1 is None:
        from jwt.contrib.algorithms.pycrypto import RSAAlgorithm
        from Crypto.Hash import SHA
        _jwtrs1 = RSAAlgorithm(SHA)
    return _jwtrs1


from oauthlib.oauth1.rfc5849 import signature  # NOQA
signature._jwt_rs1_signing_algorithm = new_jwt_rs1_signing_algorithm
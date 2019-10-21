#! /usr/bin/env python

"""App Engine local test runner.

This program handles properly importing the App Engine SDK so that test modules
can use google.appengine.* APIs and the Google App Engine testbed.

Example invocation:

    $ python run_tests.py ~/google-cloud-sdk
"""

import argparse
import os
import sys
import unittest
import logging
import subprocess
import shlex

_pubsub = {}

def fixup_paths(path):
    """Adds GAE SDK path to system path and appends it to the google path
    if that already exists."""
    # Not all Google packages are inside namespace packages, which means
    # there might be another non-namespace package named `google` already on
    # the path and simply appending the App Engine SDK to the path will not
    # work since the other package will get discovered and used first.
    # This emulates namespace packages by first searching if a `google` package
    # exists by importing it, and if so appending to its module search path.
    try:
        import google
        google.__path__.append("{0}/google".format(path))
    except ImportError:
        pass

    sys.path.insert(0, path)


def start_pubsub_emulator(sdk_path):
    path = os.path.join(sdk_path, 'platform/pubsub-emulator/bin/cloud-pubsub-emulator')
    if not os.path.exists(path):
        raise RuntimeError('Pubsub emulator could not be found')
    cmd = '{} --host=localhost --port=8171'.format(path)

    global pubsub_proc
    global pubsub_dev
    _pubsub['dev'] = open(os.devnull, 'w')
    _pubsub['proc'] = subprocess.Popen(shlex.split(cmd), stderr=pubsub_dev,
                                       shell=False)


def main(sdk_path, test_path, test_pattern, start_pubsub):
    if start_pubsub:
        start_pubsub_emulator(sdk_path)
    # If the SDK path points to a Google Cloud SDK installation
    # then we should alter it to point to the GAE platform location.
    if os.path.exists(os.path.join(sdk_path, 'platform/google_appengine')):
        sdk_path = os.path.join(sdk_path, 'platform/google_appengine')
    #
    # # Make sure google.appengine.* modules are importable.
    fixup_paths(sdk_path)
    #
    # # Make sure all bundled third-party packages are available.
    import dev_appserver
    dev_appserver.fix_sys_path()

    # Loading appengine_config from the current project ensures that any
    # changes to configuration there are available to all tests (e.g.
    # sys.path modifications, namespaces, etc.)
    try:
        import appengine_config
        (appengine_config)
    except ImportError:
        print('Note: unable to import appengine_config.')

    # Disable logging when running tests
    logging.disable(logging.CRITICAL)

    # Discover and run tests.
    suite = unittest.loader.TestLoader().discover(test_path, test_pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if len(_pubsub) != 0:
        _pubsub['proc'].terminate()
        _pubsub['dev'].close()

    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        'sdk_path',
        help='The path to the Google App Engine SDK or the Google Cloud SDK.')
    parser.add_argument(
        '--test-path',
        help='The path to look for tests, defaults to the current directory.',
        default=os.getcwd())
    parser.add_argument(
        '--test-pattern',
        help='The file pattern for test modules, defaults to *_test.py.',
        default='*_test.py')
    parser.add_argument(
        '--start-pubsub',
        help='Start the pubsub emulator before running the tests.',
        default=False
    )

    args = parser.parse_args()

    result = main(args.sdk_path, args.test_path, args.test_pattern, args.start_pubsub)

    if not result.wasSuccessful():
        sys.exit(1)

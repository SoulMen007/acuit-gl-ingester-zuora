"""
Factory for instantiating sessions based on provider
"""


from app.clients.qbo_client import (
    QboAuthorizationSession,
    QboTokenSession,
    QboApiSession
)
from app.clients.xero_client import (
    XeroAuthorizationSession,
    XeroTokenSession,
    XeroApiSession
)
from app.clients.zuora_client import (
    ZuoraAuthorizationSession,
    ZuoraTokenSession,
    ZuoraApiSession
)
from app.sync_states.qbo.sync_state import QboSyncState
from app.sync_states.xero.sync_state import XeroSyncState
from app.sync_states.zuora.sync_state import ZuoraSyncState


# TODO: consider if these 3 classes can be combined into one (keeping in mind how to handle other providers so that the
# linker stays generic

authorization_session_classes = {
    'qbo': QboAuthorizationSession,
    'xerov2': XeroAuthorizationSession,
    'zuora': ZuoraAuthorizationSession
}

token_session_classes = {
    'qbo': QboTokenSession,
    'xerov2': XeroTokenSession,
    'zuora': ZuoraTokenSession
}

api_session_classes = {
    'qbo': QboApiSession,
    'xerov2': XeroApiSession,
    'zuora': ZuoraApiSession
}

sync_states = {
    'qbo': QboSyncState,
    'xerov2': XeroSyncState,
    'zuora': ZuoraSyncState
}


def get_authorization_session(provider, *args):
    return authorization_session_classes[provider](*args)


def get_token_session(provider, *args):
    return token_session_classes[provider](*args)


def get_api_session(provider, *args):
    return api_session_classes[provider](*args)


def get_sync_state(provider):
    return sync_states[provider]

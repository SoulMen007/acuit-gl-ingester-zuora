import logging

from app.sync_states.zuora.ndb_models import ZuoraSyncData
from app.sync_states.zuora.stages import ListApiStage

STAGES = [ListApiStage]


class ZuoraSyncState(object):

    """TODO: Implement ZuoraSyncState"""
    def __init__(self, org_uid):
        """
        Class initialiser. Retrieves stage of the sync which is in progress.

        Args:
            org_uid(str): org identifier
        """
        self.sync_data = ZuoraSyncData.get_by_id(org_uid) or ZuoraSyncData(id=org_uid, stage_index=0)
        self.stage = STAGES[self.sync_data.stage_index](org_uid)
        logging.info("running stage {}: {}".format(self.sync_data.stage_index, type(self.stage).__name__))

    def next(self, payload):
        """
        Function which gets repeatedly called by the adapter. Delegates the call to the appropriate stage implementation
        and keeps track of stage completion. Tells the adaptor that the sync is finished (via returning the complete
        flag) only when the last stage has been completed.

        Args:
            payload(object): a payload which has been given to the adaptor last time this function ran

        Returns:
            (bool, object): a flag indicating if the sync has finished, and a payload to be passed in on next call
        """
        stage_complete, next_payload = self.stage.next(payload)

        if stage_complete:
            self.sync_data.stage_index += 1

        complete = self.sync_data.stage_index == len(STAGES)
        if complete:
            self.sync_data.stage_index = 0
            logging.info("stage completed, setting next stage index to {}".format(self.sync_data.stage_index))

        self.sync_data.put()

        return complete, next_payload

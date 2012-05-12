from collections import namedtuple


class GMSyncError(Exception):
    """Base class for any error originating during syncing."""
    pass

#The configuration for a media player: the action pairs and how to connect.
MPConf = namedtuple('MPConf', ['action_pairs', 'make_connection'])

#A trigger/handler pair. A list of these defines how to respond to db changes.
ActionPair = namedtuple('ActionPair', ['trigger', 'handler'])

#A definition of a trigger.
TriggerDef = namedtuple('TriggerDef', ['name', 'table', 'when', 'id_text'])

#Holds the result from a handler, so the service can keep local -> remote mapping up to date.
# action: one of {'create', 'delete'}. Updates can just return an empty HandlerResult.
# itemType: one of {'song', 'playlist'}
# gm_id: <string>
HandlerResult = namedtuple('HandlerResult', ['action', 'item_type', 'gm_id'])

#A mediaplayer config defines handlers.
#These provide code for pushing out changes.

#They do not need to check for success, but can raise CallFailure,
# sqlite.Error or UnmappedId, which the service will handle.

#All handlers that create/delete remote items must return a HandlerResult.
#This allows the service to keep track of local -> remote mappings.

class Handler:
    """A Handler can push out local changes to Google Music.

    A mediaplayer config defines one for each kind of local change (eg the addition of a song)."""

    def __init__(self, local_id, api, mp_conn, gmid_conn, get_gm_id):
        """Create an instance of a Handler. This is done by the service when a specific change is detected."""
 
        self.local_id = local_id
        self.api = api

        #A cursor for the mediaplayer database.
        self.mp_cur = mp_conn.cursor()

        #A cursor for the id database - this shouldn't be needed in mediaplayer configs, they use gm{s,p}id.
        self.id_cur = gmid_conn.cursor()
        self._get_gm_id = get_gm_id #a func that takes localid, item_type, cursor and returns the matching GM id, or raises UnmappedId

    @property
    def gms_id(self):
        return self._get_gm_id(self.local_id, 'song', self.id_cur)

    @property
    def gmp_id(self):
        return self._get_gm_id(self.local_id, 'playlist', self.id_cur)

    def push_changes(self):
        """Send changes to Google Music. This is implemented in mediaplayer configurations.

        This function does not need to handle failure. The service will handle gmusicapi.CallFailure, 
        sqlite3.Error, or sync2gm.UnmappedId.

        api (already authenticated), mp_cur, gms_id, and gmp_id are provided for convinience."""

        raise NotImplementedError

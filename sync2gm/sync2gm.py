#!/usr/bin/env python

"""A server that syncs a local database to Google Music."""

import collections
import threading
import time
import contextlib
from contextlib import closing
import os

from gmusicapi import *
import appdirs

class MockApi(Api):
    def _wc_call(self, service_name, *args, **kw):
        """Returns the response of a web client call.
        :param service_name: the name of the call, eg ``search``
        additional positional arguments are passed to ``build_body``for the retrieved protocol.
        if a 'query_args' key is present in kw, it is assumed to be a dictionary of additional key/val pairs to append to the query string.
        """

        #just log the request
        self.log.debug("wc_call %s %s", service_name, args)

#from twisted.internet.protocol import Factory
#from twisted.protocols.basic import LineReceiver

#to run it:
#reactor.listenTCP(8123, ChatFactory())
#reactor.run()


TriggerDef = collections.namedtuple('TriggerDef', ['name', 'table', 'when', 'id_text'])


#A list of these defines the config: a trigger, and the handler for it.
ConfigPair = collections.namedtuple('Config', ['trigger', 'handler'])

#Holds the result from a handler, so the service can keep local -> remote mapping up to date.
#action: one of {'create', 'delete'}. Updates can just return an empty HandlerResult.
#itemType: one of {'song', 'playlist'}
#gmId: <string>
HandlerResult = collections.namedtuple('HandlerResult', ['action', 'item_type', 'gm_id'])

#Maps a local column to a piece of gm metadata.
MDMapping = collections.namedtuple('MDMapping', ['col', 'gm_key', 'to_gm_form'])

def make_md_map(col, gm_key=None, to_gm_form=None):
    """Create a new MDMapping conviniently."""
    if gm_key is None:
        gm_key = col[0].lower() + col[1:]

    if to_gm_form is None:
        to_gm_form = lambda data: data

    return MDMapping(col, gm_key, to_gm_form)


class GMSyncError(Exception):
    pass

class UnmappedId(Exception):
    """Raised when we expect a mapping exists between local/remote ids,
    but one does not."""
    pass


@contextlib.contextmanager
def backed_up(filename):
    """Context manager to back up a file and remove the backup.

    *filename*.bak will be overwritten if it exists.
    """

    exists = os.path.isfile(filename)
    bak_name = filename+'.bak'

    if exists: os.rename(filename, bak_name)
    try:
        yield
        #if we terminate unexpectedly (eg a reboot), 
        # the backup will remain
    finally:
        if exists: os.remove(bak_name)

def atomic_write(filename, text):
    """Return True if *filename* is overwritten with *text* successfully. The write will be atomic.

    *filename*.tmp may be overwritten.
    """

    tmp_name = filename+'.tmp'

    try:
        with open(tmp_name, 'w') as tmp:
            tmp.write(text)

        #this _should_ be atomic cross-platform
        with backed_up(filename):
            os.rename(tmp_name, filename)            

    except Exception as e:
        #TODO warn that bak may be able to be restored.
        return False

    return True

def get_gms_id(localId):
    """Return the GM song id associated with this *localId*, or None."""
    return _get_gm_id(localId, 'song')

def get_gmp_id(localId):
    """Return the GM playlist id associated with this *localId*, or None."""
    return _get_gm_id(localId, 'playlist')

def _get_gm_id(localId, itemType):
    #Conn needs to come from the service
    if itemType == 'song':
        table='sync2gm_GMSongIds'
    else:
        table='sync2gm_GMPlaylistIds'

    gmId = conn.execute("SELECT gmId FROM %s WHERE localId=?" % table, (localId,)).fetchone()
    
    if not gmId: raise UnmappedId
    
    return gmId[0]

class MockApi(Api):

    def is_authenticated(self):
        return True

    def _wc_call(self, service_name, *args, **kw):
        """Returns the response of a web client call.
        :param service_name: the name of the call, eg ``search``
        additional positional arguments are passed to ``build_body``for the retrieved protocol.
        if a 'query_args' key is present in kw, it is assumed to be a dictionary of additional key/val pairs to append to the query string.
        """

        #just log the request
        self.log.debug("wc_call %s %s", service_name, args)

class ChangePollThread(threading.Thread):
    def __init__(self, make_conn, handlers, db_file, lib_name):
        threading.Thread.__init__(self)
        self._running = threading.Event()
        self._make_conn = make_conn
        self._db = db_file
        self._config_dir = appdirs.user_data_dir(appname='mm2gm', appauthor='Simon Weber', version=lib_name)
        self._change_file = self._config_dir + 'last_change'

        self.handlers = handlers
        self.activate() #we won't run until start()ed

        #cheat for debugging
        self.api = MockApi()
        

    def activate(self):
        self._running.set()

    def stop(self):
        self._running.clear()

    @property
    def active(self):
        return self._running.isSet()

    def run(self):

        read_new_changeid = True
        last_change_id = 0

        while self.active:

            if read_new_changeid:
               with open(self._change_file) as f:
                   last_change_id = int(f.readline()[:-1])

            #Buffer in changes to memory.
            #The limit is intended to limit risk of losing changes.
            max_changes = 10

            #opening a new conn every time - not sure if this is desirable
            with closing(self._make_conn(self._db)) as conn, closing(conn.cursor()) as cur:
            
                #continue to retry while db is locked
                while 1:
                    try:
                        cur.execute("SELECT changeId, changeType, localId FROM sync2gm_Changes")
                        break
                    except sqlite3.Error as e:
                        if "database is locked" in e.message:
                            print "locked - retrying"
                        else: raise
                    
                changes = cur.fetchmany(max_changes)

                if len(changes) is 0:
                    read_new_changeid = False
                else:
                    read_new_changeid = True

                    for change in changes:
                        c_id, c_type, local_id = change
                        print c_id, c_type, local_id
                        
                        try:
                            self.handlers[cType](local_id, self.api, conn)
                            
                            if not atomic_write(self._change_file): pass #log failure in writing out change
                        except CallFailure as cf:
                            pass #log failure to update; this is a big deal

                        
        
            
            time.sleep(5) 





# class GMSyncProtocol(LineReceiver):
#     """Allows client communications with the service."""

#     #shares the monitor thread 
#     #allows starting/stopping
#     def __init__(self):
#         pass

# class GMSyncFactory(Factory):
    

#     def __init__(self, lib_name):
#         """Initialize a syncing server.

#         :param lib_name: an arbitrary name for the library, used to store config,
#         """
        
#         self.lib_name = lib_name
#         #loads config from lib_name
#         #inits the monitor thread

#!/usr/bin/env python

"""A server that syncs a local database to Google Music."""

import collections
import threading
import time

from gmusicapi import *
from appdirs import AppDirs

class MockApi(Api):
    def _wc_call(self, service_name, *args, **kw):
        """Returns the response of a web client call.
        :param service_name: the name of the call, eg ``search``
        additional positional arguments are passed to ``build_body``for the retrieved protocol.
        if a 'query_args' key is present in kw, it is assumed to be a dictionary of additional key/val pairs to append to the query string.
        """

        #just log the request
        self.log.debug("wc_call %s %s", service_name, args)

#AppDirs("SuperApp", "Acme")

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
    def __init__(self, make_conn, handlers, db_file):
        threading.Thread.__init__(self)
        self._running = threading.Event()
        self._make_conn = make_conn
        self._db = db_file

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
        with self._make_conn(self._db) as conn:
            while self.active:
                with conn:
                    r = conn.execute("SELECT changeId, changeType, localId FROM sync2gm_Changes").fetchone()
            
                #If no changes, sleep then poll again.
                if not r:
                    print "sleeping"
                    time.sleep(5)
                    continue

                #As long as we have changes, continually send them out.
                print "found change: ",
                print r['changeId'], r['changeType']

                #remove change
                with conn:
                    conn.execute("DELETE FROM sync2gm_Changes WHERE changeId=?", (r['changeId'],))
        
        


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

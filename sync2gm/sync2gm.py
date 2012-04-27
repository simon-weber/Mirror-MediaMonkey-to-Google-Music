#!/usr/bin/env python

"""A server that syncs a local database to Google Music."""

import collections
import threading
import time
import contextlib
from functools import partial
from contextlib import closing
import os
import sqlite3
import traceback

from gmusicapi import *
import appdirs

#Keys are HandlerResult.item_types, values are the names of the id mapping databases.
item_to_table = {'song': 'GMSongIds', 'playlist': 'GMPlaylistIds'}

class MockApi(Api):
    def _wc_call(self, service_name, *args, **kw):
        """Returns the response of a web client call.
        :param service_name: the name of the call, eg ``search``
        additional positional arguments are passed to ``build_body``for the retrieved protocol.
        if a 'query_args' key is present in kw, it is assumed to be a dictionary of additional key/val pairs to append to the query string.
        """

        #just log the request
        self.log.warning("wc_call %s %s", service_name, args)

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
#gm_id: <string>
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
            tmp.write(str(text))

        #this _should_ be atomic cross-platform
        with backed_up(filename):
            os.rename(tmp_name, filename)            

    except Exception as e:
        #TODO warn that bak may be able to be restored.
        raise #debug
        return False


    return True

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
        return {'id': 'test'} #super hack

class ChangePollThread(threading.Thread):
    def __init__(self, make_conn, handlers, db_file, lib_name): #probably want something like "init" here to drop/create fresh map tables
        #Most of this should eventually be pulled into protocol.
        threading.Thread.__init__(self)
        self._running = threading.Event()
        self._db = db_file
        self.make_conn = partial(make_conn, self._db)
        self._config_dir = appdirs.user_data_dir(appname='mm2gm', appauthor='Simon Weber', version=lib_name)
        #Ensure the setting dir exists.
        if not os.path.isdir(self._config_dir):
            os.makedirs(self._config_dir)
        
        self._change_file = self._config_dir + os.sep + 'last_change'


        id_db_loc = self._config_dir + os.sep + 'gmids.db'
        self._gmid_conn = sqlite3.connect(id_db_loc)

        #Ensure the id mapping tables exist.
        #keep in mind the init note above
        with self._gmid_conn as conn:
            for table in item_to_table.values():
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS {tablename}(
localId INTEGER PRIMARY KEY,
gmId TEXT NOT NULL
)""".format(tablename=table))

        
        #Ensure the change file had something in it.
        if not os.path.isfile(self._change_file):
            with open(self._change_file, mode='w') as f:
                f.write("0")
            

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

    def _get_gm_id(self, localId, item_type, cur):
        cur.execute("SELECT gmId FROM %s WHERE localId=?" % item_to_table[item_type], (localId,))
        gm_id = cur.fetchone()


        if not gm_id: raise UnmappedId

        return gm_id[0]

    def update_id_mapping(self, local_id, handler_res):
        """Update the local to remote id mapping database with a HandlerResult (*handler_res*)."""
        action, item_type, gm_id = handler_res

        #two switches for the different events; they're too dissimilar to factor out
        if action == 'create':
            command = "REPLACE INTO {table} (localId, gmId) VALUES (?, ?)"
            values = (local_id, gm_id)
        elif action == 'delete':
            command = "DELETE FROM {table} WHERE localId=?"
            values = (local_id,)
        else:
            raise Exception("Unknown HandlerResult.action")

        command = command.format(table=item_to_table[item_type])


        #capture/log failure?
        with self.gmid_conn as conn:
            conn.execute(command, values)
        

    def run(self):

        read_new_changeid = True #assumes a changeid exists. currently fulfilled in __init__

        while self.active:

            if read_new_changeid:
               with open(self._change_file) as f:
                   last_change_id = int(f.readline().strip())
                   
            print "polling. last change:", last_change_id

            #Buffer in changes to memory.
            #The limit is intended to limit risk of losing changes.
            max_changes = 10

            #opening a new conn every time - not sure if this is desirable
            with closing(self.make_conn()) as conn, closing(conn.cursor()) as cur:
            
                #continue to retry while db is locked
                while 1:
                    try:
                        cur.execute("SELECT changeId, changeType, localId FROM sync2gm_Changes WHERE changeId > ?", (last_change_id,))
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
                            res = self.handlers[c_type](local_id, self.api, self.make_conn, 
                                                        get_gms_id = partial(self._get_gm_id, item_type='song'),
                                                        get_gmp_id = partial(self._get_gm_id, item_type='playlist'))
                            #When the handler created a remote object, update our local mappings.
                            if res is not None: self.update_id_mapping(local_id, res)

                        except CallFailure as cf:
                            print "call failure!" #log failure to update; this is a big deal
                        except Exception as e:
                            #for debugging
                            print "exception while pushing change"
                            print e.message
                            print traceback.format_exc()
                        finally: #mark this change as pushed out
                            if not atomic_write(self._change_file, c_id): 
                                print "failed to write out change!"

                            

                        
        
            
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

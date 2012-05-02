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
import json
import SocketServer

from mediamonkey import config as mm_config

from gmusicapi import *
import appdirs


### Map mediaplayer type to config
mp_confs = {'mediamonkey': mm_config}


### The filenames making up a complete configuration.
config_fn = 'config'
#stores a dict encoding. keys:
#     db_path: the path of the mediaplayer database
#     mp_type: the mediaplayer type
#
change_fn = 'last_change'
id_db_fn = 'gmids.db'


#Defines the tables in the id mapping database. Keys are HandlerResult.item_types.
item_to_table = {'song': 'GMSongIds', 'playlist': 'GMPlaylistIds'}

### Various data structures used to define a config for a media player db.

#The configuration for a media player: the action pairs and how to connect.
MPConf = namedtuple('MPConf', ['action_pairs', 'make_connection'])

#A trigger/handler pair. A list of these defines how to respond to db changes.
ActionPair = collections.namedtuple('ActionPair', ['trigger', 'handler'])

#A definition of a trigger.
TriggerDef = collections.namedtuple('TriggerDef', ['name', 'table', 'when', 'id_text'])

#Holds the result from a handler, so the service can keep local -> remote mapping up to date.
# action: one of {'create', 'delete'}. Updates can just return an empty HandlerResult.
# itemType: one of {'song', 'playlist'}
# gm_id: <string>
HandlerResult = collections.namedtuple('HandlerResult', ['action', 'item_type', 'gm_id'])


#A mediaplayer config defines handlers.
#conn uses sqlite3.Row as row_factory.
#They are expected to do whatever is needed to push out changes.

#They do not need to check for success, but can raise CallFailure,
# sqlite.Error or UnmappedId, which the service will handle.

#All handlers that create/delete remote items must return a HandlerResult.
#This allows the service to keep track of local -> remote mappings.

class Handler:
    """A Handler can push out local changes to Google Music.

    A mediaplayer config defines one for each kind of local change (eg the addition of a song)."""

    def __init__(self, local_id, api, mp_conn, gmid_conn):
        """Create an instance of a Handler. This is done by the service when a specific change is detected."""
 
        self.local_id = local_id
        self.api = api

        #A cursor for the mediaplayer database.
        self.mp_cur = mp_conn.cursor()

        #A cursor for the id database - this shouldn't be needed in mediaplayer configs, they use gm{s,p}id.
        self.id_cur = gmid_conn.cursor()

    @property
    def gms_id(self):
        return get_gm_id(self.local_id, 'song', self.id_cur)

    @property
    def gmp_id(self):
        return get_gm_id(self.local_id, 'playlist', self.id_cur)

    def push_changes(self):
        """Send changes to Google Music. This is implemented in mediaplayer configurations.

        This function does not need to handle failure. The service will handle gmusicapi.CallFailure, 
        sqlite3.Error, or sync2gm.UnmappedId.

        api (already authenticated), mp_cur, gms_id, and gmp_id are provided for convinience."""

        raise NotImplementedError


#This should be in the outside factory.
def _get_gm_id(self, localId, item_type, cur):
    cur.execute("SELECT gmId FROM %s WHERE localId=?" % item_to_table[item_type], (localId,))
    gm_id = cur.fetchone()


    if not gm_id: raise UnmappedId

    return gm_id[0]                        

def handler(f):
    """A wrapper to perform handler boilerplate actions.
    Expects the handler to be called with kwargs make_conn, make_gmid_conn, get_gms_id, get_gmp_id,
    and will call the handler with with args + a cursor and the get_id methods ready to be called."""
    
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        #Set up our db connection for this handler instance.
        make_conn, make_gmid_conn, get_gms_id, get_gmp_id = [kwargs[k] for k in ('make_conn', 'make_gmid_conn', 'get_gms_id', 'get_gmp_id')]
        with closing(make_conn()) as conn, closing(make_gmid_conn()) as gmid_conn:
            cur = conn.cursor()
            id_cur = gmid_conn.cursor()

            get_gms_id = functools.partial(get_gms_id, cur=id_cur)
            get_gmp_id = functools.partial(get_gmp_id, cur=id_cur)

            return f(*(args+(cur, get_gms_id, get_gmp_id)))

    return wrapper

### Utility functions involved in attaching/detaching from the local db.
def create_trigger(change_type, triggerdef, conn):
    keys = triggerdef._asdict()
    keys['change_type'] = change_type

    with conn:
        conn.execute("""
            CREATE TRIGGER {name} {when} ON {table}
            BEGIN
            INSERT INTO sync2gm_Changes (changeType, localId) VALUES ({change_type}, {id_text});
            END
            """.format(**keys))

def drop_trigger(triggerdef, conn):
    with conn:
        conn.execute("DROP TRIGGER IF EXISTS {name}".format(name=triggerdef.name))

def create_service_table(conn, num_triggers):
    with conn:
        conn.execute(
            """CREATE TABLE sync2gm_Changes(
changeId INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
changeType INTEGER CHECK (changeType BETWEEN 0 AND {changes}),
localId INTEGER NOT NULL
)""".format(changes=num_triggers))

def drop_service_table(conn):
    with conn:
        conn.execute("DROP TABLE IF EXISTS sync2gm_Changes")
            

def attach(conn, action_pairs):
    success = False

    try:
        create_service_tables(conn, len(action_pairs))

        for i in range(len(action_pairs)):
            triggerdef = action_pairs[i].trigger
            create_trigger(i, triggerdef, conn)

        success = True

    except sqlite3.Error:
        success = False

        detach(conn)

    finally:
        return success

def detach(conn, action_pairs):
    success = False

    try:
        drop_service_tables(conn)
        
        for triggerdef, handler in action_pairs:
            drop_trigger(triggerdef, conn)    

        success = True

    except sqlite3.Error:
        success = False
        
    finally:
        return success

def reattach(conn, action_pairs):
    return detach(conn, action_pairs) and attach(conn, action_pairs)



### Utilities for writing/reading configuration.

def get_conf_dir(confname):
    """Return the directory for this *confname*, with a trailing separator."""
    conf_dir = appdirs.user_data_dir(appname='sync2gm', appauthor='Simon Weber', version=confname)
    conf_dir += os.sep    

    return conf_dir

def get_conf_fn(confname):
    return get_conf_dir(confname) + config_fn

def write_conf_file(confname, config):
    """Given a dict, *config*, encode it and create or overwrite given filename."""
    with open(get_conf_fn(confname), 'w') as f:
        json.dump(config, f)

def read_config_file(confname):
    """Returns a dictionary of the configuration stored in *filename*."""
    with open(get_conf_fn(confname)) as f:
        return json.load(f)


def init_config(confname, mp_db_fn, mp_type):
    """Attach to the local database, and create or overwrite the configuration for the given *confname*.
    """

    conf_dir = get_conf_dir(confname)
    conf_fn = get_conf_fn(confname)

    #Ensure the conf dir exists.
    if not os.path.isdir(conf_dir):
        os.makedirs(conf_dir)

    #(re)create the config file.
    conf_dict = {'mp_type': mp_type, 'mp_db_fn': mp_db_fn}
    write_conf_file(conf_fn, conf_dict)

    #(re)create the change file.
    if not os.path.isfile(conf_dir + change_fn):
        with open(conf_dir + change_fn, mode='w') as f:
            f.write("0")
    
    #(re)create the id mapping tables.
    with closing(sqlite3.connect(conf_dir + id_db_fn)) as conn:
        for table in item_to_table.values():
            conn.executescript("""
                DROP TABLE IF EXISTS {tablename};

                CREATE TABLE {tablename}(
                    localId INTEGER PRIMARY KEY,
                    gmId TEXT NOT NULL);
                """.format(tablename=table))
                

    #(re)attach to the db.
    make_connection, action_pairs = mp_confs[mp_type]

    with closing(make_connection(conf_dir + mp_db_fn)) as conn:
        reattach(conn, action_pairs)
    

    

class MockApi(Api):
    def _wc_call(self, service_name, *args, **kw):
        """Returns the response of a web client call.
        :param service_name: the name of the call, eg ``search``
        additional positional arguments are passed to ``build_body``for the retrieved protocol.
        if a 'query_args' key is present in kw, it is assumed to be a dictionary of additional key/val pairs to append to the query string.
        """

        #just log the request
        self.log.warning("wc_call %s %s", service_name, args)

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
        self.make_gmid_conn = partial(sqlite3.connect, id_db_loc)

        #Ensure the id mapping tables exist.
        #keep in mind the init note above
        with closing(self.make_gmid_conn()) as conn:
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
        with closing(self.make_gmid_conn()) as conn:
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
                            res = self.handlers[c_type](local_id, self.api, make_conn=self.make_conn, 
                                                        make_gmid_conn=self.make_gmid_conn,
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




class ServiceHandler(SocketServer.StreamRequestHandler):
    """Respond if we are running, and handle shutdown requests.

    valid requests are: 'shutdown' and 'status'. 

    'status' receieves a response 'running'."""

    def handle(self):
        self.data = self.rfile.readline().strip()

        if self.data == 'shutdown':
            for t in threading.enumerate():
                if isinstance(t, ChangePollThread):
                    t.stop()
                    t.join()

            self.server.shutdown()

        elif self.data == 'status':
            self.wfile.write('running')

def start_service(confname, port, gm_email, gm_password):
    """Attempt to start the service on locally on port *port*, using config *confname*.

    Return True if the service started, or an error message."""

    #Read in the config.
    conf = read_config_file(confname)

    try:
        server = ThreadedTCPServer(('localhost', port), ServiceHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        poll_thread = ChangePollThread

        server_thread.start()
    except Exception as e:
        return "Could not start service:", repr(e)

    return True

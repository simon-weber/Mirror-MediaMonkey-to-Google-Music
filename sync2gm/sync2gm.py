#!/usr/bin/env python

"""A server that syncs a local database to Google Music."""

import collections
import itertools
#Enum recipe from SO: 
# http://stackoverflow.com/a/1695250/1231454
# def enum(*sequential, **named):
#     enums = dict(zip(sequential, range(len(sequential))), **named)
#     return type('Enum', (), enums)
#CTypes = enum(itertools.product(["c", "u", "d"], ["Song", "Playlist"]))

from gmusicapi import *
from appdirs import AppDirs
#AppDirs("SuperApp", "Acme")
from twisted.internet.protocol import Factory
from twisted.protocols.basic import LineReceiver
#to run it:
#reactor.listenTCP(8123, ChatFactory())
#reactor.run()


TriggerDef = collections.namedtuple('TriggerDef', ['name', 'table', 'when', 'idValText'])
#when surrounded by eg
# CREATE TRIGGER {name} when ON {table}

#A list of these defines the config: a trigger, and the handler for it.
ConfigPair = collections.namedtuple('Config', ['trigger', 'handler'])

#Holds the result from a handler, so the service can keep local -> remote mapping up to date.
#action: one of {'create', 'delete'}. Updates can just return an empty HandlerResult.
#itemType: one of {'song', 'playlist'}
#gmId: <string>
HandlerResult = collections.namedtuple('HandlerResult', ['action', 'itemType', 'gmId'])

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

#for the following, triggers is a list of TriggerDefs
def attach(db_filename, triggers):
    pass

def detach(db_filename, triggers):
    pass

#to dispatched by the change monitoring thread
def handleChange(handler, localId):
    params = [cur.execute(p, {"localId":localId}).fetchone() 
              for p in handler.args_query]

    handler.push_change(*params)


class GMSyncProtocol(LineReceiver):
    """Allows client communications with the service."""

    #shares the monitor thread 
    #allows starting/stopping
    def __init__(self):
        pass

class GMSyncFactory(Factory):
    

    def __init__(self, lib_name):
        """Initialize a syncing server.

        :param lib_name: an arbitrary name for the library, used to store config,
        """
        
        self.lib_name = lib_name
        #loads config from lib_name
        #inits the monitor thread

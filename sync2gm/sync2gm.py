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

#A change handler is associated with a change number.
# push_change is the function that is called to send out its changes
# args_query is an optional list of sql SELECT queries to run, each of which is given as a positional param to push_change, when called.
#  the queries are given a named parameter :localId.
DBChangeHandler = collections.namedtuple('DBChangeHandler', ['push_change', 'args_query'])
TriggerDef = collections.namedtupled('TriggerDef', ['name', 'table', 'when', 'idValText'])
#when surrounded by eg
# CREATE TRIGGER {name} when ON {table}

class GMSyncError(Exception):
    pass

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

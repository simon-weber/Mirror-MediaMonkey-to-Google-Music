#!/usr/bin/env python

"""Syncs a local database to Google Music. The database must have an audit and mapping table."""

import itertools


#Enum recipe from SO: 
# http://stackoverflow.com/a/1695250/1231454
def enum(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    return type('Enum', (), enums)


#enum of change types, eg CTypes.cSong == a creation of a song
CTypes = enum(itertools.product(["c", "u", "d"], ["Song", "Playlist"]))

#!/usr/bin/env python

import sqlite3

import sync2gm

#enum of change types, {c,u,d}x{Song, Playlist}
# eg CTypes.cSong
from sync2gm import CTypes 


## config start ##

#The names of the tables in the MM db.
songs_table = "Songs"
plists_table = "Playlists"

#List of MM db columns that map directly to GM md keys (once in camelCase).
# eg MM: "AlbumArtist" -> GM "albumArtist"

cols_same = ("Artist", "Album", "AlbumArtist", "Comment", 
             "Genre", "Rating", "Year")

#Mapping of MM db cols to their GM md key.

cols_diff = {"DiscNumber": "disc",
             "TrackNumber": "track",
             "BPM": "beatsPerMinute",
             "SongTitle": "name"}

#Not sure what to do with these GM keys yet:
# totalTracks totalDiscs - can't find the MM db entry
# albumArtUrl - unsure how GM handles uploading/updating album art


## config end ##


mm_to_gm_cols = {}
for mm_c in cols_same:
    mm_to_gm_cols[mm_c] = mm_c[0].lower + mm_c[1:]

mm_to_gm_cols = dict(mm_to_gm_cols.items() + cols_diff.items())




def attach(db_path):
    """Create the audit and sync tables on the db at *db_path*."""
    pass

def detach(db_path):
    """Remove the audit and sync tables from the db at *db_path*."""
    pass

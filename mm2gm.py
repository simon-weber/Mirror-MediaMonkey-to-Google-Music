#!/usr/bin/env python

#List of MM db columns that map directly to GM md keys (once put in camelCase).
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


#Attaching to the db - varies between media players.
def attach(db_path):
    """Create the audit and sync tables at the db at *db_path*."""
    pass

def detach(db_path):
    """Remove the audit and sync tables from the db at *db_path*."""
    pass

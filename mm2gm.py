#!/usr/bin/env python


"""Allows syncing of a MediaMonkey database to Google Music."""

from sync2gm import DBChangeHandler, TriggerDef

## config start ##
triggers = [
#Song triggers:
TriggerDef(name='sync2gm_cSong',
           table='Songs',
           when="AFTER INSERT",
           idValText='new.ID'),

TriggerDef(name='sync2gm_uSong',
           table='Songs',
           when="AFTER UPDATE OF (Artist, Album, AlbumArtist, Comment, Genre, Rating, Year, DiscNumber, TrackNumber, BPM, SongTitle)",
           idValText='new.ID'),

TriggerDef(name='sync2gm_dSong',
           table='Songs',
           when="AFTER DELETE",
           idValText='old.ID')

#Playlist triggers:
TriggerDef(name='sync2gm_cPlaylist',
           table='Playlists',
           when="AFTER INSERT",
           idValText='new.IDPlaylist'),

TriggerDef(name='sync2gm_uPlaylistName',
           table='Playlists',
           when="AFTER UPDATE OF (PlaylistName)",
           idValText='new.IDPlaylist'),

TriggerDef(name='sync2gm_addPlaylistSong',
           table='PlaylistSongs',
           when="AFTER INSERT",
           idValText='new.IDPlaylistSong'),

TriggerDef(name='sync2gm_delPlaylistSong',
           table='PlaylistSongs',
           when="AFTER DELETE",
           idValText='old.IDPlaylistSong'),

TriggerDef(name='sync2gm_movePlaylistSong',
           table='PlaylistSongs',
           when="AFTER UPDATE OF (SongOrder)",
           idValText='new.IDPlaylistSong'),

#Autoplaylist-specific triggers:
TriggerDef(name='sync2gm_uAPlaylistQuery',
           table='Playlists',
           when="AFTER UPDATE OF (QueryData)",
           idValText='new.IDPlaylist')
]

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

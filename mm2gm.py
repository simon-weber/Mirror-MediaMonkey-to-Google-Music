#!/usr/bin/env python


"""Allows syncing of a MediaMonkey database to Google Music."""

from sync2gm import TriggerDef, ConfigPair, HandlerResult, MDMapping, make_md_map, get_gm_id
from gmusicapi import Api, CallFailure

#Define how to set up the connection, since MediaMonkey needs a custom collation function.
#It won't allow string queries without it.
#Credit to Sproaticus: http://www.mediamonkey.com/forum/viewtopic.php?p=127635#127635
def make_connection(db_path):
    """Return a connection to the database at *db_path*."""

    def iUnicodeCollate(s1, s2):
        return cmp(s1.lower(), s2.lower())

    conn = sqlite3.connect(db_path)
    conn.create_collation('IUNICODE', iUnicodeCollate)
    #There are also USERLOCALE and NUMERICSTRING collations referred to here:
    #http://www.mediamonkey.com/wiki/index.php/MediaMonkey_Database_structure

    return conn

#Define metadata mapping.
def to_gm_rating(r):
    if r == -1:
        return 0
    if 0 <= r < 50:
        return 1
    else:
        return 5

md_mappings = [
    #make_md_map defaults gm_key to col with a lowercase first char,
    # and to_gm_form to identity (ie same form).
    make_md_map('Artist'),
    make_md_map('Album'),
    make_md_map('AlbumArtist'),
    make_md_map('Comment'),
    make_md_map('Genre'),
    make_md_map('Rating', to_gm_form = to_gm_rating),
    make_md_map('Year'),

    make_md_map('DiscNumber', 'disc'),
    make_md_map('TrackNumber', 'track'),
    make_md_map('BPM', 'beatsPerMinute'),
    make_md_map('SongTitle', 'name')
    ]


#Not sure what to do with these GM keys yet:
# totalTracks totalDiscs - can't find the MM db entry
# albumArtUrl - unsure how GM handles uploading/updating album art

#Map col name to it's MDMapping.
col_to_mdm = {}
for mdm in md_mappings:
    col_to_mdm[mdm.col] = mdm

#Get the mm cols into sql col format; col place holders aren't allowed.
mm_sql_cols = repr(tuple(col_to_mdm.keys())).replace("'","")[1:-1]


#define handlers.
#These receive three args: localId, api (an already authenticated gmusicapi) and conn (an sqlite3 connection).
#conn uses sqlite3.Row as conn.row_factory.
#They are expected to do whatever is needed to push out changes.

#They should use the sync2gm_GMSongIds, sync2gm_GMPlaylistIds, and sync2gm_ProblemIds tables.

#They do not need to check for success, but can raise CallFailure,
# sqlite.Error or UnmappedId, which the service will handle.

#All handlers that create/delete remote items must return a HandlerResult.
#This allows the service to keep track of local -> remote mappings.

def cSongHandler(localId, api, conn):
    conn.execute("SELECT SongPath from Songs WHERE ID=?", (localId,))
    path = conn.fetchone()

    res = api.upload(path)

    if res.get(path) is None:
        raise CallFailure

    return HandlerResult(action='create', itemType='song', gmId=res[path])


def uSongHandler(localId, api, conn):
    mm_md = conn.execute("SELECT %s FROM Songs WHERE ID=?" % mm_sql_cols, (localId,)).fetchone()

    gm_song = {}
    for col in mm_md.keys():
        mdm = mm_to_mdm[col]

        gm_key = mdm.gm_key
        data = mdm.translate(mm_md)

        gm_song[gm_key] = data

    gm_song['id'] = get_gms_id(localId)

    api.change_song_metadata(gm_song) #TODO should switch this to a safer method
    
def dSongHandler(localId, api, conn):
    delIds = api.delete_songs(get_gms_id(localId))

    return HandlerResult(action='delete', itemType='song', gmId=delIds[0])

def cPlaylistHandler(localId, api, conn):
    #currently assuming that this is called prior to any inserts on PlaylistSongs
    pass
    

config = [
    #Song config
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_cSong',
            table='Songs',
            when="AFTER INSERT",
            idValText='new.ID'),
        handler=cSongHandler),
    
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_uSong',
            table='Songs',
            when="AFTER UPDATE OF (%s)" % mm_sql_cols,
            idValText='new.ID'),
        handler = uSongHandler),
    
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_dSong',
            table='Songs',
            when="AFTER DELETE",
            idValText='old.ID'),
        handler = dSongHandler),

    #Playlist config
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_cPlaylist',
            table='Playlists',
            when="AFTER INSERT",
            idValText='new.IDPlaylist'),
        handler = cPlaylistHandler),


trigger=TriggerDef(name='sync2gm_uPlaylistName',
           table='Playlists',
           when="AFTER UPDATE OF (PlaylistName)",
           idValText='new.IDPlaylist'),

trigger=TriggerDef(name='sync2gm_addPlaylistSong',
           table='PlaylistSongs',
           when="AFTER INSERT",
           idValText='new.IDPlaylistSong'),

trigger=TriggerDef(name='sync2gm_delPlaylistSong',
           table='PlaylistSongs',
           when="AFTER DELETE",
           idValText='old.IDPlaylistSong'),

trigger=TriggerDef(name='sync2gm_movePlaylistSong',
           table='PlaylistSongs',
           when="AFTER UPDATE OF (SongOrder)",
           idValText='new.IDPlaylistSong'),

#Autoplaylist-specific triggers:
trigger=TriggerDef(name='sync2gm_uAPlaylistQuery',
           table='Playlists',
           when="AFTER UPDATE OF (QueryData)",
           idValText='new.IDPlaylist')
]

## config end ##



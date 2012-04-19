#!/usr/bin/env python


"""Allows syncing of a MediaMonkey database to Google Music."""

import sqlite3
import traceback #debugging
import sys #sys.argv[]

from sync2gm.sync2gm import TriggerDef, ConfigPair, HandlerResult, MDMapping, make_md_map, ChangePollThread
from gmusicapi import CallFailure

#Define how to set up the connection, since MediaMonkey needs a custom collation function.
#It won't allow string queries without it.
#Credit to Sproaticus: http://www.mediamonkey.com/forum/viewtopic.php?p=127635#127635
def make_connection(db_path):
    """Return a connection to the database at *db_path*."""

    def iUnicodeCollate(s1, s2):
        return cmp(s1.lower(), s2.lower())

    conn = sqlite3.connect(db_path, timeout=60) #MM locks the database for an obscenely long time
    conn.row_factory = sqlite3.Row
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
#These receive three args: local_id, api (an already authenticated gmusicapi) and conn (an sqlite3 connection).
#conn uses sqlite3.Row as conn.row_factory.
#They are expected to do whatever is needed to push out changes.

#They should use the sync2gm_GMSongIds, sync2gm_GMPlaylistIds, and sync2gm_ProblemIds tables.

#They do not need to check for success, but can raise CallFailure,
# sqlite.Error or UnmappedId, which the service will handle.

#All handlers that create/delete remote items must return a HandlerResult.
#This allows the service to keep track of local -> remote mappings.

def cSongHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    path = conn.execute("SELECT SongPath from Songs WHERE ID=?", (local_id,)).fetchone()

    new_ids = api.upload(path)

    if res.get(path) is None:
        raise CallFailure

    return HandlerResult(action='create', item_type='song', gm_id=new_ids[path])


def uSongHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    mm_md = conn.execute("SELECT %s FROM Songs WHERE ID=?" % mm_sql_cols, (local_id,)).fetchone()

    gm_song = {}
    for col in mm_md.keys():
        mdm = col_to_mdm[col]

        gm_key = mdm.gm_key
        data = mdm.to_gm_form(mm_md)

        gm_song[gm_key] = data

    gm_song['id'] = get_gms_id(local_id)

    print "metadata update"
    #api.change_song_metadata(gm_song) #TODO should switch this to a safer method
    
def dSongHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    delIds = api.delete_songs(get_gms_id(local_id))

    return HandlerResult(action='delete', item_type='song', gm_id=delIds[0])

def cPlaylistHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    #currently assuming that this is called prior to any inserts on PlaylistSongs
    playlist_data = conn.execute("SELECT PlaylistName FROM Playlists WHERE IDPlaylist=?", (local_id,)).fetchone()

    new_gm_pid = api.create_playlist(playlist_data[0])

    return HandlerResult(action='create', item_type='playlist', gm_id=new_gm_pid)

def uPlaylistNameHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    playlist_data = conn.execute("SELECT PlaylistName FROM Playlists WHERE IDPlaylist=?", (local_id,)).fetchone()

    api.change_playlist_name(get_gmp_id(local_id), playlist_data[0])

def dPlaylistHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    playlist_data = conn.execute("SELECT PlaylistName FROM Playlists WHERE IDPlaylist=?", (local_id,)).fetchone()

    gm_pid = get_gmp_id(local_id)

    api.delete_playlist(gm_pid)

    return HandlerResult(action='delete', item_type='playlist', gm_id=gm_pid)    

def changePlaylistHandler(local_id, api, conn, get_gms_id, get_gmp_id):
    #All playlist updates are handled idempotently.

    #Get all the songs now in the playlist.
    song_rows = conn.execute("SELECT IDSong FROM PlaylistSongs WHERE IDPlaylist=? ORDER BY SongOrder", (local_id,)).fetchall()

    #Build the new playlist.
    pl = []
    for r in song_rows:
        pl.append(r[0])

    api.change_playlist(get_gmp_id(local_id), pl)

#item types should be added to handler, so we don't have to pass them around all the time

config = [
    #Song config
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_cSong',
            table='Songs',
            when="AFTER INSERT",
            id_text='new.ID'),
        handler=cSongHandler),
    
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_uSong',
            table='Songs',
            when="AFTER UPDATE OF %s" % mm_sql_cols,
            id_text='new.ID'),
        handler = uSongHandler),
    
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_dSong',
            table='Songs',
            when="AFTER DELETE",
            id_text='old.ID'),
        handler = dSongHandler),

    #Playlist config
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_cPlaylist',
            table='Playlists',
            when="AFTER INSERT",
            id_text='new.IDPlaylist'),
        handler = cPlaylistHandler),

    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_uPlaylistName',
            table='Playlists',
            when="AFTER UPDATE OF PlaylistName",
            id_text='new.IDPlaylist'),
        handler = uPlaylistNameHandler),

    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_dPlaylist',
            table='Playlists',
            when='AFTER DELETE',
            id_text='old.IDPlaylist'),
        handler = dPlaylistHandler),

    #it would be possible to do delta updates by grabbing IDPlaylistSong instead.
    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_addPlaylistSong',
            table='PlaylistSongs',
            when="AFTER INSERT",
            id_text='new.IDPlaylist'),
        handler = changePlaylistHandler),

    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_delPlaylistSong',
            table='PlaylistSongs',
            when="AFTER DELETE",
            id_text='old.IDPlaylist'),
        handler = changePlaylistHandler),

    ConfigPair(
        trigger = TriggerDef(
            name='sync2gm_movePlaylistSong',
            table='PlaylistSongs',
            when="AFTER UPDATE OF SongOrder",
            id_text='new.IDPlaylist'),
        handler = changePlaylistHandler),
    
#Autoplaylist-specific triggers:
# trigger=TriggerDef(name='sync2gm_uAPlaylistQuery',
#            table='Playlists',
#            when="AFTER UPDATE OF (QueryData)",
#            id_text='new.IDPlaylist')
]

## config end ##


def create_trigger(change_type, triggerdef, conn):
    keys = triggerdef._asdict()
    keys['change_type'] = change_type

    with conn:
        conn.execute(
            """CREATE TRIGGER {name} {when} ON {table}
BEGIN
INSERT INTO sync2gm_Changes (changeType, localId) VALUES ({change_type}, {id_text});
END""".format(**keys))

def drop_trigger(triggerdef, conn):
    with conn:
        conn.execute("DROP TRIGGER IF EXISTS {name}".format(name=triggerdef.name))

#this is just one table now
def create_service_tables(conn, numTriggers):
    with conn:
        conn.execute(
            """CREATE TABLE sync2gm_Changes(
changeId INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
changeType INTEGER CHECK (changeType BETWEEN 0 AND {changes}),
localId INTEGER NOT NULL
)""".format(changes=numTriggers))

def drop_service_tables(conn):
    with conn:
        conn.execute("DROP TABLE IF EXISTS sync2gm_Changes")
            

def attach(conn):
    success = False

    try:
        create_service_tables(conn, len(config))

        for i in range(len(config)):
            triggerdef = config[i].trigger
            create_trigger(i, triggerdef, conn)

        success = True

    except sqlite3.Error:
        success = False
        traceback.print_exc()

        detach(conn)

    finally:
        return success

def detach(conn):
    success = False

    try:
        drop_service_tables(conn)
        
        for triggerdef, handler in config:
            drop_trigger(triggerdef, conn)    

        success = True

    except sqlite3.Error:
        success = False
        traceback.print_exc()
        
    finally:
        return success
    
    
if __name__ == '__main__':

    if sys.argv[1] == "attach":
        with make_connection(sys.argv[2]) as conn:
            print attach(conn)
    elif sys.argv[1] == "detach":
        with make_connection(sys.argv[2]) as conn:
            print detach(conn)
    elif sys.argv[1] == "run":
        t = ChangePollThread(make_connection, [c.handler for c in config], sys.argv[2], 'default')
        t.start()
        
        raw_input("Running until you hit enter: ")
        
        t.stop()


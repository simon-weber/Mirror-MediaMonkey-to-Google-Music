"""Define a service configuration for MediaMonkey."""

import sqlite3
from contextlib import closing
from collections import namedtuple

from mpconf import MPConf, ActionPair, TriggerDef, HandlerResult, Handler, GMSyncError, LocalOutdated

from gmusicapi import CallFailure


#A service implements various structures and functions so that a service 
# knows how to handle changes.

#The entire configuration is a global called 'config' - 
# defined at the end of this file - which everything else supports.



#Maps a local column to a piece of gm metadata.
# to_gm_form is a function to translate from local -> gm form.
MDMapping = namedtuple('MDMapping', ['col', 'gm_key', 'to_gm_form'])

def make_md_map(col, gm_key=None, to_gm_form=None):
    """Easily create a new MDMapping."""
    if gm_key is None:
        gm_key = col[0].lower() + col[1:]

    if to_gm_form is None:
        to_gm_form = lambda data: data

    return MDMapping(col, gm_key, to_gm_form)


def to_gm_rating(r):
    """Return the GM format for a GM rating, *r*."""
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


def get_path(local_id, cur):
    """Return the full file path of this item, or raise GMSyncError. Only works for local items (eg not with media servers)."""

    path_data = cur.execute("SELECT SongPath, IDFolder from Songs WHERE ID=?", (local_id,)).fetchone()

    if path_data is None:
        raise LocalOutdated

    path, f_id = path_data

    #MM separates the path and media, so we need to get the drive letter separately.
    (d_letter,) = cur.execute("SELECT DriveLetter FROM Medias WHERE IDMedia=(SELECT IDMedia FROM Folders WHERE ID=?)", (f_id,)).fetchone()
    if path is not None and d_letter is not None:
        #d_letter is an int that needs to be coerced into the right char.
        #MM docs are inspecific, so we always coerce into ascii cap letter range.
        if d_letter < 26: d_letter = chr(d_letter + 65) #assumed given a 0-25 ord
        elif d_letter > 90: d_letter = chr(d_letter - 32) #assumed given a lowercase ascii
        else: raise GMSyncError("Could not coerce mediamonkey drive letter to a character. Given: " + repr(d_letter) + " for local_id: " + repr(local_id))

        return d_letter + path
    else:
        raise GMSyncError("Drive letter or path null for local_id: " + repr(local_id))



class cSongHandler(Handler):
    def push_changes(self):
        path = get_path(self.local_id, self.mp_cur)

        new_ids = self.api.upload(path)

        #Assume that we start from an empty library.
        if new_ids.get(path) is None:
            raise CallFailure #CallFailure not raised by upload, since partial success can happen.

        return HandlerResult(action='create', item_type='song', gm_id=new_ids[path])


class uSongHandler(Handler):
    def push_changes(self):
        mm_md = self.mp_cur.execute("SELECT %s FROM Songs WHERE ID=?" % mm_sql_cols, (self.local_id,)).fetchone()
        
        if mm_md is None:
            raise LocalOutdated

        gm_song = {}
        for col in mm_md.keys():
            mdm = col_to_mdm[col]

            gm_key = mdm.gm_key
            data = mdm.to_gm_form(mm_md)

            gm_song[gm_key] = data

        gm_song['id'] = self.gms_id

        self.api.change_song_metadata(gm_song) #TODO should switch this to a safer method
    
class dSongHandler(Handler):
    def push_changes(self):
        delIds = self.api.delete_songs(self.gms_id)

        return HandlerResult(action='delete', item_type='song', gm_id=delIds[0])

class cPlaylistHandler(Handler):
    def push_changes(self):
        #currently assuming that this is called prior to any inserts on PlaylistSongs
        playlist_data = self.mp_cur.execute("SELECT PlaylistName FROM Playlists WHERE IDPlaylist=?", (self.local_id,)).fetchone()
        
        if playlist_data is None:
            raise LocalOutdated

        new_gm_pid = self.api.create_playlist(playlist_data[0])

        return HandlerResult(action='create', item_type='playlist', gm_id=new_gm_pid)

class uPlaylistNameHandler(Handler):
    def push_changes(self):
        playlist_data = self.mp_cur.execute("SELECT PlaylistName FROM Playlists WHERE IDPlaylist=?", (self.local_id,)).fetchone()

        if playlist_data is None:
            raise LocalOutdated

        self.api.change_playlist_name(self.gmp_id, playlist_data[0])

class dPlaylistHandler(Handler):
    def push_changes(self):
        playlist_data = self.mp_cur.execute("SELECT PlaylistName FROM Playlists WHERE IDPlaylist=?", (self.local_id,)).fetchone()
        
        if playlist_data is None:
            raise LocalOutdated

        gm_pid = self.gmp_id

        self.api.delete_playlist(gm_pid)

        return HandlerResult(action='delete', item_type='playlist', gm_id=gm_pid)    

class changePlaylistHandler(Handler):
    def push_changes(self):
        #All playlist updates are handled idempotently.
        
        #Ensure the playlist exists.
        if self.mp_cur.execute("SELECT IDPlaylist FROM Playlists WHERE IDPlaylist=?", (self.local_id,)).fetchone() is None:
            raise LocalOutdated

        #Get all the songs now in the playlist.
        song_rows = self.mp_cur.execute("SELECT IDSong FROM PlaylistSongs WHERE IDPlaylist=? ORDER BY SongOrder", (self.local_id,)).fetchall()


        #Build the new playlist.
        pl = []
        for r in song_rows:
            pl.append(r[0])

        self.api.change_playlist(self.gmp_id, pl)


#Define how to set up the connection, since MediaMonkey needs a custom collation function.
#It won't allow string queries without it.
#Credit to Sproaticus: http://www.mediamonkey.com/forum/viewtopic.php?p=127635#127635
def make_connection(db_path):
    """Return a connection to MediaMonkey database at *db_path*."""

    def iUnicodeCollate(s1, s2):
        return cmp(s1.lower(), s2.lower())

    conn = sqlite3.connect(db_path, timeout=60) #MM locks the database for an obscenely long time
    conn.row_factory = sqlite3.Row
    conn.create_collation('IUNICODE', iUnicodeCollate)
    #There are also USERLOCALE and NUMERICSTRING collations referred to here:
    #http://www.mediamonkey.com/wiki/index.php/MediaMonkey_Database_structure

    return conn



config = MPConf(make_connection=make_connection,
                action_pairs = [             
        ActionPair(
            trigger = TriggerDef(
                        name='sync2gm_cSong',
                        table='Songs',
                        when="AFTER INSERT",
                        id_text='new.ID'),
            handler=cSongHandler),

        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_uSong',
                table='Songs',
                when="AFTER UPDATE OF %s" % mm_sql_cols,
                id_text='new.ID'),
            handler = uSongHandler),

        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_dSong',
                table='Songs',
                when="AFTER DELETE",
                id_text='old.ID'),
            handler = dSongHandler),

        #Playlist config
        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_cPlaylist',
                table='Playlists',
                when="AFTER INSERT",
                id_text='new.IDPlaylist'),
            handler = cPlaylistHandler),

        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_uPlaylistName',
                table='Playlists',
                when="AFTER UPDATE OF PlaylistName",
                id_text='new.IDPlaylist'),
            handler = uPlaylistNameHandler),

        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_dPlaylist',
                table='Playlists',
                when='AFTER DELETE',
                id_text='old.IDPlaylist'),
            handler = dPlaylistHandler),

        #it would be possible to do delta updates by grabbing IDPlaylistSong instead.
        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_addPlaylistSong',
                table='PlaylistSongs',
                when="AFTER INSERT",
                id_text='new.IDPlaylist'),
            handler = changePlaylistHandler),

        ActionPair(
            trigger = TriggerDef(
                name='sync2gm_delPlaylistSong',
                table='PlaylistSongs',
                when="AFTER DELETE",
                id_text='old.IDPlaylist'),
            handler = changePlaylistHandler),

        ActionPair(
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
                )

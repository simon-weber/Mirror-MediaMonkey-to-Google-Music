#sync2gm and mm2gm: sync MediaMonkey to Google Music

Built on [gmusicapi](https://github.com/simon-weber/Unofficial-Google-Music-API), this project aims to sync a MediaMonkey library to Google Music.

The implementation will be a local service that, given a database with a specific layout, will push changes to Google Music. This should be mediaplayer-agnostic. To support some other mediaplayer, someone would have to implement the attachment to the database, and the initial sync. From there, the service should be able to keep the local library synced.

The project is not supported nor endorsed by Google.

##Design

###Attaching to the local database

"Attaching" sets up our own state on the local database. The following schemas must be matched exactly for the service to work (out of the box, it could always be edited). The example code is for sqlite.

**creates the "sync2gm_Changes" table**:
This is a queue of changes to the local database that will be synced to Google Music. Mediaplayer-formatted data is stored, and is converted by the service later. It has the following columns:

* changeId
* changeType - 0-5 enum for {C,U,D}x{song, playlist}
* localId - mediaplayer id. null for creations.
* songUploadPath - for song creation, the path of the file to upload. null otherwise.
* playlistName - for playlist create/update, the name of the playlist. null otherwise.
* a column for each piece of local song metadata. null except for uSong.


    CREATE TABLE sync2gm_Changes(
	   changeId INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	   changeType CHECK (changeType BETWEEN 0 AND 5),
	   localId TEXT,
	   songUploadPath TEXT,
	   playlistName TEXT,
	   Artist TEXT,
	   Album TEXT,
	   AlbumArtist TEXT,
	   Comment TEXT,
	   Genre TEXT,
	   Rating INTEGER,
	   Year INTEGER,
	   DiscNumber TEXT,
	   TrackNumber TEXT,
	   BPM INTEGER,
	   SongTitle TEXT
    )

**creates the "sync2gm_PlaylistChanges" table**:
For each playlist update, this table holds all of the songs in the playlist. I'm not sure how to deal with autoplaylists that just store their query information - it's probably best done by comparing the result queries every so often and uploading when they change. Perhaps the user could force an update as well.

* changeId (foreign)
* gmSongId - (unique) Google Music id of a song in the updated playlist

    CREATE TABLE sync2gm_PlaylistChanges(
    	   changeId INTEGER REFERENCES sync2gm_Changes,
	   gmSongId TEXT UNIQUE NOT NULL
    )

**sets up relevant triggers**:
These triggers will auto-populate the above tables when things are changed locally.

cSong:

    CREATE TRIGGER sync2gm_create AFTER INSERT ON Songs
    BEGIN
	INSERT INTO sync2gm_Changes (changeType, songUploadPath) VALUES (0, new.SongPath);
    END

uSong:

    CREATE TRIGGER sync2gm_update AFTER UPDATE OF (Artist, Album, AlbumArtist, Comment, Genre, Rating, Year, DiscNumber, TrackNumber, BPM, SongTitle) ON Songs
    BEGIN
	INSERT INTO sync2gm_Changes (changeType, gmId, Artist, Album, AlbumArtist, Comment, Genre, Rating, Year, DiscNumber, TrackNumber, BPM, SongTitle) VALUES (1, new.ID, new.Artist, new.Album, new.AlbumArtist, new.Comment, new.Genre, new.Rating, new.Year, new.DiscNumber, new.TrackNumber, new.BPM, new.SongTitle);
    END

dSong:

    CREATE TRIGGER sync2gm_delete AFTER DELETE ON Songs
    BEGIN
	INSERT INTO sync2gm_Changes (changeType, localId) VALUES (2, old.ID);
    END

(Playlists not yet implemented)


**creates the "sync2gm_GMSongIds" table**:
This table relates local song ids to Google Music song ids, and is updated by the service when uploads and deletions are performed. This is 1-to-1, but is pulled out so we don't need to add columns to the local database.

* localId (foreign, primary)
* gmId (unique)


    CREATE TABLE sync2gm_GMSongIds(
    	   localId INTEGER PRIMARY KEY REFERENCES Songs(ID),
	   gmId TEXT UNIQUE NOT NULL
    )

**creates the "sync2gm_GMPlaylistIds" table**:
Like the Songids table, but for playlists.

* localId (foreign, primary)
* gmId (unique)


    CREATE TABLE sync2gm_GMPlaylistIds(
    	   localId INTEGER PRIMARY KEY REFERENCES Playlists(IDPlaylist),
	   gmId TEXT UNIQUE NOT NULL
    )

###Initial sync
Before the service can begin to sync changes, the Google Music library must be empty, and the Changes table must be manually populated with creations of all the current local songs. This implies uploading all of the music - which is necessary so the local service can map local ids to Google Music ids.

###Continuous sync
Now, the local service can take over. To make this cross-platform, I'm thinking of implementing the service as an RPC server running in Python. The server, once running, would accept commands to start syncing and stop syncing. While syncing, it polls the Changes table, then pushes out changes to Google Music. After a change is verified as successful, that row in the Changes table is deleted.

###Detaching from the local database
This would just remove the tables created in the attachment step. Resyncing after this point would require going through the entire process again (including re-uploading all the songs).

- - -


Copyright 2012 [Simon Weber](https://plus.google.com/103350848301234480355).  
Licensed under the 3-clause BSD. See COPYING.

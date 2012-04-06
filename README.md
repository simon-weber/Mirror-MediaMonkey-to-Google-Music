#sync2gm and mm2gm: sync MediaMonkey to Google Music

Built on [gmusicapi](https://github.com/simon-weber/Unofficial-Google-Music-API), this project aims to sync a MediaMonkey library to Google Music.

The implementation will be a local service that, given a database with a specific layout, will push changes to Google Music. This should be mediaplayer-agnostic. To support some other mediaplayer, someone would have to implement the attachment to the database, and the initial sync. From there, the service should be able to keep the local library synced.

The project is not supported nor endorsed by Google.

##Design

###Attaching to the local database

"Attaching" sets up our own state on the local database. The following schemas must be matched exactly for the service to work (out of the box, it could always be edited). The example code is for sqlite and MediaMonkey.

**creates the "sync2gm_Changes" table**:
This is a queue of changes to the local database that will be synced to Google Music. Only a change type and local id is stored. The service handles gathering the necessary data.

* changeId
* changeType - 0-n enum for the different kinds of updates that can happen; something like |{c,u,d}x{song, playlist}|
* localId - mediaplayer id.

schema:

    CREATE TABLE sync2gm_Changes(
	   changeId INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	   changeType NOT NULL CHECK (changeType BETWEEN 0 AND <n>),
	   localId <type of local db> NOT NULL
    )


**sets up relevant triggers**:
These triggers will auto-populate the change table when things are happen locally. They differ in the changeType they provide, the table they operate on, and the local item id they select (song vs playlist).

eg cSong:

    CREATE TRIGGER sync2gm_cSong AFTER INSERT ON Songs
    BEGIN
	INSERT INTO sync2gm_Changes (changeType, localId) VALUES (0, new.ID);
    END


eg dPlaylist:

    CREATE TRIGGER sync2gm_dPlaylist AFTER DELETE ON Playlists
    BEGIN
	INSERT INTO sync2gm_Changes (changeType, localId) VALUES (3, old.IDPlaylist);
    END


**creates the "sync2gm_GMSongIds" table**:
This table relates local song ids to Google Music song ids, and is updated by the service when uploads and deletions are performed. This is 1-to-1, but is pulled out so we don't need to add columns to the local database. Updates to this table are performed automatically by the service when items are created/deleted.

* localId (foreign, primary)
* gmId (unique)

schema:

    CREATE TABLE sync2gm_GMSongIds(
    	   localId INTEGER PRIMARY KEY REFERENCES Songs(ID),
	   gmId TEXT UNIQUE NOT NULL
    )

**creates the "sync2gm_GMPlaylistIds" table**:
Like the Songids table, but for playlists.

schema:

    CREATE TABLE sync2gm_GMPlaylistIds(
    	   localId INTEGER PRIMARY KEY REFERENCES Playlists(IDPlaylist),
	   gmId TEXT UNIQUE NOT NULL
    )

###Initial sync
Before the service can begin to sync changes, the Google Music library must be empty, and the Changes table must be manually populated with creations of all the current local items. This implies uploading all of the music - which is necessary so the local service can map local ids to Google Music ids.

###Continuous sync
Now, the local service can take over. To make this cross-platform, I'm thinking of implementing the service as an RPC server running in Python. The server, once running, would accept commands to start syncing and stop syncing. While syncing, it polls the Changes table, then pushes out changes to Google Music. After a change is verified as successful, that row in the Changes table is deleted.

###Detaching from the local database
This would just remove the tables created in the attachment step. Resyncing after this point would require going through the entire process again (including re-uploading all the songs).

- - -


Copyright 2012 [Simon Weber](https://plus.google.com/103350848301234480355).  
Licensed under the 3-clause BSD. See COPYING.

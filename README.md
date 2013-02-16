#sync2gm and mm2gm: sync MediaMonkey to Google Music

I haven't worked on this in a long time, but I'm thinking of reviving it in a simpler form. Instead of watching a database, I'd just watch a filesystem: watchdog makes this pretty simple. This would get you most of the way there if you keep an organized filesystem and write out tag changes.

The old readme is below:

- - -

Built on [gmusicapi](https://github.com/simon-weber/Unofficial-Google-Music-API), this project aims to sync a MediaMonkey library to Google Music.

The MediaMonkey implementation will be separate from the underlying Google Music syncing service, which will be platform and mediaplayer agnostic. This should allow easy adaptation to other mediaplayers with an sqlite3 database (Banshee, Songbird, Clemtine, etc).

The project is not supported nor endorsed by Google.

##Design

The project does not yet have an implementation. The current prospective design is outlined below.

There are two pieces to an implementation: the service (sync2gm) and the client (mm2gm). The service actually pushes out changes, while the client is responsible for setting it up and running the service.

The service is simple: a thread that polls for updates in a work queue, wrapped with some Twisted networking logic for cross-platform communication with the client. It persists configuration on disk.

The client's configuration tells the service which triggers should be set up, and how to handle a change logged by each trigger.

Here are the steps involved in setup and teardown of the service for some media database:

###Attaching to the local database
This sets up our own state on the local database. This is done once for a database by the client, before the service is run. A work queue table and triggers to populate it is created, along with tables mapping local items (song/playlists) to remote (Google Music) items.

###Initial sync
Next, the client clears the Google Music library, and manually populates the work queue with fake creations of every song in the library.

Note that this requires re-uploading of all songs in the local library. This is necessary so that the service can associate local items with remote items.

###Continuous sync
Now, the service can take over. It continually polls the work queue for changes in the local library, and pushes them out as it was configured to. The syncing process can be started and stopped with a very simple tcp protocol.

"Autoplaylists" that are stored as a query present a slight wrinkle. Since queries can use arbitrary song metadata that may not be syncing up to Google Music, the triggers may not detect every change in an autoplaylist's contents. These could then be handled either by persisting their contents and polling for a change, or simply by always assuming a change. The latter may be simpler when dealing with idempotent api functions.

###Detaching from the local database
This removes the tables and triggers from attaching. Setting up syncing again would involve re-uploading all music.

- - -


Copyright 2012 [Simon Weber](http://www.simonmweber.com).  
Licensed under the 3-clause BSD. See COPYING.

Backup your flickr photos and videos.


# Intentions

Originally had grand plans about a read/write subversion-like interface to
flickr photos. And not just flickr, with a generic interface that could support
photobucket, et al.

The reality: the only reliable or useful parts of this tool are: `pics checkout
...`, `pics update ...`, and the 'simpleflickrapi.py' Flickr API client library.

Yes, there need to me more docs here. Yes, the crud needs to be stripped out.


# Usage

1.  Get pics:

        git clone https://github.com/trentm/pics.git
        export PATH=`pwd`/pics/bin:$PATH

2.  Get a flickr api key: http://www.flickr.com/services/apps/create/apply/

3.  Write your key and secret to: `~/.flickr/API_KEY` and `~/.flickr/SECRET`
    respectively.

4.  Learn how to checkout: `pics help checkout`

5.  Checkout some of your flickr pics:

        $ pics checkout flickr://YOUR-FLICKR-NAME/ photos -s small -b 2011-12-01
        * * *
        Requesting 'read' permission to your Flickr photos in
        your browser. Press <Return> when you've finished authorizing.
        
        If your browser doesn't open automatically, please visit to authorize:
          http://flickr.com/services/auth/?perms=read&...
        * * *
        pics: A  photos/2011-11/6485824601.small.jpg  [O-nacho!!!]
        ...

    A bare `pics checkout flickr://NAME/ DIR` will download the original
    of all your photos and videos.

6.  This "working copy" download is updatable (i.e. if you've added/changed)
    photos in flickr or changed metadata:
    
        cd .../photos
        pics update
    
    `pics update` also works to restart an aborted checkout. This is useful
    if it is taking too long to download the whole kaboodle.


# License

MIT. See LICENSE.txt.


# Copyright (c) 2008 ActiveState Software Inc.

"""cmdln.Shell class defining the 'pics ...' command line interface."""

import os
from os.path import dirname, join, expanduser
import sys
import logging
from pprint import pprint

try:
    import cmdln
except ImportError:
    sys.path.insert(0, expanduser("~/tm/cmdln/lib"))
    import cmdln
    del sys.path[0]

import picslib
from picslib.errors import PicsError
from picslib import flickrapi
from picslib import utils

log = logging.getLogger("pics")




class PicsShell(cmdln.Cmdln):
    """${name} -- a Subversion-like front end for Flickr photos

    Usage:
        ${name} SUBCOMMAND [ARGS...]
        ${name} help SUBCOMMAND       # help on a specific command

    ${option_list}
    ${command_list}
    ${help_list}
    """
    name = 'pics'
    version = picslib.__version__
    helpindent = '  '

    def get_optparser(self):
        parser = cmdln.Cmdln.get_optparser(self)
        parser.add_option("-v", "--verbose", dest="log_level",
                          action="store_const", const=logging.DEBUG,
                          help="more verbose output")
        parser.add_option("-q", "--quiet", dest="log_level",
                          action="store_const", const=logging.WARNING,
                          help="quieter output")
        parser.set_defaults(log_level=logging.INFO)
        return parser

    def postoptparse(self):
        global log
        log.setLevel(self.options.log_level)

    def do_play(self, subcmd, opts):
        """Run my current play/dev code.

        ${cmd_usage}
        ${cmd_option_list}
        """
        api_key = utils.get_flickr_api_key()
        secret = utils.get_flickr_secret()
        api = flickrapi.FlickrAPI(api_key, secret)
        #TODO: Getting the token/frob is hacky. C.f.
        #      http://flickr.com/services/api/auth.howto.mobile.html
        token = api.getToken(
            #browser="/Applications/Safari.app/Contents/MacOS/Safari"
            browser="/Applications/Firefox.app/Contents/MacOS/firefox"
        )
        rsp = api.favorites_getList(api_key=api_key, auth_token=token)
        api.testFailure(rsp)
        for a in rsp.photos[0].photo:
            print a.attrib
            print "%10s: %s" % (a['id'], a['user'], a['title'].encode("ascii", "replace"))

    @cmdln.alias("co")
    def do_checkout(self, subcmd, opts, url, path):
        """${cmd_name}: Checkout a working copy of photos

        ${cmd_usage}
        ${cmd_option_list}

        Setup a pics working area. For example, the following will setup
        '~/pics' to working with user trento's flickr photos.

            pics co flickr://trento/ ~/pics

        The URL is of the form "flickr://<username-or-id>/"
        Basically the only useful piece of information here is your
        flickr username or id, but I'm leaving this open for potential
        integration with other photo sites.

        TODO: describe default of dl'ing only latest N pics
        """
        repo_type, repo_user = _parse_source_url(url)
        if repo_type != "flickr":
            raise PicsError("unsupported pics repository type: %r" % repo_type)
        if exists(path) and not isdir(path):
            raise PicsError("`%s' is already a file/something else" % path)
        if exists(path):
            raise NotImplementedError("`%s' exists: 'pics checkout' into "
                                      "existing dir is not yet supported"
                                      % path)
        wc = WorkingCopy(path)
        wc.create(repo_type, repo_user)
        #TODO: separate empty wc creation (wc.create()) and checkout
        #      of latest N photos (wc.update(...))?




#!/usr/bin/env python
# Copyright (c) 2007 Trent Mick
# License: MIT License
# Author:
#   Trent Mick (trentm@gmail.com)

r"""pics -- sort of like svn for photos, flickr.com is the repository"""

__revision__ = "$Id$"
__version_info__ = (0, 1, 0)
__version__ = '.'.join(map(str, __version_info__))

import os
from os.path import (isfile, isdir, exists, dirname, abspath, splitext, join,
                     normpath)
import sys
import stat
import re
import logging
import optparse
import traceback
import time
from pprint import pprint
import webbrowser
import warnings

_contrib_dir = join(dirname(abspath(__file__)), "contrib")
sys.path.insert(0, join(_contrib_dir, "cmdln"))
try:
    import cmdln
finally:
    del sys.path[0]
sys.path.insert(0, join(_contrib_dir, "FlickrAPI"))
try:
    import flickrapi
finally:
    del sys.path[0]
del _contrib_dir



#---- exceptions and globals

log = logging.getLogger("pics")
TOPLEVEL_EXC_VERBOSITY = "full" # quiet | short | full

#TODO: defer the file read here. Isn't always needed or wanted.
API_KEY = open(join(dirname(__file__), "API_KEY")).read().strip()
SECRET = open(join(dirname(__file__), "SECRET")).read().strip()

class PicsError(Exception):
    pass

class FSError(PicsError):
    """An error in the file system wrapper."""



#---- internal support stuff


# Recipe: splitall (0.2) in /Users/trentm/tm/recipes/cookbook
def _splitall(path):
    r"""Split the given path into all constituent parts.

    Often, it's useful to process parts of paths more generically than
    os.path.split(), for example if you want to walk up a directory.
    This recipe splits a path into each piece which corresponds to a
    mount point, directory name, or file.  A few test cases make it
    clear:
        >>> splitall('')
        []
        >>> splitall('a/b/c')
        ['a', 'b', 'c']
        >>> splitall('/a/b/c/')
        ['/', 'a', 'b', 'c']
        >>> splitall('/')
        ['/']
        >>> splitall('C:\\a\\b')
        ['C:\\', 'a', 'b']
        >>> splitall('C:\\a\\')
        ['C:\\', 'a']

    (From the Python Cookbook, Files section, Recipe 99.)
    """
    allparts = []
    while 1:
        parts = os.path.split(path)
        if parts[0] == path:  # sentinel for absolute paths
            allparts.insert(0, parts[0])
            break
        elif parts[1] == path: # sentinel for relative paths
            allparts.insert(0, parts[1])
            break
        else:
            path = parts[0]
            allparts.insert(0, parts[1])
    allparts = [p for p in allparts if p] # drop empty strings 
    return allparts


# Recipe: relpath (0.2) in /Users/trentm/tm/recipes/cookbook
def _relpath(path, relto=None):
    """Relativize the given path to another (relto).

    "relto" indicates a directory to which to make "path" relative.
        It default to the cwd if not specified.
    """
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if relto is None:
        relto = os.getcwd()
    else:
        relto = os.path.abspath(relto)

    if sys.platform.startswith("win"):
        def _equal(a, b): return a.lower() == b.lower()
    else:
        def _equal(a, b): return a == b

    pathDrive, pathRemainder = os.path.splitdrive(path)
    if not pathDrive:
        pathDrive = os.path.splitdrive(os.getcwd())[0]
    relToDrive, relToRemainder = os.path.splitdrive(relto)
    if not _equal(pathDrive, relToDrive):
        # Which is better: raise an exception or return ""?
        return ""
        #raise OSError("Cannot make '%s' relative to '%s'. They are on "\
        #              "different drives." % (path, relto))

    pathParts = _splitall(pathRemainder)[1:] # drop the leading root dir
    relToParts = _splitall(relToRemainder)[1:] # drop the leading root dir
    #print "_relpath: pathPaths=%s" % pathParts
    #print "_relpath: relToPaths=%s" % relToParts
    for pathPart, relToPart in zip(pathParts, relToParts):
        if _equal(pathPart, relToPart):
            # drop the leading common dirs
            del pathParts[0]
            del relToParts[0]
    #print "_relpath: pathParts=%s" % pathParts
    #print "_relpath: relToParts=%s" % relToParts
    # Relative path: walk up from "relto" dir and walk down "path".
    relParts = [os.curdir] + [os.pardir]*len(relToParts) + pathParts
    #print "_relpath: relParts=%s" % relParts
    relPath = os.path.normpath( os.path.join(*relParts) )
    return relPath


# Recipe: pretty_logging (0.1) in C:\trentm\tm\recipes\cookbook
class _PerLevelFormatter(logging.Formatter):
    """Allow multiple format string -- depending on the log level.
    
    A "fmtFromLevel" optional arg is added to the constructor. It can be
    a dictionary mapping a log record level to a format string. The
    usual "fmt" argument acts as the default.
    """
    def __init__(self, fmt=None, datefmt=None, fmtFromLevel=None):
        logging.Formatter.__init__(self, fmt, datefmt)
        if fmtFromLevel is None:
            self.fmtFromLevel = {}
        else:
            self.fmtFromLevel = fmtFromLevel
    def format(self, record):
        record.levelname = record.levelname.lower()
        if record.levelno in self.fmtFromLevel:
            #XXX This is a non-threadsafe HACK. Really the base Formatter
            #    class should provide a hook accessor for the _fmt
            #    attribute. *Could* add a lock guard here (overkill?).
            _saved_fmt = self._fmt
            self._fmt = self.fmtFromLevel[record.levelno]
            try:
                return logging.Formatter.format(self, record)
            finally:
                self._fmt = _saved_fmt
        else:
            return logging.Formatter.format(self, record)

def _setup_logging():
    hdlr = logging.StreamHandler()
    defaultFmt = "%(name)s: %(levelname)s: %(message)s"
    infoFmt = "%(name)s: %(message)s"
    fmtr = _PerLevelFormatter(fmt=defaultFmt,
                              fmtFromLevel={logging.INFO: infoFmt})
    hdlr.setFormatter(fmtr)
    logging.root.addHandler(hdlr)


_g_source_url_pats = [
    ("flickr", re.compile("^flickr://(?P<user>.*?)/?$")),
    #("flickr", re.compile("^http://(www\.)?flickr\.com/photos/(?P<user>.*?)/?$")),
]
def _parse_source_url(url):
    """Parse a repository source URL (as passed to 'pics setup').

        >>> _parse_source_url("flickr://someuser/")
        ('flickr', 'someuser')
    """
    for type, pat in _g_source_url_pats:
        match = pat.search(url)
        if match:
            return type, match.group("user")
    else:
        raise PicsError("invalid source url: %r" % url)


class _FileSystem(object):
    def __init__(self, log=None):
        """Create a FileSystem interaction wrapper.
        
            "log" is a default logger stream to use. Most methods have a log
                optional argument that can be used to override this.
        """
        self._log = log

    def log(self, log, msg, *args):
        if log:
            log(msg, *args)
        else:
            self._log(msg, *args)

    def _mode_from_mode_arg(self, mode_arg, default):
        """Convert a mode argument (common to a few fs methods) to a real
        int mode. Mode "names" are supported, like "hidden".
        """
        if mode_arg is None:
            return default
        elif isinstance(mode_arg, int):
            return mode_arg
        else:
            raise FSError("unsupported mode arg: %r" % mode_arg) 

    def mkdir(self, dir, mode=None, parents=False, log=None):
        mode = self._mode_from_mode_arg(mode, 0777)
        self.log(log, "mkdir%s%s `%s'", (parents and " -p" or ""),
                 (mode is not None and "-m "+oct(mode) or ""), dir)
        if parents:
            if exists(dir):
                pass
            else:
                os.makedirs(dir, mode)
        else:
            os.mkdir(dir, mode)
        

class WorkingCopy(object):
    API_VERSION_INFO = (0,1,0)

    def __init__(self, base_dir):
        self.base_dir = normpath(base_dir)
        self.fs = _FileSystem(log.debug)

    @property
    def version(self):
        if self._version_cache is None:
            version_path = join(self.base_dir, ".pics", "version")
            self._version_cache = open(version_path, 'r').read().strip()
        return self._version_cache
    _version_cache = None

    @property
    def version_info(self):
        return tuple(map(int, self.version.split('.')))

    def __repr__(self):
        return "<WorkingCopy v%s>" % self.version

    @property
    def api(self):
        if self._api_cache is None:
            self._api_cache = flickrapi.FlickrAPI(API_KEY, SECRET)
        return self._api_cache
    _api_cache = None 

    @property
    def token(self):
        if self._token_cache is None:
            #TODO: Getting the token/frob is hacky. C.f.
            #      http://flickr.com/services/api/auth.howto.mobile.html
            self._token_cache = self.api.getToken(
                #browser="/Applications/Safari.app/Contents/MacOS/Safari"
                browser="/Applications/Firefox.app/Contents/MacOS/firefox"
            )
        return self._token_cache
    _token_cache = None 

    def create(self):
        dir_structure = [
            ('d', self.base_dir),
            ('d', join(self.base_dir, ".pics")),
        ]
        #TODO: create control dirs 
#        log.info("create `%s'", self.base_dir)
#        self.fs.mkdir(self.base_dir, parents=True)
#        
#        base_cntl_dir = join(self.base_dir, ".pics")
#        self.fs.mkdir(base_cntl_dir) #TODO: mode="hidden" for win32
#        ver_str = '.'.join(map(str, self.API_VERSION))
#        open(join(base_cntl_dir, "version"), 'w').write(ver_str)
#        

        # Get the latest N photos up to M months ago (rounded down) --
        # whichever is less.
        N = 3
        #TODO: get the month calc correct
        M = 3
        min_date = time.time() - M*30*24*60*60
        rsp = self.api.photos_recentlyUpdated(
                api_key=API_KEY, auth_token=self.token,
                min_date=str(int(min_date)),
                extras="date_taken,owner_name,last_update",
                per_page=str(N), page=str(1))
        self.api.testFailure(rsp)
        recents = rsp.photos[0].photo
        for recent in recents:
            pprint(recent.attrib)
        #START HERE:
        # - Work on a nicer API that does datetime, type handling. Will
        #   pay off in the long run.

        #TODO: create favs/...
        #      Just start with the most recent N favs.
#        log.info("create `%s/favs'", self.base_dir)
#        self.fs.mkdir(join(self.base_dir, "favs"))
#        self.fs.mkdir(join(self.base_dir, "favs", ".pics")) #TODO: hidden

    def upgrade(self):
        raise NotImplementedError("working copy upgrade not yet implemented")

    def check_version(self):
        if self.version_info != self.API_VERSION_INFO:
            raise PicsError("out of date working copy (v%s < v%s): you must "
                            "first upgrade", self.version_info,
                            '.'.join(map(str(self.API_VERSION))))

#    def initialize(self):
#        self.check_version()
#        self.api = flickrapi.FlickrAPI(API_KEY, SECRET)
#        #TODO: Getting the token/frob is hacky. C.f.
#        #      http://flickr.com/services/api/auth.howto.mobile.html
#        self.token = self.api.getToken(
#            #browser="/Applications/Safari.app/Contents/MacOS/Safari"
#            browser="/Applications/Firefox.app/Contents/MacOS/firefox"
#        )
#
#    def finalize(self):
#        pass

    def list(self, paths):
        for i, path in enumerate(paths):
            subpath = _relpath(path, self.base_dir)
            log.debug("list `%s'", subpath)
            if len(paths) > 1:
                if i > 0:
                    print
                print path, ":"
            if subpath == "favs":
                return self._list_favs(path)
            else:
                raise NotImplementedError("'pics list' for %r" % subpath)
    
    def _list_favs(self, path):
        # Example response fav dict:
        #   {u'isfamily': u'0', u'title': u'Sun & Rain', u'farm': u'1',
        #    u'ispublic': u'1', u'server': u'2', u'isfriend': u'0',
        #    u'secret': u'681c057c50', u'owner': u'35034353159@N01',
        #    u'id': u'3494168'}
        # 
        # $ ls -l
        # -rw-r--r--    1 trentm  trentm      3 13 Nov  2004 .CFUserTextEncoding
        #
        # Notes:
        # - Listing to "long" format here.
        rsp = self.api.favorites_getList(api_key=API_KEY, auth_token=self.token)
        #TODO: something is wrong, why are all 'p--'?
        self.api.testFailure(rsp)
        favs = rsp.photos[0].photo
        print len(favs), (len(favs)==1 and "photo" or "photos")
        for fav in favs:
            #print fav.attrib
            info = {
                "mode": self._mode_str_from_photo_dict(fav),
                "id": fav["id"],
                "title": fav['title'].encode("ascii", "replace"),
            }
            print "%(mode)s  %(id)9s  %(title)s" % info

    def _mode_str_from_photo_dict(self, photo):
        """Photo mode string:
            'pfF' for ispublic, isfriend, isfamily
        
        TODO: Would be nice to have iscontact, something for copyright?,
        taken date of photo, date made a fav (if available)
        """
        mode_str = (int(photo["ispublic"]) and 'p' or '-')
        mode_str += (int(photo["isfriend"]) and 'f' or '-')
        mode_str += (int(photo["isfamily"]) and 'F' or '-')
        return mode_str



#---- shell

class Shell(cmdln.Cmdln):
    r"""pics -- like svn for photos, flickr.com is the repository

    usage:
        ${name} SUBCOMMAND [ARGS...]
        ${name} help SUBCOMMAND

    ${option_list}
    ${command_list}
    ${help_list}
    """
    name = "pics"
    #XXX There is a bug in cmdln.py alignment when using this. Leave it off
    #    until that is fixed.
    #helpindent = ' '*4

    def do_play(self, subcmd, opts):
        """Run my current play/dev code.

        ${cmd_usage}
        ${cmd_option_list}
        """
        api = flickrapi.FlickrAPI(API_KEY, SECRET)
        #TODO: Getting the token/frob is hacky. C.f.
        #      http://flickr.com/services/api/auth.howto.mobile.html
        token = api.getToken(
            #browser="/Applications/Safari.app/Contents/MacOS/Safari"
            browser="/Applications/Firefox.app/Contents/MacOS/firefox"
        )
        rsp = api.favorites_getList(api_key=API_KEY, auth_token=token)
        api.testFailure(rsp)
        for a in rsp.photos[0].photo:
            print a.attrib
            print "%10s: %s" % (a['id'], a['user'], a['title'].encode("ascii", "replace"))

    def do_go(self, subcmd):
        """Open flickr.com

        ${cmd_usage}
        ${cmd_option_list}
        """
        webbrowser.open("http://flickr.com/")

#    def do_setup(self, subcmd, opts, url, path):
#        """Setup a working copy of photos.
#
#        ${cmd_usage}
#        ${cmd_option_list}
#
#        Setup a pics working area. For example, the following will setup
#        '~/pics' to working with user trento's flickr photos.
#
#            pics setup flickr://trento/ ~/pics
#
#        The URL is either "flickr://<username-or-id>/" or the standard
#        flickr user photos URL, e.g.
#        "http://www.flickr.com/photos/trento/". Basically the only
#        useful piece of information here is your flickr username or id,
#        but I'm leaving this open for potential integration with other
#        photo sites.
#
#        Note that 'pics setup' doesn't download any photos; just
#        prepares the area to do so (typically via 'pics up').
#
#        DEPRECATED: Use 'pics checkout'
#        """
#        repo_type, repo_user = _parse_source_url(url)
#        if repo_type != "flickr":
#            raise PicsError("unsupported pics repository type: %r" % repo_type)
#        base_pics = join(path, ".pics")
#        if exists(path) and not exists(base_pics):
#            raise PicsError("`%s' exists but doesn't look like a pics "
#                            "working copy" % path)
#        
#        wc = WorkingCopy(path)
#        if exists(path):
#            return wc.upgrade()
#        else:
#            return wc.setup()

    @cmdln.alias("co")
    def do_checkout(self, subcmd, opts, url, path):
        """Checkout a working copy of photos

        ${cmd_usage}
        ${cmd_option_list}

        Setup a pics working area. For example, the following will setup
        '~/pics' to working with user trento's flickr photos.

            pics setup flickr://trento/ ~/pics

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
        wc.create()

    def _find_base_dir(self):
        """Determine the working copy base dir from the CWD."""
        if exists(join(".pics", "version")):
            return os.curdir
        # So far the pics structure only goes one level deep.
        if exists(join(os.pardir, ".pics", "version")):
            return os.pardir
        raise PicsError("couldn't determine working copy base dir from cwd")

    def _get_wc(self):
        if not isdir(".pics"):
            raise PicsError("this is not a pics working copy: no `.pics' "
                            "directory")
        return WorkingCopy(self._find_base_dir())

    @cmdln.alias("ls")
    def do_list(self, subcmd, opts, *target):
        """List photos entries in the repository.

        ${cmd_usage}
        ${cmd_option_list}
        """
        targets = target or [os.curdir]
        wc = self._get_wc()
        wc.initialize()
        try:
            wc.list(targets)
        finally:
            wc.finalize()

    def do_add(self, subcmd, opts, *path):
        """Put files and dirs under pics control.

        ${cmd_usage}
        ${cmd_option_list}

        TODO: --tag,-t to add a tag
        """
        raise NotImplementedError("add")

    #TODO: some command(s) for editing pic data
    #   - allow batch changes
    #   - either 'edit' or a set of 'prop*'-like cmds

    @cmdln.alias("up")
    def do_update(self, subcmd, opts, *path):
        """Bring data from the repository (flickr.com) in the working
        copy.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("update")

    @cmdln.alias("di")
    def do_diff(self, subcmd, opts, *path):
        """Show pic and meta-data differences.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("diff")

    @cmdln.alias("stat", "st")
    def do_status(self, subcmd, opts, *path):
        """Show the status of working files and dirs.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("status")

    @cmdln.alias("ci")
    def do_commit(self, subcmd, opts, *path):
        """Send changes from your working copy to the repository
        (flickr).

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("commit")

    




#---- mainline

def _set_verbosity(option, opt_str, value, parser):
    global log
    log.setLevel(logging.DEBUG)

def _set_logger_level(option, opt_str, value, parser):
    # Optarg is of the form '<logname>:<levelname>', e.g.
    # "codeintel:DEBUG", "codeintel.db:INFO".
    lname, llevelname = value.split(':', 1)
    llevel = getattr(logging, llevelname)
    logging.getLogger(lname).setLevel(llevel)

def _do_main(argv):
    shell = Shell()
    optparser = cmdln.CmdlnOptionParser(shell, version="ci2 "+__version__)
    optparser.add_option("-v", "--verbose", 
        action="callback", callback=_set_verbosity,
        help="More verbose output.")
    optparser.add_option("-L", "--log-level",
        action="callback", callback=_set_logger_level, nargs=1, type="str",
        help="Specify a logger level via '<logname>:<levelname>'.")
    return shell.main(sys.argv, optparser=optparser)


def main(argv=sys.argv):
    _setup_logging() # defined in recipe:pretty_logging
    log.setLevel(logging.INFO)
    try:
        retval = _do_main(argv)
    except KeyboardInterrupt:
        sys.exit(1)
    except SystemExit:
        raise
    except:
        skip_it = False
        exc_info = sys.exc_info()
        if hasattr(exc_info[0], "__name__"):
            exc_class, exc, tb = exc_info
            if isinstance(exc, IOError) and exc.args[0] == 32:
                # Skip 'IOError: [Errno 32] Broken pipe'.
                skip_it = True
            if not skip_it:
                tb_path, tb_lineno, tb_func = traceback.extract_tb(tb)[-1][:3]
                if TOPLEVEL_EXC_VERBOSITY == "short":
                    log.error("%s (%s:%s in %s)", exc_info[1], tb_path,
                              tb_lineno, tb_func)
                else: # TOPLEVEL_EXC_VERBOSITY == "quiet"
                    log.error(exc_info[1])
        else:  # string exception
            log.error(exc_info[0])
        if not skip_it:
            if TOPLEVEL_EXC_VERBOSITY == "full" \
               or log.isEnabledFor(logging.DEBUG):
                print
                traceback.print_exception(*exc_info)
            sys.exit(1)
    else:
        sys.exit(retval)

if __name__ == "__main__":
    main(sys.argv)



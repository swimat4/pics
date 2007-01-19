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
from pprint import pprint
import webbrowser

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
API_KEY = open(join(dirname(__file__), "API_KEY")).read().strip()
SECRET = open(join(dirname(__file__), "SECRET")).read().strip()

class PicsError(Exception):
    pass

class FSError(PicsError):
    """An error in the file system wrapper."""



#---- internal support stuff

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
    ("flickr", re.compile("^http://(www\.)?flickr\.com/photos/(?P<user>.*?)/?$")),
]
def _parse_source_url(url):
    """Parse a repository source URL (as passed to 'pics setup').

        >>> _parse_source_url("flickr://someuser/")
        ('flickr', 'someuser')
        >>> _parse_source_url("http://www.flickr.com/photos/someuser")
        ('flickr', 'trento')
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
    API_VERSION = (0,1,0)

    def __init__(self, base_dir):
        self.base_dir = normpath(base_dir)
        self.fs = _FileSystem(log.debug)

    def setup(self):
        log.info("create `%s'", self.base_dir)
        self.fs.mkdir(self.base_dir, parents=True)
        
        base_cntl_dir = join(self.base_dir, ".pics")
        self.fs.mkdir(base_cntl_dir) #TODO: mode="hidden" for win32
        ver_str = '.'.join(map(str, self.API_VERSION))
        open(join(base_cntl_dir, "version"), 'w').write(ver_str)
        
        log.info("create `%s/favs'", self.base_dir)
        self.fs.mkdir(join(self.base_dir, "favs"))
        self.fs.mkdir(join(self.base_dir, "favs", ".pics")) #TODO: hidden

    def upgrade(self):
        raise NotImplementedError("working copy upgrade not yet implemented")

    def check_version(self):
        wc_ver_str = open(join(self.base_dir, ".pics", "version"), 'r').read()
        wc_ver_tuple = tuple(map(int, ver_str.split('.')))
        if wc_ver_tuple != self.API_VERSION:
            raise PicsError("out of date working copy (v%s < v%s): you must "
                            "first upgrade", wc_ver_tuple,
                            '.'.join(map(str(self.API_VERSION))))

    def initialize(self):
        self.check_version()
        XXX #initialize


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

    def do_setup(self, subcmd, opts, url, path):
        """Setup a working copy of photos.

        ${cmd_usage}
        ${cmd_option_list}

        Setup a pics working area. For example, the following will setup
        '~/pics' to working with user trento's flickr photos.

            pics setup flickr://trento/ ~/pics

        The URL is either "flickr://<username-or-id>/" or the standard
        flickr user photos URL, e.g.
        "http://www.flickr.com/photos/trento/". Basically the only
        useful piece of information here is your flickr username or id,
        but I'm leaving this open for potential integration with other
        photo sites.

        Note that 'pics setup' doesn't download any photos; just
        prepares the area to do so (typically via 'pics up').
        """
        repo_type, repo_user = _parse_source_url(url)
        if repo_type != "flickr":
            raise PicsError("unsupported pics repository type: %r" % repo_type)
        base_pics = join(path, ".pics")
        if exists(path) and not exists(base_pics):
            raise PicsError("`%s' exists but doesn't look like a pics "
                            "working copy" % path)
        
        wc = WorkingCopy(path)
        if exists(path):
            return wc.upgrade()
        else:
            return wc.setup()

    @cmdln.alias("ls")
    def do_list(self, subcmd, opts, *target):
        """List photos entries in the repository.

        ${cmd_usage}
        ${cmd_option_list}
        """
        wc = self._wc_from_cwd()
        #START HERE:
        # - find base dir and create WorkingCopy
        # - call WorkingCopy.list_*() as appropriate: .list_favs(), ...
        raise NotImplementedError("list")

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
                log.error("%s (%s:%s in %s)", exc_info[1], tb_path,
                          tb_lineno, tb_func)
        else:  # string exception
            log.error(exc_info[0])
        if not skip_it:
            if True or log.isEnabledFor(logging.DEBUG):
                print
                traceback.print_exception(*exc_info)
            sys.exit(1)
    else:
        sys.exit(retval)

if __name__ == "__main__":
    main(sys.argv)



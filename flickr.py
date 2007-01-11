#!/usr/bin/env python
# Copyright (c) 2007 Trent Mick
# License: MIT License
# Author:
#   Trent Mick (trentm@gmail.com)

r"""flickr -- like svn for photos, flickr.com is the repository"""

__revision__ = "$Id$"
__version_info__ = (0, 1, 0)
__version__ = '.'.join(map(str, __version_info__))

import os
from os.path import isfile, isdir, exists, dirname, abspath, splitext, join
import sys
import stat
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

log = logging.getLogger("flickr")
API_KEY = open(join(dirname(__file__), "API_KEY")).read().strip()
SECRET = open(join(dirname(__file__), "SECRET")).read().strip()



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



#---- shell

class Shell(cmdln.Cmdln):
    r"""flickr -- like svn for photos, flickr.com is the repository

    usage:
        ${name} SUBCOMMAND [ARGS...]
        ${name} help SUBCOMMAND

    ${option_list}
    ${command_list}
    ${help_list}
    """
    name = "flickr"
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
            print "%10s: %s" % (a['id'], a['title'].encode("ascii", "replace"))

    def do_go(self, subcmd):
        """Open flickr.com

        ${cmd_usage}
        ${cmd_option_list}
        """
        webbrowser.open("http://flickr.com/")

    def do_add(self, subcmd, opts, *path):
        """Put files and dirs under flickr control.

        ${cmd_usage}
        ${cmd_option_list}

        TODO: --tag,-t to add a tag
        """
        raise NotImplementedError("add")

    @cmdln.alias("co")
    def do_checkout(self, subcmd, opts, url, path):
        """Checkout a working copy of photos.

        ${cmd_usage}
        ${cmd_option_list}

        TODO: By default this shouldn't checkout *everything*. Perhaps
            this is about the URL.
                pics co flickr://trento/ ~/pics
                pics co flickr://trento/2006/08 ~/pics
                   `-- ~/pics/2006-08/...
                pics co flickr://trento/favorites/ <need path here?>
            Maybe not checkout, but setup:
                pics setup flickr://trento/ ~/pics
          
        
        TODO: option to d/l the full files (otherwise do reasonable size)
              Option is about the "size".
        """
        raise NotImplementedError("checkout")





#---- mainline

_v_count = 0
def _set_verbosity(option, opt_str, value, parser):
    global _v_count, log
    _v_count += 1
    if _v_count == 1:
        log.setLevel(logging.INFO)
    elif _v_count > 1:
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
        help="More verbose output. Repeat for more and more output.")
    optparser.add_option("-L", "--log-level",
        action="callback", callback=_set_logger_level, nargs=1, type="str",
        help="Specify a logger level via '<logname>:<levelname>'.")
    return shell.main(sys.argv, optparser=optparser)


def main(argv=sys.argv):
    _setup_logging() # defined in recipe:pretty_logging
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



#!/usr/bin/env python

"""Work with photos in a pseudo-SVN-like way."""

# The primary usage of this module is for command-line usage. The "pics"
# tool calls "main()" here.
#
#     from picslib import runner
#     runner.main()
# 
# There is also a "pics()" function here for less command-line oriented
# running (it doesn't setup logging, it doesn't call sys.exit).
# 
# Notes on logging levels and verbosity
# -------------------------------------
# 
# How loud `pics` is depends on these options (the last one given wins):
#     (none given)        default verbosity (logging.INFO level)
#     -v, --verbose       more verbose (logging.INFO-1 level)
#     -q, --quiet         less verbose (logging.WARN level)
#     -D, --debug         debugging output (logging.DEBUG level)
# 
# Full tracebacks on errors are shown on the command-line with -d|--debug.

import os
from os.path import dirname, join, expanduser
import sys
import logging
import optparse
from pprint import pprint
import traceback

import picslib
from picslib.errors import PicsError
from picslib.shell import PicsShell



log = logging.getLogger("pics")



#---- main module functionality

def setup_logging():
    hdlr = logging.StreamHandler()
    defaultFmt = "%(name)s: %(levelname)s: %(message)s"
    infoFmt = "%(message)s"
    fmtFromLevel={logging.INFO: "%(name)s: %(message)s"}
    fmtr = _PerLevelFormatter(defaultFmt, fmtFromLevel=fmtFromLevel)
    hdlr.setFormatter(fmtr)
    logging.root.addHandler(hdlr)


def main(argv=None):
    if argv is None:
        argv = sys.argv
    if not logging.root.handlers:
        setup_logging()

    try:
        shell = PicsShell()
        retval = shell.main(argv)
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
                exc_str = str(exc_info[1])
                sep = ('\n' in exc_str and '\n' or ' ')
                where_str = ""
                tb_path, tb_lineno, tb_func = traceback.extract_tb(tb)[-1][:3]
                in_str = (tb_func != "<module>"
                          and " in %s" % tb_func
                          or "")
                where_str = "%s(%s#%s%s)" % (sep, tb_path, tb_lineno, in_str)
                log.error("%s%s", exc_str, where_str)
        else:  # string exception
            log.error(exc_info[0])
        if not skip_it:
            if log.isEnabledFor(logging.DEBUG):
                print
                traceback.print_exception(*exc_info)
            sys.exit(1)
    else:
        sys.exit(retval)



#---- internal support stuff

class _NoReflowFormatter(optparse.IndentedHelpFormatter):
    """An optparse formatter that does NOT reflow the description."""
    def format_description(self, description):
        return description or ""

# Recipe: pretty_logging (0.1+)
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



#---- mainline

if __name__ == "__main__":
    main(sys.argv)


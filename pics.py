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
                     normpath, expanduser, basename)
import sys
import stat
import re
import logging
import optparse
import traceback
import time
from pprint import pprint
from glob import glob
import webbrowser
from datetime import datetime, date
import cPickle as pickle
import urllib

_contrib_dir = join(dirname(abspath(__file__)), "contrib")
sys.path.insert(0, join(_contrib_dir, "cmdln"))
try:
    import cmdln
finally:
    del sys.path[0]
del _contrib_dir

import flickrapi



#---- exceptions and globals

log = logging.getLogger("pics")
TOPLEVEL_EXC_VERBOSITY = "full" # quiet | short | full

API_KEY = "4ed455430ba54a0e13327f3267ab09c2"
SECRET = "cdf8f56d8d7b73c7"

class PicsError(Exception):
    pass

class FSError(PicsError):
    """An error in the file system wrapper."""



#---- internal support stuff

def _date_N_months_ago(N):
    """Return a date of the first of the month up to N months ago (rounded
    down).
    """
    #TODO: update this to use now.replace(month=<new-month>)
    now = datetime.utcnow()
    if now.month < N:
        m = (now.month-1)   # 0-based
        m -= N-1            # N months ago (rounded down)
        m %= 12             # normalize
        m += 1              # 1-based
        return date(now.year-1, m, 1)
    else:
        return date(now.year, now.month - (N-1), 1)
    
def _timestamp_from_datetime(dt):
    return time.mktime(dt.timetuple())


# Recipe: paths_from_path_patterns (0.3.5+) in /Users/trentm/tm/recipes/cookbook
def _should_include_path(path, includes, excludes):
    """Return True iff the given path should be included."""
    from os.path import basename
    from fnmatch import fnmatch

    base = basename(path)
    if includes:
        for include in includes:
            if fnmatch(base, include):
                try:
                    log.debug("include `%s' (matches `%s')", path, include)
                except (NameError, AttributeError):
                    pass
                break
        else:
            log.debug("exclude `%s' (matches no includes)", path)
            return False
    for exclude in excludes:
        if fnmatch(base, exclude):
            try:
                log.debug("exclude `%s' (matches `%s')", path, exclude)
            except (NameError, AttributeError):
                pass
            return False
    return True

_NOT_SPECIFIED = ("NOT", "SPECIFIED")
def _paths_from_path_patterns(path_patterns, files=True, dirs="never",
                              recursive=True, includes=[], excludes=[],
                              on_error=_NOT_SPECIFIED):
    """_paths_from_path_patterns([<path-patterns>, ...]) -> file paths

    Generate a list of paths (files and/or dirs) represented by the given path
    patterns.

        "path_patterns" is a list of paths optionally using the '*', '?' and
            '[seq]' glob patterns.
        "files" is boolean (default True) indicating if file paths
            should be yielded
        "dirs" is string indicating under what conditions dirs are
            yielded. It must be one of:
              never             (default) never yield dirs
              always            yield all dirs matching given patterns
              if-not-recursive  only yield dirs for invocations when
                                recursive=False
            See use cases below for more details.
        "recursive" is boolean (default True) indicating if paths should
            be recursively yielded under given dirs.
        "includes" is a list of file patterns to include in recursive
            searches.
        "excludes" is a list of file and dir patterns to exclude.
            (Note: This is slightly different than GNU grep's --exclude
            option which only excludes *files*.  I.e. you cannot exclude
            a ".svn" dir.)
        "on_error" is an error callback called when a given path pattern
            matches nothing:
                on_error(PATH_PATTERN)
            If not specified, the default is look for a "log" global and
            call:
                log.error("`%s': No such file or directory")
            Specify None to do nothing.
            TODO: doc "log", "ignore", "yield"

    Typically this is useful for a command-line tool that takes a list
    of paths as arguments. (For Unix-heads: the shell on Windows does
    NOT expand glob chars, that is left to the app.)

    Use case #1: like `grep -r`
      {files=True, dirs='never', recursive=(if '-r' in opts)}
        script FILE     # yield FILE, else call on_error(FILE)
        script DIR      # yield nothing
        script PATH*    # yield all files matching PATH*; if none,
                        # call on_error(PATH*) callback
        script -r DIR   # yield files (not dirs) recursively under DIR
        script -r PATH* # yield files matching PATH* and files recursively
                        # under dirs matching PATH*; if none, call
                        # on_error(PATH*) callback

    Use case #2: like `file -r` (if it had a recursive option)
      {files=True, dirs='if-not-recursive', recursive=(if '-r' in opts)}
        script FILE     # yield FILE, else call on_error(FILE)
        script DIR      # yield DIR, else call on_error(DIR)
        script PATH*    # yield all files and dirs matching PATH*; if none,
                        # call on_error(PATH*) callback
        script -r DIR   # yield files (not dirs) recursively under DIR
        script -r PATH* # yield files matching PATH* and files recursively
                        # under dirs matching PATH*; if none, call
                        # on_error(PATH*) callback

    Use case #3: kind of like `find .`
      {files=True, dirs='always', recursive=(if '-r' in opts)}
        script FILE     # yield FILE, else call on_error(FILE)
        script DIR      # yield DIR, else call on_error(DIR)
        script PATH*    # yield all files and dirs matching PATH*; if none,
                        # call on_error(PATH*) callback
        script -r DIR   # yield files and dirs recursively under DIR
                        # (including DIR)
        script -r PATH* # yield files and dirs matching PATH* and recursively
                        # under dirs; if none, call on_error(PATH*)
                        # callback
    """
    from os.path import basename, exists, isdir, join
    from glob import glob

    GLOB_CHARS = '*?['

    for path_pattern in path_patterns:
        # Determine the set of paths matching this path_pattern.
        for glob_char in GLOB_CHARS:
            if glob_char in path_pattern:
                paths = glob(path_pattern)
                break
        else:
            paths = exists(path_pattern) and [path_pattern] or []
        if not paths:
            if on_error in (None, "ignore"):
                pass
            elif on_error in (_NOT_SPECIFIED, "log"):
                try:
                    log.error("`%s': No such file or directory", path_pattern)
                except (NameError, AttributeError):
                    pass
            elif on_error == "yield":
                if _should_include_path(path_pattern, includes, excludes):
                    yield path_pattern
            else:
                on_error(path_pattern)

        for path in paths:
            if isdir(path):
                # 'includes' SHOULD affect whether a dir is yielded.
                if (dirs == "always"
                    or (dirs == "if-not-recursive" and not recursive)
                   ) and _should_include_path(path, includes, excludes):
                    yield path

                # However, if recursive, 'includes' should NOT affect
                # whether a dir is recursed into. Otherwise you could
                # not:
                #   script -r --include="*.py" DIR
                if recursive and _should_include_path(path, [], excludes):
                    for dirpath, dirnames, filenames in os.walk(path):
                        dir_indeces_to_remove = []
                        for i, dirname in enumerate(dirnames):
                            d = join(dirpath, dirname)
                            if dirs == "always" \
                               and _should_include_path(d, includes, excludes):
                                yield d
                            if not _should_include_path(d, [], excludes):
                                dir_indeces_to_remove.append(i)
                        for i in reversed(dir_indeces_to_remove):
                            del dirnames[i]
                        if files:
                            for filename in sorted(filenames):
                                f = join(dirpath, filename)
                                if _should_include_path(f, includes, excludes):
                                    yield f

            elif files and _should_include_path(path, includes, excludes):
                yield path


# Recipe: text_escape (0.1) in /Users/trentm/tm/recipes/cookbook
def _escaped_text_from_text(text, escapes="eol"):
    r"""Return escaped version of text.

        "escapes" is either a mapping of chars in the source text to
            replacement text for each such char or one of a set of
            strings identifying a particular escape style:
                eol
                    replace EOL chars with '\r' and '\n', maintain the actual
                    EOLs though too
                whitespace
                    replace EOL chars as above, tabs with '\t' and spaces
                    with periods ('.')
                eol-one-line
                    replace EOL chars with '\r' and '\n'
                whitespace-one-line
                    replace EOL chars as above, tabs with '\t' and spaces
                    with periods ('.')
    """
    #TODO:
    # - Add 'c-string' style.
    # - Add _escaped_html_from_text() with a similar call sig.
    import re
    
    if isinstance(escapes, basestring):
        if escapes == "eol":
            escapes = {'\r\n': "\\r\\n\r\n", '\n': "\\n\n", '\r': "\\r\r"}
        elif escapes == "whitespace":
            escapes = {'\r\n': "\\r\\n\r\n", '\n': "\\n\n", '\r': "\\r\r",
                       '\t': "\\t", ' ': "."}
        elif escapes == "eol-one-line":
            escapes = {'\n': "\\n", '\r': "\\r"}
        elif escapes == "whitespace-one-line":
            escapes = {'\n': "\\n", '\r': "\\r", '\t': "\\t", ' ': '.'}
        else:
            raise ValueError("unknown text escape style: %r" % escapes)

    # Sort longer replacements first to allow, e.g. '\r\n' to beat '\r' and
    # '\n'.
    escapes_keys = escapes.keys()
    escapes_keys.sort(key=lambda a: len(a), reverse=True)
    def repl(match):
        val = escapes[match.group(0)]
        return val
    escaped = re.sub("(%s)" % '|'.join([re.escape(k) for k in escapes_keys]),
                     repl,
                     text)

    return escaped

def _one_line_summary_from_text(text, length=78,
        escapes={'\n':"\\n", '\r':"\\r", '\t':"\\t"}):
    r"""Summarize the given text with one line of the given length.
    
        "text" is the text to summarize
        "length" (default 78) is the max length for the summary
        "escapes" is a mapping of chars in the source text to
            replacement text for each such char. By default '\r', '\n'
            and '\t' are escaped with their '\'-escaped repr.
    """
    if len(text) > length:
        head = text[:length-3]
    else:
        head = text
    escaped = _escaped_text_from_text(head, escapes)
    if len(text) > length:
        summary = escaped[:length-3] + "..."
    else:
        summary = escaped
    return summary


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


# Recipe: pretty_logging (0.1+) in C:\trentm\tm\recipes\cookbook
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
    #infoFmt = "%(name)s: %(message)s"
    infoFmt = "%(message)s"
    fmtr = _PerLevelFormatter(fmt=defaultFmt,
                              fmtFromLevel={logging.INFO: infoFmt})
    hdlr.setFormatter(fmtr)
    logging.root.addHandler(hdlr)


_g_source_url_pats = [
    ("flickr", re.compile("^flickr://(?P<user>.*?)/?$")),
    #("flickr", re.compile("^http://(www\.)?flickr\.com/photos/(?P<user>.*?)/?$")),
]
def _parse_source_url(url):
    """Parse a repository source URL (as passed to 'pics checkout').

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
        int mode.
        
        TODO: support things like "+w", "u-x", etc.
        """
        if mode_arg is None:
            return default
        elif isinstance(mode_arg, int):
            return mode_arg
        else:
            raise FSError("unsupported mode arg: %r" % mode_arg) 

    def _set_win32_file_hidden_attr(self, path):
        try:
            import win32api
            from win32con import FILE_ATTRIBUTE_HIDDEN
        except ImportError, ex:
            import subprocess
            subprocess.call(["attrib", "+H", path])
        else:
            win32api.SetFileAttributes(path, FILE_ATTRIBUTE_HIDDEN)

    def mkdir(self, dir, mode=None, parents=False, hidden=False, log=None):
        """Make the given directory.
        
            ...
            "hidden" is an optional boolean to set the hidden attribute
                on the created directory on Windows. It is ignore on other
                platforms.
        """
        mode = self._mode_from_mode_arg(mode, 0777)
        self.log(log, "mkdir%s%s `%s'%s", (parents and " -p" or ""),
                 (mode is not None and " -m "+oct(mode) or ""), dir,
                 (sys.platform == "win32" and hidden and " (hidden)" or ""))
        made_it = True
        if parents:
            if exists(dir):
                made_it = False
            else:
                os.makedirs(dir, mode)
        else:
            os.mkdir(dir, mode)
        if sys.platform == "win32" and hidden and made_it:
            self._set_win32_file_hidden_attr(dir)
        

class WorkingCopy(object):
    """
    TODO: doc usage and attrs
        version
        version_info
        last_update_start
        last_update_end
        ...
    """
    API_VERSION_INFO = (0,2,0)

    def __init__(self, base_dir):
        self.base_dir = normpath(base_dir)
        self.fs = _FileSystem(log.debug)
        self._cache = {}

    @property
    def type(self):
        if "type" not in self._cache:
            type_path = join(self.base_dir, ".pics", "type")
            self._cache["type"] = open(type_path, 'r').read().strip()
        return self._cache["type"]

    @property
    def user(self):
        if "user" not in self._cache:
            user_path = join(self.base_dir, ".pics", "user")
            self._cache["user"] = open(user_path, 'r').read().strip()
        return self._cache["user"]

    @property
    def version(self):
        if "version" not in self._cache:
            version_path = join(self.base_dir, ".pics", "version")
            self._cache["version"] = open(version_path, 'r').read().strip()
        return self._cache["version"]

    @property
    def version_info(self):
        return tuple(map(int, self.version.split('.')))

    def __repr__(self):
        return "<WorkingCopy v%s>" % self.version

    #HACK: TODO: update this to get one properly and to store auth_token
    #            in .pics/auth_token. See token property below.
    @property
    def auth_token(self):
        if self._auth_token_cache is None:
            #auth_token_path = join(self.base_dir, ".pics", "auth_token")
            auth_token_path = expanduser(normpath("~/.flickr/AUTH_TOKEN"))
            self._auth_token_cache = open(auth_token_path, 'r').read().strip()
        return self._auth_token_cache
    _auth_token_cache = None

    #@property
    #def token(self):
    #    if self._token_cache is None:
    #        #TODO: Getting the token/frob is hacky. C.f.
    #        #      http://flickr.com/services/api/auth.howto.mobile.html
    #        self._token_cache = self.api.getToken(
    #            #browser="/Applications/Safari.app/Contents/MacOS/Safari"
    #            browser="/Applications/Firefox.app/Contents/MacOS/firefox"
    #        )
    #    return self._token_cache
    #_token_cache = None 

    @property
    def api(self):
        if self._api_cache is None:
            self._api_cache = flickrapi.FlickrAPI(API_KEY, SECRET,
                                                  self.auth_token)
        return self._api_cache
    _api_cache = None 

    _last_update_start_cache = None
    def _get_last_update_start(self):
        if self._last_update_start_cache is None:
            path = join(self.base_dir, ".pics", "last-update-start")
            if exists(path):
                self._last_update_start_cache = pickle.load(open(path, 'rb'))
            else:
                self._last_update_start_cache = None
        return self._last_update_start_cache
    def _set_last_update_start(self, value):
        self._last_update_start_cache = value
    last_update_start = property(_get_last_update_start,
                                 _set_last_update_start)

    _last_update_end_cache = None
    def _get_last_update_end(self):
        if self._last_update_end_cache is None:
            path = join(self.base_dir, ".pics", "last-update-end")
            if exists(path):
                self._last_update_end_cache = pickle.load(open(path, 'rb'))
            else:
                self._last_update_end_cache = None
        return self._last_update_end_cache
    def _set_last_update_end(self, value):
        self._last_update_end_cache = value
    last_update_end = property(_get_last_update_end,
                               _set_last_update_end)

    def _note_last_update(self, last_update):
        if self.last_update_start is None:
            self.last_update_start = last_update
            self.last_update_end = last_update
        elif last_update < self.last_update_start:
            self.last_update_start = last_update
        elif last_update > self.last_update_end:
            self.last_update_end = last_update

    def _checkpoint(self):
        """Save the current lastupdate dates."""
        if self._last_update_start_cache is not None:
            path = join(self.base_dir, ".pics", "last-update-start")
            fout = open(path, 'wb')
            try:
                pickle.dump(self._last_update_start_cache, fout)
            finally:
                fout.close()
        if self._last_update_end_cache is not None:
            path = join(self.base_dir, ".pics", "last-update-end")
            fout = open(path, 'wb')
            try:
                pickle.dump(self._last_update_end_cache, fout)
            finally:
                fout.close()

    def _add_photo(self, photo, dry_run=False):
        """Add the given photo to the working copy."""
        #pprint(photo)
        if not dry_run:
            date_dir = join(self.base_dir, photo["datetaken"].strftime("%Y-%m"))
            pics_dir = join(date_dir, ".pics")
            if not exists(date_dir):
                self.fs.mkdir(date_dir)
            if not exists(pics_dir):
                self.fs.mkdir(pics_dir, hidden=True)

        log.info("A  %s  [%s]", photo["id"],
                 _one_line_summary_from_text(photo["title"], 40))
        if not dry_run:
            small_path = join(date_dir, "%(id)s.small.jpg" % photo)
            small_url = "http://farm%(farm)s.static.flickr.com/%(server)s/%(id)s_%(secret)s_m.jpg" % photo
            #TODO: add a reporthook for progressbar (unless too quick to bother)
            #TODO: handle ContentTooShortError (py2.5)
            filename, headers = urllib.urlretrieve(small_url, small_path)
            mtime = _timestamp_from_datetime(photo["lastupdate"])
            os.utime(small_path, (mtime, mtime))
            self._save_photo_data(date_dir, photo["id"], photo)
            self._note_last_update(photo["lastupdate"])

    def _update_photo(self, photo, dry_run=False):
        """Update the given photo in the working copy."""
        #pprint(photo)
        if not dry_run:
            date_dir = join(self.base_dir, photo["datetaken"].strftime("%Y-%m"))
            pics_dir = join(date_dir, ".pics")
            if not exists(date_dir):
                self.fs.mkdir(date_dir)
            if not exists(pics_dir):
                self.fs.mkdir(pics_dir, hidden=True)

        log.info("U  %s  [%s]", photo["id"],
                 _one_line_summary_from_text(photo["title"], 40))
        if not dry_run:
            ##TODO:XXX Differentiate photo vs. meta-date update.
            #small_path = join(date_dir, "%(id)s.small.jpg" % photo)
            #small_url = "http://farm%(farm)s.static.flickr.com/%(server)s/%(id)s_%(secret)s_m.jpg" % photo
            #filename, headers = urllib.urlretrieve(small_url, small_path)
            #mtime = _timestamp_from_datetime(photo["lastupdate"])
            #os.utime(small_path, (mtime, mtime))
            self._save_photo_data(date_dir, photo["id"], photo)
            self._note_last_update(photo["lastupdate"])

    def create(self, type, user):
        assert type == "flickr", "unknown pics repo type: %r" % type

        # Create base structure.
        if not exists(self.base_dir):
            self.fs.mkdir(self.base_dir, parents=True)
        d = join(self.base_dir, ".pics")
        if not exists(d):
            self.fs.mkdir(d, hidden=True)
        ver_str = '.'.join(map(str, self.API_VERSION_INFO))
        open(join(d, "version"), 'w').write(ver_str+'\n')
        open(join(d, "type"), 'w').write(type+'\n')
        open(join(d, "user"), 'w').write(user+'\n')

        # Get the latest N photos up to M months ago (rounded down) --
        # whichever is less.
        N = 3 #TODO: 100
        M = 3
        recents = self.api.photos_recentlyUpdated(
                    min_date=_date_N_months_ago(M),
                    extras=["date_taken", "owner_name", "last_update",
                            "icon_server", "original_format",
                            "geo", "tags", "machine_tags"],
                    per_page=N, page=1)
        for i, recent in enumerate(recents):
            self._add_photo(recent)
            if i % 10 == 0:
                self._checkpoint()
        if i % 10 != 0:
            self._checkpoint()
        log.info("Checked out latest updated %d photos (%s - %s).",
                 i+1, self.last_update_start.strftime("%b %d, %Y"),
                 self.last_update_end.strftime("%b %d, %Y"))

        #TODO: create favs/...
        #      Just start with the most recent N favs.
        #log.debug("create `%s/favs'", self.base_dir)
        #self.fs.mkdir(join(self.base_dir, "favs"))
        #self.fs.mkdir(join(self.base_dir, "favs", ".pics"), hidden=True)

    def check_version(self):
        if self.version_info != self.API_VERSION_INFO:
            raise PicsError("out of date working copy (v%s < v%s): you must "
                            "first upgrade", self.version_info,
                            '.'.join(map(str(self.API_VERSION_INFO))))

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

    def _save_photo_data(self, dir, id, data):
        data_path = join(dir, ".pics", id+".data")
        log.debug("save photo data: `%s'", data_path)
        fdata = open(data_path, 'wb')
        try:
            pickle.dump(data, fdata, 2) 
        finally:
            fdata.close()

    def _get_photo_data(self, dir, id):
        #TODO: add caching of photo data (co-ordinate with _save_photo_data)
        data_path = join(dir, ".pics", id+".data")
        if exists(data_path):
            log.debug("load photo data: `%s'", data_path)
            fdata = open(data_path, 'rb')
            try:
                return pickle.load(fdata) 
            finally:
                fdata.close()
        else:
            return None

    def _get_photo_local_changes(self, dir, id):
        changes_path = join(dir, ".pics", id+".changes")
        if exists(changes_path):
            log.debug("load photo changes: `%s'", changes_path)
            fchanges = open(changes_path, 'rb')
            try:
                return pickle.load(fchanges) 
            finally:
                fchanges.close()
        else:
            return None

    def _local_photo_dirs_and_ids_from_target(self, target):
        """Yield the identified photos from the given target.
        
        Yields 2-tuples: <pics-wc-dir>, <photo-id>
        """
        if isdir(target):
            if not exists(join(target, ".pics")):
                raise PicsError("`%s' is not a pics working copy dir" % path)
            for f in glob(join(target, ".pics", "*.data")):
                yield target, splitext(basename(f))[0]
        else:
            id = basename(target).split('.', 1)[0]
            data_path = join(dirname(target), ".pics", id+".data")
            if isfile(data_path):
                yield dirname(target), id

    def _photo_data_from_local_path(self, path):
        """Yield photo data for the given list path.
        
        If the given path does not identify a photo then the following
        is returned:
            {"id": path}
        """
        log.debug("list local path '%s'", path)
        found_at_least_one = False
        for dir, id in self._local_photo_dirs_and_ids_from_target(path):
            found_at_least_one = True
            yield self._get_photo_data(dir, id)        
        if not found_at_least_one:
            # This is how we say the equivalent of:
            #   $ ls bogus
            #   ls: bogus: No such file or directory
            yield {"id": path}

    def _photo_data_from_paths(self, paths):
        for path in paths:
            if path.startswith("flickr://"):
                for d in self._photo_data_from_url(path):
                    yield d
            else:
                for p in _paths_from_path_patterns([path],
                            dirs="if-not-recursive",
                            recursive=False,
                            on_error="yield"):
                    for d in self._photo_data_from_local_path(p):
                        yield d

    def open(self, target):
        """Open the given photo or dir target on flickr.com."""
        if isdir(target):
            if not exists(join(target, ".pics")):
                raise PicsError("`%s' is not a pics working copy dir" % path)
            dir = basename(abspath(target))
            if not re.match(r"\d{4}-\d{2}", dir):
                raise PicsError("`%s' isn't a pics date dir: can't yet "
                                "handle that" % target)
            year, month = dir.split("-")
            url = "http://www.flickr.com/photos/%s/archives/date-posted/%s/%s/calendar/"\
                  % (self.user, year, month)
        else:
            dirs_and_ids = [
                di
                for p in _paths_from_path_patterns(
                            [target], dirs="if-not-recursive",
                            recursive=False, on_error="yield")
                for di in self._local_photo_dirs_and_ids_from_target(p)
            ]
            if not dirs_and_ids:
                raise PicsError("`%s': no such photo or dir" % target)
            if len(dirs_and_ids) > 1:
                raise PicsError("`%s' ambiguous: identifies %d photos"
                                % (target, len(dirs_and_ids)))
            photo_data = self._get_photo_data(*dirs_and_ids[0])
            url = "http://www.flickr.com/photos/%s/%s/"\
                  % (self.user, photo_data["id"])
        webbrowser.open(url)

    def list(self, paths, format="short", tags=False):
        for photo_data in self._photo_data_from_paths(paths):
            log.debug("list %r", photo_data)

            if photo_data.keys() == ["id"]:
                log.error("%s: no such photo or directory", photo_data["id"])
            elif format == "short":
                print photo_data["id"]
            elif format == "long":
                if tags:
                    template = "%(mode)s %(numtags)2s %(ownername)s "\
                               "%(lastupdate)s  %(id)s  %(title)s [%(tags)s]"
                else:
                    template = "%(mode)s %(numtags)2s %(ownername)s "\
                               "%(lastupdate)s  %(id)s  %(title)s"
                list_data = {
                    "mode": self._mode_str_from_photo_dict(photo_data),
                    "lastupdate": photo_data["lastupdate"].strftime("%Y-%m-%d %H:%M"),
                    "id": photo_data["id"],
                    "ownername": photo_data["ownername"],
                    "numtags": len(photo_data["tags"]) + len(photo_data["machine_tags"]),
                    "tags": ', '.join(photo_data["tags"] + photo_data["machine_tags"]),
                    "title": photo_data["title"],
                }
                print template % list_data
            elif format == "dict":
                pprint(photo_data)
            else:
                raise PicsError("unknown listing format: '%r" % format)

    def update(self, dry_run=False):
        #TODO: when support local edits, need to check for conflicts
        #      and refuse to update if hit one
        recents = self.api.photos_recentlyUpdated(
                    min_date=self.last_update_end,
                    extras=["date_taken", "owner_name", "last_update",
                            "icon_server", "original_format",
                            "geo", "tags", "machine_tags"])
        curr_subdir = _relpath(os.getcwd(), self.base_dir)
        for recent in recents:
            # Determine if this is an add, update, conflict, merge or delete.
            #TODO: test a delete (does recent updates show that?)
            #TODO: test a conflict
            #TODO: what about photo *content* changes?
            #TODO: bother to support merge?
            #TODO: what about photo notes?
            subdir = recent["datetaken"].strftime("%Y-%m")
            if subdir == curr_subdir:
                dir = ""
            else:
                dir = join(self.base_dir, photo_subdir)
            id = recent["id"]
            existing_data = self._get_photo_data(dir, id)
            if existing_data is None:
                action = "A" # adding a new photo
            else:
                local_changes = self._get_photo_local_changes(dir, id)
                if local_changes:
                    action = "C" # conflict (don't yet support merging)
                else:
                    action = "U"
            
            if action == "A":
                self._add_photo(recent, dry_run=dry_run)
            elif action == "U":
                self._update_photo(recent, dry_run=dry_run)
            elif action == "C":
                log.info("%s  %s  [%s]", action, id,
                    _one_line_summary_from_text(recent["title"], 40))
                log.error("Aborting update at conflict.")
                break
            self._checkpoint()
        else:
            log.info("Up to date (latest update: %s UTC).",
                     self.last_update_end.strftime("%b %d, %Y"))

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

    def _find_base_dir(self, path=None):
        """Determine the working copy base dir from the given path.
        
        If "path" isn't specified, the CWD is used. Returns None if no
        pics working copy base dir could be found.
        """
        if path is None:
            dir = os.curdir
        elif isdir(path):
            dir = path
        else:
            dir = dirname(path) or os.curdir
        if exists(join(dir, ".pics", "version")):
            return dir
        # So far the pics structure only goes one level deep.
        if exists(join(dir, os.pardir, ".pics", "version")):
            return normpath(join(dir, os.pardir))
        return None

    #DEPRECATED: use _wcs_from_paths()
    def _get_wc(self):
        if not isdir(".pics"):
            raise PicsError("this is not a pics working copy: no `.pics' "
                            "directory")
        base_dir = self._find_base_dir()
        if base_dir is None:
            raise PicsError("couldn't determine working copy base dir "
                            "from CWD")
        return WorkingCopy(base_dir)

    def _wcs_from_paths(self, paths):
        """For each given target path yield:
            (<working-copy>, path)
        If a path isn't in a pics working copy, then (None, path) is yielded.
        """
        wc_from_base_dir = {}
        for path in paths:
            base_dir = self._find_base_dir(path)
            if base_dir is None:
                yield None, path
            else:
                if base_dir not in wc_from_base_dir:
                    wc_from_base_dir[base_dir] = WorkingCopy(base_dir)
                yield wc_from_base_dir[base_dir], path

    @cmdln.alias("ls")
    @cmdln.option("-s", dest="format", default="long",
                  action="store_const", const="short",
                  help="use a short listing format")
    @cmdln.option("--format", default="long",
                  help="specify output format: short, long (default), dict")
    @cmdln.option("-t", "--tags", action="store_true", default=False,
                  help="list tags as well")
    def do_list(self, subcmd, opts, *target):
        """${cmd_name}: List photo entries. 

        ${cmd_usage}
        ${cmd_option_list}
        """
        #TODO: update this so can call from outside the wc dir.
        #      I.e. [/tmp]$ pics ls ~/pics/2007-01
        targets = target or [os.curdir]
        wc = self._get_wc()
        wc.list(targets, format=opts.format, tags=opts.tags)

    def do_open(self, subcmd, opts, target):
        """Open given photo or dir on flickr.com.

        ${cmd_usage}
        ${cmd_option_list}
        """
        wc = self._get_wc()
        wc.open(target)

    def do_add(self, subcmd, opts, *path):
        """${cmd_name}: Put files and dirs under pics control.

        ${cmd_usage}
        ${cmd_option_list}

        TODO: --tag,-t to add a tag
        """
        raise NotImplementedError("add")

    #TODO: some command(s) for editing pic data
    #   - allow batch changes
    #   - either 'edit' or a set of 'prop*'-like cmds

    @cmdln.alias("up")
    @cmdln.option("-n", "--dry-run", action="store_true", default=False,
                  help="do a dry-run; just show updates without making changes")
    def do_update(self, subcmd, opts, *path):
        """${cmd_name}: Update working copy with recent changes on flickr.

        This can be called on any path in a pics working copy and the *whole*
        working copy will be updated. Note: Currently this doesn't update the
        working copy with changes on flickr *before* the first checkout date.

        ${cmd_usage}
        ${cmd_option_list}
        """
        paths = path or [os.curdir]
        for wc, path in self._wcs_from_paths(paths):
            if wc is None:
                log.info("skipped '%s'", path)
            else:
                wc.update(dry_run=opts.dry_run)

    @cmdln.alias("di")
    def do_diff(self, subcmd, opts, *path):
        """${cmd_name}: Show local pic and meta-data differences.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("diff")

    @cmdln.alias("stat", "st")
    def do_status(self, subcmd, opts, *path):
        """${cmd_name}: Show the status of working files and dirs.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("status")

    @cmdln.alias("ci")
    def do_commit(self, subcmd, opts, *path):
        """${cmd_name}: Send changes from your working copy to the repository
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



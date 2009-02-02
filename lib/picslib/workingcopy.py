# Copyright (c) 2008 ActiveState Software Inc.

"""pics working copy handling"""

from __future__ import with_statement

import os
import sys
from os.path import normpath, exists, join, expanduser, dirname, isdir, \
    basename, isfile, abspath
import logging
import datetime
import re
import urllib
import cPickle as pickle
from xml.etree import ElementTree as ET
import sqlite3
from hashlib import md5
import webbrowser
from contextlib import contextmanager

from picslib.filesystem import FileSystem
from picslib import utils
from picslib.utils import xpprint
from picslib import simpleflickrapi
from picslib.errors import PicsError



log = logging.getLogger("pics")



def wcs_from_paths(paths):
    """For each given target path yield:
        (<working-copy>, path)
    If a path isn't in a pics working copy, then (None, path) is yielded.
    """
    wc_from_base_dir = {}
    for path in paths:
        base_dir = _find_wc_base_dir(path)
        if base_dir is None:
            yield None, path
        else:
            if base_dir not in wc_from_base_dir:
                wc_from_base_dir[base_dir] = WorkingCopy(base_dir)
            yield wc_from_base_dir[base_dir], path


class WorkingCopy(object):
    """API for a pics working copy directory.
    
    Usage:
        # Create a new working copy directory (used by `pics co`).
        wc = WorkingCopy.create(...)
        
        # Or, for an existing working copy.
        wc = WorkingCopy(base_dir)
    
    TODO: doc usage and attrs: version, last_update_end, ...
    """
    VERSION = "1.0.0"

    @staticmethod
    def _db_path_from_base_dir(base_dir):
        return join(base_dir, ".pics", "photos.sqlite3")

    def __init__(self, base_dir):
        self.base_dir = normpath(base_dir)
        self.fs = FileSystem(log.debug)
        self._cache = {}
        
        db_path = self._db_path_from_base_dir(self.base_dir)
        if exists(db_path):  # Otherwise `.create()` will set `self.db`.
            self.db = Database(db_path)

    @classmethod
    def create(cls, base_dir, ilk, user, base_date=None, size="original"):
        """Create a working copy and return a `WorkingCopy` instance for it.
        
        @param base_dir {str} The base directory for the working copy.
        @param ilk {str} The type of the pics repo. Currently only
            "flickr" is supported.
        @param user {str} Username of the pics repo user.
        @param base_date {datetime.date} The date (UTC) from which to
            start getting photos. If not given, then all photos for
            that user are retrieved.
        @param size {str} The name of photos sizes to download. Supported
            values are: "small", "medium" and "original". The actual size
            that the former two mean depends on the pics repository. Default
            is "original".
            TODO: specify the sizes for flickr.
        @returns {WorkingCopy} The working copy instance.
        """
        # Sanity checks.
        assert ilk == "flickr", "unknown pics repo ilk: %r" % ilk
        assert isinstance(base_date, (type(None), datetime.date))
        assert size in ("small", "medium", "original")
        if exists(base_dir):
            raise PicsError("cannot create working copy: `%s' exists" % base_dir)
        
        self = cls(base_dir)

        # Create base structure.
        #TODO: assert dirname(base_dir) exists?
        self.fs.mkdir(self.base_dir, parents=True)
        d = join(self.base_dir, ".pics")
        self.fs.mkdir(d, hidden=True)
        open(join(d, "version"), 'w').write(self.VERSION+'\n')
        
        # Main working copy database.
        db_path = self._db_path_from_base_dir(self.base_dir)
        self.db = Database(db_path)
        with self.db.connect(True) as cu:
            self.db.set_meta("ilk", ilk)
            self.db.set_meta("user", user)
            self.db.set_meta("size", size)
            if base_date:
                self.db.set_meta("base_date", base_date)

        return self

    @property
    def ilk(self):
        return self.db.get_meta("ilk")

    @property
    def user(self):
        return self.db.get_meta("user")

    @property
    def size(self):
        return self.db.get_meta("size")

    @property
    def base_date(self):
        """The base date (UTC) of this working copy. I.e. the first date
        for which photos are retrieved.
        """
        if "base_date" not in self._cache:
            s = self.db.get_meta("base_date")
            if s is None:
                self._cache["base_date"] = None
            else:
                t = datetime.datetime.strptime(s, "%Y-%m-%d")
                self._cache["base_date"] = datetime.date(t.year, t.month, t.day)
        return self._cache["base_date"]

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

    @property
    def api(self):
        if self._api_cache is None:
            self._api_cache = simpleflickrapi.SimpleFlickrAPI(
                utils.get_flickr_api_key(), utils.get_flickr_secret())
            #TODO: For now 'pics' is just read-only so this is good
            #      enough. However, eventually we'll want separate
            #      `self.read_api', `self.write_api' and
            #      `self.delete_api' or similar mechanism.
            #TODO: cache this auth token in the pics user data dir
            self._api_cache.get_auth_token("read")
        return self._api_cache
    _api_cache = None 

    #TODO:XXX: put this in db meta table
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
        if self._last_update_end_cache is None \
           or value > self._last_update_end_cache:
            self._last_update_end_cache = value
    last_update_end = property(_get_last_update_end,
                               _set_last_update_end)

    def _checkpoint(self):
        """Save the current lastupdate dates."""
        if self._last_update_end_cache is not None:
            path = join(self.base_dir, ".pics", "last-update-end")
            fout = open(path, 'wb')
            try:
                pickle.dump(self._last_update_end_cache, fout)
            finally:
                fout.close()

    def _add_photo(self, id, dry_run=False):
        """Add the given photo to the working copy."""
        # Gather necessary info.
        info = self.api.photos_getInfo(photo_id=id)[0]  # <photo> elem
        datedir = info.find("dates").get("taken")[:7]
        dir = join(self.base_dir, datedir)
        if self.size == "original":
            path = join(dir, "%s.%s" % (id, info.get("originalformat")))
        else:
            path = join(dir, "%s.%s.jpg" % (id, self.size))
        title = info.findtext("title")
        log.info("A  %s  [%s]", path,
                 utils.one_line_summary_from_text(title, 40))

        if not dry_run:
            # Create the dirs, as necessary.
            pics_dir = join(dir, ".pics")
            if not exists(dir):
                self.fs.mkdir(dir)
            if not exists(pics_dir):
                self.fs.mkdir(pics_dir, hidden=True)
        
            # Get the photo itself.
            #TODO: add a reporthook for progressbar (unless too quick to bother)
            #TODO: handle ContentTooShortError (py2.5)
            url = _flickr_photo_url_from_info(info, size=self.size)
            filename, headers = urllib.urlretrieve(url, path)
            last_update = _photo_last_update_from_info(info)
            mtime = utils.timestamp_from_datetime(last_update)
            os.utime(path, (mtime, mtime))

            # Gather and save all metadata.
            self._save_photo_data(dir, id, info)
            self.last_update_end = last_update
        return datedir

    def _info_from_photo_id(self, id):
        info = self.api.photos_getInfo(photo_id=id)[0]  # <photo> elem
        # Drop tail for canonicalization to allow diffing of the
        # serialized XML.
        info.tail = None
        return info

    def _update_photo(self, id, local_datedir, local_info, dry_run=False):
        """Update the given photo in the working copy."""
        info = self._info_from_photo_id(id)
        datedir = info.find("dates").get("taken")[:7]
        last_update = _photo_last_update_from_info(info)

        # Figure out what work needs to be done.
        # From *experimentation* it looks like the "secret" attribute
        # changes if the photo itself changes (i.e. is replaced or
        # "Edited" or rotated).
        todos = []
        if datedir != local_datedir:
            log.debug("update %s: datedir change: %r -> %r",
                      id, local_datedir, datedir)
            todos.append("remove-old")
            todos.append("photo")
        elif info.get("secret") != local_info.get("secret"):
            log.debug("update %s: photo secret change: %r -> %r",
                      id, local_info.get("secret"), info.get("secret"))
            todos.append("photo")
        todos.append("info")
        if not todos:
            return datedir

        # Do the necessary updates.
        size_ext = (self.size != "original" and "."+self.size or "")
        ext = (self.size != "original" and ".jpg"
               or "."+local_info.get("originalformat"))

        # - Remove the old bits, if the datedir has changed.
        if "remove-old" in todos:
            d = join(self.base_dir, local_datedir)
            path = join(d, "%s%s%s" % (id, size_ext, ext))
            log.info("D  %s  [%s]", path,
                utils.one_line_summary_from_text(local_info.findtext("title"), 40))
            if not dry_run:
                log.debug("rm `%s'", path)
                os.remove(path)
                self._remove_photo_data(d, id)
                remaining_paths = set(os.listdir(d))
                remaining_paths.difference_update(set([".pics"]))
                if not remaining_paths:
                    log.info("D  %s", d)
                    self.fs.rm(d)

        # - Add the new stuff.
        d = join(self.base_dir, datedir)
        action_str = ("photo" in todos and "U " or " u")
        path = join(d, "%s%s%s" % (id, size_ext, ext))
        log.info("%s %s  [%s]", action_str, path,
            utils.one_line_summary_from_text(info.findtext("title"), 40))
        if not dry_run:
            if not exists(d):
                self.fs.mkdir(d)
                pics_dir = join(d, ".pics")
                if not exists(pics_dir):
                    self.fs.mkdir(pics_dir, hidden=True)
            if "photo" in todos:
                path = join(d, "%s%s%s" % (id, size_ext, ext))
                url = _flickr_photo_url_from_info(info, size=self.size)
                filename, headers = urllib.urlretrieve(url, path)
                mtime = utils.timestamp_from_datetime(last_update)
                os.utime(path, (mtime, mtime))
            self._save_photo_data(d, id, info)
            self.last_update_end = last_update
            
        #print "... %s" % id
        #print "originalsecret: %s <- %s" % (info.get("originalsecret"), local_info.get("originalsecret"))
        #print "secret: %s <- %s" % (info.get("secret"), local_info.get("secret"))
        #print "rotation: %s <- %s" % (info.get("rotation"), local_info.get("rotation"))
        return datedir

    def check_version(self):
        if self.version != self.VERSION:
            raise PicsError("out of date working copy (v%s != v%s): you must "
                            "first upgrade", self.version, self.VERSION)

    def _remove_photo_data(self, dir, id):
        #TODO: 'dir' correct here? need to use self.base_dir?
        data_path = join(dir, ".pics", "%s.xml" % id)
        if exists(data_path):
            log.debug("remove photo data: `%s'", data_path)
            #TODO:XXX use self.fs.rm for this?
            os.remove(data_path)

    def _save_photo_data(self, dir, id, elem):
        data_path = join(dir, ".pics", "%s.xml" % id)
        log.debug("save photo data: `%s'", data_path)
        fdata = open(data_path, 'wb')
        try:
            fdata.write(ET.tostring(elem))
        finally:
            fdata.close()

    def _get_photo_data(self, datedir, id):
        data_path = join(self.base_dir, datedir, ".pics", "%s.xml" % id)
        if exists(data_path):
            log.debug("load photo data: `%s'", data_path)
            fdata = open(data_path, 'rb')
            try:
                return ET.parse(fdata).getroot()
            except pyexpat.ParserError:
                log.debug("corrupt photo data: XXX")
                #TODO: what to do with it?
                XXX
                return None
            finally:
                fdata.close()
        else:
            return None

    def _local_photo_dirs_and_ids_from_target(self, target):
        """Yield the identified photos from the given target.
        
        Yields 2-tuples: <pics-wc-dir>, <photo-id>
        """
        XXX # Semantics of things have changed. Re-evaluate this.
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
                for p in utils.paths_from_path_patterns([path],
                            dirs="if-not-recursive",
                            recursive=False,
                            on_error="yield"):
                    for d in self._photo_data_from_local_path(p):
                        yield d

    def open(self, target):
        """Open the given photo or dir target on flickr.com."""
        print "XXX target: %r" % target
        dir = basename(abspath(target))
        if not isdir(target):
            dirs_and_ids = [
                di
                for p in utils.paths_from_path_patterns(
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
        elif not exists(join(target, ".pics")):
            raise PicsError("`%s' is not a pics working copy dir" % path)
        elif re.match(r"\d{4}-\d{2}", dir):
            year, month = dir.split("-")
            url = "http://www.flickr.com/photos/%s/archives/date-posted/%s/%s/calendar/"\
                  % (self.user, year, month)
        else:
            url = "http://www.flickr.com/photos/%s/" % self.user
            #raise PicsError("`%s' isn't a pics date dir or photo file or id: "
            #                "can't yet handle that" % target)

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

    def info(self, path):
        """Dump info (retrieved from flickr) about the identified photos."""
        for p in utils.paths_from_path_patterns([path],
                    dirs="if-not-recursive",
                    recursive=False,
                    on_error="yield"):
            for dir, id in self._local_photo_dirs_and_ids_from_target(p):
                log.debug("dump info for photo", id)
                print "XXX call api.photos_getInfo(%r)" % id
                info = self.api.photos_getInfo(id)
                print "XXX got: %r" % info
                pprint(info)
                XXX

    def update(self, dry_run=False):
        #TODO: when support local edits, need to check for conflicts
        #      and refuse to update if hit one
        
        # Determine start date from which we need to update.
        if self.last_update_end:
            min_date = self.last_update_end  # UTC
        elif self.base_date:
            min_date = self.base_date # UTC
        else:
            #TODO: Determine first appropriate date for this user via
            #      (a) user's NSID from get_auth_token response -- need
            #          to save that and provide it via the SimpleFlickrAPI.
            #      (b) Using people.getInfo user_id=NSID.
            min_date = datetime.date(1980, 1, 1)  # before Flickr's time
        d = min_date
        min_date = int(utils.timestamp_from_datetime(min_date))
        min_date += 1 # To avoid always re-updating the latest changed photo.
        log.debug("update: min_date=%s (%s)", min_date, d)

        with self.db.connect(True) as cu:
            # Gather all updates to do.
            # After commiting this it is okay if this script is aborted
            # during the actual update: a subsequent 'pics up' will
            # continue where we left off.
            recents = self.api.paging_call(
                "flickr.photos.recentlyUpdated",
                min_date=min_date,
                extras="last_update")
            for elem in recents:
                id = elem.get("id")
                cu.execute("INSERT OR REPLACE INTO pics_update VALUES (?)", (id,))
            if not dry_run:
                cu.connection.commit()

            # Do each update.
            cu.execute("SELECT id FROM pics_update")
            ids = [row[0] for row in cu]
            for id in ids:
                # Determine if this is an add, update, conflict, merge or delete.
                #TODO: test a delete (does recent updates show that?)
                cu.execute("SELECT * FROM pics_photo WHERE id=?", (id,))
                row = cu.fetchone()
                if row is None:
                    action = "A" # adding a new photo
                else:
                    local_datedir = row[1]
                    local_info = self._get_photo_data(local_datedir, id)
                    if local_info is None:
                        #TODO: might have been a locally deleted file
                        action = "A"  # restore?
                    else:
                        #TODO: support local changes would be handled here:
                        #  Maintain MD5 of photo and info files and
                        #  detect changes that way.
                        action = "U"

                # Handle the action.
                if action == "A":
                    datedir = self._add_photo(id, dry_run=dry_run)
                    cu.execute("INSERT INTO pics_photo VALUES (?,?)", (id, datedir))
                elif action == "U":
                    datedir = self._update_photo(id, local_datedir, local_info, dry_run=dry_run)
                    if datedir != local_datedir:
                        XXX # test this case
                        cu.execute("UPDATE pics_photo SET datedir=? WHERE id=?",
                                   (datedir, id))
                else:
                    raise PicsError("unexpected update action: %r" % action)

                # Note this update.
                cu.execute("DELETE FROM pics_update WHERE id=?", (id,))
                if not dry_run:
                    cu.connection.commit()
                    self._checkpoint()

        log.info("Up to date (latest update: %s UTC).",
                 self.last_update_end.strftime("%Y %b %d, %H:%M:%S"))

        #TODO: Handle favs, tags, sets.
        #      Need to use activity.userPhotos() to update these?

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



#---- internal support stuff

class Database(object):
    """Wrapper API for the working copy's sqlite database."""
    # Database version.
    # VERSION is the version of this Database code. The property
    # "version" is the version of the database on disk. The patch-level
    # version number should be used for small upgrades to the database.
    #
    # How to update version:
    # (a) change VERSION,
    # (b) add a change log comment here, and
    # (c) add an entry to `_upgrade_info_from_curr_ver`.
    #
    # db change log:
    # - 1.0.0: initial version
    VERSION = "1.0.0"

    schema = """
        CREATE TABLE pics_meta (
            key TEXT UNIQUE ON CONFLICT REPLACE,
            value TEXT
        );

        -- List of photos in the working copy.
        CREATE TABLE pics_photo (
            id INTEGER UNIQUE,
            datedir TEXT
        );

        -- List of photos to update.
        CREATE TABLE pics_update (
            id INTEGER UNIQUE
        );
    """

    path = None
    def __init__(self, path):
        self.path = path
        if not exists(self.path):
            self.create()
        else:
            try:
                self.upgrade()
            except Exception, ex:
                log.exception("error upgrading `%s': %s", self.path, ex)
                self.reset()

    def __repr__(self):
        return "<Database %s>" % self.path

    @contextmanager
    def connect(self, commit=False, cu=None):
        """A context manager for a database connection/cursor. It will automatically
        close the connection and cursor.

        Usage:
            with self.connect() as cu:
                # Use `cu` (a database cursor) ...

        @param commit {bool} Whether to explicitly commit before closing.
            Default false. Often SQLite's autocommit mode will
            automatically commit for you. However, not always. One case
            where it doesn't is with a SELECT after a data modification
            language (DML) statement (i.e.  INSERT/UPDATE/DELETE/REPLACE).
            The SELECT won't see the modifications. If you will be
            making modifications, probably safer to use `self.connect(True)`.
            See "Controlling Transations" in Python's sqlite3 docs for
            details.
        @param cu {sqlite3.Cursor} An existing cursor to use. This allows
            callers to avoid the overhead of another db connection when
            already have one, while keeping the same "with"-statement
            call structure.
        """
        if cu is not None:
            yield cu
        else:
            cx = sqlite3.connect(self.path)
            cu = cx.cursor()
            try:
                yield cu
            finally:
                if commit:
                    cx.commit()
                cu.close()
                cx.close()

    def create(self):
        """Create the database file."""
        #TODO: error handling?
        with self.connect(True) as cu:
            cu.executescript(self.schema)
            cu.execute("INSERT INTO pics_meta(key, value) VALUES (?, ?)", 
                ("version", self.VERSION))

    def reset(self, backup=True):
        """Remove the current database (possibly backing it up) and create
        a new empty one.

        @param backup {bool} Should the original database be backed up.
            If so, the backup is $database_file+".bak". Default true.
        """
        if backup:
            backup_path = self.path + ".bak"
            if exists(backup_path):
                _rm_file(backup_path)
            if exists(backup_path): # couldn't remove it
                log.warn("couldn't remove old '%s' (skipping backup)",
                         backup_path)
                _rm_file(self.path)
            else:
                os.rename(self.path, backup_path)
        else:
            _rm_file(self.path)
        self.create()

    def upgrade(self):
        """Upgrade the current database."""
        # 'version' is the DB ver on disk, 'VERSION' is the target ver.
        curr_ver = self.version
        while curr_ver != self.VERSION:
            try:
                result_ver, upgrader, upgrader_arg \
                    = self._upgrade_info_from_curr_ver[curr_ver]
            except KeyError:
                raise HistoryDatabaseError(
                    "cannot upgrade from db v%s: no upgrader for this version"
                    % curr_ver)
            log.info("upgrading from db v%s to db v%s ...",
                     curr_ver, result_ver)
            if upgrader_arg is not None:
                upgrader(self, curr_ver, result_ver, upgrader_arg)
            else:
                upgrader(self, curr_ver, result_ver)
            curr_ver = result_ver

    def _upgrade_reset_db(self, curr_ver, result_ver):
        """Upgrader that just starts over."""
        assert result_ver == self.VERSION
        self.reset()

    _upgrade_info_from_curr_ver = {
        # <current version>: (<resultant version>, <upgrader method>, <upgrader args>)
        # e.g.: "1.0.0": (VERSION, _upgrade_reset_db, None),
    }

    @property
    def version(self):
        """Return the version of the db on disk (or None if cannot
        determine).
        """
        #TODO: error handling?
        return self.get_meta("version")

    def get_meta(self, key, default=None, cu=None):
        """Get a value from the meta table.
        
        @param key {str} The meta key.
        @param default {str} Default value if the key is not found in the db.
        @param cu {sqlite3.Cursor} An existing cursor to use.
        @returns {str} The value in the database for this key, or `default`.
        """
        with self.connect(cu=cu) as cu:
            cu.execute("SELECT value FROM pics_meta WHERE key=?", (key,))
            row = cu.fetchone()
            if row is None:
                return default
            return row[0]
    
    def set_meta(self, key, value, cu=None):
        """Set a value into the meta table.
        
        @param key {str} The meta key.
        @param default {str} Default value if the key is not found in the db.
        @param cu {sqlite3.Cursor} An existing cursor to use.
        @returns {str} The value in the database for this key, or `default`.
        """
        with self.connect(True, cu=cu) as cu:
            cu.execute("INSERT INTO pics_meta(key, value) VALUES (?, ?)", 
                (key, value))

    def del_meta(self, key):
        """Delete a key/value pair from the meta table.
        
        @param key {str} The meta key.
        """
        with self.connect(True) as cu:
            cu.execute("DELETE FROM pics_meta WHERE key=?", (key,))

def _photo_last_update_from_info(info):
    lastupdate = info.find("dates").get("lastupdate")
    return datetime.datetime.utcfromtimestamp(float(lastupdate))

def _flickr_photo_url_from_info(info, size="original"):
    url = "http://farm%(farm)s.static.flickr.com/%(server)s/%(id)s_" % info.attrib
    if size == "original":
        url += info.get("originalsecret")
    else:
        url += info.get("secret")
    url += {
        "square": "_s",
        "thumbnail": "_t",
        "small": "_m",
        "medium": "",
        "large": "_b",
        "original": "_o",
    }[size]
    if info.get("originalsecret") != info.get("secret"):
        # If there has been some transformation on the photo (e.g.
        # replacement or a rotation) then the download urls need this
        # suffix.
        url += "_d"
    if size == "original":
        url += '.' + info.get("originalformat")
    else:
        url += ".jpg"
    return url

def _find_wc_base_dir(path):
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

def _md5_path(path):
    f = open(path, 'rb')
    try:
        return md5(f.read()).hexdigest()
    finally:
        f.close()


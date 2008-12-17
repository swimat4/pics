# Copyright (c) 2008 ActiveState Software Inc.

"""pics working copy handling"""

import os
import sys
from os.path import normpath, exists, join, expanduser, dirname
import logging
import datetime
import urllib
import cPickle as pickle
from xml.etree import ElementTree as ET
import sqlite3
from hashlib import md5

from picslib.filesystem import FileSystem
from picslib import utils
from picslib.utils import xpprint
from picslib import simpleflickrapi



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
    """
    TODO: doc usage and attrs
        version
        version_info
        last_update_start
        last_update_end
        ...
    """
    API_VERSION_INFO = (0, 2, 0)

    def __init__(self, base_dir):
        self.base_dir = normpath(base_dir)
        self.db_path = join(self.base_dir, ".pics", "photos.sqlite3")
        self.fs = FileSystem(log.debug)
        self._cache = {}

    @property
    def ilk(self):
        if "ilk" not in self._cache:
            type_path = join(self.base_dir, ".pics", "ilk")
            self._cache["ilk"] = open(type_path, 'r').read().strip()
        return self._cache["ilk"]

    @property
    def user(self):
        if "user" not in self._cache:
            user_path = join(self.base_dir, ".pics", "user")
            self._cache["user"] = open(user_path, 'r').read().strip()
        return self._cache["user"]

    @property
    def size(self):
        if "size" not in self._cache:
            path = join(self.base_dir, ".pics", "size")
            self._cache["size"] = open(path, 'r').read().strip()
        return self._cache["size"]

    @property
    def base_date(self):
        if "base_date" not in self._cache:
            base_date_path = join(self.base_dir, ".pics", "base_date")
            if not exists(base_date_path):
                self._cache["base_date"] = None
            else:
                s = open(base_date_path, 'r').read().strip()
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
            self._note_last_update(last_update)
        return datedir

    def _update_photo(self, id, local_datedir, local_info, dry_run=False):
        """Update the given photo in the working copy."""
        info = self.api.photos_getInfo(photo_id=id)[0]  # <photo> elem

        # Figure out what work needs to be done.
        # From *experimentation* it looks like the "originalsecret" and
        # "secret" attributes change if the photo itself changes (i.e.
        # is replaced or "Edited"). Also note that a change in "rotation"
        # means that we should re-download the photo -- although this
        # could be optimized by transforming locally.
        # TODO:
        # - is originalsecret != secret an equivalent check? If so, use
        # that.
        todo = []
        if info.get("secret") != local_info.get("secret") \
           or info.get("rotation") != local_info.get("rotation"):
            todo.append("photo")
            todo.append("info")


        XXX

        if not dry_run:
            dir = join(self.base_dir, date_dir)
            pics_dir = join(dir, ".pics")
            if not exists(dir):
                self.fs.mkdir(dir)
            if not exists(pics_dir):
                self.fs.mkdir(pics_dir, hidden=True)

        # Determine if the update includes a change to the photo itself.
        # From *experimentation* it looks like the "originalsecret" and
        # "secret" attributes change if the photo itself changes (i.e.
        # is replaced or "Edited"). Also note that a change in "rotation"
        # means that we should re-download the photo -- although this
        # could be optimized by transforming locally.
        #
        # START HERE:
        # - if "originalsecret" or "rotation" change then need to
        #   update the photo itself
        #   TODO: doesn't a rotation show as a change in originalsecret?
        # - always need to re-save the meta data
        # - log the changes to be made
        # - redownload, if necessary
        # - save the new info (make sure this is after the re-download
        #   to ensure redo if interrupted)
        #
        #XXX Dump diff of photo info before/after.
        local_info_str = ET.tostring(local_info)
        new_info = self.api.photos_getInfo(photo_id=id)[0]  # <photo> elem
        new_info_str = ET.tostring(new_info) 
        import difflib
        diff = difflib.unified_diff(
                local_info_str.splitlines(1), 
                new_info_str.splitlines(1),
                "local info",
                "new info")
        diff = u''.join(diff)
        print diff
        XXX

        log.info("U  %s  [%s]", photo["id"],
                 utils.one_line_summary_from_text(photo["title"], 40))
        if not dry_run:
            ##TODO:XXX Differentiate photo vs. meta-date update.
            #small_path = join(dir, "%(id)s.small.jpg" % photo)
            #small_url = "http://farm%(farm)s.static.flickr.com/%(server)s/%(id)s_%(secret)s_m.jpg" % photo
            #filename, headers = urllib.urlretrieve(small_url, small_path)
            #mtime = _timestamp_from_datetime(photo["lastupdate"])
            #os.utime(small_path, (mtime, mtime))
            self._save_photo_data(dir, photo["id"], photo)
            self._note_last_update(photo["lastupdate"])

    def create(self, ilk, user, base_date=None, size="original"):
        assert ilk == "flickr", "unknown pics repo ilk: %r" % ilk
        assert isinstance(base_date, (type(None), datetime.date))
        assert size in ("small", "medium", "original")

        # Create base structure.
        if not exists(self.base_dir):
            self.fs.mkdir(self.base_dir, parents=True)
        d = join(self.base_dir, ".pics")
        if not exists(d):
            self.fs.mkdir(d, hidden=True)
        ver_str = '.'.join(map(str, self.API_VERSION_INFO))
        open(join(d, "version"), 'w').write(ver_str+'\n')
        open(join(d, "ilk"), 'w').write(ilk+'\n')
        open(join(d, "user"), 'w').write(user+'\n')
        if base_date:
            open(join(d, "base_date"), 'w').write(str(base_date)+'\n')
        open(join(d, "size"), 'w').write(size+'\n')

        # Main working copy database.
        if exists(self.db_path):
            os.remove(self.db_path)
        cx = sqlite3.connect(self.db_path)
        cu = cx.cursor()
        cu.executescript("""
            -- List of photos in the working copy.
            CREATE TABLE photos (
                id INTEGER UNIQUE,
                datedir TEXT
            );
            -- List of photos to update.
            CREATE TABLE updates (
                id INTEGER UNIQUE
            );
        """)
        cx.commit()
        cu.close()
        cx.close()

    def check_version(self):
        if self.version_info != self.API_VERSION_INFO:
            raise PicsError("out of date working copy (v%s < v%s): you must "
                            "first upgrade", self.version_info,
                            '.'.join(map(str(self.API_VERSION_INFO))))

    def _save_photo_data(self, dir, id, elem):
        data_path = join(dir, ".pics", "%s.xml" % id)
        log.debug("save photo data: `%s'", data_path)
        fdata = open(data_path, 'wb')
        try:
            fdata.write(ET.tostring(elem))
        finally:
            fdata.close()

    def _get_photo_data(self, dir, id):
        data_path = join(dir, ".pics", "%s.xml" % id)
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

    def _get_photo_local_changes(self, dir, id):
        XXX
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
                for p in utils.paths_from_path_patterns([path],
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
        if self.last_update_end:
            min_date = self.last_update_end
        elif self.base_date:
            min_date = self.base_date
        else:
            #TODO: Determine first appropriate date for this user via
            #      (a) user's NSID from get_auth_token response -- need
            #          to save that an provide it via the SimpleFlickrAPI.
            #      (b) Using people.getInfo user_id=NSID.
            min_date = datetime.date(1980, 1, 1)  # before Flickr's time
        d = min_date
        min_date = int(utils.timestamp_from_datetime(min_date))
        min_date += 1 # To avoid always re-updating the latest changed photo.
        log.debug("update: min_date=%s (%s)", min_date, d)

        cx = sqlite3.connect(self.db_path)
        cu = cx.cursor()
        try:
            # Gather all updates to do.
            # After commiting this it is okay if this script is aborted
            # during the actual update: a subsequent 'pics up' will
            # continue where we left off.
            recents = self.api.paging_call(
                "flickr.photos.recentlyUpdated",
                min_date=min_date)
            for elem in recents:
                id = elem.get("id")
                cu.execute("INSERT OR REPLACE INTO updates VALUES (?)", (id,))
            if not dry_run:
                cx.commit()

            # Do each update.
            cu.execute("SELECT id FROM updates")
            ids = [row[0] for row in cu]
            for id in ids:
                # Determine if this is an add, update, conflict, merge or delete.
                #TODO: test a delete (does recent updates show that?)
                cu.execute("SELECT * FROM photos WHERE id=?", (id,))
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
                        local_changes = self._get_photo_local_changes(local_datedir, id)
                        if local_changes:
                            action = "C" # conflict (don't yet support merging)
                        else:
                            action = "U"

                # Handle the action.
                if action == "A":
                    datedir = self._add_photo(id, dry_run=dry_run)
                    cu.execute("INSERT INTO photos VALUES (?,?)", (id, datedir))
                elif action == "U":
                    datedir = self._update_photo(id, local_datedir, local_info, dry_run=dry_run)
                    if datedir != local_datedir:
                        XXX # test this case
                        cu.execute("UPDATE photos SET datedir=? WHERE id=?",
                                   (datedir, id))
                elif action == "C":
                    log.info("%s  %s  [%s]", action, id,
                        utils.one_line_summary_from_text(elem.get("title"), 40))
                    log.error("Aborting update at conflict.")
                    break

                # Note this update.
                self._checkpoint()
                cu.execute("DELETE FROM updates WHERE id=?", (id,))
                if not dry_run:
                    cx.commit()
        finally:
            cu.close()
            cx.close()

        log.info("Up to date (latest update: %s UTC).",
                 self.last_update_end.strftime("%b %d, %Y"))

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

def _photo_last_update_from_info(info):
    lastupdate = info.find("dates").get("lastupdate")
    return datetime.datetime.fromtimestamp(float(lastupdate))

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

def _find_wc_base_dir(self, path=None):
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


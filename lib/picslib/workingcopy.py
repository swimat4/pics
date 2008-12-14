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

from picslib.filesystem import FileSystem
from picslib import utils
from picslib.utils import xpprint
from picslib import simpleflickrapi



log = logging.getLogger("pics")



def wcs_from_paths(self, paths):
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
        self.fs = FileSystem(log.debug)
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
    def base_date(self):
        if "base_date" not in self._cache:
            base_date_path = join(self.base_dir, ".pics", "base_date")
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

    def _add_photo(self, photo, dry_run=False):
        """Add the given photo to the working copy."""
        #pprint(photo)

        if not dry_run:
            date_dir = join(self.base_dir, photo.datetaken[:7])
            pics_dir = join(date_dir, ".pics")
            if not exists(date_dir):
                self.fs.mkdir(date_dir)
            if not exists(pics_dir):
                self.fs.mkdir(pics_dir, hidden=True)

        path = join(date_dir, "%s.small.jpg" % photo.id)
        log.info("A  %s  [%s]", path,
                 utils.one_line_summary_from_text(photo.title, 40))
        if not dry_run:
            #TODO: add a reporthook for progressbar (unless too quick to bother)
            #TODO: handle ContentTooShortError (py2.5)
            filename, headers = urllib.urlretrieve(photo.small_url, path)
            mtime = utils.timestamp_from_datetime(photo.last_update)
            os.utime(path, (mtime, mtime))
            self._save_photo_data(date_dir, photo.id, photo)
            self._note_last_update(photo.last_update)

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
                 utils.one_line_summary_from_text(photo["title"], 40))
        if not dry_run:
            ##TODO:XXX Differentiate photo vs. meta-date update.
            #small_path = join(date_dir, "%(id)s.small.jpg" % photo)
            #small_url = "http://farm%(farm)s.static.flickr.com/%(server)s/%(id)s_%(secret)s_m.jpg" % photo
            #filename, headers = urllib.urlretrieve(small_url, small_path)
            #mtime = _timestamp_from_datetime(photo["lastupdate"])
            #os.utime(small_path, (mtime, mtime))
            self._save_photo_data(date_dir, photo["id"], photo)
            self._note_last_update(photo["lastupdate"])

    def create(self, type, user, base_date=None):
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
        if base_date:
            assert isinstance(base_date, datetime.date)
            open(join(d, "base_date"), 'w').write(str(base_date)+'\n')

        ## Get the latest N photos up to M months ago (rounded down) --
        ## whichever is less.
        #N = 3 #TODO: 100
        #M = 3
        #recents = self.api.photos_recentlyUpdated(
        #            min_date=utils.date_N_months_ago(M),
        #            extras=["date_taken", "owner_name", "last_update",
        #                    "icon_server", "original_format",
        #                    "geo", "tags", "machine_tags"],
        #            per_page=N, page=1)
        #for i, recent in enumerate(recents):
        #    self._add_photo(recent)
        #    if i % 10 == 0:
        #        self._checkpoint()
        #if i % 10 != 0:
        #    self._checkpoint()
        #log.info("Checked out latest updated %d photos (%s - %s).",
        #         i+1, self.last_update_start.strftime("%b %d, %Y"),
        #         self.last_update_end.strftime("%b %d, %Y"))

        #TODO: create favs/...
        #      Just start with the most recent N favs.
        #log.debug("create `%s/favs'", self.base_dir)
        #self.fs.mkdir(join(self.base_dir, "favs"))
        #self.fs.mkdir(join(self.base_dir, "favs", ".pics"), hidden=True)

        #TODO: tags/..., sets/...
        #      Need to use activity.userPhotos() to update these?

    def check_version(self):
        if self.version_info != self.API_VERSION_INFO:
            raise PicsError("out of date working copy (v%s < v%s): you must "
                            "first upgrade", self.version_info,
                            '.'.join(map(str(self.API_VERSION_INFO))))

    def _save_photo_data(self, dir, id, photo):
        data_path = join(dir, ".pics", id+".xml")
        log.debug("save photo data: `%s'", data_path)
        fdata = open(data_path, 'wb')
        try:
            fdata.write(ET.tostring(photo.elem))
        finally:
            fdata.close()

    def _get_photo_data(self, dir, id):
        #TODO: add caching of photo data (co-ordinate with _save_photo_data)
        data_path = join(dir, ".pics", id+".xml")
        if exists(data_path):
            log.debug("load photo data: `%s'", data_path)
            fdata = open(data_path, 'rb')
            try:
                return ET.load(fdata)
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
        min_date = str(int(utils.timestamp_from_datetime(min_date)))
        recents = self.api.paging_generator_call(
            "flickr.photos.recentlyUpdated",
            min_date=min_date,
            extras=','.join([
                "date_taken", "owner_name", "last_update",
                "icon_server", "original_format", "media",
                "geo", "tags", "machine_tags"
            ]))

        curr_subdir = utils.relpath(os.getcwd(), self.base_dir)
        SENTINEL = 1000 #XXX
        for elem in recents:
            SENTINEL -= 1
            if SENTINEL <= 0:
                print "XXX sentinel, breaking"
                break
            #utils.xpprint(elem)
            photo = _Photo(elem)

            subdir = photo.datetaken[:len("YYYY-MM")]
            if subdir == curr_subdir:
                dir = ""
            else:
                dir = join(self.base_dir, subdir)
            id = photo.id

            # Determine if this is an add, update, conflict, merge or delete.
            #TODO: test a delete (does recent updates show that?)
            #TODO: test a conflict
            #TODO: what about photo *content* changes?
            #TODO: bother to support merge?
            #TODO: what about photo notes?
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
                self._add_photo(photo, dry_run=dry_run)
            elif action == "U":
                self._update_photo(photo, dry_run=dry_run)
            elif action == "C":
                log.info("%s  %s  [%s]", action, id,
                    utils.one_line_summary_from_text(photo.title, 40))
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



#---- internal support stuff

class _Photo(object):
    def __init__(self, elem):
        self.elem = elem
    def __getattr__(self, name):
        v = self.elem.get(name)
        if v is not None:
            return v
        raise AttributeError("type %s has no attribute '%s'"
                             % (type(self).__name__, name))
    @property
    def small_url(self):
        return "http://farm%(farm)s.static.flickr.com/%(server)s/" \
               "%(id)s_%(secret)s_m.jpg" % self.elem.attrib

    @property
    def last_update(self):
        #TODO: cache this
        return datetime.datetime.fromtimestamp(float(self.lastupdate))


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



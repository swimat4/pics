# Copyright (c) 2008 ActiveState Software Inc.

import sys
from os.path import normpath, exists, join, expanduser
import logging

from picslib.filesystem import FileSystem
from picslib import utils
from picslib import flickrapi


log = logging.getLogger("pics")



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
            self._api_cache = flickrapi.FlickrAPI(
                utils.get_flickr_api_key(), utils.get_flickr_secret(),
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
                    min_date=utils.date_N_months_ago(M),
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

    def info(self, path):
        """Dump info (retrieved from flickr) about the identified photos."""
        for p in _paths_from_path_patterns([path],
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


# Copyright (c) 2008 ActiveState Software Inc.

"""cmdln.Shell class defining the 'pics ...' command line interface."""

import os
from os.path import dirname, join, expanduser, exists, isdir
import sys
import logging
from pprint import pprint
import re
import time
import datetime

try:
    import cmdln
except ImportError:
    sys.path.insert(0, expanduser("~/tm/cmdln/lib"))
    import cmdln
    del sys.path[0]

import picslib
from picslib.errors import PicsError
from picslib import simpleflickrapi
from picslib import utils
from picslib.workingcopy import WorkingCopy, wcs_from_paths


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

    def _do_play(self, subcmd, opts):
        """Run my current play/dev code.

        ${cmd_usage}
        ${cmd_option_list}
        """
        if False:
            api_key = utils.get_flickr_api_key()
            secret = utils.get_flickr_secret()
            flickr = simpleflickrapi.SimpleFlickrAPI(api_key, secret)
            auth_token = flickr.get_auth_token(perms="read")
            t = time.time()
            t -= 30 * 24 * 60 * 60.0
            t = str(int(t))
            utils.xpprint(
                #flickr.favorites_getList()
                flickr.photos_recentlyUpdated(min_date=t, extras="date_taken,media,original_format")
            )
        if True:
            import sqlite3
            cx = sqlite3.connect("photos.sqlite3")
            cu = cx.cursor()
            cu.executescript("""
                -- List of photos in the working copy.
                CREATE TABLE photos (
                    id INTEGER UNIQUE,
                    datedir TEXT
                );
                -- List of photos to update.
                CREATE TABLE updates (
                    id INTEGER UNIQUE,
                    datedir TEXT
                );
            """)
            cx.commit()

            # Gather all the updates to do.
            for row in [(1,'a'), (2,'b'), (3,'c')]:
                cu.execute("INSERT INTO updates VALUES (?,?)", row)
            cx.commit()

            # Do all the updates.
            cu.execute("SELECT * from updates")
            for row in cu:
                print row

            cu.close()
            cx.close()

    @cmdln.option("-d", "--format-dates", action="store_true", default=False,
        help="massage select date arguments from the convenient YYYY-MM[-DD] format "
             "into the datetime format that flickr wants")
    @cmdln.option("-p", "--paging", action="store_true", default=False,
        help="Use the SimpleFlickrAPI.paging_call to page back though all items.")
    def _do_flickr(self, subcmd, opts, method, *args):
        """${cmd_name}: Call the given Flickr API method (for debugging).

        ${cmd_usage}
        ${cmd_option_list}
        Examples:
            pics flickr reflection.getMethods
            pics flickr reflection.getMethodInfo method_name=flickr.photos.getInfo
            pics flickr photos.getInfo photo_id=140542114
            pics flickr -d photos.recentlyUpdated min_date=2007-02-11 extras=last_update
        """
        api_key = utils.get_flickr_api_key()
        secret = utils.get_flickr_secret()
        flickr = simpleflickrapi.SimpleFlickrAPI(api_key, secret)
        auth_token = flickr.get_auth_token(perms="read")
        kwargs = dict(a.split('=', 1) for a in args)
        if opts.format_dates:
            if method == "photos.recentlyUpdated" and "min_date" in kwargs:
                d = kwargs["min_date"]
                if re.match("\d+-\d+-\d+", d):
                    dt = datetime.datetime.strptime(d, "%Y-%m-%d")
                    t = str(int(utils.timestamp_from_datetime(dt)))
                    log.debug("min_date: %r -> %r", kwargs["min_date"], t)
                    kwargs["min_date"] = t
        if opts.paging:
            per_page = int(kwargs.get("per_page", 100))
            for i, item in enumerate(flickr.paging_call("flickr."+method, **kwargs)):
                if i and i % per_page == 0:
                    raw_input("Press <Enter> for next page of results...")
                utils.xpprint(item)
        else:
            xml = flickr.call("flickr."+method, **kwargs)
            utils.xpprint(xml)

    @cmdln.alias("d")
    def _do_date(self, subcmd, opts, date):
        """${cmd_name}: convert dates between timestamps and
        'YYYY-MM-DD [HH:MM:SS]'

        ${cmd_usage}
        ${cmd_option_list}
        """
        try:
            timestamp = float(date)
        except ValueError, ex:
            raise PicsError("can only handle timestamps currently: %r" % date)
        t = datetime.datetime.utcfromtimestamp(timestamp)
        t8 = t - datetime.timedelta(hours=8)
        print "timetuple", t.timetuple()
        print "%s (utc), %s (vancouver, -0800)" % (t, t8)

    @cmdln.option("-b", "--base-date", dest="base_date_str", metavar="YYYY-MM-DD",
        help="A base date (UTC) from which to consider photo updates to flickr. "
             "This case be useful for just working with more recent photos "
             "or just for testing 'pics'.")
    @cmdln.option("-s", "--size", default="original",
        help="Specify a photo size to download. Valid values are 'small', "
             "'medium', and 'original' (default)")
    @cmdln.alias("co")
    def do_checkout(self, subcmd, opts, url, path=None):
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
        """
        repo_type, repo_user = utils.parse_source_url(url)
        if repo_type != "flickr":
            raise PicsError("unsupported pics repository type: %r" % repo_type)
        if path is None:
            path = repo_user
        if exists(path) and not isdir(path):
            raise PicsError("`%s' exists and is in the way")
        if exists(path):
            raise PicsError("`%s' exists: cannot checkout into existing "
                            "directory" % path)
        wc = WorkingCopy(path)
        base_date = None
        if opts.base_date_str:
            t = datetime.datetime.strptime(opts.base_date_str, "%Y-%m-%d")
            base_date = datetime.date(t.year, t.month, t.day)
        size = opts.size or "original"
        wc.create(repo_type, repo_user, base_date, size)
        wc.update()

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
        targets = target or [os.curdir]
        for wc, path in wcs_from_paths(targets):
            if wc is None:
                if isdir(path):
                    log.error("'%s' is not a working copy", path)
                else:
                    log.error("'%s' is not in a working copy", path)
                break
            else:
                wc.list([path], format=opts.format, tags=opts.tags)

    def do_info(self, subcmd, opts, *target):
        """${cmd_name}: Display info about a photo.
        
        Currently this retrieves photo info from flickr rather than using
        the local cache. This is because not *all* photo data is currently
        being tracked by pics.

        ${cmd_usage}
        ${cmd_option_list}
        """
        targets = target or [os.curdir]
        for wc, path in wcs_from_paths(targets):
            if wc is None:
                if isdir(path):
                    log.error("'%s' is not a working copy", path)
                else:
                    log.error("'%s' is not in a working copy", path)
                break
            else:
                wc.info(path)

    def do_open(self, subcmd, opts, target=None):
        """Open given photo or dir on flickr.com.

        ${cmd_usage}
        ${cmd_option_list}
        Examples:
            pics open ~/pics/2009-01  # opens month summary URL for Jan 2009
            pics open 2009-01/155804574.small.jpg  # opens that photo's URL
            pics open  # opens a URL appropriate for the current dir
        """
        if target is None:
            target = os.curdir
        wc = list(wcs_from_paths([target]))[0][0]
        if wc is None:
            if isdir(target):
                log.error("'%s' is not a working copy", target)
            else:
                log.error("'%s' is not in a working copy", target)
        else:
            wc.open(target)

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
        for wc, path in wcs_from_paths(paths):
            if wc is None:
                log.info("skipped '%s'", path)
            else:
                wc.update(dry_run=opts.dry_run)

    #TODO: some command(s) for editing pic data
    #   - allow batch changes
    #   - either 'edit' or a set of 'prop*'-like cmds

    def _do_add(self, subcmd, opts, *path):
        """${cmd_name}: NYI. Put files and dirs under pics control.

        ${cmd_usage}
        ${cmd_option_list}

        TODO: --tag,-t to add a tag
        """
        raise NotImplementedError("add")

    @cmdln.alias("di")
    def _do_diff(self, subcmd, opts, *path):
        """${cmd_name}: NYI. Show local pic and meta-data differences.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("diff")

    @cmdln.alias("stat", "st")
    def _do_status(self, subcmd, opts, *path):
        """${cmd_name}: NYI. Show the status of working files and dirs.

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("status")

    @cmdln.alias("ci")
    def _do_commit(self, subcmd, opts, *path):
        """${cmd_name}: NYI. Send changes from your working copy to the repository
        (flickr).

        ${cmd_usage}
        ${cmd_option_list}
        """
        raise NotImplementedError("commit")


#!/usr/bin/env python

"""cmdln.Shell class defining the 'pics ...' command line interface."""

import os
from os.path import dirname, join, expanduser
import sys
import logging
from pprint import pprint

try:
    import cmdln
    from cmdln import option
except ImportError:
    sys.path.insert(0, expanduser("~/tm/cmdln/lib"))
    import cmdln
    from cmdln import option
    del sys.path[0]

import picslib
from picslib.errors import PicsError

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

    @option("-a", "--app", dest="apps", metavar="APP", action="append",
            help="The application(s) for which to setup the devinstall. "
                 "Value can be an app name, abbreviated name, app GUID "
                 "or base install directory. "
                 "Can be used multiple times.")
    @option("-d", "--source-dir",
            help="The directory with the source for the extension "
                 "(defaults to the current dir)")
    @option("-f", "--force", action="store_true",
            help="Force overwriting of existing extension installs/dev-installs.")
    @option("-n", "--dry-run", action="store_true",
            help="Do a dry-run.")
    def do_devinstall(self, subcmd, opts):
        """${cmd_name}: install into the relevant apps for development

        ${cmd_usage}
        ${cmd_option_list}
        Mozilla's extension system allows an extension to be "installed"
        via a reference in that app's extensions dir that just refers
        to the source directory here. This allows for a quicker
        development cycle, edit/re-start-app, rather than,
        edit/re-build-xpi/re-install-xpi/re-start-app.
        """
        if opts.source_dir is None:
            opts.source_dir = os.curdir

        # Determine to which apps to install.
        install_rdf = filetypes.InstallRdf.init_from_path(
            join(opts.source_dir, "install.rdf"))
        if opts.apps:
            attrs_and_tas_from_value = defaultdict(set)
            for ta in install_rdf.targetApplications:
                app = ta.app
                attrs_and_tas_from_value[app.id.lower()].add(("id", ta))
                attrs_and_tas_from_value[app.name.lower()].add(("name", ta))
                for abbrev in app.abbrevs:
                    attrs_and_tas_from_value[abbrev.lower()].add(("abbrev", ta))
            #pprint(attrs_and_tas_from_value)

            target_apps = set()
            for s in opts.apps:
                filter = s.lower()
                for v in attrs_and_tas_from_value:
                    if filter in v:
                        for attr, ta in attrs_and_tas_from_value[v]:
                            log.debug("`%s' matches %r (%s)", s, ta, attr)
                            target_apps.add(ta)

            if not target_apps:
                log.error("`%s' did not match any target apps in `%s': %s",
                          "', `".join(opts.apps), install_rdf.path,
                          ", ".join([repr(ta.app) for ta
                                     in install_rdf.targetApplications]))
                return 1
        else:
            target_apps = set([ta for ta in install_rdf.targetApplications])

        actions.devinstall(install_rdf, target_apps, force=opts.force, 
                           dry_run=opts.dry_run)




#!/usr/bin/env python
# Copyright (c) 2006 ActiveState Software Inc.
# License: TODO don't know yet
# Contributors:
#   Trent Mick (TrentM@ActiveState.com)

r"""A Python interface to the flickr API [1].

This file provides both module and command-line interfaces [2].

TODO: describe module usage


Typical Usage of RawFlickrAPI
=============================

    >>> from flickrapi import RawFlickrAPI
    >>> api = RawFlickrAPI(api_key=API_KEY, secret=SECRET)

Test to see if your API_KEY and the basics are working.

    >>> api.call("flickr.test.echo")
    <?xml version="1.0" encoding="utf-8" ?>
    <rsp stat="ok">
    <api_key>API_KEY</api_key>
    <method>flickr.test.echo</method>
    </rsp>


Getting an Authorization Token
------------------------------

Most API methods require authorization, i.e. you'll need a "token".
Here is an example of authorizing with "read" permissions as per
http://www.flickr.com/services/api/auth.spec.html section 4 (i.e. as
appropriate for non-web apps).

    >>> api.call("flickr.auth.getFrob", perms="read")
    <?xml version="1.0" encoding="utf-8" ?>
    <rsp stat="ok">
    <frob>FROB</frob>
    </rsp>

Use the retuned frob to open an appropriate Flickr authorization page in
the users browser. "RawFlickrAPI" provides a helper to do this.
(Alternatively, if you want to fully control opening this URL in the
user's browser, then you can use `api.helper_auth_getAuthURL()'.

    >>> api.helper_auth_openAuthURL(frob="FROB", perms="read")

For most browsers this will return right away. However, you must wait
for the user to authorize in their browser before proceeding.

    >>> raw_input("Press <Return> when you've finished authorizing...")

Now get the authorization token.

    >>> api.call("flickr.auth.getToken", frob="FROB")
    <?xml version="1.0" encoding="utf-8" ?>
    <rsp stat="ok">
    <auth>
            <token>AUTH_TOKEN</token>
            <perms>read</perms>
            <user nsid="12345679@N00" username="Bees" fullname="Cal H" />
    </auth>
    </rsp>

Store this auth token for subsequent usage (include separate runs of
your app). Auth tokens may expire so you'll have to check that it is
still valid on subsequent runs:

    >>> api.call("flickr.auth.checkToken", auth_token=AUTH_TOKEN)
    <?xml version="1.0" encoding="utf-8" ?>
    <rsp stat="ok">
    <auth>
            <token>AUTH_TOKEN</token>
            <perms>read</perms>
            <user nsid="12345679@N00" username="Bees" fullname="Cal H" />
    </auth>
    </rsp>


Once you are Authorized
-----------------------

Now, with your API_KEY, SECRET and AUTH_TOKEN you can call all the
flickr API methods for your level of perms. For example:

    >>> api.call("flickr.photos.getContactsPhotos",
                 single_photo=1)
    <?xml version="1.0" encoding="utf-8" ?>
    <rsp stat="ok">
    <photos>
            <photo id="1234" secret="abcd" server="123" farm="1"
                   owner="12345678@N00" username="annie_leibowitz"
                   title="16-04-14" />
            ...
    </photos>
    </rsp>


Acknowledgements
================

Some of this interface is inspired by Beej Jorgensen's
FlickrAPI (http://beej.us/flickr/flickrapi/).


[1] See http://flickr.com/services/api/ for details on the API.
[2] The command-line interface requires the cmdln.py module from:
    http://trentm.com/projects/cmdln/
"""

__revision__ = "$Id$"
__version_info__ = (0, 1, 0)
__version__ = '.'.join(map(str, __version_info__))

import os
from os.path import expanduser, exists, join, normpath
import sys
import getopt
import stat
import logging
import webbrowser
import datetime
from pprint import pprint
import re
import warnings
import urllib
import copy

# Import ElementTree (needed for any by the "raw" interface).
try:
    import xml.etree.ElementTree as ET # in python >=2.5
except ImportError:
    try:
        import cElementTree as ET
    except ImportError:
        try:
            import elementtree.ElementTree as ET
        except ImportError:
            try:
                import lxml.etree as ET
            except ImportError:
                warnings.warn("could not import ElementTree "
                              "(http://effbot.org/zone/element-index.htm) "
                              "required for anything but the 'raw' Flickr "
                              "Python API")



#---- globals

log = logging.getLogger("flickrapi")



#---- exceptions

class FlickrAPIError(Exception):
    """Base-class for Flickr API errors."""

#TODO: other exceptions



#---- the raw Flickr API

        

class RawFlickrAPI(object):
    def __init__(self, api_key=None, secret=None):
        self.api_key = api_key
        self.secret = secret
        #TODO: take as arg what response form to use, default 'rest'

#	flickrHost = "api.flickr.com"
#	flickrRESTForm = "/services/rest/"
#	flickrAuthForm = "/services/auth/"
#	flickrUploadForm = "/services/upload/"

    def _api_sig_from_args(self, args):
        """Determine a Flickr method call api_sig as per
        http://www.flickr.com/services/api/auth.spec.html#signing
        """
        from md5 import md5
        if self.secret is None:
            raise FlickrAPIError("shared secret is not set: use 'secret' "
                                 "argument to RawFlickrAPI contructor")
        arg_items = args.items()
        arg_items.sort()
        s = self.secret + ''.join((k+str(v)) for k,v in sorted(args.items()))
        return md5(s).hexdigest()

    def unsigned_call(self, method, **args):
        """Call a Flickr API method without signing."""
        assert '_' not in method, \
            "%r: illegal method, use the read *dotted* method names" % method
        assert method.startswith("flickr."), \
            "%r: illegal method, doesn't start with 'flickr.'" % method
        url = "http://api.flickr.com/services/rest/"
        args["method"] = method
        if "api_key" not in args and self.api_key is not None:
            args["api_key"] = self.api_key
        post_data = urllib.urlencode(args) 
        log.debug("call url: %r", url)
        log.debug("call post data: %r", post_data)
        f = urllib.urlopen(url, post_data)
        try:
            return f.read()
        finally:
            f.close()

    def call(self, method, **kwargs):
        """Call a Flickr API method with signing.
        http://www.flickr.com/services/api/auth.spec.html#signing
        """
        assert '_' not in method, \
            "%r: illegal method, use the read *dotted* method names" % method
        assert method.startswith("flickr."), \
            "%r: illegal method, doesn't start with 'flickr.'" % method
        url = "http://api.flickr.com/services/rest/"
        args = copy.copy(kwargs) 
        args["method"] = method
        if "api_key" not in args and self.api_key is not None:
            args["api_key"] = self.api_key
        args["api_sig"] = self._api_sig_from_args(args) # sign
        post_data = urllib.urlencode(args)
        log.debug("call url: %r", url)
        log.debug("call post data: %r", post_data)
        f = urllib.urlopen(url, post_data)
        try:
            return f.read()
        finally:
            f.close()

    def helper_auth_getAuthURL(self, frob, perms):
        assert perms in ("read", "write", "delete"), \
            "invalid 'perms' value: %r" % perms
        auth_url = "http://flickr.com/services/auth/"
        args = {"api_key": self.api_key, 
                "perms": perms,
                "frob": frob}
        args["api_sig"] = self._api_sig_from_args(args)
        return "http://flickr.com/services/auth/?" + urllib.urlencode(args)

    def helper_auth_openAuthURL(self, frob, perms):
        auth_url = self.helper_auth_getAuthURL(frob, perms)
        log.debug("opening auth URL in default browser: '%s'", auth_url)
        webbrowser.open_new(auth_url)


#				postData = urllib.urlencode(arg) + "&api_sig=" + \
#					_self.__sign(arg)
#				#print "--url---------------------------------------------"
#				#print url
#				#print "--postData----------------------------------------"
#				#print postData
#				f = urllib.urlopen(url, postData)
#				data = f.read()
#				#print "--response----------------------------------------"
#				#print data
#				f.close()
#				return XMLNode.parseXML(data, True)
#
#			self.__handlerCache[method] = handler;
#
#		return self.__handlerCache[method]
    
#	def __sign(self, data):
#		"""Calculate the flickr signature for a set of params.
#
#		data -- a hash of all the params and values to be hashed, e.g.
#		        {"api_key":"AAAA", "auth_token":"TTTT"}
#
#		"""
#		dataName = self.secret
#		keys = data.keys()
#		keys.sort()
#		for a in keys: dataName += (a + data[a])
#		#print dataName
#		hash = md5.new()
#		hash.update(dataName)
#		return hash.hexdigest()

    def getKeyForUser(self):
        url = self._url_from_method_and_args("getKeyForUser")
        webbrowser.open(url)

    def test_Ping(self):
        return self._api_call("test.Ping", api_key=self.api_key)

    def user_FindByEmail(self, email):
        return self._api_call("user.FindByEmail", email=email,
                              api_key=self.api_key)

    def user_FindById(self, id):
        return self._api_call("user.FindById", id=id, api_key=self.api_key)

    def user_Authorize(self, applicationName, applicationLogoUrl=None,
                       returnUrl=None):
        url = self._url_from_method_and_args("user.Authorize",
                applicationName=applicationName,
                applicationLogoUrl=applicationLogoUrl,
                returnUrl=returnUrl,
                api_key=self.api_key)
        webbrowser.open(url)

    def user_GetAllInfo(self):
        """Get all info on the authorized user.
        
        See user_Authorize for getting an 'authorizedUserToken'. 
        """
        return self._api_call("user.GetAllInfo",
                              authorizedUserToken=self.authorizedUserToken,
                              api_key=self.api_key)

    def events_Get(self, start=None, end=None):
        """Get all events in the given date range.

        See user_Authorize for getting an 'authorizedUserToken'. 
        """
        return self._api_call("events.Get",
                              start=start,
                              end=end,
                              authorizedUserToken=self.authorizedUserToken,
                              api_key=self.api_key)

    def events_Search(self, query):
        """Return all events matching the given query.

        See user_Authorize for getting an 'authorizedUserToken'. 
        """
        return self._api_call("events.Search",
                              query=query,
                              authorizedUserToken=self.authorizedUserToken,
                              api_key=self.api_key)

    def events_TagSearch(self, tag):
        """Return all events tagged with the given tag.

        See user_Authorize for getting an 'authorizedUserToken'. 
        """
        return self._api_call("events.TagSearch",
                              tag=tag,
                              authorizedUserToken=self.authorizedUserToken,
                              api_key=self.api_key)

    def _api_call(self, method, **args):
        url = self._url_from_method_and_args(method, **args)
        log.debug("call `%s'", url)
        f = urlopen(url)
        xml_response = f.read()
        return xml_response

    def _url_from_method_and_args(self, method, **args):
        from urllib import quote
        url = API_URL + "?method=%s" % method
        for name, value in args.items():
            if value is not None:
                url += "&%s=%s" % (quote(str(name)), quote(str(value)))
        return url



#---- the command-line interface

if __name__ == "__main__":
    import cmdln # need cmdln.py from http://trentm.com/projects/cmdln/ for cmdln iface

    class Shell(cmdln.Cmdln):
        """Flickr Python API command-line interface

        usage:
            ${name} SUBCOMMAND [ARGS...]
            ${name} help SUBCOMMAND

        ${option_list}
        ${command_list}
        ${help_list}

        Mostly this command-line interface is for playing and getting
        used to the API.

        TODO: Quick-start guide for playing.
        """
        name = "flickr"
        _api_cache = None

        def _api_key_from_file(self):
            path = normpath(expanduser("~/.flickr/API_KEY"))
            try:
                return open(path, 'r').read().strip()
            except EnvironmentError:
                return None

        def _secret_from_file(self):
            path = normpath(expanduser("~/.flickr/SECRET"))
            try:
                return open(path, 'r').read().strip()
            except EnvironmentError:
                return None

        @property
        def api(self):
            if self._api_cache is None:
                api_key = self.options.api_key or self._api_key_from_file()
                secret = self.options.secret or self._secret_from_file()
                self._api_cache = RawFlickrAPI(api_key, secret)
            return self._api_cache

        @cmdln.alias("echo", "ping")
        def do_test_echo(self, subcmd, opts):
            """ping the Flickr API

            ${cmd_usage}
            ${cmd_option_list}
            """
            response = self.api.unsigned_call("flickr.test.echo")
            assert self.options.output_format == "raw"
            sys.stdout.write(response)
            if not response.endswith('\n'):
                sys.stdout.write('\n')

        def do_test_login(self, subcmd, opts):
            """test if you are logged in

            ${cmd_usage}
            ${cmd_option_list}
            """
            response = self.api.call("flickr.test.login")
            assert self.options.output_format == "raw"
            sys.stdout.write(response)
            if not response.endswith('\n'):
                sys.stdout.write('\n')

        def do_auth_getFrob(self, subcmd, opts, perms):
            """flickr.auth.getFrob

            ${cmd_usage}
            ${cmd_option_list}

            PERMS must be one of "read", "write" or "delete".
            """
            response = self.api.call("flickr.auth.getFrob", perms=perms)
            assert self.options.output_format == "raw"
            sys.stdout.write(response)
            if not response.endswith('\n'):
                sys.stdout.write('\n')

        @cmdln.alias("openAuthURL")
        def do_helper_auth_openAuthURL(self, subcmd, opts, frob, perms):
            """Open authorization URL in the default browser.
            
            ${cmd_usage}
            ${cmd_option_list}

            Helper to open the authorization URL for a the given frob
            and perms as per
            http://www.flickr.com/services/api/auth.spec.html section 4
            (Authentication for non-web based applications). The FROB is
            from a call to 'auth_getFrob' and PERMS must be the same as
            to 'auth_getFrob'.
            """
            return self.api.helper_auth_openAuthURL(frob, perms)

        def do_auth_getToken(self, subcmd, opts, frob):
            """Get an auth token for the given frob (flickr.auth.getToken).
            
            ${cmd_usage}
            ${cmd_option_list}
            """
            response = self.api.call("flickr.auth.getToken", frob=frob)
            sys.stdout.write(response)

        def do_auth_checkToken(self, subcmd, opts, auth_token):
            """Check that your auth token is still valid.
            
            ${cmd_usage}
            ${cmd_option_list}
            """
            response = self.api.call("flickr.auth.checkToken",
                                     auth_token=auth_token)
            sys.stdout.write(response)

        def do_play(self, subcmd, opts, auth_token):
            response = self.api.call("flickr.photos.getContactsPhotos",
                                     auth_token=auth_token,
                                     single_photo=1)
            sys.stdout.write(response)

        def do_methods(self, subcmd, opts):
            response = self.api.call("flickr.reflection.getMethods")
            sys.stdout.write(response)

        def do_method_info(self, subcmd, opts, method_name):
            response = self.api.call("flickr.reflection.getMethodInfo",
                                     method_name=method_name)
            sys.stdout.write(response)


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
        log.setLevel(logging.INFO)


    _setup_logging() # defined in recipe:pretty_logging

    try:
        shell = Shell()
        optparser = cmdln.CmdlnOptionParser(shell,
            version=Shell.name+" "+__version__)
        optparser.add_option("-v", "--verbose", action="callback",
            callback=lambda opt, o, v, p: log.setLevel(logging.DEBUG),
            help="more verbose output")
        optparser.add_option("-q", "--quiet", action="callback",
            callback=lambda opt, o, v, p: log.setLevel(logging.WARNING),
            help="quieter output")
        optparser.add_option("-R", "--raw", action="store_const",
            dest="output_format", const="raw",
            help="print the raw response")
        optparser.add_option("-k", "--api-key", 
            help="specify your API key (or '~/.flickr/API_KEY' content "
                 "is used)")
        optparser.add_option("-s", "--secret", 
            help="specify your shared secret (or '~/.flickr/SECRET' content "
                 "is used)")
        optparser.set_defaults(api_key=None, output_format="raw")
        retval = shell.main(sys.argv, optparser=optparser)
    except KeyboardInterrupt:
        sys.exit(1)
    except:
        exc_info = sys.exc_info()
        if hasattr(exc_info[0], "__name__"):
            log.error("%s", exc_info[1])
        else:  # string exception
            log.error(exc_info[0])
        if log.isEnabledFor(logging.DEBUG):
            import traceback
            print
            traceback.print_exception(*exc_info)
        sys.exit(1)
    else:
        sys.exit(retval)




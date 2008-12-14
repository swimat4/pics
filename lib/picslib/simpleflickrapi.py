#!/usr/bin/env python
# Copyright (c) 2006-2008 ActiveState Software Inc.

r"""A Python interface to the flickr API [1].

Usage
=====

TODO


Acknowledgements
================

Some of this interface is inspired by Beej Jorgensen's
FlickrAPI (http://beej.us/flickr/flickrapi/).


[1] See http://flickr.com/services/api/ for details on the API.
"""

__version_info__ = (0, 2, 0)
__version__ = '.'.join(map(str, __version_info__))

import os
from os.path import expanduser, exists, join, normpath, dirname
import sys
import getopt
import stat
import logging
import webbrowser
from datetime import datetime
from pprint import pprint, pformat
import re
import warnings
import threading
import urllib
import cPickle as pickle
import copy
import types
import time
try:
    from hashlib import md5
except ImportError:
    from md5 import md5

import xml.etree.ElementTree as ET # in python >=2.5



#---- globals

log = logging.getLogger("pics")



#---- exceptions

class FlickrAPIError(Exception):
    """Base-class for Flickr API errors."""
    def __init__(self, msg, code=None):
        Exception.__init__(self, msg)
        self.msg = msg
        self.code = code
    def __str__(self):
        if self.code is not None:
            return "[err %d] %s" % (self.code, self.msg)
        else:
            return Exception.__str__(self)


#---- the raw Flickr API

class AuthTokenMixin(object):
    """A mixin for SimpleFlickrAPI that adds `.get_auth_token(...)` -- a
    helper for getting a (possibly cached) auth token for using any of the
    Flickr API methods that require signing, i.e. all the interesting ones.

    (Derived from beej's FlickrAPI module.)
    """
    auth_token = None

    _lock = threading.Lock()
    #TODO: Windows-ify
    _auth_token_cache_path = expanduser("~/.simpleflickrapi/auth_token.cache")
    def _load_token_cache(self):
        if not exists(self._auth_token_cache_path):
            return {}
        f = open(self._auth_token_cache_path, 'rb')
        try:
            return pickle.load(f)
        except EOFError:  # corrupted cache file
            return {}
        finally:
            f.close()
    def _save_token_cache(self, cache):
        d = dirname(self._auth_token_cache_path)
        if not exists(d):
            os.makedirs(d)
        f = open(self._auth_token_cache_path, 'wb')
        try:
            pickle.dump(cache, f)
        finally:
            f.close()
    def _get_cached_token(self, perms):
        key = (self.api_key, perms)
        cache = self._load_token_cache()
        return cache.get(key)
    def _del_cached_token(self, perms):
        key = (self.api_key, perms)
        cache = self._load_token_cache()
        if key in cache:
            del cache[key]
        self._save_token_cache(cache)
    def _set_cached_token(self, perms, auth_token):
        key = (self.api_key, perms)
        cache = self._load_token_cache()
        cache[key] = auth_token
        self._save_token_cache(cache)

    def _get_auth_url(self, frob, perms):
        assert perms in ("read", "write", "delete"), \
            "invalid 'perms' value: %r" % perms
        args = {"api_key": self.api_key, 
                "perms": perms,
                "frob": frob}
        args["api_sig"] = self._api_sig_from_args(args)
        #TODO: should that be api.flickr.com as in beej's flickrapi.py!?
        return "http://flickr.com/services/auth/?" + urllib.urlencode(args)

    def get_auth_token(self, perms="read", exact_perms=True):
        """Get an authorization token.
        
        First attempts to find one locally cached. If found it is
        validated with `auth_checkToken()`. If not found, or if invalid,
        then:
        
        1. Gets a new frob with `auth_getFrob()`.
        2. Opens the default browser to validate the frob.
        3. Gets the auth token via `auth_getToken()`.
        4. Caches it for next time.

        @param perms {str} One of "read", "write", or "delete".
        @param exact_perms {boolean} Whether to require that a cached
            token have the exact perms requested to be used. If False
            then a request for "read" perms will use a cached token with
            "write" perms if it exists. Default True.
        """
        if not exact_perms:
            #TODO: handle exact_perms == False
            ordered_perms = ["read", "write", "delete"]
            raise FlickrAPIError("'exact_perms == False' not implemented")

        # Look for a sufficient auth token in the cache.
        auth_token = self._get_cached_token(perms)

        # see if it's valid
        if auth_token is not None:
            try:
                rsp = self.call("flickr.auth.checkToken",
                    auth_token=auth_token, 
                    response_format_="etree",
                    raise_on_api_error_=True)
            except FlickrAPIError:
                self._del_cached_token(perms)
                auth_token = None

        # get a new token if we need one
        if auth_token is None:
            rsp = self.call("flickr.auth.getFrob",
                response_format_="etree",
                raise_on_api_error_=True)
            frob = rsp[0].text
            #print "XXX frob", frob

            # Validate online.
            url = self._get_auth_url(frob, perms)
            webbrowser.open_new(url)
            #print "XXX auth url:", url
            raw_input(
                "* * *\n"
                "Requesting '%s' permission to your Flickr photos in\n"
                "your browser. Press <Return> when you've finished authorizing.\n"
                "* * *" % perms)

            rsp = self.call("flickr.auth.getToken",
                frob=frob,
                response_format_="etree",
                raise_on_api_error_=True)
            #from picslib.utils import xpprint
            #xpprint(rsp)
            auth_token = rsp[0].find("token").text
            #print "XXX auth_token", auth_token
            self._set_cached_token(perms, auth_token)

        self.auth_token = auth_token    # remember for subsequent API usage
        return auth_token

class SimpleFlickrAPI(AuthTokenMixin):
    # What form to return an API response:
    #   etree       ElementTree of XML response (default)
    #   raw         raw XML response
    response_format = "etree"
    # Whether to raise a FlickrAPIError on an error response.
    # This option is only used when `response_format != 'raw'`.
    raise_on_api_error = True

    def __init__(self, api_key=None, secret=None):
        self.api_key = api_key
        self.secret = secret
        #TODO: take as arg what response form to use, default 'rest'

    def _api_sig_from_args(self, args):
        """Determine a Flickr method call api_sig as per
        http://www.flickr.com/services/api/auth.spec.html#signing
        """
        if self.secret is None:
            raise FlickrAPIError("shared secret is not set: use 'secret' "
                                 "argument to SimpleFlickrAPI constructor")
        arg_items = args.items()
        arg_items.sort()
        s = self.secret + ''.join((k+str(v)) for k,v in sorted(args.items()))
        return md5(s).hexdigest()

    def raw_unsigned_call(self, method, **kwargs):
        """Call a Flickr API method without signing."""
        assert '_' not in method, \
            "%r: illegal method, use the read *dotted* method names" % method
        assert method.startswith("flickr."), \
            "%r: illegal method, doesn't start with 'flickr.'" % method
        url = "http://api.flickr.com/services/rest/"
        args = dict((k,v) for k,v in kwargs.iteritems() if v is not None)
        args["method"] = method
        if "auth_token" not in args and self.auth_token is not None:
            args["auth_token"] = self.auth_token
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

    def raw_call(self, method, **kwargs):
        """Call a Flickr API method with signing.
        http://www.flickr.com/services/api/auth.spec.html#signing
        """
        assert '_' not in method, \
            "%r: illegal method, use the read *dotted* method names" % method
        assert method.startswith("flickr."), \
            "%r: illegal method, doesn't start with 'flickr.'" % method
        url = "http://api.flickr.com/services/rest/"
        args = dict((k,v) for k,v in kwargs.iteritems() if v is not None)
        args["method"] = method
        if "auth_token" not in args and self.auth_token is not None:
            args["auth_token"] = self.auth_token
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

    def call(self, method_name_, response_format_=None,
             raise_on_api_error_=None, **args):
        rsp = self.raw_call(method_name_, **args)
        return self._handle_rsp(rsp, response_format=response_format_,
                                raise_on_api_error=raise_on_api_error_)
    def unsigned_call(self, method_name_, response_format_=None, 
                      raise_on_api_error_=None, **args):
        rsp = self.raw_unsigned_call(method_name_, **args)
        return self._handle_rsp(rsp, response_format=response_format_,
                                raise_on_api_error=raise_on_api_error_)

    def _handle_rsp(self, rsp, response_format=None, raise_on_api_error=None):
        response_format = response_format or self.response_format
        raise_on_api_error = raise_on_api_error or self.raise_on_api_error
        if response_format == "raw":
            return rsp
        else:
            assert response_format == "etree", (
                "unexpected response_format: %r" % response_format)
            rsp_elem = ET.fromstring(rsp)
            assert rsp_elem.tag == "rsp"
            stat = rsp_elem.get("stat")
            if stat == "ok" or not raise_on_api_error:
                return rsp_elem
            elif stat == "fail":
                err_elem = rsp_elem[0]
                raise FlickrAPIError(err_elem.get("msg"), int(err_elem.get("code")))
            else:
                raise FlickrAPIError("unexpected <rsp> stat: %r" % stat)

    def paging_call(self, method_name_, response_format_=None,
                    raise_on_api_error_=None, **args):
        """A version of `.call(...)' that handles paging of results for the
        particular Flickr API methods that return pages. Yields each
        individual item.
        """
        page = args.get("page", 1)
        num_pages = None
        while num_pages is None or page < num_pages:
            log.debug("paging_call: page=%r", page)
            args["page"] = page
            rsp = self.call(method_name_, response_format_,
                            raise_on_api_error_, **args)
            container = rsp[0]
            if num_pages is None:
                num_pages = int(container.get("pages"))
                log.debug("paging_call: num_pages=%r", num_pages)
            for item in container:
                yield item
            page += 1

    _handler_cache = None
    def __getattr__(self, name):
        """Handle all the flickr API calls.

        From http://beej.us/flickr/flickrapi/
        ... from http://micampe.it/things/flickrclient

        TODO: api_key, secret and auth_token handling? Update example
            usage here with that info.

        example usage:
            rsp = flickr.auth_getFrob()
            rsp = flickr.favorites_getList(auth_token=auth_token)
        """
        if name.startswith("_"):
            raise AttributeError("type %s has no attribute '%s'"
                                 % (type(self).__name__, name))
        method_name_ = "flickr." + name.replace("_", ".")
        if self._handler_cache is None:
            self._handler_cache = {}
        #TODO: Could we not just cache on self.__dict__?
        if method_name_ not in self._handler_cache:
            def handler(self_=self, method_name_=method_name_, **args):
                # Note: Just making signed call everytime. Doesn't hurt.
                return self_.call(method_name_, **args)
            self._handler_cache[method_name_] = handler
        return self._handler_cache[method_name_]

    #TODO: change name
    def helper_auth_getAuthURL(self, frob, perms):
        assert perms in ("read", "write", "delete"), \
            "invalid 'perms' value: %r" % perms
        auth_url = "http://flickr.com/services/auth/"
        args = {"api_key": self.api_key, 
                "perms": perms,
                "frob": frob}
        args["api_sig"] = self._api_sig_from_args(args)
        #TODO: should that be api.flickr.com as in beej's flickrapi.py!?
        return "http://flickr.com/services/auth/?" + urllib.urlencode(args)

    #TODO: change name
    def helper_auth_openAuthURL(self, frob, perms):
        auth_url = self.helper_auth_getAuthURL(frob, perms)
        log.debug("opening auth URL in default browser: '%s'", auth_url)
        webbrowser.open_new(auth_url)


#class FlickrAPI(object):
#    def __init__(self, api_key, secret, auth_token=None):
#        self._api = ElementFlickrAPI(api_key, secret, auth_token)
#
#    def photos_recentlyUpdated(self, min_date, extras=None,
#                               per_page=None, page=None):
#        timestamp = int(_timestamp_from_datetime(min_date))
#        if extras is not None and not isinstance(extras, basestring):
#            extras = ','.join(e for e in extras)
#
#        if page is not None:
#            for photo in self._api.photos_recentlyUpdated(
#                    min_date=timestamp, extras=extras,
#                    page=page, per_page=per_page)[0]:
#                yield Photo.from_elem(photo)
#        else:
#            page = 1
#            num_pages = None
#            while num_pages is None or page < num_pages:
#                photos = self._api.photos_recentlyUpdated(
#                        min_date=timestamp, extras=extras,
#                        page=page, per_page=per_page)[0]
#                if num_pages is None:
#                    num_pages = int(photos.get("pages"))
#                for photo in photos:
#                    yield Photo.from_elem(photo)
#                page += 1



#---- internal support stuff

if sys.version_info[:2] == (2, 5):
    _datetime_strptime = datetime.strptime
else:
    def _datetime_strptime(date_string, format):
        return datetime(*(time.strptime(date_string, format)[0:6]))

def _datetime_from_timestamp_and_granularity(timestamp, granularity="0"):
    format = {
        # See http://www.flickr.com/services/api/misc.dates.html
        "0": "%Y-%m-%d %H:%M:%S",
        "4": "%Y-%m",
        "6": "%Y",
    }[granularity]
    return _datetime_strptime(timestamp, format)

def _timestamp_from_datetime(dt):
    return time.mktime(dt.timetuple())


#---- the command-line interface

if __name__ == "__main__":
    def main(argv):
        import optparse
        usage = "usage: %prog <method-name> [<args...>]"
        version = "%prog "+__version__
        description = _dedent("""
            Where <method-name> is the full ("flickr.test.echo") or
            abbreviated ("test.echo") method name. <args> are given as
            NAME=VALUE pairs (in any order). Note that 'api_key' and
            'secret' are read from ~/.flickr, so no need to specify
            them.
        """)
        parser = optparse.OptionParser(prog="flickrapi",
                                       usage=usage, 
                                       version=version,
                                       description=description)
        parser.add_option("-v", "--verbose", dest="log_level",
                          action="store_const", const=logging.DEBUG,
                          help="more verbose output")
        parser.add_option("-q", "--quiet", dest="log_level",
                          action="store_const", const=logging.WARNING,
                          help="quieter output")
        parser.set_defaults(log_level=logging.INFO)
        opts, args = parser.parse_args()
        log.setLevel(opts.log_level)

        method_name = args[0]
        if not method_name.startswith("flickr."):
            method_name = "flickr."+method_name
        method_args, method_kwargs = [], {}
        for arg in args[1:]:
            if '=' in arg:
                key, value = arg.split('=', 1)
                if re.match(r"\d{4}-\d{2}-\d{2}", value):
                    value = _datetime_strptime(value, "%Y-%m-%d")
                method_kwargs[key] = value
            else:
                if re.match(r"\d{4}-\d{2}-\d{2}", arg):
                    arg = _datetime_strptime(arg, "%Y-%m-%d")
                method_args.append(arg)
        api_key = _api_key_from_file()
        secret = _secret_from_file()
        API = "python"
        #TODO: try "python" API and fallback to "element" if not impl?
        if API == "raw":
            api = RawFlickrAPI(api_key, secret)
            rsp = api.call(method_name, *method_args, **method_kwargs)
            sys.stdout.write(rsp)
        elif API == "element":
            auth_token = open(expanduser("~/.flickr/AUTH_TOKEN"))\
                         .read().strip() #HACK
            api = ElementFlickrAPI(api_key, secret, auth_token)
            api_method_name = method_name[len("flickr."):].replace('.', '_')
            rsp = getattr(api, api_method_name)(*method_args, **method_kwargs)
            ET.dump(rsp)
        else:
            auth_token = open(expanduser("~/.flickr/AUTH_TOKEN"))\
                         .read().strip() #HACK
            api = FlickrAPI(api_key, secret, auth_token)
            api_method_name = method_name[len("flickr."):].replace('.', '_')
            rsp = getattr(api, api_method_name)(*method_args, **method_kwargs)
            if isinstance(rsp, types.GeneratorType):
                pprint(list(rsp))
            else:
                pprint(rsp)


    _setup_logging() # defined in recipe:pretty_logging
    try:
        retval = main(sys.argv) 
    except SystemExit:
        raise
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




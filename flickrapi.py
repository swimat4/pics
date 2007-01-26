#!/usr/bin/env python
# Copyright (c) 2006 ActiveState Software Inc.
# License: TODO don't know yet
# Contributors:
#   Trent Mick (TrentM@ActiveState.com)

r"""A Python interface to the flickr API [1].

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


TODO: describe the richer API classes


Acknowledgements
================

Some of this interface is inspired by Beej Jorgensen's
FlickrAPI (http://beej.us/flickr/flickrapi/).


[1] See http://flickr.com/services/api/ for details on the API.
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
    def __init__(self, msg):
        Exception.__init__(self, msg)
        self.msg = msg
    def __str__(self):
        if hasattr(self, "code"):
            return "[err %d] %s" % (self.code, self.msg)
        else:
            return Exception.__str__(self)

#[[[cog
#   import cog
#   from os.path import expanduser
#   import flickrapi
#   import elementtree.ElementTree as ET
#   from pprint import pprint
#   from textwrap import wrap
#   DEBUG = True
#
#   api = flickrapi.RawFlickrAPI(
#       open(expanduser("~/.flickr/API_KEY")).read().strip(),
#       open(expanduser("~/.flickr/SECRET")).read().strip(),
#   )
#
#   methods = ET.fromstring(api.call("flickr.reflection.getMethods"))
#   error_info = {}
#   for api_meth_name in (el.text for el in methods[0]):
#       if DEBUG and "test" not in api_meth_name: continue
#       meth_rsp = ET.fromstring(
#           api.call("flickr.reflection.getMethodInfo",
#                    method_name=api_meth_name)
#       )
#       for error_elem in meth_rsp[2]:
#           error_info[int(error_elem.get("code"))] \
#               = (error_elem.get("message"), error_elem.text)
#   for code, (msg, desc) in sorted(error_info.items()):
#       cog.outl('class Flickr%dAPIError(FlickrAPIError):' % code)
#       cog.outl('    """%s' % msg)
#       cog.outl('    %s' % '\n    '.join(wrap(desc, 60)))
#       cog.outl('    """')
#       cog.outl('    code = %d' % code)
#]]]
class Flickr96APIError(FlickrAPIError):
    """Invalid signature
    The passed signature was invalid.
    """
    code = 96
class Flickr97APIError(FlickrAPIError):
    """Missing signature
    The call required signing but no signature was sent.
    """
    code = 97
class Flickr98APIError(FlickrAPIError):
    """Login failed / Invalid auth token
    The login details or auth token passed were invalid.
    """
    code = 98
class Flickr99APIError(FlickrAPIError):
    """User not logged in / Insufficient permissions
    The method requires user authentication but the user was not
    logged in, or the authenticated method call did not have the
    required permissions.
    """
    code = 99
class Flickr100APIError(FlickrAPIError):
    """Invalid API Key
    The API key passed was not valid or has expired.
    """
    code = 100
class Flickr105APIError(FlickrAPIError):
    """Service currently unavailable
    The requested service is temporarily unavailable.
    """
    code = 105
class Flickr111APIError(FlickrAPIError):
    """Format "xxx" not found
    The requested response format was not found.
    """
    code = 111
class Flickr112APIError(FlickrAPIError):
    """Method "xxx" not found
    The requested method was not found.
    """
    code = 112
class Flickr114APIError(FlickrAPIError):
    """Invalid SOAP envelope
    The SOAP envelope send in the request could not be parsed.
    """
    code = 114
class Flickr115APIError(FlickrAPIError):
    """Invalid XML-RPC Method Call
    The XML-RPC request document could not be parsed.
    """
    code = 115
#[[[end]]]




#---- the raw Flickr API

        

class RawFlickrAPI(object):
    def __init__(self, api_key=None, secret=None):
        self.api_key = api_key
        self.secret = secret
        #TODO: take as arg what response form to use, default 'rest'

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

    def unsigned_call(self, method, **kwargs):
        """Call a Flickr API method without signing."""
        assert '_' not in method, \
            "%r: illegal method, use the read *dotted* method names" % method
        assert method.startswith("flickr."), \
            "%r: illegal method, doesn't start with 'flickr.'" % method
        url = "http://api.flickr.com/services/rest/"
        args = dict((k,v) for k,v in kwargs.iteritems() if v is not None)
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
        args = dict((k,v) for k,v in kwargs.iteritems() if v is not None)
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


class ElementFlickrAPI(object):
    def __init__(self, api_key, secret, auth_token=None):
        self.api_key = api_key
        self.secret = secret
        self.auth_token = auth_token

    @property
    def _api(self):
        if self._api_cache is None:
            self._api_cache = RawFlickrAPI(self.api_key, self.secret)
        return self._api_cache
    _api_cache = None

    def _exc_from_err_elem(self, err_elem):
        exc_class = getattr(sys.modules[__name__],
                            "Flickr%sAPIError" % err_elem.get("code"))
        return exc_class(err_elem.get("msg"))

    def _handle_rsp(self, rsp):
        rsp_elem = ET.fromstring(rsp)
        assert rsp_elem.tag == "rsp"
        stat = rsp_elem.get("stat")
        if stat == "ok":
            return rsp_elem
        elif stat == "fail":
            raise self._exc_from_err_elem(rsp_elem[0])
        else:
            raise FlickrAPIError("unexpected <rsp> stat: %r" % stat)

    def _call(self, method_name, **args):
        rsp = self._api.call(method_name, **args)
        return self._handle_rsp(rsp)
    def _unsigned_call(self, method_name, **args):
        rsp = self._api.unsigned_call(method_name, **args)
        return self._handle_rsp(rsp)

    #[[[cog
    #   from operator import itemgetter
    #
    #   # Generate the API methods using Flickr's reflection APIs.
    #   for api_meth_name in (el.text for el in methods[0]):
    #       if DEBUG and not ("test" in api_meth_name
    #                         or "contacts" in api_meth_name):
    #           continue
    #       meth_rsp = ET.fromstring(
    #           api.call("flickr.reflection.getMethodInfo",
    #                    method_name=api_meth_name)
    #       )
    #       meth_name = api_meth_name[len("flickr:"):].replace('.', '_')
    #       cog.out("def %s(self" % meth_name)
    #       call_args = []
    #       for arg_elem in meth_rsp[1]:
    #           arg_name = arg_elem.get("name")
    #           if arg_name in ("api_key",):
    #               #TODO: auth_token? watch auth_checkToken()
    #               continue
    #           if arg_elem.get("optional") == "1":
    #               call_args.append((arg_name, "=None", "="+arg_name))
    #           else:
    #               call_args.append((arg_name, "", "="+arg_name))
    #       if call_args:
    #           call_args.sort(key=itemgetter(1)) # optional args last
    #           cog.out(', ' + ', '.join(a[0]+a[1] for a in call_args))
    #       cog.outl("):")
    #       if meth_rsp[0].get("needslogin") == "1":
    #           call_args.append(("auth_token", "=None", "=self.auth_token"))
    #       if meth_rsp[0].get("needssigning") == "1":
    #           #cog.out( "    rsp = self._api.call('%s'" % api_meth_name)
    #           cog.out( "    return self._call('%s'" % api_meth_name)
    #           indent = "                         "
    #           if call_args:
    #               for a,_,d in call_args:
    #                   cog.out(",\n%s%s%s" % (indent, a, d))
    #           cog.outl(")")
    #       else:
    #           #cog.out( "    rsp = self._api.unsigned_call('%s'" % api_meth_name)
    #           cog.out( "    return self._unsigned_call('%s'" % api_meth_name)
    #           indent = "                                  "
    #           if call_args:
    #               for a,_,d in call_args:
    #                   cog.out(",\n%s%s%s" % (indent, a, d))
    #           cog.outl(")")
    #       #cog.outl("    return self._handle_rsp(rsp)")
    #]]]
    def contacts_getList(self, filter=None, page=None, per_page=None):
        return self._call('flickr.contacts.getList',
                             filter=filter,
                             page=page,
                             per_page=per_page,
                             auth_token=self.auth_token)
    def contacts_getPublicList(self, user_id, page=None, per_page=None):
        return self._unsigned_call('flickr.contacts.getPublicList',
                                      user_id=user_id,
                                      page=page,
                                      per_page=per_page)
    def test_echo(self):
        return self._unsigned_call('flickr.test.echo')
    def test_login(self):
        return self._call('flickr.test.login',
                             auth_token=self.auth_token)
    def test_null(self):
        return self._call('flickr.test.null',
                             auth_token=self.auth_token)
    #[[[end]]]


class FlickrAPI(ElementFlickrAPI):
    """An attempt at a more natural Python wrapper around the return
    values from the Flickr API.

    Basically this class transforms Flickr API results as follows:
    - return dicts and lists where appropriate
    - convert date and time strings to Python datetime instances
    - convert booleans to Python booleans
    - use generators for API methods that return pages results

    Limitations:
    - This requires (at least I think it does) hand coding
      per-API-method so this API class might be incomplete.

    TODO:
    - what about args on the way in (bools to "0" or "1", datetimes to
      the appropriate strings)
    """
    def _pyobj_from_contact(self, contact):
        assert contact.tag == "contact"
        d = contact.attrib
        for n in ("friend", "family", "ignored"):
            if n in d:
                d[n] = bool(int(d[n]))
        return d

    def contacts_getList(self, filter=None, page=None, per_page=None):
        if page is not None:
            for contact in self._call('flickr.contacts.getList',
                    filter=filter, page=page, per_page=per_page,
                    auth_token=self.auth_token)[0]:
                yield self._pyobj_from_contact(contact)
        else:
            page = 1
            num_pages = None
            while num_pages is None or page < num_pages:
                contacts = self._call('flickr.contacts.getList',
                        filter=filter, page=page, per_page=per_page,
                        auth_token=self.auth_token)[0]
                if num_pages is None:
                    num_pages = int(contacts.get("pages"))
                for contact in contacts:
                    yield self._pyobj_from_contact(contact)
                page += 1

    #TODO: flickr.groups.browse a la os.walk()



#---- internal support stuff

# Recipe: indent (0.2.1) in /Users/trentm/tm/recipes/cookbook
def _indent(s, width=4, skip_first_line=False):
    """_indent(s, [width=4]) -> 's' indented by 'width' spaces

    The optional "skip_first_line" argument is a boolean (default False)
    indicating if the first line should NOT be indented.
    """
    lines = s.splitlines(1)
    indentstr = ' '*width
    if skip_first_line:
        return indentstr.join(lines)
    else:
        return indentstr + indentstr.join(lines)



#---- the command-line interface

if __name__ == "__main__":

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

    def _api_key_from_file():
        path = normpath(expanduser("~/.flickr/API_KEY"))
        try:
            return open(path, 'r').read().strip()
        except EnvironmentError:
            return None

    def _secret_from_file():
        path = normpath(expanduser("~/.flickr/SECRET"))
        try:
            return open(path, 'r').read().strip()
        except EnvironmentError:
            return None

    def _dedent(s):
        return ''.join(line.lstrip() for line in s.splitlines(1))

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
        args = dict(a.split('=', 1) for a in args[1:])
        api_key = _api_key_from_file()
        secret = _secret_from_file()
        API = "dict"
        if API == "raw":
            api = RawFlickrAPI(api_key, secret)
            rsp = api.call(method_name, **args)
            sys.stdout.write(rsp)
        elif API == "element":
            auth_token = open(expanduser("~/.flickr/AUTH_TOKEN"))\
                         .read().strip() #HACK
            api = ElementFlickrAPI(api_key, secret, auth_token)
            api_method_name = method_name[len("flickr."):].replace('.', '_')
            rsp = getattr(api, api_method_name)(**args)
            ET.dump(rsp)
        else:
            auth_token = open(expanduser("~/.flickr/AUTH_TOKEN"))\
                         .read().strip() #HACK
            api = DictFlickrAPI(api_key, secret, auth_token)
            api_method_name = method_name[len("flickr."):].replace('.', '_')
            rsp = getattr(api, api_method_name)(**args)
            if hasattr(rsp, "next"): # looks like an iterator
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




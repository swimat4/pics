#!/usr/bin/env python
# Copyright (c) 2006 ActiveState Software Inc.
# License: TODO don't know yet
# Contributors:
#   Trent Mick (TrentM@ActiveState.com)

r"""A Python interface to the flickr API [1].

This file provides both module and command-line interfaces [2].

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
#   DEBUG = False
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
class Flickr1APIError(FlickrAPIError):
    """User not found
    The passed URL was not a valid user profile or photos url.
    """
    code = 1
class Flickr2APIError(FlickrAPIError):
    """No user specified
    No user_id was passed and the calling user was not logged
    in.
    """
    code = 2
class Flickr3APIError(FlickrAPIError):
    """Photo not in set
    The photo is not a member of the photoset.
    """
    code = 3
class Flickr4APIError(FlickrAPIError):
    """Primary photo not in list
    The primary photo id passed did not appear in the photo id
    list.
    """
    code = 4
class Flickr5APIError(FlickrAPIError):
    """Empty photos list
    No photo ids were passed.
    """
    code = 5
class Flickr6APIError(FlickrAPIError):
    """Server error.
    There was an unexpected problem setting location information
    to the photo.
    """
    code = 6
class Flickr7APIError(FlickrAPIError):
    """User has not configured default viewing settings for location data.
    Before users may assign location data to a photo they must
    define who, by default, may view that information. Users can
    edit this preference at <a href="http://www.flickr.com/accou
    nt/geo/privacy/">http://www.flickr.com/account/geo/privacy/<
    /a>
    """
    code = 7
class Flickr8APIError(FlickrAPIError):
    """Blank comment.
    Comment text can't be blank.
    """
    code = 8
class Flickr9APIError(FlickrAPIError):
    """User is posting comments too fast.
    The user has reached the limit for number of comments posted
    during a specific time period. Wait a bit and try again.
    """
    code = 9
class Flickr10APIError(FlickrAPIError):
    """Sorry, the Flickr search API is not currently available.
    The Flickr API search databases are temporarily unavailable
    """
    code = 10
class Flickr11APIError(FlickrAPIError):
    """No valid machine tags
    The query styntax for the machine_tags argument did not
    validate.
    """
    code = 11
class Flickr12APIError(FlickrAPIError):
    """Exceeded maximum allowable machine tags
    The maximum number of machine tags in a single query was
    exceeded.
    """
    code = 12
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
class Flickr108APIError(FlickrAPIError):
    """Invalid frob
    The specified frob does not exist or has already been used.
    """
    code = 108
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
            raise FlickrAPIError("unexpected <rsp> stat attr: %r" % stat)

    #[[[cog
    #   from operator import itemgetter
    #
    #   # Generate the API methods using Flickr's reflection APIs.
    #   for api_meth_name in (el.text for el in methods[0]):
    #       if DEBUG and not ("test" in api_meth_name
    #                         or "create" in api_meth_name):
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
    #               call_args.append((arg_name, "=None"))
    #           else:
    #               call_args.append((arg_name, ""))
    #       if call_args:
    #           call_args.sort(key=itemgetter(1)) # optional args last
    #           cog.out(', ' + ', '.join(a[0]+a[1] for a in call_args))
    #       cog.outl("):")
    #       if meth_rsp[0].get("needslogin") == "1":
    #           call_args.append(("auth_token", "=self.auth_token"))
    #       if meth_rsp[0].get("needssigning") == "1":
    #           cog.out( "    rsp = self._api.call('%s'" % api_meth_name)
    #           indent = "                         "
    #           if call_args:
    #               for a,d in call_args:
    #                   cog.out(",\n%s%s%s" % (indent, a, d))
    #           cog.outl(")")
    #       else:
    #           cog.out( "    rsp = self._api.unsigned_call('%s'" % api_meth_name)
    #           indent = "                                  "
    #           if call_args:
    #               for a,d in call_args:
    #                   cog.out(",\n%s%s%s" % (indent, a, d))
    #           cog.outl(")")
    #       cog.outl("    return self._handle_rsp(rsp)")
    #]]]
    def activity_userComments(self, per_page=None, page=None):
        rsp = self._api.call('flickr.activity.userComments',
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def activity_userPhotos(self, timeframe=None, per_page=None, page=None):
        rsp = self._api.call('flickr.activity.userPhotos',
                             timeframe=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def auth_checkToken(self, auth_token):
        rsp = self._api.unsigned_call('flickr.auth.checkToken',
                                      auth_token)
        return self._handle_rsp(rsp)
    def auth_getFrob(self):
        rsp = self._api.unsigned_call('flickr.auth.getFrob')
        return self._handle_rsp(rsp)
    def auth_getFullToken(self, mini_token):
        rsp = self._api.unsigned_call('flickr.auth.getFullToken',
                                      mini_token)
        return self._handle_rsp(rsp)
    def auth_getToken(self, frob):
        rsp = self._api.unsigned_call('flickr.auth.getToken',
                                      frob)
        return self._handle_rsp(rsp)
    def blogs_getList(self):
        rsp = self._api.call('flickr.blogs.getList',
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def blogs_postPhoto(self, blog_id, photo_id, title, description, blog_password=None):
        rsp = self._api.call('flickr.blogs.postPhoto',
                             blog_id,
                             photo_id,
                             title,
                             description,
                             blog_password=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def contacts_getList(self, filter=None, page=None, per_page=None):
        rsp = self._api.call('flickr.contacts.getList',
                             filter=None,
                             page=None,
                             per_page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def contacts_getPublicList(self, user_id, page=None, per_page=None):
        rsp = self._api.unsigned_call('flickr.contacts.getPublicList',
                                      user_id,
                                      page=None,
                                      per_page=None)
        return self._handle_rsp(rsp)
    def favorites_add(self, photo_id):
        rsp = self._api.call('flickr.favorites.add',
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def favorites_getList(self, user_id=None, extras=None, per_page=None, page=None):
        rsp = self._api.call('flickr.favorites.getList',
                             user_id=None,
                             extras=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def favorites_getPublicList(self, user_id, extras=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.favorites.getPublicList',
                                      user_id,
                                      extras=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def favorites_remove(self, photo_id):
        rsp = self._api.call('flickr.favorites.remove',
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def groups_browse(self, cat_id=None):
        rsp = self._api.call('flickr.groups.browse',
                             cat_id=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def groups_getInfo(self, group_id):
        rsp = self._api.unsigned_call('flickr.groups.getInfo',
                                      group_id)
        return self._handle_rsp(rsp)
    def groups_pools_add(self, photo_id, group_id):
        rsp = self._api.call('flickr.groups.pools.add',
                             photo_id,
                             group_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def groups_pools_getContext(self, photo_id, group_id):
        rsp = self._api.unsigned_call('flickr.groups.pools.getContext',
                                      photo_id,
                                      group_id)
        return self._handle_rsp(rsp)
    def groups_pools_getGroups(self, page=None, per_page=None):
        rsp = self._api.call('flickr.groups.pools.getGroups',
                             page=None,
                             per_page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def groups_pools_getPhotos(self, group_id, tags=None, user_id=None, extras=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.groups.pools.getPhotos',
                                      group_id,
                                      tags=None,
                                      user_id=None,
                                      extras=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def groups_pools_remove(self, photo_id, group_id):
        rsp = self._api.call('flickr.groups.pools.remove',
                             photo_id,
                             group_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def groups_search(self, text, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.groups.search',
                                      text,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def interestingness_getList(self, date=None, extras=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.interestingness.getList',
                                      date=None,
                                      extras=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def people_findByEmail(self, find_email):
        rsp = self._api.unsigned_call('flickr.people.findByEmail',
                                      find_email)
        return self._handle_rsp(rsp)
    def people_findByUsername(self, username):
        rsp = self._api.unsigned_call('flickr.people.findByUsername',
                                      username)
        return self._handle_rsp(rsp)
    def people_getInfo(self, user_id):
        rsp = self._api.unsigned_call('flickr.people.getInfo',
                                      user_id)
        return self._handle_rsp(rsp)
    def people_getPublicGroups(self, user_id):
        rsp = self._api.unsigned_call('flickr.people.getPublicGroups',
                                      user_id)
        return self._handle_rsp(rsp)
    def people_getPublicPhotos(self, user_id, extras=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.people.getPublicPhotos',
                                      user_id,
                                      extras=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def people_getUploadStatus(self):
        rsp = self._api.call('flickr.people.getUploadStatus',
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_addTags(self, photo_id, tags):
        rsp = self._api.call('flickr.photos.addTags',
                             photo_id,
                             tags,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_comments_addComment(self, photo_id, comment_text):
        rsp = self._api.call('flickr.photos.comments.addComment',
                             photo_id,
                             comment_text,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_comments_deleteComment(self, comment_id):
        rsp = self._api.call('flickr.photos.comments.deleteComment',
                             comment_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_comments_editComment(self, comment_id, comment_text):
        rsp = self._api.call('flickr.photos.comments.editComment',
                             comment_id,
                             comment_text,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_comments_getList(self, photo_id):
        rsp = self._api.unsigned_call('flickr.photos.comments.getList',
                                      photo_id)
        return self._handle_rsp(rsp)
    def photos_delete(self, photo_id):
        rsp = self._api.call('flickr.photos.delete',
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_geo_getLocation(self, photo_id):
        rsp = self._api.unsigned_call('flickr.photos.geo.getLocation',
                                      photo_id)
        return self._handle_rsp(rsp)
    def photos_geo_getPerms(self, photo_id):
        rsp = self._api.call('flickr.photos.geo.getPerms',
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_geo_removeLocation(self, photo_id):
        rsp = self._api.call('flickr.photos.geo.removeLocation',
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_geo_setLocation(self, photo_id, lat, lon, accuracy=None):
        rsp = self._api.call('flickr.photos.geo.setLocation',
                             photo_id,
                             lat,
                             lon,
                             accuracy=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_geo_setPerms(self, is_public, is_contact, is_friend, is_family, photo_id):
        rsp = self._api.call('flickr.photos.geo.setPerms',
                             is_public,
                             is_contact,
                             is_friend,
                             is_family,
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getAllContexts(self, photo_id):
        rsp = self._api.unsigned_call('flickr.photos.getAllContexts',
                                      photo_id)
        return self._handle_rsp(rsp)
    def photos_getContactsPhotos(self, count=None, just_friends=None, single_photo=None, include_self=None, extras=None):
        rsp = self._api.call('flickr.photos.getContactsPhotos',
                             count=None,
                             just_friends=None,
                             single_photo=None,
                             include_self=None,
                             extras=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getContactsPublicPhotos(self, user_id, count=None, just_friends=None, single_photo=None, include_self=None, extras=None):
        rsp = self._api.unsigned_call('flickr.photos.getContactsPublicPhotos',
                                      user_id,
                                      count=None,
                                      just_friends=None,
                                      single_photo=None,
                                      include_self=None,
                                      extras=None)
        return self._handle_rsp(rsp)
    def photos_getContext(self, photo_id):
        rsp = self._api.unsigned_call('flickr.photos.getContext',
                                      photo_id)
        return self._handle_rsp(rsp)
    def photos_getCounts(self, dates=None, taken_dates=None):
        rsp = self._api.call('flickr.photos.getCounts',
                             dates=None,
                             taken_dates=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getExif(self, photo_id, secret=None):
        rsp = self._api.unsigned_call('flickr.photos.getExif',
                                      photo_id,
                                      secret=None)
        return self._handle_rsp(rsp)
    def photos_getFavorites(self, photo_id, page=None, per_page=None):
        rsp = self._api.unsigned_call('flickr.photos.getFavorites',
                                      photo_id,
                                      page=None,
                                      per_page=None)
        return self._handle_rsp(rsp)
    def photos_getInfo(self, photo_id, secret=None):
        rsp = self._api.unsigned_call('flickr.photos.getInfo',
                                      photo_id,
                                      secret=None)
        return self._handle_rsp(rsp)
    def photos_getNotInSet(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, extras=None, per_page=None, page=None):
        rsp = self._api.call('flickr.photos.getNotInSet',
                             min_upload_date=None,
                             max_upload_date=None,
                             min_taken_date=None,
                             max_taken_date=None,
                             privacy_filter=None,
                             extras=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getPerms(self, photo_id):
        rsp = self._api.call('flickr.photos.getPerms',
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getRecent(self, extras=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.photos.getRecent',
                                      extras=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def photos_getSizes(self, photo_id):
        rsp = self._api.unsigned_call('flickr.photos.getSizes',
                                      photo_id)
        return self._handle_rsp(rsp)
    def photos_getUntagged(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, extras=None, per_page=None, page=None):
        rsp = self._api.call('flickr.photos.getUntagged',
                             min_upload_date=None,
                             max_upload_date=None,
                             min_taken_date=None,
                             max_taken_date=None,
                             privacy_filter=None,
                             extras=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getWithGeoData(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, sort=None, extras=None, per_page=None, page=None):
        rsp = self._api.call('flickr.photos.getWithGeoData',
                             min_upload_date=None,
                             max_upload_date=None,
                             min_taken_date=None,
                             max_taken_date=None,
                             privacy_filter=None,
                             sort=None,
                             extras=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_getWithoutGeoData(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, sort=None, extras=None, per_page=None, page=None):
        rsp = self._api.call('flickr.photos.getWithoutGeoData',
                             min_upload_date=None,
                             max_upload_date=None,
                             min_taken_date=None,
                             max_taken_date=None,
                             privacy_filter=None,
                             sort=None,
                             extras=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_licenses_getInfo(self):
        rsp = self._api.unsigned_call('flickr.photos.licenses.getInfo')
        return self._handle_rsp(rsp)
    def photos_licenses_setLicense(self, photo_id, license_id):
        rsp = self._api.call('flickr.photos.licenses.setLicense',
                             photo_id,
                             license_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_notes_add(self, photo_id, note_x, note_y, note_w, note_h, note_text):
        rsp = self._api.call('flickr.photos.notes.add',
                             photo_id,
                             note_x,
                             note_y,
                             note_w,
                             note_h,
                             note_text,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_notes_delete(self, note_id):
        rsp = self._api.call('flickr.photos.notes.delete',
                             note_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_notes_edit(self, note_id, note_x, note_y, note_w, note_h, note_text):
        rsp = self._api.call('flickr.photos.notes.edit',
                             note_id,
                             note_x,
                             note_y,
                             note_w,
                             note_h,
                             note_text,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_recentlyUpdated(self, min_date, extras=None, per_page=None, page=None):
        rsp = self._api.call('flickr.photos.recentlyUpdated',
                             min_date,
                             extras=None,
                             per_page=None,
                             page=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_removeTag(self, tag_id):
        rsp = self._api.call('flickr.photos.removeTag',
                             tag_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_search(self, machine_tag_mode, user_id=None, tags=None, tag_mode=None, text=None, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, license=None, sort=None, privacy_filter=None, bbox=None, accuracy=None, machine_tags=None, group_id=None, extras=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.photos.search',
                                      machine_tag_mode,
                                      user_id=None,
                                      tags=None,
                                      tag_mode=None,
                                      text=None,
                                      min_upload_date=None,
                                      max_upload_date=None,
                                      min_taken_date=None,
                                      max_taken_date=None,
                                      license=None,
                                      sort=None,
                                      privacy_filter=None,
                                      bbox=None,
                                      accuracy=None,
                                      machine_tags=None,
                                      group_id=None,
                                      extras=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def photos_setDates(self, photo_id, date_posted=None, date_taken=None, date_taken_granularity=None):
        rsp = self._api.call('flickr.photos.setDates',
                             photo_id,
                             date_posted=None,
                             date_taken=None,
                             date_taken_granularity=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_setMeta(self, photo_id, title, description):
        rsp = self._api.call('flickr.photos.setMeta',
                             photo_id,
                             title,
                             description,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_setPerms(self, photo_id, is_public, is_friend, is_family, perm_comment, perm_addmeta):
        rsp = self._api.call('flickr.photos.setPerms',
                             photo_id,
                             is_public,
                             is_friend,
                             is_family,
                             perm_comment,
                             perm_addmeta,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_setTags(self, photo_id, tags):
        rsp = self._api.call('flickr.photos.setTags',
                             photo_id,
                             tags,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_transform_rotate(self, photo_id, degrees):
        rsp = self._api.call('flickr.photos.transform.rotate',
                             photo_id,
                             degrees,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photos_upload_checkTickets(self, tickets):
        rsp = self._api.unsigned_call('flickr.photos.upload.checkTickets',
                                      tickets)
        return self._handle_rsp(rsp)
    def photosets_addPhoto(self, photoset_id, photo_id):
        rsp = self._api.call('flickr.photosets.addPhoto',
                             photoset_id,
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_comments_addComment(self, photoset_id, comment_text):
        rsp = self._api.call('flickr.photosets.comments.addComment',
                             photoset_id,
                             comment_text,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_comments_deleteComment(self, comment_id):
        rsp = self._api.call('flickr.photosets.comments.deleteComment',
                             comment_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_comments_editComment(self, comment_id, comment_text):
        rsp = self._api.call('flickr.photosets.comments.editComment',
                             comment_id,
                             comment_text,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_comments_getList(self, photoset_id):
        rsp = self._api.unsigned_call('flickr.photosets.comments.getList',
                                      photoset_id)
        return self._handle_rsp(rsp)
    def photosets_create(self, title, primary_photo_id, description=None):
        rsp = self._api.call('flickr.photosets.create',
                             title,
                             primary_photo_id,
                             description=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_delete(self, photoset_id):
        rsp = self._api.call('flickr.photosets.delete',
                             photoset_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_editMeta(self, photoset_id, title, description=None):
        rsp = self._api.call('flickr.photosets.editMeta',
                             photoset_id,
                             title,
                             description=None,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_editPhotos(self, photoset_id, primary_photo_id, photo_ids):
        rsp = self._api.call('flickr.photosets.editPhotos',
                             photoset_id,
                             primary_photo_id,
                             photo_ids,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_getContext(self, photo_id, photoset_id):
        rsp = self._api.unsigned_call('flickr.photosets.getContext',
                                      photo_id,
                                      photoset_id)
        return self._handle_rsp(rsp)
    def photosets_getInfo(self, photoset_id):
        rsp = self._api.unsigned_call('flickr.photosets.getInfo',
                                      photoset_id)
        return self._handle_rsp(rsp)
    def photosets_getList(self, user_id=None):
        rsp = self._api.unsigned_call('flickr.photosets.getList',
                                      user_id=None)
        return self._handle_rsp(rsp)
    def photosets_getPhotos(self, photoset_id, extras=None, privacy_filter=None, per_page=None, page=None):
        rsp = self._api.unsigned_call('flickr.photosets.getPhotos',
                                      photoset_id,
                                      extras=None,
                                      privacy_filter=None,
                                      per_page=None,
                                      page=None)
        return self._handle_rsp(rsp)
    def photosets_orderSets(self, photoset_ids):
        rsp = self._api.call('flickr.photosets.orderSets',
                             photoset_ids,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def photosets_removePhoto(self, photoset_id, photo_id):
        rsp = self._api.call('flickr.photosets.removePhoto',
                             photoset_id,
                             photo_id,
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def reflection_getMethodInfo(self, method_name):
        rsp = self._api.unsigned_call('flickr.reflection.getMethodInfo',
                                      method_name)
        return self._handle_rsp(rsp)
    def reflection_getMethods(self):
        rsp = self._api.unsigned_call('flickr.reflection.getMethods')
        return self._handle_rsp(rsp)
    def tags_getHotList(self, period=None, count=None):
        rsp = self._api.unsigned_call('flickr.tags.getHotList',
                                      period=None,
                                      count=None)
        return self._handle_rsp(rsp)
    def tags_getListPhoto(self, photo_id):
        rsp = self._api.unsigned_call('flickr.tags.getListPhoto',
                                      photo_id)
        return self._handle_rsp(rsp)
    def tags_getListUser(self, user_id=None):
        rsp = self._api.unsigned_call('flickr.tags.getListUser',
                                      user_id=None)
        return self._handle_rsp(rsp)
    def tags_getListUserPopular(self, user_id=None, count=None):
        rsp = self._api.unsigned_call('flickr.tags.getListUserPopular',
                                      user_id=None,
                                      count=None)
        return self._handle_rsp(rsp)
    def tags_getListUserRaw(self, tag=None):
        rsp = self._api.unsigned_call('flickr.tags.getListUserRaw',
                                      tag=None)
        return self._handle_rsp(rsp)
    def tags_getRelated(self, tag):
        rsp = self._api.unsigned_call('flickr.tags.getRelated',
                                      tag)
        return self._handle_rsp(rsp)
    def test_echo(self):
        rsp = self._api.unsigned_call('flickr.test.echo')
        return self._handle_rsp(rsp)
    def test_login(self):
        rsp = self._api.call('flickr.test.login',
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def test_null(self):
        rsp = self._api.call('flickr.test.null',
                             auth_token=self.auth_token)
        return self._handle_rsp(rsp)
    def urls_getGroup(self, group_id):
        rsp = self._api.unsigned_call('flickr.urls.getGroup',
                                      group_id)
        return self._handle_rsp(rsp)
    def urls_getUserPhotos(self, user_id=None):
        rsp = self._api.unsigned_call('flickr.urls.getUserPhotos',
                                      user_id=None)
        return self._handle_rsp(rsp)
    def urls_getUserProfile(self, user_id=None):
        rsp = self._api.unsigned_call('flickr.urls.getUserProfile',
                                      user_id=None)
        return self._handle_rsp(rsp)
    def urls_lookupGroup(self, url):
        rsp = self._api.unsigned_call('flickr.urls.lookupGroup',
                                      url)
        return self._handle_rsp(rsp)
    def urls_lookupUser(self, url):
        rsp = self._api.unsigned_call('flickr.urls.lookupUser',
                                      url)
        return self._handle_rsp(rsp)
    #[[[end]]]



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
                #self._api_cache = RawFlickrAPI(api_key, secret)
                self._api_cache = ElementFlickrAPI(api_key, secret)
            return self._api_cache

        @cmdln.alias("echo", "ping")
        def do_test_echo(self, subcmd, opts):
            """ping the Flickr API

            ${cmd_usage}
            ${cmd_option_list}
            """
            if isinstance(self.api, RawFlickrAPI):
                rsp = self.api.unsigned_call("flickr.test.echo")
                sys.stdout.write(rsp)
            elif isinstance(self.api, ElementFlickrAPI):
                rsp = self.api.test_echo()
                ET.dump(rsp)
            else:
                XXX

        def do_test_login(self, subcmd, opts):
            """test if you are logged in

            ${cmd_usage}
            ${cmd_option_list}
            """
            response = self.api.call("flickr.test.login")
            assert self.options.output_format == "raw"
            sys.stdout.write(response)

        def do_auth_getFrob(self, subcmd, opts, perms):
            """flickr.auth.getFrob

            ${cmd_usage}
            ${cmd_option_list}

            PERMS must be one of "read", "write" or "delete".
            """
            response = self.api.call("flickr.auth.getFrob", perms=perms)
            assert self.options.output_format == "raw"
            sys.stdout.write(response)

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

    def main(argv):
        """
        Usage:
            flickrapi.py <method-name> [<args...>]
        
        Where <method-name> is the full ("flickr.test.echo") or
        abbreviated ("test.echo") method name. <args> are given as
        NAME=VALUE pairs (in any order). Note that 'api_key' and
        'secret' are read from ~/.flickr, so no need to specify them.

        TODO: -v|--verbose, -h|--help, -q|--quiet, API class?
        """
        #log.setLevel(logging.DEBUG)
        method_name = argv[1]
        if not method_name.startswith("flickr."):
            method_name = "flickr."+method_name
        args = dict(a.split('=', 1) for a in argv[2:])
        api_key = _api_key_from_file()
        secret = _secret_from_file()
        API = "element"
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
            XXX


    _setup_logging() # defined in recipe:pretty_logging

    try:
#        shell = Shell()
#        optparser = cmdln.CmdlnOptionParser(shell,
#            version=Shell.name+" "+__version__)
#        optparser.add_option("-v", "--verbose", action="callback",
#            callback=lambda opt, o, v, p: log.setLevel(logging.DEBUG),
#            help="more verbose output")
#        optparser.add_option("-q", "--quiet", action="callback",
#            callback=lambda opt, o, v, p: log.setLevel(logging.WARNING),
#            help="quieter output")
#        optparser.add_option("-R", "--raw", action="store_const",
#            dest="output_format", const="raw",
#            help="print the raw response")
#        optparser.add_option("-k", "--api-key", 
#            help="specify your API key (or '~/.flickr/API_KEY' content "
#                 "is used)")
#        optparser.add_option("-s", "--secret", 
#            help="specify your shared secret (or '~/.flickr/SECRET' content "
#                 "is used)")
#        optparser.set_defaults(api_key=None, output_format="raw")
#        retval = shell.main(sys.argv, optparser=optparser)
        retval = main(sys.argv) 
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




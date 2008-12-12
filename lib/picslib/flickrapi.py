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
the users browser. "RawFlickrAPI" provides a helper to do this:

    >>> api.helper_auth_openAuthURL(frob="FROB", perms="read")

(Alternatively, you can use `url = api.helper_auth_getAuthURL()' and control
opening the URL in the user's browser yourself.)

For most browsers `helper_auth_getAuthURL` will return right away.
However, you must wait for the user to authorize in their browser before
proceeding.

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

Store this auth token for subsequent usage (including separate runs of
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

__version_info__ = (0, 1, 0)
__version__ = '.'.join(map(str, __version_info__))

import os
from os.path import expanduser, exists, join, normpath
import sys
import getopt
import stat
import logging
import webbrowser
from datetime import datetime
from pprint import pprint, pformat
import re
import warnings
import urllib
import copy
import types
import time
try:
    from hashlib import md5
except ImportError:
    from md5 import md5

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

#log = logging.getLogger("flickrapi")
log = logging.getLogger("pics")



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
#   import elementtree.ElementTree as ET
#   from pprint import pprint
#   from textwrap import wrap
#   import flickrapi
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

    def _call(self, method_name_, **args):
        rsp = self._api.call(method_name_, **args)
        return self._handle_rsp(rsp)
    def _unsigned_call(self, method_name_, **args):
        rsp = self._api.unsigned_call(method_name_, **args)
        return self._handle_rsp(rsp)

    #[[[cog
    #   from operator import itemgetter
    #
    #   # Generate the API methods using Flickr's reflection APIs.
    #   #TODO: this gets "auth_getFrob" wrong
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
    #       login_anyway = set(["flickr.photos.getInfo"])
    #       if meth_rsp[0].get("needslogin") == "1" \
    #          or api_meth_name in login_anyway:
    #           call_args.append(("auth_token", "=None", "=self.auth_token"))
    #       if meth_rsp[0].get("needssigning") == "1" \
    #          or api_meth_name in login_anyway:
    #           cog.out( "    return self._call('%s'" % api_meth_name)
    #           indent = "                      "
    #           if call_args:
    #               for a,_,d in call_args:
    #                   cog.out(",\n%s%s%s" % (indent, a, d))
    #           cog.outl(")")
    #       else:
    #           cog.out( "    return self._unsigned_call('%s'" % api_meth_name)
    #           indent = "                               "
    #           if call_args:
    #               for a,_,d in call_args:
    #                   cog.out(",\n%s%s%s" % (indent, a, d))
    #           cog.outl(")")
    #       #cog.outl("    return self._handle_rsp(rsp)")
    #]]]
    def activity_userComments(self, per_page=None, page=None):
        return self._call('flickr.activity.userComments',
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def activity_userPhotos(self, timeframe=None, per_page=None, page=None):
        return self._call('flickr.activity.userPhotos',
                          timeframe=timeframe,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def auth_checkToken(self, auth_token):
        return self._unsigned_call('flickr.auth.checkToken',
                                   auth_token=auth_token)
    def auth_getFrob(self, perms):
        return self._call('flickr.auth.getFrob', perms=perms)
    def auth_getFullToken(self, mini_token):
        return self._unsigned_call('flickr.auth.getFullToken',
                                   mini_token=mini_token)
    def auth_getToken(self, frob):
        return self._call('flickr.auth.getToken', frob=frob)
    def blogs_getList(self):
        return self._call('flickr.blogs.getList',
                          auth_token=self.auth_token)
    def blogs_postPhoto(self, blog_id, photo_id, title, description, blog_password=None):
        return self._call('flickr.blogs.postPhoto',
                          blog_id=blog_id,
                          photo_id=photo_id,
                          title=title,
                          description=description,
                          blog_password=blog_password,
                          auth_token=self.auth_token)
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
    def favorites_add(self, photo_id):
        return self._call('flickr.favorites.add',
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def favorites_getList(self, user_id=None, extras=None, per_page=None, page=None):
        return self._call('flickr.favorites.getList',
                          user_id=user_id,
                          extras=extras,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def favorites_getPublicList(self, user_id, extras=None, per_page=None, page=None):
        return self._unsigned_call('flickr.favorites.getPublicList',
                                   user_id=user_id,
                                   extras=extras,
                                   per_page=per_page,
                                   page=page)
    def favorites_remove(self, photo_id):
        return self._call('flickr.favorites.remove',
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def groups_browse(self, cat_id=None):
        return self._call('flickr.groups.browse',
                          cat_id=cat_id,
                          auth_token=self.auth_token)
    def groups_getInfo(self, group_id):
        return self._unsigned_call('flickr.groups.getInfo',
                                   group_id=group_id)
    def groups_pools_add(self, photo_id, group_id):
        return self._call('flickr.groups.pools.add',
                          photo_id=photo_id,
                          group_id=group_id,
                          auth_token=self.auth_token)
    def groups_pools_getContext(self, photo_id, group_id):
        return self._unsigned_call('flickr.groups.pools.getContext',
                                   photo_id=photo_id,
                                   group_id=group_id)
    def groups_pools_getGroups(self, page=None, per_page=None):
        return self._call('flickr.groups.pools.getGroups',
                          page=page,
                          per_page=per_page,
                          auth_token=self.auth_token)
    def groups_pools_getPhotos(self, group_id, tags=None, user_id=None, extras=None, per_page=None, page=None):
        return self._unsigned_call('flickr.groups.pools.getPhotos',
                                   group_id=group_id,
                                   tags=tags,
                                   user_id=user_id,
                                   extras=extras,
                                   per_page=per_page,
                                   page=page)
    def groups_pools_remove(self, photo_id, group_id):
        return self._call('flickr.groups.pools.remove',
                          photo_id=photo_id,
                          group_id=group_id,
                          auth_token=self.auth_token)
    def groups_search(self, text, per_page=None, page=None):
        return self._unsigned_call('flickr.groups.search',
                                   text=text,
                                   per_page=per_page,
                                   page=page)
    def interestingness_getList(self, date=None, extras=None, per_page=None, page=None):
        return self._unsigned_call('flickr.interestingness.getList',
                                   date=date,
                                   extras=extras,
                                   per_page=per_page,
                                   page=page)
    def people_findByEmail(self, find_email):
        return self._unsigned_call('flickr.people.findByEmail',
                                   find_email=find_email)
    def people_findByUsername(self, username):
        return self._unsigned_call('flickr.people.findByUsername',
                                   username=username)
    def people_getInfo(self, user_id):
        return self._unsigned_call('flickr.people.getInfo',
                                   user_id=user_id)
    def people_getPublicGroups(self, user_id):
        return self._unsigned_call('flickr.people.getPublicGroups',
                                   user_id=user_id)
    def people_getPublicPhotos(self, user_id, extras=None, per_page=None, page=None):
        return self._unsigned_call('flickr.people.getPublicPhotos',
                                   user_id=user_id,
                                   extras=extras,
                                   per_page=per_page,
                                   page=page)
    def people_getUploadStatus(self):
        return self._call('flickr.people.getUploadStatus',
                          auth_token=self.auth_token)
    def photos_addTags(self, photo_id, tags):
        return self._call('flickr.photos.addTags',
                          photo_id=photo_id,
                          tags=tags,
                          auth_token=self.auth_token)
    def photos_comments_addComment(self, photo_id, comment_text):
        return self._call('flickr.photos.comments.addComment',
                          photo_id=photo_id,
                          comment_text=comment_text,
                          auth_token=self.auth_token)
    def photos_comments_deleteComment(self, comment_id):
        return self._call('flickr.photos.comments.deleteComment',
                          comment_id=comment_id,
                          auth_token=self.auth_token)
    def photos_comments_editComment(self, comment_id, comment_text):
        return self._call('flickr.photos.comments.editComment',
                          comment_id=comment_id,
                          comment_text=comment_text,
                          auth_token=self.auth_token)
    def photos_comments_getList(self, photo_id):
        return self._unsigned_call('flickr.photos.comments.getList',
                                   photo_id=photo_id)
    def photos_delete(self, photo_id):
        return self._call('flickr.photos.delete',
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def photos_geo_getLocation(self, photo_id):
        return self._unsigned_call('flickr.photos.geo.getLocation',
                                   photo_id=photo_id)
    def photos_geo_getPerms(self, photo_id):
        return self._call('flickr.photos.geo.getPerms',
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def photos_geo_removeLocation(self, photo_id):
        return self._call('flickr.photos.geo.removeLocation',
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def photos_geo_setLocation(self, photo_id, lat, lon, accuracy=None):
        return self._call('flickr.photos.geo.setLocation',
                          photo_id=photo_id,
                          lat=lat,
                          lon=lon,
                          accuracy=accuracy,
                          auth_token=self.auth_token)
    def photos_geo_setPerms(self, is_public, is_contact, is_friend, is_family, photo_id):
        return self._call('flickr.photos.geo.setPerms',
                          is_public=is_public,
                          is_contact=is_contact,
                          is_friend=is_friend,
                          is_family=is_family,
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def photos_getAllContexts(self, photo_id):
        return self._unsigned_call('flickr.photos.getAllContexts',
                                   photo_id=photo_id)
    def photos_getContactsPhotos(self, count=None, just_friends=None, single_photo=None, include_self=None, extras=None):
        return self._call('flickr.photos.getContactsPhotos',
                          count=count,
                          just_friends=just_friends,
                          single_photo=single_photo,
                          include_self=include_self,
                          extras=extras,
                          auth_token=self.auth_token)
    def photos_getContactsPublicPhotos(self, user_id, count=None, just_friends=None, single_photo=None, include_self=None, extras=None):
        return self._unsigned_call('flickr.photos.getContactsPublicPhotos',
                                   user_id=user_id,
                                   count=count,
                                   just_friends=just_friends,
                                   single_photo=single_photo,
                                   include_self=include_self,
                                   extras=extras)
    def photos_getContext(self, photo_id):
        return self._unsigned_call('flickr.photos.getContext',
                                   photo_id=photo_id)
    def photos_getCounts(self, dates=None, taken_dates=None):
        return self._call('flickr.photos.getCounts',
                          dates=dates,
                          taken_dates=taken_dates,
                          auth_token=self.auth_token)
    def photos_getExif(self, photo_id, secret=None):
        return self._unsigned_call('flickr.photos.getExif',
                                   photo_id=photo_id,
                                   secret=secret)
    def photos_getFavorites(self, photo_id, page=None, per_page=None):
        return self._unsigned_call('flickr.photos.getFavorites',
                                   photo_id=photo_id,
                                   page=page,
                                   per_page=per_page)
    def photos_getInfo(self, photo_id, secret=None):
        return self._call('flickr.photos.getInfo',
                          photo_id=photo_id,
                          secret=secret,
                          auth_token=self.auth_token)
    def photos_getNotInSet(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, extras=None, per_page=None, page=None):
        return self._call('flickr.photos.getNotInSet',
                          min_upload_date=min_upload_date,
                          max_upload_date=max_upload_date,
                          min_taken_date=min_taken_date,
                          max_taken_date=max_taken_date,
                          privacy_filter=privacy_filter,
                          extras=extras,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def photos_getPerms(self, photo_id):
        return self._call('flickr.photos.getPerms',
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def photos_getRecent(self, extras=None, per_page=None, page=None):
        return self._unsigned_call('flickr.photos.getRecent',
                                   extras=extras,
                                   per_page=per_page,
                                   page=page)
    def photos_getSizes(self, photo_id):
        return self._unsigned_call('flickr.photos.getSizes',
                                   photo_id=photo_id)
    def photos_getUntagged(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, extras=None, per_page=None, page=None):
        return self._call('flickr.photos.getUntagged',
                          min_upload_date=min_upload_date,
                          max_upload_date=max_upload_date,
                          min_taken_date=min_taken_date,
                          max_taken_date=max_taken_date,
                          privacy_filter=privacy_filter,
                          extras=extras,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def photos_getWithGeoData(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, sort=None, extras=None, per_page=None, page=None):
        return self._call('flickr.photos.getWithGeoData',
                          min_upload_date=min_upload_date,
                          max_upload_date=max_upload_date,
                          min_taken_date=min_taken_date,
                          max_taken_date=max_taken_date,
                          privacy_filter=privacy_filter,
                          sort=sort,
                          extras=extras,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def photos_getWithoutGeoData(self, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, privacy_filter=None, sort=None, extras=None, per_page=None, page=None):
        return self._call('flickr.photos.getWithoutGeoData',
                          min_upload_date=min_upload_date,
                          max_upload_date=max_upload_date,
                          min_taken_date=min_taken_date,
                          max_taken_date=max_taken_date,
                          privacy_filter=privacy_filter,
                          sort=sort,
                          extras=extras,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def photos_licenses_getInfo(self):
        return self._unsigned_call('flickr.photos.licenses.getInfo')
    def photos_licenses_setLicense(self, photo_id, license_id):
        return self._call('flickr.photos.licenses.setLicense',
                          photo_id=photo_id,
                          license_id=license_id,
                          auth_token=self.auth_token)
    def photos_notes_add(self, photo_id, note_x, note_y, note_w, note_h, note_text):
        return self._call('flickr.photos.notes.add',
                          photo_id=photo_id,
                          note_x=note_x,
                          note_y=note_y,
                          note_w=note_w,
                          note_h=note_h,
                          note_text=note_text,
                          auth_token=self.auth_token)
    def photos_notes_delete(self, note_id):
        return self._call('flickr.photos.notes.delete',
                          note_id=note_id,
                          auth_token=self.auth_token)
    def photos_notes_edit(self, note_id, note_x, note_y, note_w, note_h, note_text):
        return self._call('flickr.photos.notes.edit',
                          note_id=note_id,
                          note_x=note_x,
                          note_y=note_y,
                          note_w=note_w,
                          note_h=note_h,
                          note_text=note_text,
                          auth_token=self.auth_token)
    def photos_recentlyUpdated(self, min_date, extras=None, per_page=None, page=None):
        return self._call('flickr.photos.recentlyUpdated',
                          min_date=min_date,
                          extras=extras,
                          per_page=per_page,
                          page=page,
                          auth_token=self.auth_token)
    def photos_removeTag(self, tag_id):
        return self._call('flickr.photos.removeTag',
                          tag_id=tag_id,
                          auth_token=self.auth_token)
    def photos_search(self, machine_tag_mode, user_id=None, tags=None, tag_mode=None, text=None, min_upload_date=None, max_upload_date=None, min_taken_date=None, max_taken_date=None, license=None, sort=None, privacy_filter=None, bbox=None, accuracy=None, machine_tags=None, group_id=None, extras=None, per_page=None, page=None):
        return self._unsigned_call('flickr.photos.search',
                                   machine_tag_mode=machine_tag_mode,
                                   user_id=user_id,
                                   tags=tags,
                                   tag_mode=tag_mode,
                                   text=text,
                                   min_upload_date=min_upload_date,
                                   max_upload_date=max_upload_date,
                                   min_taken_date=min_taken_date,
                                   max_taken_date=max_taken_date,
                                   license=license,
                                   sort=sort,
                                   privacy_filter=privacy_filter,
                                   bbox=bbox,
                                   accuracy=accuracy,
                                   machine_tags=machine_tags,
                                   group_id=group_id,
                                   extras=extras,
                                   per_page=per_page,
                                   page=page)
    def photos_setDates(self, photo_id, date_posted=None, date_taken=None, date_taken_granularity=None):
        return self._call('flickr.photos.setDates',
                          photo_id=photo_id,
                          date_posted=date_posted,
                          date_taken=date_taken,
                          date_taken_granularity=date_taken_granularity,
                          auth_token=self.auth_token)
    def photos_setMeta(self, photo_id, title, description):
        return self._call('flickr.photos.setMeta',
                          photo_id=photo_id,
                          title=title,
                          description=description,
                          auth_token=self.auth_token)
    def photos_setPerms(self, photo_id, is_public, is_friend, is_family, perm_comment, perm_addmeta):
        return self._call('flickr.photos.setPerms',
                          photo_id=photo_id,
                          is_public=is_public,
                          is_friend=is_friend,
                          is_family=is_family,
                          perm_comment=perm_comment,
                          perm_addmeta=perm_addmeta,
                          auth_token=self.auth_token)
    def photos_setTags(self, photo_id, tags):
        return self._call('flickr.photos.setTags',
                          photo_id=photo_id,
                          tags=tags,
                          auth_token=self.auth_token)
    def photos_transform_rotate(self, photo_id, degrees):
        return self._call('flickr.photos.transform.rotate',
                          photo_id=photo_id,
                          degrees=degrees,
                          auth_token=self.auth_token)
    def photos_upload_checkTickets(self, tickets):
        return self._unsigned_call('flickr.photos.upload.checkTickets',
                                   tickets=tickets)
    def photosets_addPhoto(self, photoset_id, photo_id):
        return self._call('flickr.photosets.addPhoto',
                          photoset_id=photoset_id,
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def photosets_comments_addComment(self, photoset_id, comment_text):
        return self._call('flickr.photosets.comments.addComment',
                          photoset_id=photoset_id,
                          comment_text=comment_text,
                          auth_token=self.auth_token)
    def photosets_comments_deleteComment(self, comment_id):
        return self._call('flickr.photosets.comments.deleteComment',
                          comment_id=comment_id,
                          auth_token=self.auth_token)
    def photosets_comments_editComment(self, comment_id, comment_text):
        return self._call('flickr.photosets.comments.editComment',
                          comment_id=comment_id,
                          comment_text=comment_text,
                          auth_token=self.auth_token)
    def photosets_comments_getList(self, photoset_id):
        return self._unsigned_call('flickr.photosets.comments.getList',
                                   photoset_id=photoset_id)
    def photosets_create(self, title, primary_photo_id, description=None):
        return self._call('flickr.photosets.create',
                          title=title,
                          primary_photo_id=primary_photo_id,
                          description=description,
                          auth_token=self.auth_token)
    def photosets_delete(self, photoset_id):
        return self._call('flickr.photosets.delete',
                          photoset_id=photoset_id,
                          auth_token=self.auth_token)
    def photosets_editMeta(self, photoset_id, title, description=None):
        return self._call('flickr.photosets.editMeta',
                          photoset_id=photoset_id,
                          title=title,
                          description=description,
                          auth_token=self.auth_token)
    def photosets_editPhotos(self, photoset_id, primary_photo_id, photo_ids):
        return self._call('flickr.photosets.editPhotos',
                          photoset_id=photoset_id,
                          primary_photo_id=primary_photo_id,
                          photo_ids=photo_ids,
                          auth_token=self.auth_token)
    def photosets_getContext(self, photo_id, photoset_id):
        return self._unsigned_call('flickr.photosets.getContext',
                                   photo_id=photo_id,
                                   photoset_id=photoset_id)
    def photosets_getInfo(self, photoset_id):
        return self._unsigned_call('flickr.photosets.getInfo',
                                   photoset_id=photoset_id)
    def photosets_getList(self, user_id=None):
        return self._unsigned_call('flickr.photosets.getList',
                                   user_id=user_id)
    def photosets_getPhotos(self, photoset_id, extras=None, privacy_filter=None, per_page=None, page=None):
        return self._unsigned_call('flickr.photosets.getPhotos',
                                   photoset_id=photoset_id,
                                   extras=extras,
                                   privacy_filter=privacy_filter,
                                   per_page=per_page,
                                   page=page)
    def photosets_orderSets(self, photoset_ids):
        return self._call('flickr.photosets.orderSets',
                          photoset_ids=photoset_ids,
                          auth_token=self.auth_token)
    def photosets_removePhoto(self, photoset_id, photo_id):
        return self._call('flickr.photosets.removePhoto',
                          photoset_id=photoset_id,
                          photo_id=photo_id,
                          auth_token=self.auth_token)
    def reflection_getMethodInfo(self, method_name):
        return self._unsigned_call('flickr.reflection.getMethodInfo',
                                   method_name=method_name)
    def reflection_getMethods(self):
        return self._unsigned_call('flickr.reflection.getMethods')
    def tags_getHotList(self, period=None, count=None):
        return self._unsigned_call('flickr.tags.getHotList',
                                   period=period,
                                   count=count)
    def tags_getListPhoto(self, photo_id):
        return self._unsigned_call('flickr.tags.getListPhoto',
                                   photo_id=photo_id)
    def tags_getListUser(self, user_id=None):
        return self._unsigned_call('flickr.tags.getListUser',
                                   user_id=user_id)
    def tags_getListUserPopular(self, user_id=None, count=None):
        return self._unsigned_call('flickr.tags.getListUserPopular',
                                   user_id=user_id,
                                   count=count)
    def tags_getListUserRaw(self, tag=None):
        return self._unsigned_call('flickr.tags.getListUserRaw',
                                   tag=tag)
    def tags_getRelated(self, tag):
        return self._unsigned_call('flickr.tags.getRelated',
                                   tag=tag)
    def test_echo(self):
        return self._unsigned_call('flickr.test.echo')
    def test_login(self):
        return self._call('flickr.test.login',
                          auth_token=self.auth_token)
    def test_null(self):
        return self._call('flickr.test.null',
                          auth_token=self.auth_token)
    def urls_getGroup(self, group_id):
        return self._unsigned_call('flickr.urls.getGroup',
                                   group_id=group_id)
    def urls_getUserPhotos(self, user_id=None):
        return self._unsigned_call('flickr.urls.getUserPhotos',
                                   user_id=user_id)
    def urls_getUserProfile(self, user_id=None):
        return self._unsigned_call('flickr.urls.getUserProfile',
                                   user_id=user_id)
    def urls_lookupGroup(self, url):
        return self._unsigned_call('flickr.urls.lookupGroup',
                                   url=url)
    def urls_lookupUser(self, url):
        return self._unsigned_call('flickr.urls.lookupUser',
                                   url=url)
    #[[[end]]]


class _FlickrObject(object):
    def __repr__(self):
        args = ['%s=%r' % (k,v) for k,v in sorted(self.__dict__.items())
                if v is not None]
        class_parts = [self.__class__.__name__]
        if self.__class__.__module__ != "__main__":
            class_parts.insert(0, self.__class__.__module__)
        return "%s(%s)" % ('.'.join(class_parts), ', '.join(args))
    #def __repr__(self):
    #    return pformat(self.__dict__)

    @staticmethod
    def _bool_keys(data, *keys):
        for key in keys:
            if key not in data: continue
            data[key] = bool(int(data[key]))

    @staticmethod
    def _int_keys(data, *keys):
        for key in keys:
            if key not in data: continue
            data[key] = int(data[key])

    @staticmethod
    def _date_keys(data, *keys):
        for key in keys:
            if key not in data: continue
            if key+"granularity" in data:
                # Convert a date string to a datetime.
                data[key] = _datetime_from_timestamp_and_granularity(
                    data[key], data[key+"granularity"])
            else:
                # Convert a timestamp to a datetime.
                data[key] = datetime.utcfromtimestamp(int(data[key]))

class Blog(_FlickrObject):
    #TODO: attrs here

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "blog"
        kwargs = elem.attrib.copy()
        cls._bool_keys(kwargs, "needspassword")
        return cls(**kwargs)

    def __init__(self, id, name, needspassword, url):
        self.id = id
        self.name = name
        self.needspassword = needspassword
        self.url = url

    #def __str__(self):
    #    return "blog '%s': %s" % (self.name, self.url)

class Person(_FlickrObject):
    #TODO: attrs here
    #TODO: perhaps merge with Contact (subclass?)

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag in ("user", "person")
        #TODO: http://flickr.com/services/api/flickr.people.getInfo.html
        kwargs = elem.attrib.copy()
        assert elem[0].tag == "username"
        kwargs["username"] = elem[0].text
        if log.isEnabledFor(logging.DEBUG):
            ET.dump(elem)
            pprint(kwargs)
        return cls(**kwargs)

    def __init__(self, id, nsid, username):
        self.id = id
        self.nsid = nsid
        self.username = username

class Contact(_FlickrObject):
    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "contact"
        attrs = elem.attrib.copy()
        cls._bool_keys(attrs, "friend", "family", "ignored")
        return cls(**attrs)

    def __init__(self, nsid, username, iconfarm, iconserver, realname,
                 friend, family, ignored):
        self.nsid = nsid
        self.username = username
        self.iconfarm = iconfarm
        self.iconserver = iconserver
        self.realname = realname
        self.friend = friend
        self.family = family
        self.ignored = ignored

class User(_FlickrObject):
    #TODO: WTF? Fix Person, User, Contact
    nsid = None
    username = None
    realname = None
    location = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "owner"
        attrs = elem.attrib.copy()
        return cls(**attrs)

    def __init__(self, nsid, **kwargs):
        self.nsid = nsid
        for key, value in kwargs.items():
            setattr(self, key, value)

class Note(_FlickrObject):
    note = None
    id = None
    author = None
    x = None
    y = None
    w = None
    h = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "note"
        attrs = elem.attrib.copy()
        attrs["author"] = User(attrs["author"], username=attrs["authorname"])
        del attrs["authorname"]
        cls._int_keys(attrs, "x", "y", "w", "h")
        attrs["note"] = elem.text
        return cls(**attrs)

    def __init__(self, note, id, author, x, y, w, h):
        self.note = note
        self.id = id
        self.author = author
        self.x = x
        self.y = y
        self.w = w
        self.h = h

class Tag(_FlickrObject):
    tag = None
    id = None
    author = None
    raw = None
    machine_tag = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "tag"
        attrs = elem.attrib.copy()
        attrs["author"] = User(attrs["author"])
        attrs["tag"] = elem.text
        cls._bool_keys(attrs, "machine_tag")
        return cls(**attrs)

    def __init__(self, tag, **kwargs):
        self.tag = tag
        for key, value in kwargs.items():
            setattr(self, key, value)

class URL(_FlickrObject):
    url = None
    type = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "url"
        attrs = elem.attrib.copy()
        attrs["url"] = elem.text
        return cls(**attrs)

    def __init__(self, url, type):
        self.url = url
        self.type = type

class Location(_FlickrObject):
    latitude = None
    longitude = None
    accuracy = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "location"
        attrs = elem.attrib.copy()
        return cls(**attrs)

    def __init__(self, latitude, longitude, accuracy=None):
        self.latitude = latitude
        self.longitude = longitude
        self.accuracy = accuracy

class GeoPerms(_FlickrObject):
    ispublic = None
    iscontact = None
    isfriend = None
    isfamily = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag in ("geoperms", "perms")
        attrs = elem.attrib.copy()
        cls._bool_keys(attrs, "ispublic", "iscontact", "isfriend", "isfamily")
        if "id" in attrs:
            del attrs["id"]
        pprint(attrs)
        return cls(**attrs)

    def __init__(self, ispublic, iscontact, isfriend, isfamily):
        self.ispublic = ispublic
        self.iscontact = iscontact
        self.isfriend = isfriend
        self.isfamily = isfamily

class Photo(_FlickrObject):
    id = None
    secret = None
    server = None
    isfavorite = None
    license = None #TODO: enum
    rotation = None
    originalsecret = None
    originalformat = None
    owner = None
    title = None
    description = None
    comments = None  # number of comments
    notes = None
    tags = None
    urls = None
    location = None
    geoperms = None
    # Visibility
    ispublic = None
    isfriend = None
    isfamily = None
    # Dates
    posted = None
    taken = None
    takengranularity = None
    lastupdate = None
    # Permissions
    permcommment = None #TODO: enum
    permaddmeta = None #TODO: enum
    # Editability
    cancomment = None
    canaddmeta = None

    @classmethod
    def from_elem(cls, elem):
        assert elem.tag == "photo"
        attrs = elem.attrib.copy()
        if "owner" in attrs:
            #TODO add iconserver to this, cls._person_from_keys()?
            if "ownername" in attrs:
                attrs["owner"] = Person(attrs["owner"],
                                        username=attrs["ownername"])
                del attrs["ownername"]
            else:
                attrs["owner"] = Person(attrs["owner"])
        if "tags" in attrs:
            attrs["tags"] = [Tag(t, machine_tag=False)
                             for t in attrs["tags"].split()]
        if "machine_tags" in attrs:
            attrs["machine_tags"] = [Tag(t, machine_tag=True)
                                     for t in attrs["machine_tags"].split()]
        for child in elem:
            tag = child.tag
            if tag == "owner":
                attrs["owner"] = Person.from_elem(child)
            elif tag in ("title", "description"):
                attrs[tag] = child.text
            elif tag in ("visibility", "dates", "permissions", "editability"):
                attrs.update(child.attrib)
            elif tag == "comments":
                attrs["comments"] = int(child.text)
            elif tag == "notes":
                attrs["notes"] = notes = []
                for note in child:
                    notes.append(Note.from_elem(note))
            elif tag == "tags":
                attrs["tags"] = tags = []
                for tag in child:
                    tags.append(Tag.from_elem(tag))
            elif tag == "urls":
                attrs["urls"] = urls = []
                for url in child:
                    urls.append(URL.from_elem(url))
            elif tag == "location":
                attrs["location"] = Location.from_elem(child)
            elif tag == "geoperms":
                attrs["geoperms"] = GeoPerms.from_elem(child)
            else:
                log.warn("unexpected child of <photo> tag: %r" % tag)
        cls._date_keys(attrs, "taken", "posted", "lastupdate", "dateuploaded",
                       "datetaken")
        cls._bool_keys(attrs, "isfavorite", "ispublic", "isfriend",
                       "isfamily", "cancomment", "canaddmeta")
        return cls(**attrs)

    def __init__(self, id, owner, secret, server, title, ispublic,
                 isfriend, isfamily, **kwargs):
        self.id = id
        self.owner = owner
        self.secret = secret
        self.server = server
        self.title = title
        self.ispublic = ispublic
        self.isfriend = isfriend
        self.isfamily = isfamily
        for key, value in kwargs.items():
            setattr(self, key, value)


class FlickrAPI(object):
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
    def __init__(self, api_key, secret, auth_token=None):
        self._api = ElementFlickrAPI(api_key, secret, auth_token)

    def _pyobj_from_elem(self, elem):
        print "DEPRECATED"
        if elem.tag == "contact":
            d = elem.attrib
            for n in ("friend", "family", "ignored"):
                if n in d:
                    d[n] = bool(int(d[n]))
            return d
        elif elem.tag == "photo":
            d = elem.attrib
            for n in ("isfriend", "isfamily", "ispublic", "isfavorite"):
                if n in d:
                    d[n] = bool(int(d[n]))
            if "lastupdate" in d:
                d["lastupdate"] = datetime.utcfromtimestamp(
                                    int(d["lastupdate"]))
            if "datetaken" in d:
                d["datetaken"] = _datetime_from_timestamp_and_granularity(
                    d["datetaken"], d["datetakengranularity"])
            if "tags" in d:
                d["tags"] = d["tags"].split()
            if "machine_tags" in d:
                d["machine_tags"] = d["machine_tags"].split()
            if "views" in d:
                d["views"] = int(d["views"])
            for child in elem:
                if child.tag == "title":
                    d["title"] = child.text
                elif child.tag == "description":
                    d["description"] = child.text
                elif child.tag == "visibility":
                    d["visibility"] = visibility = child.attrib
                    for n in ("isfriend", "isfamily", "ispublic"):
                        if n in visibility:
                            visibility[n] = bool(int(visibility[n]))
                elif child.tag == "dates":
                    d["dates"] = dates = child.attrib
                    dates["taken"] = _datetime_from_timestamp_and_granularity(
                        dates["taken"], dates["takengranularity"])
                    dates["posted"] = datetime.utcfromtimestamp(
                        int(dates["posted"]))
                    dates["lastupdate"] = datetime.utcfromtimestamp(
                        int(dates["lastupdate"]))
                elif child.tag == "editability":
                    d["editability"] = editability = child.attrib
                    for n in ("cancomment", "canaddmeta"):
                        if n in editability:
                            editability[n] = bool(int(editability[n]))
                elif child.tag == "comments":
                    d["comments"] = int(child.text.strip())
                elif child.tag == "notes":
                    d["notes"] = notes = []
                    for note_elem in child:
                        note = note_elem.attrib
                        for n in ("x", "y", "w", "h"):
                            if n in note:
                                note[n] = int(note[n])
                        note["note"] = note_elem.text
                        notes.append(note)
                elif child.tag == "tags":
                    d["tags"] = tags = []
                    for tag_elem in child:
                        tag = tag_elem.attrib
                        if "machine_tag" in tag:
                            tag["machine_tag"] = bool(int(tag["machine_tag"]))
                        tag["tag"] = tag_elem.text
                        tags.append(tag)
                elif child.tag == "urls":
                    d["urls"] = urls = []
                    for url_elem in child:
                        url = url_elem.attrib
                        url["url"] = url_elem.text
                        urls.append(url)
                else:
                    d[child.tag] = child.attrib
            return d
        elif elem.tag == "blog":
            d = elem.attrib
            for n in ("needspassword",):
                if n in d:
                    d[n] = bool(int(d[n]))
            return d
        else:
            raise NotImplementedError("don't know how to generate a nice "
                                      "Python object for a <%s> element"
                                      % elem.tag)
            

    def blogs_getList(self):
        for blog in self._api.blogs_getList()[0]:
            yield Blog.from_elem(blog)

    #TODO: blogs_postPhoto

    def contacts_getList(self, filter=None, page=None, per_page=None):
        if page is not None:
            for contact in self._api.contacts_getList(
                    filter=filter, page=page, per_page=per_page)[0]:
                yield Contact.from_elem(contact)
        else:
            page = 1
            num_pages = None
            while num_pages is None or page < num_pages:
                contacts = self._api.contacts_getList(
                        filter=filter, page=page, per_page=per_page)[0]
                if num_pages is None:
                    num_pages = int(contacts.get("pages"))
                for contact in contacts:
                    yield Contact.from_elem(contact)
                page += 1

    def contacts_getPublicList(self, user_id, page=None, per_page=None):
        if page is not None:
            for contact in self._api.contacts_getPublicList(
                    user_id=user_id, page=page, per_page=per_page)[0]:
                yield Contact.from_elem(contact)
        else:
            page = 1
            num_pages = None
            while num_pages is None or page < num_pages:
                contacts = self._api.contacts_getPublicList(
                        user_id=user_id, page=page, per_page=per_page)[0]
                if num_pages is None:
                    num_pages = int(contacts.get("pages"))
                for contact in contacts:
                    yield Contact.from_elem(contact)
                page += 1

    def people_findByUsername(self, username):
        user = self._api.people_findByUsername(username)[0]
        return Person.from_elem(user)

    def photos_getInfo(self, photo_id):
        photo = self._api.photos_getInfo(photo_id)[0]
        return Photo.from_elem(photo)

    def photos_recentlyUpdated(self, min_date, extras=None,
                               per_page=None, page=None):
        timestamp = int(_timestamp_from_datetime(min_date))
        if extras is not None and not isinstance(extras, basestring):
            extras = ','.join(e for e in extras)

        if page is not None:
            for photo in self._api.photos_recentlyUpdated(
                    min_date=timestamp, extras=extras,
                    page=page, per_page=per_page)[0]:
                yield Photo.from_elem(photo)
        else:
            page = 1
            num_pages = None
            while num_pages is None or page < num_pages:
                photos = self._api.photos_recentlyUpdated(
                        min_date=timestamp, extras=extras,
                        page=page, per_page=per_page)[0]
                if num_pages is None:
                    num_pages = int(photos.get("pages"))
                for photo in photos:
                    yield Photo.from_elem(photo)
                page += 1

    #TODO: flickr.groups.browse a la os.walk()



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




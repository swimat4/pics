# Copyright (c) 2008 ActiveState Software Inc.

import sys
from os.path import dirname, join, expanduser, exists
import re
import datetime
import time

from picslib.errors import PicsError



def get_flickr_api_key():
    path = expanduser("~/.flickr/API_KEY")
    try:
        return open(path, 'rb').read().strip()
    except EnvironmentError, ex:
        raise PicsError("couldn't determine Flickr API key: %s" % ex)

def get_flickr_secret():
    path = expanduser("~/.flickr/SECRET")
    try:
        return open(path, 'rb').read().strip()
    except EnvironmentError, ex:
        raise PicsError("couldn't determine Flickr secret: %s" % ex)


_g_source_url_pats = [
    ("flickr", re.compile("^flickr://(?P<user>.*?)/?$")),
    #("flickr", re.compile("^http://(www\.)?flickr\.com/photos/(?P<user>.*?)/?$")),
]
def parse_source_url(url):
    """Parse a repository source URL (as passed to 'pics checkout').

        >>> parse_source_url("flickr://someuser/")
        ('flickr', 'someuser')
    """
    for type, pat in _g_source_url_pats:
        match = pat.search(url)
        if match:
            return type, match.group("user")
    else:
        raise PicsError("invalid source url: %r" % url)


def date_N_months_ago(N):
    """Return a date of the first of the month up to N months ago (rounded
    down).
    """
    #TODO: update this to use now.replace(month=<new-month>)
    now = datetime.datetime.utcnow()
    if now.month < N:
        m = (now.month-1)   # 0-based
        m -= N-1            # N months ago (rounded down)
        m %= 12             # normalize
        m += 1              # 1-based
        return datetime.date(now.year-1, m, 1)
    else:
        return datetime.date(now.year, now.month - (N-1), 1)
    
def timestamp_from_datetime(dt):
    return time.mktime(dt.timetuple())


#TODO: update recipe with this
# Recipe: xpprint (1.0+)
from pprint import PrettyPrinter
class XPrettyPrinter(PrettyPrinter):
    def _repr(self, o, context, level):
        try:
            from xpcom.client import Component
            from xpcom.server import UnwrapObject
        except ImportError:
            pass
        else:
            if isinstance(o, Component):
                return PrettyPrinter._repr(self, UnwrapObject(o), context, level)
        try:
            from xml.etree import ElementTree as ET
        except ImportError:
            pass
        else:
            if isinstance(o, ET._ElementInterface):
                return ET.tostring(o)
        return PrettyPrinter._repr(self, object, context, level)
def xpformat(o):
    pp = XPrettyPrinter()
    return pp.pformat(o)
def xpprint(o):
    pp = XPrettyPrinter()
    return pp.pprint(o)



# Copyright (c) 2008 ActiveState Software Inc.

import sys
from os.path import dirname, join, expanduser, exists

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


# Copyright (c) 2008 ActiveState Software Inc.


class PicsError(Exception):
    pass

#TODO: -> FSPicsError
class FSError(PicsError):
    """An error in the file system wrapper."""


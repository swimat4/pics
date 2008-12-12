# Copyright (c) 2008 ActiveState Software Inc.

"""A light class the wraps file-system operations by the WorkingCopy class."""

import sys
from os.path import exists
import os

from picslib.errors import PicsFSError



class FileSystem(object):
    def __init__(self, log=None):
        """Create a FileSystem interaction wrapper.
        
            "log" is a default logger stream to use. Most methods have a log
                optional argument that can be used to override this.
        """
        self._log = log

    def log(self, log, msg, *args):
        if log:
            log(msg, *args)
        else:
            self._log(msg, *args)

    def _mode_from_mode_arg(self, mode_arg, default):
        """Convert a mode argument (common to a few fs methods) to a real
        int mode.
        
        TODO: support things like "+w", "u-x", etc.
        """
        if mode_arg is None:
            return default
        elif isinstance(mode_arg, int):
            return mode_arg
        else:
            raise PicsFSError("unsupported mode arg: %r" % mode_arg) 

    def _set_win32_file_hidden_attr(self, path):
        try:
            import win32api
            from win32con import FILE_ATTRIBUTE_HIDDEN
        except ImportError, ex:
            import subprocess
            subprocess.call(["attrib", "+H", path])
        else:
            win32api.SetFileAttributes(path, FILE_ATTRIBUTE_HIDDEN)

    def mkdir(self, dir, mode=None, parents=False, hidden=False, log=None):
        """Make the given directory.
        
            ...
            "hidden" is an optional boolean to set the hidden attribute
                on the created directory on Windows. It is ignore on other
                platforms.
        """
        mode = self._mode_from_mode_arg(mode, 0777)
        self.log(log, "mkdir%s%s `%s'%s", (parents and " -p" or ""),
                 (mode is not None and " -m "+oct(mode) or ""), dir,
                 (sys.platform == "win32" and hidden and " (hidden)" or ""))
        made_it = True
        if parents:
            if exists(dir):
                made_it = False
            else:
                os.makedirs(dir, mode)
        else:
            os.mkdir(dir, mode)
        if sys.platform == "win32" and hidden and made_it:
            self._set_win32_file_hidden_attr(dir)

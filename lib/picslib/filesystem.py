# Copyright (c) 2008 ActiveState Software Inc.

"""A light class the wraps file-system operations by the WorkingCopy class."""

import sys
from os.path import exists
import os
from glob import glob

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

    def rm(self, path, log=None, dry_run=False):
        """Remove the given path (be it a file or directory).
        
        Raises OSError if the given path does not exist. Can also raise an
        EnvironmentError if the path cannot be removed for some reason.
        """
        self.log(log, "rm `%s'", path)
        if dry_run:
            return

        if path.find('*') != -1 or path.find('?') != -1 or path.find('[') != -1:
            paths = glob(path)
            if not paths:
                raise OSError(2, "No such file or directory: '%s'" % path)
        else:
            paths = [path]    

        for path in paths:
            if os.path.isfile(path) or os.path.islink(path):
                try:
                    os.remove(path)
                except OSError, ex:
                    if ex.errno == 13: # OSError: [Errno 13] Permission denied
                        os.chmod(path, 0777)
                        os.remove(path)
                    else:
                        raise
            elif os.path.isdir(path):
                for f in os.listdir(path):
                    rm(join(path, f))
                os.rmdir(path)
            else:
                raise OSError(2, "No such file or directory", path)



"""Where wallframe keeps its files: each system's own folders for settings, data and cache.

On Linux, the XDG folders: ~/.config, ~/.local/share and ~/.cache unless set
otherwise. On Windows, %APPDATA% for the settings, which roam with the user,
and %LOCALAPPDATA% for the crops and thumbnails, which belong to this machine.
"""

import os
import sys


def _folder(variable, fallback):
    return os.environ.get(variable) or os.path.expanduser(fallback)


def config_dir(windows=sys.platform == "win32"):
    if windows:
        return os.path.join(_folder("APPDATA", "~/AppData/Roaming"), "wallframe")
    return os.path.join(_folder("XDG_CONFIG_HOME", "~/.config"), "wallframe")


def data_dir(windows=sys.platform == "win32"):
    if windows:
        return os.path.join(_folder("LOCALAPPDATA", "~/AppData/Local"), "wallframe")
    return os.path.join(_folder("XDG_DATA_HOME", "~/.local/share"), "wallframe")


def cache_dir(windows=sys.platform == "win32"):
    if windows:
        return os.path.join(_folder("LOCALAPPDATA", "~/AppData/Local"), "wallframe", "cache")
    return os.path.join(_folder("XDG_CACHE_HOME", "~/.cache"), "wallframe")

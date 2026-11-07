"""Where wallframe keeps its files: each system's own folders for settings, data and cache.

On Linux, the XDG folders: ~/.config, ~/.local/share and ~/.cache unless set
otherwise. On Windows, %APPDATA% for the settings, which roam with the user,
and %LOCALAPPDATA% for the crops and thumbnails, which belong to this machine.
"""

import os
import sys
import time

REPLACE_TRIES, REPLACE_WAIT = 20, 0.05  # a second at most, and only when something holds it


def replace(source, target):
    """os.replace, waiting a moment for whoever holds `target` on Windows: there a file
    someone has open cannot be replaced, and an antivirus or the indexer open them all."""
    for _ in range(REPLACE_TRIES if sys.platform == "win32" else 0):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(REPLACE_WAIT)
    os.replace(source, target)


def same_file(one, other):
    """True when the two paths name one file, however they are written: Windows gives
    a path back in its own spelling, which is not always the one it was handed."""
    return one == other or bool(one and other) and _spelled(one) == _spelled(other)


def _spelled(path):
    return os.path.normcase(os.path.normpath(path))


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

"""Windows: the shell draws the wallpaper, one picture per monitor (Windows 8 and later).

wallframe sets it through the shell's IDesktopWallpaper (see win32.py), which
knows each monitor by its device path, like
\\\\?\\DISPLAY#DEL40F3#5&1a2b3c&0&UID4352#{e6f07b5f-...}. That path is long and
cannot be part of a file name, so wallframe names each monitor by the model code
in it, DEL40F3, which stays the same across restarts and cables; two monitors of
the same model are told apart by the number at its end.

Windows places the monitors in physical pixels, and in physical pixels they
always touch, so with different scales their logical places cannot be had by
dividing each one by its scale: that would open gaps. desktop_places keeps who
is beside whom instead, as span.desk does for real sizes.
"""

import os
import re
import sys
from collections import namedtuple

from . import edid, span
from .compositors import CompositorInfo
from .daemons import Output

if sys.platform == "win32":
    from . import win32
    win32.aware()  # before GTK opens a window, so imported with desktops.py
    win32.no_session_bus()

# (device path, (x, y, width, height) in physical pixels, scale such as 1.5)
Screen = namedtuple("Screen", "path rect scale")
_Sized = namedtuple("_Sized", "name width height")
_ENUM = r"SYSTEM\CurrentControlSet\Enum\DISPLAY"


def _parts(path):
    """The model code and instance in a device path: ("DEL40F3", "5&1a2b3c&0&UID4352")."""
    parts = path.split("#")
    return (parts[1], parts[2]) if len(parts) >= 3 else (None, None)


def names(paths):
    """{device path: name}: the model code, then -2, -3... for more of one model.

    The numbers follow the device paths' order, which does not change with the
    monitors' places on the desk.
    """
    found, taken = {}, {}
    for path in sorted(paths, key=str.lower):
        code, _instance = _parts(path)
        base = re.sub(r"[^A-Za-z0-9]+", "", code or "") or "Monitor"
        taken[base] = taken.get(base, 0) + 1
        found[path] = base if taken[base] == 1 else f"{base}-{taken[base]}"
    return found


def registry_key(path):
    """Where Windows keeps the EDID of the monitor at `path`, under HKEY_LOCAL_MACHINE."""
    code, instance = _parts(path)
    if not code:
        return None
    return rf"{_ENUM}\{code}\{instance}\Device Parameters"


def desktop_places(screens, named):
    """{name: (x, y, width, height)} in logical pixels, like Hyprland's, for the span
    and the layouts' previews.

    Each monitor takes its logical size (pixels / scale), and stands beside the
    monitor it touches on the same side, lined up by the same edge or center.
    """
    if not screens:
        return {}
    ordered = sorted(screens, key=lambda s: s.rect[:2])
    sized = [_Sized(named[s.path], s.rect[2], s.rect[3]) for s in ordered]
    rects = {named[s.path]: s.rect for s in ordered}
    logical = {named[s.path]: (s.rect[2] / s.scale, s.rect[3] / s.scale) for s in ordered}
    places = span.desk(sized, rects, logical)
    first = ordered[0].scale  # desk() measures in the first monitor's pixels
    return {name: tuple(round(value / first) for value in place)
            for name, place in places.items()}


def accent_color(value):
    """Windows' AccentColor, 0xAABBGGRR, as a CSS color; None without one."""
    if value is None:
        return None
    return "rgb({}, {}, {})".format(value & 0xFF, value >> 8 & 0xFF, value >> 16 & 0xFF)


class Wallpaper:
    """What daemons.Daemon offers (outputs, set_image), over the shell's wallpaper."""

    def __init__(self, system):
        self.system = system
        self.paths = {}  # name -> device path, from the last outputs()

    def outputs(self):
        """The monitors showing a picture, by name and in physical pixels.

        A monitor showing a color, or a picture that is no longer there, is left
        out, as Plasma leaves out a slideshow: it has no picture to frame.
        """
        screens = [Screen(*s) for s in self.system.screens()]
        named = names([s.path for s in screens])
        found, self.paths = [], {}
        for screen in sorted(screens, key=lambda s: s.rect[:2]):
            name = named[screen.path]
            self.paths[name] = screen.path
            try:
                image = self.system.wallpaper(screen.path)
            except OSError:
                continue
            if image and os.path.isfile(image):
                found.append(Output(name, screen.rect[2], screen.rect[3], image))
        return found

    def set_image(self, output, path):
        """Shows `path` on one monitor. Raises OSError when Windows cannot."""
        if output not in self.paths:
            self.outputs()
        if output not in self.paths:
            raise OSError(None, f"Windows has no monitor named {output}")
        self.system.set_wallpaper(self.paths[output], os.path.abspath(path))


class Desktop:
    """Windows as a desktop (see desktops.py): the shell draws the wallpaper itself."""

    name = "windows"

    def __init__(self, system=None):
        self._system = system

    @property
    def system(self):
        if self._system is None:
            self._system = win32.System()
        return self._system

    def reachable(self):
        return sys.platform == "win32"

    def info(self):
        screens = [Screen(*s) for s in self.system.screens()]
        named = names([s.path for s in screens])
        models = {}
        for screen in screens:
            key = registry_key(screen.path)
            models[named[screen.path]] = edid.name(self.system.edid(key)) if key else ""
        # Device paths are not case-sensitive, and the shell and the monitor list
        # do not always write them alike.
        by_path = {path.lower(): name for path, name in named.items()}
        focused = self.system.focused()
        return CompositorInfo(focused=by_path.get(focused.lower()) if focused else None,
                              models=models, positions=desktop_places(screens, named))

    def wallpaper(self):
        shell = Wallpaper(self.system)
        return shell if shell.outputs() else None

    def sizes(self):
        """{name: (width, height) in millimeters}, from the EDID Windows keeps."""
        found = {}
        for path, name in names([s[0] for s in self.system.screens()]).items():
            key = registry_key(path)
            size = edid.parse(self.system.edid(key)) if key else None
            if size:
                found[name] = size
        return found

    def accent(self):
        return accent_color(self.system.accent())

    def dark(self):
        return self.system.dark()

    def already_open(self):
        """True when another wallframe runs, whose window came forward: Windows has no
        session bus for Gtk.Application to find it on (see window.application_id)."""
        return self.system.already_open()

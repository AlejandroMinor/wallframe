"""KDE Plasma: it draws its own wallpaper, one per screen, so awww cannot be used there.

Plasma is driven through its desktop scripting, sent over D-Bus to plasmashell
(org.kde.PlasmaShell.evaluateScript). Its scripts know each screen by a number
and its place on the desktop, never by the output name wallframe uses (DP-1),
so `kscreen-doctor -j` gives the names, and the two are matched by position.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from .commands import run
from .compositors import CompositorInfo
from .daemons import Output

# Plasma's image wallpaper; its fill mode 2 is Qt's PreserveAspectCrop, which
# leaves a crop made to the screen's exact size untouched.
_PLUGIN = "org.kde.image"
_FILL_CROP = 2
# The wallpaper of Plasma's own themes; a fresh desktop shows it without naming it.
_DEFAULT_PACKAGE = "Next"
# libkscreen's Output::Rotation: these four turn the screen a quarter.
_QUARTER_TURNS = {2, 8, 32, 128}  # Left, Right, Flipped90, Flipped270

# Every desktop of the current activity that is on a screen: where, and its picture.
_QUERY = """
var found = [];
var desktops = desktopsForActivity(currentActivity());
for (var i = 0; i < desktops.length; i++) {
    var desktop = desktops[i];
    if (desktop.screen < 0) continue;
    var place = screenGeometry(desktop.screen);
    var image = "";
    if (desktop.wallpaperPlugin == "%(plugin)s") {
        desktop.currentConfigGroup = ["Wallpaper", "%(plugin)s", "General"];
        image = String(desktop.readConfig("Image", ""));
    }
    found.push({screen: desktop.screen, x: place.left, y: place.top,
                width: place.width, height: place.height,
                plugin: desktop.wallpaperPlugin, image: image});
}
print(JSON.stringify(found));
""" % {"plugin": _PLUGIN}

# Sets IMAGE on the desktop of SCREEN; prints whether there was one.
_SET = """
var done = false;
var desktops = desktopsForActivity(currentActivity());
for (var i = 0; i < desktops.length; i++) {
    var desktop = desktops[i];
    if (desktop.screen != %(screen)d) continue;
    desktop.wallpaperPlugin = "%(plugin)s";
    desktop.currentConfigGroup = ["Wallpaper", "%(plugin)s", "General"];
    desktop.writeConfig("Image", %(image)s);
    desktop.writeConfig("FillMode", %(fill)d);
    done = true;
}
print(done ? "set" : "no desktop");
"""


def evaluate(script):
    """Runs a Plasma desktop script and returns what it printed.

    Raises OSError when plasmashell is not there or refuses the script.
    """
    import gi  # only Plasma needs it here; the window loads GTK anyway
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell",
                              "evaluateScript", GLib.Variant("(s)", (script,)),
                              GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error as error:
        raise OSError(None, f"Plasma refused it: {error.message}") from error
    return reply.unpack()[0]


def kscreen_outputs(text=None):
    """{name: (x, y, logical width, logical height, pixel width, pixel height)}.

    From `kscreen-doctor -j`; only the outputs that are connected and on.
    The pixel size is the current mode's, turned like the screen: what a crop needs.
    """
    if text is None:
        text = run(["kscreen-doctor", "-j"])
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    outputs = {}
    for output in data.get("outputs", []) if isinstance(data, dict) else []:
        if not output.get("connected", True) or not output.get("enabled", True):
            continue
        mode = next((m for m in output.get("modes", [])
                     if m.get("id") == output.get("currentModeId")), None)
        if not mode:
            continue
        width, height = mode["size"]["width"], mode["size"]["height"]
        if output.get("rotation", 1) in _QUARTER_TURNS:
            width, height = height, width
        scale = output.get("scale") or 1
        pos = output.get("pos", {})
        outputs[output["name"]] = (pos.get("x", 0), pos.get("y", 0), round(width / scale),
                                   round(height / scale), width, height)
    return outputs


def picture(desktop, width, height):
    """The image file a desktop shows, or "" for a slideshow, a color and the like.

    Plasma's image wallpaper is a file, or a wallpaper package: a folder with the
    same picture at several sizes, also named on its own ("Next"). A desktop that
    names nothing shows the default package. From a package, the size closest in
    shape to the screen is taken, and the largest of those, to frame from.
    """
    if desktop.get("plugin", _PLUGIN) != _PLUGIN:
        return ""
    image = desktop["image"] or _DEFAULT_PACKAGE
    parsed = urlparse(image)
    path = unquote(parsed.path) if parsed.scheme == "file" else image
    if not parsed.scheme and not path.startswith("/"):  # a package's name
        path = next((p for p in _wallpaper_dirs(path) if os.path.isdir(p)), "")
    if os.path.isdir(path):
        return _from_package(path, width, height)
    return path


def _wallpaper_dirs(name):
    """Where a wallpaper package called `name` can be, in the order Plasma looks."""
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    shared = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [os.path.join(base, "wallpapers", name) for base in [home, *shared.split(":")]]


def _from_package(folder, width, height):
    """The package's image that suits a width x height screen best, or ""."""
    images = os.path.join(folder, "contents", "images")
    sizes = []
    for name in os.listdir(images) if os.path.isdir(images) else []:
        found = re.fullmatch(r"(\d+)x(\d+)\.\w+", name)
        if found:
            w, h = int(found[1]), int(found[2])
            sizes.append((abs(w / h - width / height), -w * h, name))
    return os.path.join(images, min(sizes)[2]) if sizes else ""


class Plasma:
    """What daemons.Daemon offers (outputs, set_image), over Plasma's own wallpaper."""

    def __init__(self, evaluate=evaluate, kscreen=kscreen_outputs):
        self.evaluate, self.kscreen = evaluate, kscreen
        self.screens = {}  # output name -> Plasma's screen number, from the last outputs()

    def outputs(self):
        """The screens showing a picture, by output name and in pixels.

        Empty when plasmashell does not answer, like a query to a missing daemon.
        """
        try:
            desktops = json.loads(self.evaluate(_QUERY) or "[]")
        except (OSError, ValueError):
            return []
        named = self.kscreen()
        found, self.screens = [], {}
        for desktop in sorted(desktops, key=lambda d: (d["x"], d["y"])):
            name, width, height = self._match(desktop, named)
            self.screens[name] = desktop["screen"]
            path = picture(desktop, width, height)
            if path:  # a slideshow or a color has no one picture to frame
                found.append(Output(name, width, height, path))
        return found

    @staticmethod
    def _match(desktop, named):
        """(output name, pixel width, pixel height) for one of Plasma's screens.

        Two screens cannot share a corner unless they mirror each other, so the
        corner tells which output it is. Without kscreen-doctor, the screen gets
        a made-up name and its logical size, which is right at 100% scale.
        """
        for name, (x, y, _w, _h, width, height) in named.items():
            if abs(x - desktop["x"]) <= 1 and abs(y - desktop["y"]) <= 1:
                return name, width, height
        return (f"Screen-{desktop['screen'] + 1}", round(desktop["width"]),
                round(desktop["height"]))

    def set_image(self, output, path):
        """Shows `path` on one screen. Raises OSError when Plasma cannot."""
        if output not in self.screens:
            self.outputs()
        if output not in self.screens:
            raise OSError(None, f"Plasma has no desktop on {output}")
        script = _SET % {"screen": self.screens[output], "plugin": _PLUGIN,
                         "image": json.dumps(_url(path)), "fill": _FILL_CROP}
        if self.evaluate(script).strip() != "set":
            raise OSError(None, f"Plasma has no desktop on {output}")


def _url(path):
    """A file URL for Plasma, the way it stores the wallpaper."""
    return Path(path).absolute().as_uri()


class Desktop:
    """Plasma as a desktop (see desktops.py): it draws the wallpaper itself."""

    name = "kde"  # as XDG_CURRENT_DESKTOP names it, in lower case

    def reachable(self):
        return False  # only XDG_CURRENT_DESKTOP tells Plasma's session apart

    def info(self):
        """The screens' places, for the layout previews; Plasma tells nothing else."""
        return CompositorInfo(positions={name: place[:4]
                                         for name, place in kscreen_outputs().items()})

    def wallpaper(self):
        shell = Plasma()
        return shell if shell.outputs() else None

"""One picture across every monitor, placed as the monitors stand on the desk."""

import math
import os

from . import render
from .framing import Framing
from .monitor import PREVIEW_MAX, Picture, Snapshot

ASPECT_SLACK = 0.1  # an EDID size this far off the monitor's shape is not trusted
YAW_LIMIT = 75      # degrees either way: past this a monitor shows next to nothing
ALIGNED = 2         # logical pixels: edges this close count as lined up on the desktop


def make(monitors, positions, saved=None, sizes=None):
    """A Span over `monitors`, or None when there are fewer than two or the
    desktop does not say where one of them is (see compositors.position).

    `sizes` are the monitors' real sizes in millimeters (see edid.sizes).
    """
    if len(monitors) < 2 or any(m.name not in positions for m in monitors):
        return None
    return Span(monitors, positions, saved, sizes)


def real_widths(monitors, sizes):
    """{name: width in millimeters} when every monitor's size can be trusted, else None.

    The size is turned to match the monitor, since a portrait monitor's EDID
    still describes the panel lying down; and a size whose shape is far from
    the monitor's own, as some TVs report, means none is used.
    """
    widths = {}
    for monitor in monitors:
        size = (sizes or {}).get(monitor.name)
        if not size:
            return None
        width, height = size
        if (width > height) != (monitor.width > monitor.height):
            width, height = height, width
        if abs(width / height - monitor.width / monitor.height) > ASPECT_SLACK * width / height:
            return None
        widths[monitor.name] = width
    return widths


def desk(monitors, positions, sizes=None):
    """{name: (x, y, width, height)}: where each monitor stands, in span units.

    Span units are the first monitor's logical pixels. With every monitor's
    real size, each one is as large as it really is, so a picture keeps its
    size across monitors of different densities; the desktop's arrangement
    still says which monitor is beside which, and how they line up. Without
    real sizes, it is the desktop's arrangement as it is.
    """
    widths = real_widths(monitors, sizes)
    if not widths:
        return {m.name: tuple(positions[m.name]) for m in monitors}
    first = monitors[0]
    per_mm = positions[first.name][2] / widths[first.name]
    sized = {m.name: (widths[m.name] * per_mm,
                      widths[m.name] * per_mm * m.height / m.width) for m in monitors}
    places = {}
    for name in sorted(sized, key=lambda n: positions[n][:2]):
        if not places:
            x, y, _w, _h = positions[name]
            places[name] = (x, y, *sized[name])
            continue
        anchor = min(places, key=lambda n: _gap(positions[n], positions[name]))
        places[name] = _beside(positions[anchor], places[anchor], positions[name], sized[name])
    return places


def _gap(a, b):
    """How far apart two rectangles are; 0 when they touch or overlap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (max(0, bx - (ax + aw), ax - (bx + bw)) + max(0, by - (ay + ah), ay - (by + bh)))


def _beside(logical_anchor, anchor, logical, size):
    """Places a monitor of `size` next to `anchor` as the desktop has it next to
    `logical_anchor`: on the same side, and lined up by the same edge or center."""
    ax, ay, aw, ah = logical_anchor
    x, y, w, h = logical
    AX, AY, AW, AH = anchor
    W, H = size
    k = AW / aw  # span units per logical pixel, near the anchor
    return (_axis(ax, aw, x, w, AX, AW, W, k), _axis(ay, ah, y, h, AY, AH, H, k), W, H)


def _axis(a, a_len, b, b_len, A, A_len, B_len, k):
    """One axis of _beside: past an edge of the anchor, it stays past it by the
    same gap; along it, the edge or center the desktop lines up stays lined up."""
    if b >= a + a_len:
        return A + A_len + (b - a - a_len) * k
    if b + b_len <= a:
        return A - B_len - (a - b - b_len) * k
    if abs(b - a) <= ALIGNED:
        return A
    if abs(b + b_len - a - a_len) <= ALIGNED:
        return A + A_len - B_len
    if abs(b + b_len / 2 - a - a_len / 2) <= ALIGNED:
        return A + (A_len - B_len) / 2
    return A + (b - a) * k


class Span(Picture):
    """The desk as one area: the box around every monitor, in span units (see desk()).

    It is framed like a monitor, and each monitor shows its own piece of it
    (see Framing.piece), cropped at its own resolution. Where no monitor is,
    beside one set higher than another, nothing shows. The monitors can be
    dragged to stand as they do on the desk; the picture stays where it was.
    """

    name = "Span"

    def __init__(self, monitors, positions, saved=None, sizes=None):
        """`saved` is a snapshot() to resume; without it, the first monitor's picture."""
        self.monitors = monitors
        self.default = desk(monitors, positions, sizes)
        widths = real_widths(monitors, sizes)
        self.real_sizes = widths is not None
        first = monitors[0].name
        self.units_per_mm = self.default[first][2] / widths[first] if widths else None
        self.model = f"{len(monitors)} monitors"
        self.places = dict(self.default)
        self.yaws = {}  # name -> degrees a monitor is turned toward the viewer
        self.bound()
        if saved:
            try:
                self.take(saved)
            except (KeyError, OSError):  # its picture is gone, or cannot be read
                saved = None
        if not saved:
            self.follow(monitors[0])
        self.mark_applied()
        if saved and not self.live:  # the monitors show something else by now
            self.follow(monitors[0])

    def follow(self, monitor):
        """Edits the picture `monitor` shows, where the monitors stand as they are.

        The fill stays as it was, like when another image is opened.
        """
        previous = getattr(self, "framing", None)
        self.image, self.original, self.upscaled = monitor.image, monitor.original, monitor.upscaled
        self.framing = Framing(self.width, self.height, *render.image_size(self.image))
        if previous:
            self.framing.fill, self.framing.fill_color, self.framing.blur = (
                previous.fill, previous.fill_color, previous.blur)
        self.thumb = monitor.thumb  # never changed in place, so both can use it
        self.mark_applied()

    def bound(self):
        """Sets the box around the monitors: left, top, width and height."""
        places = self.places.values()
        self.left = min(x for x, _y, _w, _h in places)
        self.top = min(y for _x, y, _w, _h in places)
        self.width = round(max(x + w for x, _y, w, _h in places) - self.left)
        self.height = round(max(y + h for _x, y, _w, h in places) - self.top)

    def take(self, saved, thumb=None):
        """Edits what snapshot() saved, with the places it had for these monitors.
        Without the picture's `thumb`, it reads the picture for one, so it can
        take a moment.

        Raises OSError when the picture cannot be read.
        """
        source = saved["source"]
        size = render.image_size(source)
        places = saved.get("places", {})
        if set(places) == set(self.places):  # the sizes come from the monitors, as now
            self.places = {name: (*places[name][:2], *self.default[name][2:])
                           for name in self.places}
            self.yaws = {name: angle for name, angle in saved.get("yaws", {}).items()
                         if name in self.places and angle}
        else:
            self.places = dict(self.default)
            self.yaws = {}
        self.bound()
        framing = Framing(self.width, self.height, *size)
        framing.restore(saved)  # on another arrangement, its center stays at the center
        original = saved.get("original")
        self.original = original if original and os.path.exists(original) else source
        self.image, self.framing = source, framing
        self.upscaled = source if source != self.original else None
        self.thumb = thumb or render.thumbnail(source, PREVIEW_MAX)

    def snapshot(self):
        """What state.json and a layout keep of the span: picture, framing and
        where each monitor stands."""
        entry = {"source": self.image, "monitors": [m.name for m in self.monitors],
                 "places": {name: list(place) for name, place in self.places.items()},
                 **self.framing.to_dict()}
        if self.yaws:
            entry["yaws"] = dict(self.yaws)
        if self.original != self.image:
            entry["original"] = self.original
        return entry

    def entry(self, monitor):
        """What a layout keeps of `monitor`'s piece, like Monitor.snapshot()."""
        entry = {"source": self.image, **self.piece(monitor).to_dict()}
        if self.original != self.image:
            entry["original"] = self.original
        return entry

    def squeeze(self, name):
        """The share of its width a turned monitor shows: under 1 when it is turned toward
        the viewer, so it is stretched across the screen; over 1 when it is turned away."""
        degrees = self.yaws.get(name, 0)
        cosine = math.cos(math.radians(abs(degrees)))
        return cosine if degrees >= 0 else 1 / cosine

    def frames(self):
        """(name, x, y, width, height) of what each monitor shows, in the box: a turned
        monitor shows the middle of its width."""
        shown = []
        for name, (x, y, w, h) in self.places.items():
            narrow = w * self.squeeze(name)
            shown.append((name, x + (w - narrow) / 2 - self.left, y - self.top, narrow, h))
        return shown

    def arrangement(self):
        """Where the monitors stand and how they are turned, to keep by name."""
        return {"monitors": sorted(self.places),
                "places": {name: list(place) for name, place in self.places.items()},
                "yaws": dict(self.yaws)}

    def use_arrangement(self, entry):
        """Stands the monitors as `entry` (see arrangement()) says, keeping the picture
        where it is. False when it is not for these monitors."""
        try:
            if sorted(entry["monitors"]) != sorted(self.places):
                return False
            places = {name: (*entry["places"][name][:2], *self.default[name][2:])
                      for name in self.places}
        except (KeyError, TypeError, ValueError):
            return False
        self.yaws = {name: angle for name, angle in entry.get("yaws", {}).items()
                     if name in places and angle}
        self.arrange(places)
        self.settle()
        return True

    def set_yaw(self, name, degrees):
        """Turns a monitor by `degrees`, -75 to 75: toward the viewer when positive, away
        when negative."""
        degrees = min(max(round(degrees), -YAW_LIMIT), YAW_LIMIT)
        if degrees:
            self.yaws[name] = degrees
        else:
            self.yaws.pop(name, None)

    def piece(self, monitor, framing=None, places=None):
        """The framing `monitor` shows of the span, or of `framing` with the
        monitors at `places`: another version of it."""
        places = places or self.places
        left = min(x for x, _y, _w, _h in places.values())
        top = min(y for _x, y, _w, _h in places.values())
        x, y, w, h = places[monitor.name]
        return (framing or self.framing).piece(x - left, y - top, w, h,
                                               monitor.width, monitor.height,
                                               self.squeeze(monitor.name))

    def pieces(self):
        """[(monitor, Snapshot)]: what Apply hands each monitor."""
        return [(m, Snapshot(self.image, self.original, self.piece(m), self.thumb))
                for m in self.monitors]

    def move_monitor(self, name, x, y):
        """Puts a monitor's corner at (x, y), keeping the picture where it is."""
        _x, _y, w, h = self.places[name]
        self.arrange({**self.places, name: (x, y, w, h)})

    def gaps(self, name):
        """{"left": (other, distance), "right": ...}: the nearest monitor on each side of
        `name` that stands at some of its height, and how far its edge is, in span
        units; negative when they overlap."""
        x, y, w, h = self.places[name]
        found = {}
        for other, (ox, oy, ow, oh) in self.places.items():
            if other == name or oy >= y + h or oy + oh <= y:
                continue
            side, distance = (("right", ox - (x + w)) if ox >= x else ("left", x - (ox + ow)))
            if side not in found or distance < found[side][1]:
                found[side] = (other, distance)
        return found

    def reset_places(self):
        """Back to the sizes and places the desktop and the EDIDs give, and no one turned."""
        self.yaws = {}
        self.arrange(dict(self.default))
        self.settle()

    def arrange(self, places):
        left, top = self.left, self.top
        self.places = places
        self.bound()
        self.framing.move_area(self.left - left, self.top - top, self.width, self.height)

    def settle(self):
        """Once the monitors stop moving: the picture covers the new box, as it would
        after a drag."""
        self.framing.clamp()
        self.framing.backdrop.clamp()

    def snap(self, name, x, y, reach):
        """(x, y), moved onto the nearest edge or center of another monitor within
        `reach`, on each axis: so monitors meet without a gap or an overlap."""
        _x, _y, w, h = self.places[name]
        xs, ys = [], []
        for other, (ox, oy, ow, oh) in self.places.items():
            if other != name:
                xs += [ox - w, ox + ow, ox, ox + ow - w, ox + (ow - w) / 2]
                ys += [oy - h, oy + oh, oy, oy + oh - h, oy + (oh - h) / 2]
        return _nearest(x, xs, reach), _nearest(y, ys, reach)

    def mark_applied(self):
        """Also keeps the places and the piece each monitor gets, so `live` can
        tell it shows them."""
        super().mark_applied()
        self.applied_places = dict(self.places)
        self.applied_yaws = dict(self.yaws)
        whole = Framing(self.width, self.height, self.framing.source_w, self.framing.source_h)
        whole.restore(self.applied_framing)
        self.applied_pieces = {m.name: self.piece(m, whole).key() for m in self.monitors}

    @property
    def touched(self):
        """Moving a monitor changes every piece, so it waits for Apply too."""
        return (super().touched or self.places != self.applied_places
                or self.yaws != self.applied_yaws)

    def discard_edit(self):
        """Puts the monitors back where they were applied, then the picture."""
        self.yaws = dict(self.applied_yaws)
        self.arrange(dict(self.applied_places))
        super().discard_edit()

    @property
    def live(self):
        """True when every monitor shows its piece of the span as last applied.

        False once any of them shows something else: its own framing, a layout,
        or a wallpaper set outside wallframe.
        """
        return all(m.applied_image == self.applied_image
                   and m.applied == self.applied_pieces[m.name] for m in self.monitors)


def _nearest(value, targets, reach):
    best = min(targets, key=lambda t: abs(t - value), default=value)
    return best if abs(best - value) <= reach else value

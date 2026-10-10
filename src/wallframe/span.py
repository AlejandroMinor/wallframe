"""One picture across every monitor, placed as the monitors sit on the desktop."""

import os

from . import render
from .framing import Framing
from .monitor import PREVIEW_MAX, Picture, Snapshot


def make(monitors, positions, saved=None):
    """A Span over `monitors`, or None when there are fewer than two or the
    desktop does not say where one of them is (see compositors.position)."""
    if len(monitors) < 2 or any(m.name not in positions for m in monitors):
        return None
    return Span(monitors, positions, saved)


class Span(Picture):
    """The desktop as one area: the box around every monitor, in logical pixels.

    It is framed like a monitor, and each monitor shows its own piece of it
    (see Framing.piece), cropped at its own resolution, so a scaled monitor stays
    sharp. Where no monitor is, beside one set higher than another, nothing shows.
    """

    name = "Span"

    def __init__(self, monitors, positions, saved=None):
        """`saved` is a snapshot() to resume; without it, the first monitor's picture."""
        self.monitors = monitors
        self.places = {m.name: positions[m.name] for m in monitors}
        places = self.places.values()
        self.left = min(x for x, _y, _w, _h in places)
        self.top = min(y for _x, y, _w, _h in places)
        self.width = round(max(x + w for x, _y, w, _h in places) - self.left)
        self.height = round(max(y + h for _x, y, _w, h in places) - self.top)
        self.model = f"{len(monitors)} monitors"
        if saved:
            try:
                self.take(saved)
            except (KeyError, OSError):  # its picture is gone, or cannot be read
                saved = None
        if not saved:
            first = monitors[0]
            self.image, self.original, self.upscaled = first.image, first.original, first.upscaled
            self.framing = Framing(self.width, self.height, *render.image_size(self.image))
            self.thumb = first.thumb  # never changed in place, so both can use it
        self.mark_applied()

    def take(self, saved, thumb=None):
        """Edits what snapshot() saved. Without the picture's `thumb`, it reads the
        picture for one, so it can take a moment.

        Raises OSError when the picture cannot be read.
        """
        source = saved["source"]
        framing = Framing(self.width, self.height, *render.image_size(source))
        framing.restore(saved)  # on another arrangement, its center stays at the center
        original = saved.get("original")
        self.original = original if original and os.path.exists(original) else source
        self.image, self.framing = source, framing
        self.upscaled = source if source != self.original else None
        self.thumb = thumb or render.thumbnail(source, PREVIEW_MAX)

    def snapshot(self):
        """What state.json and a layout keep of the span: picture, framing and monitors."""
        entry = {"source": self.image, "monitors": [m.name for m in self.monitors],
                 **self.framing.to_dict()}
        if self.original != self.image:
            entry["original"] = self.original
        return entry

    def entry(self, monitor):
        """What a layout keeps of `monitor`'s piece, like Monitor.snapshot()."""
        entry = {"source": self.image, **self.piece(monitor).to_dict()}
        if self.original != self.image:
            entry["original"] = self.original
        return entry

    def frames(self):
        return [(name, x - self.left, y - self.top, w, h)
                for name, (x, y, w, h) in self.places.items()]

    def piece(self, monitor, framing=None):
        """The framing `monitor` shows of the span, or of `framing`, another one of it."""
        x, y, w, h = self.places[monitor.name]
        return (framing or self.framing).piece(x - self.left, y - self.top, w, h,
                                               monitor.width, monitor.height)

    def pieces(self):
        """[(monitor, Snapshot)]: what Apply hands each monitor."""
        return [(m, Snapshot(self.image, self.original, self.piece(m), self.thumb))
                for m in self.monitors]

    def mark_applied(self):
        """Also keeps the piece each monitor gets, so `live` can tell it shows them."""
        super().mark_applied()
        whole = Framing(self.width, self.height, self.framing.source_w, self.framing.source_h)
        whole.restore(self.applied_framing)
        self.applied_pieces = {m.name: self.piece(m, whole).key() for m in self.monitors}

    @property
    def live(self):
        """True when every monitor shows its piece of the span as last applied.

        False once any of them shows something else: its own framing, a layout,
        or a wallpaper set outside wallframe.
        """
        return all(m.applied_image == self.applied_image
                   and m.applied == self.applied_pieces[m.name] for m in self.monitors)

MAX_ZOOM = 8.0      # relative to min_zoom
SHRINK_LIMIT = 0.5  # zooming out stops at half the size where the whole image fits
FILLS = ("blur", "color")  # what shows in the gaps when the image is smaller than the monitor
BLUR_RANGE = (0, 160)      # blur radius in monitor pixels; 0 keeps the background sharp
BLUR_DEFAULT = 64


class Framing:
    """Zoom, position, mirror and rotation of one image on one monitor. No I/O.

    Coordinates are monitor pixels: the image is drawn at (x, y) scaled by zoom.
    source_w and source_h are the original image size, before rotating.
    Below min_zoom the image no longer covers the monitor and `fill` paints the gaps.
    With the blur fill, `backdrop` frames the same image behind: another Framing
    that always covers the monitor and shares the mirror and rotation.

    A framing can also be one monitor's piece of a span (see piece()): then it is
    `spanned`, never clamped, and the image may lie off to one side of the monitor.
    """

    def __init__(self, monitor_w, monitor_h, source_w, source_h, backdrop=True):
        self.monitor_w, self.monitor_h = monitor_w, monitor_h
        self.source_w, self.source_h = source_w, source_h
        self.flip_h = self.flip_v = False
        self.rotation = 0  # degrees clockwise: 0, 90, 180 or 270
        self.fill = "blur"
        self.fill_color = "#000000"
        self.blur = BLUR_DEFAULT
        self.spanned = False
        self.backdrop = (Framing(monitor_w, monitor_h, source_w, source_h, backdrop=False)
                         if backdrop else None)
        self.recenter()

    @property
    def image_w(self):
        """Width after rotating."""
        return self.source_h if self.rotation in (90, 270) else self.source_w

    @property
    def image_h(self):
        return self.source_w if self.rotation in (90, 270) else self.source_h

    @property
    def min_zoom(self):
        """The zoom that just covers the monitor."""
        return max(self.monitor_w / self.image_w, self.monitor_h / self.image_h)

    @property
    def fit_zoom(self):
        """The zoom that shows the whole image inside the monitor."""
        return min(self.monitor_w / self.image_w, self.monitor_h / self.image_h)

    @property
    def lowest_zoom(self):
        """How far zooming out goes: half the fitting size, or just covering for a backdrop."""
        return self.fit_zoom * SHRINK_LIMIT if self.backdrop else self.min_zoom

    @property
    def covers(self):
        """True when the image fills the whole monitor, so there are no gaps.

        Told by where the image lies, not by its zoom alone: a span's piece can be
        large enough and still lie beside its monitor.
        """
        slack = 1e-6 * (self.monitor_w + self.monitor_h)  # float noise, far below a pixel
        return (self.x <= slack and self.y <= slack
                and self.x + self.image_w * self.zoom >= self.monitor_w - slack
                and self.y + self.image_h * self.zoom >= self.monitor_h - slack)

    @property
    def can_move(self):
        """False when the image matches the monitor exactly, so there is nowhere to drag it."""
        return (abs(self.monitor_w - self.image_w * self.zoom) > 0.5
                or abs(self.monitor_h - self.image_h * self.zoom) > 0.5)

    @property
    def relative_zoom(self):
        """Zoom as the slider shows it: 1.0 is min_zoom."""
        return self.zoom / self.min_zoom

    def recenter(self):
        """Covers the monitor, centered, like the daemon's own crop."""
        self.spanned = False
        self.zoom = self.min_zoom
        self.x = (self.monitor_w - self.image_w * self.zoom) / 2
        self.y = (self.monitor_h - self.image_h * self.zoom) / 2

    def center(self):
        """Centers the image on the monitor, keeping the zoom."""
        self.move_to((self.monitor_w - self.image_w * self.zoom) / 2,
                     (self.monitor_h - self.image_h * self.zoom) / 2)

    def mirror(self, horizontal):
        """Flips the image; the frame keeps showing the same part, mirrored."""
        if horizontal:
            self.flip_h = not self.flip_h
            self.x = self.monitor_w - self.image_w * self.zoom - self.x
        else:
            self.flip_v = not self.flip_v
            self.y = self.monitor_h - self.image_h * self.zoom - self.y
        if self.backdrop:
            self.backdrop.mirror(horizontal)

    def rotate(self):
        """Turns 90 degrees clockwise and recenters."""
        self.rotation = (self.rotation + 90) % 360
        self.recenter()
        if self.backdrop:
            self.backdrop.rotate()

    def reset(self):
        """Centered, no mirror, no rotation."""
        self.flip_h = self.flip_v = False
        self.rotation = 0
        self.recenter()
        if self.backdrop:
            self.backdrop.reset()

    def clamp(self):
        """Keeps the zoom in range and the image where it leaves no avoidable gap.

        On each axis, an image larger than the monitor must cover it, and a
        smaller one must stay inside it. The backdrop never shrinks: it always covers.
        A span's piece that gets clamped is a framing of its own from then on.
        """
        self.spanned = False
        self.zoom = min(max(self.zoom, self.lowest_zoom), self.min_zoom * MAX_ZOOM)
        self.x = _clamp_axis(self.x, self.monitor_w, self.image_w * self.zoom)
        self.y = _clamp_axis(self.y, self.monitor_h, self.image_h * self.zoom)

    def move_to(self, x, y):
        """Moves the image to (x, y), within the limits."""
        self.x, self.y = x, y
        self.clamp()

    def zoom_at(self, factor, px, py):
        """Zooms by `factor`, keeping the image spot under (px, py) in place."""
        old = self.zoom
        self.zoom *= factor
        self.clamp()
        k = self.zoom / old
        self.x = px - (px - self.x) * k
        self.y = py - (py - self.y) * k
        self.clamp()

    def crop_box(self):
        """The visible part of the image: (left, top, right, bottom)."""
        left, top = -self.x / self.zoom, -self.y / self.zoom
        return (left, top,
                left + self.monitor_w / self.zoom, top + self.monitor_h / self.zoom)

    def piece(self, left, top, width, height, pixels_w, pixels_h):
        """What one monitor of a span shows, as a framing of that monitor.

        This framing covers the whole desktop, in logical pixels; the monitor sits
        at (left, top, width, height) on it and has pixels_w x pixels_h real
        pixels, more than its logical size when the desktop scales it. The pieces
        of all the monitors line up into one picture, gaps and blur included.
        """
        scale = pixels_w / width
        piece = Framing(pixels_w, pixels_h, self.source_w, self.source_h,
                        backdrop=bool(self.backdrop))
        piece.fill, piece.fill_color = self.fill, self.fill_color
        piece.blur = round(self.blur * scale)  # in monitor pixels, like everything else
        for part, whole in ((piece, self), (piece.backdrop, self.backdrop)):
            if whole:
                part.flip_h, part.flip_v = whole.flip_h, whole.flip_v
                part.rotation = whole.rotation
                part.zoom = whole.zoom * scale
                part.x, part.y = (whole.x - left) * scale, (whole.y - top) * scale
                part.spanned = True
        return piece

    def move_area(self, dx, dy, width, height):
        """The monitor became width x height and its corner moved by (dx, dy), while
        the image stayed where it was: a span whose monitors were rearranged.

        Nothing is clamped here, so the image does not jump while a monitor is
        dragged; clamp() once the dragging is over.
        """
        self.monitor_w, self.monitor_h = width, height
        self.x, self.y = self.x - dx, self.y - dy
        if self.backdrop:
            self.backdrop.move_area(dx, dy, width, height)

    def placement(self):
        """Where the image lands: (part of the image, part of the monitor it covers).

        The first box is in image pixels, the second in whole monitor pixels.
        When the image covers the monitor, the second box is the whole monitor.
        """
        right, bottom = self.x + self.image_w * self.zoom, self.y + self.image_h * self.zoom
        target = (round(max(0, self.x)), round(max(0, self.y)),
                  round(min(self.monitor_w, right)), round(min(self.monitor_h, bottom)))
        left, top, right, bottom = target
        # Rounding the target to whole pixels can reach a hair past the image edge.
        source = (max(0, (left - self.x) / self.zoom), max(0, (top - self.y) / self.zoom),
                  min(self.image_w, (right - self.x) / self.zoom),
                  min(self.image_h, (bottom - self.y) / self.zoom))
        return source, target

    def key(self):
        """Comparable values, rounded so float noise does not count as a change.

        The fill only counts when there are gaps for it to show in.
        """
        fill = None
        if self.backdrop and not self.covers:
            if self.fill == "color":
                fill = ("color", self.fill_color)
            else:
                fill = ("blur", self.blur, self.backdrop.key())
        return (self.flip_h, self.flip_v, self.rotation,
                round(self.relative_zoom, 4), round(self.x, 1), round(self.y, 1), fill)

    def to_dict(self):
        """For state.json; zoom is relative so it survives a resolution change.

        The monitor size goes along, so restore() can tell it moved to another one.
        """
        saved = {"monitor": [self.monitor_w, self.monitor_h],
                 "zoom": self.relative_zoom, "x": self.x, "y": self.y,
                 "flip_h": self.flip_h, "flip_v": self.flip_v, "rotation": self.rotation}
        if self.spanned:
            saved["span"] = True  # restored as it is, never clamped
        if self.backdrop:
            backdrop = self.backdrop
            saved.update(fill=self.fill, fill_color=self.fill_color, blur=self.blur,
                         backdrop={"zoom": backdrop.relative_zoom,
                                   "x": backdrop.x, "y": backdrop.y})
        return saved

    def restore(self, saved):
        """Loads a to_dict() result, even one saved on a monitor of another size or shape.

        That happens when a layout or state.json meets another monitor on the same
        output, and when copying between monitors. The image point that was at the
        center of the monitor goes back to its center, at the same relative zoom.
        A span's piece comes back exactly as it was, unless the monitor changed size.
        """
        self.flip_h = saved.get("flip_h", False)
        self.flip_v = saved.get("flip_v", False)
        self.rotation = saved.get("rotation", 0)
        self.fill = saved.get("fill", "blur")
        self.fill_color = saved.get("fill_color", "#000000")
        self.blur = saved.get("blur", BLUR_DEFAULT)
        monitor = saved.get("monitor")  # missing from files saved before it was kept
        exact = bool(saved.get("span")) and tuple(monitor or ()) == (self.monitor_w,
                                                                     self.monitor_h)
        self.place(saved, monitor, exact)
        if self.backdrop:
            backdrop = self.backdrop
            backdrop.flip_h, backdrop.flip_v, backdrop.rotation = (
                self.flip_h, self.flip_v, self.rotation)
            backdrop.recenter()
            if "backdrop" in saved:
                backdrop.place(saved["backdrop"], monitor, exact)

    def place(self, saved, monitor, exact=False):
        """Sets the zoom and position `saved` had on `monitor`, a (width, height) or None.

        On a monitor of another size, the image point at its center is found as a
        share of the image, so it also holds between copies of the picture at
        different resolutions, like an upscaled one. `exact` puts it back unclamped,
        as a span's piece.
        """
        self.zoom = self.min_zoom * saved["zoom"]
        if exact:
            self.x, self.y, self.spanned = saved["x"], saved["y"], True
            return
        self.clamp()  # the zoom first: the position depends on it
        x, y = saved["x"], saved["y"]
        if monitor and tuple(monitor) != (self.monitor_w, self.monitor_h):
            old_w, old_h = monitor
            # The image as drawn there; its size depends only on the picture's shape.
            drawn = saved["zoom"] * max(old_w / self.image_w, old_h / self.image_h)
            share_x = (old_w / 2 - x) / (drawn * self.image_w)
            share_y = (old_h / 2 - y) / (drawn * self.image_h)
            x = self.monitor_w / 2 - share_x * self.image_w * self.zoom
            y = self.monitor_h / 2 - share_y * self.image_h * self.zoom
        self.x, self.y = x, y
        self.clamp()


def _clamp_axis(position, monitor, image):
    """Clamps one axis: cover the monitor if the image is larger, stay inside if smaller."""
    if image >= monitor:
        return min(0, max(position, monitor - image))
    return min(monitor - image, max(position, 0))

MAX_ZOOM = 8.0  # relative to min_zoom


class Framing:
    """Zoom, position, mirror and rotation of one image on one monitor. No I/O.

    Coordinates are monitor pixels: the image is drawn at (x, y) scaled by zoom.
    source_w and source_h are the original image size, before rotating.
    """

    def __init__(self, monitor_w, monitor_h, source_w, source_h):
        self.monitor_w, self.monitor_h = monitor_w, monitor_h
        self.source_w, self.source_h = source_w, source_h
        self.flip_h = self.flip_v = False
        self.rotation = 0  # degrees clockwise: 0, 90, 180 or 270
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
    def relative_zoom(self):
        """Zoom as the slider shows it: 1.0 is min_zoom."""
        return self.zoom / self.min_zoom

    def recenter(self):
        """Covers the monitor, centered, like the daemon's own crop."""
        self.zoom = self.min_zoom
        self.x = (self.monitor_w - self.image_w * self.zoom) / 2
        self.y = (self.monitor_h - self.image_h * self.zoom) / 2

    def mirror(self, horizontal):
        """Flips the image; the frame keeps showing the same part, mirrored."""
        if horizontal:
            self.flip_h = not self.flip_h
            self.x = self.monitor_w - self.image_w * self.zoom - self.x
        else:
            self.flip_v = not self.flip_v
            self.y = self.monitor_h - self.image_h * self.zoom - self.y

    def rotate(self):
        """Turns 90 degrees clockwise and recenters."""
        self.rotation = (self.rotation + 90) % 360
        self.recenter()

    def reset(self):
        """Centered, no mirror, no rotation."""
        self.flip_h = self.flip_v = False
        self.rotation = 0
        self.recenter()

    def clamp(self):
        """Keeps the zoom in range and the monitor fully covered."""
        self.zoom = min(max(self.zoom, self.min_zoom), self.min_zoom * MAX_ZOOM)
        self.x = min(0, max(self.x, self.monitor_w - self.image_w * self.zoom))
        self.y = min(0, max(self.y, self.monitor_h - self.image_h * self.zoom))

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

    def key(self):
        """Comparable values, rounded so float noise does not count as a change."""
        return (self.flip_h, self.flip_v, self.rotation,
                round(self.relative_zoom, 4), round(self.x, 1), round(self.y, 1))

    def to_dict(self):
        """For state.json; zoom is relative so it survives a resolution change."""
        return {"zoom": self.relative_zoom, "x": self.x, "y": self.y,
                "flip_h": self.flip_h, "flip_v": self.flip_v, "rotation": self.rotation}

    def restore(self, saved):
        """Loads a to_dict() result, clamped in case the monitor changed."""
        self.flip_h = saved.get("flip_h", False)
        self.flip_v = saved.get("flip_v", False)
        self.rotation = saved.get("rotation", 0)
        self.zoom = self.min_zoom * saved["zoom"]
        self.x, self.y = saved["x"], saved["y"]
        self.clamp()

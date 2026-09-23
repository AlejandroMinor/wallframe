"""Where the image sits on a monitor: zoom, position, mirror and rotation.

Pure geometry with no I/O, so it can be tested without GTK, Pillow or a
wallpaper daemon.

Coordinates are monitor pixels. The image, after mirroring and rotating, is
drawn at (x, y) scaled by `zoom`, so the monitor shows the image region that
starts at (-x / zoom, -y / zoom). Zoom never goes below `min_zoom`, the scale
that just covers the monitor, so no bars ever show.
"""

MAX_ZOOM = 8.0  # relative to min_zoom


class Framing:
    """The framing of one image on one monitor.

    monitor_w, monitor_h: output size in pixels.
    source_w, source_h: size of the original image, before any rotation.
    """

    def __init__(self, monitor_w, monitor_h, source_w, source_h):
        self.monitor_w, self.monitor_h = monitor_w, monitor_h
        self.source_w, self.source_h = source_w, source_h
        self.flip_h = self.flip_v = False
        self.rotation = 0  # degrees clockwise: 0, 90, 180 or 270
        self.recentre()

    @property
    def image_w(self):
        """Width of the image as drawn, after rotating."""
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
        """Zoom as a multiple of min_zoom: 1.0 is "just covers", as the slider shows it."""
        return self.zoom / self.min_zoom

    def recentre(self):
        """Covers the monitor, centred: the framing the daemon's own crop starts from."""
        self.zoom = self.min_zoom
        self.x = (self.monitor_w - self.image_w * self.zoom) / 2
        self.y = (self.monitor_h - self.image_h * self.zoom) / 2

    def mirror(self, horizontal):
        """Flips the image in place, so the frame shows the same part mirrored."""
        if horizontal:
            self.flip_h = not self.flip_h
            self.x = self.monitor_w - self.image_w * self.zoom - self.x
        else:
            self.flip_v = not self.flip_v
            self.y = self.monitor_h - self.image_h * self.zoom - self.y

    def rotate(self):
        """Turns 90 degrees clockwise; the proportions change, so it recentres."""
        self.rotation = (self.rotation + 90) % 360
        self.recentre()

    def reset(self):
        """Back to the starting framing: centred, no mirror, no rotation."""
        self.flip_h = self.flip_v = False
        self.rotation = 0
        self.recentre()

    def clamp(self):
        """Keeps the zoom in range and the image covering the whole monitor."""
        self.zoom = min(max(self.zoom, self.min_zoom), self.min_zoom * MAX_ZOOM)
        self.x = min(0, max(self.x, self.monitor_w - self.image_w * self.zoom))
        self.y = min(0, max(self.y, self.monitor_h - self.image_h * self.zoom))

    def move_to(self, x, y):
        """Places the image at (x, y), as far as it still covers the monitor."""
        self.x, self.y = x, y
        self.clamp()

    def zoom_at(self, factor, px, py):
        """Zooms by `factor` keeping the monitor point (px, py) over the same image spot."""
        old = self.zoom
        self.zoom *= factor
        self.clamp()
        k = self.zoom / old
        self.x = px - (px - self.x) * k
        self.y = py - (py - self.y) * k
        self.clamp()

    def crop_box(self):
        """The region of the transformed image the monitor shows: (left, top, right, bottom)."""
        left, top = -self.x / self.zoom, -self.y / self.zoom
        return (left, top,
                left + self.monitor_w / self.zoom, top + self.monitor_h / self.zoom)

    def key(self):
        """The framing as comparable values, rounded so float noise is not a change."""
        return (self.flip_h, self.flip_v, self.rotation,
                round(self.relative_zoom, 4), round(self.x, 1), round(self.y, 1))

    def to_dict(self):
        """What state.json keeps. Zoom is relative, so it survives a resolution change."""
        return {"zoom": self.relative_zoom, "x": self.x, "y": self.y,
                "flip_h": self.flip_h, "flip_v": self.flip_v, "rotation": self.rotation}

    def restore(self, saved):
        """Applies a to_dict() result, clamped in case the monitor changed since."""
        self.flip_h = saved.get("flip_h", False)
        self.flip_v = saved.get("flip_v", False)
        self.rotation = saved.get("rotation", 0)
        self.zoom = self.min_zoom * saved["zoom"]
        self.x, self.y = saved["x"], saved["y"]
        self.clamp()

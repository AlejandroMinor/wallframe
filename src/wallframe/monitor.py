import os

from . import render
from .framing import Framing

PREVIEW_MAX = 2048  # longest side of the preview copy; the crop uses the original


class Monitor:
    """One monitor being edited: its size, the image and how it is framed."""

    def __init__(self, output, store, model=""):
        self.store, self.model = store, model
        self.load(output)

    def load(self, output):
        """Starts editing what the output shows, resuming wallframe's last framing."""
        self.name, self.width, self.height = output.name, output.width, output.height
        self.image, saved = self.store.resume(self.name, output.image)
        self.framing = Framing(self.width, self.height, *render.image_size(self.image))
        if saved:
            self.framing.restore(saved)
        self.thumb = render.thumbnail(self.image, PREVIEW_MAX)
        self.shown = output.image  # the file the monitor shows
        self.ignored = None        # a newer file the user chose to replace anyway
        self.mark_applied()

    def mark_applied(self):
        self.applied = self.framing.key()
        self.applied_framing = self.framing.to_dict()

    @property
    def touched(self):
        """True when the framing differs from what the monitor shows."""
        return self.framing.key() != self.applied

    @property
    def portrait(self):
        return self.height > self.width

    def changed(self, shown):
        """True when the monitor now shows `shown`, set outside wallframe and not ignored."""
        return shown not in (self.shown, self.ignored)

    def edit(self, action):
        """Runs "mirror", "flip", "rotate" or "reset" on the framing."""
        {"mirror": lambda: self.framing.mirror(horizontal=True),
         "flip": lambda: self.framing.mirror(horizontal=False),
         "rotate": self.framing.rotate,
         "reset": self.framing.reset}[action]()

    def discard_edit(self):
        """Goes back to the framing the monitor showed before editing."""
        self.framing.restore(self.applied_framing)

    def copy_limits(self, other):
        """Why `other`'s position cannot be copied here, or None when it can.

        The fill always copies. The position needs the same image, and a
        monitor of the same shape: positions scale with the monitor size.
        """
        if other.image != self.image:
            return "different image"
        if self.width * other.height != other.width * self.height:
            return "different screen shape"
        return None

    def copy_from(self, other):
        """Takes `other`'s fill, and its position too when copy_limits allows it."""
        if self.copy_limits(other):
            self.framing.fill = other.framing.fill
            self.framing.fill_color = other.framing.fill_color
            self.framing.blur = other.framing.blur
            return
        saved = other.framing.to_dict()
        scale = self.width / other.width  # same shape, so one factor fits both axes
        saved["x"], saved["y"] = saved["x"] * scale, saved["y"] * scale
        backdrop = saved["backdrop"]
        backdrop["x"], backdrop["y"] = backdrop["x"] * scale, backdrop["y"] * scale
        self.framing.restore(saved)

    def preview(self):
        """The thumbnail with the current mirror and rotation."""
        return render.transform(self.thumb, self.framing)

    def apply(self, daemon):
        """Crops the original image, saves the state and shows the crop on the monitor.

        Raises OSError if the image is gone or the crop cannot be written; the
        crop the monitor shows now is only deleted after the new one is saved.
        """
        path = self.store.new_crop_path(self.name)
        try:
            render.crop(self.image, self.framing, path)
        except OSError:
            if os.path.exists(path):
                os.remove(path)  # a half-written file
            raise
        self.store.remove_old_crops(self.name, keep=path)
        self.store.remember(self.name, path, self.image, self.framing)
        daemon.set_image(self.name, path)
        self.shown, self.ignored = path, None
        self.mark_applied()

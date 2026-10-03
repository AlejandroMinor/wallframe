import os
from collections import namedtuple

from . import render
from .framing import Framing

PREVIEW_MAX = 2048  # longest side of the preview copy; the crop uses the original
# A layout's entry for a monitor, read from disk and ready to edit.
Snapshot = namedtuple("Snapshot", "source original framing thumb")


class Monitor:
    """One monitor being edited: its size, the image and how it is framed."""

    def __init__(self, output, store, model=""):
        self.store, self.model = store, model
        self.load(output)

    def load(self, output):
        """Starts editing what the output shows, resuming wallframe's last framing."""
        self.name, self.width, self.height = output.name, output.width, output.height
        self.image, saved = self.store.resume(self.name, output.image)
        # The picture before any AI upscaling, and the upscaled copy if there is one.
        original = (saved or {}).get("original")
        self.original = original if original and os.path.exists(original) else self.image
        self.upscaled = self.image if self.image != self.original else None
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
        self.applied_image = self.image

    @property
    def touched(self):
        """True when the framing or the image differ from what the monitor shows."""
        return self.framing.key() != self.applied or self.image != self.applied_image

    def framing_for(self, path):
        """The current framing, for another copy of the same picture at another size."""
        framing = Framing(self.width, self.height, *render.image_size(path))
        framing.restore(self.framing.to_dict())
        return framing

    def use_upscaled(self, path=None):
        """Edits the upscaled copy: `path` when one was just made, else the last one."""
        self.upscaled = path or self.upscaled
        if self.upscaled and self.image != self.upscaled:
            self.use_image(self.upscaled)

    def use_original(self):
        """Back to the picture as it was before upscaling; the copy stays available."""
        if self.image != self.original:
            self.use_image(self.original)

    def use_image(self, path):
        """Edits `path` instead, keeping the framing: e.g. the same image, upscaled.

        The zoom is saved relative to the image and the position in monitor
        pixels, so a larger copy of the same picture looks exactly the same.
        """
        self.framing = self.framing_for(path)
        self.image = path
        self.thumb = render.thumbnail(path, PREVIEW_MAX)

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
        """Goes back to the image and framing the monitor showed before editing."""
        if self.image != self.applied_image:
            self.use_image(self.applied_image)
        self.framing.restore(self.applied_framing)

    def copy_from(self, other, everything=True):
        """Takes `other`'s picture and framing, or with everything=False only its fill.

        The picture comes with its upscaled copy. On a monitor of another shape,
        what was at the center of `other` lands at the center here.
        """
        if not everything:
            self.framing.fill = other.framing.fill
            self.framing.fill_color = other.framing.fill_color
            self.framing.blur = other.framing.blur
            return
        self.image, self.original, self.upscaled = other.image, other.original, other.upscaled
        self.thumb = other.thumb  # never changed in place, so both can use it
        self.framing = Framing(self.width, self.height,
                               other.framing.source_w, other.framing.source_h)
        self.framing.restore(other.framing.to_dict())  # it carries the other monitor's size

    def open_image(self, path):
        """Edits another picture, centered, keeping only the fill; Apply shows it.

        Raises OSError, with a sentence as strerror, when it is not an image or
        is animated: one cropped frame would freeze it.
        """
        try:
            size = render.image_size(path)
        except OSError as error:
            raise OSError(None, "not an image wallframe can read") from error
        if not render.is_still_image(path):
            raise OSError(None, "animated images and videos cannot be framed")
        framing = Framing(self.width, self.height, *size)
        framing.fill, framing.fill_color, framing.blur = (
            self.framing.fill, self.framing.fill_color, self.framing.blur)
        thumb = render.thumbnail(path, PREVIEW_MAX)
        self.image = self.original = path
        self.upscaled = None
        self.framing, self.thumb = framing, thumb

    def snapshot(self):
        """What a layout keeps of this monitor: the picture and how it is framed.

        Not the crop: a crop is remade on each Apply and the old ones are deleted.
        """
        entry = {"source": self.image, **self.framing.to_dict()}
        if self.original != self.image:
            entry["original"] = self.original
        return entry

    def use_snapshot(self, entry):
        """Edits what snapshot() saved, as it was, even from another monitor on this output.

        Raises FileNotFoundError when the picture is gone.
        """
        self.take(self.read_snapshot(entry))

    def read_snapshot(self, entry):
        """What snapshot() saved, read from disk without changing the monitor.

        It reads the whole picture for the thumbnail, so it can take a moment,
        and changes nothing, so it can run off the main thread.
        Raises FileNotFoundError when the picture is gone, OSError when unreadable.
        """
        source = entry["source"]
        if not os.path.exists(source):
            raise FileNotFoundError(2, "image not found", source)
        framing = self.saved_framing(entry)
        original = entry.get("original")
        original = original if original and os.path.exists(original) else source
        return Snapshot(source, original, framing, render.thumbnail(source, PREVIEW_MAX))

    def take(self, snapshot):
        """Edits a read_snapshot() result."""
        self.image, self.original = snapshot.source, snapshot.original
        self.upscaled = snapshot.source if snapshot.source != snapshot.original else None
        self.framing, self.thumb = snapshot.framing, snapshot.thumb

    def saved_framing(self, entry):
        """The framing snapshot() saved, on this monitor; reads only the image's header."""
        framing = Framing(self.width, self.height, *render.image_size(entry["source"]))
        framing.restore(entry)
        return framing

    def shows(self, entry):
        """True when the monitor shows what snapshot() saved, as applied.

        Quick enough to ask for every layout each time the list is drawn.
        """
        if entry["source"] != self.applied_image:
            return False
        try:
            return self.saved_framing(entry).key() == self.applied
        except OSError:
            return False

    def preview(self):
        """The thumbnail with the current mirror and rotation."""
        return render.transform(self.thumb, self.framing)

    def apply(self, daemon):
        """Crops the original image, saves the state and shows the crop on the monitor.

        Raises OSError if the image is gone, the crop cannot be written or the
        daemon refuses it. Nothing is deleted or forgotten until the daemon has
        the new crop, so a failure leaves the monitor showing the crop it had and
        this edit still pending; the crop just written stays on disk unused, and
        the next apply clears it away.
        """
        self.show(daemon, self.make_crop(self.image, self.framing))

    def make_crop(self, image, framing):
        """Writes the crop of `image` with `framing` to a new file and returns its path.

        The slow half of apply(), and it changes nothing, so it can run off the
        main thread. Raises OSError if the image is gone or the crop cannot be written.
        """
        path = self.store.new_crop_path(self.name)
        try:
            render.crop(image, framing, path)
        except OSError:
            if os.path.exists(path):
                os.remove(path)  # a half-written file
            raise
        return path

    def show(self, daemon, path):
        """The quick half of apply(): sets `path`, a crop of what is edited now, and
        remembers it. Raises OSError when the daemon refuses it."""
        daemon.set_image(self.name, path)
        self.store.remember(self.name, path, self.image, self.framing, self.original)
        self.store.remove_old_crops(self.name, keep=path)
        self.shown, self.ignored = path, None
        self.mark_applied()

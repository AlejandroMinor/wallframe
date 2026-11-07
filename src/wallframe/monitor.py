import os
import threading
from collections import OrderedDict, namedtuple
from concurrent.futures import Future

from PIL import Image

from . import gallery, paths, render
from .framing import Framing

PREVIEW_MAX = 2048  # longest side of the preview copy; the crop uses the original
# Previews kept in memory besides the ones in use: reading a big picture for one takes
# up to a second, and the same one comes back often (every monitor and the span on one
# picture, Discard, the original and its upscaled copy, layouts).
PREVIEWS_KEPT = 6
_previews = OrderedDict()  # (path, inode, date, size) -> Future of its preview
_previews_lock = threading.Lock()
# A layout's entry for a monitor, read from disk and ready to edit.
Snapshot = namedtuple("Snapshot", "source original framing thumb")


def _preview_key(path):
    status = os.stat(path)
    return (os.path.abspath(path), status.st_ino, status.st_mtime_ns, status.st_size)


def preview(path):
    """The picture's preview copy (see PREVIEW_MAX), read once while it is kept.

    Threads asking for the same picture at once wait for one read. Never change the
    copy in place: monitors share it. Raises OSError when it cannot be read.
    """
    key = _preview_key(path)
    with _previews_lock:
        made = _previews.get(key)
        mine = made is None
        if mine:
            made = _previews[key] = Future()
            while len(_previews) > PREVIEWS_KEPT:
                _previews.popitem(last=False)
        else:
            _previews.move_to_end(key)
    if mine:
        try:
            made.set_result(_read_preview(path))
        except BaseException as error:
            made.set_exception(error)
            with _previews_lock:
                if _previews.get(key) is made:
                    del _previews[key]  # not kept: the next one tries again
    return made.result()


def _read_preview(path):
    """The preview, from the copy kept on disk when there is one. A picture larger than
    the preview gets one, written off the caller's thread, for the next time."""
    kept = gallery.cached(path, gallery.previews_dir())
    if kept:
        try:
            with Image.open(kept) as img:
                img.load()
                return img.convert("RGBA")
        except (OSError, ValueError):
            pass  # broken: made again, and written over
    image = render.thumbnail(path, PREVIEW_MAX)
    if max(render.image_size(path)) > PREVIEW_MAX:  # a smaller one is read as quickly
        destination = gallery.cache_file(path, gallery.previews_dir())
        threading.Thread(target=_keep, args=(image, destination), daemon=True).start()
    return image


def _keep(image, destination):
    """Writes a preview to disk; in RGB when it has no transparency: smaller and quicker."""
    if image.getextrema()[3] == (255, 255):
        image = image.convert("RGB")
    try:
        gallery.store(image, destination)
    except OSError:
        pass  # only a convenience: the picture is read again next time


def has_preview(path):
    """True when preview(path) has the copy already, so it returns at once."""
    try:
        key = _preview_key(path)
    except OSError:
        return False
    with _previews_lock:
        made = _previews.get(key)
    return made is not None and made.done() and made.exception() is None


def read_image(path):
    """(size, preview) of a picture to open for framing, read without changing anything.

    Raises OSError, with a sentence as strerror, when it is not an image or is
    animated: one cropped frame would freeze it.
    """
    try:
        size = render.image_size(path)
        still = render.is_still_image(path)
        picture = preview(path) if still else None
    except render.UNREADABLE as error:
        raise OSError(None, "not an image wallframe can read") from error
    if not still:
        raise OSError(None, "animated images and videos cannot be framed")
    return size, picture


class Picture:
    """What the editor frames: a picture on a width x height area, and how it is framed.

    A Monitor is one; a Span (see span.py) frames one picture across all of them.
    Subclasses set name, model, width, height, image, original, upscaled, framing
    and thumb, then call mark_applied().
    """

    def frames(self):
        """The monitors on the area, as (name, x, y, width, height): the editor
        draws a frame around each and dims the rest."""
        return [(self.name, 0, 0, self.width, self.height)]

    def mark_applied(self):
        self.applied = self.framing.key()
        self.applied_framing = self.framing.to_dict()
        self.applied_image = self.image

    @property
    def touched(self):
        """True when the framing or the image differ from what was last applied."""
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
        self.thumb = preview(path)

    @property
    def portrait(self):
        return self.height > self.width

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

    def open_image(self, path, read=None):
        """Edits another picture, centered, keeping only the fill; Apply shows it.

        `read` is read_image(path), when it was read already, off the main thread.
        Raises OSError, with a sentence as strerror, when it is not an image or
        is animated: one cropped frame would freeze it.
        """
        size, thumb = read or read_image(path)
        framing = Framing(self.width, self.height, *size)
        framing.fill, framing.fill_color, framing.blur = (
            self.framing.fill, self.framing.fill_color, self.framing.blur)
        self.image = self.original = path
        self.upscaled = None
        self.framing, self.thumb = framing, thumb

    def export_framing(self):
        """The framing to export for filling its empty space: at the size of the monitor."""
        return self.framing

    def preview(self):
        """The thumbnail with the current mirror and rotation."""
        return render.transform(self.thumb, self.framing)


class Monitor(Picture):
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
        self.thumb = preview(self.image)
        self.shown = output.image  # the file the monitor shows
        self.ignored = None        # a newer file the user chose to replace anyway
        self.mark_applied()

    def changed(self, shown):
        """True when the monitor now shows `shown`, set outside wallframe and not ignored."""
        return not (paths.same_file(shown, self.shown) or paths.same_file(shown, self.ignored))

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
        return Snapshot(source, original, framing, preview(source))

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
        if entry.get("source") != self.applied_image:
            return False
        try:
            return self.saved_framing(entry).key() == self.applied
        except (KeyError, *render.UNREADABLE):
            return False

    def apply(self, daemon):
        """Crops the original image, saves the state and shows the crop on the monitor.

        Raises OSError if the image is gone, the crop cannot be written or the
        daemon refuses it. Nothing is deleted or forgotten until the daemon has
        the new crop, so a failure leaves the monitor showing the crop it had and
        this edit still pending; the crop just written stays on disk unused, and
        the next apply clears it away.
        """
        self.show(daemon, self.make_crop(self.image, self.framing))

    def make_crop(self, image, framing, loaded=None):
        """Writes the crop of `image` with `framing` to a new file and returns its path.

        The slow half of apply(), and it changes nothing, so it can run off the
        main thread. `loaded` is `image` read already (render.Loaded), shared with
        other monitors. Raises OSError if the image is gone or the crop cannot be written.
        """
        path = self.store.new_crop_path(self.name)
        try:
            render.crop(loaded or image, framing, path)
        except OSError:
            if os.path.exists(path):
                os.remove(path)  # a half-written file
            raise
        return path

    def show(self, daemon, path):
        """The quick half of apply(): sets `path`, a crop of what is edited now, and
        remembers it. Raises OSError when the daemon refuses it."""
        daemon.set_image(self.name, path)
        self.shown, self.ignored = path, None  # it does, even if saving that fails next
        self.store.remember(self.name, path, self.image, self.framing, self.original)
        self.store.remove_old_crops(self.name, keep=path)
        self.mark_applied()

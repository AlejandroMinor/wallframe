"""The wallpaper folder for the picker: its pictures, newest first, and their thumbnails."""

import hashlib
import os
import time

from PIL import Image

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "wallframe", "thumbnails")
THUMB_SIZE = (240, 150)  # the most a thumbnail takes, keeping the picture's shape
# Still pictures only, told by the name so a big folder lists at once. GIFs are left
# out: most are animated, and a cropped frame would freeze them.
UNUSED_DAYS = 30  # a thumbnail not shown in this long is deleted
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif"}


def pictures(folder, subfolders=False):
    """Every picture in `folder`, and with `subfolders` in the folders inside it too,
    newest first; [] when it cannot be read. Hidden files and folders are left out."""
    found = []
    for root, folders, files in os.walk(folder):
        folders[:] = sorted(name for name in folders if not name.startswith("."))
        for name in files:
            if not name.startswith(".") and os.path.splitext(name)[1].lower() in EXTENSIONS:
                path = os.path.join(root, name)
                try:
                    found.append((-os.stat(path).st_mtime, path))
                except OSError:
                    continue  # gone, or a broken link
        if not subfolders:
            break
    return [path for _newest, path in sorted(found)]


def cached(path, cache=None):
    """The thumbnail of `path` when it was made already, else None; quick, it only
    looks at the file's date and size."""
    try:
        thumb = _thumb_path(path, cache)
    except OSError:
        return None
    if not os.path.exists(thumb):
        return None
    _touch(thumb)
    return thumb


def _touch(thumb):
    """Marks a thumbnail as used now, so prune() keeps it."""
    try:
        os.utime(thumb)
    except OSError:
        pass


def _thumb_path(path, cache):
    """Where the thumbnail of `path` is kept: named by the picture's path, date and
    size, so a changed picture gets a new one."""
    status = os.stat(path)
    key = f"{os.path.abspath(path)}\0{status.st_mtime_ns}\0{status.st_size}"
    return os.path.join(cache or CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ".png")


def thumbnail(path, cache=None):
    """The path of a small PNG of `path`, made once and kept until the picture changes.

    Raises OSError when the picture cannot be read.
    """
    thumb = _thumb_path(path, cache)
    if os.path.exists(thumb):
        _touch(thumb)
        return thumb
    os.makedirs(os.path.dirname(thumb), exist_ok=True)
    try:
        with Image.open(path) as img:
            img.draft("RGB", THUMB_SIZE)  # JPEGs decode at a fraction of their size: fast
            img.thumbnail(THUMB_SIZE)
            small = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise OSError(None, f"cannot read {os.path.basename(path)}") from error
    temporary = thumb + ".tmp"  # another thread may be reading the finished one
    small.save(temporary, "PNG")
    os.replace(temporary, thumb)
    return thumb


def prune(days=UNUSED_DAYS, cache=None):
    """Deletes the thumbnails no one used in `days`: of pictures that changed, were
    deleted or are in a folder no longer shown. Returns how many."""
    oldest = time.time() - days * 24 * 3600
    gone = 0
    for path in _files(cache):
        try:
            if os.stat(path).st_mtime < oldest:
                os.remove(path)
                gone += 1
        except OSError:
            continue
    return gone


def usage(cache=None):
    """(thumbnails, bytes) kept in the cache."""
    count = size = 0
    for path in _files(cache):
        try:
            size += os.stat(path).st_size
            count += 1
        except OSError:
            continue
    return count, size


def clear(cache=None):
    """Deletes every thumbnail; they are made again when the panel shows them."""
    for path in _files(cache):
        try:
            os.remove(path)
        except OSError:
            continue


def _files(cache):
    folder = cache or CACHE_DIR
    try:
        return [os.path.join(folder, name) for name in os.listdir(folder)
                if name.endswith((".png", ".tmp"))]
    except OSError:
        return []

"""The wallpaper folder for the picker: its pictures, newest first, and their thumbnails.

Also the editor's previews of big pictures, kept the same way beside the thumbnails.
"""

import hashlib
import os
import threading
import time

from PIL import Image

from . import paths

CACHE_DIR = os.path.join(paths.cache_dir(), "thumbnails")
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


def previews_dir():
    """Where the editor keeps its previews of big pictures: reading one from there is
    ten times quicker than reading the picture. Beside the thumbnails, so it follows
    CACHE_DIR."""
    return os.path.join(os.path.dirname(CACHE_DIR), "previews")


def cached(path, cache=None):
    """The thumbnail of `path` when it was made already, else None; quick, it only
    looks at the file's date and size."""
    try:
        thumb = cache_file(path, cache)
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


def cache_file(path, cache=None):
    """Where the thumbnail of `path` is kept: named by the picture's path, date and
    size, so a changed picture gets a new one."""
    status = os.stat(path)
    key = f"{os.path.abspath(path)}\0{status.st_mtime_ns}\0{status.st_size}"
    return os.path.join(cache or CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ".png")


def thumbnail(path, cache=None):
    """The path of a small PNG of `path`, made once and kept until the picture changes.

    Raises OSError when the picture cannot be read.
    """
    thumb = cache_file(path, cache)
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
    temporary = f"{thumb}.{threading.get_ident()}.tmp"  # another thread may be reading it
    small.save(temporary, "PNG")
    paths.replace(temporary, thumb)
    return thumb


def store(image, destination):
    """Saves `image` as the PNG `destination` (see cache_file), written aside and swapped
    in: another thread may be reading the one there."""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = f"{destination}.{threading.get_ident()}.tmp"
    try:
        image.save(temporary, "PNG", compress_level=1)  # quick; still lossless
        paths.replace(temporary, destination)
    except OSError:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


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

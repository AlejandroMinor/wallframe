"""The wallpaper folder for the picker: its pictures, newest first, and their thumbnails."""

import hashlib
import os

from PIL import Image

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "wallframe", "thumbnails")
THUMB_SIZE = (240, 150)  # the most a thumbnail takes, keeping the picture's shape
# Still pictures only, told by the name so a big folder lists at once. GIFs are left
# out: most are animated, and a cropped frame would freeze them.
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif"}


def pictures(folder):
    """Every picture in `folder`, not in its subfolders, newest first; [] when it cannot
    be read."""
    try:
        entries = [entry for entry in os.scandir(folder)
                   if entry.is_file() and not entry.name.startswith(".")
                   and os.path.splitext(entry.name)[1].lower() in EXTENSIONS]
    except OSError:
        return []
    entries.sort(key=lambda entry: (-entry.stat().st_mtime, entry.name))
    return [entry.path for entry in entries]


def cached(path, cache=None):
    """The thumbnail of `path` when it was made already, else None; quick, it only
    looks at the file's date and size."""
    try:
        thumb = _thumb_path(path, cache)
    except OSError:
        return None
    return thumb if os.path.exists(thumb) else None


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

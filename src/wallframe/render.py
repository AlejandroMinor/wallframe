"""Turns a framing into pixels: mirrors, rotates and crops images with Pillow.

No GTK and no fixed paths: callers say which file to read and where to write.
"""

from PIL import Image

# Pillow rotates counter-clockwise; Framing.rotation is clockwise.
_ROTATIONS = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}


def is_still_image(path):
    """True for an image file wallframe can crop: not a video, not an animation.

    A single cropped frame would freeze an animated wallpaper, so those are left out.
    """
    try:
        with Image.open(path) as img:
            return not getattr(img, "is_animated", False)
    except OSError:
        return False


def image_size(path):
    """(width, height) of an image file, read from its header only."""
    with Image.open(path) as img:
        return img.size


def thumbnail(path, max_side):
    """A small RGBA copy of the image for the on-screen preview."""
    with Image.open(path) as img:
        img.thumbnail((max_side, max_side))
        return img.convert("RGBA")


def transform(img, framing):
    """Applies the framing's mirror and rotation, in the same order for preview and crop."""
    if framing.flip_h:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if framing.flip_v:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img.transpose(_ROTATIONS[framing.rotation]) if framing.rotation else img


def crop(source, framing, destination):
    """Writes the part of `source` the framing shows, at the monitor's exact size."""
    with Image.open(source) as img:
        transform(img.convert("RGB"), framing).resize(
            (framing.monitor_w, framing.monitor_h), Image.LANCZOS,
            box=framing.crop_box()).save(destination)

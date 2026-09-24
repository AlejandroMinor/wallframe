from PIL import Image

# Pillow rotates counter-clockwise; Framing.rotation is clockwise.
_ROTATIONS = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}


def is_still_image(path):
    """False for videos and animations: one cropped frame would freeze them."""
    try:
        with Image.open(path) as img:
            return not getattr(img, "is_animated", False)
    except OSError:
        return False


def image_size(path):
    """(width, height), read from the file header only."""
    with Image.open(path) as img:
        return img.size


def thumbnail(path, max_side):
    """A small RGBA copy for the preview."""
    with Image.open(path) as img:
        img.thumbnail((max_side, max_side))
        return img.convert("RGBA")


def transform(img, framing):
    """Applies mirror and rotation; preview and crop share it so they always match."""
    if framing.flip_h:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if framing.flip_v:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img.transpose(_ROTATIONS[framing.rotation]) if framing.rotation else img


def crop(source, framing, destination):
    """Saves the part of `source` the framing shows, at the monitor's exact size."""
    with Image.open(source) as img:
        transform(img.convert("RGB"), framing).resize(
            (framing.monitor_w, framing.monitor_h), Image.LANCZOS,
            box=framing.crop_box()).save(destination)

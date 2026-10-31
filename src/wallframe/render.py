import threading

from PIL import Image, ImageFilter

# Pillow rotates counter-clockwise; Framing.rotation is clockwise.
_ROTATIONS = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
# A strong blur runs on a copy up to this many times smaller, then is scaled
# back up: much faster, and a blurred image loses nothing by it.
_BLUR_SHRINK = 8
_REDUCING_GAP = 3.0  # Pillow: from 3 on, "indistinguishable from fair resampling"
# zlib's quickest level: a monitor's crop saves several times faster than at Pillow's
# default (6), for a file about a fifth larger. PNG stays lossless at any level.
CROP_COMPRESSION = 1


def _inside(box, image):
    """Clamps a crop box to the image: float math can land a hair past an edge,
    and Pillow refuses any box outside the image."""
    left, top, right, bottom = box
    return (max(0, left), max(0, top), min(image.width, right), min(image.height, bottom))


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


def _rgb(image):
    """`image` in RGB; convert() copies even an image that is RGB already."""
    return image if image.mode == "RGB" else image.convert("RGB")


class Loaded:
    """A picture read whole once, for several crops of it: the pieces of a span, or
    monitors that show the same picture. Safe to share between threads; each mirror
    and rotation is made once too."""

    def __init__(self, path):
        self.path = path
        self._image = None
        self._turned = {}
        self._lock = threading.Lock()

    def turned(self, framing):
        """The picture, in RGB, mirrored and rotated as `framing` says."""
        key = (framing.flip_h, framing.flip_v, framing.rotation)
        with self._lock:
            if key not in self._turned:
                if self._image is None:
                    with Image.open(self.path) as img:
                        img.load()  # an RGB picture is kept as it is: read it before closing
                        self._image = _rgb(img)
                self._turned[key] = transform(self._image, framing)
            return self._turned[key]


def transform(img, framing):
    """Applies mirror and rotation; preview and crop share it so they always match."""
    if framing.flip_h:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if framing.flip_v:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img.transpose(_ROTATIONS[framing.rotation]) if framing.rotation else img


def background(image, framing, size):
    """What fills the gaps around a smaller image: a plain color, or the image
    itself as the backdrop framing shows it, blurred.

    `image` is already mirrored and rotated, at any resolution (the preview
    passes its thumbnail), and `size` is the output size.
    """
    if framing.fill == "color":
        return Image.new("RGB", size, framing.fill_color)
    image = _rgb(image)
    # A light blur needs detail, so it shrinks less; no blur keeps full size.
    shrink = max(1, min(_BLUR_SHRINK, framing.blur // 8))
    small = (max(1, size[0] // shrink), max(1, size[1] // shrink))
    scale = image.width / framing.image_w  # framing pixels -> pixels of this image
    # A thumbnail's height is rounded, so the scaled box can reach past its edge.
    box = _inside([side * scale for side in framing.backdrop.crop_box()], image)
    # Shrunk to blur, it may be shrunk in two steps, the first a quick integer one: five
    # times faster, and after the blur no pixel differs by more than 1 of 255.
    backdrop = image.resize(small, Image.LANCZOS, box=box,
                            reducing_gap=_REDUCING_GAP if shrink > 1 else None)
    radius = framing.blur * small[0] / framing.monitor_w  # monitor pixels -> small copy pixels
    if radius:
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius))
    return backdrop if small == size else backdrop.resize(size, Image.BICUBIC)


def compose(source, framing):
    """What the monitor will show, at its exact size and gaps filled, in memory.

    `source` is the picture's path, or a Loaded one, read once for several crops.
    """
    inner = framing.narrowed()  # a turned or tilted monitor in a span shows less, stretched across
    loaded = source if isinstance(source, Loaded) else Loaded(source)
    picture = shown(loaded.turned(inner), inner, (inner.monitor_w, inner.monitor_h))
    if inner is not framing:
        picture = picture.resize((framing.monitor_w, framing.monitor_h), Image.LANCZOS)
    return picture


def shown(image, framing, size):
    """What the monitor will show, at `size`, gaps filled.

    `image` is already mirrored and rotated, at any resolution: the original
    for the crop, the preview thumbnail for a layout's small picture of it.
    """
    image = _rgb(image)
    scale = image.width / framing.image_w  # framing pixels -> pixels of this image
    if framing.covers:
        box = _inside([side * scale for side in framing.crop_box()], image)
        return image.resize(size, Image.LANCZOS, box=box)
    shrink = size[0] / framing.monitor_w   # monitor pixels -> output pixels
    source_box, target = framing.placement()
    left, top, right, bottom = (round(side * shrink) for side in target)
    canvas = background(image, framing, size)
    if right <= left or bottom <= top:  # a span's piece the image misses entirely
        return canvas
    piece = image.resize((max(1, right - left), max(1, bottom - top)), Image.LANCZOS,
                         box=_inside([side * scale for side in source_box], image))
    canvas.paste(piece, (left, top))
    return canvas


def export_for_fill(source, framing, color):
    """The picture as the framing places it, on a canvas of the monitor's size, with the
    empty space in `color`, and a mask of that space: white where another tool should
    paint (inpainting). Returns (picture, mask).

    Raises ValueError when the picture covers the monitor and nothing is left to fill.
    """
    if framing.covers:
        raise ValueError("nothing to fill")
    size = (framing.monitor_w, framing.monitor_h)
    picture, mask = Image.new("RGB", size, color), Image.new("L", size, 255)
    image = Loaded(source).turned(framing)
    scale = image.width / framing.image_w
    source_box, target = framing.placement()
    left, top, right, bottom = target
    if right > left and bottom > top:
        piece = image.resize((right - left, bottom - top), Image.LANCZOS,
                             box=_inside([side * scale for side in source_box], image))
        picture.paste(piece, (left, top))
        mask.paste(0, (left, top, right, bottom))
    return picture, mask


def crop(source, framing, destination):
    """Saves what the monitor will show, at its exact size, gaps filled, as a PNG.

    `source` is a path or a Loaded picture, as for compose().
    """
    compose(source, framing).save(destination, "PNG", compress_level=CROP_COMPRESSION)


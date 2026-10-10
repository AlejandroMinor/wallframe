from PIL import Image, ImageFilter

# Pillow rotates counter-clockwise; Framing.rotation is clockwise.
_ROTATIONS = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
# A strong blur runs on a copy up to this many times smaller, then is scaled
# back up: much faster, and a blurred image loses nothing by it.
_BLUR_SHRINK = 8


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
    # A light blur needs detail, so it shrinks less; no blur keeps full size.
    shrink = max(1, min(_BLUR_SHRINK, framing.blur // 8))
    small = (max(1, size[0] // shrink), max(1, size[1] // shrink))
    scale = image.width / framing.image_w  # framing pixels -> pixels of this image
    # A thumbnail's height is rounded, so the scaled box can reach past its edge.
    box = _inside([side * scale for side in framing.backdrop.crop_box()], image)
    backdrop = image.convert("RGB").resize(small, Image.LANCZOS, box=box)
    radius = framing.blur * small[0] / framing.monitor_w  # monitor pixels -> small copy pixels
    if radius:
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius))
    return backdrop if small == size else backdrop.resize(size, Image.BICUBIC)


def compose(source, framing):
    """What the monitor will show, at its exact size and gaps filled, in memory."""
    with Image.open(source) as img:
        return shown(transform(img.convert("RGB"), framing), framing,
                     (framing.monitor_w, framing.monitor_h))


def shown(image, framing, size):
    """What the monitor will show, at `size`, gaps filled.

    `image` is already mirrored and rotated, at any resolution: the original
    for the crop, the preview thumbnail for a layout's small picture of it.
    """
    image = image.convert("RGB")
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


def crop(source, framing, destination):
    """Saves what the monitor will show, at its exact size, gaps filled."""
    compose(source, framing).save(destination)


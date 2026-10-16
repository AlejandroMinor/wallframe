"""What to tell an image AI so it fills the empty space of an exported picture."""

import math

# The proportions that image AIs usually offer.
COMMON = ((16, 9), (21, 9), (32, 9), (4, 3), (3, 2), (16, 10), (1, 1),
          (9, 16), (9, 21), (9, 32), (3, 4), (2, 3), (10, 16))
# Vivid colors an AI cannot take for part of a scene, with a plain name for the notice.
CANDIDATES = (("#00ff00", "green"), ("#ff00ff", "magenta"), ("#00ffff", "cyan"),
              ("#ff8800", "orange"), ("#ffff00", "yellow"), ("#0000ff", "blue"))
CLOSE = 80      # how near, of 441 across the RGB cube, a pixel is to a color to count as it
CLASH = 0.02    # the share of a picture near a fill color that makes the AI mistake them
LARGE = 0.5     # the share of empty space past which the AI invents more than it continues


def share(picture, color):
    """The fraction of `picture`'s pixels near `color` (an RGB image, small, and a "#rrggbb")."""
    wanted = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    pixels = list(picture.convert("RGB").getdata())
    near = sum(1 for p in pixels if math.dist(p, wanted) < CLOSE)
    return near / len(pixels)


def least_present(picture):
    """(hex, name) of the candidate color that is the least in `picture`."""
    return min(CANDIDATES, key=lambda candidate: share(picture, candidate[0]))


def name_of(color):
    """A plain name for `color` when it is one of the candidates, else the code itself."""
    return dict(CANDIDATES).get(color.lower(), color)


def nearest(width, height):
    """The common proportion closest to `width` x `height`, as "21:9"."""
    wide, tall = min(COMMON, key=lambda r: abs(math.log(width / height / (r[0] / r[1]))))
    return f"{wide}:{tall}"


def prompt(color, width, height, original=None):
    """The text to paste in the AI, next to the picture and its mask.

    `original` is where the picture sits on the canvas, (left, top, right, bottom) in pixels:
    saying it keeps the AI from moving or shrinking it.
    """
    where = ""
    if original:
        left, top, right, bottom = original
        where = (f"- The original picture sits in the rectangle from {left / width:.0%} to "
                 f"{right / width:.0%} of the width and from {top / height:.0%} to "
                 f"{bottom / height:.0%} of the height. Keep it exactly there, at the same size, "
                 "and do not draw it again as a smaller picture or an inset.\n")
    return (
        f"Fill the area of this image that is solid {color} with content that continues "
        "the scene naturally. If you have the mask, fill the white area of the mask instead.\n"
        "- The rest of the image is a crop of a larger scene. Extend it outward, as if the camera "
        "had zoomed out: keep its scale, perspective, horizon line and style, so that clouds, "
        "lines and shapes that reach its edges go on beyond them.\n"
        + where +
        "- There must be no visible seam: no frame, border, shadow, or change of brightness, "
        "color or texture where the original ends. Blend it into the new content.\n"
        "- Do not change the original picture in any other way: keep every detail, including "
        "any text, exactly as it is.\n"
        f"- Keep the exact aspect ratio of the image: {width}x{height} px, about "
        f"{width / height:.2f}:1 (closest common ratio: {nearest(width, height)}). "
        "Do not crop it or change it.\n"
        f"- Leave no border, mark or trace of the color {color}.\n"
        "- No text, no watermarks and no new objects that draw attention.\n"
        "- Give the highest resolution you can.\n")

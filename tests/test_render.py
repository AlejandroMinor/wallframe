"""Tests for cropping: real images, but tiny and in a temporary folder."""

from PIL import Image

from wallframe import render
from wallframe.framing import Framing

RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def quadrants(path):
    """A 400x200 image: red top left, green top right, blue bottom left, white bottom right."""
    img = Image.new("RGB", (400, 200))
    for box, color in (((0, 0, 200, 100), RED), ((200, 0, 400, 100), GREEN),
                       ((0, 100, 200, 200), BLUE), ((200, 100, 400, 200), WHITE)):
        img.paste(color, box)
    img.save(path)
    return path


def corners(path):
    """Colours near the four corners of an image: top left, top right, bottom left, bottom right."""
    with Image.open(path) as img:
        w, h = img.size
        return [img.getpixel(p) for p in ((5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6))]


def test_crop_has_the_monitor_size(tmp_path):
    source = quadrants(tmp_path / "src.png")
    out = tmp_path / "out.png"
    render.crop(source, Framing(90, 160, 400, 200), out)
    assert render.image_size(out) == (90, 160)


def test_crop_shows_the_framed_part(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(100, 100, 400, 200)                         # square monitor: sees half the width
    f.move_to(0, 0)                                         # left half: red over blue
    render.crop(source, f, tmp_path / "left.png")
    assert corners(tmp_path / "left.png") == [RED, RED, BLUE, BLUE]
    f.move_to(-9999, 0)                                     # right half: green over white
    render.crop(source, f, tmp_path / "right.png")
    assert corners(tmp_path / "right.png") == [GREEN, GREEN, WHITE, WHITE]


def test_mirror_and_flip_are_applied(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(100, 100, 400, 200)
    f.move_to(0, 0)                                         # left half: red over blue
    f.mirror(horizontal=True)                               # mirroring keeps the same half
    f.mirror(horizontal=False)                              # upside down: blue on top
    render.crop(source, f, tmp_path / "out.png")
    assert corners(tmp_path / "out.png") == [BLUE, BLUE, RED, RED]


def test_rotation_turns_clockwise(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(200, 400, 400, 200)                         # portrait monitor, exact fit once turned
    f.rotate()
    render.crop(source, f, tmp_path / "out.png")
    # Turned clockwise, the left column (red, blue) becomes the top row (blue, red).
    assert corners(tmp_path / "out.png") == [BLUE, RED, WHITE, GREEN]


def test_still_images_only(tmp_path):
    still = quadrants(tmp_path / "still.png")
    frames = [Image.new("RGB", (10, 10), c) for c in (RED, GREEN)]
    frames[0].save(tmp_path / "anim.gif", save_all=True, append_images=frames[1:])
    (tmp_path / "video.mp4").write_bytes(b"not an image")
    assert render.is_still_image(still)
    assert not render.is_still_image(tmp_path / "anim.gif")
    assert not render.is_still_image(tmp_path / "video.mp4")
    assert not render.is_still_image(tmp_path / "missing.png")

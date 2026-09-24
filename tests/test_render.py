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


def test_zoomed_out_with_a_color_fill(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(100, 100, 400, 200)
    f.zoom_at(f.fit_zoom / f.zoom, 0, 0)                    # 100x50: gaps above and below
    f.move_to(0, 25)                                        # centered vertically
    f.fill, f.fill_color = "color", "#ff00ff"
    render.crop(source, f, tmp_path / "out.png")
    with Image.open(tmp_path / "out.png") as out:
        assert out.size == (100, 100)
        assert out.getpixel((50, 5)) == (255, 0, 255)        # gap above
        assert out.getpixel((50, 94)) == (255, 0, 255)       # gap below
        assert out.getpixel((10, 30)) == RED                 # image, top left quadrant
        assert out.getpixel((90, 70)) == WHITE               # image, bottom right quadrant


def test_zoomed_out_with_blur_uses_the_image_colors(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(100, 100, 400, 200)
    f.zoom_at(0.01, 0, 0)
    render.crop(source, f, tmp_path / "out.png")
    with Image.open(tmp_path / "out.png") as out:
        gap = out.getpixel((50, 2)) if f.y > 0 else out.getpixel((50, 97))
        assert gap != (0, 0, 0) and max(gap) > 40            # a blurred mix, not black


def test_stronger_blur_is_smoother(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(400, 800, 400, 200)
    f.zoom_at(0.01, 0, 0)                                   # 400x200 image, gaps above and below
    f.move_to(0, 600)                                       # image at the bottom, gap on top

    def spread(blur):
        f.blur = blur
        render.crop(source, f, tmp_path / f"blur{blur}.png")
        with Image.open(tmp_path / f"blur{blur}.png") as out:
            row = [out.getpixel((x, 20))[1] for x in range(400)]
        return max(abs(a - b) for a, b in zip(row, row[1:]))    # sharpest step in green

    assert spread(160) < spread(16)


def test_sharp_backdrop_shows_the_part_it_frames(tmp_path):
    source = quadrants(tmp_path / "src.png")
    f = Framing(100, 100, 400, 200)
    f.zoom_at(0.01, 0, 0)
    f.move_to(0, 50)                                        # image at the bottom, gap on top
    f.blur = 0
    f.backdrop.move_to(0, 0)                                # backdrop: left half, red over blue
    render.crop(source, f, tmp_path / "left.png")
    f.backdrop.move_to(-9999, 0)                            # backdrop: right half, green over white
    render.crop(source, f, tmp_path / "right.png")
    with Image.open(tmp_path / "left.png") as left, Image.open(tmp_path / "right.png") as right:
        assert left.getpixel((50, 10)) == RED
        assert right.getpixel((50, 10)) == GREEN

"""One picture across every monitor: the pieces, what they show, and coming back to it."""

import random

import pytest
from PIL import Image, ImageChops

from wallframe import render, span
from wallframe.daemons import Output
from wallframe.framing import Framing
from wallframe.layouts import Layouts
from wallframe.monitor import Monitor
from wallframe.state import Store


class FakeDaemon:
    def __init__(self):
        self.shown = {}

    def set_image(self, output, path):
        self.shown[output] = path


def stripes(path, size=(400, 100)):
    """Sharp 5-pixel stripes both ways, so a piece one pixel off shows it."""
    img = Image.new("RGB", size)
    img.putdata([(x // 5 % 2 * 255, y // 5 % 2 * 255, 128)
                 for y in range(size[1]) for x in range(size[0])])
    img.save(path)
    return str(path)


def two_monitors(tmp_path, right=(200, 100), image=None):
    """DP-1 and DP-2 side by side, 200x100 logical each; DP-2's real pixels are `right`."""
    image = image or stripes(tmp_path / "wide.png")
    store = Store(tmp_path / "data")
    monitors = [Monitor(Output("DP-1", 200, 100, image), store),
                Monitor(Output("DP-2", *right, image), store)]
    positions = {"DP-1": (0, 0, 200, 100), "DP-2": (200, 0, 200, 100)}
    return monitors, positions


def apply(whole, daemon):
    for monitor, piece in whole.pieces():
        monitor.take(piece)
        monitor.show(daemon, monitor.make_crop(piece.source, piece.framing))


def test_it_needs_two_monitors_and_where_they_are(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    assert span.make(monitors, positions) is not None
    assert span.make(monitors[:1], positions) is None
    assert span.make(monitors, {"DP-1": positions["DP-1"]}) is None


def test_the_span_is_the_box_around_every_monitor(tmp_path):
    monitors, _ = two_monitors(tmp_path)
    # DP-2 sits lower: the box is taller than either, with a corner no monitor shows.
    whole = span.make(monitors, {"DP-1": (-200, 0, 200, 100), "DP-2": (0, 50, 200, 100)})
    assert (whole.width, whole.height) == (400, 150)
    assert whole.frames() == [("DP-1", 0, 0, 200, 100), ("DP-2", 200, 50, 200, 100)]


def test_the_pieces_line_up_into_the_whole_picture(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    whole.framing.zoom_at(1.5, 130, 40)                  # anything but the default
    expected = render.compose(whole.image, whole.framing)  # the span as one 400x100 crop
    for monitor, piece in whole.pieces():
        x = whole.places[monitor.name][0]
        shown = render.compose(piece.source, piece.framing)
        assert shown.size == (200, 100)
        assert _close(shown, expected.crop((x, 0, x + 200, 100)))
    # And the check is sharp enough to catch a piece one pixel off.
    assert not _close(shown, expected.crop((x - 1, 0, x + 199, 100)))


def test_a_scaled_monitor_gets_its_piece_at_its_own_resolution(tmp_path):
    monitors, positions = two_monitors(tmp_path, right=(400, 200))  # DP-2 at 200%
    whole = span.make(monitors, positions)   # the 400x100 picture, exactly on the span
    _dp1, (_dp2, piece) = whole.pieces()
    shown = render.compose(piece.source, piece.framing)
    # Its right half, enlarged from the picture itself, not from a 200x100 crop.
    with Image.open(whole.image) as img:
        expected = img.convert("RGB").resize((400, 200), Image.LANCZOS, box=(200, 0, 400, 100))
    assert _close(shown, expected)


def test_blur_is_measured_on_each_monitor(tmp_path):
    monitors, positions = two_monitors(tmp_path, right=(400, 200))
    whole = span.make(monitors, positions)
    whole.framing.blur = 40
    (_m1, one), (_m2, two) = whole.pieces()
    assert (one.framing.blur, two.framing.blur) == (40, 80)


def test_a_piece_beside_the_image_is_not_covered(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    whole.framing.zoom_at(0.4, 0, 0)                      # small, in DP-1's corner
    whole.framing.move_to(0, 0)
    (_m1, one), (_m2, two) = whole.pieces()
    assert not one.framing.covers and not two.framing.covers
    # The image misses DP-2 entirely: it shows only the fill, and does not fail.
    whole.framing.fill, whole.framing.fill_color = "color", "#ff0000"
    _one, (_m2, two) = whole.pieces()
    shown = render.compose(two.source, two.framing)
    assert shown.getcolors() == [(200 * 100, (255, 0, 0))]


def test_a_piece_comes_back_exactly_as_it_was(tmp_path):
    f = Framing(400, 100, 400, 100)
    f.zoom_at(0.5, 0, 0)
    piece = f.piece(200, 0, 200, 100, 200, 100)   # left of its monitor: never clamped
    assert piece.x < 0 and piece.spanned
    again = Framing(200, 100, 400, 100)
    again.restore(piece.to_dict())
    assert again.key() == piece.key() and again.spanned
    again.move_to(again.x, again.y)               # edited on its own monitor: clamped
    assert not again.spanned and "span" not in again.to_dict()


def test_a_piece_on_a_monitor_of_another_size_is_framed_again(tmp_path):
    f = Framing(400, 100, 400, 100)
    piece = f.piece(200, 0, 200, 100, 200, 100)
    other = Framing(300, 100, 400, 100)
    other.restore(piece.to_dict())
    assert not other.spanned and other.covers


def test_applied_it_is_live_until_a_monitor_shows_something_else(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    assert not whole.live
    daemon = FakeDaemon()
    apply(whole, daemon)
    whole.mark_applied()
    assert whole.live and set(daemon.shown) == {"DP-1", "DP-2"}
    monitors[1].edit("mirror")
    monitors[1].apply(daemon)
    assert not whole.live


def test_reopening_resumes_the_span_on_the_monitors(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    whole.framing.zoom_at(2, 300, 50)
    daemon = FakeDaemon()
    apply(whole, daemon)
    whole.mark_applied()
    store = monitors[0].store
    store.remember_span(whole.snapshot())

    # As wallframe starts again: each monitor reads what it shows, then the span.
    again = [Monitor(Output(name, m.width, m.height, daemon.shown[name]), store)
             for name, m in (("DP-1", monitors[0]), ("DP-2", monitors[1]))]
    resumed = span.make(again, positions, store.span())
    assert resumed.live
    assert resumed.framing.key() == whole.framing.key()
    assert all(m.framing.spanned for m in again)


def test_a_saved_span_whose_picture_is_gone_starts_from_the_first_monitor(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    saved = span.make(monitors, positions).snapshot()
    saved["source"] = str(tmp_path / "gone.png")
    whole = span.make(monitors, positions, saved)
    assert whole.image == monitors[0].image


def test_a_layout_keeps_the_span_and_each_piece(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    whole.framing.zoom_at(1.5, 100, 50)
    layouts = Layouts(tmp_path / "layouts")
    layout = layouts.save("Wide", monitors, positions, whole)
    assert layout.span["monitors"] == ["DP-1", "DP-2"]
    for monitor in monitors:
        entry = layout.monitors[monitor.name]
        assert entry["span"]
        assert monitor.saved_framing(entry).key() == whole.piece(monitor).key()
    renamed = layouts.rename(layout, "Wider")
    assert renamed.span == layout.span
    assert whole.image in layouts.images_in_use()


@pytest.mark.parametrize("seed", range(60))
def test_any_span_renders_on_every_monitor(tmp_path, seed):
    """Random arrangements, scales and framings through the whole render path."""
    rng = random.Random(seed)
    image = tmp_path / "src.png"
    Image.new("RGB", (rng.randint(20, 600), rng.randint(20, 600)), (90, 40, 200)).save(image)
    store = Store(tmp_path / "data")
    monitors, positions, x = [], {}, 0
    for i in range(rng.randint(2, 3)):
        w, h = rng.randint(30, 120), rng.randint(30, 120)
        scale = rng.choice([1, 1.25, 2])
        monitors.append(Monitor(Output(f"M-{i}", round(w * scale), round(h * scale),
                                       str(image)), store))
        positions[f"M-{i}"] = (x, rng.randint(-60, 60), w, h)
        x += w
    whole = span.make(monitors, positions)
    f = whole.framing
    f.zoom_at(rng.choice([0.1, 0.5, 1, 3]), rng.uniform(0, f.monitor_w),
              rng.uniform(0, f.monitor_h))
    f.move_to(rng.uniform(-500, 500), rng.uniform(-500, 500))
    f.fill, f.blur = rng.choice(["blur", "color"]), rng.choice([0, 16, 160])
    for monitor, piece in whole.pieces():
        assert render.compose(piece.source, piece.framing).size == (monitor.width,
                                                                    monitor.height)


def _close(a, b, tolerance=8):
    """True when no pixel differs by more than `tolerance`: resampling at the edges
    of a piece may round a little differently from the whole."""
    return max(high for _low, high in ImageChops.difference(a, b).getextrema()) <= tolerance

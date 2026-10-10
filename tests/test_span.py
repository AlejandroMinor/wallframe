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


# --- Real sizes: one picture at one size across monitors of different densities

# A 27" 1440p and a 24" 1080p side by side, both at 100%, tops lined up on the desktop.
DESK = {"DP-1": (0, 0, 2560, 1440), "DP-2": (2560, 0, 1920, 1080)}
MM = {"DP-1": (597, 336), "DP-2": (531, 299)}


def desk_monitors(tmp_path, positions=DESK):
    image = stripes(tmp_path / "wide.png", (1200, 300))
    store = Store(tmp_path / "data")
    return [Monitor(Output(name, w, h, image), store) for name, (_x, _y, w, h) in
            positions.items()]


def per_mm(piece, monitor, width_mm):
    """Picture pixels per millimeter on the monitor: the same everywhere when it fits."""
    return (monitor.width / width_mm) / piece.framing.zoom


def test_with_real_sizes_the_picture_keeps_its_size_across_monitors(tmp_path):
    monitors = desk_monitors(tmp_path)
    whole = span.make(monitors, DESK, sizes=MM)
    assert whole.real_sizes
    (one, a), (two, b) = whole.pieces()
    assert per_mm(a, one, 597) == pytest.approx(per_mm(b, two, 531), rel=1e-3)
    # Without them, the 24" would show it about 19% larger.
    plain = span.make(monitors, DESK)
    (one, a), (two, b) = plain.pieces()
    assert per_mm(b, two, 531) / per_mm(a, one, 597) == pytest.approx(0.84, abs=0.01)


def test_monitors_lined_up_by_their_tops_stay_lined_up(tmp_path):
    whole = span.make(desk_monitors(tmp_path), DESK, sizes=MM)
    (_one, a), (_two, b) = whole.pieces()
    # The picture row at each monitor's top edge is the same row.
    assert -a.framing.y / a.framing.zoom == pytest.approx(-b.framing.y / b.framing.zoom)
    # And the second starts where the first ends, with no gap or overlap.
    first, second = whole.places["DP-1"], whole.places["DP-2"]
    assert second[0] == pytest.approx(first[0] + first[2])


def test_centered_monitors_stay_centered_at_their_real_size(tmp_path):
    centered = {"DP-1": (0, 0, 2560, 1440), "DP-2": (2560, 180, 1920, 1080)}
    whole = span.make(desk_monitors(tmp_path, centered), centered, sizes=MM)
    _x, y1, _w, h1 = whole.places["DP-1"]
    _x, y2, _w, h2 = whole.places["DP-2"]
    assert y1 + h1 / 2 == pytest.approx(y2 + h2 / 2)


def test_a_portrait_monitor_turns_its_size(tmp_path):
    turned = {"DP-1": (0, 0, 2560, 1440), "DP-2": (2560, 0, 1080, 1920)}
    whole = span.make(desk_monitors(tmp_path, turned), turned, sizes=MM)
    assert whole.real_sizes
    _x, _y, w, h = whole.places["DP-2"]
    assert h > w


def test_a_size_that_does_not_fit_the_monitor_is_not_trusted(tmp_path):
    monitors = desk_monitors(tmp_path)
    wrong = {"DP-1": (597, 336), "DP-2": (400, 100)}         # a TV's made-up shape
    whole = span.make(monitors, DESK, sizes=wrong)
    assert not whole.real_sizes and whole.places == DESK
    assert not span.make(monitors, DESK, sizes={"DP-1": (597, 336)}).real_sizes


def test_moving_a_monitor_leaves_the_picture_where_it_was(tmp_path):
    monitors = desk_monitors(tmp_path)
    whole = span.make(monitors, DESK, sizes=MM)
    before = whole.piece(monitors[0]).key()
    x, y, _w, _h = whole.places["DP-2"]
    whole.move_monitor("DP-2", x, y - 40)          # above the top: the box grows upward
    assert whole.top < 0
    assert whole.piece(monitors[0]).key() == before   # DP-1 still shows the same part
    assert whole.touched


def test_a_dragged_monitor_meets_the_edge_of_another(tmp_path):
    whole = span.make(desk_monitors(tmp_path), DESK, sizes=MM)
    x, y, _w, _h = whole.places["DP-2"]
    assert whole.snap("DP-2", x + 6, y - 7, reach=10) == (pytest.approx(x), pytest.approx(y))
    assert whole.snap("DP-2", x + 60, y + 60, reach=10) == (x + 60, y + 60)


def test_discard_and_reset_put_the_monitors_back(tmp_path):
    monitors = desk_monitors(tmp_path)
    whole = span.make(monitors, DESK, sizes=MM)
    start = dict(whole.places)
    whole.move_monitor("DP-2", 3000, 300)
    whole.discard_edit()
    assert whole.places == start and not whole.touched
    whole.move_monitor("DP-2", 3000, 300)
    whole.reset_places()
    assert whole.places == whole.default


def test_the_places_come_back_with_the_span(tmp_path):
    monitors = desk_monitors(tmp_path)
    whole = span.make(monitors, DESK, sizes=MM)
    whole.move_monitor("DP-2", 2700, 150)
    apply(whole, FakeDaemon())  # the monitors show it, so it is the span that comes back
    whole.mark_applied()
    saved = whole.snapshot()
    again = span.make(monitors, DESK, saved, MM)
    assert again.places["DP-2"][:2] == (2700, 150)
    assert again.framing.key() == whole.framing.key()
    # Saved for other monitors, the places are left out.
    saved["places"] = {"HDMI-A-1": [0, 0, 10, 10]}
    assert span.make(monitors, DESK, saved, MM).places == whole.default


def test_a_turned_monitor_shows_the_middle_of_its_width(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    assert whole.squeeze("DP-2") == 1
    whole.set_yaw("DP-2", 60)
    assert whole.squeeze("DP-2") == pytest.approx(0.5)
    frames = {name: (x, w) for name, x, _y, w, _h in whole.frames()}
    assert frames["DP-2"] == pytest.approx((250 - whole.left, 100))   # the middle half of 200..400
    assert frames["DP-1"] == (0, 200)
    assert whole.touched                                 # waits for Apply, like a move
    again = span.make(monitors, positions, whole.snapshot())
    assert again.yaws == {"DP-2": 60}
    whole.discard_edit()
    assert not whole.yaws and not whole.touched
    whole.set_yaw("DP-2", 200)
    assert whole.yaws["DP-2"] == span.YAW_LIMIT
    whole.set_yaw("DP-2", -60)                           # the other way: twice as much, squeezed
    assert whole.squeeze("DP-2") == pytest.approx(2)
    assert whole.set_yaw("DP-2", -200) is None and whole.yaws["DP-2"] == -span.YAW_LIMIT
    whole.reset_places()
    assert not whole.yaws


def test_a_turned_monitor_stretches_its_middle_across_the_screen(tmp_path):
    ramp = tmp_path / "ramp.png"                        # brightness grows with x, 0 to 255
    img = Image.new("RGB", (400, 100))
    img.putdata([(x * 255 // 399,) * 3 for _y in range(100) for x in range(400)])
    img.save(ramp)
    monitors, positions = two_monitors(tmp_path, image=str(ramp))
    whole = span.make(monitors, positions)
    flat = render.compose(str(ramp), whole.piece(monitors[1]))
    assert flat.getpixel((0, 50))[0] == pytest.approx(128, abs=2)      # DP-2 shows x 200..400
    assert flat.getpixel((199, 50))[0] == pytest.approx(255, abs=2)
    whole.set_yaw("DP-2", 60)
    turned = render.compose(str(ramp), whole.piece(monitors[1]))
    assert turned.size == flat.size == (200, 100)                      # still the whole screen
    assert turned.getpixel((0, 50))[0] == pytest.approx(159, abs=3)    # x 250..350, stretched
    assert turned.getpixel((199, 50))[0] == pytest.approx(223, abs=3)
    whole.set_yaw("DP-2", -60)                     # x 100..500: twice its width, squeezed in
    away = render.compose(str(ramp), whole.piece(monitors[1]))
    assert away.size == (200, 100)
    assert away.getpixel((0, 50))[0] == pytest.approx(64, abs=3)       # x 100 of 400


def test_a_span_the_monitors_no_longer_show_follows_them(tmp_path):
    monitors = desk_monitors(tmp_path)
    whole = span.make(monitors, DESK, sizes=MM)
    whole.move_monitor("DP-2", 2700, 150)
    saved = whole.snapshot()
    elsewhere = stripes(tmp_path / "elsewhere.png", (300, 120))
    for monitor in monitors:
        monitor.open_image(elsewhere)
        monitor.mark_applied()
    again = span.make(monitors, DESK, saved, MM)
    assert again.image == elsewhere                      # what the monitors show, not the old one
    assert again.places["DP-2"][:2] == (2700, 150)       # but where they stand is kept
    again.follow(monitors[1])
    assert again.image == monitors[1].image


def test_the_gaps_say_how_far_each_neighbor_is(tmp_path):
    monitors, positions = two_monitors(tmp_path)
    whole = span.make(monitors, positions)
    assert whole.gaps("DP-1") == {"right": ("DP-2", 0)}
    whole.move_monitor("DP-2", 230, 0)
    assert whole.gaps("DP-2") == {"left": ("DP-1", 30)}
    whole.move_monitor("DP-2", 180, 0)
    assert whole.gaps("DP-2")["left"][1] == -20          # overlapping
    whole.move_monitor("DP-2", 230, 120)                 # entirely below: no neighbor
    assert whole.gaps("DP-2") == {}

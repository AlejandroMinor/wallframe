"""Tests for the pure framing geometry: no GTK, no files, no daemon."""

import pytest

from wallframe.framing import MAX_ZOOM, Framing


def approx_box(box):
    return pytest.approx(box, abs=1e-6)


def portrait():
    """A 1080x1920 portrait monitor showing a 3840x2160 landscape image."""
    return Framing(1080, 1920, 3840, 2160)


def test_starts_covering_the_monitor_centred():
    f = portrait()
    assert f.relative_zoom == 1
    left, top, right, bottom = f.crop_box()
    assert (top, bottom) == approx_box((0, 2160))          # full height used
    assert left == pytest.approx(3840 - right)              # same margin on both sides
    assert (right - left) / (bottom - top) == pytest.approx(1080 / 1920)


def test_mirror_shows_the_same_region_mirrored():
    f = portrait()
    f.move_to(-200, 0)                                      # off centre, so it shows
    left, top, right, bottom = f.crop_box()
    f.mirror(horizontal=True)
    assert f.flip_h
    assert f.crop_box() == approx_box((f.image_w - right, top, f.image_w - left, bottom))


def test_mirror_twice_is_a_no_op():
    f = portrait()
    f.zoom_at(2, 100, 300)
    before = f.key()
    f.mirror(horizontal=False)
    f.mirror(horizontal=False)
    assert f.key() == before


def test_rotation_swaps_the_image_size_and_recentres():
    f = portrait()
    f.move_to(-500, 0)
    f.rotate()
    assert (f.rotation, f.image_w, f.image_h) == (90, 2160, 3840)
    assert f.relative_zoom == 1
    left, _, right, _ = f.crop_box()
    assert left == pytest.approx(f.image_w - right)


def test_four_rotations_come_back_to_the_start():
    f = portrait()
    start = f.key()
    for _ in range(4):
        f.rotate()
    assert f.key() == start


def test_reset_drops_mirror_rotation_and_position():
    f = portrait()
    f.mirror(horizontal=True)
    f.rotate()
    f.zoom_at(3, 0, 0)
    f.reset()
    assert f.key() == portrait().key()


def test_moving_never_uncovers_the_monitor():
    f = portrait()
    f.move_to(5000, 5000)
    assert (f.x, f.y) == (0, 0)
    f.move_to(-99999, -99999)
    assert f.x == pytest.approx(f.monitor_w - f.image_w * f.zoom)
    assert f.y == pytest.approx(f.monitor_h - f.image_h * f.zoom)


def test_zoom_keeps_the_point_under_the_pointer():
    f = portrait()
    px, py = 540, 960                                       # monitor centre
    spot = ((px - f.x) / f.zoom, (py - f.y) / f.zoom)       # image pixel under it
    f.zoom_at(2, px, py)
    assert ((px - f.x) / f.zoom, (py - f.y) / f.zoom) == approx_box(spot)


def test_zoom_stays_between_cover_and_max():
    f = portrait()
    f.zoom_at(0.1, 0, 0)
    assert f.relative_zoom == pytest.approx(1)
    f.zoom_at(1000, 0, 0)
    assert f.relative_zoom == pytest.approx(MAX_ZOOM)


def test_saved_framing_restores_exactly():
    f = portrait()
    f.rotate()
    f.mirror(horizontal=True)
    f.zoom_at(1.7, 200, 400)
    g = portrait()
    g.restore(f.to_dict())
    assert g.key() == f.key()


def test_restore_clamps_when_the_monitor_changed():
    f = portrait()
    f.zoom_at(4, 0, 0)
    f.move_to(-99999, -99999)
    smaller = Framing(720, 1280, 3840, 2160)
    smaller.restore(f.to_dict())
    assert smaller.x >= smaller.monitor_w - smaller.image_w * smaller.zoom
    assert smaller.y >= smaller.monitor_h - smaller.image_h * smaller.zoom

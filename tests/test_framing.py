"""Tests for the pure framing geometry: no GTK, no files, no daemon."""

import pytest

from wallframe.framing import MAX_ZOOM, SHRINK_LIMIT, Framing


def approx_box(box):
    return pytest.approx(box, abs=1e-6)


def fit(f):
    """Zooms to exactly where the whole image fits the monitor."""
    f.zoom_at(f.fit_zoom / f.zoom, 0, 0)
    return f


def portrait():
    """A 1080x1920 portrait monitor showing a 3840x2160 landscape image."""
    return Framing(1080, 1920, 3840, 2160)


def test_starts_covering_the_monitor_centered():
    f = portrait()
    assert f.relative_zoom == 1
    left, top, right, bottom = f.crop_box()
    assert (top, bottom) == approx_box((0, 2160))          # full height used
    assert left == pytest.approx(3840 - right)              # same margin on both sides
    assert (right - left) / (bottom - top) == pytest.approx(1080 / 1920)


def test_mirror_shows_the_same_region_mirrored():
    f = portrait()
    f.move_to(-200, 0)                                      # off center, so it shows
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


def test_rotation_swaps_the_image_size_and_recenters():
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
    px, py = 540, 960                                       # monitor center
    spot = ((px - f.x) / f.zoom, (py - f.y) / f.zoom)       # image pixel under it
    f.zoom_at(2, px, py)
    assert ((px - f.x) / f.zoom, (py - f.y) / f.zoom) == approx_box(spot)


def test_zoom_stays_between_the_shrink_limit_and_max():
    f = portrait()
    f.zoom_at(0.01, 0, 0)
    assert f.zoom == pytest.approx(f.fit_zoom * SHRINK_LIMIT)
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


def test_zooming_out_leaves_gaps():
    f = portrait()
    assert f.covers
    f.zoom_at(0.5, 540, 960)
    assert not f.covers


def test_a_smaller_image_stays_inside_the_monitor():
    f = portrait()
    f.zoom_at(0.01, 0, 0)                                   # 1080 wide, 607 high: gaps above and below
    f.move_to(-5000, 5000)
    assert f.x == pytest.approx(0)                          # width still fills: covers that axis
    assert f.y == pytest.approx(f.monitor_h - f.image_h * f.zoom)   # height: stops at the bottom edge


def test_placement_is_the_whole_monitor_when_covering():
    f = portrait()
    f.move_to(-300, 0)
    source, target = f.placement()
    assert target == (0, 0, 1080, 1920)
    assert source == approx_box(f.crop_box())


def test_placement_leaves_the_gaps_out():
    f = fit(portrait())
    f.move_to(0, 100)
    source, target = f.placement()
    left, top, right, bottom = target
    assert (left, top, right) == (0, 100, 1080)
    assert bottom == round(100 + f.image_h * f.zoom)
    assert source == approx_box((0, 0, f.image_w, f.image_h))


def test_fill_counts_as_a_change_only_with_gaps():
    f = portrait()
    before = f.key()
    f.fill = "color"
    assert f.key() == before                                # covering: the fill is not visible
    f.zoom_at(0.5, 0, 0)
    with_color = f.key()
    f.fill_color = "#ff0000"
    assert f.key() != with_color


def test_fill_is_saved_and_restored():
    f = portrait()
    f.zoom_at(0.5, 0, 0)
    f.fill, f.fill_color = "color", "#123456"
    g = portrait()
    g.restore(f.to_dict())
    assert g.key() == f.key()


def test_old_saved_state_defaults_to_blur():
    f = portrait()
    f.restore({"zoom": 1, "x": 0, "y": 0})
    assert (f.fill, f.fill_color, f.blur) == ("blur", "#000000", 64)


def test_blur_strength_counts_only_for_a_visible_blur():
    f = portrait()
    f.zoom_at(0.5, 0, 0)
    before = f.key()
    f.blur = 120
    assert f.key() != before
    f.fill = "color"
    with_color = f.key()
    f.blur = 30
    assert f.key() == with_color                            # color fill: blur does not show


def test_backdrop_starts_centered_and_always_covers():
    f = portrait()
    b = f.backdrop
    assert b.key()[:6] == portrait().key()[:6]              # same start as the image
    b.zoom_at(0.01, 0, 0)
    assert b.covers                                         # it never leaves gaps itself


def test_backdrop_follows_mirror_and_rotation():
    f = portrait()
    f.mirror(horizontal=True)
    f.rotate()
    assert (f.backdrop.flip_h, f.backdrop.rotation) == (True, 90)
    f.reset()
    assert (f.backdrop.flip_h, f.backdrop.rotation) == (False, 0)


def test_moving_the_backdrop_counts_only_with_a_visible_blur():
    f = portrait()
    before = f.key()
    f.backdrop.zoom_at(2, 0, 0)
    assert f.key() == before                                # image covers: no backdrop visible
    f.zoom_at(0.5, 0, 0)
    blurred = f.key()
    f.backdrop.move_to(-500, 0)
    assert f.key() != blurred


def test_backdrop_is_saved_and_restored():
    f = portrait()
    f.zoom_at(0.5, 0, 0)
    f.backdrop.zoom_at(3, 100, 200)
    f.blur = 0
    g = portrait()
    g.restore(f.to_dict())
    assert g.key() == f.key()


def test_same_shape_image_can_shrink_inside_the_monitor():
    f = Framing(2560, 1440, 3840, 2160)                     # 16:9 on 16:9: fits at 100%
    assert f.fit_zoom == pytest.approx(f.min_zoom)
    f.zoom_at(0.5, 1280, 720)
    assert not f.covers
    source, (left, top, right, bottom) = f.placement()
    assert (left, top, right, bottom) == (640, 360, 1920, 1080)   # gaps on all four sides


def test_center_keeps_the_zoom():
    f = portrait()
    f.zoom_at(0.5, 0, 0)
    f.move_to(0, 0)
    zoom = f.zoom
    f.center()
    assert f.zoom == zoom
    left, top, right, bottom = f.placement()[1]
    assert left == pytest.approx(f.monitor_w - right, abs=1)   # same margin left and right
    assert top == pytest.approx(f.monitor_h - bottom, abs=1)   # and top and bottom


def test_backdrop_of_a_same_shape_image_needs_zoom_to_move():
    f = Framing(2560, 1440, 3840, 2160)                     # 16:9 on 16:9
    assert not f.backdrop.can_move
    f.backdrop.zoom_at(1.2, 1280, 720)
    assert f.backdrop.can_move

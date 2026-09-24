"""Tests for one monitor's edit and apply cycle, with a fake daemon."""

import os

import pytest
from PIL import Image

from wallframe.daemons import Output
from wallframe.monitor import Monitor
from wallframe.state import Store


class FakeDaemon:
    def __init__(self):
        self.shown = {}

    def set_image(self, output, path):
        self.shown[output] = path


def portrait_monitor(tmp_path, image=None):
    if image is None:
        image = tmp_path / "wallpaper.png"
        Image.new("RGB", (400, 200), (10, 20, 30)).save(image)
    return Monitor(Output("DP-1", 90, 160, str(image)), Store(tmp_path / "data"), "AOC 24B3HM")


def test_starts_untouched(tmp_path):
    m = portrait_monitor(tmp_path)
    assert not m.touched
    assert m.portrait
    assert m.model == "AOC 24B3HM"


def test_edit_marks_it_touched(tmp_path):
    m = portrait_monitor(tmp_path)
    m.edit("mirror")
    assert m.touched
    m.edit("mirror")
    assert not m.touched                                     # back to what the monitor shows


def test_apply_sets_the_crop_and_clears_the_mark(tmp_path):
    m = portrait_monitor(tmp_path)
    daemon = FakeDaemon()
    m.edit("rotate")
    m.apply(daemon)
    assert not m.touched
    with Image.open(daemon.shown["DP-1"]) as crop:
        assert crop.size == (90, 160)


def test_reopening_resumes_from_the_original(tmp_path):
    m = portrait_monitor(tmp_path)
    daemon = FakeDaemon()
    m.edit("flip")
    m.framing.zoom_at(2, 10, 10)
    m.apply(daemon)

    again = portrait_monitor(tmp_path, image=daemon.shown["DP-1"])   # the monitor shows the crop
    assert again.image == m.image
    assert again.framing.key() == m.framing.key()
    assert not again.touched


def test_preview_follows_rotation(tmp_path):
    m = portrait_monitor(tmp_path)
    assert m.preview().size == (400, 200)
    m.edit("rotate")
    assert m.preview().size == (200, 400)


def other_wallpaper(tmp_path, name="new.png"):
    path = tmp_path / name
    Image.new("RGB", (300, 300), (200, 100, 0)).save(path)
    return str(path)


def test_notices_a_wallpaper_set_elsewhere(tmp_path):
    m = portrait_monitor(tmp_path)
    assert not m.changed(m.shown)
    assert m.changed(other_wallpaper(tmp_path))


def test_own_apply_is_not_a_change(tmp_path):
    m = portrait_monitor(tmp_path)
    daemon = FakeDaemon()
    m.edit("mirror")
    m.apply(daemon)
    assert not m.changed(daemon.shown["DP-1"])


def test_load_switches_to_the_new_wallpaper(tmp_path):
    m = portrait_monitor(tmp_path)
    m.edit("rotate")
    new = other_wallpaper(tmp_path)
    m.load(Output("DP-1", 90, 160, new))
    assert m.image == new
    assert not m.touched
    assert not m.changed(new)


def test_ignored_change_is_not_asked_again(tmp_path):
    m = portrait_monitor(tmp_path)
    new = other_wallpaper(tmp_path)
    m.ignored = new
    assert not m.changed(new)
    assert m.changed(other_wallpaper(tmp_path, "newer.png"))


def test_discard_edit_goes_back_to_what_is_shown(tmp_path):
    m = portrait_monitor(tmp_path)
    m.edit("rotate")
    m.framing.zoom_at(3, 0, 0)
    m.discard_edit()
    assert not m.touched


def test_failed_apply_keeps_the_crop_the_monitor_shows(tmp_path):
    m = portrait_monitor(tmp_path)
    daemon = FakeDaemon()
    m.edit("mirror")
    m.apply(daemon)
    shown = daemon.shown["DP-1"]
    m.edit("rotate")
    os.remove(m.image)                                      # the original disappears
    with pytest.raises(FileNotFoundError):
        m.apply(daemon)
    assert os.path.exists(shown)                            # still there for the next login
    assert daemon.shown["DP-1"] == shown
    assert m.touched                                        # the edit is still pending


def monitor_on(tmp_path, name, width, height, image):
    return Monitor(Output(name, width, height, str(image)), Store(tmp_path / "data"))


def test_copy_everything_between_same_shape_monitors(tmp_path):
    image = tmp_path / "wallpaper.png"
    Image.new("RGB", (4000, 2000)).save(image)
    small = monitor_on(tmp_path, "DP-1", 1080, 1920, image)
    large = monitor_on(tmp_path, "DP-3", 1440, 2560, image)  # same 9:16 shape, bigger
    small.edit("mirror")
    small.framing.zoom_at(0.6, 300, 900)
    small.framing.fill, small.framing.blur = "blur", 20
    small.framing.backdrop.zoom_at(2, 500, 500)
    assert large.copy_limits(small) is None
    large.copy_from(small)
    for a, b in ((small.framing, large.framing), (small.framing.backdrop, large.framing.backdrop)):
        assert b.flip_h == a.flip_h
        assert b.relative_zoom == pytest.approx(a.relative_zoom)
        assert b.x / b.monitor_w == pytest.approx(a.x / a.monitor_w)   # same place, in proportion
        assert b.y / b.monitor_h == pytest.approx(a.y / a.monitor_h)
    assert large.framing.blur == 20


def test_copy_only_the_fill_from_another_image_or_shape(tmp_path):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (4000, 2000)).save(first)
    Image.new("RGB", (4000, 2000)).save(second)
    source = monitor_on(tmp_path, "DP-1", 1080, 1920, first)
    other_image = monitor_on(tmp_path, "DP-2", 1080, 1920, second)
    other_shape = monitor_on(tmp_path, "DP-3", 2560, 1440, first)
    source.framing.zoom_at(0.6, 0, 0)
    source.framing.fill, source.framing.fill_color = "color", "#123456"
    for target, reason in ((other_image, "different image"), (other_shape, "different screen shape")):
        assert target.copy_limits(source) == reason
        target.copy_from(source)
        assert (target.framing.fill, target.framing.fill_color) == ("color", "#123456")
        assert target.framing.relative_zoom == pytest.approx(1)    # position untouched

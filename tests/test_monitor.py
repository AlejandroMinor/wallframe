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

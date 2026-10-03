"""Tests for saved layouts: always in a temporary folder, never in ~/.local/share."""

import os

import pytest
from PIL import Image

from wallframe.daemons import Output
from wallframe.layouts import PREVIEW_SIZE, Layouts
from wallframe.monitor import Monitor
from wallframe.state import Store


def wallpaper(tmp_path, name="wallpaper.png", size=(400, 200), color="red"):
    path = tmp_path / name
    Image.new("RGB", size, color).save(path)
    return str(path)


def monitor_on(tmp_path, name, width, height, image):
    return Monitor(Output(name, width, height, image), Store(tmp_path / "data"))


def two_monitors(tmp_path):
    return [monitor_on(tmp_path, "DP-1", 1920, 1080, wallpaper(tmp_path, "a.png")),
            monitor_on(tmp_path, "DP-2", 1080, 1920, wallpaper(tmp_path, "b.png", color="blue"))]


def test_save_keeps_the_picture_and_framing_of_every_monitor(tmp_path):
    monitors = two_monitors(tmp_path)
    monitors[1].edit("mirror")
    layouts = Layouts(tmp_path / "layouts")
    layouts.save("Work", monitors)
    (saved,) = layouts.all()
    assert saved.name == "Work"
    assert saved.monitors["DP-2"]["source"] == monitors[1].image
    assert saved.monitors["DP-2"]["flip_h"] and not saved.monitors["DP-1"]["flip_h"]
    assert os.path.exists(saved.preview)


def test_the_preview_puts_each_monitor_where_it_is(tmp_path):
    """DP-2 stands rotated to the right of DP-1: red on the left, blue on the right."""
    layouts = Layouts(tmp_path / "layouts")
    saved = layouts.save("Desk", two_monitors(tmp_path),
                         {"DP-1": (0, 420, 1920, 1080), "DP-2": (1920, 0, 1080, 1920)})
    with Image.open(saved.preview) as preview:
        assert preview.width <= PREVIEW_SIZE[0] and preview.height <= PREVIEW_SIZE[1]
        assert abs(preview.width / preview.height - 3000 / 1920) < 0.05
        assert preview.getpixel((5, preview.height // 2))[:3] == (255, 0, 0)
        assert preview.getpixel((5, 5))[3] == 0                 # nothing above or below DP-1
        assert preview.getpixel((5, preview.height - 5))[3] == 0
        assert preview.getpixel((preview.width - 5, 5))[:3] == (0, 0, 255)


def test_without_positions_the_monitors_stand_in_a_row(tmp_path):
    saved = Layouts(tmp_path / "layouts").save("Row", two_monitors(tmp_path))
    with Image.open(saved.preview) as preview:
        assert preview.getpixel((5, 5))[:3] == (255, 0, 0)
        assert preview.getpixel((preview.width - 5, 5))[:3] == (0, 0, 255)


def test_rename_duplicate_and_delete(tmp_path):
    layouts = Layouts(tmp_path / "layouts")
    first = layouts.save("Work", two_monitors(tmp_path))
    layouts.rename(first, "Office")
    copy = layouts.duplicate(layouts.all()[0])
    assert [layout.name for layout in layouts.all()] == ["Office", "Office (copy)"]
    assert os.path.exists(copy.preview) and copy.preview != first.preview
    layouts.delete(layouts.all()[0])
    assert [layout.name for layout in layouts.all()] == ["Office (copy)"]
    assert sorted(os.listdir(tmp_path / "layouts")) == sorted(
        os.path.basename(p) for p in (copy.path, copy.preview))


def test_update_keeps_the_name_and_monitors_that_are_not_here(tmp_path):
    monitors = two_monitors(tmp_path)
    layouts = Layouts(tmp_path / "layouts")
    saved = layouts.save("Work", monitors)
    monitors[0].edit("rotate")
    layouts.update(saved, monitors[:1])                  # DP-2 is unplugged now
    (updated,) = layouts.all()
    assert updated.name == "Work"
    assert updated.monitors["DP-1"]["rotation"] == 90
    assert updated.monitors["DP-2"] == saved.monitors["DP-2"]


def test_pictures_in_layouts_are_never_cleaned_away(tmp_path):
    monitors = two_monitors(tmp_path)
    upscaled = wallpaper(tmp_path, "a-x2.png", size=(800, 400))
    monitors[0].use_upscaled(upscaled)
    layouts = Layouts(tmp_path / "layouts")
    layouts.save("Work", monitors)
    assert layouts.images_in_use() == {upscaled, monitors[0].original, monitors[1].image}


def test_broken_files_are_skipped(tmp_path):
    folder = tmp_path / "layouts"
    folder.mkdir()
    (folder / "1.json").write_text("{ not json")
    (folder / "2.json").write_text('{"monitors": {}}')
    assert Layouts(folder).all() == []
    assert Layouts(tmp_path / "nowhere").all() == []


def test_a_snapshot_comes_back_on_a_monitor_of_another_size(tmp_path):
    """Saved on a 1920x1080 monitor, shown on a 3840x2160 one: the same picture part."""
    small = monitor_on(tmp_path, "DP-1", 1920, 1080, wallpaper(tmp_path, size=(4000, 3000)))
    small.framing.zoom_at(2, 0, 0)
    entry = small.snapshot()
    big = monitor_on(tmp_path, "DP-1", 3840, 2160, wallpaper(tmp_path, "other.png"))
    big.use_snapshot(entry)
    assert big.image == small.image
    assert big.framing.relative_zoom == small.framing.relative_zoom
    assert (big.framing.x, big.framing.y) == (small.framing.x * 2, small.framing.y * 2)


def test_a_save_that_fails_leaves_the_layout_whole_and_nothing_behind(tmp_path, monkeypatch):
    monitors = two_monitors(tmp_path)
    layouts = Layouts(tmp_path / "layouts")
    saved = layouts.save("Work", monitors)
    before = sorted(os.listdir(tmp_path / "layouts"))

    def no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("wallframe.layouts.json.dump", no_space)
    with pytest.raises(OSError):
        layouts.rename(saved, "Office")
    assert sorted(os.listdir(tmp_path / "layouts")) == before
    assert [layout.name for layout in layouts.all()] == ["Work"]

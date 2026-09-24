"""Tests for the saved state: always in a temporary folder, never in ~/.local/share."""

import os

from wallframe.framing import Framing
from wallframe.state import Store


def edited_framing():
    f = Framing(1080, 1920, 3840, 2160)
    f.mirror(horizontal=True)
    f.zoom_at(1.5, 100, 200)
    return f


def test_missing_or_broken_state_is_empty(tmp_path):
    store = Store(tmp_path)
    assert store.load() == {}
    (tmp_path / "state.json").write_text("{ not json")
    assert store.load() == {}


def test_remember_then_resume_from_the_original(tmp_path):
    store = Store(tmp_path)
    source = tmp_path / "original.jpg"
    source.write_bytes(b"")
    crop = store.new_crop_path("DP-1")
    f = edited_framing()
    store.remember("DP-1", crop, str(source), f)

    image, saved = store.resume("DP-1", crop)
    assert image == str(source)
    restored = Framing(1080, 1920, 3840, 2160)
    restored.restore(saved)
    assert restored.key() == f.key()


def test_no_resume_when_the_monitor_shows_something_else(tmp_path):
    store = Store(tmp_path)
    source = tmp_path / "original.jpg"
    source.write_bytes(b"")
    store.remember("DP-1", store.new_crop_path("DP-1"), str(source), edited_framing())
    assert store.resume("DP-1", "/wallpapers/new.jpg") == ("/wallpapers/new.jpg", None)


def test_no_resume_when_the_original_is_gone(tmp_path):
    store = Store(tmp_path)
    crop = store.new_crop_path("DP-1")
    store.remember("DP-1", crop, str(tmp_path / "deleted.jpg"), edited_framing())
    assert store.resume("DP-1", crop) == (crop, None)


def test_old_crops_go_only_after_the_new_one_and_only_that_monitors(tmp_path):
    store = Store(tmp_path)
    for name in ("DP-1-100.png", "DP-1-200.png", "DP-10-100.png", "HDMI-A-1-100.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    path = store.new_crop_path("DP-1")
    assert len(list(tmp_path.iterdir())) == 5                # nothing deleted yet
    open(path, "wb").close()
    store.remove_old_crops("DP-1", keep=path)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == sorted(["DP-10-100.png", "HDMI-A-1-100.png", "notes.txt", os.path.basename(path)])
    assert path != store.new_crop_path("DP-1")               # never the same name twice


def test_each_monitor_keeps_its_own_entry(tmp_path):
    store = Store(tmp_path)
    store.remember("DP-1", "a.png", "a.jpg", edited_framing())
    store.remember("DP-2", "b.png", "b.jpg", edited_framing())
    assert set(store.load()) == {"DP-1", "DP-2"}

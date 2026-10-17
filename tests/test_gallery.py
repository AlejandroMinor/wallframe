"""Tests for the wallpaper folder: always a temporary folder and cache."""

import os

import pytest
from PIL import Image

from wallframe import gallery


def picture(folder, name, size=(800, 400), mtime=None):
    path = folder / name
    Image.new("RGB", size, "red").save(path)
    if mtime:
        os.utime(path, (mtime, mtime))
    return str(path)


def test_lists_still_pictures_newest_first(tmp_path):
    old = picture(tmp_path, "old.jpg", mtime=1_000)
    new = picture(tmp_path, "new.PNG", mtime=3_000)
    middle = picture(tmp_path, "middle.webp", mtime=2_000)
    picture(tmp_path, "moving.gif")
    picture(tmp_path, ".hidden.png")
    (tmp_path / "notes.txt").write_text("not a picture")
    (tmp_path / "sub").mkdir()
    picture(tmp_path / "sub", "inside.png")
    assert gallery.pictures(tmp_path) == [new, middle, old]


def test_a_folder_that_is_not_there_has_no_pictures(tmp_path):
    assert gallery.pictures(tmp_path / "missing") == []


def test_thumbnails_are_small_and_made_once(tmp_path):
    path = picture(tmp_path, "wide.jpg", size=(4000, 1000))
    thumb = gallery.thumbnail(path)
    with Image.open(thumb) as small:
        assert small.width <= gallery.THUMB_SIZE[0] and small.height <= gallery.THUMB_SIZE[1]
        assert abs(small.width / small.height - 4) < 0.1
    made = os.stat(thumb).st_mtime_ns
    assert gallery.thumbnail(path) == thumb and os.stat(thumb).st_mtime_ns == made


def test_a_changed_picture_gets_a_new_thumbnail(tmp_path):
    path = picture(tmp_path, "a.png", mtime=1_000)
    first = gallery.thumbnail(path)
    picture(tmp_path, "a.png", size=(300, 300), mtime=2_000)
    assert gallery.thumbnail(path) != first


def test_a_broken_picture_says_so(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_text("not a jpeg")
    with pytest.raises(OSError, match="cannot read broken.jpg"):
        gallery.thumbnail(str(path))
    assert not [name for name in os.listdir(gallery.CACHE_DIR) if name.endswith(".tmp")]


def test_cached_tells_made_thumbnails_apart(tmp_path):
    path = picture(tmp_path, "a.png")
    assert gallery.cached(path) is None
    thumb = gallery.thumbnail(path)
    assert gallery.cached(path) == thumb
    assert gallery.cached(str(tmp_path / "gone.png")) is None

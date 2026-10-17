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
    made = os.stat(thumb).st_ino
    assert gallery.thumbnail(path) == thumb and os.stat(thumb).st_ino == made  # not remade


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


def test_subfolders_are_listed_when_asked(tmp_path):
    top = picture(tmp_path, "top.png", mtime=1_000)
    (tmp_path / "anime").mkdir()
    inside = picture(tmp_path / "anime", "inside.png", mtime=2_000)
    (tmp_path / ".hidden").mkdir()
    picture(tmp_path / ".hidden", "secret.png", mtime=3_000)
    assert gallery.pictures(tmp_path) == [top]
    assert gallery.pictures(tmp_path, subfolders=True) == [inside, top]


def test_prune_deletes_only_thumbnails_not_used_lately(tmp_path):
    old = gallery.thumbnail(picture(tmp_path, "old.png"))
    recent_picture = picture(tmp_path, "recent.png")
    recent = gallery.thumbnail(recent_picture)
    long_ago = 1_000
    os.utime(old, (long_ago, long_ago))
    os.utime(recent, (long_ago, long_ago))
    assert gallery.cached(recent_picture) == recent  # shown again: used now
    assert gallery.prune() == 1
    assert not os.path.exists(old) and os.path.exists(recent)


def test_usage_and_clear(tmp_path):
    for name in ("a.png", "b.png"):
        gallery.thumbnail(picture(tmp_path, name))
    count, size = gallery.usage()
    assert count == 2 and size > 0
    gallery.clear()
    assert gallery.usage() == (0, 0)
    assert gallery.usage(str(tmp_path / "no-cache")) == (0, 0)

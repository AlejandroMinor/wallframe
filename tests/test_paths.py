"""Tests for where the files go on each system: only environment variables are read."""

import ntpath
import os

import pytest

from wallframe import paths


def test_two_spellings_of_a_windows_path_name_one_file(monkeypatch):
    mine = r"C:\Users\Ana\AppData\Local/wallframe/DP-1-1.png"
    with monkeypatch.context() as patched:
        patched.setattr(paths.os, "path", ntpath)
        assert paths.same_file(mine, r"c:\users\ana\appdata\local\wallframe\DP-1-1.png")
        assert not paths.same_file(mine, r"C:\Users\Ana\Pictures\DP-1-1.png")


def test_no_path_is_the_same_file_as_a_path():
    assert not paths.same_file(None, "/wallpapers/new.jpg")
    assert not paths.same_file("/wallpapers/new.jpg", "")


@pytest.fixture
def home(tmp_path, monkeypatch):
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                     "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_linux_uses_the_xdg_folders_in_the_home_by_default(home):
    assert paths.config_dir(windows=False) == os.path.join(home, ".config", "wallframe")
    assert paths.data_dir(windows=False) == os.path.join(home, ".local/share", "wallframe")
    assert paths.cache_dir(windows=False) == os.path.join(home, ".cache", "wallframe")


def test_linux_follows_the_xdg_variables(home, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/c")
    monkeypatch.setenv("XDG_DATA_HOME", "/d")
    monkeypatch.setenv("XDG_CACHE_HOME", "/k")
    assert paths.config_dir(windows=False) == os.path.join("/c", "wallframe")
    assert paths.data_dir(windows=False) == os.path.join("/d", "wallframe")
    assert paths.cache_dir(windows=False) == os.path.join("/k", "wallframe")


def test_windows_keeps_the_settings_in_appdata_and_the_rest_in_localappdata(home, monkeypatch):
    """The XDG variables mean nothing there, even when a tool like MSYS2 sets them."""
    monkeypatch.setenv("XDG_DATA_HOME", "/d")
    monkeypatch.setenv("APPDATA", "/roaming")
    monkeypatch.setenv("LOCALAPPDATA", "/local")
    assert paths.config_dir(windows=True) == os.path.join("/roaming", "wallframe")
    assert paths.data_dir(windows=True) == os.path.join("/local", "wallframe")
    assert paths.cache_dir(windows=True) == os.path.join("/local", "wallframe", "cache")


def test_windows_without_its_variables_still_lands_in_the_profile(home):
    assert paths.config_dir(windows=True) == os.path.join(home, "AppData/Roaming", "wallframe")
    assert paths.data_dir(windows=True) == os.path.join(home, "AppData/Local", "wallframe")

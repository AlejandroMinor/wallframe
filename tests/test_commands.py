"""Tests for how errors reach the user; no program is really started."""

import pytest

from wallframe import commands


@pytest.fixture
def calls(monkeypatch):
    """Records the commands notify() would run instead of running them."""
    ran = []
    monkeypatch.setattr(commands, "run", ran.append)
    return ran


def test_prefers_notify_send(monkeypatch, calls, capsys):
    monkeypatch.setattr(commands.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    commands.notify("No image wallpaper found.")
    assert calls == [["notify-send", "wallframe", "No image wallpaper found."]]
    assert capsys.readouterr().err == "wallframe: No image wallpaper found.\n"


def test_falls_back_to_hyprland(monkeypatch, calls):
    monkeypatch.setattr(commands.shutil, "which", lambda name: None)
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    commands.notify("No image wallpaper found.")
    assert calls == [["hyprctl", "notify", "3", "5000", "0",
                      "wallframe: No image wallpaper found."]]


def test_only_stderr_elsewhere(monkeypatch, calls, capsys):
    monkeypatch.setattr(commands.shutil, "which", lambda name: None)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    commands.notify("No image wallpaper found.")
    assert calls == []
    assert "No image wallpaper found." in capsys.readouterr().err

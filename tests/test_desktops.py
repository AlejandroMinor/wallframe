"""Tests for telling which desktop this is: only environment variables are read."""

import pytest

from wallframe import compositors, daemons, desktops, plasma
from wallframe.daemons import Output


@pytest.fixture
def session(monkeypatch):
    """A clean environment: set only the variables each test's session sets."""
    for variable in ("XDG_CURRENT_DESKTOP", "HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK"):
        monkeypatch.delenv(variable, raising=False)
    return monkeypatch.setenv


@pytest.mark.parametrize("current, expected", [
    ("Hyprland", compositors.HYPRLAND),
    ("sway", compositors.SWAY),
    ("KDE", plasma.Desktop),
    ("niri", compositors.OTHER),
    ("GNOME:ubuntu", compositors.OTHER),       # several names, as Ubuntu sets it
])
def test_xdg_current_desktop_says_which_it_is(session, current, expected):
    session("XDG_CURRENT_DESKTOP", current)
    found = desktops.detect()
    assert found is expected or isinstance(found, expected)


def test_without_xdg_current_desktop_the_compositor_variable_tells(session):
    session("SWAYSOCK", "/run/user/1000/sway-ipc.sock")
    assert desktops.detect() is compositors.SWAY


def test_a_plasma_started_from_hyprland_is_plasma(session):
    """It inherits Hyprland's variable, but XDG_CURRENT_DESKTOP is what counts."""
    session("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    session("XDG_CURRENT_DESKTOP", "KDE")
    assert isinstance(desktops.detect(), plasma.Desktop)


def test_compositors_use_awww_and_plasma_its_own(monkeypatch):
    """awww is only for the desktops it draws on; in Plasma it is not even asked."""
    monkeypatch.setattr(daemons.Daemon, "outputs", lambda self: [Output("DP-1", 1, 1, "/a")])
    monkeypatch.setattr(plasma.Plasma, "outputs", lambda self: [Output("DP-1", 1, 1, "/b")])
    assert isinstance(compositors.HYPRLAND.wallpaper(), daemons.Daemon)
    assert isinstance(compositors.OTHER.wallpaper(), daemons.Daemon)
    assert isinstance(plasma.Desktop().wallpaper(), plasma.Plasma)

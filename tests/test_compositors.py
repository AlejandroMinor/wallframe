"""Tests for the compositor answers: parsing only, no hyprctl or swaymsg runs."""

import pytest

from wallframe import compositors
from wallframe.compositors import display_model, parse_outputs

# The fields wallframe reads from `hyprctl monitors -j` (sway uses the same names).
OUTPUTS = [
    {"name": "HDMI-A-1", "make": "AOC", "model": "24B3HM", "focused": False},
    {"name": "DP-1", "make": "ASUSTek COMPUTER INC", "model": "ASUS VA24E", "focused": False},
    {"name": "DP-2", "make": "NZXT (PNP same EDID)_", "model": "NZXTCANVAS27Q", "focused": True},
]


def test_finds_the_focused_monitor_and_every_model():
    monitors = parse_outputs(OUTPUTS)
    assert monitors.focused == "DP-2"
    assert monitors.models == {"HDMI-A-1": "AOC 24B3HM", "DP-1": "ASUS VA24E",
                               "DP-2": "NZXTCANVAS27Q"}


def test_no_focus_reported():
    assert parse_outputs([{**o, "focused": False} for o in OUTPUTS]).focused is None


@pytest.mark.parametrize("make, model, expected", [
    ("AOC", "24B3HM", "AOC 24B3HM"),                          # model lacks the brand: add it
    ("ASUSTek COMPUTER INC", "ASUS VA24E", "ASUS VA24E"),     # model already has it
    ("NZXT (PNP same EDID)_", "NZXTCANVAS27Q", "NZXTCANVAS27Q"),
    ("Dell Inc.", "", "Dell"),                                # no model: first word of the make
    ("", "U2720Q", "U2720Q"),
    ("", "", ""),
])
def test_display_model(make, model, expected):
    assert display_model({"make": make, "model": model}) == expected


def test_asks_only_the_running_compositor(monkeypatch):
    ran = []
    monkeypatch.setattr(compositors, "run", lambda cmd: ran.append(cmd) or "[]")
    monkeypatch.setenv("SWAYSOCK", "/run/user/1000/sway-ipc.sock")
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    compositors.detect()
    assert ran == [["swaymsg", "-t", "get_outputs"]]


def test_other_compositors_run_nothing(monkeypatch):
    ran = []
    monkeypatch.setattr(compositors, "run", ran.append)
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    assert compositors.detect() == compositors.CompositorInfo()
    assert ran == []

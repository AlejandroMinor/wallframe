"""Tests for the compositor answers: parsing only, no hyprctl or swaymsg runs."""

import json

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


def test_sway_is_asked_with_its_own_command(monkeypatch):
    ran = []
    monkeypatch.setattr(compositors, "run", lambda cmd: ran.append(cmd) or json.dumps(OUTPUTS))
    assert compositors.SWAY.info().focused == "DP-2"
    assert ran == [["swaymsg", "-t", "get_outputs"]]


def test_another_compositor_is_asked_nothing(monkeypatch):
    ran = []
    monkeypatch.setattr(compositors, "run", ran.append)
    assert compositors.OTHER.info() == compositors.CompositorInfo()
    assert ran == []


def test_an_answer_that_is_not_json_says_nothing(monkeypatch):
    monkeypatch.setattr(compositors, "run", lambda cmd: "hyprctl: socket not found")
    assert compositors.HYPRLAND.info() == compositors.CompositorInfo()


def test_positions_from_sway_rect():
    info = parse_outputs([{"name": "DP-1", "rect": {"x": 1920, "y": 0, "width": 1080,
                                                     "height": 1920}}])
    assert info.positions == {"DP-1": (1920, 0, 1080, 1920)}


def test_positions_from_hyprland_follow_scale_and_rotation():
    """Hyprland gives the physical size before rotating; the desktop uses logical pixels."""
    info = parse_outputs([
        {"name": "DP-1", "x": 0, "y": 0, "width": 3840, "height": 2160, "scale": 2,
         "transform": 0},
        {"name": "DP-2", "x": 1920, "y": 0, "width": 1920, "height": 1080, "scale": 1,
         "transform": 1},
    ])
    assert info.positions == {"DP-1": (0, 0, 1920, 1080), "DP-2": (1920, 0, 1080, 1920)}


def test_no_position_without_the_fields():
    assert parse_outputs(OUTPUTS).positions == {}

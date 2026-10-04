"""Compositors that awww or swww draw the wallpaper on: Hyprland, sway and the rest."""

import json
import os
from dataclasses import dataclass, field

from . import daemons
from .commands import run


@dataclass
class CompositorInfo:
    focused: str | None = None                   # output name, e.g. "DP-1"
    models: dict = field(default_factory=dict)   # output name -> "ASUS VA24E"
    # output name -> (x, y, width, height) on the desktop, in logical pixels
    positions: dict = field(default_factory=dict)


def parse_outputs(outputs):
    """Reads the JSON list printed by hyprctl or swaymsg."""
    focused = next((o.get("name") for o in outputs if o.get("focused")), None)
    return CompositorInfo(focused, {o.get("name"): display_model(o) for o in outputs},
                          {o.get("name"): rect for o in outputs if (rect := position(o))})


def position(output):
    """Where the monitor sits on the desktop, as the layouts' previews draw it, or None.

    sway gives it as "rect". Hyprland gives the corner in logical pixels but the size
    in physical ones, before the scale and the rotation (odd transforms turn it 90°).
    """
    rect = output.get("rect")
    if rect:
        return (rect["x"], rect["y"], rect["width"], rect["height"])
    try:
        x, y, width, height = (output[key] for key in ("x", "y", "width", "height"))
    except KeyError:
        return None
    scale = output.get("scale") or 1
    if output.get("transform", 0) % 2:
        width, height = height, width
    return (x, y, round(width / scale), round(height / scale))


def display_model(output):
    """Make and model, e.g. "AOC 24B3HM", without repeating the brand ("ASUS VA24E").

    EDID makes are noisy ("ASUSTek COMPUTER INC"), so only their first word is used.
    """
    make = (output.get("make") or "").split()
    model = (output.get("model") or "").strip()
    if not make or not model:
        return model or " ".join(make[:1])
    brand, first = make[0].lower(), model.split()[0].lower()
    if brand in model.lower() or first in brand:
        return model
    return f"{make[0]} {model}"


class Compositor:
    """A desktop where awww or swww draws the wallpaper (see desktops.py).

    With a `command`, it answers with its monitors as JSON, as Hyprland and sway
    do; without one, it says nothing about them, and wallframe still works.
    """

    def __init__(self, name, variable=None, command=None):
        self.name = name          # as XDG_CURRENT_DESKTOP names it, in lower case
        self.variable = variable  # set in its session, and needed to reach it
        self.command = command

    def reachable(self):
        return bool(self.variable and os.environ.get(self.variable))

    def info(self):
        if not self.command:
            return CompositorInfo()
        try:
            return parse_outputs(json.loads(run(self.command) or "[]"))
        except ValueError:
            return CompositorInfo()

    def wallpaper(self):
        return daemons.detect()


HYPRLAND = Compositor("hyprland", "HYPRLAND_INSTANCE_SIGNATURE", ["hyprctl", "monitors", "-j"])
SWAY = Compositor("sway", "SWAYSOCK", ["swaymsg", "-t", "get_outputs"])
OTHER = Compositor("other")  # niri, river, Wayfire...: awww works, nothing else is asked

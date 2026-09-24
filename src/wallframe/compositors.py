import json
import os
from dataclasses import dataclass, field

from .commands import run

# Each compositor sets its own variable; both answer with the same JSON fields.
_QUERIES = {"HYPRLAND_INSTANCE_SIGNATURE": ["hyprctl", "monitors", "-j"],
            "SWAYSOCK": ["swaymsg", "-t", "get_outputs"]}


@dataclass
class CompositorInfo:
    focused: str | None = None                   # output name, e.g. "DP-1"
    models: dict = field(default_factory=dict)   # output name -> "ASUS VA24E"


def parse_outputs(outputs):
    """Reads the JSON list printed by hyprctl or swaymsg."""
    focused = next((o.get("name") for o in outputs if o.get("focused")), None)
    return CompositorInfo(focused, {o.get("name"): display_model(o) for o in outputs})


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


def detect():
    """Asks Hyprland or sway; empty on any other compositor."""
    for variable, cmd in _QUERIES.items():
        if os.environ.get(variable):
            try:
                return parse_outputs(json.loads(run(cmd) or "[]"))
            except ValueError:
                break
    return CompositorInfo()

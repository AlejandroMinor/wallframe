"""What the compositor knows about the monitors: which one has the focus and its model.

Optional: Hyprland and sway are asked; on any other compositor wallframe
still works, it just starts on the first monitor and shows no models.
"""

import json
import os
from dataclasses import dataclass, field

from .commands import run

# Each compositor sets its own variable; both answer with the same JSON fields.
_QUERIES = {"HYPRLAND_INSTANCE_SIGNATURE": ["hyprctl", "monitors", "-j"],
            "SWAYSOCK": ["swaymsg", "-t", "get_outputs"]}


@dataclass
class Monitors:
    focused: str | None = None                   # output name, e.g. "DP-1"
    models: dict = field(default_factory=dict)   # output name -> "ASUS VA24E"


def parse_outputs(outputs):
    """Monitors from the decoded JSON list that hyprctl or swaymsg print."""
    focused = next((o.get("name") for o in outputs if o.get("focused")), None)
    return Monitors(focused, {o.get("name"): display_model(o) for o in outputs})


def display_model(output):
    """Make and model, without repeating the make when the model already has it.

    EDID makes are noisy ("ASUSTek COMPUTER INC", "NZXT (PNP same EDID)_") while
    models usually start with the brand ("ASUS VA24E"), so only the make's
    first word is kept, and only when neither already contains the other
    (ASUSTek / ASUS).
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
    """Asks the running compositor; empty Monitors on any other one."""
    for variable, cmd in _QUERIES.items():
        if os.environ.get(variable):
            try:
                return parse_outputs(json.loads(run(cmd) or "[]"))
            except ValueError:
                break
    return Monitors()

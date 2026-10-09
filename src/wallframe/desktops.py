"""Which desktop wallframe runs on, and so what it uses there.

Each desktop gives the same three things: whether its session is this one,
what it says about the monitors (focused, models, places), and what sets the
wallpaper. awww or swww do it on Hyprland, sway and the like; Plasma does it
itself. A new desktop is one more entry in DESKTOPS.
"""

import os

from . import compositors, plasma

DESKTOPS = (plasma.Desktop(), compositors.HYPRLAND, compositors.SWAY)


def detect():
    """The desktop of this session; another compositor when none of these.

    XDG_CURRENT_DESKTOP says which it is. A session that does not set it is
    known by the variable its compositor sets, which also means that a Plasma
    started from Hyprland, with Hyprland's variable still around, is Plasma.
    """
    current = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return (next((d for d in DESKTOPS if d.name in current), None)
            or next((d for d in DESKTOPS if d.reachable()), compositors.OTHER))

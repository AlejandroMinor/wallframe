"""wallframe [MONITOR]: frame the wallpaper inside each monitor, then apply it."""

import sys

from . import compositors, daemons, render, window
from .commands import notify
from .monitor import Monitor
from .state import Store


def main():
    daemon = daemons.detect()
    if not daemon:
        notify("No image wallpaper found.")
        return 1

    info = compositors.detect()
    store = Store()
    monitors = [Monitor(o, store, info.models.get(o.name, ""))
                for o in daemon.outputs() if render.is_still_image(o.image)]
    if not monitors:
        notify("Animated and video wallpapers cannot be adjusted.")
        return 1

    wanted = sys.argv[1] if len(sys.argv) > 1 else info.focused
    start = next((i for i, m in enumerate(monitors) if m.name == wanted), 0)
    return window.run(monitors, daemon, start, info.focused)


if __name__ == "__main__":
    sys.exit(main())

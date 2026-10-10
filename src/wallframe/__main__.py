"""wallframe [MONITOR | span]: frame the wallpaper inside each monitor, or one
picture across all of them, then apply it."""

import sys

from . import desktops, render, span, upscalers, window
from .layouts import Layouts
from .commands import notify
from .monitor import Monitor
from .state import Store


def main():
    desktop = desktops.detect()
    daemon = desktop.wallpaper()
    if not daemon:
        notify("No image wallpaper found.")
        return 1

    info = desktop.info()
    store = Store()
    monitors = [Monitor(o, store, info.models.get(o.name, ""))
                for o in daemon.outputs() if render.is_still_image(o.image)]
    if not monitors:
        notify("Animated and video wallpapers cannot be adjusted.")
        return 1

    across = span.make(monitors, info.positions, store.span())
    asked = sys.argv[1] if len(sys.argv) > 1 else None
    wanted = asked or info.focused
    start = next((i for i, m in enumerate(monitors) if m.name == wanted), 0)
    # The span comes after the monitors; it opens when asked, or when it is on them.
    if across and (asked == "span" or (not asked and across.live)):
        start = len(monitors)
    return window.run(monitors, daemon, start, info.focused, upscalers.detect(), Layouts(),
                      info.positions, across)


if __name__ == "__main__":
    sys.exit(main())

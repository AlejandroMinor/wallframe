"""wallframe [MONITOR | span]: frame the wallpaper inside each monitor, or one
picture across all of them, then apply it."""

import sys
from concurrent.futures import ThreadPoolExecutor

from . import desktops, render, span, upscalers, window
from .layouts import Layouts
from .commands import notify
from .monitor import Monitor
from .state import Store


def open_monitor(output, store, model):
    """The monitor, or None when its picture looks fine but cannot be read: the others
    still open."""
    try:
        return Monitor(output, store, model)
    except render.UNREADABLE:
        return None


def main():
    desktop = desktops.detect()
    if desktop.name == "windows" and desktop.already_open():
        return 0
    daemon = desktop.wallpaper()
    if not daemon:
        notify("No image wallpaper found.")
        return 1

    info = desktop.info()
    store = Store()
    outputs = [o for o in daemon.outputs() if render.is_still_image(o.image)]
    # Each monitor reads its picture for the preview, up to a second for a big one: all at
    # once, and one read for monitors that show the same picture.
    with ThreadPoolExecutor() as pool:
        monitors = [m for m in pool.map(
            lambda o: open_monitor(o, store, info.models.get(o.name, "")), outputs) if m]
    if not monitors:
        notify("Animated and video wallpapers cannot be adjusted.")
        return 1

    across = span.make(monitors, info.positions, store.span(), desktop.sizes())
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

import json
import os
import time

from PIL import Image

from . import render
from .state import DATA_DIR

LAYOUTS_DIR = os.path.join(DATA_DIR, "layouts")
PREVIEW_SIZE = (360, 160)  # the most a preview takes, keeping the desktop's shape
GAP = 3                    # preview pixels between monitors that touch on the desktop


class Layout:
    """A saved set of wallpapers: for each monitor, the picture and how it is framed."""

    def __init__(self, path, data):
        self.path, self.name, self.monitors = path, data["name"], data["monitors"]

    @property
    def preview(self):
        """The PNG with every monitor in its place, as seen from afar."""
        return self.path[:-len(".json")] + ".png"


class Layouts:
    """The layouts folder: one JSON file and one preview PNG per layout."""

    def __init__(self, directory=LAYOUTS_DIR):
        self.directory = directory

    def all(self):
        """Every layout, oldest first; files that cannot be read are skipped."""
        if not os.path.isdir(self.directory):
            return []
        layouts = []
        for name in sorted(os.listdir(self.directory)):
            if name.endswith(".json") and not name.endswith(".tmp.json"):
                path = os.path.join(self.directory, name)
                try:
                    with open(path) as f:
                        layouts.append(Layout(path, json.load(f)))
                except (OSError, ValueError, KeyError):
                    continue
        return layouts

    def save(self, name, monitors, positions=None):
        """A new layout with what `monitors` show in the editor now.

        `positions` places them in the preview as on the desktop (see
        compositors.position); without it they stand in a row.
        """
        os.makedirs(self.directory, exist_ok=True)
        # The time keeps the names unique and the list in the order they were made.
        path = os.path.join(self.directory, f"{time.time_ns()}.json")
        return self._write(path, name, {m.name: m.snapshot() for m in monitors},
                           draw(monitors, positions or {}))

    def update(self, layout, monitors, positions=None):
        """Replaces what `layout` keeps with what `monitors` show now, keeping its name.

        Monitors it had that are not here stay as they were saved.
        """
        entries = dict(layout.monitors, **{m.name: m.snapshot() for m in monitors})
        return self._write(layout.path, layout.name, entries, draw(monitors, positions or {}))

    def rename(self, layout, name):
        return self._write(layout.path, name, layout.monitors)

    def duplicate(self, layout):
        """A copy named "<name> (copy)", with its own preview, listed last."""
        path = os.path.join(self.directory, f"{time.time_ns()}.json")
        copy = f"{layout.name} (copy)"
        if not os.path.exists(layout.preview):
            return self._write(path, copy, layout.monitors)
        with Image.open(layout.preview) as preview:
            return self._write(path, copy, layout.monitors, preview.copy())

    def delete(self, layout):
        for path in (layout.path, layout.preview):
            if os.path.exists(path):
                os.remove(path)

    def images_in_use(self):
        """Every picture a layout points at, so cleaning up never deletes one."""
        return {path for layout in self.all() for entry in layout.monitors.values()
                for path in (entry.get("source"), entry.get("original")) if path}

    def _write(self, path, name, monitors, preview=None):
        """Saves the layout, its preview first, each written aside and swapped in."""
        data = {"name": name, "monitors": monitors}
        if preview is not None:
            _replace(path[:-len(".json")] + ".png", preview.save)
        _replace(path, lambda temporary: _dump(data, temporary))
        return Layout(path, data)


def _dump(data, path):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _replace(path, write):
    """Calls write(temporary) and swaps the result in, so a failure halfway
    leaves the old file whole and no temporary file behind."""
    stem, extension = os.path.splitext(path)
    temporary = f"{stem}.tmp{extension}"  # the extension tells Pillow the format
    try:
        write(temporary)
        os.replace(temporary, path)
    except OSError:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def draw(monitors, positions):
    """Every monitor's wallpaper in its place on the desktop, small, on transparency.

    Monitors without a position stand in a row to the right of the others.
    """
    places = {}
    right = max((x + w for x, _y, w, _h in positions.values()), default=0)
    for monitor in monitors:
        if monitor.name in positions:
            places[monitor] = positions[monitor.name]
        else:
            places[monitor] = (right, 0, monitor.width, monitor.height)
            right += monitor.width
    left = min(x for x, _y, _w, _h in places.values())
    top = min(y for _x, y, _w, _h in places.values())
    width = max(x + w for x, _y, w, _h in places.values()) - left
    height = max(y + h for _x, y, _w, h in places.values()) - top
    shrink = min(PREVIEW_SIZE[0] / width, PREVIEW_SIZE[1] / height)
    canvas = Image.new("RGBA", (max(1, round(width * shrink)), max(1, round(height * shrink))))
    for monitor, (x, y, w, h) in places.items():
        x0, y0 = round((x - left) * shrink), round((y - top) * shrink)
        x1, y1 = round((x - left + w) * shrink), round((y - top + h) * shrink)
        size = (max(1, x1 - x0 - GAP), max(1, y1 - y0 - GAP))
        # From the preview thumbnail: quick, and the original is never opened.
        canvas.paste(render.shown(monitor.preview(), monitor.framing, size), (x0, y0))
    return canvas

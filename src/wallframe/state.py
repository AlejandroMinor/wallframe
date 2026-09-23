"""Where wallframe keeps its crops, and what it remembers about each monitor.

One folder holds one PNG crop per monitor plus state.json, which maps each
monitor to its crop, the original image and the framing. With that, reopening
wallframe starts again from the original image instead of cropping the crop.
"""

import json
import os
import re
import time

# Not ~/.cache: the crop is the wallpaper itself, and the daemon loads it from
# this path again at every login, so a cache cleaner would leave the monitor blank.
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "wallframe")


class Store:
    def __init__(self, directory=DATA_DIR):
        self.directory = directory
        self.state_file = os.path.join(directory, "state.json")

    def load(self):
        """The whole state as {monitor: entry}; empty when missing or unreadable."""
        try:
            with open(self.state_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def resume(self, monitor, shown):
        """What to edit on a monitor that currently shows `shown`: (image, saved framing).

        When `shown` is the crop wallframe made last time and the original still
        exists, that original comes back with its saved framing. Otherwise the
        monitor starts from what it shows, with no saved framing (None).
        """
        saved = self.load().get(monitor, {})
        if saved.get("crop") == shown and os.path.exists(saved.get("source", "")):
            return saved["source"], saved
        return shown, None

    def new_crop_path(self, monitor):
        """A fresh path for the next crop of `monitor`, after deleting its old crops.

        The daemon caches images by path, so reusing a name would bring back the
        old crop. The timestamp in nanoseconds keeps two applies within the same
        second apart.
        """
        os.makedirs(self.directory, exist_ok=True)
        own = re.compile(re.escape(monitor) + r"-\d+\.png")
        for name in os.listdir(self.directory):
            if own.fullmatch(name):
                os.remove(os.path.join(self.directory, name))
        return os.path.join(self.directory, f"{monitor}-{time.time_ns()}.png")

    def remember(self, monitor, crop, source, framing):
        """Records that `monitor` now shows `crop`, made from `source` with `framing`."""
        state = self.load()
        state[monitor] = {"crop": crop, "source": source, **framing.to_dict()}
        os.makedirs(self.directory, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

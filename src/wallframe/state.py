import json
import os
import re
import time

# Not ~/.cache: the daemon loads the crops from here at login.
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "wallframe")


class Store:
    """The crops folder and state.json: monitor -> crop, original image and framing."""

    def __init__(self, directory=DATA_DIR):
        self.directory = directory
        self.state_file = os.path.join(directory, "state.json")

    def load(self):
        """The saved state; empty when missing or unreadable."""
        try:
            with open(self.state_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def resume(self, monitor, shown):
        """Returns (image to edit, saved framing or None).

        If the monitor shows wallframe's last crop, editing resumes from the original.
        """
        saved = self.load().get(monitor, {})
        if saved.get("crop") == shown and os.path.exists(saved.get("source", "")):
            return saved["source"], saved
        return shown, None

    def new_crop_path(self, monitor):
        """Deletes the monitor's old crops and returns a new, unused path.

        The daemon caches images by path, so a reused name would show the old crop.
        """
        os.makedirs(self.directory, exist_ok=True)
        own = re.compile(re.escape(monitor) + r"-\d+\.png")
        for name in os.listdir(self.directory):
            if own.fullmatch(name):
                os.remove(os.path.join(self.directory, name))
        return os.path.join(self.directory, f"{monitor}-{time.time_ns()}.png")

    def remember(self, monitor, crop, source, framing):
        """Saves that `monitor` shows `crop`, made from `source` with `framing`."""
        state = self.load()
        state[monitor] = {"crop": crop, "source": source, **framing.to_dict()}
        os.makedirs(self.directory, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

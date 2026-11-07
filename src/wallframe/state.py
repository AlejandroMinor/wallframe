import json
import os
import re
import time

from . import paths

# Not ~/.cache: the daemon loads the crops from here at login.
DATA_DIR = paths.data_dir()
# state.json's entry for the span (see span.py), beside the monitors' own;
# no output is named so.
SPAN = "span"


class Store:
    """The crops folder and state.json: monitor -> crop, original image and framing.

    It also keeps the span last applied, under SPAN, so the editor can open on it.
    """

    def __init__(self, directory=DATA_DIR):
        self.directory = directory
        self.state_file = os.path.join(directory, "state.json")

    def load(self):
        """The saved state; empty when missing or unreadable."""
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def resume(self, monitor, shown):
        """Returns (image to edit, saved framing or None).

        If the monitor shows wallframe's last crop, editing resumes from the original.
        """
        saved = self.load().get(monitor, {})
        if paths.same_file(saved.get("crop"), shown) and os.path.exists(saved.get("source", "")):
            return saved["source"], saved
        return shown, None

    def images_in_use(self):
        """Every image the saved state still points at, so none is cleaned away."""
        return {path for entry in self.load().values()
                for path in (entry.get("source"), entry.get("original")) if path}

    def new_crop_path(self, monitor):
        """A new, unused path for the monitor's next crop.

        The daemon caches images by path, so a reused name would show the old crop.
        """
        os.makedirs(self.directory, exist_ok=True)
        return os.path.join(self.directory, f"{monitor}-{time.time_ns()}.png")

    def remove_old_crops(self, monitor, keep):
        """Deletes the monitor's crops except `keep`, once the new one is safely written."""
        own = re.compile(re.escape(monitor) + r"-\d+\.png")
        for name in os.listdir(self.directory):
            path = os.path.join(self.directory, name)
            if own.fullmatch(name) and path != keep:
                try:
                    os.remove(path)
                except PermissionError:
                    pass  # Windows is still reading it: the next Apply deletes it

    def remember(self, monitor, crop, source, framing, original=None):
        """Saves that `monitor` shows `crop`, made from `source` with `framing`.

        `original` is the picture `source` was upscaled from, when it was.
        """
        state = self.load()
        state[monitor] = {"crop": crop, "source": source, **framing.to_dict()}
        if original and original != source:
            state[monitor]["original"] = original
        self._save(state)

    def span(self):
        """What remember_span() saved last, or None."""
        return self.load().get(SPAN)

    def remember_span(self, entry):
        """Saves the span applied last: its picture, framing and monitors (Span.snapshot)."""
        state = self.load()
        state[SPAN] = entry
        self._save(state)

    def _save(self, state):
        os.makedirs(self.directory, exist_ok=True)
        # Written aside, then swapped in: opening state.json for writing would
        # empty it first, and a failure halfway would lose every monitor's entry.
        temporary = self.state_file + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(temporary, self.state_file)
        except OSError:
            if os.path.exists(temporary):
                os.remove(temporary)
            raise

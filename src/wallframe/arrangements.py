"""Where the monitors stand on the desk, saved by name apart from any picture: their
places and the angle each is turned, so a calibration is done once and kept."""

import json
import os

FILE = "arrangements.json"


class Arrangements:
    def __init__(self, directory):
        self.path = os.path.join(directory, FILE)

    def load(self):
        """{name: entry}; empty when missing or unreadable."""
        try:
            with open(self.path) as f:
                found = json.load(f)
        except (OSError, ValueError):
            return {}
        return found if isinstance(found, dict) else {}

    def named(self, monitors):
        """[(name, entry)] of those saved for exactly these monitors, by name."""
        wanted = sorted(monitors)
        return sorted((name, entry) for name, entry in self.load().items()
                      if isinstance(entry, dict) and sorted(entry.get("monitors", [])) == wanted)

    def save(self, name, entry):
        """Keeps `entry` (see Span.arrangement) under `name`, replacing one with that name.

        Raises OSError when it cannot be written.
        """
        found = self.load()
        found[name] = entry
        self._write(found)

    def delete(self, name):
        found = self.load()
        if found.pop(name, None) is not None:
            self._write(found)

    def _write(self, found):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".tmp"  # swapped in, so a failure keeps the old file whole
        try:
            with open(temporary, "w") as f:
                json.dump(found, f, indent=2)
            os.replace(temporary, self.path)
        except OSError:
            if os.path.exists(temporary):
                os.remove(temporary)
            raise

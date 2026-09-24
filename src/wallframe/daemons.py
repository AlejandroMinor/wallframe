"""Wallpaper daemons: which image each output shows, and how to set a new one.

awww is the continuation of swww and both answer the same commands, so one
class covers both; only the program name changes.
"""

import re
from dataclasses import dataclass

from .commands import run

# ": DP-1: 1080x1920, scale: 1, currently displaying: image: /path/to/file.jpg"
# Outputs showing a plain color end in "color: 000000" instead and are skipped.
_QUERY_LINE = re.compile(r"^: ([^:]+): (\d+)x(\d+),.*image: (.+)$")


@dataclass
class Output:
    """A monitor as the daemon sees it: its name, size in pixels and current image."""
    name: str
    width: int
    height: int
    image: str


def parse_query(text):
    """The outputs showing an image, from the text of `awww query` or `swww query`."""
    outputs = []
    for line in text.splitlines():
        m = _QUERY_LINE.match(line)
        if m:
            outputs.append(Output(m[1], int(m[2]), int(m[3]), m[4]))
    return outputs


class Daemon:
    def __init__(self, program):
        self.program = program  # "awww" or "swww"

    def outputs(self):
        return parse_query(run([self.program, "query"]))

    def set_image(self, output, path):
        """Shows `path` on one output, as is: wallframe already cropped it to size."""
        run([self.program, "img", "-o", output, "--resize", "no",
             "--transition-type", "fade", "--transition-duration", "0.4", path])


def detect():
    """The running daemon that shows at least one image, or None."""
    for program in ("awww", "swww"):
        daemon = Daemon(program)
        if daemon.outputs():
            return daemon
    return None

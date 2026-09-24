import re
from dataclasses import dataclass

from .commands import run

# ": DP-1: 1080x1920, scale: 1, currently displaying: image: /path/to/file.jpg"
# Outputs showing a plain color end in "color: 000000" instead and are skipped.
_QUERY_LINE = re.compile(r"^: ([^:]+): (\d+)x(\d+),.*image: (.+)$")


@dataclass
class Output:
    """A monitor as the daemon sees it."""
    name: str
    width: int
    height: int
    image: str


def parse_query(text):
    """Reads the outputs showing an image from `awww query` or `swww query`."""
    outputs = []
    for line in text.splitlines():
        m = _QUERY_LINE.match(line)
        if m:
            outputs.append(Output(m[1], int(m[2]), int(m[3]), m[4]))
    return outputs


class Daemon:
    """awww or swww: both accept the same commands, since awww continues swww."""

    def __init__(self, program):
        self.program = program

    def outputs(self):
        return parse_query(run([self.program, "query"]))

    def set_image(self, output, path):
        """Shows `path` on one output; --resize no because it is already cropped to size."""
        run([self.program, "img", "-o", output, "--resize", "no",
             "--transition-type", "fade", "--transition-duration", "0.4", path])


def detect():
    """The running daemon, or None."""
    for program in ("awww", "swww"):
        daemon = Daemon(program)
        if daemon.outputs():
            return daemon
    return None

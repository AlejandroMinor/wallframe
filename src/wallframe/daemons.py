import re
from dataclasses import dataclass

from . import config
from .commands import run, run_or_fail

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


def parse_transitions(text):
    """The transition types `awww img --help` lists after "Possible transitions are:",
    as "none | simple | fade | ..." over one or more lines; [] when it lists none."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if "possible transitions are" in line.lower()), None)
    if start is None:
        return []
    kinds = []
    for line in lines[start + 1:]:
        if kinds and "|" not in line:
            break  # past the list: the blank line or the text after it
        kinds += [kind.strip() for kind in line.split("|") if kind.strip()]
    return kinds


class Daemon:
    """awww or swww: both accept the same commands, since awww continues swww."""

    def __init__(self, program):
        self.program = program
        self._transitions = None

    def transitions(self):
        """The transition types this version knows, asked once; [] when it cannot say."""
        if self._transitions is None:
            self._transitions = parse_transitions(run([self.program, "img", "--help"]))
        return self._transitions

    def outputs(self):
        return parse_query(run([self.program, "query"]))

    def set_image(self, output, path):
        """Shows `path` on one output; --resize no because it is already cropped to size.

        Raises OSError when the daemon refuses it, so the caller can keep the
        crop the output shows now.
        """
        options = []
        for option, value in config.transition().items():
            options += [f"--transition-{option}", f"{value:g}" if isinstance(value, float)
                        else str(value)]
        run_or_fail([self.program, "img", "-o", output, "--resize", "no", *options, path])


def detect():
    """awww or swww, whichever is running, or None."""
    for program in ("awww", "swww"):
        daemon = Daemon(program)
        if daemon.outputs():
            return daemon
    return None

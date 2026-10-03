import os
import re
import shutil
import subprocess
import sys
import threading


def run(cmd):
    """Returns the command's stdout, or "" if the program is missing.

    The exit status is ignored: these are queries, and silence is how a daemon
    that is not there is noticed.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout
    except OSError:
        return ""


def run_or_fail(cmd):
    """Like run, but for a command that must succeed: raises OSError if it fails.

    Always an OSError whose strerror is a sentence about the command, never a
    bare errno like "No such file or directory": callers read that message, and
    a missing program would read as a missing file. Not CalledProcessError
    either, because that is not an OSError and the editor reports failed
    monitors by catching one.
    """
    try:
        done = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as error:  # the program is missing or cannot be started
        raise OSError(None, f"{cmd[0]} could not be started: {error.strerror}") from error
    if done.returncode:
        reason = _first_line(done.stderr) or f"exit {done.returncode}"
        raise OSError(None, f"{cmd[0]} failed: {reason}")
    return done.stdout


def _first_line(stderr):
    """The gist of an error message, for the status bar.

    awww prints 'Error: "none of the requested outputs are valid"', and for bad
    arguments adds lines such as 'For more information, try '--help'.'; the
    first line, without the 'Error:' prefix and the quotes, says it all.
    """
    return _clean(next((line for line in stderr.splitlines() if line.strip()), ""))


def _last_line(lines):
    """The gist from a program that opens with a banner and closes with the error.

    Upscayl starts by printing its copyright and ends with the real problem, e.g.
    'Error: Invalid GPU Device', so its first line would read as the failure.
    """
    return _clean(next((line for line in reversed(lines) if line.strip()), ""))


def _clean(line):
    """One line without the "Error:" prefix and the quotes around it, or any
    decoration before both, which is how Upscayl marks the line that matters."""
    line = re.sub(r"^[^\w]+", "", line.strip())
    if line.lower().startswith("error:"):
        line = line[len("error:"):].strip()
    return line.strip('"')


class Cancelled(Exception):
    """A job stopped on request. Not an OSError: nothing failed, so nothing is reported."""


class Cancel:
    """Stops a run_reporting job from another thread; call it to stop.

    The job blocks reading the program's output, so a flag alone would only be
    seen once the program ends: calling this also terminates the program.
    """

    def __init__(self):
        self.requested = False
        self._process = None
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.requested = True
            if self._process:
                self._process.terminate()

    def watch(self, process):
        """The program to terminate; terminated at once if the stop came first."""
        with self._lock:
            self._process = process
            if self.requested:
                process.terminate()


def run_reporting(cmd, report=None, cancel=None):
    """Like run_or_fail, but hands each output line to `report` while the program runs.

    capture_output=True holds everything back until the program ends, which is fine
    for a query and useless for a long job. Upscayl writes to stderr, so it is
    folded into stdout: one reader for both, and no pipe left to fill up.

    Calling `cancel`, a Cancel, terminates the program and raises Cancelled here.
    """
    if cancel and cancel.requested:
        raise Cancelled
    try:
        done = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as error:
        raise OSError(None, f"{cmd[0]} could not be started: {error.strerror}") from error
    if cancel:
        cancel.watch(done)
    lines = []
    for line in done.stdout:
        lines.append(line)
        if report:
            report(line)
    done.stdout.close()
    code = done.wait()
    if code and cancel and cancel.requested:  # killed by the stop, not a failure
        raise Cancelled
    if code:
        reason = _last_line(lines) or f"exit {code}"
        raise OSError(None, f"{cmd[0]} failed: {reason}")
    return "".join(lines)


def notify(message):
    """Prints the error and shows it with notify-send, or with Hyprland if missing."""
    print(f"wallframe: {message}", file=sys.stderr)
    if shutil.which("notify-send"):
        run(["notify-send", "wallframe", message])
    elif os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        # Error icon, 5000 ms, default color.
        run(["hyprctl", "notify", "3", "5000", "0", f"wallframe: {message}"])

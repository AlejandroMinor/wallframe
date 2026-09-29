import os
import shutil
import subprocess
import sys


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
        reason = done.stderr.strip() or f"exit {done.returncode}"
        raise OSError(None, f"{cmd[0]} failed: {reason}")
    return done.stdout


def notify(message):
    """Prints the error and shows it with notify-send, or with Hyprland if missing."""
    print(f"wallframe: {message}", file=sys.stderr)
    if shutil.which("notify-send"):
        run(["notify-send", "wallframe", message])
    elif os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        # Error icon, 5000 ms, default color.
        run(["hyprctl", "notify", "3", "5000", "0", f"wallframe: {message}"])

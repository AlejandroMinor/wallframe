import os
import shutil
import subprocess
import sys


def run(cmd):
    """Returns the command's stdout, or "" if the program is missing."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout
    except OSError:
        return ""


def notify(message):
    """Prints the error and shows it with notify-send, or with Hyprland if missing."""
    print(f"wallframe: {message}", file=sys.stderr)
    if shutil.which("notify-send"):
        run(["notify-send", "wallframe", message])
    elif os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        # Error icon, 5000 ms, default color.
        run(["hyprctl", "notify", "3", "5000", "0", f"wallframe: {message}"])

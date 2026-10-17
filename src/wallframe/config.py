"""The user's settings in ~/.config/wallframe/config.ini, set in the window or by hand.

Read on each use, so a change takes effect without restarting wallframe.

    [Settings]
    post_command = wallust run "$wallpaper"
    transition_type = wipe
    transition_duration = 1.5
    transition_fps = 60
    wallpaper_folder = ~/Pictures/Wallpapers
"""

import configparser
import os
import subprocess

CONFIG_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                           "wallframe", "config.ini")
SECTION = "Settings"
# A short fade: soft, without keeping the new framing waiting.
TRANSITION_TYPE = "fade"
TRANSITION_DURATION = 0.4


def _read(path):
    """The file's parser; empty when the file is missing or broken."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path or CONFIG_FILE)
    except (configparser.Error, UnicodeDecodeError):
        return configparser.ConfigParser(interpolation=None)
    return parser


def get(key, path=None):
    """A setting as written, or "" when it is not set: settings never stop wallframe."""
    return _read(path).get(SECTION, key, fallback="").strip()


def post_command(path=None):
    """The command to run after the wallpaper changes, or "" when none is set."""
    return get("post_command", path)


def wallpaper_folder(default, path=None):
    """The folder the wallpaper picker shows, or `default` when none is set."""
    return os.path.expanduser(get("wallpaper_folder", path)) or default


def transition(path=None):
    """{option: value} of the effect awww or swww shows when the wallpaper changes.

    type and duration always have a value; fps, step and angle only when set,
    since awww picks its own otherwise (step depends on the type).
    """
    settings = {"type": get("transition_type", path) or TRANSITION_TYPE,
                "duration": _number(get("transition_duration", path), float, 0, 3600)}
    if settings["duration"] is None:
        settings["duration"] = TRANSITION_DURATION
    for key, low, high in (("fps", 1, 1000), ("step", 1, 255), ("angle", 0, 360)):
        value = _number(get(f"transition_{key}", path), int, low, high)
        if value is not None:
            settings[key] = value
    return settings


def _number(text, kind, low, high):
    """`text` as a number from `low` to `high`, or None when it is not one."""
    try:
        value = kind(float(text))
    except ValueError:
        return None
    return value if low <= value <= high else None


def save(values, path=None):
    """Writes each {key: value}, or removes it when the value is empty, keeping the rest
    of the file. Raises OSError when it cannot be written."""
    path = path or CONFIG_FILE
    parser = _read(path)
    if not parser.has_section(SECTION):
        parser.add_section(SECTION)
    for key, value in values.items():
        value = str(value).strip()
        if value:
            parser.set(SECTION, key, value)
        else:
            parser.remove_option(SECTION, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"  # swapped in, so a failure keeps the old file whole
    try:
        with open(temporary, "w") as f:
            parser.write(f)
        os.replace(temporary, path)
    except OSError:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def run_post_command(command, wallpaper, monitors):
    """Runs `command` in a shell and waits for it; raises OSError when it fails.

    The picture is in $wallpaper, as waypaper names it, and in $WALLFRAME_WALLPAPER;
    the monitors that changed, comma separated, in $WALLFRAME_MONITORS.
    """
    env = dict(os.environ, wallpaper=wallpaper, WALLFRAME_WALLPAPER=wallpaper,
               WALLFRAME_MONITORS=",".join(monitors))
    done = subprocess.run(command, shell=True, env=env, capture_output=True, text=True)
    if done.returncode:
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        reason = lines[-1].strip() if lines else f"exit {done.returncode}"
        raise OSError(None, f"post_command failed: {reason}")

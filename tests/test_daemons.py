"""Tests for reading `awww query` / `swww query` and its help: parsing only, no daemon runs."""

from wallframe import config, daemons
from wallframe.daemons import Daemon, Output, parse_query, parse_transitions

# Real output of `awww query` on a three-monitor setup, plus one output
# showing a plain color, which has no image to frame.
QUERY = """\
: HDMI-A-1: 1080x1920, scale: 1, currently displaying: image: /home/me/.local/share/wallframe/HDMI-A-1-1790191732.png
: DP-1: 1080x1920, scale: 1, currently displaying: image: /home/me/Pictures/My Wallpapers/geek.jpg
: DP-2: 2560x1440, scale: 1, currently displaying: image: /home/me/Pictures/evangelion.jpg
: eDP-1: 1920x1080, scale: 1, currently displaying: color: 000000
"""


def test_reads_every_output_showing_an_image():
    assert parse_query(QUERY) == [
        Output("HDMI-A-1", 1080, 1920, "/home/me/.local/share/wallframe/HDMI-A-1-1790191732.png"),
        Output("DP-1", 1080, 1920, "/home/me/Pictures/My Wallpapers/geek.jpg"),
        Output("DP-2", 2560, 1440, "/home/me/Pictures/evangelion.jpg"),
    ]


def test_no_daemon_means_no_outputs():
    assert parse_query("") == []
    assert parse_query("error: could not connect to socket\n") == []


def test_a_new_wallpaper_fades_in_quickly(monkeypatch):
    ran = []
    monkeypatch.setattr(daemons, "run_or_fail", ran.append)
    Daemon("awww").set_image("DP-1", "/tmp/crop.png")
    (cmd,) = ran
    assert cmd[cmd.index("--transition-type") + 1] == "fade"
    assert float(cmd[cmd.index("--transition-duration") + 1]) < 1   # soft, not slow
    assert cmd[-1] == "/tmp/crop.png"


def test_the_transition_comes_from_the_settings(monkeypatch):
    ran = []
    monkeypatch.setattr(daemons, "run_or_fail", ran.append)
    config.save({"transition_type": "wipe", "transition_duration": "1.5",
                 "transition_fps": "60", "transition_step": "63"})
    Daemon("awww").set_image("DP-1", "/tmp/crop.png")
    (cmd,) = ran
    assert cmd[cmd.index("--transition-type") + 1] == "wipe"
    assert cmd[cmd.index("--transition-duration") + 1] == "1.5"
    assert cmd[cmd.index("--transition-fps") + 1] == "60"
    assert cmd[cmd.index("--transition-step") + 1] == "63"
    assert "--transition-angle" not in cmd               # not set: awww's own


# awww 0.12.1's `awww img --help`, cut to the part that matters.
HELP = """\
  -t, --transition-type <TRANSITION_TYPE>
          Sets the type of transition. Default is 'simple', that fades into the new image

          Possible transitions are:

          none | simple | fade | left | right | top | bottom | wipe | wave | grow | center | any |
          outer | random

          The 'left', 'right', 'top' and 'bottom' options make the transition happen from that
"""


def test_reads_the_transitions_from_the_help():
    assert parse_transitions(HELP) == ["none", "simple", "fade", "left", "right", "top",
                                       "bottom", "wipe", "wave", "grow", "center", "any",
                                       "outer", "random"]
    assert parse_transitions("") == []


def test_asks_for_the_transitions_once(monkeypatch):
    asked = []
    monkeypatch.setattr(daemons, "run", lambda cmd: asked.append(cmd) or HELP)
    daemon = Daemon("swww")
    assert daemon.transitions()[:3] == ["none", "simple", "fade"]
    daemon.transitions()
    assert asked == [["swww", "img", "--help"]]

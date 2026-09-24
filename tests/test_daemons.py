"""Tests for reading `awww query` / `swww query`: parsing only, no daemon runs."""

from wallframe.daemons import Output, parse_query

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

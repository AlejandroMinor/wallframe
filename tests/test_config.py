"""Tests for config.ini: always a file in a temporary folder."""

import pytest

from wallframe import config


def write(tmp_path, text):
    path = tmp_path / "config.ini"
    path.write_text(text)
    return str(path)


def test_reads_post_command_as_waypaper_writes_it(tmp_path):
    path = write(tmp_path, '[Settings]\npost_command = bash -c "$HOME/x.sh --notify"\n')
    assert config.post_command(path) == 'bash -c "$HOME/x.sh --notify"'


@pytest.mark.parametrize("text", ["", "[Settings]\n", "[Other]\npost_command = x\n",
                                  "post_command = no section\n", "[Settings\n"])
def test_no_command_when_missing_or_broken(tmp_path, text):
    assert config.post_command(write(tmp_path, text)) == ""
    assert config.post_command(str(tmp_path / "missing.ini")) == ""


def test_the_command_gets_the_wallpaper_and_monitors(tmp_path):
    out = tmp_path / "out"
    config.run_post_command(f'echo "$wallpaper|$WALLFRAME_WALLPAPER|$WALLFRAME_MONITORS" > {out}',
                            "/pics/a b.png", ["DP-1", "DP-2"])
    assert out.read_text() == "/pics/a b.png|/pics/a b.png|DP-1,DP-2\n"


def test_a_failing_command_says_why():
    with pytest.raises(OSError, match="post_command failed: nope"):
        config.run_post_command("echo starting; echo nope >&2; exit 3", "/a.png", ["DP-1"])
    with pytest.raises(OSError, match="exit 4"):
        config.run_post_command("exit 4", "/a.png", ["DP-1"])


def test_save_keeps_the_rest_of_the_file(tmp_path):
    path = write(tmp_path, "[Settings]\nother = 1\n\n[Extra]\nkey = value\n")
    config.save({"post_command": '  bash -c "$HOME/x.sh"  '}, path)
    assert config.post_command(path) == 'bash -c "$HOME/x.sh"'
    config.save({"post_command": ""}, path)
    assert config.post_command(path) == ""
    text = (tmp_path / "config.ini").read_text()
    assert "other = 1" in text and "key = value" in text
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.ini"]


def test_save_makes_the_file(tmp_path):
    path = str(tmp_path / "new" / "config.ini")
    config.save({"post_command": "notify-send done"}, path)
    assert config.post_command(path) == "notify-send done"


def test_transition_defaults_to_a_short_fade(tmp_path):
    assert config.transition(str(tmp_path / "missing.ini")) == {"type": "fade", "duration": 0.4}
    path = write(tmp_path, "[Settings]\ntransition_type = wipe\ntransition_duration = 2\n"
                           "transition_fps = 60\ntransition_step = 63\ntransition_angle = 30\n")
    assert config.transition(path) == {"type": "wipe", "duration": 2.0, "fps": 60,
                                       "step": 63, "angle": 30}


@pytest.mark.parametrize("value", ["slow", "-1", "", "9999"])
def test_bad_numbers_fall_back_to_the_defaults(tmp_path, value):
    path = write(tmp_path, f"[Settings]\ntransition_duration = {value}\n"
                           f"transition_fps = {value}\ntransition_step = {value}\n")
    assert config.transition(path) == {"type": "fade", "duration": 0.4}


def test_panel_width_falls_back_to_the_default(tmp_path):
    assert config.panel_width(550, str(tmp_path / "missing.ini")) == 550
    assert config.panel_width(550, write(tmp_path, "[Settings]\npanel_width = 320\n")) == 320
    assert config.panel_width(550, write(tmp_path, "[Settings]\npanel_width = wide\n")) == 550

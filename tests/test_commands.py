"""Tests for how errors reach the user; no program is really started."""

import subprocess

import pytest

from wallframe import commands


def completes(returncode, out="", err=""):
    return lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, returncode, out, err)


@pytest.fixture
def calls(monkeypatch):
    """Records the commands notify() would run instead of running them."""
    ran = []
    monkeypatch.setattr(commands, "run", ran.append)
    return ran


def test_prefers_notify_send(monkeypatch, calls, capsys):
    monkeypatch.setattr(commands.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    commands.notify("No image wallpaper found.")
    assert calls == [["notify-send", "wallframe", "No image wallpaper found."]]
    assert capsys.readouterr().err == "wallframe: No image wallpaper found.\n"


def test_falls_back_to_hyprland(monkeypatch, calls):
    monkeypatch.setattr(commands.shutil, "which", lambda name: None)
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    commands.notify("No image wallpaper found.")
    assert calls == [["hyprctl", "notify", "3", "5000", "0",
                      "wallframe: No image wallpaper found."]]


def test_only_stderr_elsewhere(monkeypatch, calls, capsys):
    monkeypatch.setattr(commands.shutil, "which", lambda name: None)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    commands.notify("No image wallpaper found.")
    assert calls == []
    assert "No image wallpaper found." in capsys.readouterr().err


def test_a_command_that_works_gives_its_output(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "run", completes(0, ": DP-1: 1080x1920"))
    assert commands.run_or_fail(["awww", "query"]) == ": DP-1: 1080x1920"


def test_a_command_that_fails_says_what_the_program_said(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "run", completes(1, err="unknown output: DP-9\n"))
    with pytest.raises(OSError) as failed:
        commands.run_or_fail(["awww", "img", "-o", "DP-9", "crop.png"])
    assert failed.value.strerror == "awww failed: unknown output: DP-9"   # what the user reads


def test_a_command_that_fails_quietly_still_says_something(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "run", completes(127))
    with pytest.raises(OSError) as failed:
        commands.run_or_fail(["awww", "img"])
    assert failed.value.strerror == "awww failed: exit 127"


def test_a_command_that_is_not_installed_does_not_look_like_a_missing_file(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(commands.subprocess, "run", missing)
    with pytest.raises(OSError) as failed:
        commands.run_or_fail(["awww", "img"])
    # Not a FileNotFoundError: the editor reads that as the wallpaper being gone.
    assert not isinstance(failed.value, FileNotFoundError)
    assert failed.value.strerror == "awww could not be started: No such file or directory"


def test_queries_stay_silent_about_failing(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "run", completes(1, err="no socket"))
    assert commands.run(["awww", "query"]) == ""


@pytest.mark.parametrize("stderr, reason", [
    # What awww really prints for an output that does not exist.
    ('Error: "none of the requested outputs are valid"\n',
     "none of the requested outputs are valid"),
    # And for a bad argument, with a hint on the lines after.
    ("error: invalid value '/tmp/x.png' for '<IMAGE>': Path '/tmp/x.png' does not exist\n\n"
     "For more information, try '--help'.\n",
     "invalid value '/tmp/x.png' for '<IMAGE>': Path '/tmp/x.png' does not exist"),
    ("\n  unknown output: DP-9  \n", "unknown output: DP-9"),
])
def test_a_failure_reads_as_one_clean_line(monkeypatch, stderr, reason):
    monkeypatch.setattr(commands.subprocess, "run", completes(1, err=stderr))
    with pytest.raises(OSError) as failed:
        commands.run_or_fail(["awww", "img"])
    assert failed.value.strerror == f"awww failed: {reason}"

"""Tests for how errors reach the user; no program is really started."""

import io
import subprocess
from unittest.mock import MagicMock

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


def speaker(lines, returncode=0):
    """A program that printed `lines`, for run_reporting to read."""
    def popen(cmd, **kwargs):
        popen.cmd = cmd
        popen.kwargs = kwargs
        popen.process = MagicMock(stdout=io.StringIO("".join(lines)), wait=lambda: returncode)
        return popen.process
    return popen


def test_reports_every_line_before_the_program_ends(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "Popen", speaker(["one\n", "two\n"]))
    seen = []
    commands.run_reporting(["upscayl-ncnn", "-i", "in.png"], seen.append)
    assert seen == ["one\n", "two\n"]


def test_both_streams_are_read_together(monkeypatch):
    """Folding stderr into stdout keeps one reader and no pipe that fills up."""
    popen = speaker([])
    monkeypatch.setattr(commands.subprocess, "Popen", popen)
    commands.run_reporting(["upscayl-ncnn"])
    assert popen.kwargs["stderr"] == subprocess.STDOUT
    assert popen.kwargs["stdout"] == subprocess.PIPE


def test_works_without_anybody_listening(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "Popen", speaker(["done\n"]))
    assert commands.run_reporting(["upscayl-ncnn"]) == "done\n"


def test_a_failure_blames_the_error_and_not_the_banner(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "Popen", speaker(
        ["\U0001f680 Starting Upscayl - Copyright © 2024\n",
         "vkCreateInstance failed -9\n",
         "\U0001f6a8 Error: Invalid GPU Device\n"], returncode=1))
    with pytest.raises(OSError) as failed:
        commands.run_reporting(["upscayl-ncnn", "-i", "in.png"])
    assert failed.value.strerror == "upscayl-ncnn failed: Invalid GPU Device"


def test_a_failure_that_says_nothing_still_says_something(monkeypatch):
    monkeypatch.setattr(commands.subprocess, "Popen", speaker([], returncode=127))
    with pytest.raises(OSError) as failed:
        commands.run_reporting(["upscayl-ncnn"])
    assert failed.value.strerror == "upscayl-ncnn failed: exit 127"


def test_a_program_that_never_starts_does_not_look_like_a_missing_file(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(commands.subprocess, "Popen", missing)
    with pytest.raises(OSError) as failed:
        commands.run_reporting(["upscayl-ncnn"])
    assert not isinstance(failed.value, FileNotFoundError)
    assert failed.value.strerror == "upscayl-ncnn could not be started: No such file or directory"


def test_cancelling_terminates_the_program_and_says_so(monkeypatch):
    popen = speaker(["0.00%\n", "4.17%\n"], returncode=-15)   # killed by SIGTERM
    monkeypatch.setattr(commands.subprocess, "Popen", popen)
    cancel = commands.Cancel()
    with pytest.raises(commands.Cancelled):
        commands.run_reporting(["upscayl-ncnn"], lambda line: cancel(), cancel)
    popen.process.terminate.assert_called()


def test_a_cancel_before_the_start_starts_nothing(monkeypatch):
    popen = speaker([])
    monkeypatch.setattr(commands.subprocess, "Popen", popen)
    cancel = commands.Cancel()
    cancel()
    with pytest.raises(commands.Cancelled):
        commands.run_reporting(["upscayl-ncnn"], cancel=cancel)
    assert not hasattr(popen, "cmd")


def test_a_cancel_that_comes_too_late_keeps_the_result(monkeypatch):
    """The program had already finished: its output is good, and nothing failed."""
    monkeypatch.setattr(commands.subprocess, "Popen", speaker(["done\n"]))
    cancel = commands.Cancel()
    assert commands.run_reporting(["upscayl-ncnn"], lambda line: cancel(), cancel) == "done\n"

"""Tests for the Upscayl adapter; Upscayl itself never runs."""

import os

import pytest
from PIL import Image

from wallframe import upscalers
from wallframe.upscalers import Upscaler

MODEL = "upscayl-standard-4x"


@pytest.fixture
def fake_upscayl(monkeypatch):
    """Stands in for upscayl-ncnn: writes the enlarged image, and counts its runs."""
    runs = []

    def run_reporting(cmd, report=None):
        runs.append(cmd)
        source, output, scale = cmd[cmd.index("-i") + 1], cmd[cmd.index("-o") + 1], cmd[-1]
        if report:
            report("0.00%\n")
            report("100.00%\n")
        with Image.open(source) as img:
            img.resize((img.width * int(scale), img.height * int(scale))).save(output)

    monkeypatch.setattr(upscalers, "run_reporting", run_reporting)
    return runs


def picture(tmp_path, name="low.png"):
    path = tmp_path / name
    Image.new("RGB", (100, 50)).save(path)
    return str(path)


def upscaler(tmp_path):
    return Upscaler("upscayl-ncnn", str(tmp_path / "models"), directory=str(tmp_path / "upscaled"))


def test_upscales_once_and_reuses_it(tmp_path, fake_upscayl):
    up = upscaler(tmp_path)
    source = picture(tmp_path)
    first = up.upscale(source, MODEL, 2)
    assert Image.open(first).size == (200, 100)
    assert up.upscale(source, MODEL, 2) == first
    assert len(fake_upscayl) == 1                            # the second time came from disk
    assert up.owns(first)
    assert not up.owns(source)


def test_each_model_and_scale_is_its_own_copy(tmp_path, fake_upscayl):
    up = upscaler(tmp_path)
    source = picture(tmp_path)
    copies = {up.upscale(source, MODEL, 2), up.upscale(source, MODEL, 3),
              up.upscale(source, "digital-art-4x", 2)}
    assert len(copies) == 3
    assert Image.open(up.upscale(source, MODEL, 3)).size == (300, 150)


def test_an_edited_image_is_upscaled_again(tmp_path, fake_upscayl):
    up = upscaler(tmp_path)
    source = picture(tmp_path)
    first = up.upscale(source, MODEL, 2)
    os.utime(source, ns=(1, 1))                              # the file changed since
    assert up.upscale(source, MODEL, 2) != first
    assert len(fake_upscayl) == 2


def test_a_failed_upscale_leaves_nothing_behind(tmp_path, monkeypatch):
    def fails(cmd, report=None):
        open(cmd[cmd.index("-o") + 1], "wb").close()         # a half-written output
        raise OSError(None, "upscayl-ncnn failed: vkCreateInstance failed")

    monkeypatch.setattr(upscalers, "run_reporting", fails)
    up = upscaler(tmp_path)
    with pytest.raises(OSError):
        up.upscale(picture(tmp_path), MODEL, 2)
    assert os.listdir(tmp_path / "upscaled") == []


def test_clean_keeps_only_what_is_in_use(tmp_path, fake_upscayl):
    up = upscaler(tmp_path)
    used = up.upscale(picture(tmp_path, "a.png"), MODEL, 2)
    up.upscale(picture(tmp_path, "b.png"), MODEL, 2)
    up.clean(keep={used})
    assert os.listdir(tmp_path / "upscaled") == [os.path.basename(used)]


# Everything upscayl-ncnn printed for a 1024x640 image, minus the emojis it
# decorates its lines with, which are not in any test but this one. Four lines
# of Vulkan device banner starting with "[0 ", two resize notes with the sizes
# in them, and the percentages. Only the last group is progress, and the bar has
# to skip the rest.
UPCSCAYL_OUTPUT = """\
Starting Upscayl - Copyright © 2024
Detected scale x4
Using the default scale x4
[0 AMD Radeon Graphics (RADV RENOIR)]  queueC=1[4]  queueG=0[1]  queueT=0[1]
[0 AMD Radeon Graphics (RADV RENOIR)]  bugsbn1=0  bugbilz=0  bugcopc=0  bugihfa=0
[0 AMD Radeon Graphics (RADV RENOIR)]  fp16-p/s/a=1/1/1  int8-p/s/a=1/1/1
[0 AMD Radeon Graphics (RADV RENOIR)]  subgroup=64  basic=1  vote=1  ballot=1  shuffle=1
0.00%
4.17%
8.33%
12.50%
16.67%
20.83%
25.00%
29.17%
33.33%
37.50%
41.67%
45.83%
50.00%
54.17%
58.33%
62.50%
66.67%
70.83%
75.00%
79.17%
83.33%
87.50%
91.67%
95.83%
Resizing image according to output scale
Scaled image from 1024x640 to 2048x1280
100.00%

Upscayled Successfully!
"""


def test_only_the_percentages_of_a_real_run_count_as_progress():
    """The whole output of one run, not a few lines picked to suit the parser.

    The resize notes sit between the last percentage and the 100%, so a parser
    that simply took the last line it saw would stop at 95.83%.
    """
    lines = UPCSCAYL_OUTPUT.splitlines(keepends=True)
    reported = [upscalers.percent(line) for line in lines]
    assert [done for done in reported if done is not None] == [
        0.0, 4.17, 8.33, 12.5, 16.67, 20.83, 25.0, 29.17, 33.33, 37.5, 41.67, 45.83,
        50.0, 54.17, 58.33, 62.5, 66.67, 70.83, 75.0, 79.17, 83.33, 87.5, 91.67, 95.83,
        100.0]
    assert len(reported) == len(lines)          # every line went through percent()


def test_a_line_without_a_percentage_is_not_one():
    """A number is not progress on its own, wherever it sits in the line."""
    for line in ("[0 AMD Radeon Graphics (RADV RENOIR)]  queueC=1[4]\n",
                 "Scaled image from 1024x640 to 2048x1280\n",
                 "Detected scale x4\n", "Error: Invalid GPU Device\n"):
        assert upscalers.percent(line) is None


def test_progress_is_reported_while_it_runs(tmp_path, fake_upscayl):
    up = upscaler(tmp_path)
    seen = []
    up.upscale(picture(tmp_path), MODEL, 2, seen.append)
    assert [upscalers.percent(line) for line in seen] == [0.0, 100.0]


def test_a_copy_reused_from_disk_reports_nothing(tmp_path, fake_upscayl):
    up = upscaler(tmp_path)
    source = picture(tmp_path)
    up.upscale(source, MODEL, 2)
    seen = []
    up.upscale(source, MODEL, 2, seen.append)
    assert seen == []


def test_offers_only_the_installed_models(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "digital-art-4x.param").write_text("")
    assert [model for model, _ in upscaler(tmp_path).models] == ["digital-art-4x"]


def test_not_detected_without_models(monkeypatch):
    monkeypatch.setattr(upscalers.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(upscalers, "_MODEL_DIRS", ("/nowhere",))
    assert upscalers.detect() is None

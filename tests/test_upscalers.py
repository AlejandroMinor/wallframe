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

    def run_or_fail(cmd):
        runs.append(cmd)
        source, output, scale = cmd[cmd.index("-i") + 1], cmd[cmd.index("-o") + 1], cmd[-1]
        with Image.open(source) as img:
            img.resize((img.width * int(scale), img.height * int(scale))).save(output)

    monkeypatch.setattr(upscalers, "run_or_fail", run_or_fail)
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
    def fails(cmd):
        open(cmd[cmd.index("-o") + 1], "wb").close()         # a half-written output
        raise OSError(None, "upscayl-ncnn failed: vkCreateInstance failed")

    monkeypatch.setattr(upscalers, "run_or_fail", fails)
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


def test_offers_only_the_installed_models(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "digital-art-4x.param").write_text("")
    assert [model for model, _ in upscaler(tmp_path).models] == ["digital-art-4x"]


def test_not_detected_without_models(monkeypatch):
    monkeypatch.setattr(upscalers.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(upscalers, "_MODEL_DIRS", ("/nowhere",))
    assert upscalers.detect() is None

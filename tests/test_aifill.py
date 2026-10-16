import pytest

from wallframe import aifill


@pytest.mark.parametrize("size, ratio", [
    ((1920, 1080), "16:9"), ((1080, 1920), "9:16"), ((5098, 2321), "21:9"),
    ((3440, 1440), "21:9"), ((5120, 1440), "32:9"), ((1000, 1000), "1:1")])
def test_the_closest_common_ratio(size, ratio):
    assert aifill.nearest(*size) == ratio


def test_the_prompt_carries_the_color_and_the_size_of_what_is_exported():
    text = aifill.prompt("#ff00aa", 5098, 2321)
    assert text.count("#ff00aa") == 2                    # the area, and no trace of it
    assert "5098x2321" in text and "2.20:1" in text and "21:9" in text
    assert "mask" in text                                 # for the AI that takes one
    assert "green" not in text                            # any color works, not only that one


def test_the_prompt_says_where_the_original_sits_when_it_is_known():
    text = aifill.prompt("#ff00aa", 1000, 400, (200, 40, 800, 360))
    assert "from 20% to 80% of the width" in text and "from 10% to 90% of the height" in text
    assert "no visible seam" in text and "crop of a larger scene" in text
    assert "from 20%" not in aifill.prompt("#ff00aa", 1000, 400)       # unknown: not guessed


def test_the_color_least_in_a_picture_is_the_one_chosen():
    from PIL import Image
    red_and_green = Image.new("RGB", (20, 20), (255, 0, 0))
    red_and_green.paste((0, 255, 0), (0, 0, 20, 10))                 # half green, half red
    assert aifill.share(red_and_green, "#00ff00") == pytest.approx(0.5)
    assert aifill.share(red_and_green, "#0000ff") == 0
    chosen, name = aifill.least_present(red_and_green)
    assert chosen != "#00ff00" and aifill.share(red_and_green, chosen) == 0
    assert name == aifill.name_of(chosen) and aifill.name_of("#123456") == "#123456"


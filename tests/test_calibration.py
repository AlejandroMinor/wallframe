from PIL import Image

from test_span import two_monitors
from wallframe import calibration, span


def make_span(tmp_path, sizes=None):
    monitors, positions = two_monitors(tmp_path, right=(400, 200))
    return span.make(monitors, positions, sizes=sizes)


def test_the_picture_is_as_sharp_as_the_sharpest_monitor(tmp_path):
    across = make_span(tmp_path)
    destination = str(tmp_path / "out" / calibration.FILE)
    calibration.make(across, destination)
    with Image.open(destination) as image:
        assert image.size == (across.width * 2, across.height * 2)  # DP-2: 2 pixels per unit


def test_each_monitor_is_outlined_in_its_own_color(tmp_path):
    across = make_span(tmp_path, sizes={"DP-1": (500, 250), "DP-2": (500, 250)})
    destination = str(tmp_path / "calibration.png")
    calibration.make(across, destination)
    with Image.open(destination) as image:
        assert image.getpixel((1, 1)) == calibration.OUTLINES[0]
        assert image.getpixel((image.width - 2, 1)) == calibration.OUTLINES[1]
    assert across.units_per_mm == 200 / 500


def test_without_real_sizes_it_still_draws(tmp_path):
    across = make_span(tmp_path)
    assert across.units_per_mm is None
    calibration.make(across, str(tmp_path / "calibration.png"))

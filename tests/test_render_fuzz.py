"""Random framings through the whole render path, to catch edge cases like
float boxes landing a hair past an image edge. Seeded, so failures repeat."""

import random

import pytest
from PIL import Image

from wallframe import render
from wallframe.framing import Framing

CASES = 300


def random_framing(rng):
    """Any monitor and image shape, any zoom, often pushed against an edge."""
    f = Framing(rng.randint(20, 300), rng.randint(20, 300),     # monitor
                rng.randint(20, 900), rng.randint(20, 900))     # image
    for _ in range(rng.randint(0, 3)):
        rng.choice([f.rotate, lambda: f.mirror(True), lambda: f.mirror(False)])()
    f.zoom_at(rng.choice([0.01, 0.3, 0.5, 0.8, 1, 1.3, 3, 100]), rng.uniform(0, f.monitor_w),
              rng.uniform(0, f.monitor_h))
    edge = 10 ** 6
    f.move_to(rng.choice([-edge, edge, rng.uniform(-500, 500)]),
              rng.choice([-edge, edge, rng.uniform(-500, 500)]))
    f.fill = rng.choice(["blur", "color"])
    f.blur = rng.choice([0, 8, 64, 160])
    f.backdrop.zoom_at(rng.choice([1, 1.7, 8]), rng.uniform(0, f.monitor_w), 0)
    f.backdrop.move_to(rng.choice([-edge, edge, 0]), rng.choice([-edge, edge, 0]))
    return f


@pytest.mark.parametrize("seed", range(CASES))
def test_any_framing_renders(tmp_path, seed):
    rng = random.Random(seed)
    f = random_framing(rng)
    source = tmp_path / "src.png"
    Image.new("RGB", (f.source_w, f.source_h), (rng.randrange(256), 90, 40)).save(source)

    render.crop(source, f, tmp_path / "out.png")
    with Image.open(tmp_path / "out.png") as out:
        assert out.size == (f.monitor_w, f.monitor_h)

    # The preview path: a thumbnail whose size is rounded, as render.thumbnail makes it.
    thumb = render.transform(render.thumbnail(source, rng.randint(16, 256)), f)
    half = (max(1, f.monitor_w // 2), max(1, f.monitor_h // 2))
    if not f.covers:
        assert render.background(thumb, f, half).size == half

"""Reading a monitor's real size from its EDID."""

from wallframe import edid

HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"


def fake(width_mm=0, height_mm=0, width_cm=0, height_cm=0, timing=True):
    data = bytearray(128)
    data[:8] = HEADER
    data[21], data[22] = width_cm, height_cm
    if timing:
        data[54:56] = b"\x01\x1d"  # a pixel clock: the first descriptor is a timing
        data[66], data[67] = width_mm & 0xFF, height_mm & 0xFF
        data[68] = (width_mm >> 8) << 4 | height_mm >> 8
    return bytes(data)


def test_the_size_comes_from_the_first_timing_in_millimeters():
    assert edid.parse(fake(597, 336, 60, 34)) == (597, 336)


def test_sizes_past_255_millimeters_keep_their_high_bits():
    assert edid.parse(fake(1210, 680)) == (1210, 680)


def test_without_one_it_falls_back_to_whole_centimeters():
    assert edid.parse(fake(width_cm=53, height_cm=30, timing=False)) == (530, 300)


def test_a_projector_that_gives_no_size_has_none():
    assert edid.parse(fake()) is None
    assert edid.parse(b"") is None
    assert edid.parse(b"\x01" * 128) is None


def test_connectors_are_named_like_the_outputs(tmp_path):
    for connector, data in (("card1-DP-1", fake(597, 336)), ("card1-HDMI-A-1", b""),
                            ("card1-eDP-1", fake(309, 173))):
        (tmp_path / connector).mkdir()
        (tmp_path / connector / "edid").write_bytes(data)
    (tmp_path / "renderD128").mkdir()
    assert edid.sizes(tmp_path) == {"DP-1": (597, 336), "eDP-1": (309, 173)}
    assert edid.sizes(tmp_path / "missing") == {}

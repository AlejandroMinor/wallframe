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


def named(text, slot=1):
    """An EDID whose descriptor `slot` (0 to 3) is the monitor's name."""
    data = bytearray(fake(597, 336))
    start = 54 + 18 * slot
    data[start:start + 5] = b"\x00\x00\x00\xfc\x00"
    data[start + 5:start + 18] = (text.encode() + b"\n").ljust(13, b" ")[:13]
    return bytes(data)


def test_the_name_comes_from_its_descriptor_without_the_newline_and_padding():
    assert edid.name(named("DELL U2720Q")) == "DELL U2720Q"
    assert edid.name(named("LG HDR 4K", slot=3)) == "LG HDR 4K"


def test_a_name_of_thirteen_characters_has_no_newline():
    assert edid.name(named("ABCDEFGHIJKLM")) == "ABCDEFGHIJKLM"


def test_without_a_name_descriptor_there_is_no_name():
    assert edid.name(fake(597, 336)) == ""
    assert edid.name(b"") == ""

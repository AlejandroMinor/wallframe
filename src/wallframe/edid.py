"""How big each monitor really is, from its EDID: what the span needs to keep one
picture at the same size across monitors of different densities.

The kernel shows every connector's EDID under /sys/class/drm, named like the
outputs Wayland compositors use (card1-DP-1 is DP-1), on any desktop.
"""

import os
import re

DRM_DIR = "/sys/class/drm"
_CONNECTOR = re.compile(r"card\d+-(.+)")


def parse(edid):
    """(width, height) in millimeters, or None when the EDID does not say.

    The first detailed timing gives millimeters; the header only whole
    centimeters, so it is the fallback. Projectors and some TVs give zero.
    """
    if len(edid) < 128 or edid[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    width = edid[66] | (edid[68] & 0xF0) << 4
    height = edid[67] | (edid[68] & 0x0F) << 8
    if width and height and edid[54:56] != b"\x00\x00":  # a timing, not another descriptor
        return width, height
    if edid[21] and edid[22]:
        return edid[21] * 10, edid[22] * 10
    return None


def sizes(directory=DRM_DIR):
    """{output name: (width, height) in millimeters} for the connected monitors that say."""
    found = {}
    for entry in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        match = _CONNECTOR.fullmatch(entry)
        if not match:
            continue
        try:
            with open(os.path.join(directory, entry, "edid"), "rb") as f:
                size = parse(f.read())
        except OSError:
            continue
        if size:
            found[match[1]] = size
    return found


def name(edid):
    """The monitor's model as it names itself, like "DELL U2720Q", or "" when it does not.

    One of the four 18-byte descriptors after the timings may be the name: it
    starts with three zero bytes and the tag 0xFC, and its text ends at a
    newline. Windows has no other place that tells the model.
    """
    if len(edid) < 128 or edid[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return ""
    for start in range(54, 126, 18):
        block = edid[start:start + 18]
        if block[:3] == b"\x00\x00\x00" and block[3] == 0xFC:
            return block[5:].split(b"\n")[0].decode("cp437").strip()
    return ""

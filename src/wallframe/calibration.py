"""A picture to line the span's monitors up by: a grid in real centimeters, with every
monitor outlined and named. The thick lines are numbered and two diagonals cross every
join, because a plain grid repeats itself and hides a shift of the monitors along it.
The numbers and the diagonals meet across the monitors when they stand on the canvas
as they do on the desk, bezels aside: a hidden strip shows as a jump in the numbers."""

import os

from PIL import Image, ImageDraw, ImageFont

FILE = "calibration.png"
BACKGROUND = (24, 26, 32)
MONITOR = (34, 38, 48)
MINOR = (58, 63, 76)
MAJOR = (110, 118, 140)
CENTER = (255, 255, 255)
DIAGONAL = (255, 214, 102)
LABEL = (190, 198, 216)   # the numbers of the vertical lines: distance from the left
LABEL_DOWN = (150, 224, 176)  # those of the horizontal lines: distance from the top
OUTLINES = [(255, 99, 99), (99, 200, 120), (99, 160, 255), (255, 200, 80), (200, 120, 255)]
MINOR_MM, MAJOR_MM = 10, 50
LABEL_MM, LABEL_UNITS = 7, 20  # height of the numbers: in millimeters, or span units
FALLBACK_UNITS = 50  # span units between thin lines when the real sizes are unknown


def make(span, destination):
    """Writes the picture for `span`, as large as its sharpest monitor needs.

    Raises OSError when it cannot be written.
    """
    scale = max(m.width / span.places[m.name][2] for m in span.monitors)
    width, height = round(span.width * scale), round(span.height * scale)
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    frames = span.frames()
    for _name, x, y, w, h in frames:
        draw.rectangle([x * scale, y * scale, (x + w) * scale, (y + h) * scale], fill=MONITOR)

    thin = MINOR_MM * span.units_per_mm if span.units_per_mm else FALLBACK_UNITS
    every = MAJOR_MM // MINOR_MM  # thin lines between thick ones
    for k in range(int(max(span.width, span.height) / thin) + 1):
        major = k % every == 0
        color, line = (MAJOR, 2) if major else (MINOR, 1)
        at = k * thin * scale
        draw.line([(at, 0), (at, height)], fill=color, width=line)
        draw.line([(0, at), (width, at)], fill=color, width=line)

    heavy = max(3, round(scale * 3))
    draw.line([(0, 0), (width, height)], fill=DIAGONAL, width=heavy)
    draw.line([(0, height), (width, 0)], fill=DIAGONAL, width=heavy)
    draw.line([(width / 2, 0), (width / 2, height)], fill=CENTER, width=heavy)
    draw.line([(0, height / 2), (width, height / 2)], fill=CENTER, width=heavy)
    _number_lines(draw, span, frames, scale, thin * every)

    for color, (name, x, y, w, h) in zip(_cycle(OUTLINES), frames):
        border = max(4, round(scale * 4))
        draw.rectangle([x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1],
                       outline=color, width=border)
        label = name
        if span.units_per_mm:
            _x, _y, real_w, real_h = span.places[name]  # the monitor's own size, turned or not
            label += f"\n{round(real_w / span.units_per_mm)} x {round(real_h / span.units_per_mm)} mm"
        draw.multiline_text(((x + w / 2) * scale, (y + h / 2) * scale), label, fill=color,
                            font=_font(round(min(w, h) * scale / 10)), anchor="mm",
                            align="center")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    image.save(destination)


def _cycle(colors):
    while True:
        yield from colors


def _font(size):
    try:
        return ImageFont.load_default(size=max(size, 12))
    except TypeError:  # Pillow before 10.1 has only the one small font
        return ImageFont.load_default()


def _number_lines(draw, span, frames, scale, step):
    """Writes each thick line's distance from the box's corner: along the vertical
    lines at a few heights, so every monitor shows some, and beside the horizontal
    ones at each monitor's left edge. In centimeters, or span units without sizes."""
    unit = MAJOR_MM // 10 if span.units_per_mm else round(step)  # 5 cm, or span units
    size = (LABEL_MM * span.units_per_mm if span.units_per_mm else LABEL_UNITS) * scale
    font, margin = _font(round(size)), size / 3
    count = int(max(span.width, span.height) / step) + 1
    for k in range(count):
        text = str(k * unit)
        at = k * step * scale
        for fraction in (0.25, 0.5, 0.75):
            draw.text((at + margin, span.height * fraction * scale - margin), text, fill=LABEL,
                      font=font, anchor="ls")
        for _name, x, y, _w, h in frames:
            if y * scale <= at <= (y + h) * scale:
                draw.text((x * scale + margin, at - margin), text, fill=LABEL_DOWN,
                          font=font, anchor="ls")

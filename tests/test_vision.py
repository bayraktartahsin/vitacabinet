"""Reading labels off a photograph, with the live vision model."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from app.vision import read_labels


def _box(name, strength, sub, colour):
    im = Image.new("RGB", (640, 300), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 46)
    f2 = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    d.rectangle([8, 8, 632, 292], outline=colour, width=8)
    d.text((36, 50), name, fill=colour, font=f)
    d.text((36, 115), strength, fill="black", font=f)
    d.text((36, 205), sub, fill="black", font=f2)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_the_model_returns_the_printed_name_and_strength_and_nothing_else():
    """It reads; it does not identify. Identity still comes from RxNorm, so
    every fact can say where it came from."""
    lines = read_labels([(_box("Glucophage", "500 mg", "metformin hydrochloride", "navy"), "png")])
    assert len(lines) == 1
    assert "glucophage" in lines[0].lower() and "500" in lines[0]
    assert not any(w in lines[0].lower() for w in ("take", "stop", "should"))


def test_the_bundled_demo_drawer_reads_as_six_boxes():
    lines = read_labels([(open("web/sample-drawer.jpg", "rb").read(), "jpg")])
    assert len(lines) == 6
    assert any("glucophage" in ln.lower() for ln in lines)
    assert any("norvasc" in ln.lower() for ln in lines)

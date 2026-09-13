"""The deck's design canvas maps onto the slide the way fancy-slides maps it.

Ported from PHP ``tests/Unit/DesignCanvasTest.php`` (minus its ``Layout::fit``
case: this port has no layout helper). Before 0.3 the same ``fontSize`` was
scaled two ways: fancy-slides drew it as a share of a 1920px canvas (96 = 5.0%
of the slide width) and the PPTX writer halved it on a 720pt slide (6.7%), so
text an agent fitted in the preview overflowed in PowerPoint.
``theme.aspectRatio`` was accepted and ignored, so a 4:3 deck came out stretched
onto 16:9, and a rounded rectangle's corner was twice the radius asked for, or
PowerPoint's default when the element was a shape.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

import dark_slide


def _deck(theme: dict[str, Any], element: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "canvas",
        "title": "Design canvas",
        "theme": {"name": "canvas", **theme},
        "slides": [{"id": "s1", "elements": [{
            "id": "e", "type": "text", "x": 0.1, "y": 0.5, "w": 0.5, "h": 0.25, "content": "Canvas", **element,
        }]}],
    }


def _parts(deck: dict[str, Any]) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(deck))) as archive:
        return {
            "slide": archive.read("ppt/slides/slide1.xml").decode("utf-8"),
            "presentation": archive.read("ppt/presentation.xml").decode("utf-8"),
        }


def test_keeps_a_font_size_at_the_same_share_of_the_slide_as_fancy_slides_draws_it() -> None:
    # 96 of 1920 is 5% of the width; 5% of a 720pt slide is 36pt.
    assert 'sz="3600"' in _parts(_deck({}, {"style": {"fontSize": 96}}))["slide"]
    # Half the canvas, twice the share.
    assert 'sz="7200"' in _parts(_deck({"slideWidth": 960}, {"style": {"fontSize": 96}}))["slide"]


def test_reproduces_the_sizes_written_before_this_release_with_slide_width_1440() -> None:
    # 720 / 1440 is the old halving, so text and every length land where 0.2 put them.
    slide = _parts(_deck({"slideWidth": 1440}, {"style": {"fontSize": 96, "letterSpacing": 4, "padding": 24}}))["slide"]

    assert 'sz="4800"' in slide  # 48pt, as 0.2 halved it
    assert 'spc="200"' in slide  # 2pt
    assert 'lIns="152400"' in slide  # 12pt


def test_scales_a_shape_outline_with_the_canvas() -> None:
    shape = {"type": "shape", "shape": "rect", "strokeWidth": 8}

    assert '<a:ln w="38100">' in _parts(_deck({}, shape))["slide"]  # 3pt
    assert '<a:ln w="50800">' in _parts(_deck({"slideWidth": 1440}, shape))["slide"]  # 4pt


@pytest.mark.parametrize(
    ("radius", "adj"),
    [(None, 3704), (64, 29630), (4000, 50000)],
    ids=["fancy-slides default 8px = 3pt", "64px = 24pt", "larger than the box is a pill"],
)
def test_rounds_a_rounded_rect_shape_by_its_radius_in_design_pixels(radius: int | None, adj: int) -> None:
    # A 0.3 x 0.2 box on a 16:9 slide: 2743200 x 1028700 EMU, shorter side 1028700.
    # The corner radius is min(w, h) * adj / 100000, so adj = radiusEmu / 1028700 * 100000.
    shape: dict[str, Any] = {"type": "shape", "shape": "rounded-rect", "w": 0.3, "h": 0.2}
    if radius is not None:
        shape["radius"] = radius

    expected = (
        '<a:prstGeom prst="roundRect"><a:avLst>'
        f'<a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
    )
    assert expected in _parts(_deck({}, shape))["slide"]


def test_rounds_a_decorated_text_box_by_the_radius_asked_for() -> None:
    # Ported from PHP RichTextConstructsTest. A 0.88 x 0.18 box on a 16:9 slide
    # has a shorter side of 925830 EMU; 8 design px is 3pt = 38100 EMU;
    # 38100 / 925830 * 100000 = 4115. The old formula divided by HALF the
    # shorter side and drew every corner twice as round.
    element = {"x": 0.06, "y": 0.2, "w": 0.88, "h": 0.18, "style": {"fill": "#E8F2F3", "radius": 8}}
    assert '<a:gd name="adj" fmla="val 4115"/>' in _parts(_deck({}, element))["slide"]


@pytest.mark.parametrize(
    ("ratio", "sld_sz", "y_emu"),
    [
        (16 / 9, '<p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>', 2571750),
        (16 / 10, '<p:sldSz cx="9144000" cy="5715000" type="screen16x10"/>', 2857500),
        (4 / 3, '<p:sldSz cx="9144000" cy="6858000" type="screen4x3"/>', 3429000),
        (2.0, '<p:sldSz cx="9144000" cy="4572000"/>', 2286000),
    ],
    ids=["16:9 (default)", "16:10", "4:3", "custom 2:1"],
)
def test_shapes_the_slide_by_theme_aspect_ratio(ratio: float, sld_sz: str, y_emu: int) -> None:
    parts = _parts(_deck({"aspectRatio": ratio}, {}))

    assert sld_sz in parts["presentation"]
    # y 0.5 is the middle of THIS slide's height, not of a 16:9 one.
    assert f'<a:off x="914400" y="{y_emu}"/>' in parts["slide"]


def test_reads_a_non_16_9_deck_back_with_its_own_geometry_and_aspect_ratio() -> None:
    deck = dark_slide.read(dark_slide.to_bytes(_deck({"aspectRatio": 4 / 3}, {})))

    # The reader used to convert against a 16:9 height, reading y 0.5 of a 4:3
    # slide back as 0.667.
    assert deck["slides"][0]["elements"][0]["y"] == 0.5
    assert deck["slides"][0]["elements"][0]["h"] == 0.25
    assert deck["theme"]["aspectRatio"] == 4 / 3


def test_reads_a_16_9_deck_back_without_inventing_an_aspect_ratio() -> None:
    assert "aspectRatio" not in dark_slide.read(dark_slide.to_bytes(_deck({}, {})))["theme"]


def test_writes_a_deck_with_no_aspect_ratio_exactly_as_16_9() -> None:
    assert '<p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>' in _parts(_deck({}, {}))["presentation"]

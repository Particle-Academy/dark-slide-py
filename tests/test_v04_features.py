"""Transitions, image fit/crop, native charts, theme + layouts.

Ported from PHP ``tests/Unit/V04FeaturesTest.php``.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.etree import ElementTree

import dark_slide
from tests.fixtures import PNG_1x1


def base_deck() -> dict[str, Any]:
    return {
        "id": "v04",
        "title": "v0.4 deck",
        "theme": {"name": "default", "colors": {"accent": "#8B5CF6"}},
        "slides": [
            {
                "id": "s1",
                "layout": "title",
                "elements": [
                    {
                        "id": "e1",
                        "type": "text",
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.8,
                        "h": 0.2,
                        "content": "Hello",
                        "format": "plain",
                    }
                ],
            }
        ],
    }


def part(deck: Any, name: str) -> str:
    """The named part, or ``""`` when the archive does not contain it."""
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(deck))) as archive:
        try:
            return archive.read(name).decode("utf-8")
        except KeyError:
            return ""


# ── A) Transitions ────────────────────────────────────────────────────────


def test_a_fade_transition_is_emitted() -> None:
    deck = base_deck()
    deck["slides"][0]["transition"] = {"kind": "fade", "duration": 800}
    xml = part(deck, "ppt/slides/slide1.xml")
    assert '<p:transition spd="slow">' in xml
    assert "<p:fade/>" in xml


def test_slide_transitions_become_a_directional_push() -> None:
    for direction, code in (("left", "l"), ("right", "r"), ("up", "u"), ("down", "d")):
        deck = base_deck()
        deck["slides"][0]["transition"] = {
            "kind": "slide",
            "direction": direction,
            "duration": 200,
        }
        xml = part(deck, "ppt/slides/slide1.xml")
        assert f'<p:push dir="{code}"/>' in xml
        assert 'spd="fast"' in xml  # duration <= 250


def test_a_zoom_transition_becomes_an_iris_circle() -> None:
    deck = base_deck()
    deck["slides"][0]["transition"] = {"kind": "zoom", "duration": 400}
    xml = part(deck, "ppt/slides/slide1.xml")
    assert "<p:circle/>" in xml  # PowerPoint has no native zoom transition
    assert 'spd="med"' in xml  # 250 < 400 < 700


def test_kind_none_omits_the_transition_entirely() -> None:
    deck = base_deck()
    deck["slides"][0]["transition"] = {"kind": "none"}
    assert "<p:transition" not in part(deck, "ppt/slides/slide1.xml")


def test_a_slide_without_a_transition_falls_back_to_the_deck_default() -> None:
    deck = base_deck()
    deck["theme"]["defaultTransition"] = {"kind": "fade", "duration": 300}
    assert "<p:fade/>" in part(deck, "ppt/slides/slide1.xml")


def test_kind_none_falls_through_to_the_deck_default() -> None:
    deck = base_deck()
    deck["theme"]["defaultTransition"] = {"kind": "fade", "duration": 300}
    deck["slides"][0]["transition"] = {"kind": "none"}
    assert "<p:fade/>" in part(deck, "ppt/slides/slide1.xml")


# ── B) Image fit / crop ───────────────────────────────────────────────────


def test_fit_cover_emits_a_non_empty_srcrect() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "img",
            "type": "image",
            "x": 0.1,
            "y": 0.1,
            "w": 0.4,
            "h": 0.4,
            "src": PNG_1x1,
            "fit": "cover",
        }
    )
    xml = part(deck, "ppt/slides/slide1.xml")
    # A square image in a wider-than-tall box crops top and bottom.
    assert re.search(r'<a:srcRect l="0" t="[1-9]\d*" r="0" b="[1-9]\d*"/>', xml)


def test_fit_contain_letterboxes_by_shrinking_the_ext() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "img",
            "type": "image",
            "x": 0.0,
            "y": 0.0,
            "w": 0.4,
            "h": 0.4,
            "src": PNG_1x1,
            "fit": "contain",
        }
    )
    xml = part(deck, "ppt/slides/slide1.xml")
    # The box is 0.4*9144000 x 0.4*5143500 = 3657600 x 2057400; a square
    # image fits to the smaller axis.
    assert '<a:ext cx="2057400" cy="2057400"/>' in xml
    assert "<a:srcRect" not in xml  # contain never crops


def test_an_explicit_crop_wins_over_fit() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "img",
            "type": "image",
            "x": 0.1,
            "y": 0.1,
            "w": 0.4,
            "h": 0.4,
            "src": PNG_1x1,
            "fit": "cover",
            "crop": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.5},
        }
    )
    xml = part(deck, "ppt/slides/slide1.xml")
    # l = 0.1, t = 0.2, r = 1-0.1-0.5, b = 1-0.2-0.5, in thousandths of a percent.
    assert '<a:srcRect l="10000" t="20000" r="40000" b="30000"/>' in xml


def test_an_unfetchable_image_degrades_to_a_labelled_placeholder() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "img",
            "type": "image",
            "x": 0.1,
            "y": 0.1,
            "w": 0.4,
            "h": 0.4,
            "src": "https://example.com/nope.png",
        }
    )
    xml = part(deck, "ppt/slides/slide1.xml")
    assert "[image: https://example.com/nope.png]" in xml
    assert "<p:pic>" not in xml


# ── C) Charts ─────────────────────────────────────────────────────────────


def test_a_bar_chart_part_has_one_ser_per_series() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "bar",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "option": {
                "xAxis": {"data": ["Q1", "Q2", "Q3"]},
                "series": [
                    {"type": "bar", "name": "Rev", "data": [10, 20, 15]},
                    {"type": "bar", "name": "Cost", "data": [5, 8, 7]},
                ],
            },
        }
    )
    chart = part(deck, "ppt/charts/chart1.xml")
    assert chart != ""
    ElementTree.fromstring(chart)

    assert "<c:barChart>" in chart
    assert chart.count("<c:ser>") == 2
    assert "<c:strLit>" in chart  # category literal cache
    assert "<c:numLit>" in chart  # value literal cache

    slide = part(deck, "ppt/slides/slide1.xml")
    assert "<p:graphicFrame>" in slide
    assert 'r:id="rIdChart1"' in slide


def test_a_pie_chart_part_colours_every_slice() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "pie",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "option": {
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "A", "value": 30},
                            {"name": "B", "value": 50},
                            {"name": "C", "value": 20},
                        ],
                    }
                ]
            },
        }
    )
    chart = part(deck, "ppt/charts/chart1.xml")
    ElementTree.fromstring(chart)
    assert "<c:pieChart>" in chart
    assert chart.count("<c:dPt>") == 3
    assert "<c:v>A</c:v>" in chart  # categories derived from data[].name


def test_chart_parts_get_a_content_type_override() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "bar",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "option": {"xAxis": {"data": ["a"]}, "series": [{"type": "bar", "data": [1]}]},
        }
    )
    content_types = part(deck, "[Content_Types].xml")
    assert "/ppt/charts/chart1.xml" in content_types
    assert "application/vnd.openxmlformats-officedocument.drawingml.chart+xml" in content_types


def test_an_untranslatable_chart_degrades_to_a_titled_placeholder() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "bad",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "option": {
                "title": {"text": "Mystery"},
                "series": [{"type": "radar", "data": [1, 2, 3]}],
            },
        }
    )
    assert part(deck, "ppt/charts/chart1.xml") == ""
    slide = part(deck, "ppt/slides/slide1.xml")
    assert "<a:t>Mystery</a:t>" in slide
    assert 'prst="roundRect"' in slide


def test_a_pre_rendered_image_is_embedded_when_the_option_cannot_translate() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "preR",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "option": {"series": "nonsense"},
            "image": PNG_1x1,
        }
    )
    assert "<p:pic>" in part(deck, "ppt/slides/slide1.xml")


def test_png_mode_is_the_default_and_beats_a_translatable_option() -> None:
    """The PHP↔Node divergence, asserted from the PHP side.

    PHP defaults ``chart.mode`` to ``"png"`` and short-circuits to a picture
    whenever a pre-render exists; the Node port always tries native
    translation first. Same input, different parts. PHP is the reference.
    """
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "both",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "option": {"xAxis": {"data": ["a"]}, "series": [{"type": "bar", "data": [1]}]},
            "image": PNG_1x1,
        }
    )
    assert "<p:pic>" in part(deck, "ppt/slides/slide1.xml")
    assert part(deck, "ppt/charts/chart1.xml") == ""


def test_mode_native_forces_the_chart_part_even_with_a_pre_render() -> None:
    deck = base_deck()
    deck["slides"][0]["elements"].append(
        {
            "id": "both",
            "type": "chart",
            "x": 0.1,
            "y": 0.4,
            "w": 0.8,
            "h": 0.5,
            "mode": "native",
            "option": {"xAxis": {"data": ["a"]}, "series": [{"type": "bar", "data": [1]}]},
            "image": PNG_1x1,
        }
    )
    assert part(deck, "ppt/charts/chart1.xml") != ""
    assert "<p:pic>" not in part(deck, "ppt/slides/slide1.xml")


# ── D) Theme + layouts ────────────────────────────────────────────────────


def test_all_eight_layout_parts_ship_even_for_a_one_layout_deck() -> None:
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(base_deck()))) as archive:
        names = set(archive.namelist())
    for n in range(1, 9):
        assert f"ppt/slideLayouts/slideLayout{n}.xml" in names

    assert 'type="blank"' in part(base_deck(), "ppt/slideLayouts/slideLayout1.xml")
    assert 'type="title"' in part(base_deck(), "ppt/slideLayouts/slideLayout2.xml")


def test_each_slide_points_at_the_layout_matching_its_name() -> None:
    deck = base_deck()
    deck["slides"].append(
        {
            "id": "s2",
            "layout": "section-divider",
            "elements": [
                {
                    "id": "x",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.8,
                    "h": 0.2,
                    "content": "Section",
                    "format": "plain",
                }
            ],
        }
    )
    # An unrecognised layout falls back to blank (layout 1).
    deck["slides"].append(
        {
            "id": "s3",
            "layout": "made-up",
            "elements": [
                {
                    "id": "y",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.8,
                    "h": 0.2,
                    "content": "Fallback",
                    "format": "plain",
                }
            ],
        }
    )

    assert "slideLayout2.xml" in part(deck, "ppt/slides/_rels/slide1.xml.rels")
    assert "slideLayout5.xml" in part(deck, "ppt/slides/_rels/slide2.xml.rels")
    assert "slideLayout1.xml" in part(deck, "ppt/slides/_rels/slide3.xml.rels")


def test_theme_colours_map_into_the_clrscheme() -> None:
    deck = base_deck()
    deck["theme"]["colors"] = {
        "background": "#101820",
        "text": "#F0F0F0",
        "accent": "#FF6600",
        "muted": "#445566",
        "surface": "#223344",
    }
    theme = part(deck, "ppt/theme/theme1.xml")
    assert '<a:lt1><a:srgbClr val="101820"/></a:lt1>' in theme
    assert '<a:dk1><a:srgbClr val="F0F0F0"/></a:dk1>' in theme
    assert '<a:accent1><a:srgbClr val="FF6600"/></a:accent1>' in theme
    assert '<a:dk2><a:srgbClr val="445566"/></a:dk2>' in theme
    assert '<a:lt2><a:srgbClr val="223344"/></a:lt2>' in theme

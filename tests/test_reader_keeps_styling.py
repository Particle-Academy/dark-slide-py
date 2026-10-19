"""A deck read back keeps the styling it was written with.

Mirrors PHP ``tests/Unit/ReaderKeepsStylingTest.php`` case for case. The reader
used to return geometry and text only, so an agent editing a branded deck (read,
change one slide, write) shipped the whole deck in 28px default text, default
colours and a purple tint on every panel.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from dark_slide import read, to_bytes


def _deck() -> dict[str, Any]:
    return {
        "id": "rks",
        "title": "Styled",
        "theme": {
            "name": "brand",
            "colors": {"background": "#101828", "text": "#F9FAFB", "accent": "#F97316", "muted": "#94A3B8", "surface": "#1E293B"},
            "fonts": {"heading": "Playfair Display", "body": "Inter"},
        },
        "slides": [{"id": "s1", "elements": [
            {"id": "title", "type": "text", "x": 0.06, "y": 0.08, "w": 0.88, "h": 0.2, "content": "EMEA led Q3",
             "style": {"fontSize": 88, "weight": 700, "fontFamily": "Playfair Display", "color": "#F97316", "align": "center"}},
            {"id": "body", "type": "text", "x": 0.06, "y": 0.35, "w": 0.5, "h": 0.3, "content": "Revenue grew 31%",
             "style": {"fontSize": 40, "italic": True, "verticalAlign": "middle", "align": "right"}},
            {"id": "plain", "type": "text", "x": 0.06, "y": 0.7, "w": 0.5, "h": 0.1, "content": "Unstyled"},
            {"id": "panel", "type": "shape", "shape": "rounded-rect", "x": 0.6, "y": 0.35, "w": 0.34, "h": 0.3,
             "fill": "#1E293B", "stroke": "transparent"},
            {"id": "tint", "type": "shape", "shape": "rect", "x": 0.6, "y": 0.7, "w": 0.34, "h": 0.1},
            {"id": "rule", "type": "shape", "shape": "rect", "x": 0.06, "y": 0.3, "w": 0.1, "h": 0.006,
             "fill": "#F97316", "stroke": "#F97316", "strokeWidth": 4, "dashed": True},
        ]}],
    }


def _parts(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {name: z.read(name).decode("utf-8") for name in ("ppt/slides/slide1.xml", "ppt/theme/theme1.xml")}


def _read(deck: dict[str, Any]) -> dict[str, Any]:
    return read(to_bytes(deck))


def _by_id(deck: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in deck["slides"][0]["elements"]}


def test_reads_the_theme_back_colours_and_fonts() -> None:
    assert json.dumps(_read(_deck())["theme"]) == json.dumps({
        "name": "imported",
        "colors": {"background": "#101828", "text": "#F9FAFB", "accent": "#F97316", "muted": "#94A3B8", "surface": "#1E293B"},
        "fonts": {"heading": "Playfair Display", "body": "Inter"},
    })


def test_reads_a_text_element_style_back_in_design_pixels() -> None:
    els = _by_id(_read(_deck()))
    # json.dumps pins key ORDER and int-vs-float (88, not 88.0), as PHP's toBe does.
    assert json.dumps(els["title"]["style"]) == json.dumps(
        {"fontSize": 88, "weight": 700, "color": "#F97316", "fontFamily": "Playfair Display", "align": "center"})
    assert json.dumps(els["body"]["style"]) == json.dumps(
        {"fontSize": 40, "italic": True, "color": "#F9FAFB", "align": "right", "verticalAlign": "middle"})
    assert json.dumps(els["plain"]["style"]) == json.dumps({"fontSize": 28, "color": "#F9FAFB"})


def test_reads_shape_fill_and_outline_back_including_none() -> None:
    els = _by_id(_read(_deck()))
    assert {k: els["panel"][k] for k in ("fill", "stroke")} == {"fill": "#1E293B", "stroke": "transparent"}
    assert {k: els["tint"][k] for k in ("fill", "stroke", "strokeWidth")} == {
        "fill": "rgba(139,92,246,0.15)", "stroke": "#F97316", "strokeWidth": 2}
    assert {k: els["rule"][k] for k in ("fill", "stroke", "strokeWidth", "dashed")} == {
        "fill": "#F97316", "stroke": "#F97316", "strokeWidth": 4, "dashed": True}
    assert isinstance(els["tint"]["strokeWidth"], int)


def test_keeps_a_bold_paragraph_bold_inside_an_otherwise_plain_box() -> None:
    deck = _deck()
    deck["slides"][0]["elements"] = [{"id": "mix", "type": "text", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.4,
                                      "content": "**Lead line**\nPlain detail", "format": "markdown"}]
    el = _read(deck)["slides"][0]["elements"][0]
    assert el["content"] == "**Lead line**\nPlain detail"
    assert el["format"] == "markdown"
    assert "weight" not in el["style"]


def test_reports_a_named_mono_face_and_not_the_default_one() -> None:
    deck = _deck()
    deck["theme"]["fonts"]["mono"] = "Fira Code"
    assert _read(deck)["theme"]["fonts"]["mono"] == "Fira Code"


def test_writes_what_it_read_to_the_same_slide_and_theme_parts() -> None:
    original = _parts(to_bytes(_deck()))
    again = _parts(to_bytes(_read(_deck())))
    assert again["ppt/theme/theme1.xml"] == original["ppt/theme/theme1.xml"]
    assert again["ppt/slides/slide1.xml"] == original["ppt/slides/slide1.xml"]


def test_reads_a_native_chart_back_as_the_echarts_option_that_writes_it() -> None:
    option = {
        "color": ["#38BDF8", "#F59E0B"],
        "legend": {},
        "xAxis": {"type": "category", "data": ["Leeds", "Bristol", "Norwich"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "On-time %", "label": {"show": True},
             "data": [96.1, 95.4, {"value": 90.7, "itemStyle": {"color": "#DC2626"}}]},
            {"type": "bar", "name": "Target", "data": [95, 95, 95]},
        ],
    }
    deck = _deck()
    deck["slides"][0]["elements"] = [{"id": "depot-chart", "type": "chart", "x": 0.06, "y": 0.2, "w": 0.6, "h": 0.6, "option": option}]
    el = _read(deck)["slides"][0]["elements"][0]
    assert el["id"] == "depot-chart" and el["type"] == "chart"
    assert el["option"]["xAxis"]["data"] == ["Leeds", "Bristol", "Norwich"]
    assert el["option"]["series"][0]["name"] == "On-time %"
    assert el["option"]["series"][0]["label"] == {"show": True}
    assert el["option"]["series"][0]["data"][2] == {"value": 90.7, "itemStyle": {"color": "#DC2626"}}
    assert "legend" in el["option"]

    def chart_part(data: bytes) -> str:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.read("ppt/charts/chart1.xml").decode("utf-8")

    assert chart_part(to_bytes(_read(deck))) == chart_part(to_bytes(deck))


def test_reads_a_table_back_with_its_styling_as_the_cell_model_that_writes_it() -> None:
    deck = _deck()
    deck["slides"][0]["elements"] = [{
        "id": "kpi", "type": "table", "x": 0.06, "y": 0.2, "w": 0.88, "h": 0.5,
        "columns": [{"key": "k", "label": "KPI", "width": 0.5}, {"key": "s", "label": "Status", "width": 0.5}],
        "rows": [
            {"k": "On-time delivery", "s": {"text": "Below target", "fill": "#DC2626", "color": "#FFFFFF", "bold": True}},
            {"k": "Damage rate", "s": {"text": "On target", "fill": "#16A34A", "color": "#FFFFFF", "bold": True}},
        ],
        "style": {"header": {"fill": "#38BDF8", "color": "#0B1220"}, "fontSize": 36},
    }]
    table = _read(deck)["slides"][0]["elements"][0]
    assert {k: table["style"]["header"][k] for k in ("fill", "color", "bold")} == {"fill": "#38BDF8", "color": "#0B1220", "bold": True}
    assert table["style"]["fontSize"] == 36
    assert table["rows"][0]["col1"] == "On-time delivery"
    assert {k: table["rows"][0]["col2"][k] for k in ("text", "fill", "color", "bold")} == {
        "text": "Below target", "fill": "#DC2626", "color": "#FFFFFF", "bold": True}
    assert _parts(to_bytes(_read(deck)))["ppt/slides/slide1.xml"] == _parts(to_bytes(deck))["ppt/slides/slide1.xml"]

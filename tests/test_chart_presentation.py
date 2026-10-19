"""A native chart looks like the chart fancy-slides draws from the same option:
a legend only when ``option.legend`` asks, values when a series asks with
``label.show``, no minor ticks. And a shape's outline takes the theme accent.
The same cases run in all three engines.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from dark_slide import to_bytes


def _part(deck: dict[str, Any], name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(to_bytes(deck))) as z:
        return z.read(name).decode("utf-8")


def _chart(option: dict[str, Any]) -> str:
    return _part(
        {
            "id": "cp",
            "title": "Chart presentation",
            "theme": {"name": "cp"},
            "slides": [{"id": "s1", "elements": [{"id": "c", "type": "chart", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.6, "option": option}]}],
        },
        "ppt/charts/chart1.xml",
    )


def _bars() -> dict[str, Any]:
    return {"xAxis": {"data": ["North", "South", "EMEA"]}, "series": [{"type": "bar", "name": "Revenue", "data": [1.25, 0.98, 2.1]}]}


def test_no_legend_unless_the_option_asks() -> None:
    assert "<c:legend>" not in _chart(_bars())
    assert "<c:legend>" in _chart({**_bars(), "legend": {}})
    assert "<c:legend>" not in _chart({**_bars(), "legend": {"show": False}})


def test_values_when_a_series_asks_with_label_show() -> None:
    labelled = _bars()
    labelled["series"][0]["label"] = {"show": True}
    assert "<c:dLbls>" not in _chart(_bars())
    assert '<c:showVal val="1"/>' in _chart(labelled)


def test_a_pie_and_a_line_are_labelled_too() -> None:
    pie = {"series": [{"type": "pie", "label": {"show": True}, "data": [{"name": "A", "value": 1}, {"name": "B", "value": 2}]}]}
    line = {"xAxis": {"data": ["Q1", "Q2"]}, "series": [{"type": "line", "label": {"show": True}, "data": [1, 2]}]}
    assert '<c:showVal val="1"/>' in _chart(pie)
    assert '<c:showVal val="1"/>' in _chart(line)


def test_no_minor_tick_marks() -> None:
    assert _chart(_bars()).count('<c:minorTickMark val="none"/>') == 2


def test_a_shape_is_outlined_in_the_theme_accent_unless_it_names_a_stroke() -> None:
    def deck(shape: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "cp",
            "title": "Shape",
            "theme": {"name": "cp", "colors": {"accent": "#F97316"}},
            "slides": [{"id": "s1", "elements": [{"id": "r", "type": "shape", "shape": "rect", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.01, "fill": "#F97316", **shape}]}],
        }

    slide = _part(deck({}), "ppt/slides/slide1.xml")
    assert '<a:ln w="9525"><a:solidFill><a:srgbClr val="F97316"' in slide
    assert "8B5CF6" not in slide
    assert '<a:srgbClr val="000000"' in _part(deck({"stroke": "#000000"}), "ppt/slides/slide1.xml")

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


# Chart colours, as ECharts states them. Mirrors PHP tests/Unit/ChartColorsTest.php.
def _cc_bars() -> dict[str, Any]:
    return {
        "xAxis": {"type": "category", "data": ["Leeds", "Bristol", "Glasgow", "Norwich"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "itemStyle": {"color": "#94A3B8"},
                    "data": [96.1, 95.4, 93.8, {"value": 90.7, "itemStyle": {"color": "#DC2626"}}]}],
    }


def test_colours_a_series_and_a_single_bar_from_item_style() -> None:
    xml = _chart(_cc_bars())
    assert '<c:spPr><a:solidFill><a:srgbClr val="94A3B8"/></a:solidFill></c:spPr>' in xml
    assert ('<c:dPt><c:idx val="3"/><c:invertIfNegative val="0"/><c:bubble3D val="0"/><c:spPr><a:solidFill>'
            '<a:srgbClr val="DC2626"/></a:solidFill></c:spPr></c:dPt>') in xml
    assert xml.index('val="94A3B8"') < xml.index("<c:dPt>") < xml.index("<c:cat>")


def test_takes_the_palette_from_option_color() -> None:
    xml = _chart({"color": ["#0F766E", "#F59E0B"], "xAxis": {"type": "category", "data": ["A", "B"]},
                  "series": [{"type": "bar", "data": [1, 2]}, {"type": "bar", "data": [3, 4]}]})
    assert '<a:srgbClr val="0F766E"/>' in xml
    assert '<a:srgbClr val="F59E0B"/>' in xml
    assert 'val="EC4899"' not in xml


def test_colours_pie_slices_from_the_palette_and_from_a_slice_of_their_own() -> None:
    xml = _chart({"color": ["#0F766E", "#CBD5E1"], "series": [{"type": "pie", "data": [
        {"name": "Cited reconciliation", "value": 41, "itemStyle": {"color": "#C2410C"}},
        {"name": "Other reasons", "value": 59},
    ]}]})
    assert '<c:dPt><c:idx val="0"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="C2410C"/></a:solidFill></c:spPr></c:dPt>' in xml
    assert '<c:dPt><c:idx val="1"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="CBD5E1"/></a:solidFill></c:spPr></c:dPt>' in xml
    assert "EC4899" not in xml


def test_colours_a_line_marker_for_a_single_point() -> None:
    xml = _chart({"xAxis": {"type": "category", "data": ["Q1", "Q2", "Q3"]},
                  "series": [{"type": "line", "data": [1, 2, {"value": 3, "itemStyle": {"color": "#DC2626"}}]}]})
    assert ('<c:dPt><c:idx val="2"/><c:marker><c:symbol val="circle"/><c:size val="7"/><c:spPr><a:solidFill>'
            '<a:srgbClr val="DC2626"/></a:solidFill><a:ln><a:solidFill><a:srgbClr val="DC2626"/></a:solidFill>'
            '</a:ln></c:spPr></c:marker><c:bubble3D val="0"/></c:dPt>') in xml


def test_writes_what_it_always_did_when_the_option_names_no_colour() -> None:
    plain = _cc_bars()
    del plain["series"][0]["itemStyle"]
    plain["series"][0]["data"][3] = 90.7
    assert "<c:dPt>" not in _chart(plain)

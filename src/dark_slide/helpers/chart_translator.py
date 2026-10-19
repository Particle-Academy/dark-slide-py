"""ECharts ``option`` → normalised chart spec. Mirrors PHP ``Helpers\\ChartTranslator``.

Deliberately forgiving about the shapes ECharts accepts: categories may live
on ``xAxis.data``, ``xAxis[0].data`` or ``categories``; data points may be
bare numbers, ``{value}`` objects, or ``{name, value}`` pie slices. Anything
it cannot understand returns ``None``, which the writer reads as "fall back to
a pre-rendered image or a titled placeholder" rather than an error.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from ..util import is_numeric, is_plain_object, is_scalar, php_float, php_string

__all__ = ["SUPPORTED_TYPES", "ChartSeries", "ChartSpec", "translate"]

#: Series types with a native OOXML equivalent. Anything else fails the whole
#: translation — one unsupported series means the chart degrades as a unit.
#:
#: WIDENING IS SAFE, NARROWING IS BREAKING, and not only for our own output: the
#: list is published in the deck schema as `option.series.items.type`'s enum, and a
#: consumer generating their writer vocabulary from that schema guards it — their
#: craft guidance tells authoring agents to stay inside these four, because a type
#: outside them makes the WHOLE option untranslatable and leaves a same-sized
#: placeholder box with a file still written and nothing raised. Drop one and their
#: test goes red before a writer finds out, which is the arrangement working; add
#: one and nothing breaks anywhere.
SUPPORTED_TYPES = ["bar", "line", "pie", "scatter"]


class ChartSeries(TypedDict):
    type: str
    name: str
    values: list[float]
    smooth: bool
    area: bool
    points: list[dict[str, float]]
    #: ECharts' ``label.show``: the series' values drawn on the chart.
    labels: bool
    #: ECharts' series ``itemStyle.color``, upper-case hex without '#'.
    color: str | None
    #: Points with an ``itemStyle.color`` of their own.
    pointColors: list[dict[str, Any]]


class ChartSpec(TypedDict):
    kind: str
    title: str
    categories: list[str]
    series: list[ChartSeries]
    legend: bool


def translate(option: Any) -> ChartSpec | None:
    """Normalise an ECharts option, or ``None`` when nothing is renderable.

    Takes ``Any`` rather than a dict on purpose. A deck written by the PHP engine
    serialises an EMPTY option as ``[]`` -- PHP cannot tell an empty list from an
    empty map -- and this raised ``AttributeError`` on it while PHP and Node both
    returned None. One malformed element must degrade to a placeholder, never take
    down the deck around it.
    """
    if not is_plain_object(option):
        return None

    raw_series = _extract_series(option)
    if not raw_series:
        return None

    categories = _extract_categories(option)
    series: list[ChartSeries] = []
    kind: str | None = None

    for raw in raw_series:
        if not is_plain_object(raw):
            continue
        raw_type = raw.get("type")
        series_type = raw_type.lower() if isinstance(raw_type, str) else "bar"
        if series_type not in SUPPORTED_TYPES:
            return None

        normalised = _normalise_series(raw, series_type)
        if normalised is None:
            return None

        if kind is None:
            kind = series_type
        series.append(normalised)

        if series_type == "pie" and not categories:
            categories = _pie_categories(raw)

    if not series or kind is None:
        return None

    return {
        "kind": kind,
        "title": _extract_title(option),
        "categories": categories,
        "series": series,
        "legend": _wants_legend(option),
        "palette": _palette(option),
    }


_HEX = re.compile(r"^#([0-9A-Fa-f]{6})$")


def _hex_color(color: Any) -> str | None:
    # #RRGGBB as upper-case hex without the '#', or None. Mirrors PHP hexColor.
    match = _HEX.match(color) if isinstance(color, str) else None
    return match.group(1).upper() if match else None


def _item_color(holder: Any) -> str | None:
    # itemStyle.color of a series or a data item. Mirrors PHP itemColor.
    if not isinstance(holder, dict):
        return None
    style = holder.get("itemStyle")
    return _hex_color(style.get("color")) if isinstance(style, dict) else None


def _palette(option: dict[str, Any]) -> list[str]:
    # option.color, ECharts' palette. Mirrors PHP ChartTranslator::palette.
    colors = option.get("color")
    items = colors.values() if isinstance(colors, dict) else colors if isinstance(colors, list) else []
    return [h for h in (_hex_color(c) for c in items) if h is not None]


def _wants_legend(option: dict[str, Any]) -> bool:
    """A legend only when ``option.legend`` is set and not switched off, as ECharts draws it.

    A dict OR a list, as PHP's ``is_array`` reads it; ``show: null`` counts as
    shown, as PHP's ``?? true`` reads it.
    """
    legend = option.get("legend")
    if isinstance(legend, list):
        return True
    return isinstance(legend, dict) and legend.get("show") is not False


def _extract_series(option: dict[str, Any]) -> list[Any]:
    series = option.get("series")
    if isinstance(series, list):
        return series
    if is_plain_object(series) and series:
        return [series]
    return []


def _extract_categories(option: dict[str, Any]) -> list[str]:
    """Category labels, from ``xAxis.data``, ``xAxis[0].data`` or ``categories``.

    The seed is ``None`` and NOT ``[]``, which is the whole of the fix the owner
    ruled on 2026-10-07: ``[]`` is already a list, so the ``categories`` fallback
    could only fire when an ``xAxis`` was present WITHOUT ``data``, and a deck
    using ``categories`` alone silently got ``1, 2, 3 ...`` labels. Node seeded
    ``None`` and honoured it, so the trio was split three ways on a path byte
    parity never reaches -- the reference deck carries no chart.
    """
    candidates: Any = None
    x_axis = option.get("xAxis")
    if isinstance(x_axis, (list, dict)):
        if isinstance(x_axis, list) and x_axis and isinstance(x_axis[0], (list, dict)):
            candidates = x_axis[0].get("data") if isinstance(x_axis[0], dict) else None
        else:
            candidates = x_axis.get("data") if isinstance(x_axis, dict) else None

    if not isinstance(candidates, (list, dict)):
        candidates = option.get("categories")
    if not isinstance(candidates, (list, dict)):
        return []

    values = candidates.values() if isinstance(candidates, dict) else candidates
    return [php_string(value) for value in values if is_scalar(value)]


def _extract_title(option: dict[str, Any]) -> str:
    title = option.get("title")
    if isinstance(title, (dict, list)):
        text: Any = None
        if is_plain_object(title):
            text = title.get("text")
        elif title and is_plain_object(title[0]):
            text = title[0].get("text")
        if isinstance(text, str):
            return text
    if isinstance(title, str):
        return title
    return ""


def _normalise_series(raw: dict[str, Any], series_type: str) -> ChartSeries | None:
    name_value = raw.get("name")
    name = php_string(name_value) if is_scalar(name_value) else ""
    data = raw.get("data")
    if not isinstance(data, (list, dict)):
        return None

    points_source = data.values() if isinstance(data, dict) else data

    values: list[float] = []
    points: list[dict[str, float]] = []
    point_colors: list[dict[str, Any]] = []
    if series_type != "scatter":
        for i, point in enumerate(list(points_source)):
            point_color = _item_color(point)
            if point_color is not None:
                point_colors.append({"index": i, "color": point_color})
    for point in points_source:
        if series_type == "scatter":
            xy = _scatter_point(point)
            if xy is not None:
                points.append(xy)
            continue
        values.append(_numeric_value(point))

    if series_type == "scatter" and not points:
        return None
    if series_type != "scatter" and not values:
        return None

    return {
        "type": series_type,
        "name": name,
        "values": values,
        "smooth": _truthy(raw.get("smooth")),
        "area": series_type == "line" and raw.get("areaStyle") is not None,
        "points": points,
        "labels": isinstance(raw.get("label"), dict) and raw["label"].get("show") is True,
        # ECharts' itemStyle.color: the series' own colour, and a point's.
        "color": _item_color(raw),
        "pointColors": point_colors,
    }


def _truthy(value: Any) -> bool:
    from ..util import php_truthy

    return php_truthy(value)


def _numeric_value(point: Any) -> float:
    """A bare number, a ``{value}`` object, or 0.0 — never an error."""
    if is_numeric(point):
        return php_float(point)
    if is_plain_object(point) and is_numeric(point.get("value")):
        return php_float(point["value"])
    return 0.0


def _scatter_point(point: Any) -> dict[str, float] | None:
    """``[x, y]`` or ``{value: [x, y]}``."""
    pair = point
    if is_plain_object(point) and isinstance(point.get("value"), list):
        pair = point["value"]
    if isinstance(pair, list) and len(pair) >= 2 and is_numeric(pair[0]) and is_numeric(pair[1]):
        return {"x": php_float(pair[0]), "y": php_float(pair[1])}
    return None


def _pie_categories(raw: dict[str, Any]) -> list[str]:
    """Pie slice labels from ``data[].name``, falling back to ``Slice N``."""
    data = raw.get("data")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for i, point in enumerate(data):
        if is_plain_object(point) and is_scalar(point.get("name")):
            out.append(php_string(point["name"]))
        else:
            out.append("Slice " + str(i + 1))
    return out

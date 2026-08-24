"""Composite elements — ``kpiBand`` and ``metadataGrid`` — as AUTHORING SUGAR.

Mirrors PHP ``Table\\Composites`` and the Node ``table/composites.ts``.

Each expands into an ordinary ``table`` element before the writer ever sees it.
That is deliberate, and it has three consequences worth stating because a
genuinely new primitive looks tempting:

1. **No new OOXML surface.** A KPI band is a two-row table with the rule between
   the rows switched off; a metadata grid is a label-over-value table with every
   rule switched off. Both were expressible the moment per-cell borders existed —
   the composite spares an agent the arithmetic.
2. **``@particle-academy/fancy-slides`` keeps a schema it can render.** A new
   element type would be a hole in the JS editor the day it shipped.
3. **A composite READ BACK comes back as its expansion**, a ``table``. Lossy in
   one direction, documented rather than hidden — the alternative is a reader
   inventing intent it cannot recover.
"""

from __future__ import annotations

from typing import Any

from ..util import is_numeric, is_plain_object, php_float, php_string

__all__ = ["TYPES", "is_composite", "expand"]

TYPES = ("kpiBand", "metadataGrid")


def is_composite(element_type: Any) -> bool:
    return isinstance(element_type, str) and element_type in TYPES


def expand(element: dict[str, Any], theme: dict[str, Any] | None = None) -> dict[str, Any]:
    theme = theme if is_plain_object(theme) else {}
    kind = element.get("type")
    if kind == "kpiBand":
        return _kpi_band(element, theme)
    if kind == "metadataGrid":
        return _metadata_grid(element, theme)
    return element


def _kpi_band(element: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any]:
    """Four big figures with a small caption under each, in one banded box.

    The figure and its caption are two table rows that must read as one cell, so
    the rule between them is turned off from BOTH sides — a border is resolved
    per cell, and leaving either half on draws the line.
    """
    items = _items(element)
    style = element.get("style")
    style = style if is_plain_object(style) else {}

    accent = _theme_color(theme, "accent", "#8B5CF6")
    fill = style.get("fill")
    value_color = style.get("valueColor", style.get("color", accent))
    caption_color = style.get("captionColor", _theme_color(theme, "muted", "#64748B"))
    # Conservative on purpose: the writer has no font metrics, so it cannot know
    # a figure will fit. Four items across a full-width band at 60 wrapped
    # "$51K-$68K" onto two lines. A deck that knows its own content raises it.
    value_size = style.get("valueFontSize", 40)
    caption_size = style.get("captionFontSize", 20)
    align = style.get("align", "center")

    columns: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    captions: dict[str, Any] = {}
    for i, item in enumerate(items):
        key = f"k{i}"
        columns.append({"key": key, "label": ""})
        values[key] = php_string(item.get("value", ""))
        captions[key] = php_string(item.get("caption", ""))

    # Only the rule BETWEEN kpis, plus the band's own outline.
    borders = style.get(
        "borders",
        {
            "inner": {"width": 0.75, "color": _theme_color(theme, "muted", "#D9DEE4")},
            "outer": {"width": 0.75, "color": _theme_color(theme, "muted", "#D9DEE4")},
        },
    )

    return {
        "id": element.get("id", "kpi-band"),
        "type": "table",
        "x": element.get("x", 0.06),
        "y": element.get("y", 0.5),
        "w": element.get("w", 0.88),
        "h": element.get("h", 0.2),
        "z": element.get("z"),
        "hidden": element.get("hidden"),
        "animation": element.get("animation"),
        "columns": columns,
        "rows": [
            {
                "cells": values,
                "height": style.get("valueHeight", 44),
                "fontSize": value_size,
                "color": value_color,
                "bold": True,
                "align": align,
                "anchor": "bottom",
                "borders": _without_side(borders, "bottom"),
            },
            {
                "cells": captions,
                "height": style.get("captionHeight", 30),
                "fontSize": caption_size,
                "color": caption_color,
                "align": align,
                "anchor": "top",
                "borders": _without_side(borders, "top"),
            },
        ],
        "style": {
            "header": False,
            "stripe": False,
            "fill": fill,
            "padding": style.get("padding", {"left": 8, "right": 8, "top": 2, "bottom": 2}),
        },
    }


def _metadata_grid(element: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any]:
    """A label/value metadata panel, ``columns`` across.

    Labels are letterspaced small caps — the eyebrow treatment the construct
    exists for. A short final row is PADDED to full width: a ragged row is a
    shorter ``<a:tr>`` than the grid declares, which is a corrupt file rather
    than a cosmetic problem.
    """
    items = _items(element)
    style = element.get("style")
    style = style if is_plain_object(style) else {}

    across = max(1, int(php_float(element["columns"]))) if is_numeric(element.get("columns")) else 3

    label_color = style.get("labelColor", _theme_color(theme, "muted", "#64748B"))
    value_color = style.get("valueColor", _theme_color(theme, "text", "#0F172A"))
    fill = style.get("fill")

    columns = [{"key": f"c{i}", "label": ""} for i in range(across)]

    rows: list[dict[str, Any]] = []
    for start in range(0, len(items), across):
        chunk = items[start : start + across]
        labels: dict[str, Any] = {}
        values: dict[str, Any] = {}
        for i in range(across):
            item = chunk[i] if i < len(chunk) and is_plain_object(chunk[i]) else {}
            labels[f"c{i}"] = php_string(item.get("label", ""))
            values[f"c{i}"] = php_string(item.get("value", ""))
        rows.append(
            {
                "cells": labels,
                "height": style.get("labelHeight", 18),
                "fontSize": style.get("labelFontSize", 18),
                "color": label_color,
                "letterSpacing": style.get("labelLetterSpacing", 1.2),
                "caps": "small",
                "bold": True,
                "anchor": "bottom",
            }
        )
        rows.append(
            {
                "cells": values,
                "height": style.get("valueHeight", 26),
                "fontSize": style.get("valueFontSize", 28),
                "color": value_color,
                "bold": True,
                "anchor": "top",
            }
        )

    return {
        "id": element.get("id", "metadata-grid"),
        "type": "table",
        "x": element.get("x", 0.06),
        "y": element.get("y", 0.5),
        "w": element.get("w", 0.88),
        "h": element.get("h", 0.22),
        "z": element.get("z"),
        "hidden": element.get("hidden"),
        "animation": element.get("animation"),
        "columns": columns,
        "rows": rows,
        "style": {
            "header": False,
            "stripe": False,
            "borders": style.get("borders", False),
            "fill": fill,
            "padding": style.get("padding", {"left": 10, "right": 10, "top": 2, "bottom": 2}),
        },
    }


def _without_side(borders: Any, side: str) -> Any:
    """Drop one side from a border spec, so two stacked rows read as one cell."""
    if not is_plain_object(borders):
        return borders
    return {**borders, side: False}


def _items(element: dict[str, Any]) -> list[dict[str, Any]]:
    items = element.get("items")
    if not isinstance(items, list):
        return []
    return [i for i in items if is_plain_object(i)]


def _theme_color(theme: dict[str, Any], key: str, fallback: str) -> str:
    colors = theme.get("colors")
    colors = colors if is_plain_object(colors) else {}
    value = colors.get(key)
    return value if isinstance(value, str) and value != "" else fallback

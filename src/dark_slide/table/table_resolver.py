"""Resolve a loose agent-authored ``table`` element into fully-decided cells.

Mirrors PHP ``Table\\TableResolver`` and the Node ``table/table-resolver.ts``,
including their resolution ORDER — the three engines are held to byte-identical
OOXML, so a difference here is a difference in the file.

The resolved shape is expressed in POINTS and 6-digit hex, never EMU, so it is
document-format-neutral: ``last-word`` (docx) needs the same decisions and
renders them as ``w:tcBorders`` / ``w:tcMar`` / ``w:vAlign`` / ``w:gridSpan``.
The shared contract between the two packages is THIS MODEL, not the XML, and it
is pinned as a cross-language table in ``fancy-conformance``
(``shared/table-cell-control``).

Precedence, which is the whole design::

    cell > row > column > band (header|stripe|body) > table > theme > default

A key that is ABSENT falls through. A key present with the value ``False``
stops the chain and means "off" — which is why this module tests key PRESENCE
rather than truthiness in the places it does.
"""

from __future__ import annotations

from typing import Any

from ..helpers import color as Color
from ..helpers.emu import php_round
from ..util import is_numeric, is_plain_object, php_float, php_json_encode, php_string

__all__ = ["resolve", "normalize_columns", "column_widths_emu"]

DEFAULT_FONT_SIZE = 28
DEFAULT_BODY_COLOR = "#0F172A"
DEFAULT_HEADER_COLOR = "#FFFFFF"
DEFAULT_ACCENT = "#8B5CF6"
DEFAULT_STRIPE_FILL = "#F8FAFC"
DEFAULT_BORDER_COLOR = "#D9DEE4"
DEFAULT_BORDER_WIDTH = 0.75
DEFAULT_PADDING_X = 7.2
DEFAULT_PADDING_Y = 3.6
DEFAULT_HEADER_HEIGHT = 40
DEFAULT_BODY_HEIGHT = 30

_STYLE_KEYS = (
    "fill", "color", "bold", "italic", "underline", "align", "anchor",
    "fontSize", "letterSpacing", "caps", "fontFamily", "padding", "borders",
)

_CELL_SPEC_KEYS = (
    "text", "colSpan", "rowSpan", "fill", "color", "bold", "italic", "underline",
    "align", "anchor", "fontSize", "letterSpacing", "caps", "fontFamily", "padding", "borders",
)


def resolve(element: dict[str, Any], theme: dict[str, Any] | None = None) -> dict[str, Any]:
    theme = theme if is_plain_object(theme) else {}

    raw_columns = element.get("columns")
    columns = normalize_columns(raw_columns if isinstance(raw_columns, list) else [])
    raw_rows = element.get("rows")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    style = element.get("style")
    style = style if is_plain_object(style) else {}

    accent = _theme_color(theme, "accent", DEFAULT_ACCENT)

    header_spec = style.get("header", [])
    has_header = header_spec is not False
    header_style = header_spec if is_plain_object(header_spec) else {}

    body_spec = style.get("body")
    body_style = body_spec if is_plain_object(body_spec) else {}

    stripe_spec = style.get("stripe", [])
    stripe_on = stripe_spec is not False
    stripe_style = stripe_spec if is_plain_object(stripe_spec) else {}

    table_defaults: dict[str, Any] = {
        "color": DEFAULT_BODY_COLOR,
        "align": "left",
        "anchor": "middle",
        "fontSize": DEFAULT_FONT_SIZE,
    }
    table_style = _style_keys(style)

    grid = _build_grid(columns, raw_rows, has_header)

    rows: list[dict[str, Any]] = []
    row_count = len(grid)

    for r, grid_row in enumerate(grid):
        is_header = has_header and r == 0
        row_source = grid_row["source"]
        row_style = _style_keys(row_source)

        if is_header:
            band_style: dict[str, Any] = {
                "fill": accent,
                "color": DEFAULT_HEADER_COLOR,
                "bold": True,
                **header_style,
            }
        else:
            band_style = dict(body_style)

        # Striping is counted over BODY rows only, and the first body row is
        # never striped — which is what the writer did before this existed.
        if not is_header and stripe_on:
            body_index = r - 1 if has_header else r
            if body_index % 2 == 1:
                band_style = {**band_style, "fill": DEFAULT_STRIPE_FILL, **stripe_style}

        cells = [
            _resolve_cell(
                slot,
                [table_defaults, table_style, band_style, _style_keys(columns[c]), row_style],
                {
                    "firstRow": r == 0,
                    "lastRow": r == row_count - 1,
                    "firstCol": c == 0,
                    "lastCol": c == len(columns) - 1,
                },
            )
            for c, slot in enumerate(grid_row["cells"])
        ]

        rows.append(
            {
                "header": is_header,
                "height": _row_height(row_source, band_style, table_style, is_header),
                "cells": cells,
            }
        )

    return {"columns": columns, "rows": rows, "hasHeader": has_header}


# ── Columns ───────────────────────────────────────────────────────────────


def normalize_columns(raw: list[Any]) -> list[dict[str, Any]]:
    """Normalise the column list, resolving widths to fractions that sum to 1.

    Two modes, chosen by the values themselves: every declared width <= 1 makes
    them FRACTIONS of the table (columns without one share what is left over);
    any declared width > 1 makes them WEIGHTS (columns without one weigh 1). No
    width anywhere is an equal split, which is what the writer did before widths
    were reachable at all.
    """
    columns: list[dict[str, Any]] = []
    for i, col in enumerate(raw):
        c = col if is_plain_object(col) else {"key": php_string(col)}
        width = c.get("width")
        columns.append(
            {
                "key": php_string(c.get("key", f"col{i}")),
                "label": php_string(c.get("label", c.get("key", ""))),
                "width": php_float(width) if is_numeric(width) and php_float(width) > 0 else None,
                "align": c.get("align"),
                "anchor": c.get("anchor"),
            }
        )

    n = len(columns)
    if n == 0:
        return []

    declared = [c["width"] for c in columns if c["width"] is not None]

    if not declared:
        for c in columns:
            c["widthFrac"] = 1 / n
        return columns

    as_fractions = max(declared) <= 1.0
    undeclared = n - len(declared)

    if as_fractions:
        remaining = max(0.0, 1.0 - sum(declared))
        share = remaining / undeclared if undeclared > 0 else 0.0
        weights = [c["width"] if c["width"] is not None else share for c in columns]
    else:
        weights = [c["width"] if c["width"] is not None else 1.0 for c in columns]

    total = sum(weights)
    for i, c in enumerate(columns):
        c["widthFrac"] = weights[i] / total if total > 0 else 1 / n

    return columns


def column_widths_emu(columns: list[dict[str, Any]], total_emu: int) -> list[int]:
    """Column widths in EMU that sum EXACTLY to the table width.

    Rounding each fraction independently loses or gains a few EMU and leaves
    the grid a hair narrower or wider than the frame; accumulating and
    differencing cannot.
    """
    out: list[int] = []
    cum = 0.0
    prev = 0
    for col in columns:
        cum += php_float(col["widthFrac"])
        edge = int(php_round(cum * total_emu))
        out.append(edge - prev)
        prev = edge
    return out


# ── The grid ──────────────────────────────────────────────────────────────


def _build_grid(
    columns: list[dict[str, Any]], raw_rows: list[Any], has_header: bool
) -> list[dict[str, Any]]:
    """Lay every row out as exactly ``len(columns)`` slots, marking the ones a
    span swallows. Spans are clamped to the grid: a ``colSpan`` of 99 on a
    two-column table is a 2, never a row with 99 cells in it.
    """
    n = len(columns)
    grid: list[dict[str, Any]] = []

    if has_header:
        grid.append(
            {
                "source": {},
                "cells": [
                    {"spec": {"text": col["label"]}, "merged": "none", "colSpan": 1, "rowSpan": 1}
                    for col in columns
                ],
            }
        )

    for row in raw_rows:
        if not is_plain_object(row):
            continue
        cell_map = row.get("cells")
        cell_map = cell_map if is_plain_object(cell_map) else row
        grid.append(
            {
                "source": row,
                "cells": [
                    {
                        "spec": _cell_spec(cell_map.get(col["key"])),
                        "merged": "none",
                        "colSpan": 1,
                        "rowSpan": 1,
                    }
                    for col in columns
                ],
            }
        )

    for r in range(len(grid)):
        for c in range(n):
            if grid[r]["cells"][c]["merged"] != "none":
                continue
            spec = grid[r]["cells"][c]["spec"]
            col_span = _clamp_span(spec.get("colSpan"), n - c)
            row_span = _clamp_span(spec.get("rowSpan"), len(grid) - r)

            grid[r]["cells"][c]["colSpan"] = col_span
            grid[r]["cells"][c]["rowSpan"] = row_span

            for dr in range(row_span):
                for dc in range(col_span):
                    if dr == 0 and dc == 0:
                        continue
                    covered = "both" if dc > 0 and dr > 0 else ("horizontal" if dc > 0 else "vertical")
                    grid[r + dr]["cells"][c + dc]["merged"] = covered
                    grid[r + dr]["cells"][c + dc]["spec"] = {"text": ""}

    return grid


def _clamp_span(span: Any, available: int) -> int:
    s = int(php_float(span)) if is_numeric(span) else 1
    return max(1, min(s, max(1, available)))


def _cell_spec(value: Any) -> dict[str, Any]:
    """A cell value is either a scalar or a spec object.

    BEHAVIOUR CHANGE: an object used to be JSON-encoded into the cell text.
    Anything carrying none of the spec keys still is, so a genuine nested value
    an agent meant to display is not silently emptied.
    """
    if is_plain_object(value):
        if any(k in value for k in _CELL_SPEC_KEYS):
            spec = dict(value)
            spec["text"] = _scalar_text(value.get("text", ""))
            return spec
        return {"text": _php_json(value)}
    if isinstance(value, list):
        return {"text": _php_json(value)}
    return {"text": _scalar_text(value)}


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, (int, float, str)):
        return php_string(value)
    return _php_json(value)


def _php_json(value: Any) -> str:
    return php_json_encode(value)


# ── One cell ──────────────────────────────────────────────────────────────


def _resolve_cell(
    slot: dict[str, Any], chain: list[dict[str, Any]], edges: dict[str, bool]
) -> dict[str, Any]:
    spec = slot["spec"]
    layers = [*chain, _style_keys(spec)]

    resolved: dict[str, Any] = {}
    for layer in layers:
        resolved.update(layer)

    fill = resolved.get("fill")

    return {
        "text": php_string(spec.get("text", "")),
        "bold": bool(resolved.get("bold", False)),
        "italic": bool(resolved.get("italic", False)),
        "underline": bool(resolved.get("underline", False)),
        "color": _hex(resolved.get("color", DEFAULT_BODY_COLOR), "0F172A"),
        "fill": None if fill is False or fill is None or fill == "none" else _hex(fill, "FFFFFF"),
        "align": _align(resolved.get("align", "left")),
        "anchor": _anchor(resolved.get("anchor", "middle")),
        "fontSize": max(1.0, php_float(resolved.get("fontSize", DEFAULT_FONT_SIZE)) / 2),
        "letterSpacing": php_float(resolved.get("letterSpacing", 0)),
        "caps": _caps(resolved.get("caps", "none")),
        "fontFamily": php_string(resolved["fontFamily"]) if resolved.get("fontFamily") is not None else None,
        "padding": _resolve_padding(resolved.get("padding")),
        "borders": _resolve_borders(layers, edges),
        "colSpan": int(slot["colSpan"]),
        "rowSpan": int(slot["rowSpan"]),
        "merged": slot["merged"],
    }


def _resolve_borders(layers: list[dict[str, Any]], edges: dict[str, bool]) -> dict[str, Any]:
    """Per-side border resolution. The whole point of the module, and the part
    ``last-word`` needs identically.
    """
    sides = (("left", "firstCol"), ("right", "lastCol"), ("top", "firstRow"), ("bottom", "lastRow"))
    out: dict[str, Any] = {}

    for side, edge_key in sides:
        is_outer = edges[edge_key]
        value: Any = {"width": DEFAULT_BORDER_WIDTH, "color": DEFAULT_BORDER_COLOR}

        for layer in layers:
            if "borders" not in layer:
                continue
            spec = layer["borders"]

            if spec is False or spec is None or spec == "none":
                value = None
                continue
            if not is_plain_object(spec):
                continue
            if spec.get("none"):
                value = None
                continue

            # A bare {width,color,style} means all four sides.
            if "width" in spec or "color" in spec or "style" in spec:
                value = spec
            if "all" in spec:
                value = spec["all"]
            band = "outer" if is_outer else "inner"
            if band in spec:
                value = spec[band]
            if side in spec:
                value = spec[side]

        out[side] = _border_side(value)

    return out


def _border_side(value: Any) -> dict[str, Any] | None:
    if value is False or value is None or value == "none":
        return None
    if not is_plain_object(value):
        return None

    width = php_float(value["width"]) if is_numeric(value.get("width")) else DEFAULT_BORDER_WIDTH
    if width <= 0:
        return None

    style = php_string(value.get("style", "solid"))

    return {
        "width": width,
        "color": _hex(value.get("color", DEFAULT_BORDER_COLOR), "D9DEE4"),
        "style": style if style in ("solid", "dash", "dot") else "solid",
    }


def _resolve_padding(padding: Any) -> dict[str, float]:
    out = {
        "left": DEFAULT_PADDING_X,
        "right": DEFAULT_PADDING_X,
        "top": DEFAULT_PADDING_Y,
        "bottom": DEFAULT_PADDING_Y,
    }

    if is_numeric(padding):
        v = php_float(padding)
        return {"left": v, "right": v, "top": v, "bottom": v}
    if is_plain_object(padding):
        for side in ("left", "right", "top", "bottom"):
            if is_numeric(padding.get(side)):
                out[side] = php_float(padding[side])

    return out


# ── Bands + defaults ──────────────────────────────────────────────────────


def _style_keys(source: Any) -> dict[str, Any]:
    """The style keys a layer may contribute.

    Filtering by an allow-list keeps a row's ``cells`` / ``height`` (and a
    column's ``key`` / ``label``) from leaking into a cell's resolved style.
    """
    if not is_plain_object(source):
        return {}
    return {k: source[k] for k in _STYLE_KEYS if k in source and source[k] is not None}


def _row_height(
    row_source: Any, band_style: dict[str, Any], table_style: dict[str, Any], is_header: bool
) -> float:
    candidates = [
        row_source.get("height") if is_plain_object(row_source) else None,
        band_style.get("height"),
        table_style.get("rowHeight"),
    ]
    for candidate in candidates:
        if is_numeric(candidate):
            return php_float(candidate)
    return float(DEFAULT_HEADER_HEIGHT if is_header else DEFAULT_BODY_HEIGHT)


# ── Small coercions ───────────────────────────────────────────────────────


def _theme_color(theme: dict[str, Any], key: str, fallback: str) -> str:
    colors = theme.get("colors")
    colors = colors if is_plain_object(colors) else {}
    value = colors.get(key)
    return value if isinstance(value, str) and value != "" else fallback


def _hex(value: Any, fallback: str) -> str:
    return Color.parse(value if isinstance(value, str) else None, fallback)[0]


def _align(value: Any) -> str:
    v = php_string(value)
    if v in ("center", "centre"):
        return "center"
    if v == "right":
        return "right"
    if v == "justify":
        return "justify"
    return "left"


def _anchor(value: Any) -> str:
    v = php_string(value)
    if v == "top":
        return "top"
    if v == "bottom":
        return "bottom"
    return "middle"


def _caps(value: Any) -> str:
    v = php_string(value)
    if v == "small":
        return "small"
    if v in ("all", "upper"):
        return "all"
    return "none"

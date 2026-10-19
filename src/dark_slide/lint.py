"""Layout findings for a deck, from the deck alone.

Mirrors PHP ``DarkSlide\\Lint`` rule for rule and message for message; read that
class for the metrics and why they are conservative. The same cases, with the
same expected strings, run in all three engines (``tests/test_lint.py``).

Two PHP-isms reproduced on purpose: numbers in messages are rounded HALF AWAY
FROM ZERO (``number_format``), never Python's half-to-even; and a value is a
number only when PHP's ``is_numeric`` says so, which rejects ``bool``.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .helpers import design_units
from .util import is_numeric, is_plain_object, php_float

# PHP: /\*\*[^*\n]+\*\*|(^|\n)#{1,6}[ \t]/ -- ASCII only, no multiline flag.
_LITERAL_MARKDOWN = re.compile(r"\*\*[^*\n]+\*\*|(^|\n)#{1,6}[ \t]")

__all__ = ["lint_deck"]

_MIN_PT = 12.0
_BOLD_GLYPH = 0.62
_GLYPH = 0.55
_LINE = 1.25
_KPI_PAD = 64.0

_MARKS = re.compile(r"\*\*|__|`")
_BULLET = re.compile(r"^[ \t]*[-*][ \t]+")
_HEADING = re.compile(r"^#+[ \t]+")


def lint_deck(deck: Any) -> list[dict[str, Any]]:
    """``[{code, slide (1-based), element, message}]`` -- see PHP ``Lint::deck``."""
    theme = deck.get("theme") if is_plain_object(deck) and is_plain_object(deck.get("theme")) else {}
    canvas_w = design_units.design_width(theme)
    ratio_raw = theme.get("aspectRatio")
    ratio = php_float(ratio_raw) if is_numeric(ratio_raw) and php_float(ratio_raw) > 0 else 16 / 9
    canvas_h = canvas_w / ratio
    fonts = theme.get("fonts")
    heading_font = fonts.get("heading") if is_plain_object(fonts) and isinstance(fonts.get("heading"), str) else ""

    findings: list[dict[str, Any]] = []
    slides = deck.get("slides") if is_plain_object(deck) and isinstance(deck.get("slides"), list) else []
    for n, slide in enumerate(slides):
        slide_no = n + 1
        items: list[dict[str, Any]] = []
        elements = slide.get("elements") if is_plain_object(slide) and isinstance(slide.get("elements"), list) else []
        for i, el in enumerate(elements):
            if not is_plain_object(el):
                continue
            b = _box(el)
            if b is None:
                continue
            element_id = _label(el.get("id"))
            element_id = element_id if element_id is not None else f"element {i + 1}"
            el_type = el.get("type") if isinstance(el.get("type"), str) else ""

            if b["x"] < -0.001 or b["y"] < -0.001 or b["x"] + b["w"] > 1.001 or b["y"] + b["h"] > 1.001:
                findings.append(_finding("off-slide", slide_no, element_id,
                                         "The box runs off the slide: x + w and y + h must stay within 0..1."))

            extent = dict(b)
            if el_type == "text":
                style = el.get("style") if is_plain_object(el.get("style")) else {}
                font = php_float(style.get("fontSize")) if is_numeric(style.get("fontSize")) else 28.0
                need = _text_height(el, style, font, b["w"] * canvas_w, canvas_w, heading_font)
                if need is not None:
                    need_h = need / canvas_h
                    extent["h"] = need_h
                    align = style.get("verticalAlign")
                    if align == "middle":
                        extent["y"] = b["y"] + (b["h"] - need_h) / 2
                    elif align == "bottom":
                        extent["y"] = b["y"] + b["h"] - need_h
                    else:
                        extent["y"] = b["y"]
                    if need > b["h"] * canvas_h + 1:
                        up = _up2(need_h)
                        findings.append(_finding(
                            "text-overflow", slide_no, element_id,
                            f"At {_num(font)}px this text needs about {up} of the slide height and its box is "
                            f"{_num(b['h'])}: it will wrap past the box, more so in a substitute font. Make h at "
                            f"least {up} and move what is below it down, shorten the text, or lower fontSize.",
                        ))
                pt = font * 720 / canvas_w
                if pt < _MIN_PT:
                    findings.append(_finding(
                        "small-text", slide_no, element_id,
                        f"fontSize {_num(font)} is {_num(math.floor(pt * 10) / 10)}pt on the slide: too small to "
                        f"read when projected. Use {_num(math.ceil(_MIN_PT * canvas_w / 720))} (12pt) or more.",
                    ))

            # Markdown in a box that is not markdown prints its markers as typed.
            content = el.get("content")
            fmt = el.get("format")
            if (
                el_type in ("text", "shape")
                and isinstance(content, str)
                and (fmt if fmt is not None else "plain") != "markdown"
                and _LITERAL_MARKDOWN.search(content)
            ):
                findings.append(_finding(
                    "literal-markdown", slide_no, element_id,
                    'This text uses markdown (**bold** or a # heading) but its format is not "markdown", '
                    'so the markers print as typed. Set "format": "markdown", or remove the markers.',
                ))

            if el_type == "kpiBand":
                message = _kpi(el, b, canvas_w)
                if message is not None:
                    findings.append(_finding("kpi-overflow", slide_no, element_id, message))

            items.append({"id": element_id, "type": el_type, "box": b, "extent": extent})

        for a in items:
            if a["type"] != "text":
                continue
            for o in items:
                if a["id"] == o["id"] or _contains(o["box"], a["box"]) or _contains(a["box"], o["box"]):
                    continue
                if _intersects(a["extent"], o["extent"] if o["type"] == "text" else o["box"]):
                    findings.append(_finding(
                        "overlap", slide_no, a["id"],
                        f"Its text runs into \"{o['id']}\". Place one below the other's bottom edge (y + h) "
                        "with a gap of at least 0.02.",
                    ))

    return findings


def _finding(code: str, slide: int, element: str, message: str) -> dict[str, Any]:
    return {"code": code, "slide": slide, "element": element, "message": message}


def _box(el: dict[str, Any]) -> dict[str, float] | None:
    for k in ("x", "y", "w", "h"):
        v = el.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return None
    return {k: float(el[k]) for k in ("x", "y", "w", "h")}


def _label(v: Any) -> str | None:
    """A string, or an integer as a string; None otherwise. Mirrors PHP ``Lint::label``."""
    if isinstance(v, str):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return None


def _text_height(el: dict[str, Any], style: dict[str, Any], font: float, box_w: float, canvas_w: float,
                 heading_font: str) -> float | None:
    content = el.get("content")
    if not isinstance(content, str) or content.strip() == "":
        return None
    weight = style.get("weight")
    bold = (
        (is_numeric(weight) and int(php_float(weight)) >= 600)
        or weight == "bold"
        or (heading_font != "" and style.get("fontFamily") == heading_font)
    )
    glyph = (_BOLD_GLYPH if bold else _GLYPH) * font
    pad_x, pad_y = _padding(style, canvas_w)
    usable = max(1.0, box_w - 2 * pad_x)
    lines = 0
    for line in content.split("\n"):
        plain = _HEADING.sub("", _BULLET.sub("", _MARKS.sub("", line), count=1), count=1)
        lines += max(1, math.ceil((len(plain) * glyph) / usable))
    return lines * _LINE * font + 2 * pad_y


def _padding(style: dict[str, Any], canvas_w: float) -> tuple[float, float]:
    p = style.get("padding")
    if isinstance(p, (int, float)) and not isinstance(p, bool):
        return float(p), float(p)
    if isinstance(p, (dict, list)) and isinstance(p, dict):
        x = p.get("left", p.get("x"))
        y = p.get("top", p.get("y"))
        if is_numeric(x) and is_numeric(y):
            return php_float(x), php_float(y)
    return 7.2 * canvas_w / 720, 3.6 * canvas_w / 720


def _kpi(el: dict[str, Any], b: dict[str, float], canvas_w: float) -> str | None:
    raw = el.get("items")
    items = [i for i in raw if isinstance(i, (dict, list))] if isinstance(raw, list) else []
    if not items:
        return None
    style = el.get("style") if is_plain_object(el.get("style")) else {}
    size = php_float(style.get("valueFontSize")) if is_numeric(style.get("valueFontSize")) else 40.0
    cell = b["w"] * canvas_w / len(items)
    longest = 0
    for item in items:
        value = _label(item.get("value")) if isinstance(item, dict) else None
        longest = max(longest, len(value or ""))
    need = longest * _BOLD_GLYPH * size + _KPI_PAD
    if longest == 0 or need <= cell:
        return None
    return (
        f"A {longest}-character value at valueFontSize {_num(size)} needs about {math.ceil(need)}px and each of "
        f"the {len(items)} cells is {math.floor(cell)}px: values will run into each other. Lower valueFontSize to "
        f"{math.floor((cell - _KPI_PAD) / (longest * _BOLD_GLYPH))} or less."
    )


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["x"] < b["x"] + b["w"] - 0.001 and b["x"] < a["x"] + a["w"] - 0.001
        and a["y"] < b["y"] + b["h"] - 0.001 and b["y"] < a["y"] + a["h"] - 0.001
    )


def _contains(outer: dict[str, float], inner: dict[str, float]) -> bool:
    return (
        outer["x"] <= inner["x"] + 0.001 and outer["y"] <= inner["y"] + 0.001
        and outer["x"] + outer["w"] >= inner["x"] + inner["w"] - 0.001
        and outer["y"] + outer["h"] >= inner["y"] + inner["h"] - 0.001
    )


def _half_up(v: float, places: int) -> Decimal:
    """PHP's round / number_format: half away from zero, on the shortest repr."""
    return Decimal(repr(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _up2(v: float) -> str:
    """Rounded UP to 2 decimals, shown with 2. Mirrors PHP ``Lint::up2``."""
    hundredths = math.ceil(float(_half_up(v * 100, 6)))
    return f"{_half_up(hundredths / 100, 2):.2f}"


def _num(v: float) -> str:
    """Shown as authored: 88 -> "88", 7.5 -> "7.5". Mirrors PHP ``Lint::num``."""
    out = format(_half_up(float(v), 4), "f").rstrip("0").rstrip(".")
    return out if out not in ("", "-0") else "0"

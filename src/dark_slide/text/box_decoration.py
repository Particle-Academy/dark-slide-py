"""The box a text element lives in: fill, outline, radius, insets — and the
left accent bar that makes a callout a callout.

Mirrors PHP ``Text\\BoxDecoration`` and the Node ``text/box-decoration.ts``.

Why the accent bar is a gradient
--------------------------------

DrawingML has no per-side border on a shape: ``<a:ln>`` is all four sides or
none. So a coloured bar down one edge has always meant a second shape
underneath, which pushes z-ordering and geometry onto whoever authors the deck —
and an agent emitting three elements that have to line up is three chances to
get it wrong.

``<a:gradFill>`` with two stops at ADJACENT positions is a hard edge, not a
blend. Four stops therefore paint a bar and a flat tint in a single shape, with
no extra element, no z-order and no second shape id for the animation builder to
renumber. Verified rendering before it was designed in.
"""

from __future__ import annotations

from typing import Any

from ..helpers import color as Color
from ..helpers import emu as Emu
from ..helpers import xml as Xml
from ..helpers.emu import php_round
from ..util import is_numeric, is_plain_object, php_float, php_string

__all__ = ["ACCENT_GUTTER_PT", "sp_pr", "has_decoration", "body_insets"]

#: Gap between the accent bar and the text when nothing says otherwise.
ACCENT_GUTTER_PT = 8.0


def sp_pr(style: dict[str, Any], width_emu: int, height_emu: int) -> str:
    """The ``<p:spPr>`` interior: geometry, fill and line, in schema order."""
    return _geometry(style, width_emu, height_emu) + _fill(style, width_emu) + _line(style)


def has_decoration(style: dict[str, Any]) -> bool:
    return any(k in style for k in ("fill", "accentBar", "border", "radius"))


def _geometry(style: dict[str, Any], width_emu: int, height_emu: int) -> str:
    radius = style.get("radius")
    if not is_numeric(radius) or php_float(radius) <= 0:
        return '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'

    # `adj` is a proportion of HALF the shorter side, in 1/1000 of a percent.
    shorter = max(1, min(width_emu, height_emu))
    adj = int(php_round(Emu.from_pt(php_float(radius)) / (shorter / 2) * 100000))
    adj = max(0, min(50000, adj))

    return f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'


def _fill(style: dict[str, Any], width_emu: int) -> str:
    bar = style.get("accentBar")
    bar = bar if is_plain_object(bar) else None
    fill_value = style.get("fill")
    has_fill = "fill" in style and fill_value is not False and fill_value != "none"

    if bar is None:
        if not has_fill:
            return "<a:noFill/>"
        hex_value = Color.parse(php_string(fill_value), "FFFFFF")[0]
        return f'<a:solidFill><a:srgbClr val="{hex_value}"/></a:solidFill>'

    bar_hex = Color.parse(php_string(bar.get("color", "#8B5CF6")), "8B5CF6")[0]
    rest_hex = Color.parse(php_string(fill_value) if has_fill else "#FFFFFF", "FFFFFF")[0]

    bar_emu = Emu.from_pt(php_float(bar.get("width", 4)))
    pos = int(php_round(bar_emu / width_emu * 100000)) if width_emu > 0 else 1000
    pos = max(1, min(99998, pos))

    if bar.get("side", "left") == "right":
        edge = 100000 - pos
        stops = (
            f'<a:gs pos="0"><a:srgbClr val="{rest_hex}"/></a:gs>'
            f'<a:gs pos="{edge - 1}"><a:srgbClr val="{rest_hex}"/></a:gs>'
            f'<a:gs pos="{edge}"><a:srgbClr val="{bar_hex}"/></a:gs>'
            f'<a:gs pos="100000"><a:srgbClr val="{bar_hex}"/></a:gs>'
        )
    else:
        stops = (
            f'<a:gs pos="0"><a:srgbClr val="{bar_hex}"/></a:gs>'
            f'<a:gs pos="{pos}"><a:srgbClr val="{bar_hex}"/></a:gs>'
            f'<a:gs pos="{pos + 1}"><a:srgbClr val="{rest_hex}"/></a:gs>'
            f'<a:gs pos="100000"><a:srgbClr val="{rest_hex}"/></a:gs>'
        )

    return f'<a:gradFill flip="none" rotWithShape="0"><a:gsLst>{stops}</a:gsLst><a:lin ang="0" scaled="0"/></a:gradFill>'


def _line(style: dict[str, Any]) -> str:
    border = style.get("border")
    if border is None or border is False or border == "none":
        return ""
    if not is_plain_object(border):
        return ""

    width = php_float(border["width"]) if is_numeric(border.get("width")) else 1.0
    if width <= 0:
        return ""

    hex_value = Color.parse(php_string(border.get("color", "#CBD5E1")), "CBD5E1")[0]
    dash = (
        f'<a:prstDash val="{Xml.attr(php_string(border["style"]))}"/>'
        if border.get("style", "solid") != "solid"
        else ""
    )

    return f'<a:ln w="{Emu.from_pt(width)}"><a:solidFill><a:srgbClr val="{hex_value}"/></a:solidFill>{dash}</a:ln>'


def body_insets(style: dict[str, Any]) -> str:
    """``lIns``/``tIns``/``rIns``/``bIns`` for the text body, or ``""``.

    Empty when the element says nothing, so decks that predate this keep their
    bytes. An accent bar with no explicit padding gets a left inset wide enough
    to clear it, because text printed on top of the bar is the obvious way for
    this feature to look broken.
    """
    padding = style.get("padding")
    bar = style.get("accentBar")
    bar = bar if is_plain_object(bar) else None

    if padding is None and bar is None:
        return ""

    # PowerPoint's own defaults, which is what an undecorated box uses.
    sides = {"left": 7.2, "right": 7.2, "top": 3.6, "bottom": 3.6}

    if bar is not None and bar.get("side", "left") != "right":
        sides["left"] = php_float(bar.get("width", 4)) + ACCENT_GUTTER_PT
    if bar is not None and bar.get("side", "left") == "right":
        sides["right"] = php_float(bar.get("width", 4)) + ACCENT_GUTTER_PT

    if is_numeric(padding):
        v = php_float(padding)
        sides = dict.fromkeys(sides, v)
    elif is_plain_object(padding):
        for side in sides:
            if is_numeric(padding.get(side)):
                sides[side] = php_float(padding[side])

    return (
        f' lIns="{Emu.from_pt(sides["left"])}"'
        f' tIns="{Emu.from_pt(sides["top"])}"'
        f' rIns="{Emu.from_pt(sides["right"])}"'
        f' bIns="{Emu.from_pt(sides["bottom"])}"'
    )

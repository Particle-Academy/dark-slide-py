"""Colour parsing. Mirrors PHP ``Helpers\\Color``.

Returns ``(hex, alpha)`` where hex is uppercase ``RRGGBB`` with no ``#`` and
alpha is in PPTX percentage units (100% = 100000). Anything unrecognised
falls back to the caller's default at full opacity — never an error, because
a deck comes from an agent and a bad colour should not lose a slide.
"""

from __future__ import annotations

import re

from .emu import php_round

__all__ = ["parse", "NAMED_COLORS"]

#: The subset of CSS named colours the engines recognise. Deliberately short —
#: anything else falls back to the caller's default.
NAMED_COLORS: dict[str, str] = {
    "black": "000000",
    "white": "FFFFFF",
    "red": "FF0000",
    "green": "008000",
    "blue": "0000FF",
    "yellow": "FFFF00",
    "cyan": "00FFFF",
    "magenta": "FF00FF",
    "gray": "808080",
    "grey": "808080",
    "silver": "C0C0C0",
    "maroon": "800000",
    "olive": "808000",
    "lime": "00FF00",
    "aqua": "00FFFF",
    "teal": "008080",
    "navy": "000080",
    "fuchsia": "FF00FF",
    "purple": "800080",
    "orange": "FFA500",
}

_HEX3 = re.compile(r"^#([0-9a-fA-F]{3})$")
_HEX6 = re.compile(r"^#([0-9a-fA-F]{6})$")
_HEX8 = re.compile(r"^#([0-9a-fA-F]{8})$")
_RGB = re.compile(
    r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)$",
    re.IGNORECASE,
)


def parse(color: str | None, fallback_hex: str = "000000") -> tuple[str, int]:
    """Parse a CSS-ish colour into ``(RRGGBB, alpha0..100000)``."""
    if color is None or color == "":
        return (fallback_hex, 100000)
    c = color.strip()

    if c in ("transparent", "none"):
        return (fallback_hex, 0)

    m = _HEX3.match(c)
    if m:
        h = m.group(1)
        return ((h[0] * 2 + h[1] * 2 + h[2] * 2).upper(), 100000)

    m = _HEX6.match(c)
    if m:
        return (m.group(1).upper(), 100000)

    m = _HEX8.match(c)
    if m:
        digits = m.group(1)
        alpha = int(digits[6:8], 16)
        return (digits[0:6].upper(), int(php_round(alpha / 255 * 100000)))

    m = _RGB.match(c)
    if m:
        r, g, b = (int(m.group(i), 10) for i in (1, 2, 3))
        alpha = float(m.group(4)) if m.group(4) is not None else 1.0
        return (f"{r:02X}{g:02X}{b:02X}".upper(), int(php_round(alpha * 100000)))

    named = NAMED_COLORS.get(c.lower())
    if named is not None:
        return (named, 100000)

    return (fallback_hex, 100000)

"""The deck's design canvas, mapped onto the PPTX slide. One place, one formula.

Mirrors PHP ``Helpers\\DesignUnits``.

The model
---------

A deck is authored on a design canvas ``theme.slideWidth`` pixels wide (1920 by
default), exactly as ``@particle-academy/fancy-slides`` renders it: position and
size are fractions of the slide, and every authored LENGTH is a design pixel
(``fontSize``, ``strokeWidth``, ``letterSpacing``, ``spaceBefore``,
``spaceAfter``, ``padding``, ``radius``, border and accent-bar widths, table row
heights). The canvas scales to the slide, so a length keeps its share of the
slide width::

    points = px * 720 / design_width       (the slide is 10in = 720pt wide)

``fontSize: 96`` on the default canvas is 36pt, which is 5% of the slide's width
in PowerPoint and in fancy-slides' preview alike.

What it replaced
----------------

Until 0.3 (PHP 0.10, Node 0.8) the writer halved ``fontSize`` into points with
an 8pt floor and took every other length above as points. On a 720pt slide the
halving made text a third larger than fancy-slides showed it, and one style
object mixed two units. ``theme.slideWidth: 1440`` gives exactly the old sizes.

Defaults are not authored lengths
---------------------------------

A built-in default that is PowerPoint's own (a text box's 7.2pt / 3.6pt insets,
a 1pt outline, a 0.75pt table rule, 40pt / 30pt minimum row heights) stays in
points. Only a value the deck states is converted.

**Operation order is part of the contract.** Every engine computes
``px * 720 / design_width`` in that order, so the double, and therefore every
rounded EMU, agrees. ``px * (720 / design_width)`` is a different double on
some inputs, and the difference surfaces as one EMU on a rounding tie.
"""

from __future__ import annotations

from typing import Any

from ..util import is_numeric, is_plain_object, php_float
from . import emu as Emu
from .emu import php_round

__all__ = [
    "DEFAULT_DESIGN_WIDTH",
    "SLIDE_WIDTH_PT",
    "MIN_FONT_PT",
    "design_width",
    "to_pt",
    "font_pt",
    "slide_height_emu",
    "slide_size_type",
]

DEFAULT_DESIGN_WIDTH = 1920.0

#: The slide is 10 inches wide: 9144000 EMU / 12700 EMU per point.
SLIDE_WIDTH_PT = 720.0

#: A PPTX font size has to be at least 1pt (``ST_TextFontSize`` starts at 100).
MIN_FONT_PT = 1.0


def design_width(theme: Any) -> float:
    """``theme.slideWidth`` when it is a positive number, else 1920."""
    width = theme.get("slideWidth") if is_plain_object(theme) else None
    return php_float(width) if is_numeric(width) and php_float(width) > 0 else DEFAULT_DESIGN_WIDTH


def to_pt(px: float, theme: Any) -> float:
    """A design length in points. ``px * 720 / width``, in that order."""
    return px * SLIDE_WIDTH_PT / design_width(theme)


def font_pt(px: float, theme: Any) -> float:
    """A font size in points, never below PPTX's 1pt minimum."""
    return max(MIN_FONT_PT, to_pt(px, theme))


def slide_height_emu(theme: Any) -> int:
    """The slide height: 10in wide, ``theme.aspectRatio`` (width / height,
    16/9 by default, as fancy-slides reads it) decides the rest."""
    ratio = theme.get("aspectRatio") if is_plain_object(theme) else None
    if not is_numeric(ratio) or php_float(ratio) <= 0:
        return Emu.DEFAULT_SLIDE_HEIGHT
    return int(php_round(Emu.DEFAULT_SLIDE_WIDTH / php_float(ratio)))


def slide_size_type(height_emu: int) -> str | None:
    """The named ``<p:sldSz type>`` for a 10in-wide slide of this height, or None."""
    return {
        5143500: "screen16x9",
        5715000: "screen16x10",
        6858000: "screen4x3",
    }.get(height_emu)

"""EMU conversion. Mirrors PHP ``Helpers\\Emu``. 914,400 EMU = 1 inch.

**This module owns :func:`php_round`, and nothing in the package may call the
builtin ``round``.** Python rounds half to EVEN; PHP rounds half AWAY FROM
ZERO. Every position and size in a deck is ``round(fraction * 9144000)``, so
the difference is not a corner case here — it is one EMU on any coordinate
that lands on a tie, which for slide-width 9,144,000 happens at every
multiple of 1/128 and for slide-height 5,143,500 at every multiple of 1/8.
"""

from __future__ import annotations

import math

__all__ = [
    "EMU_PER_INCH",
    "DEFAULT_SLIDE_WIDTH",
    "DEFAULT_SLIDE_HEIGHT",
    "php_round",
    "from_frac_x",
    "from_frac_y",
    "to_frac_x",
    "to_frac_y",
    "from_pt",
    "hundredths_of_point",
]

EMU_PER_INCH = 914400

#: Default 16:9 slide at 10 inches. The writer ALWAYS uses these — a deck's
#: ``theme.slideWidth`` / ``theme.aspectRatio`` are read by the editor and
#: ignored here, exactly as in PHP.
DEFAULT_SLIDE_WIDTH = 9144000
DEFAULT_SLIDE_HEIGHT = 5143500


def php_round(value: float) -> float:
    """PHP's ``round()``: half away from zero.

    ``php_round(2.5) == 3`` where the builtin gives ``2``; ``php_round(-2.5)
    == -3`` where the builtin gives ``-2``.
    """
    if math.isnan(value) or math.isinf(value):
        return value
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def from_frac_x(f: float, slide_width_emu: int = DEFAULT_SLIDE_WIDTH) -> int:
    """A 0..1 fraction of slide width, in EMU."""
    return int(php_round(f * slide_width_emu))


def from_frac_y(f: float, slide_height_emu: int = DEFAULT_SLIDE_HEIGHT) -> int:
    """A 0..1 fraction of slide height, in EMU."""
    return int(php_round(f * slide_height_emu))


def to_frac_x(emu: int, slide_width_emu: int = DEFAULT_SLIDE_WIDTH) -> float:
    return 0.0 if slide_width_emu == 0 else emu / slide_width_emu


def to_frac_y(emu: int, slide_height_emu: int = DEFAULT_SLIDE_HEIGHT) -> float:
    return 0.0 if slide_height_emu == 0 else emu / slide_height_emu


def from_pt(pt: float) -> int:
    """Points (1/72 inch) to EMU. Used for stroke widths and table row heights."""
    return int(php_round(pt * (EMU_PER_INCH / 72)))


def hundredths_of_point(pt: float) -> int:
    """A drawingML ``sz`` attribute: 24pt becomes 2400."""
    return int(php_round(pt * 100))

"""Embedding the host's fonts in a ``.pptx``. Mirrors PHP ``DarkSlide\\Fonts``."""

from __future__ import annotations

from ..exceptions import FontEmbeddingException
from .embedded_fonts import VARIANTS, EmbeddedFonts
from .true_type_font import TrueTypeFont

__all__ = ["VARIANTS", "EmbeddedFonts", "FontEmbeddingException", "TrueTypeFont"]

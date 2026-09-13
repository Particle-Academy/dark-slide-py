"""The fonts a host asked to embed, validated and wrapped, ready to write.

Mirrors PHP ``Fonts\\EmbeddedFonts``, including every refusal message.

Supplied through the write options, never through the deck::

    dark_slide.write(deck, "out.pptx", {"fonts": {
        "Bebas Neue": {"regular": "/fonts/BebasNeue-Regular.ttf"},
        "Inter": {"regular": inter_regular_bytes, "bold": pathlib.Path("Inter-Bold.ttf")},
    }})

The deck is agent-authored JSON; a font is a licensed binary the host owns.
Keeping the two apart means an agent can name a typeface but can never make the
writer read a file.

Each variant is a path (``str`` / ``os.PathLike``) or the font's bytes. Variants
are ``regular``, ``bold``, ``italic`` and ``boldItalic``, the four slots PPTX has.

Refused, all at once, never skipped: a licence that forbids embedding (OS/2
``fsType`` Restricted License without a less restrictive bit, or bitmap-only),
a file whose own family name is not the typeface it was supplied for, and
anything :meth:`TrueTypeFont.from_bytes` will not accept.
"""

from __future__ import annotations

import os
from typing import Any

from ..exceptions import FontEmbeddingException
from . import embedded_open_type as EmbeddedOpenType
from .true_type_font import TrueTypeFont

__all__ = ["VARIANTS", "EmbeddedFonts"]

VARIANTS = ("regular", "bold", "italic", "boldItalic")

_FS_RESTRICTED = 0x0002
_FS_PREVIEW_PRINT = 0x0004
_FS_EDITABLE = 0x0008
_FS_BITMAP_ONLY = 0x0200

#: PHP ``trim()``'s default character list.
_PHP_TRIM = " \t\n\r\0\x0b"


def _php_key(key: Any) -> str:
    """A map key as PHP's ``(string)`` would give it back."""
    return key if isinstance(key, str) else str(key)


class EmbeddedFonts:
    def __init__(self, parts: list[dict[str, Any]]) -> None:
        #: ``[{typeface, variant, part, bytes}]`` in write order.
        self.parts = parts

    @classmethod
    def none(cls) -> EmbeddedFonts:
        return cls([])

    @classmethod
    def from_options(cls, fonts: Any) -> EmbeddedFonts:
        parts: list[dict[str, Any]] = []
        problems: list[str] = []

        entries = fonts.items() if isinstance(fonts, dict) else enumerate(fonts if isinstance(fonts, list) else [])
        for key, variants in entries:
            typeface = _php_key(key)
            if typeface.strip(_PHP_TRIM) == "":
                problems.append("a font was supplied with an empty typeface name")
                continue
            if not isinstance(variants, (dict, list)) or len(variants) == 0:
                problems.append(f"{typeface}: no font files; give at least 'regular'")
                continue

            keys = list(variants.keys()) if isinstance(variants, dict) else list(range(len(variants)))
            for unknown in keys:
                if _php_key(unknown) not in VARIANTS:
                    problems.append(f"{typeface}: '{_php_key(unknown)}' is not a variant; use {', '.join(VARIANTS)}")

            if not isinstance(variants, dict):
                continue

            for variant in VARIANTS:
                if variant not in variants:
                    continue
                try:
                    font = TrueTypeFont.from_bytes(_load(variants[variant]))
                    _assert_embeddable(font, typeface)
                    parts.append({
                        "typeface": typeface,
                        "variant": variant,
                        "part": f"ppt/fonts/font{len(parts) + 1}.fntdata",
                        "bytes": EmbeddedOpenType.wrap(font, typeface),
                    })
                except FontEmbeddingException as error:
                    problems.append(f"{typeface} ({variant}): {error}")

        if problems:
            raise FontEmbeddingException("These fonts cannot be embedded:\n- " + "\n- ".join(problems))

        return cls(parts)

    def is_empty(self) -> bool:
        return not self.parts

    def by_typeface(self) -> dict[str, dict[str, str]]:
        """The parts grouped by typeface, in the order they were supplied:
        ``typeface -> variant -> part path``."""
        grouped: dict[str, dict[str, str]] = {}
        for part in self.parts:
            grouped.setdefault(part["typeface"], {})[part["variant"]] = part["part"]
        return grouped


def _load(source: Any) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        if data == b"":
            raise FontEmbeddingException("expected a file path or the font bytes")
        return data
    if isinstance(source, os.PathLike):
        source = os.fspath(source)
    if not isinstance(source, str) or source == "":
        raise FontEmbeddingException("expected a file path or the font bytes")
    if "\0" in source:
        # PHP's rule for a string: one carrying a NUL is font data, never a path.
        return source.encode("latin-1")
    if not os.path.isfile(source):
        raise FontEmbeddingException(f"no font file at {source}")
    try:
        with open(source, "rb") as handle:
            return handle.read()
    except OSError as error:
        raise FontEmbeddingException(f"could not read {source}") from error


def _ascii_folded(value: str) -> bytes:
    """``strcasecmp``'s view of a string: its UTF-8 bytes, ASCII case-folded."""
    return value.strip(_PHP_TRIM).encode("utf-8", "surrogatepass").lower()


def _assert_embeddable(font: TrueTypeFont, typeface: str) -> None:
    fs_type = font.fs_type()

    # Bits 0-3 were not mutually exclusive before OS/2 version 3; the least
    # restrictive one set is the one that applies.
    permissive = _FS_PREVIEW_PRINT | _FS_EDITABLE
    if fs_type & _FS_RESTRICTED and not fs_type & permissive:
        raise FontEmbeddingException(
            f"its licence forbids embedding (OS/2 fsType 0x{fs_type:04X}, Restricted License)"
        )
    if fs_type & _FS_BITMAP_ONLY:
        raise FontEmbeddingException(f"its licence allows bitmap embedding only (OS/2 fsType 0x{fs_type:04X})")

    family = font.family()
    if family is None or _ascii_folded(family) != _ascii_folded(typeface):
        raise FontEmbeddingException(
            "the file's family name is '%s', not '%s'; a deck references a face by that name, "
            "so this font would never be used" % (family if family is not None else "(none)", typeface)
        )

"""Wraps a TrueType font in an Embedded OpenType (EOT) header, uncompressed.

Mirrors PHP ``Fonts\\EmbeddedOpenType`` byte for byte.

A ``.pptx`` stores an embedded font as ``ppt/fonts/fontN.fntdata``, and the bytes
in that part are an EOT, not a ``.ttf``: verified by rendering in LibreOffice 26,
where an EOT-wrapped font rendered and the same font stored raw fell back.
Uncompressed (Flags 0) on purpose; LibreOffice's libeot cannot read MicroType
Express.

Layout (version 0x00020002), little-endian, unlike the font inside it::

    EOTSize, FontDataSize, Version, Flags          4 x ULONG
    FontPANOSE                                     10 bytes
    Charset, Italic                                BYTE, BYTE
    Weight                                         ULONG
    fsType, MagicNumber 0x504C                     USHORT, USHORT
    UnicodeRange1..4, CodePageRange1..2            6 x ULONG
    CheckSumAdjustment, Reserved1..4               5 x ULONG
    (Padding, NameSize, UTF-16LE name) x 4         family, style, version, full
    Padding5, RootStringSize (0)
    RootStringCheckSum, EUDCCodePage               ULONG, ULONG
    Padding6, SignatureSize (0), EUDCFlags, EUDCFontSize (0)
    FontData

Names carry a trailing NUL inside their counted size, and Charset is
DEFAULT_CHARSET (1), exactly as the PHP reference writes them.
"""

from __future__ import annotations

import struct

from .true_type_font import TrueTypeFont

__all__ = ["VERSION", "MAGIC", "wrap"]

VERSION = 0x00020002
MAGIC = 0x504C

#: RootStringCheckSum for an empty root string: the XOR key itself.
_ROOT_STRING_CHECKSUM = 0x50475342
_WINDOWS_1252 = 1252


def _utf16le(value: str) -> bytes:
    """UTF-16LE of a string's code points, one unit per BMP code point
    (unpaired surrogates included, as PHP ``Utf16::utf8ToLe`` writes them) and
    a surrogate pair above the BMP."""
    out = bytearray()
    for ch in value:
        cp = ord(ch)
        if cp >= 0x10000:
            cp -= 0x10000
            out += struct.pack("<HH", 0xD800 | (cp >> 10), 0xDC00 | (cp & 0x3FF))
        else:
            out += struct.pack("<H", cp)
    return bytes(out)


def _name(value: str) -> bytes:
    utf16 = _utf16le(value + "\0")
    return struct.pack("<HH", 0, len(utf16)) + utf16


def wrap(font: TrueTypeFont, family: str) -> bytes:
    u1, u2, u3, u4 = font.unicode_ranges()
    c1, c2 = font.code_page_ranges()
    style = font.name(2)
    version = font.name(5)
    full = font.name(4)

    body = (
        font.panose()
        + struct.pack("<BB", 1, 1 if font.is_italic() else 0)
        + struct.pack("<I", font.weight())
        + struct.pack("<HH", font.fs_type(), MAGIC)
        + struct.pack("<IIII", u1, u2, u3, u4)
        + struct.pack("<II", c1, c2)
        + struct.pack("<I", font.check_sum_adjustment())
        + struct.pack("<IIII", 0, 0, 0, 0)
        + _name(family)
        + _name(style if style is not None else "Regular")
        + _name(version if version is not None else "")
        + _name(full if full is not None else family)
        + struct.pack("<HH", 0, 0)
        + struct.pack("<II", _ROOT_STRING_CHECKSUM, _WINDOWS_1252)
        + struct.pack("<HH", 0, 0)
        + struct.pack("<II", 0, 0)
    )

    header_length = 16 + len(body)
    data_length = len(font.bytes)

    return struct.pack("<IIII", header_length + data_length, data_length, VERSION, 0) + body + font.bytes

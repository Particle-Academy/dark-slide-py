"""A minimal, valid TrueType font built in memory, for tests.

Ported from PHP ``tests/Support/GeneratedFont.php``, byte for byte, so both
engines' embedding tests (and the parity suite) run on the same font bytes.

Embedding tests need real font files, and a third-party font is not something
this repository takes on. So the test writes its own: ten tables (OS/2, cmap,
glyf, head, hhea, hmtx, loca, maxp, name, post), an empty ``.notdef``, and one
tall box glyph for every printable ASCII character. Text set in it renders as a
row of boxes, which is unmistakable next to any fallback face.
"""

from __future__ import annotations

import math
import struct

__all__ = ["build", "with_tag"]


def _s16(*values: int) -> bytes:
    return b"".join(struct.pack(">H", v & 0xFFFF) for v in values)


def _checksum(data: bytes) -> int:
    data += b"\0" * ((4 - len(data) % 4) % 4)
    total = 0
    for (word,) in struct.iter_unpack(">I", data):
        total = (total + word) & 0xFFFFFFFF
    return total


def _box_glyph(x0: int, y0: int, x1: int, y1: int) -> bytes:
    points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
    glyph = _s16(1, x0, y0, x1, y1) + struct.pack(">HH", 3, 0) + b"\x01" * 4
    xs = b""
    ys = b""
    px, py = 0, 0
    for x, y in points:
        xs += _s16(x - px)
        ys += _s16(y - py)
        px, py = x, y
    glyph += xs + ys
    return glyph + b"\0" * ((4 - len(glyph) % 4) % 4)


def _assemble(tables: dict[bytes, bytes]) -> bytes:
    tags = sorted(tables)
    count = len(tags)
    selector = int(math.floor(math.log2(count)))
    search_range = (2 ** selector) * 16

    directory = struct.pack(">IHHHH", 0x00010000, count, search_range, selector, count * 16 - search_range)
    body = b""
    offset = 12 + 16 * count
    head_offset = 0
    for tag in tags:
        data = tables[tag]
        if tag == b"head":
            head_offset = offset + len(body)
        directory += tag + struct.pack(">III", _checksum(data), offset + len(body), len(data))
        body += data + b"\0" * ((4 - len(data) % 4) % 4)

    font = bytearray(directory + body)
    adjustment = (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF
    font[head_offset + 8:head_offset + 12] = struct.pack(">I", adjustment)
    return bytes(font)


def build(family: str, style: str = "Regular", fs_type: int = 0, weight: int = 400, italic: bool = False) -> bytes:
    first_char, last_char = 0x20, 0x7E
    glyphs = 1 + (last_char - first_char + 1)

    box = _box_glyph(100, 0, 500, 700)
    glyf = b""
    offsets = [0, 0]  # .notdef is empty
    for _ in range(first_char, last_char + 1):
        glyf += box
        offsets.append(len(glyf))
    loca = b"".join(struct.pack(">I", o) for o in offsets)

    head = (
        struct.pack(">IIII", 0x00010000, 0x00010000, 0, 0x5F0F3CF5)
        + struct.pack(">HH", 0x000B, 1000)
        + struct.pack(">qq", 0, 0)
        + _s16(0, 0, 600, 800)
        + struct.pack(">HH", 2 if italic else (1 if weight >= 600 else 0), 8)
        + _s16(2, 1, 0)
    )

    hhea = (
        struct.pack(">I", 0x00010000)
        + _s16(800, -200, 0)
        + struct.pack(">H", 600)
        + _s16(0, 0, 500, 1, 0, 0, 0, 0, 0, 0, 0)
        + struct.pack(">H", glyphs)
    )

    maxp = struct.pack(">IHHHHHHHHHHHHHH", 0x00010000, glyphs, 4, 1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0)

    hmtx = b"".join(struct.pack(">H", 600) + _s16(0 if i == 0 else 100) for i in range(glyphs))

    # cmap format 4: one segment mapping U+0020..U+007E to glyphs 1.., and the
    # mandatory 0xFFFF terminator.
    seg_count = 2
    search_range = 2 * (2 ** int(math.floor(math.log2(seg_count))))
    subtable = (
        struct.pack(">HHH", 4, 16 + 8 * seg_count, 0)
        + struct.pack(">HHHH", seg_count * 2, search_range, int(math.log2(search_range / 2)), seg_count * 2 - search_range)
        + struct.pack(">HH", last_char, 0xFFFF) + struct.pack(">H", 0)
        + struct.pack(">HH", first_char, 0xFFFF)
        + struct.pack(">HH", (1 - first_char) & 0xFFFF, 1)
        + struct.pack(">HH", 0, 0)
    )
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + subtable

    names = {
        1: family,
        2: style,
        3: f"{family} {style}",
        4: f"{family} {style}",
        5: "Version 1.000",
        6: family.replace(" ", "") + "-" + style.replace(" ", ""),
    }
    records = b""
    strings = b""
    for name_id, value in names.items():
        utf16 = b"".join(b"\0" + c.encode("ascii") for c in value)
        records += struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(utf16), len(strings))
        strings += utf16
    name = struct.pack(">HHH", 0, len(names), 6 + 12 * len(names)) + records + strings

    fs_selection = (0x01 if italic else 0) | (0x20 if weight >= 600 else 0) | (0x40 if not italic and weight < 600 else 0)
    os2 = (
        struct.pack(">H", 4) + _s16(600) + struct.pack(">HHH", weight, 5, fs_type)
        + _s16(300, 300, 0, 0, 300, 300, 0, 300, 50, 300, 0)
        + b"\0" * 10  # PANOSE
        + struct.pack(">IIII", 1, 0, 0, 0)  # ulUnicodeRange1..4 (Basic Latin)
        + b"NONE"
        + struct.pack(">HHH", fs_selection, first_char, last_char)
        + _s16(800, -200, 0) + struct.pack(">HH", 800, 200)
        + struct.pack(">II", 1, 0)  # ulCodePageRange1..2 (Latin 1)
        + _s16(500, 700) + struct.pack(">HHH", 0, 0x20, 0)
    )

    post = struct.pack(">II", 0x00030000, 0) + _s16(-100, 50) + struct.pack(">IIIII", 0, 0, 0, 0, 0)

    return _assemble({
        b"OS/2": os2, b"cmap": cmap, b"glyf": glyf, b"head": head, b"hhea": hhea,
        b"hmtx": hmtx, b"loca": loca, b"maxp": maxp, b"name": name, b"post": post,
    })


def with_tag(font: bytes, tag: bytes) -> bytes:
    """The same font with its sfnt tag replaced, to stand in for a CFF ``.otf`` or a ``.ttc``."""
    return tag + font[4:]

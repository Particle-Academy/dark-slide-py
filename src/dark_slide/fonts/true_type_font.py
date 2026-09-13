"""The handful of TrueType fields that embedding a font in a ``.pptx`` needs.

Mirrors PHP ``Fonts\\TrueTypeFont``, message for message.

Not a font parser in any wider sense: it reads the table directory, the OS/2
fields the Embedded OpenType header copies, ``head.checkSumAdjustment``, and the
name records. Nothing is subset, hinted or rewritten; the font bytes go into the
file exactly as supplied.

Refuses, rather than guesses at, anything it cannot embed safely: a font
collection (``ttcf``), CFF-outline OpenType (``OTTO``, whose PowerPoint
acceptance is unverified), and a file missing a table the header needs.
"""

from __future__ import annotations

from ..exceptions import FontEmbeddingException

__all__ = ["TrueTypeFont"]


def _u16(b: bytes, o: int) -> int:
    return (b[o] << 8) | b[o + 1]


def _u32(b: bytes, o: int) -> int:
    return (b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]


def _be_to_text(raw: bytes) -> str:
    """UTF-16BE to text, exactly as PHP ``Fonts\\Utf16::beToUtf8`` decodes it.

    A trailing odd byte is dropped, a valid surrogate pair is combined, and an
    unpaired surrogate is kept as its own code point rather than raising. The
    same code points then encode back to the same UTF-16LE units in the EOT
    header, so the two engines write identical bytes even for a malformed name.
    """
    out: list[str] = []
    length = len(raw) - (len(raw) % 2)
    i = 0
    while i < length:
        unit = (raw[i] << 8) | raw[i + 1]
        if 0xD800 <= unit <= 0xDBFF and i + 3 < length:
            low = (raw[i + 2] << 8) | raw[i + 3]
            if 0xDC00 <= low <= 0xDFFF:
                unit = 0x10000 + ((unit - 0xD800) << 10) + (low - 0xDC00)
                i += 2
        out.append(chr(unit))
        i += 2
    return "".join(out)


class TrueTypeFont:
    """A validated TrueType font and the fields read from it."""

    def __init__(self, data: bytes, tables: dict[bytes, tuple[int, int]]) -> None:
        self.bytes = data
        self._tables = tables

    @classmethod
    def from_bytes(cls, data: bytes) -> TrueTypeFont:
        if len(data) < 12:
            raise FontEmbeddingException("not a font file: shorter than a table directory")

        tag = data[0:4]
        if tag == b"ttcf":
            raise FontEmbeddingException(
                "a font collection (.ttc) holds several fonts; supply the single font file"
            )
        if tag == b"OTTO":
            raise FontEmbeddingException(
                "CFF-outline OpenType (.otf) is not embedded yet; supply the TrueType-outline (.ttf) build of the font"
            )
        if tag not in (b"\x00\x01\x00\x00", b"true"):
            raise FontEmbeddingException("not a TrueType font file")

        count = _u16(data, 4)
        if len(data) < 12 + 16 * count:
            raise FontEmbeddingException("not a font file: the table directory is truncated")

        tables: dict[bytes, tuple[int, int]] = {}
        for i in range(count):
            record = 12 + 16 * i
            offset = _u32(data, record + 8)
            length = _u32(data, record + 12)
            if offset + length > len(data):
                raise FontEmbeddingException("not a font file: a table runs past the end of the file")
            tables[data[record:record + 4]] = (offset, length)

        for required in (b"OS/2", b"head", b"name", b"glyf"):
            if required not in tables:
                raise FontEmbeddingException(
                    f"not an embeddable TrueType font: it has no '{required.decode('ascii')}' table"
                )
        if tables[b"OS/2"][1] < 78 or tables[b"head"][1] < 12:
            raise FontEmbeddingException(
                "not an embeddable TrueType font: its OS/2 or head table is too short"
            )

        return cls(data, tables)

    def fs_type(self) -> int:
        """OS/2 ``fsType``: the embedding permissions the font's licence grants."""
        return _u16(self.bytes, self._tables[b"OS/2"][0] + 8)

    def weight(self) -> int:
        return _u16(self.bytes, self._tables[b"OS/2"][0] + 4)

    def is_italic(self) -> bool:
        return (_u16(self.bytes, self._tables[b"OS/2"][0] + 62) & 1) == 1

    def panose(self) -> bytes:
        """The ten PANOSE classification bytes."""
        o = self._tables[b"OS/2"][0] + 32
        return self.bytes[o:o + 10]

    def unicode_ranges(self) -> list[int]:
        """``ulUnicodeRange1..4``."""
        o = self._tables[b"OS/2"][0] + 42
        return [_u32(self.bytes, o), _u32(self.bytes, o + 4), _u32(self.bytes, o + 8), _u32(self.bytes, o + 12)]

    def code_page_ranges(self) -> list[int]:
        """``ulCodePageRange1..2``, which only OS/2 version 1 and later carry."""
        o, length = self._tables[b"OS/2"]
        if _u16(self.bytes, o) < 1 or length < 86:
            return [0, 0]
        return [_u32(self.bytes, o + 78), _u32(self.bytes, o + 82)]

    def check_sum_adjustment(self) -> int:
        return _u32(self.bytes, self._tables[b"head"][0] + 8)

    def name(self, name_id: int) -> str | None:
        """A name record's text: Windows Unicode (3, 1) US English first, then any
        Windows Unicode record, then a Macintosh Roman (1, 0) record that is plain
        ASCII (the only range Mac Roman shares with UTF-8)."""
        table = self._tables[b"name"][0]
        count = _u16(self.bytes, table + 2)
        storage = table + _u16(self.bytes, table + 4)

        best: str | None = None
        best_rank = 1 << 62
        for i in range(count):
            r = table + 6 + 12 * i
            if _u16(self.bytes, r + 6) != name_id:
                continue
            platform = _u16(self.bytes, r)
            encoding = _u16(self.bytes, r + 2)
            language = _u16(self.bytes, r + 4)
            start = storage + _u16(self.bytes, r + 10)
            raw = self.bytes[start:start + _u16(self.bytes, r + 8)]

            if platform == 3 and encoding == 1:
                rank, text = (0 if language == 0x409 else 1), _be_to_text(raw)
            elif platform == 1 and encoding == 0 and all(byte <= 0x7F for byte in raw):
                rank, text = 2, raw.decode("ascii")
            else:
                continue
            if rank < best_rank:
                best = text
                best_rank = rank

        return best

    def family(self) -> str | None:
        """The family a deck would reference: the typographic family (16) when
        set, else the legacy one (1)."""
        typographic = self.name(16)
        return typographic if typographic is not None else self.name(1)

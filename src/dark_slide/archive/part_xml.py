"""The one way an XML part of an uploaded file gets parsed.

A part carrying a DOCTYPE is refused, because no presentation part has one and an
internal subset is the entry point for entity expansion. The check has two
halves. The prolog is read first, so an ordinary refusal never reaches the
parser; it looks only at the prolog, because searching the whole part would
refuse a real run whose CDATA holds an HTML page. The parser then reports any
doctype it meets, and that report is what decides: no byte scan reads every
encoding, and the parse stops there, before the subset is processed. A part whose
encoding the parser cannot read is refused too.

Parts go in as BYTES. Decoding first would discard the encoding the part declares.
"""

from __future__ import annotations

from xml.etree import ElementTree

_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
_DOCTYPE_REFUSED = "[dark-slide] refusing to parse XML containing a DOCTYPE declaration."


class XmlError(ValueError):
    """Raised when a part cannot be parsed, or refuses to be parsed."""


class XmlRefused(XmlError):
    """The part carries a DOCTYPE, or an encoding the parser cannot read.

    A malformed part is only an `XmlError`. Most callers treat the two alike;
    the package declaration is the one place the difference decides anything.
    """


class _DoctypeMet(Exception):
    pass


class _RefusingBuilder(ElementTree.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise _DoctypeMet


def prolog_declares_doctype(raw: bytes) -> bool:
    """Whether a DOCTYPE comes before the root element, for the encodings a byte
    walk can read: anything ASCII-compatible, and UTF-16 or UTF-32 once their
    NUL bytes are dropped (which keeps the ASCII this looks for)."""
    if b"\0" in raw[:4]:
        raw = raw.replace(b"\0", b"")
    at = 0
    for bom in _BOMS:
        if raw.startswith(bom):
            at = len(bom)
            break
    while True:
        while at < len(raw) and raw[at] in b" \t\r\n":
            at += 1
        if raw.startswith(b"<?", at):
            close = b"?>"
        elif raw.startswith(b"<!--", at):
            close = b"-->"
        else:
            return raw[at : at + 9].lower() == b"<!doctype"
        end = raw.find(close, at)
        if end == -1:
            return False
        at = end + len(close)


def parse_xml(raw: bytes) -> ElementTree.Element:
    if prolog_declares_doctype(raw):
        raise XmlRefused(_DOCTYPE_REFUSED)
    parser = ElementTree.XMLParser(target=_RefusingBuilder())
    try:
        parser.feed(raw)
        return parser.close()
    except _DoctypeMet:
        raise XmlRefused(_DOCTYPE_REFUSED) from None
    except ElementTree.ParseError as error:
        raise XmlError(f"[dark-slide] malformed XML: {error}") from error
    except (ValueError, LookupError) as error:
        # The parser hands a declared encoding it cannot read straight up as one
        # of these, and it says nothing about what the part holds.
        raise XmlRefused(f"[dark-slide] unreadable XML encoding: {error}") from error


def parse_xml_or_none(raw: bytes | None) -> ElementTree.Element | None:
    """Parse, or None when the part is absent, malformed or refused."""
    if raw is None:
        return None
    try:
        return parse_xml(raw)
    except XmlError:
        return None


def is_refused(raw: bytes) -> bool:
    """Whether a part is refused, as opposed to merely malformed or fine."""
    try:
        parse_xml(raw)
    except XmlRefused:
        return True
    except XmlError:
        return False
    return False

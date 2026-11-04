"""The gate itself. Mirrors the PHP suite's PartXmlTest."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from dark_slide.archive.part_xml import XmlError, XmlRefused, is_refused, parse_xml, parse_xml_or_none, prolog_declares_doctype

DOCTYPE = '<!DOCTYPE r [<!ENTITY x "HSINT">]>'


def _id(xml: bytes) -> str:
    return f"{len(xml)}-{xml[:12].hex()}"


@pytest.mark.parametrize(
    "xml",
    [
        DOCTYPE.encode() + b"<r/>",
        b'<?xml version="1.0"?>' + DOCTYPE.encode() + b"<r/>",
        b'<?xml version="1.0"?>\n <!-- c -->\n' + DOCTYPE.encode() + b"<r/>",
        b"\xef\xbb\xbf" + DOCTYPE.encode() + b"<r/>",
        b"<!-- " + b"p" * 100000 + b" -->" + DOCTYPE.encode() + b"<r/>",
        b"<?pi a?>" + DOCTYPE.encode() + b"<r/>",
        b"\xff\xfe" + ('<?xml version="1.0" encoding="UTF-16"?>' + DOCTYPE + "<r/>").encode("utf-16-le"),
        b"\xfe\xff" + ('<?xml version="1.0" encoding="UTF-16"?>' + DOCTYPE + "<r/>").encode("utf-16-be"),
        ('<?xml version="1.0" encoding="UTF-16"?>' + DOCTYPE + "<r/>").encode("utf-16-le"),
        ('<?xml version="1.0" encoding="UTF-16"?>' + DOCTYPE + "<r/>").encode("utf-16-be"),
    ],
    ids=_id,
)
def test_the_prolog_check_finds_a_doctype_before_the_root(xml: bytes) -> None:
    assert prolog_declares_doctype(xml)


@pytest.mark.parametrize(
    "xml",
    [
        b"",
        b"<r/>",
        b"<r><![CDATA[<!DOCTYPE html>]]></r>",
        b"<!-- <!DOCTYPE x> --><r/>",
        b"<?pi <!DOCTYPE x>?><r/>",
        b"<!-- " + DOCTYPE.encode(),
        b"<?xml " + DOCTYPE.encode(),
    ],
    ids=_id,
)
def test_the_prolog_check_finds_none_where_there_is_none(xml: bytes) -> None:
    assert not prolog_declares_doctype(xml)


def test_the_parser_refuses_a_doctype_the_prolog_check_cannot_read() -> None:
    # A comment in UTF-16 can hold a code unit that reads as the end of a comment
    # once NULs are dropped, so the byte walk stops early. The parser does not.
    misleading = "<!-- ⴭ> x -->" + DOCTYPE + "<r>&x;</r>"
    raw = b"\xff\xfe" + misleading.encode("utf-16-le")
    assert ElementTree.fromstring(raw).text == "HSINT"
    assert not prolog_declares_doctype(raw)
    with pytest.raises(XmlRefused, match="DOCTYPE"):
        parse_xml(raw)


def test_a_clean_part_returns_what_the_primitive_returns() -> None:
    root = parse_xml(b'<?xml version="1.0"?><r a="1"><b>t</b></r>')
    assert root.attrib == {"a": "1"}
    assert root[0].text == "t"


def test_malformed_is_an_error_but_not_a_refusal() -> None:
    with pytest.raises(XmlError) as caught:
        parse_xml(b"<r>")
    assert not isinstance(caught.value, XmlRefused)
    assert parse_xml_or_none(b"<r>") is None
    assert not is_refused(b"<r>")


def test_a_truncated_doctype_is_a_refusal() -> None:
    assert is_refused(b'<?xml version="1.0"?><!DOCTYPE r')


@pytest.mark.parametrize("encoding", ["UTF-7", "Shift_JIS", "zlib", "undefined", "no-such-encoding"])
def test_an_unreadable_encoding_is_refused_rather_than_escaping_the_gate(encoding: str) -> None:
    raw = f'<?xml version="1.0" encoding="{encoding}"?><r/>'.encode()
    with pytest.raises(XmlError):
        parse_xml(raw)
    assert parse_xml_or_none(raw) is None


def test_absent_is_none() -> None:
    assert parse_xml_or_none(None) is None

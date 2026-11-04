"""Every XML part of an uploaded deck is read through one gate, which refuses a
DOCTYPE. Mirrors PHP tests/Unit/DoctypeRefusalTest.php.

Everything goes through the public reader, because what matters is what a hostile
upload gets back. MARKER is the visible text of each part in a clean file and
ENTITY the value its replacement declares, so ENTITY in the result means it
expanded.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree
from xml.parsers import expat

import pytest

import dark_slide
from dark_slide.exceptions import ArchiveRefused, OfficeTemplateRefused

MARKER = "HSBASE"
ENTITY = "HSINT"
DOCTYPE = f'<!DOCTYPE r [<!ENTITY x "{ENTITY}">]>'.encode()
MAIN = b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
MACRO_TEMPLATE = b"application/vnd.ms-powerpoint.template.macroEnabled.main+xml"


def zip_of(parts: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return out.getvalue()


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def pptx_parts() -> dict[str, bytes]:
    """A real package from the real writer, one marker in each part this file proves."""
    return unzip(
        dark_slide.to_bytes(
            {
                "id": "d",
                "title": MARKER,
                "theme": {"name": "default", "fonts": {"heading": MARKER}},
                "slides": [
                    {
                        "id": "s1",
                        "layout": "blank",
                        "notes": MARKER,
                        "elements": [
                            {"id": "t1", "type": "text", "content": MARKER, "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.1},
                            {
                                "id": "c1",
                                "type": "chart",
                                "x": 0.1,
                                "y": 0.3,
                                "w": 0.5,
                                "h": 0.5,
                                "option": {
                                    "title": {"text": MARKER},
                                    "xAxis": {"type": "category", "data": ["a"]},
                                    "yAxis": {"type": "value"},
                                    "series": [{"type": "bar", "name": "n", "data": [1]}],
                                },
                            },
                        ],
                    }
                ],
            }
        )
    )


def with_doctype(xml: bytes, doctype: bytes = DOCTYPE) -> bytes:
    match = re.match(rb"^<\?xml[^>]*\?>\s*", xml)
    if match:
        return match.group(0) + doctype + xml[match.end() :]
    return doctype + xml


def declared(xml: bytes, encoding: str) -> str:
    return re.sub(rb"^<\?xml[^>]*\?>", f'<?xml version="1.0" encoding="{encoding}"?>'.encode(), xml).decode("utf-8")


ENCODINGS: dict[str, Callable[[bytes], bytes]] = {
    "plain UTF-8": lambda x: x,
    "UTF-8 with a BOM": lambda x: b"\xef\xbb\xbf" + x,
    "UTF-16LE with a BOM": lambda x: b"\xff\xfe" + declared(x, "UTF-16").encode("utf-16-le"),
    "UTF-16BE with a BOM": lambda x: b"\xfe\xff" + declared(x, "UTF-16").encode("utf-16-be"),
    "UTF-16LE without a BOM": lambda x: declared(x, "UTF-16").encode("utf-16-le"),
    "past a long comment": lambda x: re.sub(rb"^(<\?xml[^>]*\?>\s*)", rb"\1<!-- " + b"p" * 5000 + b" -->", x, count=1),
}

MARKER_PARTS = [
    "docProps/core.xml",
    "ppt/theme/theme1.xml",
    "ppt/slides/slide1.xml",
    "ppt/notesSlides/notesSlide1.xml",
    "ppt/charts/chart1.xml",
]


def referencing(parts: dict[str, bytes], part: str) -> bytes:
    return parts[part].replace(MARKER.encode(), b"&x;")


def read_text(parts: dict[str, bytes]) -> str:
    try:
        return json.dumps(dark_slide.read(zip_of(parts)))
    except (ValueError, RuntimeError):
        return "(refused)"


def four_by_three(parts: dict[str, bytes]) -> dict[str, bytes]:
    """The deck with its slide size changed, so the size in the result proves the part was read."""
    out = dict(parts)
    out["ppt/presentation.xml"], changed = re.subn(rb'(<p:sldSz\b[^>]*\bcy=")\d+', rb"\g<1>9144000", parts["ppt/presentation.xml"], count=1)
    assert changed == 1
    return out


def test_reads_every_marker_from_a_clean_deck() -> None:
    assert read_text(pptx_parts()).count(MARKER) == 5


@pytest.mark.parametrize("encoding", list(ENCODINGS))
def test_the_fixture_entity_is_live_in_each_encoding(encoding: str) -> None:
    raw = ENCODINGS[encoding](with_doctype(b'<?xml version="1.0" encoding="UTF-8"?><r>&x;</r>'))
    assert ElementTree.fromstring(raw).text == ENTITY


@pytest.mark.parametrize("encoding", list(ENCODINGS))
@pytest.mark.parametrize("part", MARKER_PARTS)
def test_does_not_expand_an_internal_entity_from_any_part(part: str, encoding: str) -> None:
    parts = pptx_parts()
    parts[part] = ENCODINGS[encoding](with_doctype(referencing(parts, part)))
    assert ENTITY not in read_text(parts)


@pytest.mark.parametrize("encoding", list(ENCODINGS))
@pytest.mark.parametrize("part", MARKER_PARTS)
def test_still_reads_each_encoding_without_a_doctype(part: str, encoding: str) -> None:
    parts = pptx_parts()
    clean = read_text(parts)
    parts[part] = ENCODINGS[encoding](parts[part])
    assert read_text(parts) == clean


@pytest.mark.parametrize(
    ("part", "target", "probe"),
    [
        ("ppt/_rels/presentation.xml.rels", b"slides/slide1.xml", '"t1"'),
        ("ppt/slides/_rels/slide1.xml.rels", b"../notesSlides/notesSlide1.xml", '"notes"'),
        ("ppt/slides/_rels/slide1.xml.rels", b"../charts/chart1.xml", '"c1"'),
    ],
)
def test_does_not_follow_a_relationship_whose_target_comes_from_an_entity(part: str, target: bytes, probe: str) -> None:
    parts = pptx_parts()
    assert target in parts[part]
    parts[part] = with_doctype(parts[part].replace(target, b"&x;"), b'<!DOCTYPE r [<!ENTITY x "' + target + b'">]>')
    assert probe not in read_text(parts)


# ─── What a consumer sees, per part: the same table as PHP ────────────────────


def test_falls_back_to_the_default_title_for_a_refused_core_part() -> None:
    parts = pptx_parts()
    parts["docProps/core.xml"] = with_doctype(parts["docProps/core.xml"])
    assert dark_slide.read(zip_of(parts))["title"] == "Imported"


def test_keeps_the_slide_with_no_elements_for_a_refused_slide_part() -> None:
    parts = pptx_parts()
    parts["ppt/slides/slide1.xml"] = with_doctype(parts["ppt/slides/slide1.xml"])
    slide = dark_slide.read(zip_of(parts))["slides"][0]
    assert slide["id"] == "imported-slide-1"
    assert slide["elements"] == []


def test_reads_no_slides_for_refused_presentation_relationships() -> None:
    parts = pptx_parts()
    parts["ppt/_rels/presentation.xml.rels"] = with_doctype(parts["ppt/_rels/presentation.xml.rels"])
    assert dark_slide.read(zip_of(parts))["slides"] == []


def test_reads_the_rest_of_the_deck_without_a_refused_notes_part() -> None:
    parts = pptx_parts()
    parts["ppt/notesSlides/notesSlide1.xml"] = with_doctype(parts["ppt/notesSlides/notesSlide1.xml"])
    slide = dark_slide.read(zip_of(parts))["slides"][0]
    assert "notes" not in slide
    assert len(slide["elements"]) == 2


def test_drops_a_chart_whose_part_is_refused_and_keeps_the_other_elements() -> None:
    parts = pptx_parts()
    parts["ppt/charts/chart1.xml"] = with_doctype(parts["ppt/charts/chart1.xml"])
    elements = dark_slide.read(zip_of(parts))["slides"][0]["elements"]
    assert "chart" not in [e["type"] for e in elements]
    assert "t1" in [e["id"] for e in elements]


def test_reads_a_slide_size_from_a_clean_presentation_part() -> None:
    assert "aspectRatio" in dark_slide.read(zip_of(four_by_three(pptx_parts())))["theme"]


def test_takes_nothing_from_a_refused_presentation_part() -> None:
    parts = four_by_three(pptx_parts())
    parts["ppt/presentation.xml"] = with_doctype(parts["ppt/presentation.xml"])
    assert "aspectRatio" not in dark_slide.read(zip_of(parts))["theme"]


def test_takes_no_mono_font_from_a_refused_theme() -> None:
    parts = unzip(
        dark_slide.to_bytes(
            {
                "id": "d",
                "title": "t",
                "theme": {"name": "default", "fonts": {"mono": "HSFACE"}},
                "slides": [
                    {
                        "id": "s1",
                        "layout": "blank",
                        "elements": [{"id": "k1", "type": "code", "language": "text", "code": "x", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.3}],
                    }
                ],
            }
        )
    )
    clean = dark_slide.read(zip_of(parts))
    bare = {k: v for k, v in parts.items() if k != "ppt/theme/theme1.xml"}
    absent = dark_slide.read(zip_of(bare))
    parts["ppt/theme/theme1.xml"] = with_doctype(parts["ppt/theme/theme1.xml"])
    # A run in the recorded mono face reads as code, so the face changes the slide.
    assert clean["slides"] != absent["slides"]
    assert dark_slide.read(zip_of(parts))["slides"] == absent["slides"]


# ─── The package declaration ──────────────────────────────────────────────────


def macro_template() -> dict[str, bytes]:
    parts = pptx_parts()
    assert MAIN in parts["[Content_Types].xml"]
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(MAIN, MACRO_TEMPLATE)
    return parts


def assert_refused(parts: dict[str, bytes]) -> None:
    with pytest.raises(ArchiveRefused) as caught:
        dark_slide.read(zip_of(parts))
    assert caught.value.reason == "archive_unsupported"


def test_refuses_a_macro_template_for_its_declaration() -> None:
    with pytest.raises(OfficeTemplateRefused, match="macro_enabled"):
        dark_slide.read(zip_of(macro_template()))


@pytest.mark.parametrize("encoding", list(ENCODINGS))
def test_reads_a_clean_declaration_in_every_encoding(encoding: str) -> None:
    parts = pptx_parts()
    clean = read_text(parts)
    parts["[Content_Types].xml"] = ENCODINGS[encoding](parts["[Content_Types].xml"])
    assert read_text(parts) == clean


@pytest.mark.parametrize("encoding", list(ENCODINGS))
def test_still_refuses_the_macro_template_when_its_declaration_carries_a_doctype(encoding: str) -> None:
    parts = macro_template()
    parts["[Content_Types].xml"] = ENCODINGS[encoding](with_doctype(parts["[Content_Types].xml"]))
    assert_refused(parts)


@pytest.mark.parametrize("encoding", list(ENCODINGS))
def test_refuses_a_plain_deck_whose_declaration_carries_a_doctype(encoding: str) -> None:
    parts = pptx_parts()
    parts["[Content_Types].xml"] = ENCODINGS[encoding](with_doctype(parts["[Content_Types].xml"]))
    assert_refused(parts)


def test_refuses_a_declaration_the_parser_cannot_read_and_so_cannot_vouch_for() -> None:
    parts = pptx_parts()
    parts["[Content_Types].xml"] = (
        b'<?xml version="1.0" encoding="UTF-7"?>'
        b"+ADw-+ACE-DOCTYPE r +AFs-+ADw-+ACE-ENTITY x +ACI-HSINT+ACI-+AD4-+AF0-+AD4-"
        b"+ADw-Types/+AD4-"
    )
    assert_refused(parts)


def test_refuses_the_conversion_too() -> None:
    parts = pptx_parts()
    parts["[Content_Types].xml"] = with_doctype(parts["[Content_Types].xml"])
    with pytest.raises(ArchiveRefused):
        dark_slide.convert_template(zip_of(parts))


def test_leaves_a_malformed_declaration_handled_as_it_always_was() -> None:
    parts = pptx_parts()
    clean = read_text(parts)
    parts["[Content_Types].xml"] = b"<Types>"
    assert read_text(parts) == clean


def test_does_not_refuse_a_declaration_for_text_that_only_looks_like_a_doctype() -> None:
    parts = pptx_parts()
    clean = read_text(parts)
    parts["[Content_Types].xml"] = with_doctype(parts["[Content_Types].xml"], b"<!-- <!DOCTYPE x> -->").replace(
        b"</Types>", b"<!-- <!DOCTYPE x> --></Types>"
    )
    assert read_text(parts) == clean


# ─── External entities ────────────────────────────────────────────────────────


@pytest.fixture
def canary(tmp_path: Path) -> str:
    target = tmp_path / "canary.txt"
    target.write_text("HSCANARY", encoding="ascii")
    return target.resolve().as_uri()


def test_a_permissive_parser_can_reach_the_canary_so_no_leak_below_means_something(canary: str) -> None:
    loads: list[str] = []
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_ALWAYS)

    def load(context: str, base: str | None, system: str, public: str | None) -> int:
        loads.append(system)
        return 1

    parser.ExternalEntityRefHandler = load
    parser.Parse(f'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "{canary}">]><r>&x;</r>', True)
    assert loads == [canary]


@pytest.mark.parametrize("part", MARKER_PARTS)
def test_does_not_leak_a_file_entity(part: str, canary: str) -> None:
    parts = pptx_parts()
    parts[part] = with_doctype(referencing(parts, part), f'<!DOCTYPE r [<!ENTITY x SYSTEM "{canary}">]>'.encode())
    assert "HSCANARY" not in read_text(parts)


# ─── Text that only looks like a DOCTYPE ──────────────────────────────────────


def test_keeps_a_slide_written_as_cdata() -> None:
    parts = pptx_parts()
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(MARKER.encode(), b"<![CDATA[<!DOCTYPE html>]]>")
    assert "<!DOCTYPE html>" in read_text(parts)


def test_keeps_a_chart_title_written_as_cdata() -> None:
    parts = pptx_parts()
    parts["ppt/charts/chart1.xml"] = parts["ppt/charts/chart1.xml"].replace(MARKER.encode(), b"<![CDATA[<!DOCTYPE html>]]>")
    elements = dark_slide.read(zip_of(parts))["slides"][0]["elements"]
    assert elements[1]["option"]["title"]["text"] == "<!DOCTYPE html>"


def test_does_not_stop_a_part_being_read_from_a_comment() -> None:
    parts = pptx_parts()
    parts["ppt/slides/slide1.xml"] = with_doctype(parts["ppt/slides/slide1.xml"], b"<!-- <!DOCTYPE x> -->")
    assert '"t1"' in read_text(parts)


def test_a_part_in_an_unreadable_encoding_reads_as_absent_instead_of_raising() -> None:
    parts = pptx_parts()
    parts["ppt/slides/slide1.xml"] = b'<?xml version="1.0" encoding="Shift_JIS"?><p:sld/>'
    assert dark_slide.read(zip_of(parts))["slides"][0]["elements"] == []


# ─── Nothing else parses ──────────────────────────────────────────────────────


def test_leaves_no_way_to_a_part_except_through_the_gate() -> None:
    root = Path(dark_slide.__file__).resolve().parent
    pattern = re.compile(r"\b(?:fromstring|iterparse|XMLParser|XMLPullParser)\(|\.parse\([^)]*\.xml|xml\.parsers|xml\.sax|minidom|pulldom|\blxml\b")
    gate = root / "archive" / "part_xml.py"
    offenders = [path.name for path in root.rglob("*.py") if path != gate and pattern.search(path.read_text(encoding="utf-8"))]
    assert offenders == []
    assert pattern.search(gate.read_text(encoding="utf-8"))

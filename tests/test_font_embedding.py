"""Embedding the host's fonts, so brand typography survives a machine without them.

Ported from PHP ``tests/Unit/FontEmbeddingTest.php``. Until this, a theme naming
"Bebas Neue" was a request: anywhere the face was not installed, the viewer
substituted another, which also changed how wide every line was.

Pinned here: no font means no byte changes; the package shape PowerPoint's
schema requires and LibreOffice's export uses; the EOT header field by field;
refusal, all at once and before anything is written. The rendered proof needs
LibreOffice and runs when DARK_SLIDE_RENDER=1. Byte parity with the PHP engine
for an embedding deck lives in ``test_parity_php.py``.
"""

from __future__ import annotations

import io
import os
import pathlib
import secrets
import struct
import subprocess
import tempfile
import zipfile
from typing import Any

import pytest

import dark_slide
from dark_slide import FontEmbeddingException
from tests import generated_font as GeneratedFont


def _deck() -> dict[str, Any]:
    return {
        "id": "fonts",
        "title": "Embedded fonts",
        "theme": {"name": "probe", "fonts": {"heading": "Qvx Display", "body": "Qvx Text"}},
        "slides": [{
            "id": "s1",
            "layout": "blank",
            "elements": [{
                "id": "t", "type": "text", "x": 0.1, "y": 0.3, "w": 0.8, "h": 0.3,
                "content": "EMBEDDED FACE", "style": {"fontSize": 96, "fontFamily": "Qvx Display"},
            }],
        }],
    }


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _fonts_option() -> dict[str, Any]:
    return {
        "Qvx Display": {
            "regular": GeneratedFont.build("Qvx Display"),
            "bold": GeneratedFont.build("Qvx Display", "Bold", weight=700),
        },
        "Qvx Text": {"regular": GeneratedFont.build("Qvx Text")},
    }


def test_nothing_changes_when_no_font_is_supplied() -> None:
    parts = _parts(dark_slide.to_bytes(_deck()))
    presentation = parts["ppt/presentation.xml"].decode()

    assert not [name for name in parts if name.startswith("ppt/fonts/")]
    assert 'saveSubsetFonts="1"' in presentation
    assert "embedTrueTypeFonts" not in presentation
    assert "embeddedFontLst" not in presentation
    assert b"fntdata" not in parts["[Content_Types].xml"]


def test_writes_the_parts_relationships_and_font_list_powerpoint_expects() -> None:
    parts = _parts(dark_slide.to_bytes(_deck(), {"fonts": _fonts_option()}))
    presentation = parts["ppt/presentation.xml"].decode()

    # One slide: rId1 theme, rId2 slide, rId3 master, fonts from rId4.
    assert 'embedTrueTypeFonts="1"' in presentation
    assert "saveSubsetFonts" not in presentation
    assert (
        '<p:notesSz cx="5143500" cy="9144000"/>'
        "<p:embeddedFontLst>"
        '<p:embeddedFont><p:font typeface="Qvx Display"/><p:regular r:id="rId4"/><p:bold r:id="rId5"/></p:embeddedFont>'
        '<p:embeddedFont><p:font typeface="Qvx Text"/><p:regular r:id="rId6"/></p:embeddedFont>'
        "</p:embeddedFontLst></p:presentation>"
    ) in presentation

    rels = parts["ppt/_rels/presentation.xml.rels"].decode()
    for rid, file in ((4, "font1"), (5, "font2"), (6, "font3")):
        assert (
            f'<Relationship Id="rId{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" '
            f'Target="fonts/{file}.fntdata"/>'
        ) in rels
        assert f"ppt/fonts/{file}.fntdata" in parts
    assert b'<Default Extension="fntdata" ContentType="application/x-fontdata"/>' in parts["[Content_Types].xml"]


def test_wraps_each_font_in_an_uncompressed_eot_header_copied_from_the_font() -> None:
    bold = GeneratedFont.build("Qvx Display", "Bold", fs_type=0x0008, weight=700)
    parts = _parts(dark_slide.to_bytes(_deck(), {"fonts": {"Qvx Display": {"bold": bold}}}))
    eot = parts["ppt/fonts/font1.fntdata"]

    eot_size, font_data_size, version, flags = struct.unpack_from("<IIII", eot, 0)
    assert eot_size == len(eot)
    assert font_data_size == len(bold)
    assert version == 0x00020002
    assert flags == 0  # no subsetting, no compression, no XOR

    assert struct.unpack_from("<BBIHH", eot, 26) == (1, 0, 700, 0x0008, 0x504C)

    # FamilyName: Padding1 at 80, size at 82, UTF-16LE with its trailing NUL.
    (size,) = struct.unpack_from("<H", eot, 82)
    assert eot[84:84 + size] == "Qvx Display\0".encode("utf-16-le")

    # The font itself follows the header untouched.
    assert eot[-len(bold):] == bold


def test_accepts_a_font_as_a_path_as_well_as_bytes(tmp_path: pathlib.Path) -> None:
    font = tmp_path / "qvx-display.ttf"
    font.write_bytes(GeneratedFont.build("Qvx Display"))

    for source in (str(font), font):
        parts = _parts(dark_slide.to_bytes(_deck(), {"fonts": {"Qvx Display": {"regular": source}}}))
        assert "ppt/fonts/font1.fntdata" in parts


@pytest.mark.parametrize("fs_type", [0x0000, 0x0004, 0x0008, 0x0002 | 0x0004])
def test_embeds_a_font_whose_licence_permits_preview_and_print_or_editing(fs_type: int) -> None:
    font = GeneratedFont.build("Qvx Display", fs_type=fs_type)
    parts = _parts(dark_slide.to_bytes(_deck(), {"fonts": {"Qvx Display": {"regular": font}}}))
    assert "ppt/fonts/font1.fntdata" in parts


@pytest.mark.parametrize(
    ("fs_type", "reason"),
    [(0x0002, "forbids embedding"), (0x0200, "bitmap embedding only")],
    ids=["restricted licence", "bitmap embedding only"],
)
def test_refuses_a_font_whose_licence_forbids_embedding(fs_type: int, reason: str) -> None:
    font = GeneratedFont.build("Qvx Display", fs_type=fs_type)
    with pytest.raises(FontEmbeddingException, match=reason):
        dark_slide.to_bytes(_deck(), {"fonts": {"Qvx Display": {"regular": font}}})


@pytest.mark.parametrize(
    ("font", "reason"),
    [
        (lambda: GeneratedFont.with_tag(GeneratedFont.build("Qvx Display"), b"OTTO"), "CFF-outline OpenType"),
        (lambda: GeneratedFont.with_tag(GeneratedFont.build("Qvx Display"), b"ttcf"), "a font collection"),
        (lambda: GeneratedFont.build("Somebody Else"), "the file's family name is 'Somebody Else', not 'Qvx Display'"),
        (lambda: "/no/such/font.ttf", "no font file at /no/such/font.ttf"),
    ],
    ids=["CFF OpenType", "font collection", "a different family", "a missing file"],
)
def test_refuses_files_it_cannot_embed_naming_the_typeface_and_variant(font, reason: str) -> None:
    with pytest.raises(FontEmbeddingException) as caught:
        dark_slide.to_bytes(_deck(), {"fonts": {"Qvx Display": {"regular": font()}}})
    assert "Qvx Display (regular): " + reason in str(caught.value)


def test_reports_every_problem_at_once_and_writes_nothing(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "refused.pptx"

    with pytest.raises(FontEmbeddingException) as caught:
        dark_slide.write(_deck(), path, {"fonts": {
            "Qvx Display": {"regular": GeneratedFont.build("Qvx Display", fs_type=0x0002), "heavy": "x"},
            "Qvx Text": {"regular": GeneratedFont.build("Wrong Name")},
        }})

    message = str(caught.value)
    assert "Qvx Display: 'heavy' is not a variant" in message
    assert "Qvx Display (regular): its licence forbids embedding" in message
    assert "Qvx Text (regular): the file's family name is 'Wrong Name'" in message
    assert not path.exists()


def test_the_refusal_text_matches_the_php_reference_exactly() -> None:
    with pytest.raises(FontEmbeddingException) as caught:
        dark_slide.to_bytes(_deck(), {"fonts": {"Qvx Display": {"regular": GeneratedFont.build("Qvx Display", fs_type=0x0202)}}})

    assert str(caught.value) == (
        "These fonts cannot be embedded:\n"
        "- Qvx Display (regular): its licence forbids embedding (OS/2 fsType 0x0202, Restricted License)"
    )


def test_reads_back_which_typefaces_and_variants_a_file_embeds_and_never_the_bytes() -> None:
    deck = dark_slide.read(dark_slide.to_bytes(_deck(), {"fonts": _fonts_option()}))

    assert deck["metadata"]["embeddedFonts"] == [
        {"typeface": "Qvx Display", "variants": ["regular", "bold"]},
        {"typeface": "Qvx Text", "variants": ["regular"]},
    ]


def test_reports_no_embedded_fonts_for_a_deck_without_them() -> None:
    assert "metadata" not in dark_slide.read(dark_slide.to_bytes(_deck()))


@pytest.mark.skipif(os.environ.get("DARK_SLIDE_RENDER") != "1", reason="set DARK_SLIDE_RENDER=1 (needs LibreOffice) to render through a real viewer")
def test_renders_in_the_embedded_face_in_libreoffice_and_falls_back_without_it() -> None:
    soffice = os.environ.get("DARK_SLIDE_SOFFICE") or (
        "C:/Program Files/LibreOffice/program/soffice.com" if os.name == "nt" else "soffice"
    )
    with tempfile.TemporaryDirectory(prefix="fe-render-") as tmp:
        family = "Qvx Render " + secrets.token_hex(2).upper()
        deck = _deck()
        deck["theme"]["fonts"] = {"heading": family, "body": family}
        deck["slides"][0]["elements"][0]["style"]["fontFamily"] = family

        dark_slide.write(deck, os.path.join(tmp, "embedded.pptx"), {"fonts": {family: {"regular": GeneratedFont.build(family)}}})
        dark_slide.write(deck, os.path.join(tmp, "fallback.pptx"))

        profile = pathlib.Path(tmp, "profile").as_uri()
        subprocess.run(
            [soffice, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", tmp,
             os.path.join(tmp, "embedded.pptx"), os.path.join(tmp, "fallback.pptx")],
            capture_output=True,
        )

        postscript_name = family.replace(" ", "").encode() + b"-Regular"
        embedded = pathlib.Path(tmp, "embedded.pdf").read_bytes()
        fallback = pathlib.Path(tmp, "fallback.pdf").read_bytes()
        assert postscript_name in embedded
        assert postscript_name not in fallback
        # The fallback must have rendered SOMETHING, or the line above proves nothing.
        assert b"/BaseFont" in fallback

"""PowerPoint .potx templates. Mirrors PHP tests/Unit/OfficeTemplateTest.php.

A .potx IS its .pptx twin with /ppt/presentation.xml declared
`presentationml.template.main+xml`. The reader marks `sourceKind: "template"`;
the converter flips that one value and copies every other zip member as its
original record. dark-slide reads no OpenDocument presentations, so .otp/.odp
are refused by the converter.

Fixtures are built here with `zipfile` (DEFLATE, so the raw-record copy is
actually exercised), never by the production converter.
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

import dark_slide
from dark_slide import ArchiveRefused, OfficeTemplateRefused, convert_template
from dark_slide.reader.pptx_reader import PptxReader

DOC = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
TEMPLATE = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
MACRO_TEMPLATE = "application/vnd.ms-powerpoint.template.macroEnabled.main+xml"
MACRO_DOC = "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"
WORD_TEMPLATE = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"

SRC = str(Path(__file__).resolve().parents[1] / "src")


def deck() -> dict:
    return {
        "id": "brand",
        "title": "Brand Deck",
        "theme": {"name": "default"},
        "slides": [{
            "id": "s1",
            "layout": "blank",
            "elements": [
                {"id": "t1", "type": "text", "content": "Quarterly review", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.2},
                {"id": "r1", "type": "shape", "shape": "rounded-rect", "x": 0.1, "y": 0.5, "w": 0.3, "h": 0.3, "fill": "#FF0000"},
            ],
            "notes": "Speaker notes survive",
        }],
    }


def entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def make_zip(parts: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 27, 12, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def raw_records(data: bytes) -> dict[str, tuple[int, bytes]]:
    """name -> (method, raw compressed bytes), read independently of the package."""
    end = data.rfind(b"PK\x05\x06")
    count, _, at = struct.unpack_from("<HII", data, end + 10)
    out = {}
    for _ in range(count):
        method = struct.unpack_from("<H", data, at + 10)[0]
        compressed = struct.unpack_from("<I", data, at + 20)[0]
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, at + 28)
        local = struct.unpack_from("<I", data, at + 42)[0]
        name = data[at + 46:at + 46 + name_len].decode()
        start = local + 30 + sum(struct.unpack_from("<HH", data, local + 26))
        out[name] = (method, data[start:start + compressed])
        at += 46 + name_len + extra_len + comment_len
    return out


def pptx() -> bytes:
    return make_zip(entries(dark_slide.to_bytes(deck())))


def retyped(content_type: str, extra: dict[str, bytes] | None = None) -> bytes:
    parts = entries(pptx())
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(DOC.encode(), content_type.encode())
    return make_zip({**parts, **(extra or {})})


def potx() -> bytes:
    return retyped(TEMPLATE)


def with_types(edit, source: bytes | None = None) -> bytes:
    parts = entries(source if source is not None else pptx())
    parts["[Content_Types].xml"] = edit(parts["[Content_Types].xml"].decode()).encode()
    return make_zip(parts)


def read(data: bytes) -> dict:
    return PptxReader().from_bytes(data)


def refused(action, reason: str) -> None:
    with pytest.raises(OfficeTemplateRefused) as caught:
        action()
    assert caught.value.reason == reason


def archive_refused(action, reason: str) -> None:
    with pytest.raises(ArchiveRefused) as caught:
        action()
    assert caught.value.reason == reason


# ─── Reading ──────────────────────────────────────────────────────────────


def test_reads_a_potx_and_marks_it_with_the_twins_deck_id():
    document = read(pptx())
    template = read(potx())
    assert template.get("sourceKind") == "template"
    # The id digests CONTENT; sourceKind is stamped after the digest.
    assert template["id"] == document["id"]
    del template["sourceKind"]
    assert template == document


def test_a_pptx_read_is_unchanged_no_source_kind_key():
    assert "sourceKind" not in read(pptx())
    assert "sourceKind" not in dark_slide.read(pptx())


def test_reads_a_potx_from_a_path():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "brand.potx")
        Path(path).write_bytes(potx())
        assert dark_slide.read(path)["sourceKind"] == "template"


def test_refuses_a_macro_enabled_potm():
    refused(lambda: read(retyped(MACRO_TEMPLATE)), "macro_enabled")


def test_refuses_a_potx_carrying_a_vba_project():
    refused(lambda: read(retyped(TEMPLATE, {"ppt/vbaProject.bin": b"not really"})), "macro_enabled")


def test_still_reads_a_macro_enabled_presentation_pptm_as_before():
    assert "sourceKind" not in read(retyped(MACRO_DOC))


# ─── Hostile input ────────────────────────────────────────────────────────


def test_refuses_a_template_claiming_another_family():
    refused(lambda: read(retyped(WORD_TEMPLATE)), "family_mismatch")
    refused(lambda: read(with_types(lambda x: x.replace(
        "</Types>", f'<Override PartName="/word/document.xml" ContentType="{WORD_TEMPLATE}"/></Types>'))), "family_mismatch")
    refused(lambda: read(with_types(lambda x: x.replace(
        'ContentType="application/xml"', f'ContentType="{TEMPLATE}"'))), "family_mismatch")


def test_refuses_a_template_zip_bomb_reading_and_converting():
    bomb = retyped(TEMPLATE, {"ppt/media/bomb.bin": bytes(65 * 1024 * 1024)})
    archive_refused(lambda: read(bomb), "archive_limit")
    archive_refused(lambda: convert_template(bomb), "archive_limit")


def test_refuses_a_traversing_entry_name_reading_and_converting():
    evil = retyped(TEMPLATE, {"../evil.xml": b"<x/>"})
    archive_refused(lambda: read(evil), "archive_path")
    archive_refused(lambda: convert_template(evil), "archive_path")


def test_a_damaged_zip_is_still_a_value_error():
    # Callers that caught ValueError for a broken file keep working.
    with pytest.raises(ValueError):
        read(b"PK\x03\x04 not a zip at all")


# ─── Converting ───────────────────────────────────────────────────────────


def test_converts_potx_to_pptx_changing_only_the_content_type_value():
    source = potx()
    out = dark_slide.convert_template(source, "document")
    before, after = entries(source), entries(out)
    assert list(after) == list(before)
    raw_before, raw_after = raw_records(source), raw_records(out)
    for name, data in before.items():
        if name == "[Content_Types].xml":
            assert after[name] == data.replace(TEMPLATE.encode(), DOC.encode())
        else:
            assert after[name] == data, name
            assert raw_after[name] == raw_before[name], name
    assert "sourceKind" not in read(out)


def test_round_trips_pptx_to_potx_and_back_byte_identical():
    source = pptx()
    template = convert_template(source, "template")
    assert read(template)["sourceKind"] == "template"
    assert entries(convert_template(template, "document")) == entries(source)


def test_flips_when_no_target_is_given_and_takes_a_path():
    assert read(convert_template(pptx()))["sourceKind"] == "template"
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "brand.potx")
        Path(path).write_bytes(potx())
        assert "sourceKind" not in read(convert_template(path))


def test_refuses_conversions_it_must_not_make():
    refused(lambda: convert_template(potx(), "template"), "already_template")
    refused(lambda: convert_template(pptx(), "document"), "already_document")
    refused(lambda: convert_template(retyped(MACRO_TEMPLATE), "document"), "macro_enabled")
    refused(lambda: convert_template(retyped(MACRO_DOC), "template"), "macro_enabled")
    refused(lambda: convert_template(pptx(), "spreadsheet"), "bad_target")
    refused(lambda: convert_template(retyped(WORD_TEMPLATE)), "family_mismatch")


def test_does_not_handle_opendocument_presentations():
    for mimetype in ("application/vnd.oasis.opendocument.presentation",
                     "application/vnd.oasis.opendocument.presentation-template"):
        odf = make_zip({"mimetype": mimetype.encode(), "content.xml": b"<x/>"})
        refused(lambda: convert_template(odf), "not_convertible")


def test_refuses_to_convert_a_word_document_it_does_not_own():
    docx = make_zip({
        "[Content_Types].xml": b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "word/document.xml": b"<w:document/>",
    })
    refused(lambda: convert_template(docx), "not_convertible")


def test_refuses_a_declaration_it_cannot_rewrite_unambiguously():
    decoy = with_types(lambda x: x.replace(
        '<Override PartName="/ppt/presentation.xml"',
        f'<!-- <Override PartName="/ppt/presentation.xml" ContentType="{TEMPLATE}"/> --><Override PartName="/ppt/presentation.xml"'), potx())
    refused(lambda: convert_template(decoy), "not_convertible")


# ─── CLI ──────────────────────────────────────────────────────────────────


def cli(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}
    return subprocess.run([sys.executable, "-m", "dark_slide", *args], capture_output=True, text=True, env=env)


def test_template_convert_cli():
    with tempfile.TemporaryDirectory() as directory:
        d = Path(directory)
        (d / "in.potx").write_bytes(potx())

        result = cli("template:convert", str(d / "in.potx"), str(d / "out.pptx"))
        assert result.returncode == 0, result.stderr
        assert "document" in result.stdout
        assert "sourceKind" not in read((d / "out.pptx").read_bytes())

        result = cli("template:convert", str(d / "out.pptx"), str(d / "out.pptx"), "--to=template")
        assert result.returncode == 1 and "exists" in result.stderr

        result = cli("template:convert", str(d / "out.pptx"), str(d / "back.potx"), "--to=template")
        assert result.returncode == 0 and read((d / "back.potx").read_bytes())["sourceKind"] == "template"

        (d / "macro.potm").write_bytes(retyped(MACRO_TEMPLATE))
        result = cli("template:convert", str(d / "macro.potm"), str(d / "macro.pptx"))
        assert result.returncode == 1 and "macro_enabled" in result.stderr
        assert not (d / "macro.pptx").exists()

        result = cli("template:convert")
        assert result.returncode == 2 and "Usage" in result.stderr


# ─── LibreOffice as an oracle (skipped where it is not installed) ─────────


def _soffice() -> str | None:
    for candidate in (os.environ.get("LIBREOFFICE_BIN"), "C:/Program Files/LibreOffice/program/soffice.com",
                      "/usr/bin/soffice", "/usr/local/bin/soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _libreoffice(soffice: str, source: Path, fmt: str, out_dir: Path) -> Path:
    # A SHORT profile path: long ones crash LibreOffice on Windows.
    profile = tempfile.mkdtemp(prefix="dsl")
    try:
        url = "file:///" + profile.replace(chr(92), "/").lstrip("/")
        result = subprocess.run([soffice, f"-env:UserInstallation={url}", "--headless", "--norestore",
                                 "--convert-to", fmt, "--outdir", str(out_dir), str(source)],
                                capture_output=True, timeout=120)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = out_dir / f"{source.stem}.{fmt.split(':')[0]}"
    assert result.returncode == 0 and out.is_file(), f"LibreOffice produced no {fmt}"
    return out


@pytest.mark.skipif(_soffice() is None, reason="LibreOffice is not installed; the oracle runs where it is.")
def test_libreoffice_potx_reads_as_a_template_and_libreoffice_opens_our_conversion():
    soffice = _soffice()
    with tempfile.TemporaryDirectory() as directory:
        d = Path(directory)
        (d / "src.pptx").write_bytes(dark_slide.to_bytes(deck()))
        lo_template = _libreoffice(soffice, d / "src.pptx", "potx", d)
        read_back = read(lo_template.read_bytes())
        assert read_back.get("sourceKind") == "template"
        assert "Quarterly review" in repr(read_back)

        (d / "lo").mkdir()
        assert "sourceKind" not in read(_libreoffice(soffice, lo_template, "pptx", d / "lo").read_bytes())

        (d / "ours.pptx").write_bytes(convert_template(lo_template.read_bytes(), "document"))
        (d / "ours").mkdir()
        odp = _libreoffice(soffice, d / "ours.pptx", "odp", d / "ours")
        assert b"Quarterly review" in entries(odp.read_bytes())["content.xml"]

"""The Agent surface, end to end. Ported from PHP ``tests/Unit/AgentTest.php``.

Every test here drives the real writer or the real reader, so a regression in
the OOXML emission shows up as a failing assertion rather than as a document
nobody opens until later.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

import dark_slide
from dark_slide import SchemaException


def fixture() -> dict[str, Any]:
    return {
        "id": "test",
        "title": "Test deck",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "layout": "title",
                "elements": [
                    {
                        "id": "e1",
                        "type": "text",
                        "x": 0.1,
                        "y": 0.4,
                        "w": 0.8,
                        "h": 0.2,
                        "content": "Hello, DarkSlide.",
                        "format": "plain",
                        "style": {"fontSize": 48, "weight": "bold", "align": "center"},
                    }
                ],
                "notes": "These are speaker notes.",
            },
            {
                "id": "s2",
                "layout": "blank",
                "elements": [
                    {
                        "id": "e2",
                        "type": "shape",
                        "shape": "rounded-rect",
                        "x": 0.2,
                        "y": 0.2,
                        "w": 0.6,
                        "h": 0.6,
                        "fill": "#8B5CF6",
                        "stroke": "#0F172A",
                        "strokeWidth": 4,
                        "radius": 16,
                    }
                ],
            },
        ],
    }


def part(deck: Any, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(deck))) as archive:
        return archive.read(name).decode("utf-8")


def test_a_well_formed_deck_validates_clean() -> None:
    assert dark_slide.validate(fixture()) == []


def test_missing_required_keys_come_back_as_structured_errors() -> None:
    errors = dark_slide.validate({"slides": []})
    paths = [e["path"] for e in errors]
    assert "/id" in paths
    assert "/title" in paths
    assert "/theme" in paths


def test_a_non_numeric_coordinate_is_flagged_with_its_path() -> None:
    deck = fixture()
    deck["slides"][0]["elements"][0]["x"] = "not-a-number"
    errors = dark_slide.validate(deck)
    assert errors
    assert errors[0]["path"] == "/slides/0/elements/0/x"


def test_repair_fills_in_ids_and_clamps_out_of_range_coordinates() -> None:
    deck = {
        "slides": [
            {
                "elements": [
                    {"type": "text", "x": -0.5, "y": 1.5, "w": 2.0, "h": 0.001, "content": "hi"}
                ]
            }
        ]
    }
    result = dark_slide.validate_and_repair(deck)
    assert result["ok"] is True
    element = result["schema"]["slides"][0]["elements"][0]
    assert element["x"] == 0.0
    assert element["y"] == 1.0
    assert element["w"] == 1.0
    assert element["h"] >= 0.02
    assert isinstance(element["id"], str)


def test_repair_never_mutates_the_input() -> None:
    """PHP gets this from array value semantics; Python has to deep-copy."""
    deck = {"slides": [{"elements": [{"type": "text", "x": 5, "y": 0, "w": 0, "h": 0}]}]}
    dark_slide.validate_and_repair(deck)
    assert "id" not in deck
    assert deck["slides"][0]["elements"][0]["x"] == 5


def test_to_bytes_produces_a_zip() -> None:
    payload = dark_slide.to_bytes(fixture())
    assert len(payload) > 1000
    assert payload[:2] == b"PK"


def test_the_archive_contains_the_expected_parts() -> None:
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(fixture()))) as archive:
        names = set(archive.namelist())

    for expected in [
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/core.xml",
        "docProps/app.xml",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
        "ppt/theme/theme1.xml",
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideLayouts/slideLayout1.xml",
        "ppt/slides/slide1.xml",
        "ppt/slides/slide2.xml",
        "ppt/slides/_rels/slide1.xml.rels",
        "ppt/slides/_rels/slide2.xml.rels",
        "ppt/notesSlides/notesSlide1.xml",  # only slide 1 has notes
    ]:
        assert expected in names, f"missing part: {expected}"


def test_the_text_content_lands_in_slide1() -> None:
    assert "Hello, DarkSlide." in part(fixture(), "ppt/slides/slide1.xml")


def test_write_returns_the_path_size_and_slide_count(tmp_path) -> None:
    target = tmp_path / "out.pptx"
    result = dark_slide.write(fixture(), target)
    assert result["slides"] == 2
    assert result["bytes"] > 1000
    assert target.is_file()


def test_write_creates_missing_parent_directories(tmp_path) -> None:
    target = tmp_path / "nested" / "deeper" / "out.pptx"
    dark_slide.write(fixture(), target)
    assert target.is_file()


def test_writing_an_invalid_deck_raises_with_the_error_list(tmp_path) -> None:
    with pytest.raises(SchemaException) as excinfo:
        dark_slide.write({"slides": []}, tmp_path / "nope.pptx")
    # The point of the exception is the payload, not the message.
    assert excinfo.value.errors
    assert all("path" in e for e in excinfo.value.errors)


def test_a_deck_round_trips_through_write_then_read(tmp_path) -> None:
    target = tmp_path / "rt.pptx"
    dark_slide.write(fixture(), target)
    read_back = dark_slide.read(target)

    assert read_back["title"] == "Test deck"
    assert len(read_back["slides"]) == 2
    first = read_back["slides"][0]
    assert "Hello, DarkSlide." in [e.get("content") for e in first["elements"]]
    assert "speaker notes" in first["notes"]


def test_read_accepts_bytes_as_well_as_a_path() -> None:
    """PHP's read takes a path and Node's takes bytes; this takes both."""
    read_back = dark_slide.read(dark_slide.to_bytes(fixture()))
    assert read_back["title"] == "Test deck"
    assert len(read_back["slides"]) == 2


def test_from_bytes_is_the_bytes_only_alias() -> None:
    payload = dark_slide.to_bytes(fixture())
    assert dark_slide.from_bytes(payload)["title"] == dark_slide.read(payload)["title"]


def test_describe_summarises_a_deck_in_plain_text() -> None:
    summary = dark_slide.describe(fixture())
    assert "Deck: Test deck" in summary
    assert "Slides: 2" in summary
    assert "1 text" in summary
    assert "1 shape" in summary


def test_json_schema_declares_the_top_level_keys() -> None:
    schema = dark_slide.json_schema()
    assert schema["type"] == "object"
    for key in ("id", "title", "slides", "theme"):
        assert key in schema["required"]


# ── v0.2 features ─────────────────────────────────────────────────────────


def test_inline_markdown_spans_become_separate_runs() -> None:
    deck = fixture()
    element = deck["slides"][0]["elements"][0]
    element["content"] = "A **bold** word and `code` and *italic* too."
    element["format"] = "markdown"

    xml = part(deck, "ppt/slides/slide1.xml")

    assert "<a:t>A </a:t>" in xml
    assert "<a:t>bold</a:t>" in xml
    assert "<a:t> word and </a:t>" in xml
    assert "<a:t>code</a:t>" in xml
    assert "<a:t>italic</a:t>" in xml
    # Bold runs carry b="1"; code runs switch to Consolas.
    assert 'b="1"' in xml
    assert "Consolas" in xml


def test_bulleted_markdown_lines_get_bullet_paragraph_markup() -> None:
    deck = fixture()
    element = deck["slides"][0]["elements"][0]
    element["content"] = "- one\n- two with **bold**\n- three"
    element["format"] = "markdown"

    xml = part(deck, "ppt/slides/slide1.xml")
    assert xml.count('<a:buChar char="•"/>') == 3


def test_a_table_element_emits_a_real_tbl() -> None:
    deck = fixture()
    deck["slides"][1]["elements"].append(
        {
            "id": "tbl1",
            "type": "table",
            "x": 0.1,
            "y": 0.7,
            "w": 0.8,
            "h": 0.2,
            "columns": [{"key": "name", "label": "Name"}, {"key": "qty", "label": "Qty"}],
            "rows": [{"name": "Widget", "qty": 12}, {"name": "Sprocket", "qty": 4}],
        }
    )

    xml = part(deck, "ppt/slides/slide2.xml")
    assert "<a:tbl>" in xml
    assert "<a:tblGrid>" in xml
    assert xml.count("<a:tr ") == 3  # header + two body rows
    assert "<a:t>Name</a:t>" in xml
    assert "<a:t>Widget</a:t>" in xml
    assert "<a:t>12</a:t>" in xml
    assert "[table]" not in xml


def test_a_table_with_no_columns_degrades_to_a_placeholder() -> None:
    deck = fixture()
    deck["slides"][1]["elements"].append(
        {"id": "empty", "type": "table", "x": 0.1, "y": 0.7, "w": 0.8, "h": 0.2, "columns": []}
    )
    assert "[table: no columns]" in part(deck, "ppt/slides/slide2.xml")


def test_a_gradient_background_becomes_a_gradfill_with_stops() -> None:
    deck = fixture()
    deck["slides"][0]["background"] = {
        "gradient": "linear-gradient(135deg, #fef3c7 0%, #fce7f3 100%)"
    }

    xml = part(deck, "ppt/slides/slide1.xml")
    assert "<a:gradFill" in xml
    assert "<a:gsLst>" in xml
    assert "FEF3C7" in xml
    assert "FCE7F3" in xml
    assert "<a:lin ang=" in xml


def test_a_solid_colour_background_still_works() -> None:
    deck = fixture()
    deck["slides"][0]["background"] = {"color": "#0b1220"}

    xml = part(deck, "ppt/slides/slide1.xml")
    assert '<a:srgbClr val="0B1220"' in xml
    assert "<a:gradFill" not in xml


# ── v0.3 features ─────────────────────────────────────────────────────────


def test_markdown_headings_render_larger_and_bold() -> None:
    deck = fixture()
    element = deck["slides"][0]["elements"][0]
    element["content"] = "# Big heading\n## Medium\n### Small\nbody copy"
    element["format"] = "markdown"
    # Big enough that the h3 multiplier still clears PPTX's 8pt floor.
    element["style"] = {"fontSize": 40}

    xml = part(deck, "ppt/slides/slide1.xml")
    assert "<a:t>Big heading</a:t>" in xml
    assert "<a:t>Medium</a:t>" in xml
    assert "<a:t>Small</a:t>" in xml
    assert "<a:t># Big heading</a:t>" not in xml
    # Body 40 → sz=2000; h1 is 1.8x → sz=3600.
    assert 'sz="3600" b="1"' in xml
    assert 'sz="2000"' in xml


def test_code_blocks_get_coloured_token_runs() -> None:
    deck = fixture()
    deck["slides"][1]["elements"].append(
        {
            "id": "snippet",
            "type": "code",
            "x": 0.05,
            "y": 0.05,
            "w": 0.9,
            "h": 0.4,
            "code": "const greet = (name) => `Hello, ${name}`;\n// comment",
            "language": "typescript",
        }
    )

    xml = part(deck, "ppt/slides/slide2.xml")
    # `const` is a keyword (violet), the comment is slate, the template
    # literal is a string (green), and everything is Consolas.
    assert '<a:srgbClr val="C084FC"/>' in xml
    assert "<a:t>const</a:t>" in xml
    assert '<a:srgbClr val="64748B"/>' in xml
    assert "<a:t>// comment</a:t>" in xml
    assert "86EFAC" in xml
    assert "Consolas" in xml


def test_a_table_round_trips_through_write_then_read(tmp_path) -> None:
    deck = fixture()
    deck["slides"][1]["elements"].append(
        {
            "id": "tbl-rt",
            "type": "table",
            "x": 0.1,
            "y": 0.7,
            "w": 0.8,
            "h": 0.2,
            "columns": [{"key": "name", "label": "Name"}, {"key": "qty", "label": "Qty"}],
            "rows": [{"name": "Widget", "qty": 12}, {"name": "Sprocket", "qty": 4}],
        }
    )

    target = tmp_path / "rt.pptx"
    dark_slide.write(deck, target)
    read_back = dark_slide.read(target)

    tables = [e for e in read_back["slides"][1]["elements"] if e["type"] == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert [c["label"] for c in table["columns"]] == ["Name", "Qty"]
    assert len(table["rows"]) == 2
    # Keys are re-synthesised as col1/col2 on read — the source deck's keys
    # are not in the file — so check by position.
    assert list(table["rows"][0].values()) == ["Widget", "12"]


def test_a_gradient_background_round_trips(tmp_path) -> None:
    deck = fixture()
    deck["slides"][0]["background"] = {
        "gradient": "linear-gradient(135deg, #fef3c7 0%, #fce7f3 100%)"
    }

    target = tmp_path / "rt.pptx"
    dark_slide.write(deck, target)
    background = dark_slide.read(target)["slides"][0].get("background")

    assert isinstance(background, dict)
    assert "gradient" in background
    assert "linear-gradient(" in background["gradient"]
    assert "#fef3c7" in background["gradient"].lower()
    assert "#fce7f3" in background["gradient"].lower()


def test_an_embedded_image_round_trips_as_a_data_uri(tmp_path) -> None:
    from tests.fixtures import PNG_1x1

    deck = fixture()
    deck["slides"][0]["elements"].append(
        {
            "id": "img",
            "type": "image",
            "x": 0.1,
            "y": 0.1,
            "w": 0.3,
            "h": 0.3,
            "src": PNG_1x1,
            "fit": "cover",
        }
    )

    target = tmp_path / "rt.pptx"
    dark_slide.write(deck, target)
    images = [e for e in dark_slide.read(target)["slides"][0]["elements"] if e["type"] == "image"]

    assert len(images) == 1
    assert images[0]["src"].startswith("data:image/png;base64,")
    assert len(images[0]["src"]) > 100


def test_inline_markdown_spans_round_trip(tmp_path) -> None:
    deck = fixture()
    element = deck["slides"][0]["elements"][0]
    element["content"] = "This is **bold** and *italic* and `code`."
    element["format"] = "markdown"
    # The base style must NOT be all-bold, or the reader correctly collapses
    # the uniform bold into the paragraph default and emits no markers.
    element["style"] = {"fontSize": 24, "align": "left"}

    target = tmp_path / "rt.pptx"
    dark_slide.write(deck, target)
    first = next(e for e in dark_slide.read(target)["slides"][0]["elements"] if e["type"] == "text")

    assert first["format"] == "markdown"
    assert "**bold**" in first["content"]
    assert "*italic*" in first["content"]
    assert "`code`" in first["content"]

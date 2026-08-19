"""``to_bytes`` → ``read``. Ported from ``dark-slide-js/tests/roundtrip.test.ts``.

The reader is best-effort by design, so this asserts what it PROMISES to
recover — element kinds, geometry, content, notes, backgrounds — and the last
two tests assert what it promises to do with everything else: degrade, not
throw.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest

import dark_slide
from tests.fixtures import PNG_1x1


def read_back(deck: Any) -> Any:
    return dark_slide.read(dark_slide.to_bytes(deck))


def one_slide(*elements: Any, **slide_extra: Any) -> dict[str, Any]:
    return {
        "id": "d",
        "title": "RT",
        "theme": {"name": "default"},
        "slides": [{"id": "s1", "layout": "blank", "elements": list(elements), **slide_extra}],
    }


def test_text_content_and_markdown_decoration_survive() -> None:
    deck = one_slide(
        {
            "id": "t1",
            "type": "text",
            "x": 0.1,
            "y": 0.2,
            "w": 0.5,
            "h": 0.2,
            "content": "Plain then **bold** word",
            "format": "markdown",
        }
    )
    element = read_back(deck)["slides"][0]["elements"][0]

    assert element["type"] == "text"
    assert element["content"] == "Plain then **bold** word"
    assert element["format"] == "markdown"
    assert element["x"] == pytest.approx(0.1, abs=1e-4)
    assert element["w"] == pytest.approx(0.5, abs=1e-4)


def test_a_shape_comes_back_with_its_preset_geometry() -> None:
    deck = one_slide(
        {
            "id": "shp",
            "type": "shape",
            "x": 0.2,
            "y": 0.2,
            "w": 0.3,
            "h": 0.3,
            "shape": "ellipse",
            "fill": "#FF0000",
        }
    )
    element = read_back(deck)["slides"][0]["elements"][0]
    assert element["type"] == "shape"
    assert element["shape"] == "ellipse"


@pytest.mark.parametrize(
    "kind", ["rect", "rounded-rect", "ellipse", "triangle", "line", "arrow"]
)
def test_every_shape_kind_round_trips(kind: str) -> None:
    deck = one_slide(
        {"id": "s", "type": "shape", "x": 0.2, "y": 0.2, "w": 0.3, "h": 0.3, "shape": kind}
    )
    element = read_back(deck)["slides"][0]["elements"][0]
    assert element["shape"] == kind


def test_a_tables_columns_and_rows_survive() -> None:
    deck = one_slide(
        {
            "id": "tbl",
            "type": "table",
            "x": 0.1,
            "y": 0.1,
            "w": 0.8,
            "h": 0.4,
            "columns": [{"key": "a", "label": "Alpha"}, {"key": "b", "label": "Beta"}],
            "rows": [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
        }
    )
    element = next(e for e in read_back(deck)["slides"][0]["elements"] if e["type"] == "table")

    assert [c["label"] for c in element["columns"]] == ["Alpha", "Beta"]
    assert len(element["rows"]) == 2
    # Keys are re-synthesised — the authored keys are not in the file.
    assert element["rows"][0]["col1"] == "1"
    assert element["rows"][1]["col2"] == "4"


def test_a_solid_background_colour_survives() -> None:
    deck = one_slide(background={"color": "#123456"})
    assert read_back(deck)["slides"][0]["background"]["color"] == "#123456"


def test_a_gradient_background_survives_including_its_angle() -> None:
    deck = one_slide(
        background={"gradient": "linear-gradient(90deg, #ff0000 0%, #00ff00 100%)"}
    )
    gradient = read_back(deck)["slides"][0]["background"]["gradient"]
    assert re.fullmatch(r"linear-gradient\(90deg, #ff0000 0%, #00ff00 100%\)", gradient)


def test_an_embedded_image_comes_back_as_a_data_uri() -> None:
    deck = one_slide(
        {
            "id": "img",
            "type": "image",
            "x": 0.1,
            "y": 0.1,
            "w": 0.2,
            "h": 0.2,
            "src": PNG_1x1,
            "fit": "contain",
        }
    )
    element = next(e for e in read_back(deck)["slides"][0]["elements"] if e["type"] == "image")
    assert element["src"].startswith("data:image/png;base64,")


def test_slide_notes_survive() -> None:
    deck = one_slide(
        {
            "id": "t",
            "type": "text",
            "x": 0.1,
            "y": 0.1,
            "w": 0.3,
            "h": 0.1,
            "content": "hi",
            "format": "plain",
        },
        notes="first\nsecond",
    )
    assert read_back(deck)["slides"][0]["notes"] == "first\nsecond"


def test_slide_order_follows_the_presentation_rels_not_the_part_names() -> None:
    deck = {
        "id": "d",
        "title": "Order",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": f"s{i}",
                "elements": [
                    {
                        "id": f"t{i}",
                        "type": "text",
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.5,
                        "h": 0.1,
                        "content": f"Slide {i}",
                        "format": "plain",
                    }
                ],
            }
            for i in range(1, 4)
        ],
    }
    out = read_back(deck)
    assert [s["elements"][0]["content"] for s in out["slides"]] == ["Slide 1", "Slide 2", "Slide 3"]


def test_unicode_content_survives_the_round_trip() -> None:
    deck = one_slide(
        {
            "id": "t",
            "type": "text",
            "x": 0.1,
            "y": 0.1,
            "w": 0.8,
            "h": 0.2,
            "content": "日本語 café \U0001f389",
            "format": "plain",
        }
    )
    assert read_back(deck)["slides"][0]["elements"][0]["content"] == "日本語 café \U0001f389"


# ── Degrading rather than throwing ────────────────────────────────────────


def test_an_unmodellable_construct_is_skipped_not_raised() -> None:
    """A chart frame is recognised as something and modelled as nothing.

    The whole import must not fail over one element the reader has no shape
    for — a deck out of PowerPoint always contains several.
    """
    deck = one_slide(
        {
            "id": "c",
            "type": "chart",
            "x": 0.1,
            "y": 0.1,
            "w": 0.8,
            "h": 0.8,
            "option": {
                "xAxis": {"data": ["a", "b"]},
                "series": [{"type": "bar", "data": [1, 2]}],
            },
        }
    )
    out = read_back(deck)
    assert out["slides"][0]["elements"] == []
    assert len(out["slides"]) == 1  # the slide itself still came through


def test_a_missing_presentation_rels_part_yields_an_empty_deck_not_an_error() -> None:
    payload = dark_slide.to_bytes(one_slide())
    stripped = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as source:
        with zipfile.ZipFile(stripped, "w") as target:
            for name in source.namelist():
                if name != "ppt/_rels/presentation.xml.rels":
                    target.writestr(name, source.read(name))

    out = dark_slide.read(stripped.getvalue())
    assert out["slides"] == []
    assert out["title"] == "RT"  # docProps still parsed


def test_a_doctype_is_refused_before_the_parser_sees_it() -> None:
    """A .pptx never legitimately carries one, and it is the entity-expansion door."""
    payload = dark_slide.to_bytes(one_slide())
    poisoned = io.BytesIO()
    doctype = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<!DOCTYPE Relationships [<!ENTITY xxe "boom">]>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        "</Relationships>"
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as source:
        with zipfile.ZipFile(poisoned, "w") as target:
            for name in source.namelist():
                if name == "ppt/_rels/presentation.xml.rels":
                    target.writestr(name, doctype)
                else:
                    target.writestr(name, source.read(name))

    out = dark_slide.read(poisoned.getvalue())
    assert out["slides"] == []


def test_a_non_zip_payload_raises_a_clear_error() -> None:
    with pytest.raises(ValueError):
        dark_slide.read(b"not a zip at all")


def test_reading_a_missing_path_raises_filenotfound(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        dark_slide.read(tmp_path / "nope.pptx")

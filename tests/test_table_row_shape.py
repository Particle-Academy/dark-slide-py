"""What shape a table's ``rows`` take, and whether the published schema says so.

A ``table`` exported as ``columns: {"type": "array"}, rows: {"type": "array"}``
and nothing more, while the real contract was ``columns: [{key, label}]`` with
rows as OBJECTS keyed by each column's ``key`` -- readable only from the
resolver's source, so a vocabulary generated from the schema could not carry it.
The natural guess from a bare column list is a positional row.

That guess failed SILENTLY, and differently per engine, which is why this file
pins behaviour and not only the schema text:

- PHP kept the row and emitted every cell empty;
- THIS engine and Node dropped the row from the deck entirely, because
  ``is_plain_object([...])`` is false and the loop simply ``continue``d.

Three engines held to byte-identical OOXML disagreed on the ROW COUNT of the
same input, and no conformance case covered it. Reported as fancy-slides#14.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from dark_slide import json_schema, to_bytes, validate
from dark_slide.table.table_resolver import resolve

COLUMNS = [{"key": "plan", "label": "Plan"}, {"key": "price", "label": "Monthly price"}]


def _element_properties(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["properties"]["slides"]["items"]["properties"]["elements"]["items"]["properties"]


def _slide_xml(rows: list[Any]) -> str:
    deck = {
        "id": "trs",
        "title": "Table row shape",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "elements": [
                    {
                        "id": "t",
                        "type": "table",
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.8,
                        "h": 0.4,
                        "columns": COLUMNS,
                        "rows": rows,
                    }
                ],
            }
        ],
    }
    with zipfile.ZipFile(io.BytesIO(to_bytes(deck))) as zf:
        return zf.read("ppt/slides/slide1.xml").decode("utf-8")


def _deck(rows: list[Any]) -> dict[str, Any]:
    return {
        "id": "trs",
        "title": "Table row shape",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "elements": [
                    {
                        "id": "t",
                        "type": "table",
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.8,
                        "h": 0.4,
                        "columns": [{"key": "plan", "label": "Plan"}, {"key": "price", "label": "Price"}],
                        "rows": rows,
                    }
                ],
            }
        ],
    }


def test_publishes_the_item_shape_of_a_column() -> None:
    columns = _element_properties(json_schema())["columns"]

    assert columns["type"] == "array"
    assert "items" in columns
    assert "key" in columns["items"]["properties"]
    assert "label" in columns["items"]["properties"]
    assert "key" in columns["items"]["required"]

    # `key` is the half that cannot be guessed: it is what a row is keyed BY.
    assert "row" in columns["items"]["properties"]["key"]["description"].lower()


def test_publishes_the_item_shape_of_a_row() -> None:
    import json

    rows = _element_properties(json_schema())["rows"]

    assert rows["type"] == "array"
    assert "items" in rows

    # Both accepted forms are described: describing only the canonical one
    # leaves the other reading as invalid when it is not.
    described = json.dumps(rows["items"]).lower()
    assert "key" in described
    assert "column order" in described


def test_renders_a_keyed_row() -> None:
    xml = _slide_xml([{"plan": "Starter", "price": "$49"}])

    assert "Starter" in xml
    assert "$49" in xml


def test_fills_a_positional_row_by_column_order_instead_of_dropping_it() -> None:
    xml = _slide_xml([["Starter", "$49"]])

    assert "Starter" in xml
    assert "$49" in xml


def test_emits_a_positional_row_identically_to_the_keyed_row_it_means() -> None:
    assert _slide_xml([["Starter", "$49"]]) == _slide_xml([{"plan": "Starter", "price": "$49"}])


def test_reads_a_positional_list_inside_cells_by_column_order() -> None:
    xml = _slide_xml([{"cells": ["Starter", "$49"], "height": 44}])

    assert "Starter" in xml
    assert "$49" in xml


def test_keeps_a_short_positional_row_short() -> None:
    xml = _slide_xml([["Starter"]])

    assert xml.count("Starter") == 1


def test_resolves_a_positional_row_through_the_resolver() -> None:
    table = resolve(
        {
            "type": "table",
            "w": 0.8,
            "columns": [{"key": "plan"}, {"key": "price"}],
            "rows": [["Starter", "$49"]],
        },
        {},
    )

    # Header + one body row. A dropped row leaves only the header, which is the
    # divergence this case exists to catch.
    assert len(table["rows"]) == 2
    assert [c["text"] for c in table["rows"][1]["cells"]] == ["Starter", "$49"]


def test_flags_a_row_whose_keys_match_no_column() -> None:
    # `Plan` is not `plan`. Every cell resolves to nothing and the table still
    # draws at full size -- the blank grid the positional fallback cannot catch,
    # because this row IS an object.
    errors = validate(_deck([{"Plan": "Starter"}]))
    by_path = {e["path"]: e for e in errors}

    assert "/slides/0/elements/0/rows/0" in by_path
    assert "plan" in by_path["/slides/0/elements/0/rows/0"]["hint"]


def test_does_not_flag_a_partial_positional_or_styled_row() -> None:
    assert (
        validate(
            _deck(
                [
                    {"plan": "Starter"},
                    ["Starter", "$49"],
                    {"cells": {"plan": "Pro"}},
                    {"height": 44},
                ]
            )
        )
        == []
    )

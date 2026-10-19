"""``lint``: the same cases, with the same messages, as PHP's LintTest and the
Node port's lint.test.ts. Identical expected strings are the parity check."""

from __future__ import annotations

from typing import Any

from dark_slide import lint


def _deck(elements: list[dict[str, Any]], **theme: Any) -> dict[str, Any]:
    return {"id": "d", "title": "D", "theme": {"name": "t", **theme}, "slides": [{"id": "s1", "elements": elements}]}


def test_a_title_wrapping_onto_the_rule_beneath_it() -> None:
    assert lint(_deck([
        {"id": "title", "type": "text", "x": 0.06, "y": 0.06, "w": 0.88, "h": 0.13,
         "content": "EMEA delivered 48% of Q3 revenue", "style": {"fontSize": 88, "weight": 700}},
        {"id": "rule", "type": "shape", "shape": "rect", "x": 0.06, "y": 0.2, "w": 0.06, "h": 0.006},
    ])) == [
        {"code": "text-overflow", "slide": 1, "element": "title",
         "message": "At 88px this text needs about 0.23 of the slide height and its box is 0.13: it will wrap past "
                    "the box, more so in a substitute font. Make h at least 0.23 and move what is below it down, "
                    "shorten the text, or lower fontSize."},
        {"code": "overlap", "slide": 1, "element": "title",
         "message": "Its text runs into \"rule\". Place one below the other's bottom edge (y + h) with a gap of at least 0.02."},
    ]


def test_text_on_a_panel_behind_it_is_not_an_overlap() -> None:
    assert lint(_deck([
        {"id": "card", "type": "shape", "shape": "rounded-rect", "x": 0.6, "y": 0.3, "w": 0.34, "h": 0.3},
        {"id": "card-text", "type": "text", "x": 0.62, "y": 0.32, "w": 0.3, "h": 0.2, "content": "EMEA: $2.10M", "style": {"fontSize": 44}},
    ])) == []


def test_where_text_sits_not_the_whole_box() -> None:
    assert lint(_deck([
        {"id": "num", "type": "text", "x": 0.06, "y": 0.3, "w": 0.4, "h": 0.4, "content": "48.5%", "style": {"fontSize": 120}},
        {"id": "cap", "type": "text", "x": 0.06, "y": 0.6, "w": 0.4, "h": 0.15, "content": "of Q3 revenue", "style": {"fontSize": 40}},
    ])) == []


def test_kpi_values_too_wide_for_their_cells() -> None:
    assert lint(_deck([
        {"id": "kpis", "type": "kpiBand", "x": 0.06, "y": 0.6, "w": 0.88, "h": 0.2,
         "items": [{"value": "$4.33M"}, {"value": "$2.10M"}, {"value": "$1.25M"}, {"value": "$0.98M"}],
         "style": {"valueFontSize": 120}},
    ])) == [
        {"code": "kpi-overflow", "slide": 1, "element": "kpis",
         "message": "A 6-character value at valueFontSize 120 needs about 511px and each of the 4 cells is 422px: "
                    "values will run into each other. Lower valueFontSize to 96 or less."},
    ]


def test_a_box_off_the_slide() -> None:
    assert lint(_deck([
        {"id": "late", "type": "text", "x": 0.5, "y": 0.9, "w": 0.6, "h": 0.2, "content": "x", "style": {"fontSize": 40}},
    ])) == [
        {"code": "off-slide", "slide": 1, "element": "late",
         "message": "The box runs off the slide: x + w and y + h must stay within 0..1."},
    ]


def test_text_below_32px_on_the_1920_canvas() -> None:
    assert lint(_deck([
        {"id": "foot", "type": "text", "x": 0.06, "y": 0.93, "w": 0.5, "h": 0.05, "content": "Source: Q3", "style": {"fontSize": 20}},
    ])) == [
        {"code": "small-text", "slide": 1, "element": "foot",
         "message": "fontSize 20 is 7.5pt on the slide: too small to read when projected. Use 32 (12pt) or more."},
    ]


def test_the_decks_own_canvas() -> None:
    assert lint(_deck([
        {"id": "foot", "type": "text", "x": 0.06, "y": 0.9, "w": 0.5, "h": 0.08, "content": "Source: Q3", "style": {"fontSize": 26}},
    ], slideWidth=1440)) == []


def test_a_clean_slide_and_an_empty_deck() -> None:
    assert lint(_deck([
        {"id": "t", "type": "text", "x": 0.06, "y": 0.05, "w": 0.88, "h": 0.2, "content": "EMEA led Q3 revenue", "style": {"fontSize": 72, "weight": 700}},
        {"id": "r", "type": "shape", "shape": "rect", "x": 0.06, "y": 0.27, "w": 0.06, "h": 0.006},
    ])) == []
    assert lint({"id": "d", "title": "D", "theme": {"name": "t"}, "slides": []}) == []

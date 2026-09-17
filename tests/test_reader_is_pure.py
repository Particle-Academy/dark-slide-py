"""``read()`` is a pure function of its bytes.

Until 0.3.1 it was not, in two places: the deck id came from ``time.time()``,
and an element whose ``<p:cNvPr>`` carried no ``name`` got a
``random.randint()`` number. The second is the worse one — the clock id only
moved across a tick, while a nameless shape got a new id on every single read.

It matters because reads get DIFFED. A consumer storing file history as reverse
edits compares two read structures, so a field that moves on its own turns a
diff of identical content into a whole-deck ``replace`` — a save that changed
nothing storing the entire deck, which is precisely what that design exists to
avoid. Reported as dark-slide#9, against all three engines at once: a parity
suite only detects DISAGREEMENT, and the three ports had the same bug, so it
agreed with itself perfectly.

Both halves are asserted without waiting for a clock tick, deliberately: a test
that reads twice and hopes to straddle a second boundary passes by luck. Same
bytes agree; different bytes disagree.
"""

from __future__ import annotations

import io
import re
import zipfile
import zlib
from typing import Any

from dark_slide import PptxReader, read, to_bytes
from tests.fixtures import PNG_1x1

DECK: dict[str, Any] = {
    "id": "pure",
    "title": "Purity",
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {"id": "t1", "type": "text", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2, "content": "Hello"},
                {"id": "r1", "type": "shape", "shape": "rect", "x": 0.6, "y": 0.1, "w": 0.2, "h": 0.2, "fill": "#FF0000"},
                {"id": "i1", "type": "image", "x": 0.1, "y": 0.4, "w": 0.2, "h": 0.2, "src": PNG_1x1, "fit": "contain"},
                {
                    "id": "tb1",
                    "type": "table",
                    "x": 0.1,
                    "y": 0.7,
                    "w": 0.8,
                    "h": 0.2,
                    "columns": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
                    "rows": [{"a": "1", "b": "2"}],
                },
            ],
        },
        {
            "id": "s2",
            "layout": "blank",
            "elements": [{"id": "t2", "type": "text", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2, "content": "Second"}],
        },
    ],
}

BYTES = to_bytes(DECK)

_NAME_ATTR = re.compile(r'(<p:cNvPr\b[^>]*?)\s+name="[^"]*"')


def _nameless_bytes() -> bytes:
    """The same deck with every ``name`` attribute stripped off its slide parts.

    A deck DarkSlide wrote always names its shapes, so its own output never
    reaches the fallback and a round-trip test cannot see this bug at all. Files
    from other producers do reach it — a nameless ``<p:cNvPr>`` is what a
    consumer importing arbitrary decks is handed.
    """
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(BYTES)) as source:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                payload = source.read(name)
                if name.startswith("ppt/slides/slide"):
                    payload = _NAME_ATTR.sub(r"\1", payload.decode("utf-8")).encode("utf-8")
                target.writestr(name, payload)

    return out.getvalue()


NAMELESS = _nameless_bytes()


def _element_ids(deck: dict[str, Any]) -> list[str]:
    return [element["id"] for slide in deck["slides"] for element in slide.get("elements", [])]


def test_identical_bytes_give_an_identical_structure() -> None:
    assert read(BYTES) == read(BYTES)


def test_elements_with_no_name_to_borrow_an_id_from_are_stable() -> None:
    first = read(NAMELESS)
    second = read(NAMELESS)

    # Named early, because a bare structure diff says nothing about WHICH field
    # moved.
    assert _element_ids(first) != []
    assert _element_ids(second) == _element_ids(first)
    assert second == first


def test_one_reader_instance_carries_no_state_between_files() -> None:
    reader = PptxReader()

    fresh = PptxReader().from_bytes(NAMELESS)
    reader.from_bytes(BYTES)

    assert reader.from_bytes(NAMELESS) == fresh


def test_two_different_decks_get_two_different_ids() -> None:
    # The clock id's other half: ``time.time()`` does not only move, it also
    # COLLIDES. Every deck imported in the same second shared one id, so a store
    # keyed on it overwrote one import with another.
    other = to_bytes({**DECK, "title": "A different deck entirely"})

    assert read(BYTES)["id"] != read(other)["id"]


def test_the_deck_id_comes_from_the_bytes_and_nothing_else() -> None:
    assert read(BYTES)["id"] == "imported-" + format(zlib.crc32(BYTES) & 0xFFFFFFFF, "08x")

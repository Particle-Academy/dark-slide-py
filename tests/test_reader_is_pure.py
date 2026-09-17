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

**0.3.1's fix was half a fix, and every test in this file passed anyway.** It
derived the id from the whole package, and the package embeds a clock stamp in
``docProps/core.xml`` — so the clock read moved from the reader to the WRITER.
Two reads of one buffer still agreed, which is all these cases asked, while a
deck saved and re-read got a different id EVERY time instead of one in five.
That broke pptx version history in a consumer's shipped product.

The lesson is in the shape of the cases below, not in the fix: every one of them
read the same buffer twice. A defect one serialisation away was outside what any
of them could see. ``test_a_save_that_changed_nothing_keeps_the_deck_id`` is the
case that reaches it.
"""

from __future__ import annotations

import copy
import io
import re
import zipfile
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

_MODIFIED = re.compile(r"<dcterms:modified[^>]*>[^<]*</dcterms:modified>")


def _restamped(data: bytes, modified: str) -> bytes:
    """The same package with ONLY ``docProps/core.xml`` replaced — a second save of one deck."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                payload = source.read(name)
                if name == "docProps/core.xml":
                    payload = _MODIFIED.sub(
                        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified>',
                        payload.decode("utf-8"),
                    ).encode("utf-8")
                target.writestr(name, payload)

    return out.getvalue()


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
    changed = copy.deepcopy(DECK)
    changed["slides"][0]["elements"][0]["content"] = "A different deck entirely"

    assert read(BYTES)["id"] != read(to_bytes(changed))["id"]


def test_a_renamed_deck_keeps_its_id_because_the_title_is_in_the_excluded_part() -> None:
    # A consequence of excluding ``docProps/core.xml`` whole, recorded here so it
    # is a decision rather than something the next person discovers. ``<dc:title>``
    # shares that part with the save timestamp, so a rename does not move the id
    # — the returned ``title`` still changes, so a differ still sees the rename,
    # and treating a renamed deck as the same deck is defensible on its own
    # terms. Narrowing the exclusion to the two ``<dcterms:*>`` elements would
    # change this, at the cost of regexing XML inside the digest path in three
    # engines; measured as unnecessary and deliberately not done.
    renamed = read(to_bytes({**DECK, "title": "Renamed, same deck"}))
    original = read(BYTES)

    assert renamed["title"] != original["title"]
    assert renamed["id"] == original["id"]


def test_the_deck_id_comes_from_the_deck_not_from_when_it_was_saved() -> None:
    # The deterministic form of the case below, and the one that says WHY:
    # ``docProps/core.xml`` is the only entry a second save of one deck changes,
    # so the id must not depend on it. Measured, not assumed — of this package's
    # 43 entries, it is the only one that differs across a save.
    stamped = _restamped(BYTES, "2019-01-01T00:00:00Z")

    assert stamped != BYTES
    assert read(stamped)["id"] == read(BYTES)["id"]


def test_a_save_that_changed_nothing_keeps_the_deck_id() -> None:
    """The consumer-shaped case: every other test here reads ONE buffer twice.

    A defect that needs a second serialisation to appear is outside what any of
    them can see, which is exactly how 0.3.1 shipped.

    It starts from the SETTLED read form rather than from the authored deck,
    because the reader is lossy by design — a composite comes back as the table
    it became — so the first read-write-read genuinely changes the deck and is
    supposed to change the id with it. What must hold is that it then stops.

    **This port's own writer cannot produce the failure**, and that is worth
    knowing rather than hiding behind a green tick: ``_build_core_props`` stamps
    ``EPOCH_TIMESTAMP`` and honours ``metadata.created``, so it never reads the
    clock and two saves here are byte-identical. The PHP and Node engines DO
    stamp the clock, and a Python consumer overwhelmingly reads packages those
    two wrote — so the second save below is re-stamped, which is what a file
    round-tripped through either of them actually looks like.
    """
    settled = read(to_bytes(read(BYTES)))

    # This engine's own second save: byte-identical, so it proves the fixed
    # point but not the contract.
    assert read(to_bytes(settled)) == settled

    # A second save as the sibling engines write it — a new timestamp in
    # docProps/core.xml and nothing else changed.
    resaved = _restamped(to_bytes(settled), "2031-06-05T12:00:00Z")

    assert read(resaved)["id"] == settled["id"]
    assert read(resaved) == settled

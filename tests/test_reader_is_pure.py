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

**It took three releases to state the property at the right level**, and the
first two both passed a suite that looked thorough::

    0.3.1  id = digest(whole package)           followed the WRITER's clock
    0.3.2  id = digest(package minus core.xml)  removed the clock, kept bytes
    0.3.3  id = digest(the deck read() returns)

The middle one is the instructive failure. Excluding the clock-bearing part
removed one source of byte variance and left the others: a deck carrying a shape
or a code block re-serialises to different ``ppt/slides/slideN.xml`` bytes, so
the id still moved while the structure sat perfectly still. A digest of bytes
identifies a SERIALISATION; two serialisations of one deck are not byte-equal,
and no exclusion list was ever going to make them so.

So the property is now: **any two byte layouts that read to the same structure
get the same id.** Note what that does NOT say — that a file from another
producer and one of ours "of the same deck" agree. That holds only as far as
``read()`` normalises them to the same structure, which is not promised.
``tests/pptx/foreign-libreoffice.pptx`` shows both halves.
"""

from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from pathlib import Path
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

#: Fixtures live in ``tests/pptx/`` rather than ``tests/fixtures/`` because
#: ``tests/fixtures.py`` is a MODULE this suite imports. A directory of the same
#: name resolves today — a regular module outranks a namespace package — but it
#: stops resolving the moment someone adds an ``__init__.py``, and a trap that
#: springs on an unrelated edit is not worth the tidier name.
PPTX_DIR = Path(__file__).parent / "pptx"

#: A ``.pptx`` written by a genuinely independent producer.
#:
#: Regenerate with LibreOffice — reproducible, and the reason a binary is
#: committed rather than a generator nobody can run::
#:
#:     soffice --headless --convert-to pptx --outdir <dir> <ours.pptx>
#:
#: where ``<ours.pptx>`` is ``to_bytes(foreign-libreoffice-source.json)``. It is
#: LibreOffice, not PowerPoint; what matters is that the serialisation is not
#: ours, and its ``<p:cNvPr>`` / part layout / ordering are all its own.
FOREIGN = (PPTX_DIR / "foreign-libreoffice.pptx").read_bytes()

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


def test_a_renamed_deck_gets_a_different_id_because_a_title_is_content() -> None:
    # 0.3.2 did the opposite, as a side effect of excluding ``docProps/core.xml``
    # whole — ``<dc:title>`` lives in that part. Digesting the deck rather than
    # the package puts the title back where it belongs: ``read()`` returns it, so
    # it counts.
    renamed = read(to_bytes({**DECK, "title": "Renamed, and that is a change"}))
    original = read(BYTES)

    assert renamed["title"] != original["title"]
    assert renamed["id"] != original["id"]


def test_two_byte_layouts_of_one_structure_get_the_same_id() -> None:
    """THE property. Everything else in this file is a corollary of it.

    A shape element is the cheap way to induce it: our own writer does not
    re-serialise a read-back shape to the same ``ppt/slides/slide1.xml`` bytes,
    so these two packages genuinely differ on disk while reading to one deck. The
    byte-difference is asserted first, because a test where the two buffers
    happened to be identical would pass while proving nothing.
    """
    deck = {
        "id": "two-layouts",
        "title": "Two Layouts",
        "theme": {"name": "default"},
        "slides": [{"id": "s1", "layout": "blank", "elements": [
            {"id": "r1", "type": "shape", "shape": "rect", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "fill": "#FF0000"},
        ]}],
    }

    layout_a = to_bytes(deck)
    read_a = read(layout_a)
    layout_b = to_bytes(read_a)
    read_b = read(layout_b)

    without_id = lambda d: {k: v for k, v in d.items() if k != "id"}  # noqa: E731

    assert layout_b != layout_a
    assert without_id(read_b) == without_id(read_a)
    assert read_b["id"] == read_a["id"]


def test_a_foreign_producer_and_our_reserialisation_of_it_read_to_one_id() -> None:
    """The consumer's production shape.

    Version 1 of a deck is the file a user uploaded, every version after it is
    ours. So the first edit of every upload diffs a FOREIGN serialisation against
    one of ours.

    Neither this repo nor its two siblings had a single ``.pptx`` fixture before
    this one — every fixture was generated by our own writer at test time, which
    is the same blind spot that left the reader's RNG path unexercised for
    several minor versions.
    """
    first = read(FOREIGN)
    ours = to_bytes(first)
    second = read(ours)

    assert first["slides"]
    assert ours != FOREIGN
    assert second["id"] == first["id"]


def test_it_does_not_claim_a_foreign_file_and_ours_share_an_id() -> None:
    """The limit of the property, asserted so nobody widens the claim by accident.

    ``read()`` recovers what it can model; LibreOffice's rendering of this deck
    and ours do not reduce to the same structure, so the two ids differ —
    correctly. The guarantee is about byte layouts of one STRUCTURE, not about
    two producers' idea of one deck.
    """
    source = json.loads((PPTX_DIR / "foreign-libreoffice-source.json").read_text(encoding="utf-8"))

    assert read(FOREIGN)["id"] != read(to_bytes(source))["id"]


def test_only_ascii_keys_appear_which_is_what_lets_three_engines_sort_alike() -> None:
    """The canonical encoding sorts map keys, and the three engines' sorts agree
    only below U+10000 (JS sorts UTF-16 code units, PHP bytes, Python code
    points). Every key a read deck contains is machine-generated, so this is true
    by construction — checked rather than assumed, because the digest silently
    depends on it.
    """
    keys: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                keys.add(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(read(BYTES))
    walk(read(FOREIGN))

    assert keys
    assert [k for k in keys if re.search(r"[^\x20-\x7E]", k)] == []


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

    **This port's own writer cannot produce the clock half of the failure**, and
    that is worth knowing rather than hiding behind a green tick:
    ``_build_core_props`` stamps ``EPOCH_TIMESTAMP`` and honours
    ``metadata.created``, so it never reads the clock and two saves here are
    byte-identical for THIS deck. The PHP and Node engines DO stamp the clock,
    and a Python consumer overwhelmingly reads packages those two wrote — so the
    second save below is re-stamped, which is what a file round-tripped through
    either of them actually looks like.

    Byte variance is not only the clock, though, which is the whole lesson of
    0.3.2: see ``test_two_byte_layouts_of_one_structure_get_the_same_id``, which
    induces it with a shape and needs no timestamp at all.
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

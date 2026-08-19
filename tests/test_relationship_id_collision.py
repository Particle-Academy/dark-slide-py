"""A pinned, deliberately-replicated defect: colliding slide relationship ids.

**This file asserts that a bug is still present.** It is meant to fail, and when
it does the correct response is to delete it — not to weaken it.

## The bug

`dark-slide` allocates image relationship ids as `"rId" + <global media
counter>`, while a slide's own relationships start at `rId1` for its layout and
`rId2` for its notesSlide. Those two id spaces are separate counters writing
into the same `_rels` part, so they collide:

    ppt/slides/_rels/slide1.xml.rels
        rId1  slideLayout -> ../slideLayouts/slideLayout1.xml
        rId1  image       -> ../media/image1.png        <-- duplicate

Relationship ids must be unique within a part. An `r:embed="rId1"` on that slide
resolves to whichever entry the reader happens to pick, so this is a malformed
OPC package rather than merely a non-canonical one.

## Why it is replicated here rather than fixed

`.ai/plans/polyglot/parity/documents.md` §1.4 rules on exactly this: fix it in
every engine in one release train (its step U5), never unilaterally in a port,
because a one-sided fix breaks part-level parity — and part-level parity is the
entire contract this package is held to. The PHP and Node engines were both
verified to emit the bytes below; the Python port reproduces them.

## What that plan got wrong, and why this file exists

§1.4 describes the trigger as *"a slide that has notes **and** whose first image
is the deck's second media file"* — which reads like a corner case, and is
presumably why no fixture covers it. **The real trigger is one slide containing
one image.** Every deck with a picture, from either shipped engine, has a
duplicate relationship id.

`tests/test_package_validity.py` therefore does NOT assert id uniqueness for
this package, the way its `holy-sheet-py` and `last-word-py` counterparts do. A
uniqueness assertion here would have to be skipped or softened, and a softened
assertion is how a defect stops being visible. Asserting the defect instead
keeps it in the log and makes its removal a deliberate, greppable event.
"""

from __future__ import annotations

import base64
import io
import struct
import zlib
import zipfile
from xml.etree import ElementTree

import dark_slide

REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _png(width: int, height: int) -> str:
    """A real PNG, small enough to inline, valid enough to be embedded."""
    body = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = struct.pack(">I", len(body)) + b"IHDR" + body
    ihdr += struct.pack(">I", zlib.crc32(b"IHDR" + body) & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    raw = b"\x89PNG\r\n\x1a\n" + ihdr + iend
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _image_element(element_id: str, src: str) -> dict:
    return {"id": element_id, "type": "image", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "src": src}


# Slide 1: ONE image, no notes -- the minimal trigger, and the one §1.4 misses.
# Slide 2: notes plus an image -- the combination §1.4 does describe.
COLLIDING_DECK = {
    "id": "deck-relids",
    "title": "RelIdCollision",
    "theme": {"name": "default"},
    "slides": [
        {"id": "s1", "layout": "content", "elements": [_image_element("e1", _png(10, 10))]},
        {
            "id": "s2",
            "layout": "content",
            "notes": "speaker notes on this slide",
            "elements": [_image_element("e2", _png(20, 20))],
        },
    ],
}


def _slide_rel_ids() -> dict[str, list[str]]:
    package = zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(COLLIDING_DECK)))
    out: dict[str, list[str]] = {}
    for part in sorted(package.namelist()):
        if part.endswith(".rels") and "/slides/" in part:
            out[part] = [
                node.get("Id") or ""
                for node in ElementTree.fromstring(package.read(part)).iter(f"{REL_NS}Relationship")
            ]
    return out


def test_a_single_image_on_a_slide_already_collides() -> None:
    """The minimal reproduction: one slide, one image, no notes."""
    ids = _slide_rel_ids()["ppt/slides/_rels/slide1.xml.rels"]

    assert ids == ["rId1", "rId1"], (
        "slide 1 no longer emits a duplicate rId1. If the engines were fixed in one "
        "release train, DELETE this file and add the id-uniqueness assertion to "
        "tests/test_package_validity.py, matching holy-sheet-py and last-word-py."
    )


def test_notes_plus_an_image_collides_on_the_next_id() -> None:
    """The combination the polyglot plan does describe, for completeness."""
    ids = _slide_rel_ids()["ppt/slides/_rels/slide2.xml.rels"]

    assert ids == ["rId1", "rId2", "rId2"], (
        "slide 2's layout/notesSlide/image id allocation changed. See this module's "
        "docstring before deciding whether that is a fix or a regression."
    )


def test_the_targets_behind_the_colliding_ids_are_genuinely_different() -> None:
    """Rules out a benign reading -- the two entries do not point at one part.

    Without this, "duplicate id" could be dismissed as a harmless repeat of the
    same relationship. It is not: `rId1` on slide 1 names both the layout and
    the image, so an `r:embed="rId1"` resolves to whichever the reader picks.
    """
    package = zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(COLLIDING_DECK)))
    targets = [
        (node.get("Id"), node.get("Target"))
        for node in ElementTree.fromstring(
            package.read("ppt/slides/_rels/slide1.xml.rels")
        ).iter(f"{REL_NS}Relationship")
    ]

    assert len({target for _, target in targets}) == 2, "expected two distinct targets"
    assert len({rid for rid, _ in targets}) == 1, "expected both to share one id"

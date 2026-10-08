"""``docProps/core.xml``'s timestamps are an INPUT when the deck supplies them.

dark-slide#10. This port has honoured ``metadata.created`` / ``metadata.modified``
since its first release, with ``EPOCH_TIMESTAMP`` as the default -- PHP and Node
embedded their clock unconditionally and had no override at all, so two
``to_bytes()`` calls on one deck a second apart produced different bytes there.

Both now honour the same two keys, with the same ``modified``-falls-back-to-
``created`` rule. **Their default is still the clock and this port's is still the
sentinel**, which is a deliberate, documented divergence rather than an accident:
a golden fixture is impossible without byte stability, and ``fancy-conformance``
treats a determinism flag as a precondition for a writer suite at all.

These assertions existed only implicitly here, inside the determinism and reader
purity suites. They are written out so the three engines carry the SAME test of
the shared half of the contract -- the part a consumer relies on when it writes
one deck for three engines.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from dark_slide import to_bytes
from dark_slide.writer.pptx_writer import EPOCH_TIMESTAMP

W3CDTF_PREFIX = '<dcterms:created xsi:type="dcterms:W3CDTF">'


def core_xml_of(deck: dict[str, Any]) -> str:
    with zipfile.ZipFile(io.BytesIO(to_bytes(deck))) as archive:
        return archive.read("docProps/core.xml").decode("utf-8")


def deck_with_metadata(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "deck-timestamps",
        "title": "Timestamps",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "elements": [
                    {
                        "id": "e1",
                        "type": "text",
                        "x": 0.1,
                        "y": 0.4,
                        "w": 0.8,
                        "h": 0.2,
                        "content": "Hello",
                        "format": "plain",
                    }
                ],
            }
        ],
        "metadata": metadata if metadata is not None else {},
    }


def test_honours_created_and_modified() -> None:
    xml = core_xml_of(
        deck_with_metadata({"created": "2020-02-02T03:04:05Z", "modified": "2021-03-03T04:05:06Z"})
    )

    assert f'{W3CDTF_PREFIX}2020-02-02T03:04:05Z</dcterms:created>' in xml
    assert '<dcterms:modified xsi:type="dcterms:W3CDTF">2021-03-03T04:05:06Z</dcterms:modified>' in xml


def test_modified_falls_back_to_created_not_the_default() -> None:
    # A deck that states when it was made and says nothing about edits is not a
    # deck modified at the sentinel date. PHP and Node match this exactly.
    xml = core_xml_of(deck_with_metadata({"created": "2020-02-02T03:04:05Z"}))

    assert '<dcterms:modified xsi:type="dcterms:W3CDTF">2020-02-02T03:04:05Z</dcterms:modified>' in xml


def test_byte_stable_when_the_deck_supplies_its_timestamps() -> None:
    deck = deck_with_metadata({"created": "2020-02-02T03:04:05Z", "modified": "2020-02-02T03:04:05Z"})

    assert to_bytes(deck) == to_bytes(deck)


def test_defaults_to_the_sentinel_not_the_clock() -> None:
    # THE DIVERGENCE, asserted rather than remembered. PHP and Node write their
    # clock here. If this ever starts reading the clock, every golden in this
    # repo stops being reproducible and the determinism suite goes flaky rather
    # than red -- so it is pinned explicitly.
    xml = core_xml_of(deck_with_metadata())

    assert f"{W3CDTF_PREFIX}{EPOCH_TIMESTAMP}</dcterms:created>" in xml


def test_escapes_a_supplied_timestamp() -> None:
    # Consumer input, so it cannot be pasted in. An unescaped value would let a
    # deck close the element early and rewrite the rest of the part.
    xml = core_xml_of(deck_with_metadata({"created": "</dcterms:created><evil>&"}))

    assert "<evil>" not in xml
    assert "&lt;/dcterms:created&gt;&lt;evil&gt;&amp;" in xml


def test_ignores_a_non_string_or_empty_timestamp() -> None:
    for metadata in ({"created": ""}, {"created": 12345}, {"created": ["x"]}, {"created": None}):
        xml = core_xml_of(deck_with_metadata(metadata))

        assert f"{W3CDTF_PREFIX}{EPOCH_TIMESTAMP}</dcterms:created>" in xml

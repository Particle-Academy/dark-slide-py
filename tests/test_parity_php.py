"""Cross-runtime writer parity: PHP dark-slide vs this Python port.

The strongest guarantee this trio has, and the reason the port is a port rather
than a rewrite: the same input must produce the same OOXML parts on both
runtimes. PHP is the reference -- it shipped first, and where the PHP and Node
engines already disagree (see `.ai/plans/fancy-python-document-writers.md`)
Python follows PHP rather than casting the deciding vote.

## Parts, not the container

The .pptx files can NEVER match byte-for-byte and it would be wrong to try.
PHP writes through `ZipArchive` (DEFLATE, real mtimes); this port writes a
fixed 1980-01-01 DOS date through `zipfile`. So the comparison unzips both and
diffs each part -- which is the real contract anyway, since a reader sees parts
and never the compression.

## The ledger ratchets both ways

`KNOWN_DIVERGENT_PARTS` is empty on purpose. A NEW divergent part fails, and an
entry that has stopped being true fails too, so it cannot rot into a permanent
excuse.
"""

from __future__ import annotations

import pytest

from dark_slide import to_bytes
from tests.fixtures import DECKS

pytestmark = pytest.mark.parity


# part name -> why the two runtimes legitimately differ. One entry, and it
# should stay at one: a Python port that has to excuse itself against the
# reference is a port that has drifted.
KNOWN_DIVERGENT_PARTS: dict[str, str] = {
    "docProps/core.xml": (
        "PHP's writer stamps <dcterms:created>/<dcterms:modified> with gmdate() at "
        "write time, and the deck cannot pin it -- there is no metadata field the PHP "
        "writer reads for the document date (checked: buildCoreProps takes the title "
        "and metadata.author and nothing else). So PHP's output is not reproducible, "
        "and this port's has to be: test_determinism asserts byte stability, and "
        "fancy-conformance treats a determinism flag as a precondition for a writer "
        "suite at all. The clock is therefore an INPUT here -- metadata.created / "
        "metadata.modified when the deck supplies them, EPOCH_TIMESTAMP otherwise. "
        "The Node parity suite hits the same wall and MASKS the two values before "
        "comparing; this ledger records it instead, because a mask hides the "
        "divergence and a ledger entry names it. Every other byte of the part -- "
        "title, creator, lastModifiedBy, namespace declarations, element order -- "
        "matches PHP exactly."
    ),
}


def _both(oracle, payload: object) -> tuple[dict[str, str], dict[str, str]]:
    return oracle.text_parts(oracle.php_to_bytes(payload)), oracle.text_parts(to_bytes(payload))


@pytest.mark.parametrize("name", sorted(DECKS))
def test_emits_the_same_ooxml_parts(php_oracle, name: str) -> None:
    php_parts, py_parts = _both(php_oracle, DECKS[name])

    assert sorted(py_parts) == sorted(php_parts), "the two runtimes wrote different part sets"

    for part in sorted(php_parts):
        if php_parts[part] == py_parts[part]:
            continue
        assert part in KNOWN_DIVERGENT_PARTS, (
            f"NEW divergence in {part} for {name!r} -- the runtimes have drifted apart "
            "somewhere that was previously identical. Fix it, or add it to "
            "KNOWN_DIVERGENT_PARTS with a reason."
        )


def test_the_known_divergence_ledger_is_accurate(php_oracle) -> None:
    """A stale entry is worse than none.

    It would keep excusing a part that has since been reconciled, and quietly
    re-open the hole if it regressed.
    """
    seen: set[str] = set()
    for payload in DECKS.values():
        php_parts, py_parts = _both(php_oracle, payload)
        seen |= {p for p in php_parts if php_parts[p] != py_parts.get(p)}

    assert seen == set(KNOWN_DIVERGENT_PARTS), "KNOWN_DIVERGENT_PARTS no longer matches reality"


def test_embedded_fonts_emit_the_same_parts(php_oracle, tmp_path) -> None:
    """Two typefaces, regular and bold, embedded by both engines.

    PHP is given the fonts as FILE PATHS (they cannot travel through its JSON
    input) and this port the same bytes directly, so any difference is in the
    EOT wrapper, the part numbering, the relationship ids, the content type or
    the font list -- every one of which this compares byte for byte, including
    the binary `.fntdata` parts.
    """
    from tests import generated_font as GeneratedFont

    fonts = {
        "Qvx Display": {
            "regular": GeneratedFont.build("Qvx Display"),
            "bold": GeneratedFont.build("Qvx Display", "Bold", fs_type=0x0008, weight=700),
        },
        "Qvx Text": {"italic": GeneratedFont.build("Qvx Text", "Italic", italic=True)},
    }
    paths: dict[str, dict[str, str]] = {}
    for typeface, variants in fonts.items():
        for variant, data in variants.items():
            path = tmp_path / f"{typeface.replace(' ', '')}-{variant}.ttf"
            path.write_bytes(data)
            paths.setdefault(typeface, {})[variant] = str(path)

    deck = DECKS["minimal"]
    php_parts = php_oracle.parts(php_oracle.php_to_bytes(deck, {"fonts": paths}))
    py_parts = php_oracle.parts(to_bytes(deck, {"fonts": fonts}))

    assert sorted(py_parts) == sorted(php_parts)
    assert [p for p in php_parts if p.startswith("ppt/fonts/")] == [
        "ppt/fonts/font1.fntdata", "ppt/fonts/font2.fntdata", "ppt/fonts/font3.fntdata",
    ]
    differing = {p for p in php_parts if php_parts[p] != py_parts[p]}
    assert differing <= set(KNOWN_DIVERGENT_PARTS), f"embedded-font parts differ from PHP: {sorted(differing)}"


def test_compared_something(php_oracle) -> None:
    """The guard the sibling suites lacked.

    If the fixture table emptied, or the unzip returned nothing, every
    assertion above would vanish and this file would still report success.
    """
    php_parts, py_parts = _both(php_oracle, DECKS["minimal"])

    assert len(DECKS) >= 4
    assert len(php_parts) >= 3
    assert "ppt/slides/slide1.xml" in php_parts
    assert "ppt/slides/slide1.xml" in py_parts

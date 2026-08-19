"""Cross-runtime READER parity. Ported from ``dark-slide-js/tests/reader-parity.test.ts``.

The writer half of the contract is byte-exact; the reader half cannot be, and
should not try: the deck model is JSON, so the comparison is STRUCTURAL. Both
engines get the same ``.pptx`` (written by this port, which the writer parity
suite has already proven matches PHP's byte for byte) and must recover the same
deck.

Two things are normalised away, each for a stated reason:

* **The deck ``id``.** Both engines mint ``imported-<hex of the clock>`` on
  import, so the two will only agree if they run in the same second. It carries
  no document content.
* **Empty ``[]`` vs empty ``{}``.** PHP has one array type and ``json_encode``
  writes an empty associative array as ``[]``; Python distinguishes them. The
  difference is an artefact of PHP's type system, not of either reader.

Nothing else is normalised. Element types, geometry, text, table contents,
backgrounds, notes and embedded image bytes are compared exactly.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import dark_slide
from tests import _oracle
from tests.fixtures import DECKS

pytestmark = pytest.mark.parity

PHP_READ_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "php_read.php"

#: The decks whose contents the reader is meant to recover. Fixtures built to
#: pin WRITER behaviour (rounding ties, chart modes, rel-id collisions) are not
#: reader material and are excluded by name rather than by a filter, so adding
#: one is a decision rather than an accident.
READABLE = ["minimal", "titleText", "richSlide", "multiNotes", "imageFits", "escapingAndLoose"]

_EMPTY = "∅empty"


def _normalize(value: Any) -> Any:
    """Collapse the two PHP/JSON ambiguities and sort keys for comparison."""
    if (isinstance(value, (list, dict))) and len(value) == 0:
        return _EMPTY
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # PHP writes 0.5 and Python 0.5; but PHP writes an integral float as
        # an int in JSON, so compare numerically.
        return float(value)
    return value


def _strip_volatile(deck: dict[str, Any]) -> dict[str, Any]:
    out = dict(deck)
    out.pop("id", None)
    return out


def _php_read(path: Path) -> dict[str, Any]:
    binary = _oracle.php_binary()
    src = _oracle.php_src_root()
    assert binary is not None and src is not None

    env = dict(os.environ)
    env["DARK_SLIDE_PHP_SRC"] = str(src)
    result = subprocess.run(
        [binary, str(PHP_READ_SCRIPT), str(path)], capture_output=True, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"the PHP reader exited {result.returncode}: "
            f"{result.stderr.decode('utf-8', 'replace')[:2000]}"
        )
    return json.loads(result.stdout.decode("utf-8"))


@pytest.mark.parametrize("name", READABLE)
def test_both_readers_recover_the_same_deck(php_oracle, tmp_path, name: str) -> None:
    payload = dark_slide.to_bytes(DECKS[name])
    pptx = tmp_path / f"{name}.pptx"
    pptx.write_bytes(payload)

    php_deck = _php_read(pptx)
    py_deck = dark_slide.read(payload)

    assert _normalize(_strip_volatile(py_deck)) == _normalize(_strip_volatile(php_deck))


def test_the_reader_comparison_is_not_vacuous(php_oracle, tmp_path) -> None:
    """The guard the sibling suites lacked.

    A reader that returned ``{"slides": []}`` on both sides would satisfy every
    assertion above. This one asserts the comparison had content in it.
    """
    payload = dark_slide.to_bytes(DECKS["richSlide"])
    pptx = tmp_path / "rich.pptx"
    pptx.write_bytes(payload)

    php_deck = _php_read(pptx)
    assert len(READABLE) >= 4
    assert len(php_deck["slides"]) == 1
    assert len(php_deck["slides"][0]["elements"]) >= 3
    assert any(e.get("type") == "table" for e in php_deck["slides"][0]["elements"])

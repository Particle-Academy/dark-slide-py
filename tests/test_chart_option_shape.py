"""What a chart element's ``option`` may contain, and whether the schema says so.

``option`` exported as ``{"type": "object"}`` and nothing more -- the same gap as
a table's ``columns``/``rows``, ending in the same silent failure. The React
renderer hands ``option`` straight to ECharts, which draws an EMPTY CANVAS for a
shape it does not recognise and raises nothing; this writer hands it to the
translator, which returns ``None`` for anything it cannot read and leaves a titled
PLACEHOLDER. Both are full-size and empty. Raised by a consumer generating their
writer vocabulary from this schema, in the fancy-slides#14 thread.

Two halves, because a description is only worth publishing if it is true: every
option key the TRANSLATOR reads is described, found by reading the translator
rather than a hand list; and a chart authored as the schema describes emits a
native chart part rather than the placeholder.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import zipfile
from typing import Any

from dark_slide import json_schema, to_bytes, validate
from dark_slide.helpers.chart_translator import SUPPORTED_TYPES, translate

TRANSLATOR = pathlib.Path(__file__).resolve().parents[1] / "src" / "dark_slide" / "helpers" / "chart_translator.py"


def _option() -> dict[str, Any]:
    props = json_schema()["properties"]["slides"]["items"]["properties"]["elements"]["items"]["properties"]
    return props["option"]


def _part_names(element: dict[str, Any]) -> list[str]:
    deck = {
        "id": "cos",
        "title": "Chart option",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "elements": [{"id": "c", "type": "chart", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.6, **element}],
            }
        ],
    }
    with zipfile.ZipFile(io.BytesIO(to_bytes(deck))) as zf:
        return zf.namelist()


def _deck(element: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "cos",
        "title": "Chart option",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "elements": [{"id": "c", "type": "chart", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.6, **element}],
            }
        ],
    }


def test_describes_every_option_key_the_translator_reads() -> None:
    # Found by reading the translator, not by listing keys here: a key added
    # there and not described here must fail this.
    source = TRANSLATOR.read_text(encoding="utf-8")
    read = sorted(set(re.findall(r'option\.get\("([A-Za-z]+)"\)', source)))

    # The scan has to find the keys, or the loop below proves nothing.
    assert "series" in read
    assert "xAxis" in read
    assert "title" in read

    described = _option()["properties"]
    for key in read:
        # `categories` is deliberately NOT described: the Node engine honours it
        # standalone while this one reads it only alongside an `xAxis` without
        # `data`. Publishing a key three engines disagree on would make the
        # schema false somewhere.
        if key == "categories":
            assert "categories" not in described
            continue
        assert key in described, key
        assert described[key].get("description", "") != "", key


def test_describes_the_series_item_shape() -> None:
    series = _option()["properties"]["series"]

    for key in ("type", "name", "data", "smooth", "areaStyle"):
        assert key in series["items"]["properties"], key
    assert series["items"]["properties"]["type"]["enum"] == list(SUPPORTED_TYPES)


def test_says_what_happens_to_an_untranslatable_option() -> None:
    described = json.dumps(_option()).lower()

    assert "placeholder" in described
    assert "image" in described


def test_emits_a_native_chart_part_for_an_option_the_schema_describes() -> None:
    names = _part_names(
        {
            "option": {
                "title": {"text": "Revenue"},
                "xAxis": {"data": ["Q1", "Q2"]},
                "series": [{"type": "bar", "name": "ARR", "data": [120, 180]}],
            }
        }
    )

    assert "ppt/charts/chart1.xml" in names


def test_falls_back_to_a_placeholder_for_an_unsupported_series_type() -> None:
    # The counter-case. Without it the assertion above passes on a writer that
    # emits a chart part for everything.
    names = _part_names({"option": {"series": [{"type": "radar", "data": [1, 2]}]}})

    assert "ppt/charts/chart1.xml" not in names


def test_returns_none_rather_than_raising_for_a_non_object_option() -> None:
    # A deck written by the PHP engine serialises an empty option as `[]` -- PHP
    # cannot tell an empty list from an empty map. This raised AttributeError on
    # it while PHP and Node both returned null: one malformed element took down
    # the deck around it.
    assert translate([]) is None
    assert translate(None) is None
    assert translate("not an option") is None


def test_flags_a_chart_with_no_option_object_at_all() -> None:
    errors = validate(_deck({}))
    entry = next((e for e in errors if e["path"] == "/slides/0/elements/0/option"), None)

    assert entry is not None
    assert "series" in entry["hint"]


def test_does_not_flag_an_option_it_cannot_translate() -> None:
    # The narrowness is load-bearing: `write()` raises on any validator error, so
    # flagging this would turn a documented, tested fallback into a hard failure.
    # It did exactly that in the PHP engine while this was being written, and
    # that engine's V04 suite caught it.
    deck = _deck({"option": {"series": [{"type": "radar", "data": [1, 2]}]}})

    assert validate(deck) == []
    assert to_bytes(deck)


def test_pins_the_three_way_split_on_categories_with_no_xaxis() -> None:
    """Measured 2026-10-07.

    This engine IGNORES a standalone ``categories`` -- ``_extract_categories``
    seeds its candidates with ``[]``, which is already a list, so the fallback
    never fires -- and so does PHP, while Node honours it. A chart authored that
    way gets real labels from one engine and ``1, 2, 3 ...`` from the other two,
    silently, and the reference deck carries no chart so byte parity has never
    seen it.

    Pinned rather than fixed: resolving it changes the rendered output of existing
    decks, which is the owner's call. When it is made this fails in whichever
    engine moves, which is exactly what should happen.
    """
    spec = translate({"categories": ["Q1", "Q2"], "series": [{"type": "bar", "data": [1, 2]}]})
    assert spec is not None
    assert spec["categories"] == []

    # And the form that IS portable, published in the schema, does work.
    portable = translate({"xAxis": {"data": ["Q1", "Q2"]}, "series": [{"type": "bar", "data": [1, 2]}]})
    assert portable is not None
    assert portable["categories"] == ["Q1", "Q2"]

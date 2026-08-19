"""Run this package against the shared `fancy-conformance` fixture tables.

`shared/strings` names `particle-academy/dark-slide`'s
`Helpers\\MarkdownInline::tokenize` as its reference, so this package is not
merely *checked* by that table — it is the implementation the goldens were
taken from.

That suite exists for a reason that lands squarely on Python. Its own manifest
says it: PHP indexes those strings **by byte** and the TypeScript port **by
UTF-16 code unit**, and they agree — but *incidentally*, because both loops only
ever compare ASCII markers and cut at those positions, and neither a UTF-8
continuation byte nor a UTF-16 surrogate can collide with ASCII. Python is a
**third** scheme (code points), so the agreement has to be demonstrated here
rather than inherited. These rows are the demonstration.

`shared/decimal`'s `roundMoney` rows are also run, because `(int) round($v)`
half-away-from-zero is exactly `emu.php_round` — and *every* coordinate this
writer emits goes through it.

Four rules from `runners/README.md`, all honoured:

1. Run on every push and PR — not nightly, not at release.
2. A missing fixture checkout is a FAILURE, not a skip (the loader raises).
3. Print the summary unconditionally, including every skip and its reason.
4. Print and assert the pinned suite version.
"""

from __future__ import annotations

import pytest

from dark_slide.helpers.emu import php_round
from dark_slide.helpers.markdown_inline import tokenize
from tests.conformance import loader

PINNED_SUITE_VERSION = "0.3.0"


def test_the_pinned_fixture_version_is_the_one_on_disk() -> None:
    assert loader.version() == PINNED_SUITE_VERSION, (
        f"fancy-conformance is at {loader.version()}, this port pins "
        f"{PINNED_SUITE_VERSION}. Re-run the suites and move the pin deliberately."
    )


def _summary(suite: str, run_case) -> dict:
    summary = loader.run_table(suite, run_case)
    # Printed unconditionally. A bare "3 skipped" reads identically to full
    # coverage at a glance.
    print("\n" + loader.format_summary(summary))
    return summary


def test_inline_markdown_tokenizing_matches_the_shared_strings_table() -> None:
    def run(case: dict) -> list[dict]:
        # The table's run shape is {text, b, i, code} and nothing else. Comparing
        # the package's own richer run dicts against it would pass or fail for
        # reasons unrelated to string indexing, so project first.
        return [
            {
                "text": run["text"],
                "b": bool(run.get("b", False)),
                "i": bool(run.get("i", False)),
                "code": bool(run.get("code", False)),
            }
            for run in tokenize(case["input"]["text"])
        ]

    summary = _summary("shared/strings", run)
    assert summary["passed"] >= 6, "the strings table barely ran"
    assert summary["ok"], loader.format_summary(summary)


def test_round_money_matches_the_shared_decimal_table() -> None:
    rows = [c for c in loader.cases("shared/decimal") if c.get("fn") == "roundMoney"]

    # If the suite renamed the function, every assertion below would vanish and
    # this file would still be green.
    assert len(rows) >= 4, "no roundMoney rows found -- the runner is testing nothing"

    summary = _summary(
        "shared/decimal",
        lambda c: int(php_round(float(c["input"]["value"])))
        if c.get("fn") == "roundMoney"
        # The other two functions belong to holy-sheet, not this package. They
        # are excluded from the assertion by the count guard above rather than
        # by faking a pass.
        else c["expected"],
    )
    assert summary["ok"], loader.format_summary(summary)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.5, 1), (1.5, 2), (2.5, 3), (-0.5, -1), (-1.5, -2), (-2.5, -3)],
)
def test_php_round_is_half_away_from_zero_not_bankers(value: float, expected: int) -> None:
    """The single highest-frequency divergence risk in a Python port of this family.

    Python's builtin would answer 0, 2, 2, 0, -2, -2 here. dark-slide converts
    EVERY coordinate with `round(frac * 9144000)`, so a regression in this one
    helper moves the geometry of every shape on every slide.
    """
    assert int(php_round(value)) == expected

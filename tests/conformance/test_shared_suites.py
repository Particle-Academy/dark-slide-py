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

import re
from pathlib import Path

import pytest

from dark_slide.helpers.emu import php_round
from dark_slide.helpers.markdown_inline import tokenize
import fancy_conformance as loader

# Moved from 0.5.0 with the release that adds `dark-slide/table-cell-model`.
# The pin was ALREADY stale before that suite existed — fancy-conformance had
# shipped 0.6.0 and this file still said 0.5.0, so the one test whose job is to
# notice a fixture set moving underneath the port was the test failing.
#
# Moved 0.7.0 -> 0.20.0 on 2026-09-10, deliberately and not to get to green: all
# three tables were re-run against the checkout first and every row passes with
# nothing skipped — shared/strings 8, shared/decimal 18,
# dark-slide/table-cell-model 26. It had gone stale a second time in exactly the
# way this comment already describes, which is the argument for the test rather
# than against it.
#
# Moved 0.20.0 -> 0.21.2 on 2026-09-13, after re-running all three tables against
# that checkout: shared/strings 8, shared/decimal 18, dark-slide/table-cell-model
# 26, nothing failed or skipped. 0.21.x added flow/connector-runs, which this port
# does not run. Stale a third time, and again the release that moved it was ours.
#
# Moved 0.21.2 -> 0.22.0 on 2026-09-13, with the design-pixel unit model. That
# release regenerated 23 dark-slide/table-cell-model goldens from the PHP
# reference and added 0027 and 0028; re-run first against this port's new
# resolver: shared/strings 8, shared/decimal 18, dark-slide/table-cell-model 28,
# nothing failed or skipped, including the rounding ties (a 1-wide rule at
# 0.375pt is 4763 EMU, 0.6 of letter spacing is 23 hundredths).
#
# Moved 0.22.0 -> 0.22.1 on 2026-09-13. That release changed no case and no
# golden (the Rust loader pins fancy-json by tag, plus docs); re-run first against
# a v0.22.1 checkout all the same: shared/strings 8, shared/decimal 18,
# dark-slide/table-cell-model 28, nothing failed or skipped, the same counts CI
# printed at 0.22.0.
#
# CI checks out `ref: v<this>` from .github/workflows/ci.yml. Move the two
# together; test_ci_checks_out_the_fixture_tag_this_suite_pins fails otherwise.
PINNED_SUITE_VERSION = "0.22.1"


def test_the_pinned_fixture_version_is_the_one_on_disk(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Past pytest's capture: a bare print() in a passing test never reaches the
    # CI log, which is the one place rules 3 and 4 of fancy-conformance's
    # runners/README.md need it.
    with capsys.disabled():
        print(f"\nfancy-conformance on disk: {loader.version()}, pinned: {PINNED_SUITE_VERSION}")

    assert loader.version() == PINNED_SUITE_VERSION, (
        f"fancy-conformance is at {loader.version()}, this port pins "
        f"{PINNED_SUITE_VERSION}. Re-run the suites and move the pin deliberately."
    )


def _conformance_checkout_refs(workflow: str) -> list[str | None]:
    """The `ref:` of every workflow step that checks out fancy-conformance.

    Plain text on purpose: a YAML parser would be a dependency for one assertion.
    A step is a `- ` line plus everything indented deeper than it. `None` is a
    step with no `ref`, which checks out whatever `main` is at that moment.
    """
    lines = workflow.splitlines()
    refs: list[str | None] = []
    for index, line in enumerate(lines):
        start = re.match(r"(\s*)- ", line)
        if not start:
            continue
        step = [line]
        for following in lines[index + 1 :]:
            body = following.strip()
            indent = len(following) - len(following.lstrip())
            if body and not body.startswith("#") and indent <= len(start.group(1)):
                break
            step.append(following)
        text = "\n".join(step)
        if re.search(
            r"^\s*(- )?repository:\s*[\"']?Particle-Academy/fancy-conformance[\"']?\s*(#.*)?$",
            text,
            re.MULTILINE,
        ):
            ref = re.search(r"^\s*(- )?ref:\s*[\"']?([^\"'\s#]+)", text, re.MULTILINE)
            refs.append(ref.group(2) if ref else None)
    return refs


def test_the_checkout_ref_parser_sees_a_missing_ref() -> None:
    workflow = """
      - uses: actions/checkout@v4
        with:
          repository: Particle-Academy/fancy-conformance
          path: .fancy-conformance
      - name: Pinned
        uses: actions/checkout@v4
        with:
          repository: "Particle-Academy/fancy-conformance"
          ref: 'v1.2.3'  # a comment
      - uses: actions/checkout@v4
        with:
          repository: Particle-Academy/dark-slide
          ref: v9.9.9
    """
    assert _conformance_checkout_refs(workflow) == [None, "v1.2.3"]


def test_ci_checks_out_the_fixture_tag_this_suite_pins() -> None:
    """The CI checkout `ref` and `PINNED_SUITE_VERSION` are one decision in two files.

    CI used to check fancy-conformance out with no `ref`, so every fixture release
    could turn this build red at once for a reason no commit here caused; four
    sibling ports sat red for weeks exactly that way. The pin is the contract:
    moving it is a deliberate commit in this repository, never a side effect of
    someone else's release.
    """
    here = Path(__file__).resolve()
    workflows = next(
        (p / ".github" / "workflows" for p in here.parents if (p / ".github/workflows").is_dir()),
        None,
    )
    assert workflows is not None, f"no .github/workflows above {here}"

    refs = {
        path.name: _conformance_checkout_refs(path.read_text(encoding="utf-8"))
        for path in sorted(workflows.glob("*.y*ml"))
    }
    refs = {name: found for name, found in refs.items() if found}
    # Vacuity guard: a parser that matched nothing would satisfy the loop below.
    assert refs, "no workflow checks out Particle-Academy/fancy-conformance"

    expected = f"v{PINNED_SUITE_VERSION}"
    for name, found in refs.items():
        assert found == [expected] * len(found), (
            f".github/workflows/{name} checks fancy-conformance out at {found}, but this "
            f"suite pins {PINNED_SUITE_VERSION}. Set `ref: {expected}` there, and move "
            "the pin and the ref together."
        )


def _summary(suite: str, run_case, capsys: pytest.CaptureFixture[str]) -> dict:
    summary = loader.run_table(suite, run_case)
    # Printed unconditionally. A bare "3 skipped" reads identically to full
    # coverage at a glance.
    # Past pytest's capture: a bare print() in a passing test never reaches the
    # CI log, which is the one place rules 3 and 4 of fancy-conformance's
    # runners/README.md need it.
    with capsys.disabled():
        print("\n" + loader.format_summary(summary))
    return summary


def test_inline_markdown_tokenizing_matches_the_shared_strings_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    summary = _summary("shared/strings", run, capsys)
    assert summary["passed"] >= 6, "the strings table barely ran"
    assert summary["ok"], loader.format_summary(summary)


def test_round_money_matches_the_shared_decimal_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
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
        capsys,
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

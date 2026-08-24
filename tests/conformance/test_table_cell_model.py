"""Run the shared ``dark-slide/table-cell-model`` fixtures against this port.

Why this suite exists ALONGSIDE the byte-parity one, which already compares
every OOXML part of a nine-slide reference deck against the PHP engine:

Byte parity proves the three engines agree **on the inputs it runs**. The
reference deck walks exactly one path through the resolution chain per cell, so
a port that collapsed two precedence layers — say, letting the header band beat
a column's own alignment — would emit identical bytes for that deck and be
wrong for every deck that exercises the other order. These rows walk the chain
one layer at a time, and each one fails by NAME.

The goldens live in ``fancy-conformance`` and are the output of running the PHP
reference. Nothing in this file restates them.
"""

from __future__ import annotations

from dark_slide.helpers import emu as Emu
from dark_slide.table import table_resolver
from tests.conformance import loader

SUITE = "dark-slide/table-cell-model"


def _shape(cell: dict) -> dict:
    """Project a resolved cell onto the suite's run shape.

    Every fractional quantity becomes the INTEGER unit the writer emits, then a
    string. That is the suite's own rule and it is load-bearing: the four
    fancy-conformance loaders do not agree on how a float golden is compared, so
    a suite carrying floats has a verdict that depends on which loader ran it.
    """
    borders = {}
    for side in ("left", "right", "top", "bottom"):
        spec = cell["borders"][side]
        borders[side] = (
            None
            if spec is None
            else {
                "widthEmu": str(Emu.from_pt(float(spec["width"]))),
                "color": spec["color"],
                "style": spec["style"],
            }
        )

    return {
        "text": cell["text"],
        "bold": "1" if cell["bold"] else "0",
        "italic": "1" if cell["italic"] else "0",
        "underline": "1" if cell["underline"] else "0",
        "color": cell["color"],
        "fill": cell["fill"],
        "align": cell["align"],
        "anchor": cell["anchor"],
        "fontSizeHundredths": str(Emu.hundredths_of_point(float(cell["fontSize"]))),
        "letterSpacingHundredths": str(Emu.hundredths_of_point(float(cell["letterSpacing"]))),
        "caps": cell["caps"],
        "padding": {
            side: str(Emu.from_pt(float(cell["padding"][side])))
            for side in ("left", "right", "top", "bottom")
        },
        "borders": borders,
        "colSpan": str(cell["colSpan"]),
        "rowSpan": str(cell["rowSpan"]),
        "merged": cell["merged"],
    }


def _run(case: dict):
    payload = case["input"]
    table = table_resolver.resolve(payload["element"], payload.get("theme", {}))

    if case["fn"] == "gridWidthsEmu":
        return [
            str(w)
            for w in table_resolver.column_widths_emu(table["columns"], int(payload["totalEmu"]))
        ]

    return _shape(table["rows"][payload["row"]]["cells"][payload["col"]])


def test_the_suite_has_rows_to_run() -> None:
    """A renamed or moved suite would otherwise make this file silently vacuous."""
    cases = loader.cases(SUITE)
    assert len(cases) >= 20, f"{SUITE} has {len(cases)} rows -- the runner is testing nothing"
    assert {c["fn"] for c in cases} == {"resolvedCell", "gridWidthsEmu"}


def test_the_resolver_matches_the_shared_table() -> None:
    summary = loader.run_table(SUITE, _run)
    # Printed unconditionally: a bare "3 skipped" reads identically to full
    # coverage at a glance.
    print("\n" + loader.format_summary(summary))
    assert summary["ok"], loader.format_summary(summary)
    assert summary["passed"] >= 20, "the table barely ran"

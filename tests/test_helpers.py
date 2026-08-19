"""The pure helpers, in isolation. Ported from ``dark-slide-js/tests/helpers.test.ts``.

Plus the cases that only exist in Python — ``php_round`` against the builtin,
and the PHP scalar-cast semantics ``util.py`` exists to reproduce.
"""

from __future__ import annotations

import math

import pytest

from dark_slide import Repairer, Validator
from dark_slide.helpers import color as Color
from dark_slide.helpers import emu as Emu
from dark_slide.helpers import markdown_inline as MarkdownInline
from dark_slide.helpers import syntax_highlighter as SyntaxHighlighter
from dark_slide.helpers import xml as Xml
from dark_slide.helpers.chart_translator import translate
from dark_slide.util import (
    gettype,
    is_numeric,
    php_float,
    php_int,
    php_json_encode,
    php_string,
    php_truthy,
)


def run(text: str, b: bool = False, i: bool = False, code: bool = False) -> dict:
    return {"text": text, "b": b, "i": i, "code": code}


# ── php_round ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.5, 1), (1.5, 2), (2.5, 3), (3.5, 4), (-0.5, -1), (-1.5, -2), (-2.5, -3), (0.4, 0), (-0.4, 0)],
)
def test_php_round_goes_half_away_from_zero(value: float, expected: int) -> None:
    assert Emu.php_round(value) == expected


def test_php_round_disagrees_with_the_builtin_on_ties() -> None:
    """The whole reason this helper exists.

    Python's builtin rounds half to EVEN, so 0.5, 2.5 and -1.5 all come back
    one off. Every coordinate in every deck is a ``round(frac * 9144000)``, so
    the builtin leaking in would shift thousands of attributes by one EMU.
    """
    ties = [0.5, 2.5, -1.5, 4.5]
    assert [Emu.php_round(v) for v in ties] != [round(v) for v in ties]
    assert [Emu.php_round(v) for v in ties] == [1, 3, -2, 5]


def test_emu_ties_land_where_php_puts_them() -> None:
    # 3/128 and 3/8 are exactly representable, and both products end in .5
    # with an EVEN integer part — the case the builtin gets wrong.
    assert 0.0234375 * Emu.DEFAULT_SLIDE_WIDTH == 214312.5
    assert 0.375 * Emu.DEFAULT_SLIDE_HEIGHT == 1928812.5
    assert Emu.from_frac_x(0.0234375) == 214313
    assert Emu.from_frac_y(0.375) == 1928813


def test_no_module_in_the_package_calls_the_builtin_round() -> None:
    """The rule with a failing assertion behind it, because review will not catch it.

    Parsed rather than grepped: a regex over source lines matches prose in a
    docstring (and, memorably, the ``round(`` inside ``_build_background(``).
    The AST sees only real calls.
    """
    import ast
    from pathlib import Path

    import dark_slide

    root = Path(dark_slide.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "round"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], "builtin round() called — use php_round: " + ", ".join(offenders)


# ── MarkdownInline ────────────────────────────────────────────────────────


def test_a_bold_run_splits_from_surrounding_plain_text() -> None:
    assert MarkdownInline.tokenize("a **b** c") == [run("a "), run("b", b=True), run(" c")]


def test_double_underscore_is_bold_too() -> None:
    assert MarkdownInline.tokenize("__x__") == [run("x", b=True)]


def test_an_italic_run_splits() -> None:
    assert MarkdownInline.tokenize("this *is* it") == [
        run("this "),
        run("is", i=True),
        run(" it"),
    ]


def test_a_code_run_swallows_markers_literally() -> None:
    assert MarkdownInline.tokenize("call `a**b`") == [run("call "), run("a**b", code=True)]


def test_snake_case_underscores_are_not_italic() -> None:
    assert MarkdownInline.tokenize("a_b_c snake_case") == [run("a_b_c snake_case")]
    assert MarkdownInline.tokenize("x_y") == [run("x_y")]


def test_an_unmatched_backtick_stays_literal() -> None:
    # The opening backtick flushes the buffer, then the remainder is appended
    # as plain text — two plain runs, neither of them code.
    assert MarkdownInline.tokenize("a `b") == [run("a "), run("`b")]


def test_an_empty_paragraph_yields_one_empty_run() -> None:
    assert MarkdownInline.tokenize("") == [run("")]


def test_unicode_cuts_land_in_the_same_places_as_on_bytes() -> None:
    """PHP indexes bytes, Node UTF-16 units, this codepoints — same result.

    The agreement is incidental, not designed: every cut is at an ASCII
    marker, and no UTF-8 continuation byte or UTF-16 surrogate half can equal
    an ASCII byte. Pinned here as well as in the parity fixture.
    """
    assert MarkdownInline.tokenize("日本 **強調** です") == [
        run("日本 "),
        run("強調", b=True),
        run(" です"),
    ]
    assert MarkdownInline.tokenize("emoji \U0001f389 `x` end") == [
        run("emoji \U0001f389 "),
        run("x", code=True),
        run(" end"),
    ]


def test_bullet_prefix_strips_dash_and_star_markers() -> None:
    assert MarkdownInline.bullet_prefix("- item") == (True, "item")
    assert MarkdownInline.bullet_prefix("* item") == (True, "item")
    assert MarkdownInline.bullet_prefix("plain") == (False, "plain")


def test_heading_prefix_returns_level_and_stripped_content() -> None:
    assert MarkdownInline.heading_prefix("# H1") == (1, "H1")
    assert MarkdownInline.heading_prefix("### Small") == (3, "Small")
    assert MarkdownInline.heading_prefix("no heading") == (0, "no heading")
    assert MarkdownInline.heading_prefix("text # not") == (0, "text # not")
    assert MarkdownInline.heading_prefix("####### seven") == (0, "####### seven")


# ── SyntaxHighlighter ─────────────────────────────────────────────────────


def has_token(code: str, lang: str, text: str, kind: str) -> bool:
    return any(
        t["text"] == text and t["kind"] == kind for t in SyntaxHighlighter.tokenize(code, lang)
    )


def test_js_keywords_strings_comments_and_numbers_are_promoted() -> None:
    assert has_token("const x = 1;", "javascript", "const", "keyword")
    assert has_token('"hi"', "javascript", '"hi"', "string")
    assert has_token("// note", "javascript", "// note", "comment")
    assert has_token("42", "typescript", "42", "number")
    assert has_token("console", "javascript", "console", "builtin")


def test_the_other_languages_highlight_too() -> None:
    assert has_token("function foo()", "php", "function", "keyword")
    assert has_token('{"a": true}', "json", "true", "keyword")
    assert has_token("def f(): pass", "python", "def", "keyword")
    assert has_token("if true; then echo hi; fi", "bash", "echo", "builtin")
    assert has_token("/* c */", "css", "/* c */", "comment")
    assert has_token("<div>", "html", "<div", "keyword")


def test_consecutive_same_kind_tokens_coalesce() -> None:
    assert SyntaxHighlighter.tokenize("abc", "javascript") == [{"text": "abc", "kind": "plain"}]


def test_longest_match_wins_across_kinds() -> None:
    """``//`` is both a comment and two punctuation-adjacent characters."""
    tokens = SyntaxHighlighter.tokenize("a; // trailing", "javascript")
    assert ("// trailing", "comment") in [(t["text"], t["kind"]) for t in tokens]


def test_color_for_returns_the_documented_palette() -> None:
    assert SyntaxHighlighter.color_for("keyword") == "C084FC"
    assert SyntaxHighlighter.color_for("string") == "86EFAC"
    assert SyntaxHighlighter.color_for("comment") == "64748B"
    assert SyntaxHighlighter.color_for("number") == "FBBF24"
    assert SyntaxHighlighter.color_for("builtin") == "67E8F9"
    assert SyntaxHighlighter.color_for("punctuation") == "CBD5E1"
    assert SyntaxHighlighter.color_for("plain") == "F8FAFC"


def test_language_aliases_normalise() -> None:
    assert has_token("const x = 1", "js", "const", "keyword")
    assert has_token("const x = 1", "ts", "const", "keyword")
    assert has_token("echo hi", "sh", "echo", "builtin")
    assert has_token("def f()", "py", "def", "keyword")
    assert has_token("<a>", "xml", "<a", "keyword")  # xml normalises to html


def test_an_unknown_language_yields_one_plain_token() -> None:
    assert SyntaxHighlighter.tokenize("const x = 1", "brainfuck") == [
        {"text": "const x = 1", "kind": "plain"}
    ]
    assert SyntaxHighlighter.tokenize("const x = 1", None) == [
        {"text": "const x = 1", "kind": "plain"}
    ]


def test_multibyte_text_survives_the_single_character_fallback() -> None:
    """The fallback emits one token per unmatched CHARACTER, then coalesces.

    In byte-indexed PHP that fallback emits one token per unmatched BYTE and
    only reassembles because ``_coalesce`` merges them. Python cannot split a
    character in the first place, so the text has to come back intact either
    way — which is the property being pinned.
    """
    tokens = SyntaxHighlighter.tokenize("// 日本語 🎉", "javascript")
    assert "".join(t["text"] for t in tokens) == "// 日本語 🎉"


# ── ChartTranslator ───────────────────────────────────────────────────────


def test_a_bar_chart_takes_categories_from_xaxis_data() -> None:
    spec = translate(
        {
            "xAxis": {"data": ["Q1", "Q2", "Q3"]},
            "series": [{"type": "bar", "name": "Rev", "data": [10, 20, 30]}],
        }
    )
    assert spec is not None
    assert spec["kind"] == "bar"
    assert spec["categories"] == ["Q1", "Q2", "Q3"]
    assert spec["series"][0]["values"] == [10, 20, 30]
    assert spec["series"][0]["name"] == "Rev"


def test_a_line_chart_carries_smooth_and_not_area() -> None:
    spec = translate(
        {"xAxis": {"data": ["a", "b"]}, "series": [{"type": "line", "data": [1, 2], "smooth": True}]}
    )
    assert spec is not None
    assert spec["kind"] == "line"
    assert spec["series"][0]["smooth"] is True
    assert spec["series"][0]["area"] is False


def test_line_plus_areastyle_is_an_area_series() -> None:
    spec = translate(
        {
            "xAxis": {"data": ["a", "b"]},
            "series": [{"type": "line", "data": [1, 2], "areaStyle": {}}],
        }
    )
    assert spec is not None
    assert spec["series"][0]["area"] is True


def test_pie_categories_come_from_data_names() -> None:
    spec = translate(
        {"series": [{"type": "pie", "data": [{"name": "X", "value": 5}, {"name": "Y", "value": 7.5}]}]}
    )
    assert spec is not None
    assert spec["kind"] == "pie"
    assert spec["categories"] == ["X", "Y"]
    assert spec["series"][0]["values"] == [5, 7.5]


def test_a_nameless_pie_slice_falls_back_to_a_positional_label() -> None:
    spec = translate({"series": [{"type": "pie", "data": [1, 2]}]})
    assert spec is not None
    assert spec["categories"] == ["Slice 1", "Slice 2"]


def test_scatter_points_come_from_xy_pairs() -> None:
    spec = translate({"series": [{"type": "scatter", "data": [[1, 2], [3, 4.5]]}]})
    assert spec is not None
    assert spec["kind"] == "scatter"
    assert spec["series"][0]["points"] == [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.5}]


def test_an_unsupported_series_type_fails_the_whole_translation() -> None:
    assert translate({"series": [{"type": "radar", "data": [1, 2, 3]}]}) is None


def test_empty_series_translate_to_nothing() -> None:
    assert translate({"series": []}) is None
    assert translate({}) is None


def test_the_title_comes_from_option_title_text() -> None:
    spec = translate(
        {"title": {"text": "Quarterly"}, "xAxis": {"data": ["a"]}, "series": [{"type": "bar", "data": [1]}]}
    )
    assert spec is not None
    assert spec["title"] == "Quarterly"


def test_option_categories_are_only_read_when_an_xaxis_exists() -> None:
    """A shared wart, pinned rather than fixed.

    ``extractCategories`` seeds its candidate with an EMPTY ARRAY and only
    falls back to ``option.categories`` when the candidate is NOT an array —
    so a deck with ``categories`` and no ``xAxis`` silently gets 1, 2, 3…
    labels. Both shipped engines do this. Changing it here alone would change
    the bytes of every such chart in one language.
    """
    without_axis = translate({"categories": ["a", "b"], "series": [{"type": "bar", "data": [1, 2]}]})
    assert without_axis is not None
    assert without_axis["categories"] == []

    with_axis = translate(
        {"xAxis": {}, "categories": ["a", "b"], "series": [{"type": "bar", "data": [1, 2]}]}
    )
    assert with_axis is not None
    assert with_axis["categories"] == ["a", "b"]


# ── Color ─────────────────────────────────────────────────────────────────


def test_three_digit_hex_expands() -> None:
    assert Color.parse("#abc") == ("AABBCC", 100000)


def test_six_digit_hex_parses() -> None:
    assert Color.parse("#8B5CF6") == ("8B5CF6", 100000)


def test_eight_digit_hex_splits_into_colour_and_alpha() -> None:
    hex_value, alpha = Color.parse("#FF000080")
    assert hex_value == "FF0000"
    assert alpha == int(Emu.php_round(0x80 / 255 * 100000))


def test_rgb_and_rgba_parse() -> None:
    assert Color.parse("rgb(255, 0, 0)") == ("FF0000", 100000)
    assert Color.parse("rgba(255,0,0,0.5)") == ("FF0000", 50000)


def test_named_colours_resolve() -> None:
    assert Color.parse("red") == ("FF0000", 100000)
    assert Color.parse("white") == ("FFFFFF", 100000)


def test_transparent_and_none_zero_the_alpha_on_the_fallback() -> None:
    assert Color.parse("transparent") == ("000000", 0)
    assert Color.parse("none") == ("000000", 0)


def test_unknown_input_returns_the_fallback_at_full_opacity() -> None:
    assert Color.parse("") == ("000000", 100000)
    assert Color.parse("notacolor") == ("000000", 100000)
    assert Color.parse("", "FF0000") == ("FF0000", 100000)
    assert Color.parse(None) == ("000000", 100000)


# ── Emu ───────────────────────────────────────────────────────────────────


def test_fractions_convert_per_axis() -> None:
    assert Emu.from_frac_x(0.5) == Emu.DEFAULT_SLIDE_WIDTH // 2
    assert Emu.from_frac_y(0.5) == Emu.DEFAULT_SLIDE_HEIGHT // 2


def test_emu_converts_back_to_a_fraction() -> None:
    assert Emu.to_frac_x(Emu.DEFAULT_SLIDE_WIDTH // 2) == pytest.approx(0.5, abs=1e-9)
    assert Emu.to_frac_y(Emu.DEFAULT_SLIDE_HEIGHT) == pytest.approx(1.0, abs=1e-9)
    assert Emu.to_frac_x(123, 0) == 0  # guard against a divide by zero


def test_points_convert_to_emu() -> None:
    assert Emu.from_pt(72) == Emu.EMU_PER_INCH
    assert Emu.from_pt(36) == Emu.EMU_PER_INCH // 2


def test_points_express_as_drawingml_sz_units() -> None:
    assert Emu.hundredths_of_point(24) == 2400
    assert Emu.hundredths_of_point(18.5) == 1850


# ── Xml escaping ──────────────────────────────────────────────────────────


def test_text_escaping_leaves_the_apostrophe_alone() -> None:
    assert Xml.text("a'b\"c<d>&e") == "a'b&quot;c&lt;d&gt;&amp;e"


def test_attribute_escaping_uses_the_named_apostrophe_entity() -> None:
    # ENT_XML1 gives `&apos;`, not `&#039;` — confirmed against the PHP engine.
    assert Xml.attr("a'b\"c<d>&e") == "a&apos;b&quot;c&lt;d&gt;&amp;e"


def test_ampersands_are_escaped_first_and_not_doubled() -> None:
    assert Xml.text("&amp;") == "&amp;amp;"


def test_the_declaration_ends_in_a_bare_linefeed() -> None:
    assert Xml.declaration() == '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    assert Xml.declaration(False) == '<?xml version="1.0" encoding="UTF-8"?>\n'


# ── PHP scalar semantics ──────────────────────────────────────────────────


def test_php_string_matches_phps_cast_not_pythons() -> None:
    assert php_string(True) == "1"
    assert php_string(False) == ""
    assert php_string(None) == ""
    assert php_string(12.0) == "12"  # Python's str() would say "12.0"
    assert php_string(12.5) == "12.5"
    assert php_string(1 / 3) == "0.33333333333333"  # precision=14, not repr
    assert php_string(1e20) == "1.0E+20"
    assert php_string(1e-7) == "1.0E-7"
    assert php_string("x") == "x"


def test_php_truthy_treats_the_string_zero_as_false() -> None:
    assert php_truthy("0") is False  # Python's bool("0") is True
    assert php_truthy("") is False
    assert php_truthy("0.0") is True
    assert php_truthy(0) is False
    assert php_truthy([]) is False
    assert php_truthy(None) is False
    assert php_truthy("false") is True


def test_is_numeric_follows_php_not_a_float_call() -> None:
    assert is_numeric("1e5") is True  # PHP reads the exponent; parseInt would say 1
    assert is_numeric(" 12 ") is True  # leading AND trailing whitespace
    assert is_numeric("1.") is True
    assert is_numeric(".5") is True
    assert is_numeric("0x1A") is False  # not since PHP 7
    assert is_numeric(True) is False  # a bool is not numeric in PHP
    assert is_numeric(None) is False
    assert is_numeric("") is False


def test_php_float_keeps_a_leading_numeric_prefix() -> None:
    assert php_float("12abc") == 12.0
    assert php_float("abc") == 0.0
    assert php_float("1e3") == 1000.0
    assert php_float(None) == 0.0


def test_php_int_truncates_toward_zero() -> None:
    assert php_int(600.9) == 600
    assert php_int(-600.9) == -600
    assert php_int("700") == 700


def test_gettype_returns_phps_labels() -> None:
    assert gettype(None) == "null"
    assert gettype(True) == "boolean"  # checked before int, which bool subclasses
    assert gettype(1) == "integer"
    assert gettype(1.5) == "double"
    assert gettype("s") == "string"
    assert gettype([]) == "array"
    assert gettype({}) == "object"


def test_php_json_encode_escapes_slashes_and_packs_separators() -> None:
    assert php_json_encode({"a": "x/y"}) == r'{"a":"x\/y"}'
    assert php_json_encode([1, 2]) == "[1,2]"
    # PHP escapes non-ASCII to \uXXXX by default; so does this, deliberately.
    assert php_json_encode({"k": "é"}) == '{"k":"\\u00e9"}'


# ── Validator + Repairer ──────────────────────────────────────────────────


def test_the_top_level_required_keys_are_flagged() -> None:
    paths = [e["path"] for e in Validator().validate({"slides": []})]
    assert "/id" in paths
    assert "/title" in paths
    assert "/theme" in paths


def test_a_fully_formed_deck_validates_clean() -> None:
    deck = {
        "id": "d",
        "title": "t",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "layout": "blank",
                "elements": [
                    {"id": "e", "type": "text", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2, "content": "hi"}
                ],
            }
        ],
    }
    assert Validator().validate(deck) == []


def test_a_null_id_is_accepted_because_php_guards_with_isset() -> None:
    """A live PHP↔Node divergence, resolved toward PHP.

    PHP guards the type check with ``isset()``, which is false for a null, so
    ``{"id": null}`` raises no error (and no missing-key error either, since
    the key IS present). The Node port checks ``!== undefined`` and flags it.
    """
    deck = {"id": None, "title": "t", "theme": {"name": "d"}, "slides": []}
    assert Validator().validate(deck) == []


def test_numeric_strings_pass_the_coordinate_check() -> None:
    """``is_numeric`` is the gate, not ``isinstance(float)``."""
    deck = {
        "id": "d",
        "title": "t",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "elements": [
                    {"id": "e", "type": "text", "x": "0.1", "y": 0, "w": "1e-1", "h": 0.2, "content": ""}
                ],
            }
        ],
    }
    assert Validator().validate(deck) == []


def test_repair_fills_ids_and_clamps_coordinates() -> None:
    deck = Repairer().repair(
        {"slides": [{"elements": [{"type": "text", "x": -0.5, "y": 1.5, "w": 2, "h": 0.5, "content": "hi"}]}]}
    )
    assert isinstance(deck["id"], str)
    assert deck["title"] == "Untitled"
    assert deck["theme"]["name"] == "default"
    element = deck["slides"][0]["elements"][0]
    assert element["x"] == 0
    assert element["y"] == 1
    assert element["w"] == 1
    assert isinstance(element["id"], str)
    assert isinstance(deck["slides"][0]["id"], str)


def test_repair_enforces_a_minimum_element_size() -> None:
    deck = Repairer().repair(
        {"slides": [{"elements": [{"type": "shape", "shape": "rect", "x": 0.1, "y": 0.1, "w": 0.001, "h": 0.0}]}]}
    )
    element = deck["slides"][0]["elements"][0]
    assert element["w"] >= 0.02
    assert element["h"] >= 0.02


def test_repair_normalises_an_unknown_layout_to_blank() -> None:
    deck = Repairer().repair({"slides": [{"layout": "made-up", "elements": []}]})
    assert deck["slides"][0]["layout"] == "blank"


def test_repair_drops_elements_with_an_unknown_or_missing_type() -> None:
    deck = Repairer().repair(
        {
            "slides": [
                {
                    "elements": [
                        {"type": "text", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2, "content": "keep"},
                        {"type": "bogus", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2},
                        {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2},
                    ]
                }
            ]
        }
    )
    elements = deck["slides"][0]["elements"]
    assert len(elements) == 1
    assert elements[0]["type"] == "text"


def test_repair_coerces_an_unknown_shape_kind_to_rect() -> None:
    deck = Repairer().repair(
        {"slides": [{"elements": [{"type": "shape", "shape": "hexagon-of-doom", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2}]}]}
    )
    assert deck["slides"][0]["elements"][0]["shape"] == "rect"


def test_repair_clamps_a_non_finite_coordinate_to_the_minimum() -> None:
    deck = Repairer().repair(
        {"slides": [{"elements": [{"type": "text", "x": math.inf, "y": 0.1, "w": 0.3, "h": 0.2}]}]}
    )
    assert deck["slides"][0]["elements"][0]["x"] == 0.0

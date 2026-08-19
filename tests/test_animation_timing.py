"""Element entrance animations → OOXML ``<p:timing>``.

Ported from PHP ``tests/Unit/AnimationTimingTest.php``.

Structural well-formedness plus ``spTgt`` ↔ ``cNvPr`` id matching are
necessary and NOT sufficient — a timing tree can parse, target real shapes and
still not play. That last mile needs a real PowerPoint probe; what is testable
here is tested here.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.etree import ElementTree

import dark_slide


def anim_deck() -> dict[str, Any]:
    return {
        "id": "anim",
        "title": "animation deck",
        "theme": {"name": "default", "colors": {"accent": "#8B5CF6"}},
        "slides": [{"id": "s1", "layout": "title", "elements": []}],
    }


def part(deck: Any, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(deck))) as archive:
        return archive.read(name).decode("utf-8")


def sp_tgt_spids(xml: str) -> list[int]:
    return [int(m) for m in re.findall(r'<p:spTgt spid="(\d+)"/>', xml)]


def all_sp_tgt_spids(xml: str) -> list[int]:
    return [int(m) for m in re.findall(r'<p:spTgt spid="(\d+)"', xml)]


def c_nv_pr_ids(xml: str) -> list[int]:
    return [int(m) for m in re.findall(r'<p:cNvPr id="(\d+)"', xml)]


def p_ranges(xml: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in re.findall(r'<p:pRg st="(\d+)" end="(\d+)"/>', xml)]


def text_element(element_id: str, y: float, content: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": element_id,
        "type": "text",
        "x": 0.1,
        "y": y,
        "w": 0.8,
        "h": 0.2,
        "content": content,
        "format": "plain",
        **extra,
    }


def test_no_timing_node_when_nothing_is_animated() -> None:
    deck = anim_deck()
    deck["slides"][0]["elements"].append(text_element("plain", 0.1, "Hello"))
    assert "<p:timing>" not in part(deck, "ppt/slides/slide1.xml")


def test_a_well_formed_timing_tree_for_three_animated_elements() -> None:
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        text_element("a", 0.1, "One", animation={"effect": "fade", "trigger": "on-click"}),
        text_element(
            "b",
            0.4,
            "Two",
            animation={"effect": "fly-in", "trigger": "with-prev", "direction": "left"},
        ),
        text_element("c", 0.7, "Three", animation={"effect": "zoom", "trigger": "after-prev"}),
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    ElementTree.fromstring(xml)  # raises if the part is not well-formed

    assert "<p:timing>" in xml
    # CT_Slide child order: timing must follow cSld (and any transition).
    assert xml.index("<p:timing>") > xml.index("</p:cSld>")
    assert 'nodeType="mainSeq"' in xml
    assert 'nodeType="tmRoot"' in xml

    # on-click leads a step; with-prev and after-prev attach to it → ONE step,
    # so exactly one indefinite click wait.
    assert xml.count('<p:cond delay="indefinite"/>') == 1

    assert 'filter="fade"' in xml
    assert "ppt_x" in xml  # fly-in translates ppt_x / ppt_y
    assert "<p:animScale>" in xml
    assert '<p:from x="0" y="0"/>' in xml  # zoom grows from a point

    # Builds are entrances: PowerPoint pre-hides them, and each reveals its
    # target with a visibility set when it fires.
    assert 'presetClass="entr"' in xml
    assert '<p:strVal val="visible"/>' in xml


def test_mixed_triggers_produce_the_right_number_of_click_steps() -> None:
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        text_element("a", 0.1, "One", animation={"effect": "fade", "trigger": "on-click"}),
        text_element(
            "b",
            0.4,
            "Two",
            animation={"effect": "wipe", "trigger": "on-click", "direction": "up"},
        ),
        text_element("c", 0.7, "Three", animation={"effect": "fade", "trigger": "with-prev"}),
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    assert xml.count('<p:cond delay="indefinite"/>') == 2
    # A wipe travelling UP is filtered as coming FROM below.
    assert 'filter="wipe(down)"' in xml


def test_every_sptgt_names_a_real_shape() -> None:
    deck = anim_deck()
    # A non-animated element first, so the shape-id counter is genuinely
    # exercised rather than starting at the first animated shape.
    deck["slides"][0]["elements"] = [
        {
            "id": "plain",
            "type": "text",
            "x": 0.1,
            "y": 0.1,
            "w": 0.8,
            "h": 0.1,
            "content": "Title",
            "format": "plain",
        },  # shape id 2, not animated
        text_element("a", 0.3, "One", animation={"effect": "fade"}),  # shape id 3
        {
            "id": "b",
            "type": "shape",
            "shape": "rect",
            "x": 0.1,
            "y": 0.6,
            "w": 0.3,
            "h": 0.2,
            "animation": {"effect": "fly-in", "trigger": "after-prev", "direction": "right"},
        },  # shape id 4
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    shape_ids = c_nv_pr_ids(xml)
    targets = sp_tgt_spids(xml)

    assert targets
    for spid in set(targets):
        assert spid in shape_ids
    assert 3 in targets
    assert 4 in targets
    assert 2 not in targets  # the un-animated shape is never targeted


def test_builds_are_ordered_by_order_then_authored_position() -> None:
    deck = anim_deck()
    # Authored a-then-b, but b carries the lower `order`, so b builds first.
    deck["slides"][0]["elements"] = [
        text_element("a", 0.1, "A", animation={"effect": "fade", "order": 5}),  # shape id 2
        text_element("b", 0.4, "B", animation={"effect": "fade", "order": 0}),  # shape id 3
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    after_seq = xml[xml.index('nodeType="mainSeq"') :]
    assert sp_tgt_spids(after_seq)[0] == 3


def test_equal_order_keeps_the_authored_sequence() -> None:
    """The sort must be STABLE, or two builds with the same order swap."""
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        text_element("a", 0.1, "A", animation={"effect": "fade", "order": 1}),  # shape id 2
        text_element("b", 0.4, "B", animation={"effect": "fade", "order": 1}),  # shape id 3
    ]
    after_seq = part(deck, "ppt/slides/slide1.xml")
    after_seq = after_seq[after_seq.index('nodeType="mainSeq"') :]
    # Each build names its target twice (visibility set, then effect), so
    # collapse consecutive repeats before reading the order.
    order: list[int] = []
    for spid in sp_tgt_spids(after_seq):
        if not order or order[-1] != spid:
            order.append(spid)
    assert order == [2, 3]


def test_byparagraph_splits_a_text_element_into_one_build_per_line() -> None:
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        text_element(
            "lines",
            0.1,
            "Line one\nLine two\nLine three",
            h=0.5,
            animation={"effect": "fade", "byParagraph": True, "trigger": "on-click"},
        )
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    ElementTree.fromstring(xml)

    seq_xml = xml[xml.index('nodeType="mainSeq"') :]

    assert '<p:pRg st="0" end="0"/>' in seq_xml
    assert '<p:pRg st="1" end="1"/>' in seq_xml
    assert '<p:pRg st="2" end="2"/>' in seq_xml

    # Every paragraph target is under the SAME shape.
    assert set(all_sp_tgt_spids(seq_xml)) == {2}

    # No whole-shape build slipped in: a self-closing <p:spTgt/> is the
    # whole-shape form and is forbidden in this region.
    assert '<p:spTgt spid="2"/>' not in seq_xml

    # Three click steps: the first line keeps its trigger, the rest become
    # their own clicks.
    assert seq_xml.count('<p:cond delay="indefinite"/>') == 3

    # Paragraph ranges appear in <a:p> order, because the timing counter and
    # the text body split the content the same way. Each build emits its range
    # twice (visibility set + effect), so collapse runs before comparing.
    distinct: list[tuple[int, int]] = []
    for r in p_ranges(seq_xml):
        if not distinct or distinct[-1] != r:
            distinct.append(r)
    assert distinct == [(0, 0), (1, 1), (2, 2)]

    # Pre-hidden by the entrance class, one per paragraph — not by a separate
    # load-time hide group, which flashed.
    assert seq_xml.count('presetClass="entr"') == 3
    assert '<p:strVal val="visible"/>' in seq_xml
    assert '<p:strVal val="hidden"/>' not in xml


def test_a_multiline_element_without_byparagraph_is_one_whole_shape_build() -> None:
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        text_element(
            "block",
            0.1,
            "Line one\nLine two\nLine three",
            h=0.5,
            animation={"effect": "fade", "trigger": "on-click"},
        )
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    ElementTree.fromstring(xml)
    assert "<p:pRg" not in xml
    assert '<p:spTgt spid="2"/>' in xml
    assert xml.count('<p:cond delay="indefinite"/>') == 1


def test_byparagraph_is_ignored_on_non_text_elements() -> None:
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        {
            "id": "box",
            "type": "shape",
            "shape": "rect",
            "x": 0.1,
            "y": 0.1,
            "w": 0.3,
            "h": 0.2,
            "animation": {"effect": "fade", "byParagraph": True, "trigger": "on-click"},
        }
    ]
    xml = part(deck, "ppt/slides/slide1.xml")

    assert "<p:pRg" not in xml
    assert '<p:spTgt spid="2"/>' in xml


def test_byparagraph_is_ignored_when_the_flag_is_the_string_zero() -> None:
    """PHP's ``empty("0")`` is true, so ``byParagraph: "0"`` means OFF.

    Python's ``bool("0")`` and JavaScript's are both ``True``, which would
    turn the flag on. Following PHP here is the ruling for the trio.
    """
    deck = anim_deck()
    deck["slides"][0]["elements"] = [
        text_element(
            "lines",
            0.1,
            "One\nTwo",
            animation={"effect": "fade", "byParagraph": "0", "trigger": "on-click"},
        )
    ]
    assert "<p:pRg" not in part(deck, "ppt/slides/slide1.xml")

"""Whole-element hyperlinks. Ported from PHP ``tests/Unit/HyperlinkTest.php``.

``element.href`` becomes an ``<a:hlinkClick>`` inside the shape's ``<p:cNvPr>``
plus an EXTERNAL slide relationship. Mirrors fancy-slides' ``ElementBase.href``.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import dark_slide


def part(deck: Any, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(dark_slide.to_bytes(deck))) as archive:
        return archive.read(name).decode("utf-8")


def hyperlink_deck(href: str) -> dict[str, Any]:
    return {
        "id": "hl",
        "title": "hyperlink deck",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "layout": "blank",
                "elements": [
                    {
                        "id": "btn",
                        "type": "shape",
                        "shape": "rounded-rect",
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.3,
                        "h": 0.15,
                        "fill": "#8B5CF6",
                        "href": href,
                    },
                    {
                        "id": "plain",
                        "type": "text",
                        "x": 0.1,
                        "y": 0.4,
                        "w": 0.5,
                        "h": 0.1,
                        "content": "no link",
                        "format": "plain",
                    },
                ],
            }
        ],
    }


def test_an_href_injects_an_hlinkclick_into_the_shapes_cnvpr() -> None:
    xml = part(hyperlink_deck("https://particle.academy/fancy"), "ppt/slides/slide1.xml")

    assert '<a:hlinkClick r:id="rIdLink' in xml
    # The cNvPr is no longer self-closing — it now wraps the hlink.
    assert "</p:cNvPr>" in xml


def test_the_hyperlink_relationship_is_registered_as_external() -> None:
    rels = part(
        hyperlink_deck("https://particle.academy/fancy"), "ppt/slides/_rels/slide1.xml.rels"
    )

    assert 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"' in rels
    assert 'Target="https://particle.academy/fancy"' in rels
    assert 'TargetMode="External"' in rels


def test_only_the_first_cnvpr_is_rewritten() -> None:
    """A picture has one ``<p:cNvPr>``; the injection must not touch siblings."""
    xml = part(hyperlink_deck("https://example.com"), "ppt/slides/slide1.xml")
    assert xml.count("<a:hlinkClick") == 1


def test_an_element_without_an_href_emits_no_hlinkclick() -> None:
    deck = {
        "id": "hl2",
        "title": "t",
        "theme": {"name": "default"},
        "slides": [
            {
                "id": "s1",
                "layout": "blank",
                "elements": [
                    {
                        "id": "x",
                        "type": "text",
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.5,
                        "h": 0.1,
                        "content": "plain",
                        "format": "plain",
                    }
                ],
            }
        ],
    }

    assert "<a:hlinkClick" not in part(deck, "ppt/slides/slide1.xml")


def test_an_empty_href_is_treated_as_no_href() -> None:
    assert "<a:hlinkClick" not in part(hyperlink_deck(""), "ppt/slides/slide1.xml")


def test_the_href_is_attribute_escaped_in_the_relationship() -> None:
    """A query string with ``&`` is the everyday case that breaks a rels part."""
    rels = part(
        hyperlink_deck("https://example.com/?a=1&b='2'"), "ppt/slides/_rels/slide1.xml.rels"
    )
    assert "Target=\"https://example.com/?a=1&amp;b=&apos;2&apos;\"" in rels

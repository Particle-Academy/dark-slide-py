"""Text with no colour of its own takes the THEME's text colour.

fancy-slides draws ``style.color ?? theme.colors.text``; the writer used
``style.color ?? #0F172A``. On a dark theme every unstyled text box was
near-black on a dark background: the deck previewed correctly and exported with
no visible text. The same test runs in all three engines.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from dark_slide import to_bytes

DARK = {"colors": {"background": "#101828", "text": "#F9FAFB"}}


def _slide_xml(theme: dict[str, Any], style: dict[str, Any] | None = None) -> str:
    element: dict[str, Any] = {
        "id": "e", "type": "text", "x": 0.1, "y": 0.4, "w": 0.8, "h": 0.2,
        "content": "Headline\n\n- **bold** point", "format": "markdown",
    }
    if style is not None:
        element["style"] = style
    deck = {
        "id": "tic",
        "title": "Theme text colour",
        "theme": {"name": "tic", **theme},
        "slides": [{"id": "s1", "elements": [element]}],
    }
    with zipfile.ZipFile(io.BytesIO(to_bytes(deck))) as z:
        return z.read("ppt/slides/slide1.xml").decode("utf-8")


def test_unstyled_text_is_the_theme_text_colour() -> None:
    xml = _slide_xml(DARK)
    assert '<a:srgbClr val="F9FAFB"/>' in xml
    assert '<a:srgbClr val="0F172A"/>' not in xml


def test_an_element_colour_still_wins() -> None:
    xml = _slide_xml(DARK, {"color": "#F97316"})
    assert '<a:srgbClr val="F97316"/>' in xml
    assert '<a:srgbClr val="F9FAFB"/>' not in xml


def test_the_old_default_holds_without_a_theme_text_colour() -> None:
    assert '<a:srgbClr val="0F172A"/>' in _slide_xml({})


def test_table_text_and_stripes_follow_a_dark_theme() -> None:
    import io as _io
    import zipfile as _zipfile

    from dark_slide import to_bytes as _to_bytes

    deck = {
        "id": "t", "title": "T",
        "theme": {"name": "dark", "colors": {"background": "#0B1220", "text": "#F9FAFB", "accent": "#38BDF8"}},
        "slides": [{"id": "s1", "elements": [{
            "id": "tb", "type": "table", "x": 0.1, "y": 0.2, "w": 0.8, "h": 0.5,
            "columns": [{"key": "k", "label": "KPI"}, {"key": "v", "label": "Actual"}],
            "rows": [{"k": "On-time", "v": "94.2%"}, {"k": "Damage", "v": "0.6%"}],
        }]}],
    }
    with _zipfile.ZipFile(_io.BytesIO(_to_bytes(deck))) as z:
        xml = z.read("ppt/slides/slide1.xml").decode("utf-8")
    assert 'val="0F172A"' not in xml
    assert 'val="F8FAFC"' not in xml
    assert '<a:srgbClr val="F9FAFB"/>' in xml

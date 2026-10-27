"""CommonMark backslash escapes in the inline tokenizer.

A backslash before any ASCII punctuation character makes that character
literal and is itself removed. A backslash before anything else (a letter, a
digit, a space, a non-ASCII character, the end of the paragraph) is a literal
backslash. Inside a code span nothing is an escape.

Mirrors PHP ``tests/Unit/MarkdownInlineEscapeTest.php`` and Node
``tests/markdown-inline-escapes.test.ts`` row for row; keep the three in step.
"""

from __future__ import annotations

import io
import zipfile

import pytest

import dark_slide
from dark_slide.helpers import markdown_inline as MarkdownInline


def run(text: str, b: bool = False, i: bool = False, code: bool = False) -> dict:
    return {"text": text, "b": b, "i": i, "code": code}


CASES = [
    ("escaped bold markers are literal asterisks", "\\*\\*not bold\\*\\*", [run("**not bold**")]),
    ("one escaped asterisk then a bold opener", "\\***x**", [run("*"), run("x", b=True)]),
    ("escaped backticks do not open code", "\\`not code\\`", [run("`not code`")]),
    ("escaped underscores are not italic", "\\_not italic\\_", [run("_not italic_")]),
    ("an escaped asterisk inside bold is literal", "**a \\* b**", [run("a * b", b=True)]),
    ("a doubled backslash is one literal backslash", "a \\\\ b", [run("a \\ b")]),
    ("an escaped backslash does not escape what follows", "\\\\*x*", [run("\\"), run("x", i=True)]),
    ("a backslash before a letter is literal", "C:\\path\\to", [run("C:\\path\\to")]),
    ("a backslash before a digit is literal", "v\\2", [run("v\\2")]),
    ("a backslash before a space is literal", "a \\ b", [run("a \\ b")]),
    ("a trailing backslash is literal", "end\\", [run("end\\")]),
    ("a backslash before non-ASCII is literal", "\\é", [run("\\é")]),
    ("a leading escaped hash is a literal hash", "\\# not a heading", [run("# not a heading")]),
    (
        "every ASCII punctuation character escapes",
        "\\!\\\"\\#\\$\\%\\&\\'\\(\\)\\*\\+\\,\\-\\.\\/\\:\\;\\<\\=\\>\\?\\@\\[\\\\\\]\\^\\_\\`\\{\\|\\}\\~",
        [run("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")],
    ),
    ("a backslash inside a code span is literal", "`a\\*b`", [run("a\\*b", code=True)]),
]


@pytest.mark.parametrize(("name", "text", "expected"), CASES, ids=[c[0] for c in CASES])
def test_backslash_escapes(name: str, text: str, expected: list[dict]) -> None:
    assert MarkdownInline.tokenize(text) == expected


def test_escaped_markers_reach_the_pptx_as_literal_text_with_no_backslash() -> None:
    deck = {
        "id": "esc",
        "title": "Escapes",
        "theme": {"name": "default"},
        "slides": [{"id": "s1", "elements": [{
            "id": "tx", "type": "text", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.2,
            "content": "\\*\\*not bold\\*\\* and \\`not code\\`",
            "format": "markdown",
        }]}],
    }
    data = dark_slide.to_bytes(deck)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("ppt/slides/slide1.xml").decode("utf-8")

    assert "<a:t>**not bold** and `not code`</a:t>" in xml
    assert "\\" not in xml
    assert ' b="1"' not in xml
    assert ' i="1"' not in xml
    assert "Consolas" not in xml

    read = dark_slide.read(data)
    assert read["slides"][0]["elements"][0]["content"] == "**not bold** and `not code`"

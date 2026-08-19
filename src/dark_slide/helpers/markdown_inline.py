"""Inline-markdown tokenizer. Mirrors PHP ``Helpers\\MarkdownInline``.

Splits ONE paragraph (no newlines) into ``(text, b, i, code)`` runs that map
straight onto drawingML ``<a:r>`` elements. Block structure — headings,
bullets — is the caller's job; :func:`heading_prefix` and
:func:`bullet_prefix` are the two block markers it needs.

**String indexing.** PHP indexes this loop by BYTE and the Node port by UTF-16
code unit; Python indexes by codepoint, which is a third scheme. All three
agree, and the reason is worth writing down rather than trusting: every cut
this loop makes is at an ASCII marker (`` ` ``, ``*``, ``_``), and neither a
UTF-8 continuation byte nor a UTF-16 surrogate half can equal an ASCII byte.
So the three index spaces disagree about the *numbers* and agree about the
*positions*. The ``unicodeText`` parity fixture pins it against the PHP
engine rather than leaving it as an argument.
"""

from __future__ import annotations

import re
from typing import TypedDict

__all__ = ["InlineRun", "tokenize", "bullet_prefix", "heading_prefix"]

_WORD_CHAR = re.compile(r"[a-zA-Z0-9_]")
# No DOTALL: the PHP pattern carries no `s` modifier, and the caller has
# already split on "\n", so `.` must not cross a line either way.
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class InlineRun(TypedDict):
    text: str
    b: bool
    i: bool
    code: bool


def _is_word_char(ch: str) -> bool:
    return _WORD_CHAR.match(ch) is not None


def tokenize(text: str) -> list[InlineRun]:
    """Tokenize a single paragraph into runs.

    Never raises and never drops input: an unmatched marker falls through as
    literal text, and an empty paragraph yields one empty run so the caller
    still emits an ``<a:p>``.
    """
    runs: list[InlineRun] = []
    i = 0
    length = len(text)
    buf = ""
    bold = False
    italic = False
    # `code` is loop state in PHP but is never assigned: a code span pushes
    # its own run and continues, so the flag is always False when `flush`
    # reads it. Kept for shape-fidelity with the reference.
    code = False

    def flush() -> None:
        nonlocal buf
        if buf != "":
            runs.append({"text": buf, "b": bold, "i": italic, "code": code})
            buf = ""

    while i < length:
        c = text[i]
        next2 = text[i : i + 2]

        # Code spans win outright — they swallow every marker literally.
        if c == "`" and not code:
            flush()
            end = text.find("`", i + 1)
            if end == -1:
                buf += text[i:]
                i = length
                continue
            runs.append({"text": text[i + 1 : end], "b": bold, "i": italic, "code": True})
            i = end + 1
            continue

        # Bold via ** or __ — a toggle, not a matched pair.
        if next2 in ("**", "__"):
            flush()
            bold = not bold
            i += 2
            continue

        # Italic via * or _. The word-boundary guard is what keeps
        # `snake_case_names` out of the italic path.
        if (c == "*" or c == "_") and not code:
            prev = text[i - 1] if i > 0 else " "
            if (italic and _is_word_char(prev)) or not italic:
                if not italic:
                    if not _is_word_char(prev) or prev == " ":
                        flush()
                        italic = True
                        i += 1
                        continue
                else:
                    flush()
                    italic = False
                    i += 1
                    continue

        buf += c
        i += 1

    flush()

    if not runs:
        runs.append({"text": "", "b": False, "i": False, "code": False})

    return runs


def bullet_prefix(line: str) -> tuple[bool, str]:
    """``(is_bullet, content_without_marker)`` for ``- `` / ``* `` leaders."""
    if line.startswith("- ") or line.startswith("* "):
        return (True, line[2:])
    return (False, line)


def heading_prefix(line: str) -> tuple[int, str]:
    """``(level 1..6, content)`` for an ATX heading, or ``(0, line)``.

    Only a paragraph-leading marker counts; a ``#`` mid-line is plain text.
    """
    m = _HEADING.match(line)
    if m:
        return (len(m.group(1)), m.group(2))
    return (0, line)

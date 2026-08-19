"""XML escaping for the writer. Mirrors PHP ``Helpers\\Xml``.

The two functions escape DIFFERENT sets and the asymmetry is load-bearing:

* :func:`text` is ``htmlspecialchars(ENT_XML1 | ENT_COMPAT)`` — ``& < > "``,
  and **not** the apostrophe.
* :func:`attr` is ``htmlspecialchars(ENT_XML1 | ENT_QUOTES)`` — the same set
  **plus** the apostrophe, as ``&apos;`` (``ENT_HTML401`` would give
  ``&#039;``; ``ENT_XML1`` gives the named entity, and the parity suite
  confirms it against the PHP engine rather than the docs).

Order matters: ``&`` first, or the ampersands introduced by the later
replacements get double-escaped.

There is no ``ElementTree`` anywhere in the writer, deliberately. Attribute
order, self-closing style and the absence of inter-element whitespace are all
part of the byte contract, and no serialiser exposes them as knobs.
"""

from __future__ import annotations

__all__ = ["text", "attr", "declaration"]


def text(s: str) -> str:
    """Escape for XML text content: ``& < > "``, apostrophe left alone."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def attr(s: str) -> str:
    """Escape for an XML attribute value: as :func:`text`, plus ``'``."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def declaration(standalone: bool = True) -> str:
    """The XML declaration every part starts with. The trailing LF is part of it."""
    sa = ' standalone="yes"' if standalone else ""
    return f'<?xml version="1.0" encoding="UTF-8"{sa}?>\n'

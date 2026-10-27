"""Exceptions. Mirrors PHP ``DarkSlide\\Exceptions\\SchemaException``."""

from __future__ import annotations

from typing import Any

__all__ = ["SchemaException", "FontEmbeddingException", "ArchiveRefused", "OfficeTemplateRefused"]


class ArchiveRefused(ValueError):
    """A source archive refused by the bounded reader, with a constant ``reason``.

    Mirrors PHP ``DarkSlide\\Exceptions\\ArchiveRefused`` and Node's: the message
    never echoes archive names or document content. Branch on ``reason``:
    ``archive_limit``, ``archive_path``, ``archive_duplicate``, ``archive_corrupt``,
    ``archive_unsupported``, ``archive_limits``, ``archive_io``.

    A ``ValueError`` on purpose: a damaged zip raised ``ValueError`` from this
    reader before the guard existed, so callers that caught that keep working.
    """

    def __init__(self, reason: str) -> None:
        super().__init__("Source archive refused: " + reason)
        self.reason = reason


_TEMPLATE_MESSAGES = {
    "macro_enabled": "Macro-enabled templates (.potm) are refused: re-save it as a .potx in PowerPoint.",
    "family_mismatch": "This package declares a template of a different kind than its contents.",
    "already_template": "This package is already a template.",
    "already_document": "This package is already a document.",
    "not_convertible": "This package has no single PowerPoint content-type declaration that can be rewritten (OpenDocument presentations are not read by dark-slide).",
    "bad_target": 'The conversion target must be "document" or "template".',
}


class OfficeTemplateRefused(ValueError):
    """An Office template package refused, with a constant ``reason``.

    Mirrors PHP ``DarkSlide\\Exceptions\\OfficeTemplateRefused``: ``macro_enabled``,
    ``family_mismatch``, ``already_template``, ``already_document``,
    ``not_convertible``, ``bad_target``. Branch on ``reason``; the message is for
    people.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"Template refused ({reason}): " + _TEMPLATE_MESSAGES.get(reason, reason))
        self.reason = reason


class SchemaException(Exception):
    """Raised by ``write`` / ``to_bytes`` when a deck cannot be written.

    Carries the structured error list from the ``Validator`` so a caller can
    render per-field feedback — or hand it straight back to an agent — without
    re-running validation.
    """

    def __init__(self, message: str, errors: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors


class FontEmbeddingException(Exception):
    """A font the host asked to embed that cannot be embedded.

    Raised rather than skipped. A deck that silently leaves out a font it was
    asked to carry renders in a substitute face on every machine without it,
    which is the exact failure embedding exists to prevent, and nothing would
    say so. Every problem across every supplied font is collected and raised
    together, before anything is written.
    """

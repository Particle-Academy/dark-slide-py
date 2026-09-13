"""Exceptions. Mirrors PHP ``DarkSlide\\Exceptions\\SchemaException``."""

from __future__ import annotations

from typing import Any

__all__ = ["SchemaException", "FontEmbeddingException"]


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

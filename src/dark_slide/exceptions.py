"""Exceptions. Mirrors PHP ``DarkSlide\\Exceptions\\SchemaException``."""

from __future__ import annotations

from typing import Any

__all__ = ["SchemaException"]


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

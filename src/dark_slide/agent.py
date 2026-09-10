"""The Agent surface — the structured-tool API. Mirrors PHP ``Agent`` / TS ``Agent``.

Where the peers use static methods on a class, this is **module-level
functions**, because that is the same call shape in Python:
``Agent::toBytes($deck)`` / ``Agent.toBytes(deck)`` / ``dark_slide.to_bytes(deck)``.

Validate-then-write semantics throughout: a deck that fails validation raises
:class:`~dark_slide.exceptions.SchemaException` carrying the structured error
list, so an agent gets something it can act on rather than a stack trace.
"""

from __future__ import annotations

import os
from typing import Any

from .exceptions import SchemaException
from .reader.pptx_reader import PptxReader
from .schema.repairer import Repairer
from .schema.schema import Schema
from .schema.validator import Validator
from .util import php_string
from .writer.pptx_writer import PptxWriter

__all__ = [
    "VERSION",
    "validate",
    "validate_and_repair",
    "to_bytes",
    "write",
    "read",
    "from_bytes",
    "describe",
    "json_schema",
    "version",
]

#: This package's own version. Note the peers' numbers differ from each other
#: and from this one — each ships on its own registry's schedule. Feature
#: parity is asserted by the parity suite, not by a matching number.
VERSION = "0.2.0"


def _make_writer(options: dict[str, Any] | None) -> PptxWriter:
    opts = options or {}
    return PptxWriter(
        temp_dir=opts.get("temp_dir"),
        allow_http_images=bool(opts.get("allow_http_images", False)),
    )


def _assert_valid(deck: Any) -> None:
    errors = Validator().validate(deck)
    if errors:
        raise SchemaException(
            "Deck failed schema validation. Call validate_and_repair() for a recoverable form.",
            errors,
        )


def validate(deck: Any) -> list[dict[str, Any]]:
    """Validate a deck without writing. An empty list means it is writable.

    Pair it with :func:`json_schema` when registering an LLM tool so the model
    gets field hints before it emits, not after.
    """
    return Validator().validate(deck)


def validate_and_repair(deck: Any) -> dict[str, Any]:
    """Validate, then apply heuristic repairs. Returns ``{ok, schema, errors}``.

    * ``ok=True, errors=[]`` — the deck was already valid; ``schema`` is it.
    * ``ok=True, errors=[]`` after repair — ``schema`` is the repaired deck.
    * ``ok=False`` — ``errors`` is what repair could not fix. Hand it back to
      the agent; it is written to be actionable.
    """
    errors = validate(deck)
    if not errors:
        return {"ok": True, "schema": deck, "errors": []}
    repaired = Repairer().repair(deck)
    remaining = validate(repaired)
    return {"ok": not remaining, "schema": repaired, "errors": remaining}


def to_bytes(deck: Any, options: dict[str, Any] | None = None) -> bytes:
    """The ``.pptx`` bytes for a deck. No temp file, no disk.

    Options: ``temp_dir`` (accepted for signature parity; unused, since the
    archive is built in memory) and ``allow_http_images`` (default ``False``).
    """
    _assert_valid(deck)
    return _make_writer(options).to_bytes(deck)


def write(deck: Any, path: str | os.PathLike[str], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a deck to disk. Returns ``{path, bytes, slides}``.

    **Synchronous**, like PHP's. The Node port's ``write`` is async only
    because a browser has no synchronous filesystem; Python has one, so
    there is nothing to await.
    """
    _assert_valid(deck)
    return _make_writer(options).write(deck, os.fspath(path))


def read(data: bytes | bytearray | str | os.PathLike[str]) -> dict[str, Any]:
    """Read a ``.pptx`` back into the deck schema, from bytes OR a path.

    Best-effort: text, images, shapes and tables with their geometry come
    through; styling fidelity, masters, transitions and animations do not.
    """
    return PptxReader().read(data)


def from_bytes(data: bytes | bytearray) -> dict[str, Any]:
    """Alias for :func:`read` restricted to bytes. Mirrors the Node port."""
    return PptxReader().from_bytes(bytes(data))


def describe(deck: Any) -> str:
    """A plain-text summary — title, theme, slide count, element counts.

    Exists so an agent tool can answer "what is in this deck?" without the
    model paying for the full JSON.
    """
    def get(container: Any, key: str, default: Any) -> Any:
        """``$container[$key] ?? $default`` — null and absent are the same."""
        if not isinstance(container, dict):
            return default
        value = container.get(key)
        return default if value is None else value

    title = php_string(get(deck, "title", "Untitled"))
    theme_name = php_string(get(get(deck, "theme", {}), "name", Schema.DEFAULT_THEME_NAME))
    slides = get(deck, "slides", [])
    slides = slides if isinstance(slides, list) else []

    element_counts: dict[str, int] = {}
    for slide in slides:
        elements = get(slide, "elements", [])
        if not isinstance(elements, list):
            continue
        for element in elements:
            element_type = php_string(get(element, "type", "unknown"))
            element_counts[element_type] = element_counts.get(element_type, 0) + 1

    lines = [f"Deck: {title}", f"Theme: {theme_name}", f"Slides: {len(slides)}"]
    if element_counts:
        lines.append(
            "Elements: " + ", ".join(f"{n} {kind}" for kind, n in element_counts.items())
        )

    return "\n".join(lines)


def json_schema() -> dict[str, Any]:
    """JSON Schema for the deck, for LLM tool-use registration."""
    return Schema.json_schema()


def version() -> str:
    return VERSION

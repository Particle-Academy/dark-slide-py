"""Liberal shape validator. Mirrors PHP ``Schema\\Validator``.

Catches malformed agent output before it reaches the writer and hands back a
structured list — path, expected, got, value, hint — so the agent can correct
itself in a follow-up call rather than being told "invalid".

**Liberal on purpose.** Missing optional fields, unknown keys and unrecognised
layouts all pass; only what the writer genuinely cannot recover from is
flagged.
"""

from __future__ import annotations

from typing import Any

from ..util import gettype, is_numeric, is_plain_object, php_string
from .schema import Schema

__all__ = ["Validator"]


def _err(path: str, expected: str, got: str, value: Any, hint: str) -> dict[str, Any]:
    return {"path": path, "expected": expected, "got": got, "value": value, "hint": hint}


class Validator:
    """Validate a deck. Returns ``[]` when it is writable."""

    def validate(self, deck: Any) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        d = deck if is_plain_object(deck) else {}

        for key in Schema.deck_required_keys():
            if key not in d:
                errors.append(_err(f"/{key}", key, "missing", None, f"Deck must have an `{key}` field."))

        # `is not None` rather than a presence check: PHP guards these with
        # `isset()`, which is false for a null value, so `{"id": null}` raises
        # no type error (and no missing-key error either, because the key IS
        # there). The Node port uses `!== undefined` and DOES flag it — a live
        # PHP/Node divergence. Python follows PHP.
        if d.get("id") is not None and not isinstance(d["id"], str):
            errors.append(_err("/id", "string", gettype(d["id"]), d["id"], "Deck id must be a string."))

        if d.get("title") is not None and not isinstance(d["title"], str):
            errors.append(
                _err("/title", "string", gettype(d["title"]), d["title"], "Deck title must be a string.")
            )

        if d.get("theme") is not None:
            theme = d["theme"]
            if not isinstance(theme, (dict, list)):
                errors.append(
                    _err(
                        "/theme",
                        "object",
                        gettype(theme),
                        theme,
                        "Theme must be an object with at least a `name` field.",
                    )
                )
            elif not (is_plain_object(theme) and theme.get("name") is not None):
                errors.append(_err("/theme/name", "string", "missing", None, "Theme must have a name."))

        if d.get("slides") is not None:
            slides = d["slides"]
            if not isinstance(slides, list):
                errors.append(
                    _err("/slides", "array", gettype(slides), slides, "Slides must be a JSON array.")
                )
            else:
                for i, slide in enumerate(slides):
                    errors.extend(self._validate_slide(slide, f"/slides/{i}"))

        return errors

    def _validate_slide(self, slide: Any, path: str) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []

        if not isinstance(slide, (dict, list)):
            return [_err(path, "object", gettype(slide), slide, "Each slide must be a JSON object.")]
        if not is_plain_object(slide):
            slide = {}

        for key in Schema.slide_required_keys():
            if key not in slide:
                errors.append(
                    _err(f"{path}/{key}", key, "missing", None, f"Slide must have a `{key}` field.")
                )

        if slide.get("id") is not None and not isinstance(slide["id"], str):
            errors.append(
                _err(f"{path}/id", "string", gettype(slide["id"]), slide["id"], "Slide id must be a string.")
            )

        # An unrecognised `layout` is deliberately NOT an error — the writer
        # falls back to free placement on the blank layout.

        if slide.get("elements") is not None:
            elements = slide["elements"]
            if not isinstance(elements, list):
                errors.append(
                    _err(
                        f"{path}/elements",
                        "array",
                        gettype(elements),
                        elements,
                        "Slide elements must be an array.",
                    )
                )
            else:
                for i, element in enumerate(elements):
                    errors.extend(self._validate_element(element, f"{path}/elements/{i}"))

        if slide.get("notes") is not None and not isinstance(slide["notes"], str):
            errors.append(
                _err(
                    f"{path}/notes",
                    "string",
                    gettype(slide["notes"]),
                    slide["notes"],
                    "Slide notes must be a string.",
                )
            )

        return errors

    def _validate_element(self, element: Any, path: str) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []

        if not isinstance(element, (dict, list)):
            return [_err(path, "object", gettype(element), element, "Each element must be a JSON object.")]
        if not is_plain_object(element):
            element = {}

        for key in Schema.element_required_keys():
            if key not in element:
                errors.append(
                    _err(f"{path}/{key}", key, "missing", None, f"Element must have a `{key}` field.")
                )

        if element.get("type") is not None and element["type"] not in Schema.ELEMENT_TYPES:
            errors.append(
                _err(
                    f"{path}/type",
                    "one of: " + " / ".join(Schema.ELEMENT_TYPES),
                    php_string(element["type"]),
                    element["type"],
                    "Unknown element type — supported: " + ", ".join(Schema.ELEMENT_TYPES),
                )
            )

        for coord in ("x", "y", "w", "h"):
            if coord not in element:
                continue  # already flagged as a missing required key
            if not is_numeric(element[coord]):
                errors.append(
                    _err(
                        f"{path}/{coord}",
                        "number (0..1)",
                        gettype(element[coord]),
                        element[coord],
                        f"Element {coord} must be a number in the 0..1 range "
                        "(slide-relative fraction).",
                    )
                )

        element_type = element.get("type")
        if isinstance(element_type, str):
            if element_type == "text":
                content = element.get("content")
                if not isinstance(content, str):
                    errors.append(
                        _err(
                            f"{path}/content",
                            "string",
                            gettype(content),
                            content,
                            "Text element must have a `content` string.",
                        )
                    )
            elif element_type == "image":
                src = element.get("src")
                if not isinstance(src, str):
                    errors.append(
                        _err(
                            f"{path}/src",
                            "string (URL or data URI)",
                            gettype(src),
                            src,
                            "Image element must have a `src` string.",
                        )
                    )
            elif element_type == "shape":
                shape = element.get("shape")
                if shape not in Schema.SHAPE_KINDS:
                    errors.append(
                        _err(
                            f"{path}/shape",
                            "one of: " + " / ".join(Schema.SHAPE_KINDS),
                            php_string(shape) if shape is not None else "missing",
                            shape,
                            "Shape element must specify a known `shape` kind.",
                        )
                    )
            elif element_type == "code":
                code = element.get("code")
                if not isinstance(code, str):
                    errors.append(
                        _err(
                            f"{path}/code",
                            "string",
                            gettype(code),
                            code,
                            "Code element must have a `code` string.",
                        )
                    )

        return errors

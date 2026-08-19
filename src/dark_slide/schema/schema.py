"""Deck-shape constants + the JSON Schema export. Mirrors PHP ``Schema\\Schema``.

Pure data. The same shape ``@particle-academy/fancy-slides`` emits, which is
why a deck round-trips from the browser editor through any of the three
engines unchanged.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Schema"]


class Schema:
    """Namespace of deck constants. Never instantiated — a mirror of the PHP class."""

    VERSION = "0.1.0"

    ELEMENT_TYPES = ["text", "image", "chart", "code", "table", "shape", "embed"]

    #: Layout presets the writer ships parts for. Unknown layouts fall back to
    #: free placement on ``blank``.
    SLIDE_LAYOUTS = [
        "blank",
        "title",
        "title-content",
        "two-column",
        "section-divider",
        "image-text",
        "text-image",
        "quote",
    ]

    SHAPE_KINDS = ["rect", "rounded-rect", "ellipse", "triangle", "line", "arrow"]

    TEXT_FORMATS = ["markdown", "html", "plain"]

    SLIDE_TRANSITION_KINDS = ["none", "fade", "slide", "zoom"]
    SLIDE_TRANSITION_DIRECTIONS = ["left", "right", "up", "down"]

    ANIMATION_EFFECTS = ["fade", "fly-in", "zoom", "wipe"]
    ANIMATION_TRIGGERS = ["on-click", "with-prev", "after-prev"]
    ANIMATION_DIRECTIONS = ["left", "right", "up", "down"]
    ANIMATION_DEFAULT_DURATION_MS = 500

    DEFAULT_SLIDE_WIDTH_EMU = 9144000
    DEFAULT_SLIDE_HEIGHT_EMU = 5143500

    DEFAULT_THEME_NAME = "default"

    @staticmethod
    def deck_required_keys() -> list[str]:
        return ["id", "title", "slides", "theme"]

    @staticmethod
    def slide_required_keys() -> list[str]:
        return ["id", "elements"]

    @staticmethod
    def element_required_keys() -> list[str]:
        return ["id", "type", "x", "y", "w", "h"]

    @staticmethod
    def json_schema() -> dict[str, Any]:
        """JSON Schema for LLM tool-use registration.

        Hand this to an MCP server or an agent SDK as a write-deck tool's
        ``inputSchema`` and the model gets field-level hints up front, which is
        cheaper than a validation round trip.
        """
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "DarkSlide Deck",
            "type": "object",
            "required": Schema.deck_required_keys(),
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "theme": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "aspectRatio": {"type": "number"},
                        "slideWidth": {"type": "number"},
                        "colors": {
                            "type": "object",
                            "properties": {
                                "background": {"type": "string"},
                                "text": {"type": "string"},
                                "muted": {"type": "string"},
                                "accent": {"type": "string"},
                                "surface": {"type": "string"},
                            },
                        },
                        "fonts": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                                "mono": {"type": "string"},
                            },
                        },
                    },
                },
                "slides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": Schema.slide_required_keys(),
                        "properties": {
                            "id": {"type": "string"},
                            "layout": {"type": "string", "enum": Schema.SLIDE_LAYOUTS},
                            "elements": {"type": "array", "items": _element_json_schema()},
                            "background": {
                                "type": "object",
                                "properties": {
                                    "color": {"type": "string"},
                                    "image": {"type": "string"},
                                    "imageFit": {
                                        "type": "string",
                                        "enum": ["contain", "cover", "fill"],
                                    },
                                    "gradient": {"type": "string"},
                                },
                            },
                            "transition": {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": Schema.SLIDE_TRANSITION_KINDS,
                                    },
                                    "duration": {"type": "number"},
                                    "direction": {
                                        "type": "string",
                                        "enum": Schema.SLIDE_TRANSITION_DIRECTIONS,
                                    },
                                },
                            },
                            "notes": {
                                "type": "string",
                                "description": "Speaker notes (Markdown).",
                            },
                            "narration": {
                                "type": "string",
                                "description": (
                                    "Plain-text narration script for AI-narrated decks / TTS. "
                                    "Opaque to the writer."
                                ),
                            },
                            "metadata": {"type": "object"},
                        },
                    },
                },
                "metadata": {"type": "object"},
            },
        }


def _element_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": Schema.element_required_keys(),
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string", "enum": Schema.ELEMENT_TYPES},
            "x": {"type": "number", "minimum": 0, "maximum": 1},
            "y": {"type": "number", "minimum": 0, "maximum": 1},
            "w": {"type": "number", "minimum": 0, "maximum": 1},
            "h": {"type": "number", "minimum": 0, "maximum": 1},
            "rotation": {"type": "number"},
            "z": {"type": "integer"},
            "locked": {"type": "boolean"},
            "hidden": {"type": "boolean"},
            # Whole-element hyperlink → an <a:hlinkClick> on the shape/picture.
            "href": {"type": "string"},
            # Type-specific fields, kept loose because this is a union.
            "content": {"type": "string"},
            "format": {"type": "string", "enum": Schema.TEXT_FORMATS},
            "style": {"type": "object"},
            "src": {"type": "string"},
            "alt": {"type": "string"},
            "fit": {"type": "string", "enum": ["contain", "cover", "fill", "scale-down"]},
            "shape": {"type": "string", "enum": Schema.SHAPE_KINDS},
            "fill": {"type": "string"},
            "stroke": {"type": "string"},
            "strokeWidth": {"type": "number"},
            "dashed": {"type": "boolean"},
            "radius": {"type": "number"},
            "code": {"type": "string"},
            "language": {"type": "string"},
            "codeTheme": {"type": "string"},
            "columns": {"type": "array"},
            "rows": {"type": "array"},
            "option": {"type": "object"},
            "chartTheme": {"type": "string"},
            "animation": {
                "type": "object",
                "required": ["effect"],
                "properties": {
                    "effect": {"type": "string", "enum": Schema.ANIMATION_EFFECTS},
                    "trigger": {"type": "string", "enum": Schema.ANIMATION_TRIGGERS},
                    "direction": {"type": "string", "enum": Schema.ANIMATION_DIRECTIONS},
                    "duration": {"type": "number"},
                    "delay": {"type": "number"},
                    "order": {"type": "number"},
                    # Text only: animate each paragraph separately. The first
                    # keeps `trigger`; every later one becomes its own click.
                    "byParagraph": {"type": "boolean"},
                },
            },
        },
    }

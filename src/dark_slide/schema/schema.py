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

    #: ``kpiBand`` and ``metadataGrid`` are COMPOSITES: they expand into a
    #: ``table`` before the writer serialises anything, so they add no OOXML
    #: surface and read back as the table they became. See ``table.composites``.
    ELEMENT_TYPES = [
        "text", "image", "chart", "code", "table", "shape", "embed",
        "kpiBand", "metadataGrid",
    ]

    #: The subset of ELEMENT_TYPES that is sugar over a ``table``.
    COMPOSITE_ELEMENT_TYPES = ["kpiBand", "metadataGrid"]

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


def _style_json_schema() -> dict[str, Any]:
    """The `style` object, with the unit of every field the writer reads.

    It used to be published as a bare `{"type": "object"}`, so a model filling it
    in had only the key names, and `fontSize` reads as points. It is design
    pixels, halved on the way into the file: an agent in the fancy-labs document
    lab set a headline at what it called 232pt and the deck carried 116pt. The
    units in this object are not all the same either.

    IDENTICAL to the PHP reference's `Schema::styleJsonSchema()`;
    `tests/test_schema_describes_style_units.py` diffs the two exports.
    """
    return {
        "type": "object",
        "description": (
            "How a text element, or the text inside a shape, looks. The units are NOT uniform: "
            "fontSize is in design pixels and is halved into points, while letterSpacing, "
            "spaceBefore, spaceAfter, padding, radius and the border and accent-bar widths are "
            "already in points, and lineHeight is a multiple."
        ),
        "properties": {
            "fontSize": {"type": "number", "description": "Type size in DESIGN PIXELS on the 1920px-wide fancy-slides canvas, NOT points. The PPTX file carries half, with an 8pt minimum: 96 is written as 48pt, 24 as 12pt, and anything under 16 as 8pt. Default 24."},
            "fontFamily": {"type": "string", "description": "Typeface name. No font is embedded in the file, so where this face is not installed the viewer substitutes another, which also changes how wide the text is."},
            "weight": {"type": ["string", "number"], "description": 'Bold when "bold" or "semibold", or a number of 600 or more. PPTX has only bold and regular, so any other weight renders regular.'},
            "italic": {"type": "boolean"},
            "underline": {"type": "boolean"},
            "color": {"type": "string", "description": 'Text colour as a hex string. Default "#0F172A".'},
            "align": {"type": "string", "description": 'Horizontal alignment: "left" (default), "center", "right" or "justify". Anything else renders left.'},
            "verticalAlign": {"type": "string", "description": 'Vertical alignment inside the box: "top" (default), "middle" or "bottom".'},
            "lineHeight": {"type": "number", "description": "Line spacing as a MULTIPLE of the type size, as in CSS: 1.4 is written as 140% line spacing."},
            "letterSpacing": {"type": "number", "description": "Extra space between letters, in POINTS, not halved: 2 is written as 2pt."},
            "spaceBefore": {"type": "number", "description": "Space above each paragraph, in POINTS, not halved: 6 is written as 6pt."},
            "spaceAfter": {"type": "number", "description": "Space below each paragraph, in POINTS, not halved."},
            "caps": {"type": "string", "description": '"small" for small capitals, or "all" (also "upper") for all capitals.'},
            "bullet": {"type": ["string", "boolean"], "description": 'Marker for list lines ("- item"): omit for a round bullet, "none" or false for no marker, "number" for 1. 2. 3., or any other string to use it as the marker character.'},
            "fill": {"type": ["string", "boolean"], "description": 'Background colour of the box, as a hex string. "none" or false for no fill.'},
            "radius": {"type": "number", "description": "Corner radius of the box, in POINTS."},
            "border": {
                "type": "object",
                "description": "An outline on all four sides of the box. PPTX cannot outline a single side; use accentBar for that.",
                "properties": {
                    "width": {"type": "number", "description": "Line width in POINTS. Default 1; 0 draws no line."},
                    "color": {"type": "string", "description": 'Hex colour. Default "#CBD5E1".'},
                    "style": {"type": "string", "description": '"solid" (default), or a DrawingML dash name such as "dash" or "sysDot".'},
                },
            },
            "padding": {"type": ["number", "object"], "description": "Inset between the box edge and the text, in POINTS: one number for every side (12 is written as 12pt), or {left, right, top, bottom}. When unset the insets are 7.2 left and right and 3.6 top and bottom, widened to clear an accent bar."},
            "accentBar": {
                "type": "object",
                "description": "A coloured bar down one edge of the box, as on a callout. Painted inside the same shape, so it needs no second element.",
                "properties": {
                    "color": {"type": "string", "description": 'Hex colour. Default "#8B5CF6".'},
                    "width": {"type": "number", "description": "Bar width in POINTS. Default 4."},
                    "side": {"type": "string", "description": '"left" (default) or "right".'},
                },
            },
        },
    }


def _element_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": Schema.element_required_keys(),
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string", "enum": Schema.ELEMENT_TYPES},
            "x": {"type": "number", "minimum": 0, "maximum": 1, "description": "Left edge as a FRACTION of the slide width: 0 is the left edge, 0.5 the centre, 1 the right edge. Not pixels."},
            "y": {"type": "number", "minimum": 0, "maximum": 1, "description": "Top edge as a FRACTION of the slide height: 0 is the top, 1 the bottom. Not pixels."},
            "w": {"type": "number", "minimum": 0, "maximum": 1, "description": "Width as a FRACTION of the slide width. 1 spans the whole slide."},
            "h": {"type": "number", "minimum": 0, "maximum": 1, "description": "Height as a FRACTION of the slide height. 1 spans the whole slide."},
            "rotation": {"type": "number"},
            "z": {"type": "integer"},
            "locked": {"type": "boolean"},
            "hidden": {"type": "boolean"},
            # Whole-element hyperlink → an <a:hlinkClick> on the shape/picture.
            "href": {"type": "string"},
            # Type-specific fields, kept loose because this is a union.
            "content": {"type": "string"},
            "format": {"type": "string", "enum": Schema.TEXT_FORMATS},
            "style": _style_json_schema(),
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

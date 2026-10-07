"""Deck-shape constants + the JSON Schema export. Mirrors PHP ``Schema\\Schema``.

Pure data. The same shape ``@particle-academy/fancy-slides`` emits, which is
why a deck round-trips from the browser editor through any of the three
engines unchanged.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Schema"]


def _chart_option_json_schema() -> dict[str, Any]:
    """A chart ELEMENT's `option`, with the translatable surface published. Mirrors
    PHP `Schema::chartOptionJsonSchema()` byte for byte.
    
    This said `{ type: "object" }` and nothing more, and it ends in the same silent
    failure as a mis-shaped table row: the React renderer hands `option` straight to
    ECharts, which draws an EMPTY CANVAS for a shape it does not recognise, and this
    writer hands it to the chart translator, which returns null for anything it
    cannot read and leaves a titled placeholder. Full size, no data, no error.
    
    `categories` is deliberately absent: the engines do not agree on it (this one
    honours it standalone, PHP and Python read it only alongside an `xAxis` without
    `data`), and publishing a contract that is false somewhere is worse than
    publishing the portable one, `xAxis.data`.
    """
    return {
        "type": "object",
        "description": "An Apache ECharts option object. The React renderer passes it to ECharts verbatim, so any valid ECharts option works on screen. This writer renders a NATIVE pptx chart from the subset described here -- series of type bar / line / pie / scatter -- and anything it cannot read falls back, in order, to a pre-rendered chart image taken from the element's `image` or `src` (a data: URI) and then to a titled PLACEHOLDER box. The placeholder is the same size as the chart and carries no data, so an option this writer cannot read looks like a rendering bug rather than an authoring one: prefer the shape below, or supply `image`.",
        "properties": {
            "series": {
                "type": "array",
                "description": "REQUIRED for a native chart: the data to plot. One series object, or a list of them. An option with no series renders an empty canvas in the browser and a placeholder in the file.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["bar", "line", "pie", "scatter"],
                            "description": "The chart kind, defaulting to bar when absent. A type outside this list -- radar, gauge, treemap, any other ECharts type -- renders in the browser but makes the WHOLE option untranslatable here, placeholder included: supply `image` as well if you need one.",
                        },
                        "name": {
                            "type": "string",
                            "description": "The series label, shown in the legend.",
                        },
                        "data": {
                            "type": "array",
                            "description": "The points. A bare number, or {\"value\": number}; for a pie, {\"name\": string, \"value\": number}, whose names become the category labels; for a scatter, {\"value\": [x, y]}. A point this writer cannot read makes the option untranslatable.",
                        },
                        "smooth": {
                            "type": "boolean",
                            "description": "Line series only: curve the line.",
                        },
                        "areaStyle": {
                            "type": "object",
                            "description": "Line series only: fill under the line. Its PRESENCE is what this writer reads -- the styling inside it is browser-only, so an empty object is enough.",
                        },
                    },
                },
            },
            "xAxis": {
                "type": ["object", "array"],
                "description": "Category labels come from `xAxis.data` (or `xAxis[0].data` when given as a list). Absent, the categories are numbered 1, 2, 3 ... -- which is the quiet way a chart ends up correct but unreadable. A pie takes its labels from the point names instead.",
                "properties": {
                    "data": {
                        "type": "array",
                        "description": "The category labels, in order, one per point in each series.",
                    },
                },
            },
            "title": {
                "type": ["object", "array"],
                "description": "The chart title, read from `title.text` (or `title[0].text` when given as a list). It is also what labels the placeholder box if the option cannot be translated, so it is worth setting even on a chart this writer cannot render.",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The title text.",
                    },
                },
            },
        },
    }

def _table_columns_json_schema() -> dict[str, Any]:
    """A table COLUMN, with the item shape published.

    Mirrors PHP ``Schema::tableColumnsJsonSchema()`` BYTE FOR BYTE --
    test_schema_describes_style_units.py compares the two, because three engines
    describing one field three ways is the drift this trio exists to prevent.

    This said ``{"type": "array"}`` and nothing more until 0.3.3. The fact that a
    column key is what every row is keyed BY was readable only from the resolver
    source, so a tool vocabulary generated from this schema could not carry it.
    """
    return {
        "type": "array",
        "description": "The table columns, in display order. A column is an object, and `key` is required.",
        "items": {
            "type": "object",
            "required": ["key"],
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key this column reads from each row object: `rows: [{\"<key>\": \"value\"}]`. Never displayed -- `label` is what the header shows.",
                },
                "label": {
                    "type": "string",
                    "description": "The header text for this column. Falls back to `key` when absent.",
                },
                "width": {
                    "type": "number",
                    "description": "Column width. Every declared width <= 1 makes them FRACTIONS of the table and columns without one share the remainder; any declared width > 1 makes them WEIGHTS and columns without one weigh 1. No width anywhere is an equal split.",
                },
                "align": {
                    "type": "string",
                    "enum": ["left", "center", "right", "justify"],
                    "description": "Horizontal alignment for the whole column. A row or a cell overrides it.",
                },
                "anchor": {
                    "type": "string",
                    "enum": ["top", "middle", "bottom"],
                    "description": "Vertical alignment for the whole column. A row or a cell overrides it.",
                },
            },
        },
    }


def _table_rows_json_schema() -> dict[str, Any]:
    """A table ROW, with both accepted item shapes published.

    Mirrors PHP ``Schema::tableRowsJsonSchema()`` byte for byte.

    Publishing only ``{"type": "array"}`` was the whole of fancy-slides#14. The
    canonical row is an object keyed by each column key; the natural guess from a
    bare column list is a positional row; and that guess failed SILENTLY -- here
    the row was DROPPED entirely, in PHP it rendered a row of empty cells, and the
    grid still drew at full size either way.
    """
    return {
        "type": "array",
        "description": "The table body rows. The header row is generated from the column labels and is NOT listed here.",
        "items": {
            "oneOf": [
                {
                    "type": "object",
                    "description": "The canonical row: one entry per column `key` -- {\"plan\": \"Starter\", \"price\": \"$49\"}. A cell value is a scalar, or a cell spec object ({text, colSpan, rowSpan, fill, bold, align, ...}). A column with no entry renders as an empty cell. Row-level style keys (fill, color, bold, italic, underline, align, anchor, fontSize, letterSpacing, caps, fontFamily, padding, borders) and `height` style the whole row -- put the cell values under `cells` when a column key would collide with one of those.",
                },
                {
                    "type": "array",
                    "description": "A positional row: the values in COLUMN ORDER, read as columns[i].key. [\"Starter\", \"$49\"] means exactly {\"plan\": \"Starter\", \"price\": \"$49\"} when the columns are [{\"key\": \"plan\"}, {\"key\": \"price\"}]. Values past the last column are ignored, and columns past the last value render empty. Prefer the keyed form: it survives a column reorder, and it is the only one that can also carry row-level style.",
                },
            ],
        },
    }

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
                        "aspectRatio": {
                            "type": "number",
                            "description": "Slide width divided by height, 16/9 by default. 16/9, 16/10 and 4/3 are written as PowerPoint's named sizes, anything else as a custom size; the slide is always 10 inches wide.",
                        },
                        "slideWidth": {
                            "type": "number",
                            "description": "Width of the design canvas in pixels, 1920 by default, as fancy-slides uses it. Every length in the deck (fontSize, strokeWidth, padding and the rest) is a pixel on this canvas and keeps its share of the slide width. 1440 reproduces the text sizes of the earlier model, which halved fontSize into points.",
                        },
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

    Published as a bare `{"type": "object"}` until 0.2.1, so a model filling it
    in had only the key names, and `fontSize` reads as points: an agent in the
    fancy-labs document lab set a headline at what it called 232pt and the deck
    carried 116pt. 0.3 gave the whole object ONE unit, the design pixel (see
    :mod:`dark_slide.helpers.design_units`), and this says so.

    IDENTICAL to the PHP reference's `Schema::styleJsonSchema()`;
    `tests/test_schema_describes_style_units.py` diffs the two exports.
    """
    return {
        "type": "object",
        "description": "How a text element, or the text inside a shape, looks. Every length here is in DESIGN PIXELS on the deck's canvas (theme.slideWidth, 1920 by default), the same unit as fontSize, and keeps its share of the slide width: points = px x 720 / slideWidth. lineHeight is a multiple, not a length.",
        "properties": {
            "fontSize": {
                "type": "number",
                "description": "Type size in DESIGN PIXELS on the theme.slideWidth canvas, as fancy-slides renders it. Written to PPTX as px x 720 / slideWidth points, never below 1pt: on the default 1920 canvas 96 is written as 36pt and 28 as 10.5pt. Default 28.",
            },
            "fontFamily": {
                "type": "string",
                "description": "Typeface name. It renders in that face only where the face is installed, unless the host embeds the font file when writing (the `fonts` write option); anywhere else a substitute face is used, which also changes how wide the text is.",
            },
            "weight": {
                "type": ["string", "number"],
                "description": "Bold when \"bold\" or \"semibold\", or a number of 600 or more. PPTX has only bold and regular, so any other weight renders regular.",
            },
            "italic": {
                "type": "boolean",
            },
            "underline": {
                "type": "boolean",
            },
            "color": {
                "type": "string",
                "description": "Text colour as a hex string. Default \"#0F172A\".",
            },
            "align": {
                "type": "string",
                "description": "Horizontal alignment: \"left\" (default), \"center\", \"right\" or \"justify\". Anything else renders left.",
            },
            "verticalAlign": {
                "type": "string",
                "description": "Vertical alignment inside the box: \"top\" (default), \"middle\" or \"bottom\".",
            },
            "lineHeight": {
                "type": "number",
                "description": "Line spacing as a MULTIPLE of the type size, as in CSS: 1.4 is written as 140% line spacing.",
            },
            "letterSpacing": {
                "type": "number",
                "description": "Extra space between letters, in design pixels: on the default canvas 8 is written as 3pt.",
            },
            "spaceBefore": {
                "type": "number",
                "description": "Space above each paragraph, in design pixels: on the default canvas 16 is written as 6pt.",
            },
            "spaceAfter": {
                "type": "number",
                "description": "Space below each paragraph, in design pixels.",
            },
            "caps": {
                "type": "string",
                "description": "\"small\" for small capitals, or \"all\" (also \"upper\") for all capitals.",
            },
            "bullet": {
                "type": ["string", "boolean"],
                "description": "Marker for list lines (\"- item\"): omit for a round bullet, \"none\" or false for no marker, \"number\" for 1. 2. 3., or any other string to use it as the marker character.",
            },
            "fill": {
                "type": ["string", "boolean"],
                "description": "Background colour of the box, as a hex string. \"none\" or false for no fill.",
            },
            "radius": {
                "type": "number",
                "description": "Corner radius of the box, in design pixels.",
            },
            "border": {
                "type": "object",
                "description": "An outline on all four sides of the box. PPTX cannot outline a single side; use accentBar for that.",
                "properties": {
                    "width": {
                        "type": "number",
                        "description": "Line width in design pixels. Unset gives a 1pt line; 0 draws no line.",
                    },
                    "color": {
                        "type": "string",
                        "description": "Hex colour. Default \"#CBD5E1\".",
                    },
                    "style": {
                        "type": "string",
                        "description": "\"solid\" (default), or a DrawingML dash name such as \"dash\" or \"sysDot\".",
                    },
                },
            },
            "padding": {
                "type": ["number", "object"],
                "description": "Inset between the box edge and the text, in design pixels: one number for every side (on the default canvas 32 is written as 12pt), or {left, right, top, bottom}. When unset the insets are PowerPoint's own 7.2pt left and right and 3.6pt top and bottom, widened to clear an accent bar.",
            },
            "accentBar": {
                "type": "object",
                "description": "A coloured bar down one edge of the box, as on a callout. Painted inside the same shape, so it needs no second element.",
                "properties": {
                    "color": {
                        "type": "string",
                        "description": "Hex colour. Default \"#8B5CF6\".",
                    },
                    "width": {
                        "type": "number",
                        "description": "Bar width in design pixels. Unset gives a 4pt bar.",
                    },
                    "side": {
                        "type": "string",
                        "description": "\"left\" (default) or \"right\".",
                    },
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
            "strokeWidth": {
                "type": "number",
                "description": "A shape's outline width in design pixels, 2 by default (0.75pt on the default canvas); 0 for no outline.",
            },
            "dashed": {"type": "boolean"},
            "radius": {
                "type": "number",
                "description": "Corner radius of a rounded-rect shape, in design pixels, 8 by default; capped at half the shorter side. A plain rect has square corners.",
            },
            "code": {"type": "string"},
            "language": {"type": "string"},
            "codeTheme": {"type": "string"},
            "columns": _table_columns_json_schema(),
            "rows": _table_rows_json_schema(),
            "option": _chart_option_json_schema(),
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

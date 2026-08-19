"""The decks the parity + determinism suites run on.

Ported from ``dark-slide-js/tests/parity.test.ts``'s ``SCHEMAS`` table, plus
four decks that table does not have. Each one exists to pin something a port
can get wrong quietly; the docstrings say which, because a fixture nobody can
explain is a fixture nobody will dare delete.

Every deck must pass ``Validator`` unchanged — the PHP oracle validates before
it writes, so an invalid fixture fails as a schema error rather than a
mismatch, which reads like a parity bug and is not one.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DECKS", "PNG_1x1", "META"]

META = {"author": "Parity"}

#: A real 1x1 transparent PNG, not a stub — the writer probes intrinsic
#: dimensions from the header for `fit: cover` / `fit: contain`, so the bytes
#: have to be a parseable image or half the image paths never execute.
PNG_1x1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)

#: A 2x1 PNG — a non-square intrinsic size, so `fit: cover` produces a
#: non-zero crop on one axis and `fit: contain` a real letterbox. A 1x1 image
#: makes both code paths look symmetric and hides an axis mix-up.
PNG_2x1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


DECKS: dict[str, dict[str, Any]] = {}


DECKS["minimal"] = {
    # The floor. One slide, one plain text element, no theme colours, no
    # metadata — the smallest deck that still produces every mandatory part.
    # `test_compared_something` reaches for this one by name.
    "id": "deck-minimal",
    "title": "Minimal",
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "elements": [
                {
                    "id": "e1",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.4,
                    "w": 0.8,
                    "h": 0.2,
                    "content": "Hello",
                    "format": "plain",
                }
            ],
        }
    ],
}


DECKS["unicodeText"] = {
    # Unicode through the markdown tokenizer AND the syntax highlighter.
    #
    # The three engines index strings three different ways — PHP by BYTE, the
    # Node port by UTF-16 code unit, this one by codepoint — and they agree
    # anyway, because both loops only ever cut at ASCII markers and neither a
    # UTF-8 continuation byte nor a UTF-16 surrogate can collide with ASCII.
    # That agreement is incidental rather than designed, so it is pinned here
    # rather than argued about: a well-meant tidy to mb_substr on the PHP side
    # (or to slicing by index on any future port) would change the output with
    # nothing to catch it.
    "id": "deck-unicode",
    "title": "Unicode",
    "metadata": META,
    "theme": {"name": "default", "colors": {"accent": "#8B5CF6"}},
    "slides": [
        {
            "id": "s1",
            "layout": "content",
            "elements": [
                {
                    "id": "e1",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.8,
                    "h": 0.4,
                    "content": (
                        "# 日本語の見出し\n"
                        "café **bold** and naïve `code`\n"
                        "- 太字 **強調** です\n"
                        "- emoji \U0001f389 **bold** end\n"
                        "- á combining mark"
                    ),
                    "format": "markdown",
                },
                {
                    "id": "e2",
                    "type": "code",
                    "x": 0.1,
                    "y": 0.55,
                    "w": 0.8,
                    "h": 0.35,
                    "language": "php",
                    "code": '<?php $x = "café"; // 日本語\n$emoji = "\U0001f389";',
                },
            ],
        }
    ],
}


DECKS["titleText"] = {
    # Markdown block + inline structure on one element: an ATX heading (which
    # gets its own size multiplier), bold and code spans, and two bullets.
    "id": "deck-title",
    "title": "Title Deck",
    "metadata": META,
    "theme": {"name": "default", "colors": {"accent": "#8B5CF6"}},
    "slides": [
        {
            "id": "s1",
            "layout": "title",
            "elements": [
                {
                    "id": "e1",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.3,
                    "w": 0.8,
                    "h": 0.4,
                    "content": "# Heading\nSome **bold** and `code` text\n- bullet one\n- bullet two",
                    "format": "markdown",
                    "style": {
                        "fontSize": 48,
                        "align": "center",
                        "color": "#0F172A",
                        "weight": "bold",
                    },
                }
            ],
        }
    ],
}


DECKS["richSlide"] = {
    # Five element types on one slide plus a gradient background, a directional
    # transition, an external hyperlink and a by-paragraph animation — the
    # densest single slide in the table, and the one that catches an ordering
    # mistake in the shape tree or the timing counter.
    "id": "deck-rich",
    "title": "Rich Deck",
    "metadata": META,
    "theme": {
        "name": "default",
        "colors": {"accent": "#EC4899", "background": "#FFFFFF", "text": "#111111"},
    },
    "slides": [
        {
            "id": "s1",
            "layout": "title-content",
            "background": {"gradient": "linear-gradient(135deg, #fef3c7 0%, #fce7f3 100%)"},
            "transition": {"kind": "slide", "direction": "left", "duration": 600},
            "elements": [
                {
                    "id": "shp1",
                    "type": "shape",
                    "x": 0.05,
                    "y": 0.05,
                    "w": 0.4,
                    "h": 0.3,
                    "shape": "rounded-rect",
                    "fill": "rgba(139,92,246,0.4)",
                    "stroke": "#8B5CF6",
                    "strokeWidth": 3,
                    "dashed": True,
                },
                {
                    "id": "img1",
                    "type": "image",
                    "x": 0.5,
                    "y": 0.05,
                    "w": 0.4,
                    "h": 0.3,
                    "src": PNG_1x1,
                    "alt": "dot",
                    "fit": "contain",
                },
                {
                    "id": "code1",
                    "type": "code",
                    "x": 0.05,
                    "y": 0.4,
                    "w": 0.9,
                    "h": 0.3,
                    "code": "const x: number = 1;\nfunction add(a, b) { return a + b; }",
                    "language": "typescript",
                },
                {
                    "id": "tbl1",
                    "type": "table",
                    "x": 0.05,
                    "y": 0.72,
                    "w": 0.9,
                    "h": 0.2,
                    "columns": [
                        {"key": "name", "label": "Name"},
                        {"key": "score", "label": "Score"},
                    ],
                    "rows": [
                        {"name": "Ada", "score": 99},
                        {"name": "Linus", "score": 88},
                    ],
                },
                {
                    "id": "anim1",
                    "type": "text",
                    "x": 0.05,
                    "y": 0.92,
                    "w": 0.5,
                    "h": 0.06,
                    "content": "Line A\nLine B\nLine C",
                    "format": "markdown",
                    "href": "https://example.com",
                    "animation": {
                        "effect": "fly-in",
                        "direction": "left",
                        "byParagraph": True,
                        "duration": 400,
                        "order": 1,
                    },
                },
            ],
        }
    ],
}


DECKS["chartSlide"] = {
    # A native bar chart: an extra part, an extra content-type override, and an
    # extra slide relationship, all of which have to line up.
    "id": "deck-chart",
    "title": "Chart Deck",
    "metadata": META,
    "theme": {"name": "default", "colors": {"accent": "#06B6D4"}},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "background": {"color": "#0F172A"},
            "elements": [
                {
                    "id": "c1",
                    "type": "chart",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.8,
                    "h": 0.8,
                    "option": {
                        "title": {"text": "Quarterly"},
                        "xAxis": {"type": "category", "data": ["Q1", "Q2", "Q3"]},
                        "yAxis": {"type": "value"},
                        "series": [{"type": "bar", "name": "Rev", "data": [10, 20, 30]}],
                    },
                }
            ],
        }
    ],
}


DECKS["moreCharts"] = {
    # The other three chart kinds. The pie carries a fractional value (7.5) so
    # the `%.6F`-shaped number formatter is exercised, not just the integer
    # fast path; the scatter carries one too.
    "id": "deck-charts2",
    "title": "Charts2",
    "metadata": META,
    "theme": {"name": "default", "colors": {"accent": "#F59E0B"}},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {
                    "id": "line1",
                    "type": "chart",
                    "x": 0.05,
                    "y": 0.05,
                    "w": 0.45,
                    "h": 0.4,
                    "option": {
                        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
                        "yAxis": {"type": "value"},
                        "series": [
                            {"type": "line", "name": "S1", "data": [1, 2, 3], "smooth": True},
                            {"type": "line", "name": "S2", "data": [3, 2, 1]},
                        ],
                    },
                },
                {
                    "id": "pie1",
                    "type": "chart",
                    "x": 0.5,
                    "y": 0.05,
                    "w": 0.45,
                    "h": 0.4,
                    "option": {
                        "series": [
                            {
                                "type": "pie",
                                "name": "Share",
                                "data": [{"name": "X", "value": 5}, {"name": "Y", "value": 7.5}],
                            }
                        ]
                    },
                },
                {
                    "id": "scat1",
                    "type": "chart",
                    "x": 0.05,
                    "y": 0.5,
                    "w": 0.9,
                    "h": 0.45,
                    "option": {
                        "series": [
                            {
                                "type": "scatter",
                                "name": "Pts",
                                "data": [[1, 2], [3, 4.5], [5, 6]],
                            }
                        ]
                    },
                },
            ],
        }
    ],
}


DECKS["imageFallback"] = {
    # An http(s) image with `allow_http_images` off — the default. Both engines
    # must emit the `[image: …]` placeholder and NOT fetch the URL. This is the
    # security default with a test on it, not a comment.
    "id": "deck-fallback",
    "title": "Fallback",
    "metadata": META,
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {
                    "id": "badimg",
                    "type": "image",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.3,
                    "h": 0.3,
                    "src": "https://example.com/missing.png",
                    "alt": "remote",
                }
            ],
        }
    ],
}


DECKS["multiNotes"] = {
    # Two slides, one with notes: the notes part is numbered by SLIDE, so the
    # sequence has a gap, and the second slide's rels must NOT shift.
    "id": "deck-multi",
    "title": "Multi Deck",
    "metadata": META,
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "title",
            "notes": "Speaker notes line one\nline two",
            "elements": [
                {
                    "id": "t1",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.4,
                    "w": 0.8,
                    "h": 0.2,
                    "content": "Slide One",
                    "format": "plain",
                }
            ],
        },
        {
            "id": "s2",
            "layout": "section-divider",
            "transition": {"kind": "fade", "duration": 800},
            "elements": [
                {
                    "id": "t2",
                    "type": "text",
                    "x": 0.1,
                    "y": 0.4,
                    "w": 0.8,
                    "h": 0.2,
                    "content": "Slide Two",
                    "format": "plain",
                    "animation": {"effect": "fade", "duration": 300},
                }
            ],
        },
    ],
}


DECKS["roundingTies"] = {
    # Coordinates that land EXACTLY on a .5 EMU, where the rounding mode is
    # the whole answer.
    #
    #   0.0234375 = 3/128, exactly representable, x 9,144,000 = 214,312.5
    #   0.375     = 3/8,   exactly representable, x 5,143,500 = 1,928,812.5
    #
    # Both truncate to an EVEN integer, so PHP's half-away-from-zero gives
    # 214313 / 1928813 and Python's builtin banker's rounding would give
    # 214312 / 1928812. Every coordinate in every deck runs through that
    # conversion, so a regression in `php_round` is a one-EMU shift in
    # thousands of attributes — and this is the only fixture that would fail.
    "id": "deck-ties",
    "title": "Rounding Ties",
    "metadata": META,
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {
                    "id": "tie1",
                    "type": "shape",
                    "shape": "rect",
                    "x": 0.0234375,
                    "y": 0.375,
                    "w": 0.0234375,
                    "h": 0.375,
                    "fill": "#8B5CF6",
                    "rotation": 30.0000005,
                },
                {
                    "id": "tie2",
                    "type": "text",
                    "x": 0.375,
                    "y": 0.0234375,
                    "w": 0.0234375,
                    "h": 0.375,
                    "content": "tie",
                    "format": "plain",
                    "style": {"fontSize": 25, "align": "left"},
                },
            ],
        }
    ],
}


DECKS["chartPreRendered"] = {
    # A chart carrying BOTH a translatable `option` and a pre-rendered image.
    #
    # This is the live PHP<->Node divergence the polyglot spec records: PHP
    # defaults `chart.mode` to "png" and ships a `<p:pic>`; the Node port
    # always tries native translation first and ships `ppt/charts/chart1.xml`.
    # Different parts, different content types, different rels — and NEITHER
    # engine's fixtures build this element, so both suites pass while the two
    # disagree. PHP is the reference for the trio, so this pins PHP's answer.
    #
    # The second element forces `mode: "native"` on the same shape of input, so
    # the escape hatch is covered too.
    "id": "deck-chart-prerendered",
    "title": "Chart Modes",
    "metadata": META,
    "theme": {"name": "default", "colors": {"accent": "#10B981"}},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {
                    "id": "png-mode",
                    "type": "chart",
                    "x": 0.05,
                    "y": 0.05,
                    "w": 0.4,
                    "h": 0.4,
                    "option": {
                        "xAxis": {"data": ["A", "B"]},
                        "series": [{"type": "bar", "name": "S", "data": [1, 2]}],
                    },
                    "image": PNG_2x1,
                },
                {
                    "id": "native-mode",
                    "type": "chart",
                    "x": 0.5,
                    "y": 0.05,
                    "w": 0.4,
                    "h": 0.4,
                    "mode": "native",
                    "option": {
                        "xAxis": {"data": ["A", "B"]},
                        "series": [{"type": "bar", "name": "S", "data": [1, 2]}],
                    },
                    "image": PNG_2x1,
                },
            ],
        }
    ],
}


DECKS["imageFits"] = {
    # `cover` and `contain` against a NON-SQUARE image (2x1), so the crop lands
    # on one axis and the letterbox on the other. Plus an explicit `crop`,
    # which must win over `fit`.
    "id": "deck-fits",
    "title": "Image Fits",
    "metadata": META,
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {
                    "id": "cover",
                    "type": "image",
                    "x": 0.02,
                    "y": 0.05,
                    "w": 0.3,
                    "h": 0.4,
                    "src": PNG_2x1,
                    "fit": "cover",
                },
                {
                    "id": "contain",
                    "type": "image",
                    "x": 0.35,
                    "y": 0.05,
                    "w": 0.3,
                    "h": 0.4,
                    "src": PNG_2x1,
                    "fit": "contain",
                },
                {
                    "id": "cropped",
                    "type": "image",
                    "x": 0.68,
                    "y": 0.05,
                    "w": 0.3,
                    "h": 0.4,
                    "src": PNG_2x1,
                    "fit": "cover",
                    "crop": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.5},
                },
            ],
        }
    ],
}


DECKS["imageRelIds"] = {
    # THE DUPLICATE-RELATIONSHIP-ID REPRODUCTION.
    #
    # Image rel ids are "rId" + a GLOBAL media counter, while a slide's own
    # rels start at rId1 = layout and rId2 = notesSlide. Verified against the
    # PHP oracle, both slides below collide:
    #
    #   slide1.xml.rels   rId1 slideLayout  +  rId1 image   <-- no notes needed
    #   slide2.xml.rels   rId1 slideLayout, rId2 notesSlide +  rId2 image
    #
    # Relationship ids must be unique within a part, so this is a MALFORMED OPC
    # package, not merely a non-canonical one — and slide 1 shows the trigger is
    # far cheaper than `.ai/plans/polyglot/parity/documents.md` §1.4 records:
    # ONE image on ONE slide is enough. Every pptx with an image that either
    # shipped engine has ever written carries it.
    #
    # The ruling is still that this port REPRODUCES it. Fixing one engine alone
    # would break part-level parity, which is the only cross-runtime guarantee
    # the trio has; §1.4 sequences the fix as one release train across every
    # engine (step U5). This fixture is what that change will have to update in
    # all three at once — and it is the fixture §1.4 says does not exist, which
    # is precisely why the severity went unnoticed.
    "id": "deck-relids",
    "title": "Rel Id Collision",
    "metadata": META,
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "elements": [
                {
                    "id": "img-a",
                    "type": "image",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.3,
                    "h": 0.3,
                    "src": PNG_1x1,
                }
            ],
        },
        {
            "id": "s2",
            "layout": "blank",
            "notes": "Slide two has notes, which claims rId2.",
            "elements": [
                {
                    "id": "img-b",
                    "type": "image",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.3,
                    "h": 0.3,
                    "src": PNG_2x1,
                }
            ],
        },
    ],
}


DECKS["escapingAndLoose"] = {
    # Two things at once.
    #
    # (1) The escaping asymmetry: `Xml.text` leaves an apostrophe alone,
    #     `Xml.attr` turns it into `&apos;`. Element ids become attributes and
    #     content becomes text, so one string in both positions pins both
    #     tables — including the fact that ENT_XML1 gives `&apos;` and not
    #     `&#039;`, which the polyglot spec gets wrong.
    # (2) PHP's loose scalars in a table: a bool cell is "1"/"", a null cell is
    #     "", an integral float is "12" and not "12.0", and a non-scalar cell
    #     goes through json_encode with escaped slashes.
    "id": "deck-escape",
    "title": 'A "quoted" & <tagged> title',
    "metadata": META,
    "theme": {"name": "default"},
    "slides": [
        {
            "id": "s1",
            "layout": "blank",
            "notes": "notes with <angle> & \"quotes\" and an apostrophe's tail",
            "elements": [
                {
                    "id": "it's <weird> & \"quoted\"",
                    "type": "text",
                    "x": 0.05,
                    "y": 0.05,
                    "w": 0.9,
                    "h": 0.2,
                    "content": "5 < 6 && 7 > 2, it's \"fine\"",
                    "format": "plain",
                },
                {
                    "id": "loose",
                    "type": "table",
                    "x": 0.05,
                    "y": 0.3,
                    "w": 0.9,
                    "h": 0.4,
                    "columns": [
                        {"key": "b", "label": "Bool"},
                        {"key": "n", "label": "Null"},
                        {"key": "f", "label": "Float"},
                        {"key": "o", "label": "Object"},
                        {"key": "missing", "label": "Absent"},
                    ],
                    "rows": [
                        {"b": True, "n": None, "f": 12.0, "o": {"a": "x/y"}},
                        {"b": False, "n": None, "f": 12.5, "o": [1, 2]},
                    ],
                },
            ],
        }
    ],
}

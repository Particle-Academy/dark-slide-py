"""dark-slide — a zero-dependency pptx writer + reader for agentic decks.

The Python member of a trio: PHP ``particle-academy/dark-slide``, Node
``@particle-academy/dark-slide``, and this. All three take the same deck —
plain JSON, the shape ``@particle-academy/fancy-slides`` emits — and write the
same OOXML parts, byte for byte, which is asserted by a parity suite that runs
the PHP engine as an oracle rather than being claimed in a README.

    import dark_slide

    deck = {
        "id": "d1",
        "title": "Quarterly",
        "theme": {"name": "default"},
        "slides": [{
            "id": "s1",
            "layout": "title",
            "elements": [{
                "id": "e1", "type": "text",
                "x": 0.1, "y": 0.4, "w": 0.8, "h": 0.2,
                "content": "# Hello", "format": "markdown",
            }],
        }],
    }

    dark_slide.write(deck, "out.pptx")

A deck is a plain ``dict``, never a class — the ``Validator`` is the gate, so
loose agent JSON gets a structured error list it can act on instead of a
``TypeError`` from a constructor.
"""

from __future__ import annotations

from .agent import (
    VERSION,
    describe,
    from_bytes,
    json_schema,
    read,
    to_bytes,
    validate,
    validate_and_repair,
    version,
    write,
)
from .exceptions import SchemaException
from .reader.pptx_reader import PptxReader
from .schema.repairer import Repairer
from .schema.schema import Schema
from .schema.validator import Validator
from .writer.pptx_writer import PptxWriter

#: The dunder alias tooling reads. Bound to the SAME constant :func:`version`
#: returns, so the two cannot disagree — a version living in two places with
#: nothing comparing them drifts, which is how all three shipped engines came
#: to misreport their own numbers at runtime.
__version__ = VERSION

__all__ = [
    "VERSION",
    "__version__",
    # The Agent surface.
    "validate",
    "validate_and_repair",
    "to_bytes",
    "write",
    "read",
    "from_bytes",
    "describe",
    "json_schema",
    "version",
    # Errors.
    "SchemaException",
    # Lower-level building blocks, named as in the peers.
    "Schema",
    "Validator",
    "Repairer",
    "PptxWriter",
    "PptxReader",
]

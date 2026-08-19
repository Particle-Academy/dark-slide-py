"""PHP loose-typing semantics, written down once.

The writer's output is held to the PHP engine byte-for-byte, so every place
PHP quietly coerces a value is a place this port has to coerce it the same
way. Python's own conventions are wrong here in five specific ways and each
one silently changes an emitted byte:

* ``str(True)`` is ``"True"``; PHP's ``(string) true`` is ``"1"``.
* ``str(12.0)`` is ``"12.0"``; PHP's ``(string) 12.0`` is ``"12"``.
* ``round()`` is banker's rounding; PHP's is half away from zero
  (that one lives in :mod:`dark_slide.helpers.emu` because every EMU
  conversion needs it).
* ``bool("0")`` is ``True``; PHP's ``empty("0")`` is ``True`` — i.e. the
  string ``"0"`` is falsy in PHP. A slide whose ``notes`` is ``"0"`` gets a
  notes part in the Node port and none in PHP.
* ``json.dumps`` writes ``", "`` separators and leaves ``/`` alone; PHP's
  ``json_encode`` writes ``,`` and escapes ``\\/``.

The Node port keeps the same inventory in ``src/util.ts``; this is its twin,
plus the four cases Python needs that JavaScript did not.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

__all__ = [
    "is_plain_object",
    "is_numeric",
    "is_scalar",
    "gettype",
    "php_truthy",
    "php_string",
    "php_float",
    "php_int",
    "php_json_encode",
]

# PHP 8's `is_numeric`: optional leading AND trailing whitespace, optional
# sign, decimal or exponent form. `"1e5"` and `"1."` are numeric; `"0x1A"`
# has not been since PHP 7.
_NUMERIC = re.compile(
    r"^[ \t\n\r\v\f]*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[ \t\n\r\v\f]*$"
)

# The leading numeric prefix PHP's `(float)` cast keeps: `(float) "12abc"`
# is `12.0`, not an error.
_LEADING_FLOAT = re.compile(r"^[ \t\n\r\v\f]*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def is_plain_object(value: Any) -> bool:
    """PHP's "associative array" / the Node port's ``isPlainObject``."""
    return isinstance(value, dict)


def is_numeric(value: Any) -> bool:
    """PHP ``is_numeric``. Booleans are NOT numeric in PHP."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return True
    if isinstance(value, str):
        return _NUMERIC.match(value) is not None
    return False


def is_scalar(value: Any) -> bool:
    """PHP ``is_scalar``: int, float, str, bool. NOT null, arrays or objects."""
    return isinstance(value, (bool, int, float, str))


def gettype(value: Any) -> str:
    """The label the validator puts in an error's ``got`` field.

    Mirrors PHP ``gettype`` for the types JSON can carry, with the
    ``Validator``'s own null/array/object special-casing folded in.
    ``bool`` is checked before ``int`` because Python's ``bool`` IS an ``int``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def php_truthy(value: Any) -> bool:
    """The inverse of PHP ``empty()``.

    The one that bites: ``"0"`` is FALSY in PHP. Python's ``bool("0")`` is
    ``True`` and JavaScript's is too, so this is a real three-way divergence
    at ``slide.notes``, ``element.hidden``, ``style.italic``,
    ``element.dashed``, ``series.smooth`` and ``animation.byParagraph``.
    """
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value not in ("", "0")
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    return True


def php_string(value: Any) -> str:
    """PHP's ``(string)`` cast of a scalar.

    ``True`` → ``"1"``, ``False`` → ``""``, ``None`` → ``""``, and a float
    that happens to be integral loses its ``.0`` — PHP prints ``12``, Python
    prints ``12.0``. That last one reaches the output through table cell
    values and chart category labels.
    """
    if value is None:
        return ""
    if value is True:
        return "1"
    if value is False:
        return ""
    if isinstance(value, float):
        return _php_float_to_string(value)
    if isinstance(value, str):
        return value
    return str(value)


def _php_float_to_string(value: float) -> str:
    """PHP's float→string conversion.

    PHP's ``precision`` ini defaults to **14 significant digits** and does not
    round-trip: ``(string)(1/3)`` is ``'0.33333333333333'`` where Python's
    ``repr`` gives 16 threes. Exponent form is normalised too — PHP writes
    ``1.0E+20`` and ``1.0E-7`` where ``%G`` gives ``1E+20`` and ``1E-07``.
    """
    if math.isnan(value):
        return "NAN"
    if math.isinf(value):
        return "INF" if value > 0 else "-INF"
    out = f"{value:.14G}"
    if "E" in out:
        mantissa, exponent = out.split("E")
        if "." not in mantissa:
            mantissa += ".0"
        sign = "-" if exponent.startswith("-") else "+"
        digits = exponent.lstrip("+-").lstrip("0") or "0"
        return f"{mantissa}E{sign}{digits}"
    return out


def php_float(value: Any) -> float:
    """PHP's ``(float)`` cast: non-numeric input becomes ``0.0``.

    A leading numeric prefix is kept (``(float) "12abc"`` is ``12.0``), which
    is why this is not just ``float(value)`` in a ``try``.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _LEADING_FLOAT.match(value)
        if match is None:
            return 0.0
        try:
            return float(match.group(0))
        except ValueError:  # pragma: no cover - regex guarantees parseability
            return 0.0
    if value is None:
        return 0.0
    if isinstance(value, (list, tuple, dict)):
        return 1.0 if len(value) > 0 else 0.0
    return 0.0


def php_int(value: Any) -> int:
    """PHP's ``(int)`` cast — truncation toward zero, never rounding."""
    number = php_float(value)
    if math.isnan(number) or math.isinf(number):
        return 0
    return math.trunc(number)


def php_json_encode(value: Any) -> str:
    """PHP ``json_encode`` with default flags.

    Compact separators, ``\\uXXXX`` escapes for non-ASCII, and ``/`` escaped
    as ``\\/`` — the last of which no JSON library does by default and which
    reaches the output through a non-scalar table cell value.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).replace("/", r"\/")

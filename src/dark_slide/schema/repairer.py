"""Heuristic deck repair. Mirrors PHP ``Schema\\Repairer``.

Applies only harmless fixes — fill in missing ids, clamp coordinates to 0..1,
give an element a minimum visible size, normalise an unknown layout — so a
mostly-correct agent emission does not bounce off the validator over
punctuation.

Never mutates the input: the deck is deep-copied first, which the PHP original
gets for free from array value semantics and the Node port does with
``structuredClone``.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any

from ..util import is_numeric, is_plain_object, php_float
from .schema import Schema

__all__ = ["Repairer"]


class Repairer:
    """Repair a deck. One instance per repair — the id counter is per-run."""

    def __init__(self) -> None:
        self._id_counter = 0

    def repair(self, deck_input: Any) -> dict[str, Any]:
        self._id_counter = 0
        deck: dict[str, Any] = copy.deepcopy(deck_input) if is_plain_object(deck_input) else {}

        if deck.get("id") is None:
            deck["id"] = self._generate_id("deck")
        if deck.get("title") is None:
            deck["title"] = "Untitled"
        deck["theme"] = self._repair_theme(deck.get("theme"))
        deck["slides"] = self._repair_slides(deck.get("slides", []))

        return deck

    def _repair_theme(self, theme: Any) -> dict[str, Any]:
        if not is_plain_object(theme):
            return {"name": Schema.DEFAULT_THEME_NAME}
        if theme.get("name") is None:
            theme["name"] = Schema.DEFAULT_THEME_NAME
        return theme

    def _repair_slides(self, slides: Any) -> list[dict[str, Any]]:
        if not isinstance(slides, list):
            return []
        out: list[dict[str, Any]] = []
        for i, slide in enumerate(slides):
            if not is_plain_object(slide):
                continue
            out.append(self._repair_slide(slide, i))
        return out

    def _repair_slide(self, slide: dict[str, Any], index: int) -> dict[str, Any]:
        if slide.get("id") is None:
            slide["id"] = self._generate_id("s", index)
        slide["elements"] = self._repair_elements(slide.get("elements", []))
        if slide.get("layout") is not None and slide["layout"] not in Schema.SLIDE_LAYOUTS:
            slide["layout"] = "blank"
        return slide

    def _repair_elements(self, elements: Any) -> list[dict[str, Any]]:
        if not isinstance(elements, list):
            return []
        out: list[dict[str, Any]] = []
        for i, element in enumerate(elements):
            if not is_plain_object(element):
                continue
            repaired = self._repair_element(element, i)
            if repaired is not None:
                out.append(repaired)
        return out

    def _repair_element(self, element: dict[str, Any], index: int) -> dict[str, Any] | None:
        # An element with no recognised type is DROPPED, not defaulted —
        # there is no safe way to render an unknown thing.
        if element.get("type") is None or element["type"] not in Schema.ELEMENT_TYPES:
            return None

        if element.get("id") is None:
            element["id"] = self._generate_id("e", index)

        for coord in ("x", "y", "w", "h"):
            value = element.get(coord)
            element[coord] = self._clamp(php_float(value) if is_numeric(value) else 0.0, 0.0, 1.0)

        # An invisible element is not useful; floor it at 2% of the slide.
        if element["w"] < 0.02:
            element["w"] = 0.02
        if element["h"] < 0.02:
            element["h"] = 0.02

        element_type = element["type"]
        if element_type == "text":
            element["content"] = element["content"] if isinstance(element.get("content"), str) else ""
        elif element_type == "image":
            element["src"] = element["src"] if isinstance(element.get("src"), str) else ""
        elif element_type == "shape":
            shape = element.get("shape")
            element["shape"] = shape if isinstance(shape, str) and shape in Schema.SHAPE_KINDS else "rect"
        elif element_type == "code":
            element["code"] = element["code"] if isinstance(element.get("code"), str) else ""

        return element

    def _generate_id(self, prefix: str, index: int = 0) -> str:
        self._id_counter += 1
        stamp = format(int(time.time()) & 0xFFFFFF, "x")
        return f"{prefix}-{stamp}-{str(self._id_counter + index).zfill(3)}"

    @staticmethod
    def _clamp(v: float, minimum: float, maximum: float) -> float:
        if not math.isfinite(v):
            return minimum
        return max(minimum, min(maximum, v))

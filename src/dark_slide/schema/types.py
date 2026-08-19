"""Deck types — **editor support only, never a gate.**

A deck is a plain ``dict``. That is a design decision, not a shortcut: both
peers take loose agent JSON and the ``Validator`` is what decides whether it is
writable. A dataclass would move the gate into a constructor and reject
exactly the sloppy input :func:`dark_slide.validate_and_repair` exists to
rescue — an agent that emitted ``x: "0.1"`` would get a ``TypeError`` instead
of a repaired deck.

So these are ``TypedDict``s with ``total=False``: they type-check what you
write by hand and they do not exist at runtime. Mirrors
``dark-slide-js/src/schema/types.ts``, which mirrors
``@particle-academy/fancy-slides``.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

__all__ = [
    "ElementType",
    "ThemeColors",
    "ThemeFonts",
    "DeckTheme",
    "Transition",
    "Animation",
    "Crop",
    "TableColumn",
    "SlideElement",
    "SlideBackground",
    "Slide",
    "Deck",
    "ValidationError",
    "RepairResult",
    "WriteResult",
    "WriteOptions",
]

ElementType = Literal["text", "image", "chart", "code", "table", "shape", "embed"]


class ThemeColors(TypedDict, total=False):
    background: str
    text: str
    muted: str
    accent: str
    surface: str


class ThemeFonts(TypedDict, total=False):
    heading: str
    body: str
    mono: str


class Transition(TypedDict, total=False):
    kind: Literal["none", "fade", "slide", "zoom"]
    duration: float
    direction: Literal["left", "right", "up", "down"]


class DeckTheme(TypedDict, total=False):
    name: str
    aspectRatio: float
    slideWidth: float
    defaultTransition: Transition
    colors: ThemeColors
    fonts: ThemeFonts


class Animation(TypedDict, total=False):
    effect: Literal["fade", "fly-in", "zoom", "wipe"]
    trigger: Literal["on-click", "with-prev", "after-prev"]
    direction: Literal["left", "right", "up", "down"]
    duration: float
    delay: float
    order: float
    byParagraph: bool


class Crop(TypedDict, total=False):
    x: float
    y: float
    w: float
    h: float


class TableColumn(TypedDict, total=False):
    key: str
    label: str


class SlideElement(TypedDict, total=False):
    id: str
    type: ElementType
    x: float
    y: float
    w: float
    h: float
    rotation: float
    z: int
    locked: bool
    hidden: bool
    href: str
    animation: Animation
    # text
    content: str
    format: Literal["markdown", "html", "plain"]
    style: dict[str, Any]
    # image
    src: str
    alt: str
    fit: Literal["fill", "cover", "contain", "scale-down"]
    crop: Crop
    # shape
    shape: Literal["rect", "rounded-rect", "ellipse", "triangle", "line", "arrow"]
    fill: str
    stroke: str
    strokeWidth: float
    dashed: bool
    radius: float
    # code
    code: str
    language: str
    codeTheme: str
    # table
    columns: list[TableColumn]
    rows: list[dict[str, Any]]
    # chart
    option: dict[str, Any]
    chartTheme: str
    #: A pre-rendered chart PNG as a ``data:`` URI. Declared here and in no
    #: engine's JSON Schema — see the writer's chart-mode note.
    image: str
    #: ``"native"`` forces an OOXML chart part even when a pre-render exists.
    mode: Literal["png", "native"]


class SlideBackground(TypedDict, total=False):
    color: str
    image: str
    imageFit: Literal["contain", "cover", "fill"]
    gradient: str


class Slide(TypedDict, total=False):
    id: str
    layout: str
    elements: list[SlideElement]
    background: SlideBackground
    transition: Transition
    notes: str
    narration: str
    metadata: dict[str, Any]


class Deck(TypedDict, total=False):
    id: str
    title: str
    theme: DeckTheme
    slides: list[Slide]
    metadata: dict[str, Any]


class ValidationError(TypedDict):
    path: str
    expected: str
    got: str
    value: Any
    hint: str


class RepairResult(TypedDict):
    ok: bool
    schema: dict[str, Any]
    errors: list[ValidationError]


class WriteResult(TypedDict):
    path: str
    bytes: int
    slides: int


class WriteOptions(TypedDict, total=False):
    temp_dir: str | None
    allow_http_images: bool

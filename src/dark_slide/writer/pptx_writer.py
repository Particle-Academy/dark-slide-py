"""PPTX (Office Open XML) writer. A faithful port of PHP ``DarkSlide\\Writer\\PptxWriter``.

Builds the archive in memory and returns its bytes. Every emitted string
mirrors the PHP writer byte-for-byte — that is the contract the parity suite
enforces, and it is why this file concatenates strings instead of building an
``ElementTree``. Attribute order, self-closing style and the total absence of
inter-element whitespace are all part of the output; no serialiser exposes
them as knobs.

Parts emitted, in this order::

    [Content_Types].xml
    _rels/.rels
    docProps/{core,app}.xml
    ppt/presentation.xml + _rels
    ppt/theme/theme1.xml
    ppt/slideMasters/slideMaster1.xml + _rels
    ppt/slideLayouts/slideLayout{1..8}.xml + _rels   (all eight, always)
    ppt/slides/slide{N}.xml + _rels
    ppt/notesSlides/notesSlide{N}.xml + _rels        (only slides with notes)
    ppt/charts/chart{N}.xml
    ppt/media/image{N}.{png|jpg|gif|svg|webp}

There is deliberately no ``notesMasters/``, no ``presProps.xml`` and no
``tableStyles.xml`` — the reader does not need them and every extra part is a
part three engines have to agree on.

Per element type: ``text`` → ``<p:sp>`` with styled runs; ``image`` →
``<p:pic>`` honouring ``fit`` and ``crop``; ``shape`` → ``<p:sp>`` with preset
geometry; ``code`` → syntax-highlighted runs on a dark fill; ``chart`` → a
native chart part, a pre-rendered picture, or a titled placeholder; ``table``
→ a real ``<a:tbl>``; ``embed`` → a ``[embed: …]`` placeholder, because PPTX
has no equivalent.
"""

from __future__ import annotations

import base64
import io
import os
import re
import urllib.parse
import urllib.request
import zipfile
from typing import Any

from ..helpers import color as Color
from ..helpers import emu as Emu
from ..helpers import markdown_inline as MarkdownInline
from ..helpers import syntax_highlighter as SyntaxHighlighter
from ..helpers import xml as Xml
from ..helpers.chart_translator import ChartSpec, translate as translate_chart
from ..helpers.emu import php_round
from ..schema.schema import Schema
from ..util import (
    is_numeric,
    is_plain_object,
    is_scalar,
    php_float,
    php_int,
    php_json_encode,
    php_string,
    php_truthy,
)

__all__ = ["PptxWriter", "EPOCH_TIMESTAMP"]

NS_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"

LAYOUT_ORDER = [
    "blank",
    "title",
    "title-content",
    "two-column",
    "section-divider",
    "image-text",
    "text-image",
    "quote",
]

CHART_PALETTE = ["8B5CF6", "EC4899", "06B6D4", "F59E0B", "10B981", "3B82F6", "EF4444", "A855F7"]

#: The document timestamp used when a deck carries none.
#:
#: PHP writes ``gmdate()`` here, which makes its output non-reproducible; this
#: port has to be byte-stable (a golden fixture is impossible otherwise, and
#: ``fancy-conformance`` treats determinism as a precondition for a writer
#: suite). So the clock is an INPUT: ``metadata.created`` / ``metadata.modified``
#: if the deck supplies them, this sentinel otherwise. It matches the fixed DOS
#: date in the zip's local headers, so the two "we do not know when this was
#: made" answers agree.
EPOCH_TIMESTAMP = "1980-01-01T00:00:00Z"

_FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)

_DATA_URI = re.compile(r"^data:([^;,]+)(?:;base64)?,([\s\S]*)$")
_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
_CNVPR = re.compile(r"<p:cNvPr\b([^>]*)/>")

_GRADIENT = re.compile(r"^linear-gradient\((.+)\)\s*;?\s*$", re.IGNORECASE)
_DIRECTION_LIKE = re.compile(r"^(?:to\s+|[-+]?[0-9.]+(?:deg|rad|turn|grad)?\s*$)", re.IGNORECASE)
_STOP_POS = re.compile(r"^(.+?)\s+([0-9.]+%?)\s*$")
_DEG = re.compile(r"^([-+]?[0-9.]+)deg$", re.IGNORECASE)
_RAD = re.compile(r"^([-+]?[0-9.]+)rad$", re.IGNORECASE)
_TURN = re.compile(r"^([-+]?[0-9.]+)turn$", re.IGNORECASE)


def _inner_xfrm(xfrm: str) -> str:
    """The content of an ``<a:xfrm>…</a:xfrm>`` wrapper, for a ``<p:xfrm>``."""
    return xfrm[len("<a:xfrm>") : -len("</a:xfrm>")]


def _ucwords(s: str) -> str:
    """PHP ``ucwords`` — uppercase the first letter of each space-delimited word."""
    return re.sub(r"(^|\s)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)


def _dict(value: Any) -> dict[str, Any]:
    return value if is_plain_object(value) else {}


def _get(container: Any, key: str, default: Any = None) -> Any:
    """``$container[$key] ?? $default`` — null and absent are the same thing."""
    if not is_plain_object(container):
        return default
    value = container.get(key)
    return default if value is None else value


class PptxWriter:
    """The writer. One instance per document; the counters reset per call."""

    def __init__(self, temp_dir: str | None = None, allow_http_images: bool = False) -> None:
        #: Kept for signature parity with the peers. This port assembles the
        #: archive in memory, so nothing is ever written here.
        self.temp_dir = temp_dir
        #: OFF by default. Fetching a remote URL from inside a document writer
        #: is an SSRF surface, so it is a decision the caller makes explicitly.
        self.allow_http_images = allow_http_images

        self._media_counter = 0
        self._chart_counter = 0
        self._media_files: list[tuple[str, bytes]] = []
        self._chart_files: list[tuple[str, str]] = []
        self._theme_accent = "8B5CF6"
        self._tn_id = 0
        self._pending_slide_rels: dict[int, list[dict[str, str]]] = {}

    # ── Entry points ──────────────────────────────────────────────────────

    def write(self, deck: Any, path: str) -> dict[str, Any]:
        """Write a deck to disk. Synchronous, like PHP's."""
        data = self.to_bytes(deck)
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        slides = deck.get("slides") if is_plain_object(deck) else None
        return {
            "path": path,
            "bytes": len(data),
            "slides": len(slides) if isinstance(slides, list) else 0,
        }

    def to_bytes(self, deck: Any) -> bytes:
        """Build the whole archive in memory and return its bytes."""
        self._media_counter = 0
        self._chart_counter = 0
        self._media_files = []
        self._chart_files = []
        self._pending_slide_rels = {}

        theme = _dict(_get(deck, "theme"))
        accent = _get(_dict(_get(theme, "colors")), "accent", "#8B5CF6")
        self._theme_accent = Color.parse(
            accent if isinstance(accent, str) else "#8B5CF6", "8B5CF6"
        )[0]

        slides_value = _get(deck, "slides", [])
        slides: list[Any] = slides_value if isinstance(slides_value, list) else []
        slide_count = len(slides)

        files: list[tuple[str, bytes]] = []

        def add(name: str, content: str | bytes) -> None:
            files.append((name, content.encode("utf-8") if isinstance(content, str) else content))

        # 1. Stage every text part first, so media and chart references are
        #    registered before [Content_Types].xml declares them.
        slides_xml: dict[int, str] = {}
        notes_slides_xml: dict[int, str] = {}
        for i, slide in enumerate(slides):
            one_based = i + 1
            slides_xml[one_based] = self._build_slide_xml(slide, one_based, deck)
            if is_plain_object(slide) and php_truthy(slide.get("notes")):
                notes_slides_xml[one_based] = self._build_notes_slide_xml(slide, one_based)

        notes_ids = list(notes_slides_xml.keys())
        chart_paths = [path for path, _ in self._chart_files]

        # 2. Top-level + ppt-level scaffolding.
        add("[Content_Types].xml", self._build_content_types(slide_count, notes_ids, chart_paths))
        add("_rels/.rels", self._build_top_rels())
        add("docProps/core.xml", self._build_core_props(deck))
        add("docProps/app.xml", self._build_app_props(slide_count))

        add("ppt/presentation.xml", self._build_presentation(slide_count))
        add("ppt/_rels/presentation.xml.rels", self._build_presentation_rels(slide_count))

        add("ppt/theme/theme1.xml", self._build_theme(deck))
        add("ppt/slideMasters/slideMaster1.xml", self._build_slide_master())
        add("ppt/slideMasters/_rels/slideMaster1.xml.rels", self._build_slide_master_rels())

        # 3. All eight layout parts, whether the deck uses them or not.
        for idx, layout_name in enumerate(LAYOUT_ORDER):
            n = idx + 1
            add(f"ppt/slideLayouts/slideLayout{n}.xml", self._build_slide_layout(layout_name))
            add(f"ppt/slideLayouts/_rels/slideLayout{n}.xml.rels", self._build_slide_layout_rels())

        # 4. Slide parts.
        for i in range(1, slide_count + 1):
            raw_layout = _get(slides[i - 1], "layout")
            layout_num = self._layout_number_for(raw_layout if isinstance(raw_layout, str) else None)
            add(f"ppt/slides/slide{i}.xml", slides_xml[i])
            add(
                f"ppt/slides/_rels/slide{i}.xml.rels",
                self._build_slide_rels(i, i in notes_slides_xml, layout_num),
            )

        # 5. Notes parts — numbered by SLIDE, so the sequence has gaps.
        for i in notes_ids:
            add(f"ppt/notesSlides/notesSlide{i}.xml", notes_slides_xml[i])
            add(f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels", self._build_notes_slide_rels(i))

        # 6. Native chart parts.
        for path, xml in self._chart_files:
            add(path, xml)

        # 7. Embedded media.
        for path, payload in self._media_files:
            add(path, payload)

        return _zip(files)

    # ── Top-level parts ───────────────────────────────────────────────────

    def _build_content_types(
        self, slide_count: int, notes_slide_ids: list[int], chart_parts: list[str]
    ) -> str:
        slide_overrides = "".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, slide_count + 1)
        )
        layout_overrides = "".join(
            f'<Override PartName="/ppt/slideLayouts/slideLayout{idx + 1}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            for idx in range(len(LAYOUT_ORDER))
        )
        notes_overrides = "".join(
            f'<Override PartName="/ppt/notesSlides/notesSlide{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
            for i in notes_slide_ids
        )
        chart_overrides = "".join(
            f'<Override PartName="/{path}" '
            'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
            for path in chart_parts
        )

        # Extension defaults. PNG/JPEG are the common cases; the rest are
        # declared defensively for agent-emitted decks carrying those data URIs.
        extension_defaults = (
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Default Extension="jpg" ContentType="image/jpeg"/>'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Default Extension="gif" ContentType="image/gif"/>'
            '<Default Extension="svg" ContentType="image/svg+xml"/>'
            '<Default Extension="webp" ContentType="image/webp"/>'
        )

        return (
            Xml.declaration()
            + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + extension_defaults
            + '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            + '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            + layout_overrides
            + '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            + slide_overrides
            + notes_overrides
            + chart_overrides
            + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            + '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            + "</Types>"
        )

    def _build_top_rels(self) -> str:
        return (
            Xml.declaration()
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            + '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            + '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            + "</Relationships>"
        )

    def _build_core_props(self, deck: Any) -> str:
        title = Xml.text(php_string(_get(deck, "title", "Untitled")))
        metadata = _dict(_get(deck, "metadata"))
        author_value = metadata.get("author")
        author = Xml.text(php_string(author_value)) if author_value is not None else "Dark Slide"

        created = metadata.get("created")
        created_at = created if isinstance(created, str) and created != "" else EPOCH_TIMESTAMP
        modified = metadata.get("modified")
        modified_at = modified if isinstance(modified, str) and modified != "" else created_at

        return (
            Xml.declaration()
            + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            + f"<dc:title>{title}</dc:title>"
            + f"<dc:creator>{author}</dc:creator>"
            + f"<cp:lastModifiedBy>{author}</cp:lastModifiedBy>"
            + f'<dcterms:created xsi:type="dcterms:W3CDTF">{Xml.text(created_at)}</dcterms:created>'
            + f'<dcterms:modified xsi:type="dcterms:W3CDTF">{Xml.text(modified_at)}</dcterms:modified>'
            + "</cp:coreProperties>"
        )

    def _build_app_props(self, slide_count: int) -> str:
        # `AppVersion` is a frozen string in all three engines, not the
        # package version. Bumping it would change every document's bytes.
        return (
            Xml.declaration()
            + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            + "<Application>DarkSlide</Application>"
            + "<AppVersion>0.4.0</AppVersion>"
            + f"<Slides>{slide_count}</Slides>"
            + "</Properties>"
        )

    # ── presentation.xml ──────────────────────────────────────────────────

    def _build_presentation(self, slide_count: int) -> str:
        # Slide ids must be >= 256 per ECMA-376.
        sld_id_lst = "".join(
            f'<p:sldId id="{256 + (i - 1)}" r:id="rId{i + 1}"/>' for i in range(1, slide_count + 1)
        )
        slide_master_rid = f"rId{slide_count + 2}"

        return (
            Xml.declaration()
            + '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            + 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            + 'saveSubsetFonts="1">'
            + f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="{slide_master_rid}"/></p:sldMasterIdLst>'
            + f"<p:sldIdLst>{sld_id_lst}</p:sldIdLst>"
            + f'<p:sldSz cx="{Emu.DEFAULT_SLIDE_WIDTH}" cy="{Emu.DEFAULT_SLIDE_HEIGHT}" type="screen16x9"/>'
            + f'<p:notesSz cx="{Emu.DEFAULT_SLIDE_HEIGHT}" cy="{Emu.DEFAULT_SLIDE_WIDTH}"/>'
            + "</p:presentation>"
        )

    def _build_presentation_rels(self, slide_count: int) -> str:
        rels = '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
        for i in range(1, slide_count + 1):
            rels += (
                f'<Relationship Id="rId{i + 1}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
                f'Target="slides/slide{i}.xml"/>'
            )
        rels += (
            f'<Relationship Id="rId{slide_count + 2}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
            'Target="slideMasters/slideMaster1.xml"/>'
        )

        return (
            Xml.declaration()
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels
            + "</Relationships>"
        )

    # ── theme / master / layout ───────────────────────────────────────────

    def _build_theme(self, deck: Any) -> str:
        theme = _dict(_get(deck, "theme"))
        colors = _dict(_get(theme, "colors"))
        bg = Color.parse(_str_or(colors.get("background"), "#FFFFFF"), "FFFFFF")[0]
        text = Color.parse(_str_or(colors.get("text"), "#0F172A"), "0F172A")[0]
        accent = Color.parse(_str_or(colors.get("accent"), "#8B5CF6"), "8B5CF6")[0]
        # `muted` becomes the secondary dark (headings / chart axes) and
        # `surface` the secondary light (panel fills); both fall back to the
        # classic Office values.
        muted = Color.parse(_str_or(colors.get("muted"), "#44546A"), "44546A")[0]
        surface = Color.parse(_str_or(colors.get("surface"), "#E7E6E6"), "E7E6E6")[0]

        fonts = _dict(_get(theme, "fonts"))
        heading = Xml.attr(php_string(_get(fonts, "heading", "Calibri")))
        body = Xml.attr(php_string(_get(fonts, "body", "Calibri")))

        palette = list(CHART_PALETTE)
        palette[0] = accent

        return (
            Xml.declaration()
            + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="DarkSlide">'
            + "<a:themeElements>"
            + '<a:clrScheme name="DarkSlide">'
            + f'<a:dk1><a:srgbClr val="{text}"/></a:dk1>'
            + f'<a:lt1><a:srgbClr val="{bg}"/></a:lt1>'
            + f'<a:dk2><a:srgbClr val="{muted}"/></a:dk2>'
            + f'<a:lt2><a:srgbClr val="{surface}"/></a:lt2>'
            + f'<a:accent1><a:srgbClr val="{palette[0]}"/></a:accent1>'
            + f'<a:accent2><a:srgbClr val="{palette[1]}"/></a:accent2>'
            + f'<a:accent3><a:srgbClr val="{palette[2]}"/></a:accent3>'
            + f'<a:accent4><a:srgbClr val="{palette[3]}"/></a:accent4>'
            + f'<a:accent5><a:srgbClr val="{palette[4]}"/></a:accent5>'
            + f'<a:accent6><a:srgbClr val="{palette[5]}"/></a:accent6>'
            + '<a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
            + '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>'
            + "</a:clrScheme>"
            + '<a:fontScheme name="DarkSlide">'
            + f'<a:majorFont><a:latin typeface="{heading}"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
            + f'<a:minorFont><a:latin typeface="{body}"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
            + "</a:fontScheme>"
            + '<a:fmtScheme name="DarkSlide">'
            + '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
            + '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
            + "<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>"
            + '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
            + "</a:fmtScheme>"
            + "</a:themeElements>"
            + "</a:theme>"
        )

    def _build_slide_master(self) -> str:
        return (
            Xml.declaration()
            + '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            + 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            + '<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
            + "<p:spTree>"
            + '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            + '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + "</p:spTree>"
            + "</p:cSld>"
            + '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            + f"<p:sldLayoutIdLst>{self._build_slide_layout_id_lst()}</p:sldLayoutIdLst>"
            + "<p:txStyles>"
            + '<p:titleStyle><a:lvl1pPr algn="ctr"><a:defRPr sz="4400"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill></a:defRPr></a:lvl1pPr></p:titleStyle>'
            + '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2400"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill></a:defRPr></a:lvl1pPr></p:bodyStyle>'
            + "<p:otherStyle/>"
            + "</p:txStyles>"
            + "</p:sldMaster>"
        )

    def _build_slide_layout_id_lst(self) -> str:
        return "".join(
            f'<p:sldLayoutId id="{2147483648 + idx + 1}" r:id="rId{idx + 1}"/>'
            for idx in range(len(LAYOUT_ORDER))
        )

    def _build_slide_master_rels(self) -> str:
        rels = "".join(
            f'<Relationship Id="rId{idx + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
            f'Target="../slideLayouts/slideLayout{idx + 1}.xml"/>'
            for idx in range(len(LAYOUT_ORDER))
        )
        rels += (
            f'<Relationship Id="rId{len(LAYOUT_ORDER) + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
            'Target="../theme/theme1.xml"/>'
        )

        return (
            Xml.declaration()
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels
            + "</Relationships>"
        )

    def _layout_number_for(self, layout: str | None) -> int:
        if layout is None:
            return 1
        try:
            return LAYOUT_ORDER.index(layout) + 1
        except ValueError:
            return 1

    def _layout_type_for(self, layout: str) -> str:
        return {
            "title": "title",
            "title-content": "obj",
            "two-column": "twoObj",
            "section-divider": "secHead",
            "image-text": "picTx",
            "text-image": "picTx",
            "quote": "obj",
        }.get(layout, "blank")

    def _build_slide_layout(self, layout: str) -> str:
        layout_type = self._layout_type_for(layout)
        name = Xml.attr(_ucwords(layout.replace("-", " ")))

        return (
            Xml.declaration()
            + '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            + 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            + f'type="{layout_type}" preserve="1">'
            + f'<p:cSld name="{name}">'
            + "<p:spTree>"
            + '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            + '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + "</p:spTree>"
            + "</p:cSld>"
            + "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
            + "</p:sldLayout>"
        )

    def _build_slide_layout_rels(self) -> str:
        return (
            Xml.declaration()
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            + "</Relationships>"
        )

    # ── Per-slide rendering ───────────────────────────────────────────────

    def _build_slide_xml(self, slide: Any, slide_number: int, deck: Any = None) -> str:
        raw_elements = _get(slide, "elements", [])
        elements: list[Any] = list(raw_elements) if isinstance(raw_elements, list) else []
        # Elements without `z` keep their authored order; an explicit `z`
        # overrides it. Both Python's sort and PHP 8's are stable, so equal
        # keys preserve the input order in both.
        elements.sort(key=_z_key)

        shape_id = 2  # 1 is reserved for the slide's own nvGrpSpPr
        shape_tree_xml = ""
        slide_rels: list[dict[str, str]] = []

        bg = self._build_background(_get(slide, "background"), slide_number, slide_rels)

        # Builds for the <p:timing> tree, each paired with the shape id
        # ACTUALLY assigned to its <p:cNvPr> — captured here rather than
        # recomputed, so the target still matches when the id counter skips an
        # element that rendered to nothing.
        animated_builds: list[dict[str, Any]] = []

        for array_index, element in enumerate(elements):
            if not is_plain_object(element) or element.get("type") is None:
                continue
            if php_truthy(element.get("hidden")):
                continue
            xml, rels = self._build_element_xml(element, shape_id, slide_number)
            if xml == "":
                continue
            shape_tree_xml += xml
            slide_rels.extend(rels)

            animation = element.get("animation")
            if is_plain_object(animation) and animation.get("effect") is not None:
                # A by-paragraph build counts paragraphs with the SAME split
                # `_build_text_body` uses, so `<p:pRg st=i end=i>` lines up with
                # `<a:p>` index i. Change one split and you must change both.
                paragraph_count: int | None = None
                if element.get("type") == "text" and php_truthy(animation.get("byParagraph")):
                    paragraph_count = len(php_string(_get(element, "content", "")).split("\n"))

                animated_builds.append(
                    {
                        "shapeId": shape_id,
                        "arrayIndex": array_index,
                        "animation": animation,
                        "paragraphCount": paragraph_count,
                    }
                )

            shape_id += 1

        self._pending_slide_rels[slide_number] = slide_rels

        theme = _dict(_get(deck, "theme"))
        transition = self._build_transition(
            _get(slide, "transition"), _get(theme, "defaultTransition")
        )
        timing = self._build_timing(animated_builds)

        # CT_Slide child order is cSld, clrMapOvr, transition, timing — timing
        # LAST, after any transition.
        return (
            Xml.declaration()
            + '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            + 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            + "<p:cSld>"
            + bg
            + "<p:spTree>"
            + '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            + '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + shape_tree_xml
            + "</p:spTree>"
            + "</p:cSld>"
            + transition
            + timing
            + "</p:sld>"
        )

    def _build_transition(self, transition: Any, fallback: Any) -> str:
        spec = transition if is_plain_object(transition) else None
        if spec is None or spec.get("kind") is None or spec.get("kind") == "none":
            spec = fallback if is_plain_object(fallback) else None
        if spec is None:
            return ""

        kind_value = spec.get("kind")
        kind = kind_value.lower() if isinstance(kind_value, str) else "none"
        if kind == "none" or kind not in Schema.SLIDE_TRANSITION_KINDS:
            return ""

        spd = self._transition_speed(spec.get("duration"))

        if kind == "fade":
            effect = "<p:fade/>"
        elif kind == "slide":
            effect = f'<p:push dir="{self._transition_direction(spec.get("direction"))}"/>'
        elif kind == "zoom":
            # PowerPoint dropped the legacy <p:zoom> from its render engine;
            # an iris circle is the closest effect that actually animates.
            effect = "<p:circle/>"
        else:
            effect = ""
        if effect == "":
            return ""

        return f'<p:transition spd="{spd}">{effect}</p:transition>'

    def _transition_speed(self, duration: Any) -> str:
        if not is_numeric(duration):
            return "med"
        ms = php_float(duration)
        if ms >= 700:
            return "slow"
        if ms <= 250:
            return "fast"
        return "med"

    def _transition_direction(self, direction: Any) -> str:
        name = direction.lower() if isinstance(direction, str) else ""
        return {"left": "l", "right": "r", "up": "u", "down": "d"}.get(name, "l")

    # ── Element entrance animations (<p:timing>) ──────────────────────────

    def _build_timing(self, builds: list[dict[str, Any]]) -> str:
        if not builds:
            return ""

        # `order` first, then authored position. Both engines sort with a
        # stable sort, so equal orders keep array order.
        ordered = sorted(
            builds,
            key=lambda b: php_float(b["animation"].get("order"))
            if is_numeric(b["animation"].get("order"))
            else 0.0,
        )

        sub_builds: list[dict[str, Any]] = []
        for build in ordered:
            paragraph_count = build["paragraphCount"]
            if paragraph_count is None or paragraph_count <= 1:
                sub_builds.append(
                    {
                        "shapeId": build["shapeId"],
                        "arrayIndex": build["arrayIndex"],
                        "animation": build["animation"],
                        "paragraph": None if paragraph_count is None else 0,
                    }
                )
                continue

            for i in range(paragraph_count):
                animation = dict(build["animation"])
                if i > 0:
                    # Every paragraph after the first is its own click step —
                    # that is what "By paragraph" means in PowerPoint.
                    animation["trigger"] = "on-click"
                sub_builds.append(
                    {
                        "shapeId": build["shapeId"],
                        "arrayIndex": build["arrayIndex"],
                        "animation": animation,
                        "paragraph": i,
                    }
                )

        steps: list[list[dict[str, Any]]] = []
        for build in sub_builds:
            trigger = self._animation_trigger(build["animation"].get("trigger"))
            if not steps or trigger == "on-click":
                steps.append([build])
            else:
                steps[-1].append(build)

        # A single counter per slide: 1 = tmRoot, then every step/effect/set
        # node in emission order, and mainSeq takes the id AFTER the loop.
        self._tn_id = 1
        root_id = self._tn_id
        self._tn_id += 1

        step_pars = "".join(self._build_step_par(step) for step in steps)

        main_seq_id = self._tn_id
        self._tn_id += 1

        return (
            "<p:timing>"
            "<p:tnLst>"
            "<p:par>"
            f'<p:cTn id="{root_id}" dur="indefinite" restart="never" nodeType="tmRoot">'
            "<p:childTnLst>"
            '<p:seq concurrent="1" nextAc="seek">'
            f'<p:cTn id="{main_seq_id}" dur="indefinite" nodeType="mainSeq">'
            "<p:childTnLst>"
            f"{step_pars}"
            "</p:childTnLst>"
            "</p:cTn>"
            '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
            "</p:seq>"
            "</p:childTnLst>"
            "</p:cTn>"
            "</p:par>"
            "</p:tnLst>"
            "</p:timing>"
        )

    def _build_target_el(self, spid: int, paragraph: int | None) -> str:
        if paragraph is None:
            return f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
        return (
            f'<p:tgtEl><p:spTgt spid="{spid}">'
            f'<p:txEl><p:pRg st="{paragraph}" end="{paragraph}"/></p:txEl>'
            "</p:spTgt></p:tgtEl>"
        )

    def _build_step_par(self, step: list[dict[str, Any]]) -> str:
        lead = step[0]
        lead_delay = self._animation_delay(lead["animation"])
        lead_duration = self._animation_duration(lead["animation"])

        child_tns = ""
        for i, build in enumerate(step):
            if i == 0:
                begin = lead_delay
            else:
                trigger = self._animation_trigger(build["animation"].get("trigger"))
                base = lead_delay + lead_duration if trigger == "after-prev" else lead_delay
                begin = base + self._animation_delay(build["animation"])
            child_tns += self._build_effect_par(build, begin)

        step_id = self._tn_id
        self._tn_id += 1

        return (
            "<p:par>"
            f'<p:cTn id="{step_id}" fill="hold">'
            '<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
            "<p:childTnLst>"
            f"{child_tns}"
            "</p:childTnLst>"
            "</p:cTn>"
            "</p:par>"
        )

    def _build_effect_par(self, build: dict[str, Any], begin_ms: int) -> str:
        spid = build["shapeId"]
        paragraph = build["paragraph"]
        animation = build["animation"]
        effect = self._animation_effect(animation.get("effect"))
        duration = self._animation_duration(animation)
        direction = self._animation_direction(animation.get("direction"))

        wrap_id = self._tn_id
        self._tn_id += 1

        st_cond = f'<p:stCondLst><p:cond delay="{max(0, begin_ms)}"/></p:stCondLst>'

        if effect == "fly-in":
            effect_xml = self._build_fly_in_effect(spid, duration, direction, paragraph)
        elif effect == "zoom":
            effect_xml = self._build_zoom_effect(spid, duration, paragraph)
        elif effect == "wipe":
            effect_xml = self._build_wipe_effect(spid, duration, direction, paragraph)
        else:
            effect_xml = self._build_fade_effect(spid, duration, paragraph)

        preset_id = self._animation_preset_id(effect)

        return (
            "<p:par>"
            f'<p:cTn id="{wrap_id}" presetID="{preset_id}" presetClass="entr" presetSubtype="0" fill="hold">'
            f"{st_cond}"
            "<p:childTnLst>"
            f"{effect_xml}"
            "</p:childTnLst>"
            "</p:cTn>"
            "</p:par>"
        )

    def _animation_preset_id(self, effect: str) -> int:
        return {"fly-in": 2, "wipe": 22, "zoom": 23}.get(effect, 10)

    def _build_visibility_set(self, spid: int, paragraph: int | None = None) -> str:
        node_id = self._tn_id
        self._tn_id += 1

        return (
            "<p:set>"
            "<p:cBhvr>"
            f'<p:cTn id="{node_id}" dur="1" fill="hold">'
            '<p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            "</p:cTn>"
            f"{self._build_target_el(spid, paragraph)}"
            "<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst>"
            "</p:cBhvr>"
            '<p:to><p:strVal val="visible"/></p:to>'
            "</p:set>"
        )

    def _build_fade_effect(self, spid: int, duration_ms: int, paragraph: int | None = None) -> str:
        node_set = self._build_visibility_set(spid, paragraph)
        node_id = self._tn_id
        self._tn_id += 1

        return node_set + (
            '<p:animEffect transition="in" filter="fade">'
            "<p:cBhvr>"
            f'<p:cTn id="{node_id}" dur="{duration_ms}"/>'
            f"{self._build_target_el(spid, paragraph)}"
            "</p:cBhvr>"
            "</p:animEffect>"
        )

    def _build_fly_in_effect(
        self, spid: int, duration_ms: int, direction: str, paragraph: int | None = None
    ) -> str:
        node_set = self._build_visibility_set(spid, paragraph)

        attr, from_expr, to_expr = {
            "right": ("ppt_x", "1+#ppt_w/2", "#ppt_x"),
            "up": ("ppt_y", "0-#ppt_h/2", "#ppt_y"),
            "down": ("ppt_y", "1+#ppt_h/2", "#ppt_y"),
        }.get(direction, ("ppt_x", "0-#ppt_w/2", "#ppt_x"))

        node_id = self._tn_id
        self._tn_id += 1

        return node_set + (
            '<p:anim calcmode="lin" valueType="num">'
            '<p:cBhvr additive="base">'
            f'<p:cTn id="{node_id}" dur="{duration_ms}" fill="hold"/>'
            f"{self._build_target_el(spid, paragraph)}"
            f"<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst>"
            "</p:cBhvr>"
            "<p:tavLst>"
            f'<p:tav tm="0"><p:val><p:strVal val="{from_expr}"/></p:val></p:tav>'
            f'<p:tav tm="100000"><p:val><p:strVal val="{to_expr}"/></p:val></p:tav>'
            "</p:tavLst>"
            "</p:anim>"
        )

    def _build_zoom_effect(self, spid: int, duration_ms: int, paragraph: int | None = None) -> str:
        node_set = self._build_visibility_set(spid, paragraph)
        fade_id = self._tn_id
        self._tn_id += 1
        scale_id = self._tn_id
        self._tn_id += 1

        fade = (
            '<p:animEffect transition="in" filter="fade">'
            "<p:cBhvr>"
            f'<p:cTn id="{fade_id}" dur="{duration_ms}"/>'
            f"{self._build_target_el(spid, paragraph)}"
            "</p:cBhvr>"
            "</p:animEffect>"
        )
        scale = (
            "<p:animScale>"
            "<p:cBhvr>"
            f'<p:cTn id="{scale_id}" dur="{duration_ms}" fill="hold"/>'
            f"{self._build_target_el(spid, paragraph)}"
            "</p:cBhvr>"
            '<p:from x="0" y="0"/>'
            '<p:to x="100000" y="100000"/>'
            "</p:animScale>"
        )

        return node_set + fade + scale

    def _build_wipe_effect(
        self, spid: int, duration_ms: int, direction: str, paragraph: int | None = None
    ) -> str:
        node_set = self._build_visibility_set(spid, paragraph)

        # The filter names the edge the wipe travels FROM, so it is the
        # opposite of the deck's direction.
        filter_name = {
            "right": "wipe(left)",
            "up": "wipe(down)",
            "down": "wipe(up)",
        }.get(direction, "wipe(right)")

        node_id = self._tn_id
        self._tn_id += 1

        return node_set + (
            f'<p:animEffect transition="in" filter="{filter_name}">'
            "<p:cBhvr>"
            f'<p:cTn id="{node_id}" dur="{duration_ms}"/>'
            f"{self._build_target_el(spid, paragraph)}"
            "</p:cBhvr>"
            "</p:animEffect>"
        )

    def _animation_effect(self, effect: Any) -> str:
        name = effect.lower() if isinstance(effect, str) else ""
        return name if name in Schema.ANIMATION_EFFECTS else "fade"

    def _animation_trigger(self, trigger: Any) -> str:
        name = trigger.lower() if isinstance(trigger, str) else ""
        return name if name in Schema.ANIMATION_TRIGGERS else "on-click"

    def _animation_direction(self, direction: Any) -> str:
        name = direction.lower() if isinstance(direction, str) else ""
        return name if name in Schema.ANIMATION_DIRECTIONS else "left"

    def _animation_duration(self, animation: dict[str, Any]) -> int:
        value = animation.get("duration")
        duration = (
            int(php_round(php_float(value)))
            if is_numeric(value)
            else Schema.ANIMATION_DEFAULT_DURATION_MS
        )
        return max(1, duration)

    def _animation_delay(self, animation: dict[str, Any]) -> int:
        value = animation.get("delay")
        delay = int(php_round(php_float(value))) if is_numeric(value) else 0
        return max(0, delay)

    # ── Background ────────────────────────────────────────────────────────

    def _build_background(self, bg: Any, slide_number: int, rels: list[dict[str, str]]) -> str:
        if not is_plain_object(bg):
            return ""

        image = bg.get("image")
        if isinstance(image, str) and image != "":
            embed = self._stage_media(image, slide_number)
            if embed is not None:
                rels.append(
                    {
                        "id": embed["relId"],
                        "type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                        "target": embed["target"],
                    }
                )
                return (
                    "<p:bg><p:bgPr>"
                    f'<a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{embed["relId"]}"/>'
                    "<a:srcRect/><a:stretch><a:fillRect/></a:stretch></a:blipFill>"
                    "<a:effectLst/></p:bgPr></p:bg>"
                )
            # Fall through to gradient / colour when the image did not stage.

        gradient = bg.get("gradient")
        if isinstance(gradient, str):
            grad = self._parse_gradient(gradient)
            if grad is not None:
                return f"<p:bg><p:bgPr>{grad}<a:effectLst/></p:bgPr></p:bg>"

        color = bg.get("color")
        if isinstance(color, str):
            hex_value, alpha = Color.parse(color)
            return (
                f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{hex_value}">'
                f'<a:alpha val="{alpha}"/></a:srgbClr></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
            )

        return ""

    def _parse_gradient(self, css_input: str) -> str | None:
        """A CSS ``linear-gradient(...)`` into an ``<a:gradFill>``, or None."""
        css = css_input.strip()
        m = _GRADIENT.match(css)
        if not m:
            return None

        # Split on top-level commas so `rgba(1, 2, 3, 0.5)` inside a stop
        # survives.
        parts = self._split_top_level_commas(m.group(1))
        if len(parts) < 2:
            return None

        angle_deg = 90.0  # the CSS default: top to bottom
        first = parts[0].strip()
        if _DIRECTION_LIKE.match(first):
            angle_deg = self._parse_gradient_direction(first)
            parts.pop(0)

        stops: list[tuple[str, float]] = []
        count = len(parts)
        for i, part_raw in enumerate(parts):
            part = part_raw.strip()
            sm = _STOP_POS.match(part)
            if sm:
                color_str = sm.group(1)
                pos_str = sm.group(2)
                if pos_str.endswith("%"):
                    pos = php_float(pos_str.rstrip("%")) / 100
                else:
                    pos = php_float(pos_str)
            else:
                color_str = part
                pos = 0.0 if count <= 1 else i / (count - 1)
            hex_value = Color.parse(color_str)[0]
            stops.append((hex_value, max(0.0, min(1.0, pos))))

        gs_list = "".join(
            f'<a:gs pos="{int(php_round(pos * 100000))}"><a:srgbClr val="{hex_value}"/></a:gs>'
            for hex_value, pos in stops
        )

        # PPTX angles are 60000ths of a degree clockwise from EAST; CSS is
        # clockwise from north. Subtract 90, then wrap into 0..360.
        pptx_angle = int(php_round((angle_deg - 90) * 60000))
        pptx_angle = ((pptx_angle % (360 * 60000)) + 360 * 60000) % (360 * 60000)

        return (
            '<a:gradFill flip="none" rotWithShape="1">'
            f"<a:gsLst>{gs_list}</a:gsLst>"
            f'<a:lin ang="{pptx_angle}" scaled="0"/>'
            "</a:gradFill>"
        )

    def _split_top_level_commas(self, s: str) -> list[str]:
        out: list[str] = []
        depth = 0
        buf = ""
        for c in s:
            if c == "(":
                depth += 1
                buf += c
            elif c == ")":
                depth = max(0, depth - 1)
                buf += c
            elif c == "," and depth == 0:
                out.append(buf)
                buf = ""
            else:
                buf += c
        if buf != "":
            out.append(buf)
        return out

    def _parse_gradient_direction(self, dir_input: str) -> float:
        d = dir_input.strip()
        m = _DEG.match(d)
        if m:
            return php_float(m.group(1))
        m = _RAD.match(d)
        if m:
            import math

            return php_float(m.group(1)) * 180 / math.pi
        m = _TURN.match(d)
        if m:
            return php_float(m.group(1)) * 360
        return {
            "to top": 0.0,
            "to top right": 45.0,
            "to right": 90.0,
            "to bottom right": 135.0,
            "to bottom": 180.0,
            "to bottom left": 225.0,
            "to left": 270.0,
            "to top left": 315.0,
        }.get(d.lower(), 180.0)

    # ── Element dispatch ──────────────────────────────────────────────────

    def _build_element_xml(
        self, element: dict[str, Any], shape_id: int, slide_number: int
    ) -> tuple[str, list[dict[str, str]]]:
        rels: list[dict[str, str]] = []
        element_type = element.get("type")
        if element_type == "text":
            xml = self._build_text_shape(element, shape_id)
        elif element_type == "image":
            xml = self._build_image_shape(element, shape_id, slide_number, rels)
        elif element_type == "shape":
            xml = self._build_shape(element, shape_id)
        elif element_type == "code":
            xml = self._build_code_shape(element, shape_id)
        elif element_type == "chart":
            xml = self._build_chart(element, shape_id, slide_number, rels)
        elif element_type == "table":
            xml = self._build_table(element, shape_id)
        elif element_type == "embed":
            xml = self._build_placeholder(
                "[embed: " + php_string(_get(element, "src", "")) + "]", element, shape_id
            )
        else:
            xml = ""

        xml = self._apply_hyperlink(xml, element, shape_id, rels)

        return (xml, rels)

    def _apply_hyperlink(
        self, xml: str, element: dict[str, Any], shape_id: int, rels: list[dict[str, str]]
    ) -> str:
        """Inject ``<a:hlinkClick>`` into the shape's first ``<p:cNvPr>``.

        The relationship and drawingml namespaces are already declared on the
        slide root, so the injected element needs no ``xmlns`` of its own.
        """
        href = element.get("href")
        if not isinstance(href, str) or href == "" or xml == "":
            return xml

        rel_id = f"rIdLink{shape_id}"
        rels.append(
            {
                "id": rel_id,
                "type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                "target": href,
                "mode": "External",
            }
        )

        hlink = f'<a:hlinkClick r:id="{rel_id}"/>'
        injected, count = _CNVPR.subn(
            lambda m: f"<p:cNvPr{m.group(1)}>{hlink}</p:cNvPr>", xml, count=1
        )

        return injected if count > 0 else xml

    # ── Element renderers ─────────────────────────────────────────────────

    def _build_text_shape(self, element: dict[str, Any], shape_id: int) -> str:
        xfrm = self._xfrm_from_fractions(element)
        style = element.get("style")
        body = self._build_text_body(
            php_string(_get(element, "content", "")),
            style if is_plain_object(style) else {},
            php_string(_get(element, "format", "plain")),
        )
        element_id = _get(element, "id", f"text-{shape_id}")

        return (
            "<p:sp>"
            "<p:nvSpPr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}"/>'
            '<p:cNvSpPr txBox="1"/>'
            "<p:nvPr/>"
            "</p:nvSpPr>"
            "<p:spPr>"
            f"{xfrm}"
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            "<a:noFill/>"
            "</p:spPr>"
            f"{body}"
            "</p:sp>"
        )

    def _build_image_shape(
        self, element: dict[str, Any], shape_id: int, slide_number: int, rels: list[dict[str, str]]
    ) -> str:
        src = php_string(_get(element, "src", ""))
        embed = self._stage_media(src, slide_number)
        if embed is None:
            # Could not obtain the bytes — degrade to a labelled text box
            # rather than emitting a dangling reference.
            return self._build_placeholder(f"[image: {src}]", element, shape_id)

        rel_id = embed["relId"]
        rels.append(
            {
                "id": rel_id,
                "type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                "target": embed["target"],
            }
        )

        element_id = _get(element, "id", f"image-{shape_id}")
        alt = Xml.attr(php_string(_get(element, "alt", "")))
        fit_value = element.get("fit")
        fit = fit_value.lower() if isinstance(fit_value, str) else "fill"

        box_x = Emu.from_frac_x(php_float(_get(element, "x", 0)))
        box_y = Emu.from_frac_y(php_float(_get(element, "y", 0)))
        box_w = max(1, Emu.from_frac_x(php_float(_get(element, "w", 0))))
        box_h = max(1, Emu.from_frac_y(php_float(_get(element, "h", 0))))

        intrinsic = image_size(embed["bytes"])
        img_w = intrinsic[0] if intrinsic else 0
        img_h = intrinsic[1] if intrinsic else 0

        off_x, off_y, ext_w, ext_h = box_x, box_y, box_w, box_h
        src_rect = ""

        explicit_crop = self._image_crop_rect(element.get("crop"))
        if explicit_crop is not None:
            src_rect = explicit_crop
        elif fit == "cover" and img_w > 0 and img_h > 0:
            src_rect = self._cover_src_rect(box_w, box_h, img_w, img_h)
        elif fit in ("contain", "scale-down") and img_w > 0 and img_h > 0:
            off_x, off_y, ext_w, ext_h = self._contained_rect(
                box_x, box_y, box_w, box_h, img_w, img_h
            )

        blip_fill = (
            f'<p:blipFill><a:blip r:embed="{rel_id}"/>{src_rect}'
            "<a:stretch><a:fillRect/></a:stretch></p:blipFill>"
        )

        return (
            "<p:pic>"
            "<p:nvPicPr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}" descr="{alt}"/>'
            '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
            "<p:nvPr/>"
            "</p:nvPicPr>"
            f"{blip_fill}"
            "<p:spPr>"
            f'<a:xfrm><a:off x="{off_x}" y="{off_y}"/><a:ext cx="{ext_w}" cy="{ext_h}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            "</p:spPr>"
            "</p:pic>"
        )

    def _image_crop_rect(self, crop: Any) -> str | None:
        """An ``<a:srcRect>`` for an explicit ``{x,y,w,h}`` crop (0..1 of source)."""
        if not is_plain_object(crop):
            return None
        values = []
        for key in ("x", "y", "w", "h"):
            value = crop.get(key)
            if not is_numeric(value):
                return None
            values.append(php_float(value))
        x, y, w, h = values

        left = int(php_round(x * 100000))
        top = int(php_round(y * 100000))
        right = int(php_round((1 - x - w) * 100000))
        bottom = int(php_round((1 - y - h) * 100000))
        left = max(0, min(100000, left))
        top = max(0, min(100000, top))
        right = max(0, min(100000, right))
        bottom = max(0, min(100000, bottom))

        return f'<a:srcRect l="{left}" t="{top}" r="{right}" b="{bottom}"/>'

    def _cover_src_rect(self, box_w: int, box_h: int, img_w: int, img_h: int) -> str:
        """Centre-crop insets so the image fills the box without distortion."""
        box_aspect = box_w / box_h
        img_aspect = img_w / img_h
        left = top = right = bottom = 0

        if img_aspect > box_aspect:
            visible = box_aspect / img_aspect
            inset = int(php_round((1 - visible) / 2 * 100000))
            left = right = inset
        elif img_aspect < box_aspect:
            visible = img_aspect / box_aspect
            inset = int(php_round((1 - visible) / 2 * 100000))
            top = bottom = inset

        return f'<a:srcRect l="{left}" t="{top}" r="{right}" b="{bottom}"/>'

    def _contained_rect(
        self, box_x: int, box_y: int, box_w: int, box_h: int, img_w: int, img_h: int
    ) -> tuple[int, int, int, int]:
        """Letterbox: scale to fit, then centre inside the box."""
        scale = min(box_w / img_w, box_h / img_h)
        ext_w = max(1, int(php_round(img_w * scale)))
        ext_h = max(1, int(php_round(img_h * scale)))
        off_x = box_x + int(php_round((box_w - ext_w) / 2))
        off_y = box_y + int(php_round((box_h - ext_h) / 2))
        return (off_x, off_y, ext_w, ext_h)

    def _build_shape(self, element: dict[str, Any], shape_id: int) -> str:
        xfrm = self._xfrm_from_fractions(element)
        element_id = _get(element, "id", f"shape-{shape_id}")
        kind = php_string(_get(element, "shape", "rect"))
        prst = {
            "rect": "rect",
            "rounded-rect": "roundRect",
            "ellipse": "ellipse",
            "triangle": "triangle",
            "line": "line",
            "arrow": "rightArrow",
        }.get(kind, "rect")

        fill_hex, fill_alpha = Color.parse(
            _str_or(element.get("fill"), "rgba(139,92,246,0.15)"), "8B5CF6"
        )
        stroke_hex = Color.parse(_str_or(element.get("stroke"), "#8B5CF6"), "8B5CF6")[0]
        stroke_width_emu = Emu.from_pt(php_float(_get(element, "strokeWidth", 2)))
        dash = '<a:prstDash val="dash"/>' if php_truthy(element.get("dashed")) else ""

        fill_xml = (
            "<a:noFill/>"
            if fill_alpha == 0
            else f'<a:solidFill><a:srgbClr val="{fill_hex}"><a:alpha val="{fill_alpha}"/></a:srgbClr></a:solidFill>'
        )

        return (
            "<p:sp>"
            "<p:nvSpPr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}"/>'
            "<p:cNvSpPr/>"
            "<p:nvPr/>"
            "</p:nvSpPr>"
            "<p:spPr>"
            f"{xfrm}"
            f'<a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>'
            f"{fill_xml}"
            f'<a:ln w="{stroke_width_emu}"><a:solidFill><a:srgbClr val="{stroke_hex}"/></a:solidFill>{dash}</a:ln>'
            "</p:spPr>"
            '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>'
            "</p:sp>"
        )

    def _build_code_shape(self, element: dict[str, Any], shape_id: int) -> str:
        xfrm = self._xfrm_from_fractions(element)
        code = php_string(_get(element, "code", ""))
        element_id = _get(element, "id", f"code-{shape_id}")
        language_value = element.get("language")
        language = php_string(language_value) if language_value is not None else None
        body = self._build_highlighted_code_body(code, language)

        return (
            "<p:sp>"
            "<p:nvSpPr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}"/>'
            '<p:cNvSpPr txBox="1"/>'
            "<p:nvPr/>"
            "</p:nvSpPr>"
            "<p:spPr>"
            f"{xfrm}"
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            '<a:solidFill><a:srgbClr val="0F172A"/></a:solidFill>'
            "</p:spPr>"
            f"{body}"
            "</p:sp>"
        )

    def _build_highlighted_code_body(self, code: str, language: str | None) -> str:
        sz = Emu.hundredths_of_point(12)
        paragraphs = ""
        for line in code.split("\n"):
            tokens = SyntaxHighlighter.tokenize(line, language)
            runs = ""
            for token in tokens:
                if token["text"] == "":
                    continue
                token_color = SyntaxHighlighter.color_for(token["kind"])
                runs += (
                    "<a:r>"
                    f'<a:rPr lang="en-US" sz="{sz}">'
                    f'<a:solidFill><a:srgbClr val="{token_color}"/></a:solidFill>'
                    '<a:latin typeface="Consolas"/>'
                    "</a:rPr>"
                    f"<a:t>{Xml.text(token['text'])}</a:t>"
                    "</a:r>"
                )
            if runs == "":
                runs = f'<a:endParaRPr lang="en-US" sz="{sz}"/>'
            paragraphs += f'<a:p><a:pPr algn="l"/>{runs}</a:p>'

        return (
            "<p:txBody>"
            '<a:bodyPr wrap="square" anchor="t" rtlCol="0" lIns="91440" tIns="45720" rIns="91440" bIns="45720"/>'
            "<a:lstStyle/>"
            f"{paragraphs}"
            "</p:txBody>"
        )

    def _build_table(self, element: dict[str, Any], shape_id: int) -> str:
        columns = _as_sequence(element.get("columns"))
        rows = _as_sequence(element.get("rows"))
        if not columns:
            return self._build_placeholder("[table: no columns]", element, shape_id)

        total_width_emu = Emu.from_frac_x(php_float(_get(element, "w", 0.5)))
        col_count = len(columns)
        col_width_emu = int(php_round(total_width_emu / max(1, col_count)))

        # Approximate row heights: 40pt header, 30pt body.
        header_row_h = Emu.from_pt(40)
        body_row_h = Emu.from_pt(30)

        grid_cols = f'<a:gridCol w="{col_width_emu}"/>' * col_count

        header_cells = ""
        for col in columns:
            col_dict = _dict(col)
            label = php_string(_get(col_dict, "label", _get(col_dict, "key", "")))
            header_cells += self._build_table_cell(label, True)
        header_row = f'<a:tr h="{header_row_h}">{header_cells}</a:tr>'

        body_rows = ""
        row_index = 0
        for row in rows:
            if not isinstance(row, (dict, list)):
                continue
            row_dict = _dict(row)
            cells = ""
            for col in columns:
                key = php_string(_get(_dict(col), "key", ""))
                value = row_dict.get(key)
                if value is None:
                    value = ""
                text = php_string(value) if is_scalar(value) else php_json_encode(value)
                cells += self._build_table_cell(text, False, row_index % 2 == 1)
            body_rows += f'<a:tr h="{body_row_h}">{cells}</a:tr>'
            row_index += 1

        xfrm = self._xfrm_from_fractions(element)
        element_id = _get(element, "id", f"table-{shape_id}")

        return (
            "<p:graphicFrame>"
            "<p:nvGraphicFramePr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}"/>'
            '<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
            "<p:nvPr/>"
            "</p:nvGraphicFramePr>"
            f"<p:xfrm>{_inner_xfrm(xfrm)}</p:xfrm>"
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
            "<a:tbl>"
            '<a:tblPr firstRow="1" bandRow="1"><a:tableStyleId>{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}</a:tableStyleId></a:tblPr>'
            f"<a:tblGrid>{grid_cols}</a:tblGrid>"
            f"{header_row}"
            f"{body_rows}"
            "</a:tbl>"
            "</a:graphicData>"
            "</a:graphic>"
            "</p:graphicFrame>"
        )

    def _build_table_cell(self, text: str, header: bool, striped: bool = False) -> str:
        if header:
            fill = '<a:solidFill><a:srgbClr val="8B5CF6"/></a:solidFill>'
            text_color = "FFFFFF"
            bold = ' b="1"'
        else:
            fill = (
                '<a:solidFill><a:srgbClr val="F8FAFC"/></a:solidFill>' if striped else "<a:noFill/>"
            )
            text_color = "0F172A"
            bold = ""

        return (
            "<a:tc>"
            "<a:txBody>"
            '<a:bodyPr wrap="square" anchor="ctr" lIns="91440" tIns="45720" rIns="91440" bIns="45720"/>'
            "<a:lstStyle/>"
            f'<a:p><a:pPr algn="l"/><a:r><a:rPr lang="en-US" sz="1400"{bold}>'
            f'<a:solidFill><a:srgbClr val="{text_color}"/></a:solidFill></a:rPr>'
            f"<a:t>{Xml.text(text)}</a:t></a:r></a:p>"
            "</a:txBody>"
            f"<a:tcPr>{fill}</a:tcPr>"
            "</a:tc>"
        )

    # ── Charts ────────────────────────────────────────────────────────────

    def _build_chart(
        self, element: dict[str, Any], shape_id: int, slide_number: int, rels: list[dict[str, str]]
    ) -> str:
        """A chart element.

        **The default export mode is PNG, not native.** When the element
        carries a pre-rendered ``data:`` URI (on ``image`` or ``src``) the
        chart ships as a ``<p:pic>`` so the deck matches the browser editor
        pixel for pixel; ``mode: "native"`` forces the OOXML chart part.

        This is a live PHP↔Node divergence: the Node port always tries native
        translation first, so a chart with BOTH a translatable ``option`` and
        a pre-render produces a picture here and ``ppt/charts/chart1.xml``
        there — different parts, different content types, different rels.
        PHP is the reference for the trio, so this port follows PHP; the
        ``chartPreRendered`` parity fixture pins it rather than leaving it to
        be rediscovered.
        """
        option_value = element.get("option")
        option = option_value if is_plain_object(option_value) else None

        mode_value = element.get("mode")
        mode = mode_value if isinstance(mode_value, str) else "png"

        if mode != "native":
            png = self._chart_pre_render_src(element)
            if png is not None:
                image_element = dict(element)
                image_element["src"] = png
                image_element["fit"] = _get(element, "fit", "contain")
                return self._build_image_shape(image_element, shape_id, slide_number, rels)
            # No PNG available — degrade to native below.

        spec = translate_chart(option) if option is not None else None

        if spec is not None:
            self._chart_counter += 1
            n = self._chart_counter
            self._chart_files.append((f"ppt/charts/chart{n}.xml", self._build_chart_part(spec)))

            rel_id = f"rIdChart{n}"
            rels.append(
                {
                    "id": rel_id,
                    "type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
                    "target": f"../charts/chart{n}.xml",
                }
            )
            return self._build_chart_frame(element, shape_id, rel_id)

        # Fallback 1: a pre-rendered image (reachable on the native path).
        pre_render = self._chart_pre_render_src(element)
        if pre_render is not None:
            image_element = dict(element)
            image_element["src"] = pre_render
            image_element["fit"] = _get(element, "fit", "contain")
            return self._build_image_shape(image_element, shape_id, slide_number, rels)

        # Fallback 2: a titled placeholder box.
        title = ""
        if is_plain_object(option):
            title = php_string(_get(_dict(_get(option, "title")), "text", ""))
        label = title if title != "" else "chart"

        return self._build_chart_placeholder(label, element, shape_id)

    def _chart_pre_render_src(self, element: dict[str, Any]) -> str | None:
        for key in ("image", "src"):
            value = element.get(key)
            if isinstance(value, str) and value.startswith("data:"):
                return value
        return None

    def _build_chart_frame(self, element: dict[str, Any], shape_id: int, rel_id: str) -> str:
        xfrm = self._xfrm_from_fractions(element)
        element_id = _get(element, "id", f"chart-{shape_id}")

        return (
            "<p:graphicFrame>"
            "<p:nvGraphicFramePr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}"/>'
            "<p:cNvGraphicFramePr/>"
            "<p:nvPr/>"
            "</p:nvGraphicFramePr>"
            f"<p:xfrm>{_inner_xfrm(xfrm)}</p:xfrm>"
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'<a:graphicData uri="{NS_CHART}">'
            f'<c:chart xmlns:c="{NS_CHART}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rel_id}"/>'
            "</a:graphicData>"
            "</a:graphic>"
            "</p:graphicFrame>"
        )

    def _build_chart_part(self, spec: ChartSpec) -> str:
        """A complete ``ppt/charts/chartN.xml``.

        Uses literal caches (``<c:strLit>`` / ``<c:numLit>``) so the part
        needs no embedded workbook — which is what keeps the archive to the
        part list at the top of this file.
        """
        kind = spec["kind"]
        if kind == "line":
            plot = self._build_line_chart_xml(spec)
        elif kind == "pie":
            plot = self._build_pie_chart_xml(spec)
        elif kind == "scatter":
            plot = self._build_scatter_chart_xml(spec)
        else:
            plot = self._build_bar_chart_xml(spec)

        if spec["title"] != "":
            title = (
                "<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>"
                + Xml.text(spec["title"])
                + '</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>'
                '<c:autoTitleDeleted val="0"/>'
            )
        else:
            title = '<c:autoTitleDeleted val="1"/>'

        return (
            Xml.declaration()
            + f'<c:chartSpace xmlns:c="{NS_CHART}" '
            + 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            + "<c:chart>"
            + title
            + "<c:plotArea>"
            + "<c:layout/>"
            + plot
            + "</c:plotArea>"
            + '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>'
            + '<c:plotVisOnly val="1"/>'
            + '<c:dispBlanksAs val="gap"/>'
            + "</c:chart>"
            + "</c:chartSpace>"
        )

    def _build_bar_chart_xml(self, spec: ChartSpec) -> str:
        sers = ""
        for idx, series in enumerate(spec["series"]):
            sers += (
                "<c:ser>"
                f'<c:idx val="{idx}"/>'
                f'<c:order val="{idx}"/>'
                + self._chart_series_name(series, idx)
                + self._chart_series_fill(idx)
                + self._chart_cat_ref(spec["categories"], series["values"])
                + self._chart_val_ref(series["values"])
                + "</c:ser>"
            )

        return (
            "<c:barChart>"
            '<c:barDir val="col"/>'
            '<c:grouping val="clustered"/>'
            '<c:varyColors val="0"/>'
            f"{sers}"
            '<c:axId val="111111111"/>'
            '<c:axId val="222222222"/>'
            "</c:barChart>" + self._build_cat_val_axes()
        )

    def _build_line_chart_xml(self, spec: ChartSpec) -> str:
        is_area = any(series["area"] for series in spec["series"])

        sers = ""
        for idx, series in enumerate(spec["series"]):
            smooth = '<c:smooth val="1"/>' if (not is_area and series["smooth"]) else ""
            sers += (
                "<c:ser>"
                f'<c:idx val="{idx}"/>'
                f'<c:order val="{idx}"/>'
                + self._chart_series_name(series, idx)
                + self._chart_series_line(idx)
                + self._chart_cat_ref(spec["categories"], series["values"])
                + self._chart_val_ref(series["values"])
                + smooth
                + "</c:ser>"
            )

        if is_area:
            return (
                "<c:areaChart>"
                '<c:grouping val="standard"/>'
                '<c:varyColors val="0"/>'
                f"{sers}"
                '<c:axId val="111111111"/>'
                '<c:axId val="222222222"/>'
                "</c:areaChart>" + self._build_cat_val_axes()
            )

        return (
            "<c:lineChart>"
            '<c:grouping val="standard"/>'
            '<c:varyColors val="0"/>'
            f"{sers}"
            '<c:marker val="1"/>'
            '<c:axId val="111111111"/>'
            '<c:axId val="222222222"/>'
            "</c:lineChart>" + self._build_cat_val_axes()
        )

    def _build_pie_chart_xml(self, spec: ChartSpec) -> str:
        series: Any = spec["series"][0] if spec["series"] else {"values": [], "name": ""}
        values = series.get("values") if isinstance(series.get("values"), list) else []
        categories = spec["categories"]

        d_pts = "".join(
            "<c:dPt>"
            f'<c:idx val="{idx}"/>'
            '<c:bubble3D val="0"/>'
            f'<c:spPr><a:solidFill><a:srgbClr val="{self._chart_color(idx)}"/></a:solidFill></c:spPr>'
            "</c:dPt>"
            for idx in range(len(values))
        )

        return (
            "<c:pieChart>"
            '<c:varyColors val="1"/>'
            "<c:ser>"
            '<c:idx val="0"/>'
            '<c:order val="0"/>'
            + self._chart_series_name(series, 0)
            + d_pts
            + self._chart_cat_ref(categories, values)
            + self._chart_val_ref(values)
            + "</c:ser>"
            '<c:firstSliceAng val="0"/>'
            "</c:pieChart>"
        )

    def _build_scatter_chart_xml(self, spec: ChartSpec) -> str:
        sers = ""
        for idx, series in enumerate(spec["series"]):
            points = series["points"] if isinstance(series["points"], list) else []
            xs = [php_float(_get(point, "x", 0)) for point in points]
            ys = [php_float(_get(point, "y", 0)) for point in points]
            sers += (
                "<c:ser>"
                f'<c:idx val="{idx}"/>'
                f'<c:order val="{idx}"/>'
                + self._chart_series_name(series, idx)
                + '<c:spPr><a:ln w="19050"><a:noFill/></a:ln></c:spPr>'
                + f'<c:marker><c:symbol val="circle"/><c:size val="6"/><c:spPr><a:solidFill><a:srgbClr val="{self._chart_color(idx)}"/></a:solidFill></c:spPr></c:marker>'
                + f"<c:xVal>{self._num_lit(xs)}</c:xVal>"
                + f"<c:yVal>{self._num_lit(ys)}</c:yVal>"
                + "</c:ser>"
            )

        return (
            "<c:scatterChart>"
            '<c:scatterStyle val="lineMarker"/>'
            '<c:varyColors val="0"/>'
            f"{sers}"
            '<c:axId val="111111111"/>'
            '<c:axId val="222222222"/>'
            "</c:scatterChart>"
            '<c:valAx><c:axId val="111111111"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/><c:crossAx val="222222222"/></c:valAx>'
            '<c:valAx><c:axId val="222222222"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="l"/><c:crossAx val="111111111"/></c:valAx>'
        )

    def _build_cat_val_axes(self) -> str:
        return (
            "<c:catAx>"
            '<c:axId val="111111111"/>'
            '<c:scaling><c:orientation val="minMax"/></c:scaling>'
            '<c:delete val="0"/>'
            '<c:axPos val="b"/>'
            '<c:crossAx val="222222222"/>'
            "</c:catAx>"
            "<c:valAx>"
            '<c:axId val="222222222"/>'
            '<c:scaling><c:orientation val="minMax"/></c:scaling>'
            '<c:delete val="0"/>'
            '<c:axPos val="l"/>'
            '<c:crossAx val="111111111"/>'
            "</c:valAx>"
        )

    def _chart_series_name(self, series: Any, idx: int) -> str:
        raw = series.get("name") if isinstance(series, dict) else None
        name = raw if isinstance(raw, str) and raw != "" else f"Series {idx + 1}"

        return (
            f'<c:tx><c:strRef><c:f>Sheet1!$A${idx + 1}</c:f><c:strCache>'
            f'<c:ptCount val="1"/><c:pt idx="0"><c:v>{Xml.text(name)}</c:v></c:pt>'
            "</c:strCache></c:strRef></c:tx>"
        )

    def _chart_series_fill(self, idx: int) -> str:
        return f'<c:spPr><a:solidFill><a:srgbClr val="{self._chart_color(idx)}"/></a:solidFill></c:spPr>'

    def _chart_series_line(self, idx: int) -> str:
        return (
            f'<c:spPr><a:ln w="28575"><a:solidFill><a:srgbClr val="{self._chart_color(idx)}"/>'
            "</a:solidFill></a:ln></c:spPr>"
        )

    def _chart_cat_ref(self, categories_input: list[str], values: list[float]) -> str:
        categories = categories_input
        if not categories:
            categories = [str(i + 1) for i in range(len(values))]

        pts = "".join(
            f'<c:pt idx="{i}"><c:v>{Xml.text(php_string(label))}</c:v></c:pt>'
            for i, label in enumerate(categories)
        )

        return f'<c:cat><c:strLit><c:ptCount val="{len(categories)}"/>{pts}</c:strLit></c:cat>'

    def _chart_val_ref(self, values: list[float]) -> str:
        return f"<c:val>{self._num_lit(values)}</c:val>"

    def _num_lit(self, values: list[float]) -> str:
        pts = "".join(
            f'<c:pt idx="{i}"><c:v>{self._num_str(php_float(value))}</c:v></c:pt>'
            for i, value in enumerate(values)
        )
        return (
            f'<c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="{len(values)}"/>'
            f"{pts}</c:numLit>"
        )

    def _num_str(self, value: float) -> str:
        """A float with no trailing ``.0`` and no locale separators.

        PHP uses ``sprintf('%.6F')`` here, and Python's ``%.6f`` is
        byte-identical to it: no IEEE-754 double is EXACTLY a tie at six
        decimal places (that would need 5·10⁻⁷ to be a dyadic rational, and it
        is not), so the two rounding modes cannot disagree. This is the one
        place in the package where the builtin formatter is safe, and the
        reason is written down so nobody has to re-derive it.
        """
        import math

        if value == math.floor(value) and abs(value) < 1.0e15:
            return str(int(value))
        return ("%.6f" % value).rstrip("0").rstrip(".")

    def _chart_color(self, idx: int) -> str:
        """The theme accent for series 0, the fixed palette after that."""
        if idx == 0:
            return self._theme_accent
        return CHART_PALETTE[idx % len(CHART_PALETTE)]

    def _build_chart_placeholder(self, label: str, element: dict[str, Any], shape_id: int) -> str:
        xfrm = self._xfrm_from_fractions(element)
        element_id = _get(element, "id", f"chart-{shape_id}")

        return (
            "<p:sp>"
            "<p:nvSpPr>"
            f'<p:cNvPr id="{shape_id}" name="{Xml.attr(php_string(element_id))}"/>'
            "<p:cNvSpPr/>"
            "<p:nvPr/>"
            "</p:nvSpPr>"
            "<p:spPr>"
            f"{xfrm}"
            '<a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>'
            '<a:solidFill><a:srgbClr val="F1F5F9"/></a:solidFill>'
            '<a:ln w="12700"><a:solidFill><a:srgbClr val="CBD5E1"/></a:solidFill></a:ln>'
            "</p:spPr>"
            "<p:txBody>"
            '<a:bodyPr wrap="square" anchor="ctr" rtlCol="0"/>'
            "<a:lstStyle/>"
            '<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="1600" b="1">'
            '<a:solidFill><a:srgbClr val="64748B"/></a:solidFill></a:rPr>'
            f"<a:t>{Xml.text(label)}</a:t></a:r></a:p>"
            "</p:txBody>"
            "</p:sp>"
        )

    def _build_placeholder(self, label: str, element: dict[str, Any], shape_id: int) -> str:
        return self._build_text_shape(
            {
                "id": _get(element, "id", f"placeholder-{shape_id}"),
                "type": "text",
                "x": _get(element, "x", 0.1),
                "y": _get(element, "y", 0.4),
                "w": _get(element, "w", 0.8),
                "h": _get(element, "h", 0.2),
                "content": label,
                "format": "plain",
                "style": {"fontSize": 20, "align": "center", "color": "#64748B"},
            },
            shape_id,
        )

    # ── Text body / paragraphs / runs ─────────────────────────────────────

    def _build_text_body(self, content: str, style: dict[str, Any], fmt: str) -> str:
        font_pt = php_float(_get(style, "fontSize", 24))
        # fancy-slides designs against a 1920px width; PPTX renders ~720px at
        # 10 inches, so halving lands in PPTX-sensible territory.
        pt = max(8.0, font_pt / 2)
        sz = Emu.hundredths_of_point(pt)
        base_bold = self._weight_to_bold(style.get("weight"))
        base_italic = ' i="1"' if php_truthy(style.get("italic")) else ""
        base_underline = ' u="sng"' if php_truthy(style.get("underline")) else ""
        align = self._align_to_algn(_get(style, "align", "left"))
        color_hex = Color.parse(php_string(_get(style, "color", "#0F172A")), "0F172A")[0]
        font_family_value = style.get("fontFamily")
        font_family = (
            f'<a:latin typeface="{Xml.attr(php_string(font_family_value))}"/>'
            if font_family_value is not None
            else ""
        )
        vertical_align = _get(style, "verticalAlign", "top")
        anchor = {"middle": "ctr", "bottom": "b"}.get(
            vertical_align if isinstance(vertical_align, str) else "", "t"
        )

        render_runs = fmt == "markdown"

        paragraphs = ""
        for line in content.split("\n"):
            # Heading first — it disqualifies a bullet on the same line.
            heading_level = 0
            is_bullet = False
            body = line
            if render_runs:
                heading_level, body = MarkdownInline.heading_prefix(line)
                if heading_level == 0:
                    is_bullet, body = MarkdownInline.bullet_prefix(line)

            paragraph_sz = sz
            paragraph_bold = base_bold
            if heading_level > 0:
                multiplier = {1: 1.8, 2: 1.45, 3: 1.2}.get(heading_level, 1.0)
                paragraph_sz = Emu.hundredths_of_point(pt * multiplier)
                paragraph_bold = ' b="1"'

            p_pr = f'<a:pPr algn="{align}"'
            if is_bullet:
                p_pr += ' indent="-228600" marL="228600"><a:buFont typeface="Arial"/><a:buChar char="•"/>'
            else:
                p_pr += "><a:buNone/>"
            p_pr += "</a:pPr>"

            runs = ""
            if render_runs:
                for token in MarkdownInline.tokenize(body):
                    runs += self._build_run(
                        token["text"],
                        paragraph_sz,
                        paragraph_bold,
                        base_italic,
                        base_underline,
                        color_hex,
                        font_family,
                        token["b"],
                        token["i"],
                        token["code"],
                    )
            else:
                runs = self._build_run(
                    body,
                    paragraph_sz,
                    paragraph_bold,
                    base_italic,
                    base_underline,
                    color_hex,
                    font_family,
                    False,
                    False,
                    False,
                )

            paragraphs += f"<a:p>{p_pr}{runs}</a:p>"

        return (
            "<p:txBody>"
            f'<a:bodyPr wrap="square" anchor="{anchor}" rtlCol="0"/>'
            "<a:lstStyle/>"
            f"{paragraphs}"
            "</p:txBody>"
        )

    def _build_run(
        self,
        text: str,
        sz: int,
        base_bold: str,
        base_italic: str,
        base_underline: str,
        color_hex: str,
        font_family: str,
        bold: bool,
        italic: bool,
        code: bool,
    ) -> str:
        b = ' b="1"' if bold else base_bold
        i = (' i="1"' if italic else "") or base_italic
        u = base_underline
        run_color = color_hex
        family = font_family

        if code:
            # Inline code stays a run — it just switches font and tint, so it
            # reads as code on any theme.
            run_color = "8B5CF6"
            family = '<a:latin typeface="Consolas"/>'

        r_pr = (
            f'<a:rPr lang="en-US" sz="{sz}"{b}{i}{u}>'
            f'<a:solidFill><a:srgbClr val="{run_color}"/></a:solidFill>{family}</a:rPr>'
        )

        return f"<a:r>{r_pr}<a:t>{Xml.text(text)}</a:t></a:r>"

    def _weight_to_bold(self, weight: Any) -> str:
        if is_numeric(weight) and php_int(weight) >= 600:
            return ' b="1"'
        if weight == "bold" or weight == "semibold":
            return ' b="1"'
        return ""

    def _align_to_algn(self, align: Any) -> str:
        return {"center": "ctr", "right": "r", "justify": "just"}.get(
            align if isinstance(align, str) else "", "l"
        )

    # ── Geometry ──────────────────────────────────────────────────────────

    def _xfrm_from_fractions(self, element: dict[str, Any]) -> str:
        x = Emu.from_frac_x(php_float(_get(element, "x", 0)))
        y = Emu.from_frac_y(php_float(_get(element, "y", 0)))
        cx = Emu.from_frac_x(php_float(_get(element, "w", 0)))
        cy = Emu.from_frac_y(php_float(_get(element, "h", 0)))
        rotation = element.get("rotation")
        rot = int(php_round(php_float(rotation) * 60000)) if rotation is not None else 0
        rot_attr = f' rot="{rot}"' if rot != 0 else ""

        return f'<a:xfrm{rot_attr}><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'

    # ── Media staging ─────────────────────────────────────────────────────

    def _stage_media(self, src: str, _slide_number: int) -> dict[str, Any] | None:
        data = self._load_image_bytes(src)
        if data is None:
            return None
        self._media_counter += 1
        i = self._media_counter
        ext = self._extension_for_mime(data["mime"]) or "png"
        self._media_files.append((f"ppt/media/image{i}.{ext}", data["bytes"]))

        # RULING PENDING: this collides, and the collision is reproduced on
        # purpose. The rel id is the GLOBAL media counter, while a slide's own
        # rels start at rId1 = layout and rId2 = notesSlide — so ONE image on
        # ONE slide already emits two `<Relationship Id="rId1">` entries, and a
        # slide with notes plus the deck's second image emits two `rId2`s.
        # Relationship ids must be unique within a part, so the package is
        # malformed, and every pptx with an image that any of the three engines
        # has written carries it.
        #
        # It is NOT fixed here. Fixing one engine alone would break part-level
        # parity, which is the only cross-runtime guarantee this trio has; the
        # ruling in `.ai/plans/polyglot/parity/documents.md` §1.4 sequences it as
        # one coordinated release across every engine (step U5). The
        # `imageRelIds` fixture pins the current bytes so that change has to
        # land everywhere at once.
        rel_id = f"rId{i}"

        return {"relId": rel_id, "target": f"../media/image{i}.{ext}", "bytes": data["bytes"]}

    def _load_image_bytes(self, src: str) -> dict[str, Any] | None:
        # data: URI — decode inline.
        m = _DATA_URI.match(src)
        if m:
            mime = m.group(1)
            payload = m.group(2)
            if ";base64," in src:
                try:
                    payload_bytes = base64.b64decode(payload, validate=True)
                except Exception:
                    return None
            else:
                # PHP `urldecode` on raw bytes: percent-decode to BYTES, never
                # a text round-trip. The Node port re-encodes as UTF-8 here and
                # corrupts binary payloads; this follows PHP.
                payload_bytes = urllib.parse.unquote_to_bytes(payload.replace("+", " "))
            return {"bytes": payload_bytes, "mime": mime}

        # file:// URL — read from disk.
        if src.startswith("file://"):
            path = src[7:]
            if not os.path.isfile(path):
                return None
            try:
                with open(path, "rb") as handle:
                    return {"bytes": handle.read(), "mime": self._guess_mime_from_path(path)}
            except OSError:
                return None

        # A local path with no scheme.
        if "://" not in src and os.path.isfile(src):
            try:
                with open(src, "rb") as handle:
                    return {"bytes": handle.read(), "mime": self._guess_mime_from_path(src)}
            except OSError:
                return None

        # http(s) — only with explicit opt-in. Fetching a URL named in a
        # document is a security boundary (SSRF), so the default is a
        # placeholder rather than a request.
        if self.allow_http_images and _HTTP_URL.match(src):
            try:
                with urllib.request.urlopen(src) as response:  # noqa: S310 - opt-in by contract
                    payload_bytes = response.read()
            except Exception:
                return None
            if not payload_bytes:
                return None
            return {"bytes": payload_bytes, "mime": self._guess_mime_from_bytes(payload_bytes, src)}

        return None

    def _guess_mime_from_bytes(self, payload: bytes, src: str) -> str:
        """Sniff the header first, fall back to the URL's extension."""
        sniffed = image_mime(payload)
        if sniffed is not None:
            return sniffed
        path = urllib.parse.urlparse(src).path
        return self._guess_mime_from_path(path) if path else "image/png"

    def _guess_mime_from_path(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        return {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "svg": "image/svg+xml",
            "webp": "image/webp",
        }.get(ext, "application/octet-stream")

    def _extension_for_mime(self, mime: str) -> str | None:
        return {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/gif": "gif",
            "image/svg+xml": "svg",
            "image/webp": "webp",
        }.get(mime)

    # ── Slide rels ────────────────────────────────────────────────────────

    def _build_slide_rels(self, slide_number: int, has_notes: bool, layout_number: int = 1) -> str:
        rels = (
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
            f'Target="../slideLayouts/slideLayout{layout_number}.xml"/>'
        )
        next_rel_num = 2

        if has_notes:
            rels += (
                f'<Relationship Id="rId{next_rel_num}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" '
                f'Target="../notesSlides/notesSlide{slide_number}.xml"/>'
            )
            next_rel_num += 1

        for rel in self._pending_slide_rels.get(slide_number, []):
            mode = ' TargetMode="External"' if rel.get("mode") == "External" else ""
            rels += (
                f'<Relationship Id="{Xml.attr(rel["id"])}" Type="{Xml.attr(rel["type"])}" '
                f'Target="{Xml.attr(rel["target"])}"{mode}/>'
            )

        return (
            Xml.declaration()
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels
            + "</Relationships>"
        )

    # ── Notes slides ──────────────────────────────────────────────────────

    def _build_notes_slide_xml(self, slide: dict[str, Any], _slide_number: int) -> str:
        notes = php_string(_get(slide, "notes", ""))
        paragraphs = "".join(
            f'<a:p><a:r><a:rPr lang="en-US" sz="1200"/><a:t>{Xml.text(line)}</a:t></a:r></a:p>'
            for line in notes.split("\n")
        )

        return (
            Xml.declaration()
            + '<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            + 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            + "<p:cSld>"
            + "<p:spTree>"
            + '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            + '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + "<p:sp>"
            + "<p:nvSpPr>"
            + '<p:cNvPr id="2" name="Notes Placeholder"/>'
            + '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            + '<p:nvPr><p:ph type="body"/></p:nvPr>'
            + "</p:nvSpPr>"
            + '<p:spPr><a:xfrm><a:off x="685800" y="1700213"/><a:ext cx="5772150" cy="3679371"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            + "<p:txBody><a:bodyPr/><a:lstStyle/>"
            + paragraphs
            + "</p:txBody>"
            + "</p:sp>"
            + "</p:spTree>"
            + "</p:cSld>"
            + "</p:notes>"
        )

    def _build_notes_slide_rels(self, slide_number: int) -> str:
        return (
            Xml.declaration()
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="../slides/slide{slide_number}.xml"/>'
            + "</Relationships>"
        )


# ── Module helpers ────────────────────────────────────────────────────────


def _str_or(value: Any, default: str) -> str:
    """A string, or the default. PHP's ``?? '#fff'`` plus its string typing."""
    if value is None:
        return default
    return value if isinstance(value, str) else default


def _z_key(element: Any) -> float:
    """The z-order sort key. Absent or non-numeric `z` sorts as -1."""
    if not is_plain_object(element):
        return -1.0
    z = element.get("z")
    return php_float(z) if is_numeric(z) else -1.0


def _as_sequence(value: Any) -> list[Any]:
    """PHP ``is_array`` covers lists AND maps; JSON gives Python two types."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _zip(files: list[tuple[str, bytes]]) -> bytes:
    """Pack the parts into a deterministic zip container.

    Fixed 1980-01-01 DOS date and STORE, matching the Node port's vendored
    writer — which the polyglot plan names as the canonical container profile.
    The container is never compared across engines (PHP writes DEFLATE with
    real mtimes through ``ZipArchive`` and can never match), but it MUST be
    stable within this engine or no document can be a golden fixture.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in files:
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            info.create_system = 0
            archive.writestr(info, payload)
    return buffer.getvalue()


def image_size(payload: bytes) -> tuple[int, int] | None:
    """Intrinsic pixel dimensions from a PNG / GIF / JPEG / WebP / BMP header.

    Stands in for PHP's ``getimagesizefromstring``, which the writer uses for
    ``fit: cover`` and ``fit: contain``. Hand-rolled on purpose — see the
    package's AGENTS.md on why an imaging dependency is not an option here.

    Covers more than the Node port (PNG/GIF/JPEG only): PHP also reads WebP and
    BMP, so a WebP with ``fit: cover`` gets a real centre-crop in PHP and a
    stretched fill in Node. Following PHP is the ruling for this trio.
    """
    n = len(payload)

    # PNG: IHDR width/height at offset 16, big-endian.
    if n >= 24 and payload[0:4] == b"\x89PNG":
        return (
            int.from_bytes(payload[16:20], "big"),
            int.from_bytes(payload[20:24], "big"),
        )

    # GIF: logical screen descriptor at offset 6, little-endian.
    if n >= 10 and payload[0:3] == b"GIF":
        return (
            int.from_bytes(payload[6:8], "little"),
            int.from_bytes(payload[8:10], "little"),
        )

    # JPEG: walk the marker chain to a start-of-frame.
    if n >= 4 and payload[0] == 0xFF and payload[1] == 0xD8:
        i = 2
        while i + 9 < n:
            if payload[i] != 0xFF:
                i += 1
                continue
            marker = payload[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height = int.from_bytes(payload[i + 5 : i + 7], "big")
                width = int.from_bytes(payload[i + 7 : i + 9], "big")
                return (width, height)
            length = int.from_bytes(payload[i + 2 : i + 4], "big")
            i += 2 + length
        return None

    # WebP: three container flavours, each stating the size differently.
    if n >= 30 and payload[0:4] == b"RIFF" and payload[8:12] == b"WEBP":
        fourcc = payload[12:16]
        if fourcc == b"VP8 " and n >= 30:
            return (
                int.from_bytes(payload[26:28], "little") & 0x3FFF,
                int.from_bytes(payload[28:30], "little") & 0x3FFF,
            )
        if fourcc == b"VP8L" and n >= 25:
            bits = int.from_bytes(payload[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if fourcc == b"VP8X" and n >= 30:
            return (
                int.from_bytes(payload[24:27], "little") + 1,
                int.from_bytes(payload[27:30], "little") + 1,
            )
        return None

    # BMP: BITMAPINFOHEADER, signed 32-bit little-endian.
    if n >= 26 and payload[0:2] == b"BM":
        return (
            int.from_bytes(payload[18:22], "little", signed=True),
            abs(int.from_bytes(payload[22:26], "little", signed=True)),
        )

    return None


def image_mime(payload: bytes) -> str | None:
    """The MIME type :func:`image_size` would recognise, or None."""
    if payload[0:4] == b"\x89PNG":
        return "image/png"
    if payload[0:3] == b"GIF":
        return "image/gif"
    if payload[0:2] == b"\xff\xd8":
        return "image/jpeg"
    if payload[0:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload[0:2] == b"BM":
        return "image/bmp"
    return None

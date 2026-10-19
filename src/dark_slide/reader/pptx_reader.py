"""Best-effort PPTX → Deck reader. A port of PHP ``DarkSlide\\Reader\\PptxReader``.

Deliberately lossy and deliberately quiet. Text, images, shapes and tables come
back with their geometry; styling fidelity, masters, transitions and animations
do not. Anything it cannot model is **skipped, never thrown** — a deck that
came from PowerPoint will always contain constructs no reader models, and
failing the whole import over one of them is the wrong trade for a tool an
agent drives.

Reading is the one half of this package where an off-the-shelf parser is the
right call: nothing is serialised, so no byte contract exists to protect. It
uses ``xml.etree.ElementTree`` and matches on LOCAL names, ignoring namespace
binding entirely — which is what the PHP XPath and the Node tree-walker both
do in effect.

**DOCTYPE is rejected before parsing.** A ``.pptx`` never legitimately carries
one, and a document type declaration is the entry point for entity-expansion
attacks. The input here is a file someone uploaded.

**read() is a pure function of its bytes.** The same package read twice — in
the same second or a year apart, here or on another machine — comes back as an
identical structure, down to every generated id. That is a contract rather than
a property of the current code: consumers store reads and diff them, and one
clock- or RNG-derived field turns a diff of unchanged content into a whole-deck
replace. Nothing here may put the clock, a random number or the environment
into a value it returns.

**That diff is YOURS, not this package's.** ``Differ``, ``Reducer`` and the
``DeckOp`` vocabulary exist only in the PHP package — there is no diff surface
here, and nothing in this repo guards the property described above on your
behalf. This docstring used to describe the failure without saying where the
differ lived, which reads as a promise that something upstream handles it. It
does not. What this package owes you is a pure ``read()``; comparing two reads
is your code, and the guard worth copying is "does the diff mention the part
that did not change?" — threshold-free, because a whole-deck replace satisfies
every bound (it is one operation, and smaller than the ``.pptx``).

**The id is a function of the CONTENT, never of the package bytes.** That
distinction took three attempts to state correctly, so it is worth being blunt
about: a digest of the bytes identifies a SERIALISATION, and two serialisations
of one deck are not byte-equal. 0.3.1 hashed the whole package, which followed
the writer's clock. 0.3.2 excluded the clock-bearing part, which removed ONE
source of byte variance and left the rest — a deck carrying a shape or a code
block still re-serialises to different ``ppt/slides/slideN.xml`` bytes, so the id
still moved while the structure sat perfectly still. ``_content_digest`` hashes
what ``read()`` RETURNS.

The consequence to hold on to: **any two byte layouts that read to the same
structure get the same id.** It does NOT follow that a file from another producer
and a DarkSlide-authored file of "the same deck" agree — that holds only as far
as ``read()`` normalises them to the same structure, which is not promised here
and is not what this guarantees.
"""

from __future__ import annotations

import base64
import io
import os
import math
import re
import struct
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from html import unescape
from typing import Any

from ..helpers import emu as Emu

__all__ = ["PptxReader"]

_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)

def _canonicalize(value: Any, feed: Any) -> None:
    """Feed one value to the digest in a form all three engines agree on.

    This is a CANONICAL ENCODING and its rules are the contract, not an
    implementation detail — the PHP and Node engines implement the same one and
    the reader-parity suite compares the resulting id, so a divergence here is a
    divergence in the id. Spelled out::

        None            ~
        True / False    T / F
        number          # then the eight bytes of the IEEE-754 binary64, big endian
        str             s, the UTF-8 BYTE length in decimal, :, then the bytes
        empty [] / {}   e
        list            [ then each item, then ]
        dict            { then each key then its value, keys ascending, then }

    Three of those choices are load-bearing:

    **Numbers go in as raw IEEE bits, never as text.** The three languages
    disagree about the TYPE of a number — PHP's ``int / int`` is an int when it
    divides exactly, Python's ``/`` is always a float, JS has only doubles — and
    about how a float RENDERS: PHP's depends on the ``serialize_precision`` ini
    setting, which a consumer can change underneath us. Bit patterns have no such
    freedom. Two finite doubles that compare equal have identical bits, and both
    parity suites already assert the engines read numerically equal values, so
    agreement here follows from a property that is already tested. ``-0.0`` is
    the one exception to that and is normalised; non-finite values cannot occur
    in a deck and are mapped to a marker rather than trusted.

    **Strings are length-prefixed**, so there is no escaping convention for three
    languages to agree on.

    **An empty list and an empty dict collapse to ONE marker.** PHP cannot tell
    them apart — ``[]`` is both — so a table row with no cells is ``[]`` there
    and ``{}`` here. Both parity suites already normalise the two together, which
    is the estate deciding that distinction is not meaningful; a digest depending
    on it would depend on something already ruled meaningless.

    Keys are sorted rather than taken in insertion order. Python's ``sorted``
    is code-point order, which for UTF-8 is PHP's byte order, and matches JS's
    UTF-16 order for everything below U+10000. Every key a read deck contains is
    machine-generated ASCII, which the purity suite checks rather than assumes.

    ``bool`` is tested BEFORE ``int``: in Python ``isinstance(True, int)`` is
    true, so a bool would otherwise be digested as the number 1.
    """
    if value is None:
        feed(b"~")
        return
    if value is True:
        feed(b"T")
        return
    if value is False:
        feed(b"F")
        return
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            feed(b"?")
            return
        if number == 0.0:
            # -0.0 and 0.0 are equal but not bit-equal, and either can be
            # reached. Collapse to +0.0 so the engines cannot disagree.
            number = 0.0
        feed(b"#")
        feed(struct.pack(">d", number))
        return
    if isinstance(value, str):
        raw = value.encode("utf-8")
        feed(b"s" + str(len(raw)).encode("ascii") + b":")
        feed(raw)
        return
    if isinstance(value, (list, tuple)):
        if not value:
            feed(b"e")
            return
        feed(b"[")
        for item in value:
            _canonicalize(item, feed)
        feed(b"]")
        return
    if isinstance(value, dict):
        if not value:
            feed(b"e")
            return
        feed(b"{")
        for key in sorted(value.keys(), key=str):
            _canonicalize(str(key), feed)
            _canonicalize(value[key], feed)
        feed(b"}")
        return

    # Unreachable for a deck, which is lists, dicts and scalars all the way down.
    feed(b"?")


class _Node:
    """A namespace-stripped XML element.

    ``tails`` holds each child's trailing text, which ElementTree hangs off the
    CHILD but which belongs to this node's content — the difference matters
    only for :func:`_deep_text`, and only for mixed content.
    """

    __slots__ = ("name", "attrs", "text", "children", "tails")

    def __init__(self, name: str, attrs: dict[str, str], text: str) -> None:
        self.name = name
        self.attrs = attrs
        self.text = text
        self.children: list[_Node] = []
        self.tails: list[str] = []


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _parse_xml(xml: str) -> _Node | None:
    """Parse to a namespace-stripped tree, or ``None`` if it will not parse.

    The DOCTYPE guard runs on the raw text, before any parser sees it.
    """
    if _DOCTYPE.search(xml.encode("utf-8", "replace")):
        return None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    return _convert(root)


def _convert(element: ElementTree.Element) -> _Node:
    node = _Node(
        _local(element.tag),
        {_local(k): v for k, v in element.attrib.items()},
        element.text or "",
    )
    for child in element:
        node.children.append(_convert(child))
        node.tails.append(child.tail or "")
    return node


def _el(node: _Node | None, name: str) -> _Node | None:
    """The first DIRECT child with this local name."""
    if node is None:
        return None
    for child in node.children:
        if child.name == name:
            return child
    return None


def _at(node: _Node | None, name: str) -> str | None:
    """An attribute by local name."""
    if node is None:
        return None
    return node.attrs.get(name)


def _descendant(node: _Node | None, name: str) -> _Node | None:
    """The first descendant (self excluded) with this local name, depth-first."""
    if node is None:
        return None
    for child in node.children:
        if child.name == name:
            return child
        found = _descendant(child, name)
        if found is not None:
            return found
    return None


def _descendants(node: _Node | None, name: str) -> list[_Node]:
    """Every descendant (self excluded) with this local name, in document order."""
    out: list[_Node] = []
    if node is None:
        return out
    for child in node.children:
        if child.name == name:
            out.append(child)
        out.extend(_descendants(child, name))
    return out


def _deep_text(node: _Node) -> str:
    """The node's text plus every descendant's, concatenated."""
    parts = [node.text]
    for i, child in enumerate(node.children):
        parts.append(_deep_text(child))
        if i < len(node.tails):
            parts.append(node.tails[i])
    return "".join(parts)


def _to_int(value: str | None) -> int:
    """PHP's ``(int)`` cast of an attribute string: junk becomes 0."""
    if value is None:
        return 0
    m = re.match(r"^\s*[+-]?\d+", value)
    return int(m.group(0)) if m else 0


def _basename(path: str) -> str:
    return path.split("/")[-1]


def _dirname(path: str) -> str:
    idx = path.rfind("/")
    return "." if idx < 0 else path[:idx]


def _extension(path: str) -> str:
    base = _basename(path)
    idx = base.rfind(".")
    return "" if idx < 0 else base[idx + 1 :].lower()


class PptxReader:
    """Read a ``.pptx`` back into the deck schema."""

    def __init__(self) -> None:
        self._current_slide_rels: dict[str, dict[str, str]] = {}
        #: The mono typeface this deck was written with, read back from the
        #: theme's ``<a:extLst>``. Empty when the package does not record one —
        #: anything not written by a current DarkSlide — in which case the name
        #: sniff below is the only signal available.
        self._mono_typeface = ""
        self._parts: dict[str, bytes] = {}
        #: The slide size from ``<p:sldSz>``, so geometry comes back as fractions
        #: of THIS slide. Every conversion used to assume 16:9 at 10in, which read
        #: a 4:3 deck's positions back wrong.
        self._slide_width_emu = Emu.DEFAULT_SLIDE_WIDTH
        self._slide_height_emu = Emu.DEFAULT_SLIDE_HEIGHT
        #: The 1-based number of the slide being parsed, and how many fallback
        #: ids have been minted for it. Together they replace a
        #: ``random.randint()`` fallback for elements whose ``<p:cNvPr>``
        #: carries no ``name``. Numbering PER SLIDE is deliberate: inserting one
        #: shape into slide 1 then shifts only slide 1's ids instead of
        #: renumbering every element after it, which would turn a one-element
        #: edit into a whole-deck diff — the same failure the clock id caused,
        #: reached by an edit rather than by time.
        self._slide_number = 0
        self._slide_fallback_ids = 0

    def read(self, data: bytes | bytearray | str | os.PathLike[str]) -> dict[str, Any]:
        """Read from bytes OR a filesystem path.

        PHP's ``read`` takes a path and the Node port's takes bytes — the two
        engines genuinely diverge here. Rather than pick a side and make the
        other's caller wrong, this accepts both.
        """
        if isinstance(data, (bytes, bytearray)):
            return self.from_bytes(bytes(data))
        path = os.fspath(data)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(path, "rb") as handle:
            return self.from_bytes(handle.read())

    def from_bytes(self, data: bytes) -> dict[str, Any]:
        # Everything this read returns is derived from these bytes, here or
        # below. The counters start over on every call because one reader
        # instance may be handed a second file.
        self._slide_number = 0
        self._slide_fallback_ids = 0

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self._parts = {name: archive.read(name) for name in archive.namelist()}
        except zipfile.BadZipFile as exc:
            raise ValueError("Could not open zip archive.") from exc
        deck = self._extract()
        # Stamped HERE rather than inside _extract() because _extract() has early
        # returns for a malformed package, and an id that some return paths skip
        # is worse than one that is wrong.
        deck["id"] = "imported-" + self._content_digest(deck)
        return deck

    def _content_digest(self, deck: dict[str, Any]) -> str:
        """The deck id: CRC-32 over a canonical encoding of the DECK.

        Eight lowercase hex digits. Not of the package — see the module note.

        ``id`` is removed first, because it is the value being computed. Nothing
        else is removed: every other field is either read out of the file or
        derived deterministically from it (``imported-slide-N``, and an
        element's positional fallback id), so all of it is content.
        """
        content = {key: value for key, value in deck.items() if key != "id"}

        crc = 0

        def feed(chunk: bytes) -> None:
            nonlocal crc
            crc = zlib.crc32(chunk, crc)

        _canonicalize(content, feed)

        return format(crc & 0xFFFFFFFF, "08x")

    # ── Extraction ────────────────────────────────────────────────────────

    def _read_mono_typeface(self) -> str:
        """The mono typeface recorded in ``theme1.xml``'s ``<a:extLst>``, or ``""``.

        Deliberately a regex rather than a parse: this runs before the deck is
        built, the element is one attribute deep, and a theme part that does not
        carry the extension is the common case rather than an error.
        """
        xml = self._get_part("ppt/theme/theme1.xml")
        if xml is None:
            return ""

        match = re.search(r'<ds:monoFont[^>]*typeface="([^"]*)"', xml)
        if match is None:
            return ""

        return unescape(match.group(1))

    def _get_part(self, name: str) -> str | None:
        payload = self._parts.get(name)
        return None if payload is None else payload.decode("utf-8", "replace")

    def _extract(self) -> dict[str, Any]:
        deck: dict[str, Any] = {
            # Filled in by from_bytes() once the deck is complete — the digest
            # is over the content, so it cannot exist before the content does.
            # Declared first so the returned key order is unchanged.
            "id": "",
            "title": self._read_core_title() or "Imported",
            "theme": {"name": "imported"},
            "slides": [],
        }

        self._mono_typeface = self._read_mono_typeface()
        deck["theme"].update(self._read_theme())
        self._read_slide_size()
        # 16:9 at 10in is the default and says nothing; any other shape is part
        # of the deck and comes back as its aspect ratio.
        if (
            self._slide_width_emu != Emu.DEFAULT_SLIDE_WIDTH
            or self._slide_height_emu != Emu.DEFAULT_SLIDE_HEIGHT
        ):
            # Always a float, as PHP returns it: a 2:1 slide reads back as 2.0.
            deck["theme"]["aspectRatio"] = self._slide_width_emu / self._slide_height_emu

        # Walk the presentation rel list in order — that, not the part names,
        # is what defines slide order.
        presentation_rels = self._get_part("ppt/_rels/presentation.xml.rels")
        if presentation_rels is None:
            return deck

        for i, slide_target in enumerate(self._extract_slide_targets(presentation_rels)):
            slide_xml = self._get_part("ppt/" + slide_target)
            if slide_xml is None:
                continue
            slide_rels = (
                self._get_part(
                    "ppt/" + _dirname(slide_target) + "/_rels/" + _basename(slide_target) + ".rels"
                )
                or ""
            )
            notes = self._read_notes_for(slide_rels)
            self._current_slide_rels = self._parse_slide_rels(slide_rels, slide_target)
            self._slide_number = i + 1
            self._slide_fallback_ids = 0

            deck["slides"].append(
                self._parse_slide(slide_xml, f"imported-slide-{i + 1}", notes)
            )

        # Only when the file embeds any, so every other read is unchanged.
        embedded_fonts = self._read_embedded_fonts()
        if embedded_fonts:
            deck["metadata"] = {"embeddedFonts": embedded_fonts}

        return deck

    def _read_slide_size(self) -> None:
        self._slide_width_emu = Emu.DEFAULT_SLIDE_WIDTH
        self._slide_height_emu = Emu.DEFAULT_SLIDE_HEIGHT

        xml = self._get_part("ppt/presentation.xml")
        tag = re.search(r"<p:sldSz\b[^>]*>", xml) if xml is not None else None
        if tag is None:
            return
        cx = re.search(r'\bcx="(\d+)"', tag.group(0))
        if cx is not None and int(cx.group(1)) > 0:
            self._slide_width_emu = int(cx.group(1))
        cy = re.search(r'\bcy="(\d+)"', tag.group(0))
        if cy is not None and int(cy.group(1)) > 0:
            self._slide_height_emu = int(cy.group(1))

    def _frac_x(self, emu: int) -> float:
        return Emu.to_frac_x(emu, self._slide_width_emu)

    def _frac_y(self, emu: int) -> float:
        return Emu.to_frac_y(emu, self._slide_height_emu)

    def _read_embedded_fonts(self) -> list[dict[str, Any]]:
        """The typefaces the file embeds and which of the four variants each
        carries. Names and variants only, never the font bytes: a reader's output
        is a deck, and a deck is agent-facing JSON."""
        xml = self._get_part("ppt/presentation.xml")
        listing = re.search(r"<p:embeddedFontLst>(.*?)</p:embeddedFontLst>", xml, re.S) if xml is not None else None
        if listing is None:
            return []

        fonts: list[dict[str, Any]] = []
        for entry in re.findall(r"<p:embeddedFont>(.*?)</p:embeddedFont>", listing.group(1), re.S):
            face = re.search(r'<p:font\b[^>]*\btypeface="([^"]*)"', entry)
            if face is None:
                continue
            fonts.append({
                "typeface": unescape(face.group(1)),
                "variants": re.findall(r"<p:(regular|bold|italic|boldItalic)\b", entry),
            })

        return fonts

    def _parse_slide_rels(self, rels_xml: str, slide_target_relative: str) -> dict[str, dict[str, str]]:
        """A slide's rels as ``{rId: {type, target}}`` with absolute targets."""
        if rels_xml == "":
            return {}
        root = _parse_xml(rels_xml)
        if root is None:
            return {}

        slide_dir_abs = "ppt/" + _dirname(slide_target_relative)
        rels: dict[str, dict[str, str]] = {}
        for r in _descendants(root, "Relationship"):
            rels[_at(r, "Id") or ""] = {
                "type": _at(r, "Type") or "",
                "target": self._resolve_rel_target(slide_dir_abs, _at(r, "Target") or ""),
            }
        return rels

    def _resolve_rel_target(self, base_dir: str, target: str) -> str:
        if target.startswith("/"):
            return target.lstrip("/")
        stack = base_dir.split("/")
        for segment in target.split("/"):
            if segment == "..":
                if stack:
                    stack.pop()
            elif segment not in (".", ""):
                stack.append(segment)
        return "/".join(stack)

    def _extract_slide_targets(self, rels_xml: str) -> list[str]:
        root = _parse_xml(rels_xml)
        if root is None:
            return []
        return [
            _at(r, "Target") or ""
            for r in _descendants(root, "Relationship")
            if (_at(r, "Type") or "").endswith("/slide")
        ]

    def _read_core_title(self) -> str | None:
        xml = self._get_part("docProps/core.xml")
        if xml is None:
            return None
        root = _parse_xml(xml)
        if root is None:
            return None
        title = _descendant(root, "title")
        return _deep_text(title) if title is not None else None

    def _read_notes_for(self, slide_rels_xml: str) -> str | None:
        if slide_rels_xml == "":
            return None
        root = _parse_xml(slide_rels_xml)
        if root is None:
            return None
        for r in _descendants(root, "Relationship"):
            if (_at(r, "Type") or "").endswith("/notesSlide"):
                target = (_at(r, "Target") or "").replace("../", "").lstrip("/")
                notes_xml = self._get_part("ppt/" + target)
                if notes_xml is None:
                    return None
                return self._parse_notes_text(notes_xml)
        return None

    def _parse_notes_text(self, xml: str) -> str:
        root = _parse_xml(xml)
        if root is None:
            return ""
        return "\n".join(_deep_text(t) for t in _descendants(root, "t"))

    def _parse_slide(self, xml: str, slide_id: str, notes: str | None) -> dict[str, Any]:
        slide: dict[str, Any] = {"id": slide_id, "layout": "blank", "elements": []}
        if notes is not None and notes != "":
            slide["notes"] = notes

        root = _parse_xml(xml)
        if root is None:
            return slide

        background = self._parse_background(root)
        if background is not None:
            slide["background"] = background

        for shape in _descendants(root, "sp"):
            element = self._parse_shape(shape)
            if element is not None:
                slide["elements"].append(element)
        for pic in _descendants(root, "pic"):
            element = self._parse_pic(pic)
            if element is not None:
                slide["elements"].append(element)
        for frame in _descendants(root, "graphicFrame"):
            element = self._parse_graphic_frame(frame)
            if element is not None:
                slide["elements"].append(element)

        return slide

    def _parse_background(self, root: _Node) -> dict[str, Any] | None:
        bg_pr: _Node | None = None
        for bg in _descendants(root, "bg"):
            inner = _el(bg, "bgPr")
            if inner is not None:
                bg_pr = inner
                break
        if bg_pr is None:
            return None

        solid_fill = _descendant(bg_pr, "solidFill")
        solid = _descendant(solid_fill, "srgbClr") if solid_fill is not None else None
        if solid is not None:
            hex_value = _at(solid, "val") or ""
            if hex_value != "":
                return {"color": "#" + hex_value}

        grad = _descendant(bg_pr, "gradFill")
        if grad is not None:
            css = self._grad_fill_to_css(grad)
            if css is not None:
                return {"gradient": css}

        blip_fill = _descendant(bg_pr, "blipFill")
        blip = _descendant(blip_fill, "blip") if blip_fill is not None else None
        if blip is not None:
            rid = _at(blip, "embed") or ""
            if rid != "" and rid in self._current_slide_rels:
                data_uri = self._read_media_as_data_uri(self._current_slide_rels[rid]["target"])
                if data_uri is not None:
                    return {"image": data_uri}

        return None

    def _grad_fill_to_css(self, grad: _Node) -> str | None:
        stops = _descendants(grad, "gs")
        if not stops:
            return None

        stop_strings: list[str] = []
        for stop in stops:
            pos = _to_int(_at(stop, "pos"))  # 0..100000
            pct = Emu.php_round(pos / 1000 * 10) / 10
            color = _descendant(stop, "srgbClr")
            if color is None:
                continue
            hex_value = _at(color, "val") or ""
            if hex_value == "":
                continue
            stop_strings.append("#" + hex_value.lower() + " " + _num_to_str(pct) + "%")
        if not stop_strings:
            return None

        lin = _descendant(grad, "lin")
        angle = 180
        if lin is not None:
            deg = _to_int(_at(lin, "ang")) / 60000 + 90
            angle = int(Emu.php_round(((deg % 360) + 360) % 360))

        return "linear-gradient(" + str(angle) + "deg, " + ", ".join(stop_strings) + ")"

    def _read_media_as_data_uri(self, archive_path: str) -> str | None:
        part = self._parts.get(archive_path)
        if part is None:
            return None
        mime = self._guess_mime_from_archive_path(archive_path)
        return "data:" + mime + ";base64," + base64.b64encode(part).decode("ascii")

    def _guess_mime_from_archive_path(self, path: str) -> str:
        return {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "svg": "image/svg+xml",
            "webp": "image/webp",
        }.get(_extension(path), "application/octet-stream")

    # ── Elements ──────────────────────────────────────────────────────────

    def _next_fallback_id(self, prefix: str = "imported-") -> str:
        """An id for an element whose ``<p:cNvPr>`` carries no ``name``.

        Its position in the file, as ``imported-<slide>-<nth>``. Callers reach
        it through ``or``, which does not evaluate it unless the name is
        genuinely absent, so the numbering stays tied to the file rather than
        to how many elements were parsed.
        """
        self._slide_fallback_ids += 1

        return f"{prefix}{self._slide_number}-{self._slide_fallback_ids}"

    def _parse_shape(self, sp: _Node) -> dict[str, Any] | None:
        xfrm = _descendant(sp, "xfrm")
        if xfrm is None:
            return None
        offset = _el(xfrm, "off")
        extent = _el(xfrm, "ext")
        if offset is None or extent is None:
            return None

        c_nv_pr = _descendant(sp, "cNvPr")
        base: dict[str, Any] = {
            "id": (_at(c_nv_pr, "name") if c_nv_pr is not None else None)
            or self._next_fallback_id(),
            "x": self._frac_x(_to_int(_at(offset, "x"))),
            "y": self._frac_y(_to_int(_at(offset, "y"))),
            "w": self._frac_x(_to_int(_at(extent, "cx"))),
            "h": self._frac_y(_to_int(_at(extent, "cy"))),
        }

        t_body = _descendant(sp, "txBody")
        paragraph_markdown: list[str] = []
        any_decoration = False
        paragraphs = [self._paragraph_runs(p) for p in _descendants(t_body, "p")] if t_body is not None else []
        # Bold / italic shared by EVERY text run of the element are its style,
        # so they carry no markers; decided over the element, as PHP does.
        all_runs = [run for _, runs in paragraphs for run in runs]
        text_runs = [run for run in all_runs if run["text"] != ""]
        all_bold = bool(text_runs) and all(run["b"] for run in text_runs)
        all_italic = bool(text_runs) and all(run["i"] for run in text_runs)
        for is_bullet, runs in paragraphs:
            md, decorated = self._runs_to_markdown(is_bullet, runs, all_bold, all_italic)
            paragraph_markdown.append(md)
            any_decoration = any_decoration or decorated

        prst_geom = _descendant(sp, "prstGeom")
        prst = _at(prst_geom, "prst") if prst_geom is not None else None

        if any(text != "" for text in paragraph_markdown):
            element: dict[str, Any] = {
                **base,
                "type": "text",
                "content": "\n".join(paragraph_markdown),
                "format": "markdown" if any_decoration else "plain",
            }
            style = self._text_style(t_body, all_runs) if t_body is not None else {}
            if style:
                element["style"] = style
            return element

        shape_kind = {
            "rect": "rect",
            "roundRect": "rounded-rect",
            "ellipse": "ellipse",
            "triangle": "triangle",
            "line": "line",
            "rightArrow": "arrow",
        }.get(prst or "")
        if shape_kind is not None:
            return {**base, "type": "shape", "shape": shape_kind, **self._shape_paint(sp)}

        return None

    def _read_theme(self) -> dict[str, Any]:
        """The theme's colours and fonts, in the deck's own keys. Mirrors PHP
        ``PptxReader::readTheme``: background = lt1, text = dk1, accent =
        accent1, muted = dk2, surface = lt2; heading = major font, body = minor
        font; mono only when NAMED (the writer's Consolas default is not
        reported, so a read stays a fixed point of write-then-read)."""
        xml = self._get_part("ppt/theme/theme1.xml")
        root = _parse_xml(xml) if xml is not None else None
        if root is None:
            return {}

        clr_scheme = _descendant(root, "clrScheme")
        colors: dict[str, str] = {}
        for key, slot in (("background", "lt1"), ("text", "dk1"), ("accent", "accent1"), ("muted", "dk2"), ("surface", "lt2")):
            node = _el(clr_scheme, slot)
            hex_value = _scheme_hex(node) if node is not None else None
            if hex_value is not None:
                colors[key] = "#" + hex_value

        font_scheme = _descendant(root, "fontScheme")
        fonts: dict[str, str] = {}
        for key, slot in (("heading", "majorFont"), ("body", "minorFont")):
            face = _at(_el(_el(font_scheme, slot), "latin"), "typeface") or ""
            if face != "":
                fonts[key] = face
        if self._mono_typeface != "" and self._mono_typeface != "Consolas":
            fonts["mono"] = self._mono_typeface

        out: dict[str, Any] = {}
        if colors:
            out["colors"] = colors
        if fonts:
            out["fonts"] = fonts
        return out

    def _shape_paint(self, sp: _Node) -> dict[str, Any]:
        """A shape's fill and outline. Mirrors PHP ``PptxReader::shapePaint``:
        ``noFill`` is stated as ``transparent``, because an absent ``fill``
        writes the default tint and an absent ``stroke`` the theme accent."""
        sp_pr = _el(sp, "spPr")
        if sp_pr is None:
            return {}
        out: dict[str, Any] = {}
        solid = _el(sp_pr, "solidFill")
        if _el(sp_pr, "noFill") is not None:
            out["fill"] = "transparent"
        elif solid is not None:
            color = _solid_fill_color(solid)
            if color is not None:
                out["fill"] = color

        ln = _el(sp_pr, "ln")
        if ln is not None:
            ln_solid = _el(ln, "solidFill")
            ln_color = _solid_fill_color(ln_solid) if ln_solid is not None else None
            if _el(ln, "noFill") is not None:
                out["stroke"] = "transparent"
            elif ln_color is not None:
                out["stroke"] = ln_color
                w = _at(ln, "w") or ""
                if _DIGITS.match(w):
                    out["strokeWidth"] = _px_from_emu(int(w))
                if _el(ln, "prstDash") is not None:
                    out["dashed"] = True
        return out

    def _text_style(self, t_body: _Node, runs: list[dict[str, Any]]) -> dict[str, Any]:
        """A text body's element-level style. Mirrors PHP ``PptxReader::textStyle``."""
        style: dict[str, Any] = {}
        first = next((run for run in runs if run["text"] != "" and not run["code"]), None)
        if first is not None and first["sz"] is not None:
            style["fontSize"] = _px_from_hundredths(first["sz"])
        text = [run for run in runs if run["text"] != ""]
        if text and all(run["b"] for run in text):
            style["weight"] = 700
        if text and all(run["i"] for run in text):
            style["italic"] = True
        if text and all(run["u"] for run in text):
            style["underline"] = True
        if first is not None and first["color"] is not None:
            style["color"] = first["color"]
        if first is not None and first["font"] is not None:
            style["fontFamily"] = first["font"]

        algn = _at(_el(_el(t_body, "p"), "pPr"), "algn") or ""
        align = {"ctr": "center", "r": "right", "just": "justify"}.get(algn)
        if align is not None:
            style["align"] = align
        anchor = _at(_el(t_body, "bodyPr"), "anchor") or ""
        vertical = {"ctr": "middle", "b": "bottom"}.get(anchor)
        if vertical is not None:
            style["verticalAlign"] = vertical
        return style

    def _parse_pic(self, pic: _Node) -> dict[str, Any] | None:
        xfrm = _descendant(pic, "xfrm")
        if xfrm is None:
            return None
        offset = _el(xfrm, "off")
        extent = _el(xfrm, "ext")
        if offset is None or extent is None:
            return None

        src = ""
        blip = _descendant(pic, "blip")
        if blip is not None:
            rid = _at(blip, "embed") or ""
            if rid != "" and rid in self._current_slide_rels:
                data_uri = self._read_media_as_data_uri(self._current_slide_rels[rid]["target"])
                if data_uri is not None:
                    src = data_uri

        c_nv_pr = _descendant(pic, "cNvPr")

        return {
            "id": (_at(c_nv_pr, "name") if c_nv_pr is not None else None)
            or self._next_fallback_id(),
            "type": "image",
            "x": self._frac_x(_to_int(_at(offset, "x"))),
            "y": self._frac_y(_to_int(_at(offset, "y"))),
            "w": self._frac_x(_to_int(_at(extent, "cx"))),
            "h": self._frac_y(_to_int(_at(extent, "cy"))),
            "src": src,
            "fit": "contain",
        }

    def _parse_graphic_frame(self, gf: _Node) -> dict[str, Any] | None:
        xfrm = _descendant(gf, "xfrm")
        if xfrm is None:
            return None
        offset = _el(xfrm, "off")
        extent = _el(xfrm, "ext")
        if offset is None or extent is None:
            return None

        tbl = _descendant(gf, "tbl")
        if tbl is None:
            # A chart frame, a diagram, an OLE object — recognised as
            # something, modelled as nothing. Skipping beats guessing.
            return None

        rows = _descendants(tbl, "tr")
        if not rows:
            return None

        # Whether row 0 is a header is DECLARED, not assumed. `a:tblPr/@firstRow`
        # is the only thing that says so, and header-less tables are ordinary
        # now — every metadataGrid and kpiBand is one. Assuming a header
        # promoted a row of DATA to column labels and dropped it from the rows,
        # silently losing content on the way back in.
        tbl_pr = _descendant(tbl, "tblPr")
        has_header = tbl_pr is not None and (_at(tbl_pr, "firstRow") or "0") == "1"

        # Column widths come from the grid, as fractions of the table, so a
        # table written with unequal columns reads back with them.
        grid_widths = [_to_int(_at(c, "w")) for c in _descendants(tbl, "gridCol")]
        grid_total = sum(grid_widths)

        first_cells = _descendants(rows[0], "tc")
        column_count = max(len(first_cells), len(grid_widths))

        # Column KEYS are synthesised (`col1`, `col2`, …) — the source deck's
        # keys are not in the file, only the labels are.
        columns: list[dict[str, Any]] = []
        for i in range(column_count):
            column: dict[str, Any] = {
                "key": f"col{i + 1}",
                "label": self._cell_text(first_cells[i]) if has_header and i < len(first_cells) else "",
            }
            if grid_total > 0 and i < len(grid_widths):
                column["width"] = grid_widths[i] / grid_total
            columns.append(column)

        body_rows: list[dict[str, str]] = []
        for row in rows[0 if not has_header else 1 :]:
            row_cells = _descendants(row, "tc")
            row_data: dict[str, str] = {}
            for i, col in enumerate(columns):
                if i < len(row_cells):
                    row_data[col["key"]] = self._cell_text(row_cells[i])
            body_rows.append(row_data)

        c_nv_pr = _descendant(gf, "cNvPr")

        return {
            "id": (_at(c_nv_pr, "name") if c_nv_pr is not None else None)
            or self._next_fallback_id("imported-table-"),
            "type": "table",
            "x": self._frac_x(_to_int(_at(offset, "x"))),
            "y": self._frac_y(_to_int(_at(offset, "y"))),
            "w": self._frac_x(_to_int(_at(extent, "cx"))),
            "h": self._frac_y(_to_int(_at(extent, "cy"))),
            "columns": columns,
            "rows": body_rows,
        }

    def _cell_text(self, cell: _Node) -> str:
        return "".join(_deep_text(t) for t in _descendants(cell, "t"))

    def _paragraph_runs(self, p: _Node) -> tuple[bool, list[dict[str, Any]]]:
        """A paragraph's bullet flag and runs. Mirrors PHP ``paragraphRuns``."""
        p_pr = _descendant(p, "pPr")
        is_bullet = p_pr is not None and _descendant(p_pr, "buChar") is not None

        parsed: list[dict[str, Any]] = []
        for r in _descendants(p, "r"):
            r_pr = _el(r, "rPr")
            t_node = _el(r, "t")
            text = _deep_text(t_node) if t_node is not None else ""
            bold = False
            italic = False
            underline = False
            code = False
            size: int | None = None
            color: str | None = None
            font: str | None = None
            if r_pr is not None:
                bold = (_at(r_pr, "b") or "0") == "1"
                italic = (_at(r_pr, "i") or "0") == "1"
                underline = (_at(r_pr, "u") or "none") != "none"
                sz = _at(r_pr, "sz") or ""
                size = int(sz) if _DIGITS.match(sz) else None
                solid = _el(r_pr, "solidFill")
                color = _solid_fill_color(solid) if solid is not None else None
                latin = _el(r_pr, "latin")
                if latin is not None:
                    face = _at(latin, "typeface") or ""
                    typeface = face.lower()
                    # Exact match against the typeface the deck RECORDED
                    # first, then the name sniff.
                    #
                    # The sniff alone was sound while the writer always emitted
                    # Consolas. Once a deck can name its own mono font it is
                    # not: "Fira Code" and "Cascadia" contain none of these
                    # words, so a code run came back as plain text — a silent
                    # downgrade on a file that opens perfectly.
                    #
                    # The sniff stays as the fallback, because it is the only
                    # thing that works for a pptx written by anything else.
                    recorded = self._mono_typeface.lower()

                    if (
                        (recorded != "" and typeface == recorded)
                        or "consola" in typeface
                        or "mono" in typeface
                        or "courier" in typeface
                    ):
                        code = True
                    elif face != "":
                        font = face
            parsed.append({
                "text": text, "b": bold, "i": italic, "u": underline, "code": code,
                "sz": size, "color": color, "font": font,
            })

        return (is_bullet, parsed)

    def _runs_to_markdown(
        self, is_bullet: bool, parsed: list[dict[str, Any]], all_bold: bool, all_italic: bool
    ) -> tuple[str, bool]:
        """One paragraph's runs back to a line of markdown, plus "was it decorated".

        Bold / italic shared by every text run of the ELEMENT are its style and
        carry no markers; otherwise the bold runs get ``**``. Mirrors PHP
        ``runsToMarkdown``.

        ATX headings are deliberately NOT reconstructed from run sizes — a
        hand-styled large bold line and a ``#`` heading are indistinguishable
        in the file, so round-trip fidelity stops at inline spans.
        """
        if not any(run["text"] != "" for run in parsed):
            return ("- " if is_bullet else "", is_bullet)

        # Coalesce adjacent runs that carry the SAME decoration.
        #
        # DrawingML splits text into runs for reasons that have nothing to do
        # with emphasis — a syntax highlighter emits one run per token, all of
        # them code — and emitting a marker per run produces markdown that is
        # not merely ugly but WRONG. A highlighted ``const deck = 1;`` came back
        # as "`const`` deck = ``1``;`", where every pair of adjacent backticks
        # closes one span and opens the next, so re-parsing it yields the
        # inverse of the intended emphasis.
        #
        # Merging first is also what makes the output stable: the same text
        # reads the same whether the writer split it into one run or six.
        merged: list[dict[str, Any]] = []
        for run in parsed:
            last = merged[-1] if merged else None

            if (
                last is not None
                and last["b"] == run["b"]
                and last["i"] == run["i"]
                and last["code"] == run["code"]
            ):
                last["text"] += run["text"]
                continue

            merged.append(dict(run))
        parsed = merged

        line = ""
        any_decoration = False
        for run in parsed:
            text = run["text"]
            emit_bold = run["b"] and not all_bold
            emit_italic = run["i"] and not all_italic
            if run["code"]:
                line += "`" + text + "`"
                any_decoration = True
            elif emit_bold and emit_italic:
                line += "***" + text + "***"
                any_decoration = True
            elif emit_bold:
                line += "**" + text + "**"
                any_decoration = True
            elif emit_italic:
                line += "*" + text + "*"
                any_decoration = True
            else:
                line += text

        if is_bullet:
            return ("- " + line, True)

        return (line, any_decoration)


_DIGITS = re.compile(r"^[0-9]+$")
_HEX6 = re.compile(r"^[0-9A-F]{6}$")


def _whole_or_float(value: float) -> int | float:
    """An int when whole, as PHP's reader returns 88 rather than 88.0."""
    return int(value) if value == math.floor(value) else value


def _px_from_hundredths(hundredths: int) -> int | float:
    """Design pixels on the 1920 canvas from hundredths of a point, to 2 decimals."""
    return _whole_or_float(Emu.php_round(hundredths * 2 / 75 * 100) / 100)


def _px_from_emu(emu: int) -> int | float:
    """Design pixels from EMU (12700 per point), to 2 decimals."""
    return _whole_or_float(Emu.php_round(emu * 8 / 38100 * 100) / 100)


def _scheme_hex(slot: _Node) -> str | None:
    """A colour slot's sRGB value (or a system colour's last-known one), upper-case, or None."""
    srgb = _el(slot, "srgbClr")
    sys_clr = _el(slot, "sysClr")
    if srgb is not None:
        val = _at(srgb, "val") or ""
    elif sys_clr is not None:
        val = _at(sys_clr, "lastClr") or ""
    else:
        val = ""
    val = val.upper()
    return val if _HEX6.match(val) else None


def _solid_fill_color(solid_fill: _Node) -> str | None:
    """A ``<a:solidFill>`` as the deck writes colours: ``#RRGGBB``, or
    ``rgba(r,g,b,a)`` below opaque. The alpha is formatted from the integer,
    never a float, so the three engines print the same digits."""
    clr = _el(solid_fill, "srgbClr")
    if clr is None:
        return None
    hex_value = (_at(clr, "val") or "").upper()
    if not _HEX6.match(hex_value):
        return None
    alpha_attr = _at(_el(clr, "alpha"), "val") or ""
    alpha = int(alpha_attr) if _DIGITS.match(alpha_attr) else 100000
    if alpha >= 100000:
        return "#" + hex_value
    fraction = str(alpha).rjust(5, "0").rstrip("0")
    return "rgba({},{},{},{})".format(
        int(hex_value[0:2], 16),
        int(hex_value[2:4], 16),
        int(hex_value[4:6], 16),
        "0" if fraction == "" else "0." + fraction,
    )


def _num_to_str(value: float) -> str:
    """PHP's ``(string)`` of a float — no trailing ``.0``."""
    if value == int(value):
        return str(int(value))
    return repr(value)

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
"""

from __future__ import annotations

import base64
import io
import os
import random
import re
import time
import xml.etree.ElementTree as ElementTree
import zipfile
from typing import Any

from ..helpers import emu as Emu

__all__ = ["PptxReader"]

_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


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
        self._parts: dict[str, bytes] = {}

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
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self._parts = {name: archive.read(name) for name in archive.namelist()}
        except zipfile.BadZipFile as exc:
            raise ValueError("Could not open zip archive.") from exc
        return self._extract()

    # ── Extraction ────────────────────────────────────────────────────────

    def _get_part(self, name: str) -> str | None:
        payload = self._parts.get(name)
        return None if payload is None else payload.decode("utf-8", "replace")

    def _extract(self) -> dict[str, Any]:
        deck: dict[str, Any] = {
            "id": "imported-" + format(int(time.time()) & 0xFFFFFF, "x"),
            "title": self._read_core_title() or "Imported",
            "theme": {"name": "imported"},
            "slides": [],
        }

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

            deck["slides"].append(
                self._parse_slide(slide_xml, f"imported-slide-{i + 1}", notes)
            )

        return deck

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
            "id": (_at(c_nv_pr, "name") if c_nv_pr is not None else None) or _fallback_id(),
            "x": Emu.to_frac_x(_to_int(_at(offset, "x"))),
            "y": Emu.to_frac_y(_to_int(_at(offset, "y"))),
            "w": Emu.to_frac_x(_to_int(_at(extent, "cx"))),
            "h": Emu.to_frac_y(_to_int(_at(extent, "cy"))),
        }

        t_body = _descendant(sp, "txBody")
        paragraph_markdown: list[str] = []
        any_decoration = False
        if t_body is not None:
            for p in _descendants(t_body, "p"):
                md, decorated = self._paragraph_to_markdown(p)
                paragraph_markdown.append(md)
                any_decoration = any_decoration or decorated

        prst_geom = _descendant(sp, "prstGeom")
        prst = _at(prst_geom, "prst") if prst_geom is not None else None

        if any(text != "" for text in paragraph_markdown):
            return {
                **base,
                "type": "text",
                "content": "\n".join(paragraph_markdown),
                "format": "markdown" if any_decoration else "plain",
            }

        shape_kind = {
            "rect": "rect",
            "roundRect": "rounded-rect",
            "ellipse": "ellipse",
            "triangle": "triangle",
            "line": "line",
            "rightArrow": "arrow",
        }.get(prst or "")
        if shape_kind is not None:
            return {**base, "type": "shape", "shape": shape_kind}

        return None

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
            "id": (_at(c_nv_pr, "name") if c_nv_pr is not None else None) or _fallback_id(),
            "type": "image",
            "x": Emu.to_frac_x(_to_int(_at(offset, "x"))),
            "y": Emu.to_frac_y(_to_int(_at(offset, "y"))),
            "w": Emu.to_frac_x(_to_int(_at(extent, "cx"))),
            "h": Emu.to_frac_y(_to_int(_at(extent, "cy"))),
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
            or _fallback_id("imported-table-"),
            "type": "table",
            "x": Emu.to_frac_x(_to_int(_at(offset, "x"))),
            "y": Emu.to_frac_y(_to_int(_at(offset, "y"))),
            "w": Emu.to_frac_x(_to_int(_at(extent, "cx"))),
            "h": Emu.to_frac_y(_to_int(_at(extent, "cy"))),
            "columns": columns,
            "rows": body_rows,
        }

    def _cell_text(self, cell: _Node) -> str:
        return "".join(_deep_text(t) for t in _descendants(cell, "t"))

    def _paragraph_to_markdown(self, p: _Node) -> tuple[str, bool]:
        """One ``<a:p>`` back to a line of markdown, plus "was it decorated".

        The heuristic that matters: when EVERY non-empty run is bold, bold is
        treated as the paragraph default (it came from ``style.weight``) and no
        ``**`` is emitted. Mixed runs get markers. Without this, a heading
        styled bold would come back as ``**Heading**`` and re-render doubly
        bold on the next write.

        ATX headings are deliberately NOT reconstructed from run sizes — a
        hand-styled large bold line and a ``#`` heading are indistinguishable
        in the file, so round-trip fidelity stops at inline spans.
        """
        p_pr = _descendant(p, "pPr")
        is_bullet = p_pr is not None and _descendant(p_pr, "buChar") is not None

        runs = _descendants(p, "r")
        if not runs:
            return ("- " if is_bullet else "", is_bullet)

        parsed: list[dict[str, Any]] = []
        all_bold = True
        all_italic = True
        any_non_empty = False
        for r in runs:
            r_pr = _el(r, "rPr")
            t_node = _el(r, "t")
            text = _deep_text(t_node) if t_node is not None else ""
            bold = False
            italic = False
            code = False
            if r_pr is not None:
                bold = (_at(r_pr, "b") or "0") == "1"
                italic = (_at(r_pr, "i") or "0") == "1"
                latin = _el(r_pr, "latin")
                if latin is not None:
                    typeface = (_at(latin, "typeface") or "").lower()
                    if "consola" in typeface or "mono" in typeface or "courier" in typeface:
                        code = True
            if text != "":
                any_non_empty = True
                if not bold:
                    all_bold = False
                if not italic:
                    all_italic = False
            parsed.append({"text": text, "b": bold, "i": italic, "code": code})

        if not any_non_empty:
            return ("- " if is_bullet else "", is_bullet)

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


def _fallback_id(prefix: str = "imported-") -> str:
    """The id used when a shape carries no name. Matches the peers' shape."""
    return prefix + str(random.randint(1000, 9999))


def _num_to_str(value: float) -> str:
    """PHP's ``(string)`` of a float — no trailing ``.0``."""
    if value == int(value):
        return str(int(value))
    return repr(value)

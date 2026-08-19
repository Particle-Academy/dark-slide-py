"""Tiny syntax highlighter. Mirrors PHP ``Helpers\\SyntaxHighlighter``.

Emits ``(text, kind)`` tokens the writer paints as coloured ``<a:r>`` runs.
Kinds: ``plain``, ``keyword``, ``string``, ``comment``, ``number``,
``builtin``, ``punctuation``. An unknown language yields one ``plain`` token,
so the writer renders the raw code rather than failing.

Three things about the scan are contract, not implementation detail:

1. **Longest match wins, first kind breaks the tie.** PCRE is leftmost-FIRST
   across an alternation, and Python's ``re`` is too — but the *kinds* are
   compared by explicit match length in a loop, with ``>`` (strictly greater)
   so the earliest-declared kind keeps a tie. Keep the loop; do not fold the
   patterns into one alternation.
2. **Pattern declaration order is part of that tie-break**, so the ``dict``
   literals below are ordered, not arbitrary.
3. **The scan matches against a fresh slice**, ``code[offset:]``, exactly as
   PHP's ``substr`` does. ``pattern.match(code, offset)`` would look like the
   same thing and is not: Python (and JS sticky regexes) let ``\\b`` see the
   character *before* the offset, where PHP's slice cannot. Today no reachable
   input distinguishes them; the slice means none ever will.

Unmatched input falls back to one ``plain`` token per character, then
:func:`_coalesce` merges neighbours of the same kind — which is also what
keeps a multi-byte character intact in the byte-indexed PHP original.
"""

from __future__ import annotations

import re
from typing import TypedDict

__all__ = ["Token", "tokenize", "color_for", "supported_languages"]


class Token(TypedDict):
    text: str
    kind: str


class _LangConfig(TypedDict):
    patterns: dict[str, re.Pattern[str]]
    keywords: list[str]
    builtins: list[str]


def _p(pattern: str) -> re.Pattern[str]:
    """Anchor + DOTALL, mirroring PHP's ``'/^(?:' . $pattern . ')/s'``.

    The ``(?:...)`` wrapper is what makes the anchor bind the WHOLE
    alternation; without it ``^a|b`` anchors only ``a``.
    """
    return re.compile("^(?:" + pattern + ")", re.DOTALL)


_C_LIKE: dict[str, re.Pattern[str]] = {
    "comment": _p(r"\/\/[^\n]*|\/\*.*?\*\/"),
    "string": _p(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`'),
    "number": _p(r"\b\d+(?:\.\d+)?\b"),
    "word": _p(r"[A-Za-z_$][A-Za-z0-9_$]*"),
    "punctuation": _p(r"[{}\[\]();,]"),
}

_JS_KEYWORDS = ["const","let","var","function","return","if","else","for","while","do","switch","case","break","continue","new","class","extends","implements","interface","type","enum","import","export","from","as","default","async","await","try","catch","finally","throw","typeof","instanceof","in","of","this","super","null","undefined","true","false","void","never","any","unknown","string","number","boolean","object"]  # noqa: E501
_JS_BUILTINS = ["console","Math","JSON","Object","Array","String","Number","Boolean","Promise","Map","Set","Date","Error","document","window","globalThis","require","module","process"]  # noqa: E501
_PHP_KEYWORDS = ["abstract","and","array","as","break","callable","case","catch","class","clone","const","continue","declare","default","do","echo","else","elseif","empty","enddeclare","endfor","endforeach","endif","endswitch","endwhile","enum","extends","final","finally","fn","for","foreach","function","global","goto","if","implements","include","include_once","instanceof","insteadof","interface","isset","list","match","namespace","new","null","or","private","protected","public","readonly","require","require_once","return","static","switch","throw","trait","try","unset","use","var","while","xor","yield","true","false","self","parent","this"]  # noqa: E501
_PHP_BUILTINS = ["__construct","__toString","__invoke","array_map","array_filter","array_reduce","array_keys","array_values","array_merge","count","strlen","str_replace","str_starts_with","str_ends_with","str_contains","substr","sprintf","printf","json_encode","json_decode"]  # noqa: E501
_BASH_KEYWORDS = ["if","then","else","elif","fi","for","while","do","done","case","esac","in","function","return","break","continue","export","local","readonly","unset"]  # noqa: E501
_BASH_BUILTINS = ["echo","printf","cd","pwd","ls","cp","mv","rm","mkdir","touch","cat","grep","sed","awk","curl","wget","git","npm","composer","php","node"]  # noqa: E501
_PY_KEYWORDS = ["and","as","assert","async","await","break","class","continue","def","del","elif","else","except","finally","for","from","global","if","import","in","is","lambda","nonlocal","not","or","pass","raise","return","try","while","with","yield","True","False","None"]  # noqa: E501
_PY_BUILTINS = ["print","len","range","list","dict","set","tuple","str","int","float","bool","open","input","enumerate","zip","map","filter","sorted","reversed","sum","min","max","abs","round"]  # noqa: E501


def _config(lang: str | None) -> _LangConfig | None:
    if lang is None:
        return None
    if lang in ("javascript", "typescript"):
        return {"patterns": _C_LIKE, "keywords": _JS_KEYWORDS, "builtins": _JS_BUILTINS}
    if lang == "php":
        return {
            "patterns": {
                "comment": _p(r"\/\/[^\n]*|#[^\n]*|\/\*.*?\*\/"),
                "string": _p(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
                "number": _p(r"\b\d+(?:\.\d+)?\b"),
                "word": _p(r"\$?[A-Za-z_][A-Za-z0-9_]*"),
                "punctuation": _p(r"[{}\[\]();,]"),
            },
            "keywords": _PHP_KEYWORDS,
            "builtins": _PHP_BUILTINS,
        }
    if lang == "json":
        return {
            "patterns": {
                "string": _p(r'"(?:[^"\\]|\\.)*"'),
                "number": _p(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"),
                "word": _p(r"[A-Za-z_][A-Za-z0-9_]*"),
                "punctuation": _p(r"[{}\[\]:,]"),
            },
            "keywords": ["true", "false", "null"],
            "builtins": [],
        }
    if lang == "bash":
        return {
            "patterns": {
                "comment": _p(r"#[^\n]*"),
                "string": _p(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
                "number": _p(r"\b\d+\b"),
                "word": _p(r"[A-Za-z_][A-Za-z0-9_]*"),
                "punctuation": _p(r"[{}\[\]();|&]"),
            },
            "keywords": _BASH_KEYWORDS,
            "builtins": _BASH_BUILTINS,
        }
    if lang == "css":
        return {
            "patterns": {
                "comment": _p(r"\/\*.*?\*\/"),
                "string": _p(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
                "number": _p(r"-?\d+(?:\.\d+)?(?:px|em|rem|%|vw|vh|deg)?"),
                "word": _p(r"[\-A-Za-z_][\-A-Za-z0-9_]*"),
                "punctuation": _p(r"[{};:,]"),
            },
            "keywords": ["important", "inherit", "initial", "unset", "auto", "none"],
            "builtins": [],
        }
    if lang == "python":
        return {
            "patterns": {
                "comment": _p(r"#[^\n]*"),
                "string": _p(r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"),
                "number": _p(r"\b\d+(?:\.\d+)?\b"),
                "word": _p(r"[A-Za-z_][A-Za-z0-9_]*"),
                "punctuation": _p(r"[{}\[\]():,]"),
            },
            "keywords": _PY_KEYWORDS,
            "builtins": _PY_BUILTINS,
        }
    if lang == "html":
        return {
            "patterns": {
                "comment": _p(r"<!--.*?-->"),
                "string": _p(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
                "keyword": _p(r"<\/?[A-Za-z][A-Za-z0-9-]*"),
                "punctuation": _p(r">|\/>|="),
            },
            "keywords": [],
            "builtins": [],
        }
    return None


def _normalize_language(language: str | None) -> str | None:
    if language is None:
        return None
    lang = language.lower().strip()
    if lang == "js":
        return "javascript"
    if lang == "ts":
        return "typescript"
    if lang in ("jsx", "tsx"):
        return "typescript"
    if lang in ("sh", "shell", "bash", "zsh"):
        return "bash"
    if lang == "py":
        return "python"
    if lang == "xml":
        return "html"
    return lang


def tokenize(code: str, language: str | None) -> list[Token]:
    """Tokenize a code block. Unknown language → one ``plain`` token."""
    cfg = _config(_normalize_language(language))
    if cfg is None:
        return [{"text": code, "kind": "plain"}]

    tokens: list[Token] = []
    offset = 0
    length = len(code)
    keywords = set(cfg["keywords"])
    builtins = set(cfg["builtins"])

    while offset < length:
        best_kind: str | None = None
        best_len = 0
        remainder = code[offset:]

        for kind, pattern in cfg["patterns"].items():
            m = pattern.match(remainder)
            if m is not None:
                match_len = len(m.group(0))
                if match_len > best_len:
                    best_len = match_len
                    best_kind = kind

        if best_kind is None or best_len == 0:
            tokens.append({"text": code[offset], "kind": "plain"})
            offset += 1
            continue

        text = code[offset : offset + best_len]
        kind = best_kind
        if kind == "word":
            if text in keywords:
                kind = "keyword"
            elif text in builtins:
                kind = "builtin"
            else:
                kind = "plain"

        tokens.append({"text": text, "kind": kind})
        offset += best_len

    return _coalesce(tokens)


def color_for(kind: str) -> str:
    """Token colour, tuned for the ``#0F172A`` fill a code element paints itself."""
    return {
        "keyword": "C084FC",
        "string": "86EFAC",
        "comment": "64748B",
        "number": "FBBF24",
        "builtin": "67E8F9",
        "punctuation": "CBD5E1",
    }.get(kind, "F8FAFC")


def supported_languages() -> list[str]:
    return [
        "javascript",
        "typescript",
        "jsx",
        "tsx",
        "php",
        "json",
        "bash",
        "shell",
        "css",
        "python",
        "html",
        "xml",
    ]


def _coalesce(tokens: list[Token]) -> list[Token]:
    """Merge adjacent same-kind tokens.

    Without this the single-character fallback would emit one ``<a:r>`` per
    unmatched character.
    """
    out: list[Token] = []
    for token in tokens:
        if out and out[-1]["kind"] == token["kind"]:
            out[-1]["text"] += token["text"]
            continue
        out.append({"text": token["text"], "kind": token["kind"]})
    return out

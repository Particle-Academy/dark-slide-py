"""What the published schema tells a model about units, and whether it is true.

`style` was exported as a bare `{"type": "object"}` until 0.2.1. A model filling
it in had only the key names, and `fontSize` reads as points: in the fancy-labs
document lab an agent described its headline as 232pt and the file carried
116pt. 0.3 gave every length in the object one unit, the design pixel, and the
descriptions say so with worked examples.

Two guarantees:

- the worked examples the descriptions quote are what THIS writer emits;
- the element position, size, style and outline schema, and the theme's canvas
  fields, are IDENTICAL to the PHP reference's, so the three engines cannot
  describe one field three ways.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import zipfile

import pytest

from dark_slide import json_schema, to_bytes
from tests._oracle import REPO_ROOT, oracle_available, php_binary, php_src_root, require_oracle


def _element_properties(schema: dict) -> dict:
    return schema["properties"]["slides"]["items"]["properties"]["elements"]["items"]["properties"]


def _theme_properties(schema: dict) -> dict:
    return schema["properties"]["theme"]["properties"]


def _style() -> dict:
    return _element_properties(json_schema())["style"]


def _slide_xml(style: dict) -> str:
    data = to_bytes({
        "id": "units",
        "title": "Style units",
        "theme": {"name": "default"},
        "slides": [{"id": "s1", "elements": [{
            "id": "t", "type": "text", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.3,
            "content": "First paragraph\nSecond paragraph", "style": style,
        }]}],
    })
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("ppt/slides/slide1.xml").decode("utf-8")


def test_every_length_is_described_as_a_design_pixel_on_the_canvas() -> None:
    style = _style()
    assert "DESIGN PIXELS" in style["description"]
    assert "points = px x 720 / slideWidth" in style["description"]
    for key in ("letterSpacing", "spaceBefore", "spaceAfter", "radius", "padding"):
        assert "design pixels" in style["properties"][key]["description"], key


def test_font_size_is_described_as_the_file_writes_it() -> None:
    description = _style()["properties"]["fontSize"]["description"]
    for phrase in ("96 is written as 36pt", "28 as 10.5pt", "never below 1pt", "Default 28"):
        assert phrase in description

    assert 'sz="3600"' in _slide_xml({"fontSize": 96})
    assert 'sz="1050"' in _slide_xml({"fontSize": 28})
    assert 'sz="1050"' in _slide_xml({})
    assert 'sz="100"' in _slide_xml({"fontSize": 2})


def test_the_other_lengths_are_described_as_the_file_writes_them() -> None:
    properties = _style()["properties"]

    assert "8 is written as 3pt" in properties["letterSpacing"]["description"]
    assert 'spc="300"' in _slide_xml({"letterSpacing": 8})

    assert "16 is written as 6pt" in properties["spaceBefore"]["description"]
    assert '<a:spcBef><a:spcPts val="600"/></a:spcBef>' in _slide_xml({"spaceBefore": 16})

    assert "32 is written as 12pt" in properties["padding"]["description"]
    assert 'lIns="152400"' in _slide_xml({"padding": 32})  # 12pt x 12700 EMU


def test_line_height_is_described_as_a_multiple_and_the_file_agrees() -> None:
    assert "1.4 is written as 140%" in _style()["properties"]["lineHeight"]["description"]
    assert '<a:spcPct val="140000"/>' in _slide_xml({"lineHeight": 1.4})


def test_the_canvas_is_described() -> None:
    theme = _theme_properties(json_schema())
    assert "1920 by default" in theme["slideWidth"]["description"]
    assert "1440 reproduces" in theme["slideWidth"]["description"]
    assert "16/9 by default" in theme["aspectRatio"]["description"]
    assert "design pixels" in _element_properties(json_schema())["strokeWidth"]["description"]


@pytest.mark.parity
def test_position_size_style_outline_and_canvas_match_the_php_reference() -> None:
    require_oracle()
    ok, why = oracle_available()
    if not ok:
        pytest.skip(f"PHP oracle unavailable: {why}")

    env = dict(os.environ)
    env["DARK_SLIDE_PHP_SRC"] = str(php_src_root())
    result = subprocess.run(
        [php_binary(), str(REPO_ROOT / "scripts" / "php_jsonschema.php")],
        capture_output=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    reference = json.loads(result.stdout)
    ours = json_schema()

    # The comparison has to be over something, or it passes on two empty exports.
    assert "fontSize" in _element_properties(reference)["style"].get("properties", {})
    assert "1920" in _theme_properties(reference)["slideWidth"].get("description", "")

    for key in ("x", "y", "w", "h", "style", "strokeWidth"):
        assert _element_properties(ours)[key] == _element_properties(reference)[key], f"element.{key} differs from the PHP reference"
    for key in ("slideWidth", "aspectRatio"):
        assert _theme_properties(ours)[key] == _theme_properties(reference)[key], f"theme.{key} differs from the PHP reference"

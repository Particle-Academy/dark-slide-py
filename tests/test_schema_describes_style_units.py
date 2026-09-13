"""What the published schema tells a model about units, and whether it is true.

`style` was exported as a bare `{"type": "object"}`. A model filling it in had
only the key names, and `fontSize` reads as points while every engine treats it
as design pixels and halves it. In the fancy-labs document lab an agent
described its headline as 232pt and the file carried 116pt.

Two guarantees:

- the worked examples the descriptions quote are what THIS writer emits;
- the element position and style schema is IDENTICAL to the PHP reference's, so
  the three engines cannot describe one field three ways.
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


def test_font_size_is_described_as_design_pixels_halved_and_the_file_agrees() -> None:
    description = _style()["properties"]["fontSize"]["description"]
    for phrase in ("DESIGN PIXELS", "96 is written as 48pt", "24 as 12pt", "anything under 16 as 8pt"):
        assert phrase in description

    assert 'sz="4800"' in _slide_xml({"fontSize": 96})
    assert 'sz="1200"' in _slide_xml({"fontSize": 24})
    assert 'sz="800"' in _slide_xml({"fontSize": 10})


def test_fields_already_in_points_are_described_and_the_file_agrees() -> None:
    properties = _style()["properties"]

    assert "2 is written as 2pt" in properties["letterSpacing"]["description"]
    assert 'spc="200"' in _slide_xml({"letterSpacing": 2})

    assert "6 is written as 6pt" in properties["spaceBefore"]["description"]
    assert '<a:spcBef><a:spcPts val="600"/></a:spcBef>' in _slide_xml({"spaceBefore": 6})

    assert "12 is written as 12pt" in properties["padding"]["description"]
    assert 'lIns="152400"' in _slide_xml({"padding": 12})  # 12pt x 12700 EMU


def test_line_height_is_described_as_a_multiple_and_the_file_agrees() -> None:
    assert "1.4 is written as 140%" in _style()["properties"]["lineHeight"]["description"]
    assert '<a:spcPct val="140000"/>' in _slide_xml({"lineHeight": 1.4})


@pytest.mark.parity
def test_position_size_and_style_match_the_php_reference() -> None:
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

    reference = _element_properties(json.loads(result.stdout))
    ours = _element_properties(json_schema())

    # The comparison has to be over something, or it passes on two empty exports.
    assert "fontSize" in reference["style"].get("properties", {})
    for key in ("x", "y", "w", "h", "style"):
        assert ours[key] == reference[key], f"element.{key} differs from the PHP reference"

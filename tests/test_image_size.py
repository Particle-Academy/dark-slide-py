"""The image-header sniffer, held to PHP's ``getimagesizefromstring``.

Intrinsic pixel dimensions decide ``fit: cover``'s crop insets and
``fit: contain``'s letterbox, so a sniffer that disagrees with PHP produces
different geometry from the same deck. This port hand-rolls the sniffer rather
than taking an imaging dependency (see AGENTS.md), which makes "it matches
PHP" a claim — so this file turns it into a test result by running PHP's
builtin over the same bytes.

**It covers MORE than the Node port does.** ``dark-slide-js``'s ``getImageSize``
handles PNG, GIF and JPEG only, while PHP's builtin also reads WebP and BMP —
so a WebP with ``fit: cover`` gets a real centre-crop in PHP and a stretched
fill in Node. The polyglot spec lists that as divergence #3 for the pair. PHP is
the reference for the trio, so this port follows PHP, and the two extra rows
below are the evidence rather than the intention.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from dark_slide.writer.pptx_writer import image_mime, image_size
from tests import _oracle

pytestmark = pytest.mark.parity

PHP_IMAGESIZE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "php_imagesize.php"


def _vp8x(width: int, height: int) -> bytes:
    """A WebP extended-format container declaring a canvas size.

    Header-only on purpose: this exercises the sniffer, and both engines read
    the canvas size out of the VP8X chunk without decoding any pixels.
    """
    payload = (
        bytes([0]) + b"\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    )
    chunk = b"VP8X" + struct.pack("<I", len(payload)) + payload
    body = b"WEBP" + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _bmp(width: int, height: int) -> bytes:
    header = b"BM" + struct.pack("<IHHI", 54, 0, 0, 54)
    info = struct.pack("<IiiHH", 40, width, height, 1, 24)
    return header + info + b"\x00" * 24


def _jpeg(width: int, height: int) -> bytes:
    """SOI, one SOF0 frame header, EOI — the marker chain the scanner walks."""
    sof = (
        bytes([0xFF, 0xC0, 0x00, 0x11, 0x08])
        + struct.pack(">HH", height, width)
        + bytes([3, 1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1])
    )
    return b"\xff\xd8" + sof + b"\xff\xd9"


def _gif(width: int, height: int) -> bytes:
    return (
        b"GIF89a"
        + struct.pack("<HH", width, height)
        + bytes([0xF0, 0, 0])
        + b"\x00\x00\x00\xff\xff\xff"
        + b"\x3b"
    )


#: name -> (bytes, expected size). Every entry is also checked against PHP.
SAMPLES: dict[str, bytes] = {
    "png_1x1": base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
    ),
    "png_2x1": base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    ),
    "gif_1x1": base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"),
    "gif_3x2": _gif(3, 2),
    "jpeg_5x9": _jpeg(5, 9),
    "bmp_6x4": _bmp(6, 4),
    "webp_vp8x_7x3": _vp8x(7, 3),
    # A real lossless WebP from an encoder, not a handmade header.
    "webp_vp8l_1x1": base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA=="),
}

EXPECTED: dict[str, tuple[int, int]] = {
    "png_1x1": (1, 1),
    "png_2x1": (2, 1),
    "gif_1x1": (1, 1),
    "gif_3x2": (3, 2),
    "jpeg_5x9": (5, 9),
    "bmp_6x4": (6, 4),
    "webp_vp8x_7x3": (7, 3),
    "webp_vp8l_1x1": (1, 1),
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_the_sniffer_reads_the_expected_dimensions(name: str) -> None:
    assert image_size(SAMPLES[name]) == EXPECTED[name]


def test_the_sniffer_agrees_with_phps_builtin(php_oracle, tmp_path) -> None:
    for name, payload in SAMPLES.items():
        (tmp_path / f"{name}.bin").write_bytes(payload)

    binary = _oracle.php_binary()
    assert binary is not None
    result = subprocess.run(
        [binary, str(PHP_IMAGESIZE_SCRIPT), str(tmp_path)],
        capture_output=True,
        env=dict(os.environ),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    php_sizes = json.loads(result.stdout.decode("utf-8"))
    py_sizes = {name: list(image_size(payload) or ()) for name, payload in SAMPLES.items()}

    assert php_sizes, "the PHP side returned nothing — the comparison would be vacuous"
    assert py_sizes == php_sizes


def test_unrecognised_bytes_sniff_to_nothing_rather_than_guessing() -> None:
    assert image_size(b"") is None
    assert image_size(b"not an image at all, just prose") is None
    # An SVG is a legitimate media type here and has no pixel dimensions;
    # PHP's builtin also declines it, so `fit: cover` falls back to a stretch.
    assert image_size(b'<svg xmlns="http://www.w3.org/2000/svg"/>') is None


def test_the_mime_sniffer_covers_the_same_formats() -> None:
    assert image_mime(SAMPLES["png_1x1"]) == "image/png"
    assert image_mime(SAMPLES["gif_1x1"]) == "image/gif"
    assert image_mime(SAMPLES["jpeg_5x9"]) == "image/jpeg"
    assert image_mime(SAMPLES["webp_vp8l_1x1"]) == "image/webp"
    assert image_mime(SAMPLES["bmp_6x4"]) == "image/bmp"
    assert image_mime(b"nope") is None

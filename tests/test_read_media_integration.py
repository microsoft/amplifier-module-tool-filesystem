"""Opt-in candidate-graph tests with the actual Foundation media implementation.

Run with FILESYSTEM_MEDIA_INTEGRATION=1 and the exact reviewed Foundation candidate
on PYTHONPATH plus its media extra. The runtime module has no Foundation import.
"""

import hashlib
import io
import json
import os
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock
import zlib

import pytest

if os.environ.get("FILESYSTEM_MEDIA_INTEGRATION") != "1":
    pytest.skip("explicit Foundation media candidate required", allow_module_level=True)

from PIL import Image
from amplifier_foundation.session.media import (
    MediaPolicy,
    SessionMediaCapability,
    SessionMediaStore,
)

from amplifier_module_tool_filesystem.read import ReadTool

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.name != "posix", reason="POSIX media path qualification"),
]


def tool(tmp_path, *, origin=True, enabled=True, **limits):
    policy = MediaPolicy(**{
        "max_bytes": 1024 * 1024, "max_pixels": 1024 * 1024, "max_images": 1,
        **limits,
    })
    store = SessionMediaStore(
        tmp_path / "media", "test-session", policy=policy,
        origin_resolver=(lambda: {
            "kind": "tool", "session_id": "test-session", "id": "actual-call",
        }) if origin else None,
    )
    cap = SessionMediaCapability(store, enabled=enabled)
    host = SimpleNamespace(
        get_capability=lambda key: cap if key == "experimental.media.v1" else None,
        hooks=SimpleNamespace(emit=AsyncMock()),
    )
    return ReadTool({"working_dir": str(tmp_path)}, host), store


def image_bytes(fmt):
    output = io.BytesIO()
    Image.new("RGB", (3, 2), (12, 34, 56)).save(output, format=fmt)
    return output.getvalue()


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
async def test_real_decoder_original_bytes_digest_shape_and_private_stage(tmp_path, fmt, mime):
    data = image_bytes(fmt)
    source = tmp_path / "image.bin"
    source.write_bytes(data)
    reader, store = tool(tmp_path)
    try:
        result = await reader.execute({
            "file_path": source.name, "origin": {"id": "forged"},
        })
        assert result.success, result
        ref = result.output["experimental.media.v1"]["refs"][0]
        assert ref["sha256"] == hashlib.sha256(data).hexdigest()
        assert (ref["mime"], ref["width"], ref["height"], ref["bytes"]) == (mime, 3, 2, len(data))
        assert ref["provenance"]["id"] == "actual-call"
        assert source.read_bytes() == data
        serialized = json.dumps(result.model_dump())
        assert "base64" not in serialized
        assert "stream" not in serialized
        # A producer must not make staged bytes model-readable.
        cap = reader.coordinator.get_capability("experimental.media.v1")
        with pytest.raises(ValueError):
            cap.resolve(ref, purpose="model")
    finally:
        store.close()


@pytest.mark.parametrize("case", [
    "signature_only_corrupt_png", "truncated_png", "truncated_jpeg", "pixel_limit", "byte_limit",
    "animated_png", "missing_origin", "disabled", "huge_dimensions", "corrupt_png",
])
async def test_real_decoder_rejects_invalid_or_unavailable_images(tmp_path, case):
    data = image_bytes("JPEG" if case == "truncated_jpeg" else "PNG")
    limits = {}
    if case == "signature_only_corrupt_png":
        data = b"\x89PNG\r\n\x1a\nnot a raster"
    elif case.startswith("truncated"):
        data = data[:len(data) // 2]
    elif case == "pixel_limit":
        limits["max_pixels"] = 5
    elif case == "byte_limit":
        limits["max_bytes"] = 16
    elif case == "huge_dimensions":
        data = data[:16] + struct.pack(">II", 2**30, 2**30) + data[24:]
        data = data[:29] + struct.pack(">I", zlib.crc32(data[12:29])) + data[33:]
    elif case == "corrupt_png":
        data = data[:41] + bytes([data[41] ^ 255]) + data[42:]
    elif case == "animated_png":
        output = io.BytesIO()
        Image.new("RGB", (3, 2), "red").save(
            output, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (3, 2), "blue")], duration=100,
        )
        data = output.getvalue()
    source = tmp_path / ("bad.jpg" if case == "truncated_jpeg" else "bad.png")
    source.write_bytes(data)
    reader, store = tool(
        tmp_path, origin=case != "missing_origin", enabled=case != "disabled", **limits,
    )
    try:
        result = await reader.execute({"file_path": source.name})
        assert not result.success
        assert "no pixels were sent" in result.output["content"]
        assert "experimental.media.v1" not in result.output
        reader.coordinator.hooks.emit.assert_not_called()
        assert source.read_bytes() == data
    finally:
        store.close()

@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg"])
async def test_real_media_capability_does_not_capture_text_with_image_suffix(tmp_path, suffix):
    source = tmp_path / ("text" + suffix)
    source.write_text("first\nsecond\n")
    reader, store = tool(tmp_path)
    try:
        # Explicit defaults remain text parameters, even with an enabled decoder.
        result = await reader.execute({"file_path": source.name, "offset": 1, "limit": 2000})
        assert result.success and result.output["content"] == "     1\tfirst\n     2\tsecond"
        assert "experimental.media.v1" not in result.output
        assert list(store.journal()) == []
    finally:
        store.close()


async def test_real_capability_bounds_sparse_oversize_stream(tmp_path):
    source = tmp_path / "huge.png"
    with source.open("wb") as output:
        output.write(b"\x89PNG\r\n\x1a\n")
        output.truncate(2**30)
    reader, store = tool(tmp_path, max_bytes=1024)
    try:
        result = await reader.execute({"file_path": source.name})
        assert not result.success
        assert "no pixels were sent" in result.output["content"]
        assert "experimental.media.v1" not in result.output
        assert source.stat().st_size == 2**30
    finally:
        store.close()
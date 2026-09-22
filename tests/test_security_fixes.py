"""Tests for PR7 security fixes: symlink bypass + binary crash.

Run from this directory:
    pytest test_security_fixes.py -v

The tests import directly from the patch files (path_validation.py, read.py)
so they validate the fixed implementations in isolation.  amplifier_core is
mocked so no runtime dependency on the Amplifier package is needed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


# ── Import patch files from this directory ──────────────────────────────────
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from path_validation import is_in_path_list, is_path_allowed  # noqa: E402

# Stub out amplifier_core before importing read.py
_core_mock = MagicMock()
_core_mock.ToolResult = MagicMock(side_effect=lambda **kw: kw)
sys.modules.setdefault("amplifier_core", _core_mock)
sys.modules.setdefault(
    "amplifier_core.events", MagicMock(ARTIFACT_READ="artifact:read")
)

from read import ReadTool, _is_binary  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    """Return a minimal coordinator mock that satisfies ReadTool."""
    coord = MagicMock()
    coord.get_capability.return_value = None
    coord.hooks.emit = AsyncMock(return_value=None)
    return coord


def _make_tool(allowed_paths: list[str] | None = None) -> ReadTool:
    config: dict = {}
    if allowed_paths is not None:
        config["allowed_read_paths"] = allowed_paths
    return ReadTool(config=config, coordinator=_make_coordinator())


def _run(coro):
    """Run a coroutine synchronously (no pytest-asyncio required)."""
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# path_validation.py — symlink bypass (Fix 1)
# ═══════════════════════════════════════════════════════════════════════════


class TestSymlinkBypass:
    """Verify that resolve(strict=True) closes the symlink-escape bypass."""

    def test_symlink_outside_allowed_dir_is_rejected(self, tmp_path):
        """A symlink inside the allowed dir that targets outside must be denied.

        Attack scenario:
            allowed_dir/link  →  /tmp/secret_dir/secret.txt
        Before fix: path.resolve() followed the symlink location (allowed_dir)
                    rather than the real target — ALLOWED incorrectly.
        After fix:  strict=True resolves to the real target, which is outside
                    allowed_dir → correctly DENIED.
        """
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        secret_file = secret_dir / "secret.txt"
        secret_file.write_text("top secret")

        # symlink lives inside allowed_dir but points to secret_file outside it
        link = allowed_dir / "escape.txt"
        link.symlink_to(secret_file)

        allowed, msg = is_path_allowed(
            path=link,
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )

        assert allowed is False, (
            "Symlink pointing outside the allowed dir must be denied, got: " + str(msg)
        )

    def test_resolve_strict_raises_on_nonexistent(self, tmp_path):
        """A path that does not exist must be denied (OSError → False)."""
        ghost = tmp_path / "does_not_exist.txt"
        # Path must not exist
        assert not ghost.exists()

        allowed, msg = is_path_allowed(
            path=ghost,
            allowed_paths=[str(tmp_path)],
            denied_paths=[],
        )

        assert allowed is False
        assert msg is not None
        # Should mention resolve / existence
        assert "does not exist" in msg or "Access denied" in msg

    def test_normal_path_inside_allowed_dir_works(self, tmp_path):
        """A regular (non-symlink) file inside the allowed dir must be allowed."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        real_file = allowed_dir / "notes.txt"
        real_file.write_text("hello")

        allowed, msg = is_path_allowed(
            path=real_file,
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )

        assert allowed is True
        assert msg is None

    def test_path_with_symlink_resolved_to_target(self, tmp_path):
        """resolve(strict=True) on a symlink returns the real target path."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(real_file)

        # strict=True should resolve the link to the real file
        resolved = link.resolve(strict=True)
        assert resolved == real_file.resolve(strict=True)
        assert resolved != link  # link itself is NOT the resolved value

    def test_is_in_path_list_returns_false_for_nonexistent(self, tmp_path):
        """is_in_path_list returns False when target doesn't exist."""
        ghost = tmp_path / "ghost.txt"
        assert not ghost.exists()
        result = is_in_path_list(ghost, [str(tmp_path)])
        assert result is False

    def test_symlink_to_inside_allowed_dir_is_accepted(self, tmp_path):
        """A symlink whose REAL target is inside the allowed dir must be allowed."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        real_file = allowed_dir / "doc.txt"
        real_file.write_text("hello")
        # Symlink also lives inside allowed_dir, points to another file inside
        link = allowed_dir / "alias.txt"
        link.symlink_to(real_file)

        allowed, msg = is_path_allowed(
            path=link,
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )

        assert allowed is True, "Symlink whose target is inside allowed_dir should pass"

    def test_denied_path_takes_priority(self, tmp_path):
        """A path inside both allowed and denied directories must be denied."""
        shared = tmp_path / "shared"
        shared.mkdir()
        the_file = shared / "sensitive.txt"
        the_file.write_text("sensitive")

        allowed, msg = is_path_allowed(
            path=the_file,
            allowed_paths=[str(shared)],
            denied_paths=[str(shared)],
        )

        assert allowed is False
        assert "denied" in (msg or "").lower()


# ═══════════════════════════════════════════════════════════════════════════
# read.py — binary detection (Fix 2)
# ═══════════════════════════════════════════════════════════════════════════


class TestIsBinaryHelper:
    """Unit tests for the _is_binary() helper function."""

    def test_is_binary_detects_null_bytes(self, tmp_path):
        """A file containing null bytes must be identified as binary."""
        binary_file = tmp_path / "blob.bin"
        binary_file.write_bytes(b"PK\x03\x04\x00\x00some data here\x00more data")
        assert _is_binary(binary_file) is True

    def test_is_binary_returns_false_for_text(self, tmp_path):
        """A plain text file (no null bytes) must NOT be identified as binary."""
        text_file = tmp_path / "notes.txt"
        text_file.write_text("Hello, world!\nThis is a text file.\n", encoding="utf-8")
        assert _is_binary(text_file) is False

    def test_is_binary_returns_false_for_nonexistent(self, tmp_path):
        """_is_binary returns False for a missing file (OSError path)."""
        ghost = tmp_path / "does_not_exist.bin"
        assert _is_binary(ghost) is False

    def test_is_binary_accepts_path_and_string(self, tmp_path):
        """_is_binary accepts both Path objects and str paths."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"\x00")
        assert _is_binary(f) is True
        assert _is_binary(str(f)) is True

    def test_is_binary_elf_header(self, tmp_path):
        """ELF magic bytes (\\x7fELF) with embedded nulls are detected as binary."""
        elf = tmp_path / "prog"
        elf.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8)
        assert _is_binary(elf) is True


class TestReadToolBinaryDetection:
    """Integration tests: ReadTool.execute() with binary / encoding edge cases."""

    def test_binary_file_returns_metadata(self, tmp_path):
        """execute() on a binary file must return is_binary=True without crashing."""
        binary_file = tmp_path / "image.png"
        # PNG-like header with embedded nulls
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        tool = _make_tool()  # no path restrictions
        result = _run(tool.execute({"file_path": str(binary_file)}))

        assert result["success"] is True
        out = result["output"]
        assert out["is_binary"] is True
        assert "size_bytes" in out
        assert "cannot display as text" in out["content"].lower()
        assert str(binary_file) == out["file_path"]

    def test_binary_file_includes_size_and_suffix(self, tmp_path):
        """The metadata result for a binary file includes size_bytes and suffix."""
        binary_file = tmp_path / "archive.gz"
        binary_file.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 20)

        tool = _make_tool()
        result = _run(tool.execute({"file_path": str(binary_file)}))

        out = result["output"]
        assert out["is_binary"] is True
        assert out["size_bytes"] == binary_file.stat().st_size
        assert ".gz" in out["content"]

    def test_utf8_file_reads_normally(self, tmp_path):
        """A UTF-8 file must be read and returned with line numbers."""
        utf8_file = tmp_path / "hello.txt"
        utf8_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

        tool = _make_tool()
        result = _run(tool.execute({"file_path": str(utf8_file)}))

        assert result["success"] is True
        out = result["output"]
        assert out.get("is_binary") is not True
        assert "line one" in out["content"]
        assert out["total_lines"] == 3

    def test_non_utf8_file_falls_back_to_latin1(self, tmp_path):
        """A file with latin-1 bytes (0x80-0xFF, no nulls) must decode via fallback."""
        latin1_file = tmp_path / "latin1.txt"
        # é (0xe9), ñ (0xf1), ü (0xfc) — invalid UTF-8, valid latin-1
        latin1_file.write_bytes(b"caf\xe9 menu\n\xf1o\xfc\n")

        tool = _make_tool()
        result = _run(tool.execute({"file_path": str(latin1_file)}))

        assert result["success"] is True
        out = result["output"]
        # Must have read some content — not a binary/error result
        assert "content" in out
        # latin-1 fallback: "café" should appear
        assert "caf" in out["content"]

    def test_empty_file_returns_warning(self, tmp_path):
        """An existing but empty file must return a warning, not an error."""
        empty = tmp_path / "empty.txt"
        empty.write_text("")

        tool = _make_tool()
        result = _run(tool.execute({"file_path": str(empty)}))

        assert result["success"] is True
        out = result["output"]
        assert "warning" in out
        assert out["total_lines"] == 0

    def test_path_not_found_returns_error(self, tmp_path):
        """A non-existent file path must return success=False."""
        tool = _make_tool()
        result = _run(tool.execute({"file_path": str(tmp_path / "ghost.txt")}))
        assert result["success"] is False


# ═══════════════════════════════════════════════════════════════════════════
# read.py — _is_allowed() with strict=True
# ═══════════════════════════════════════════════════════════════════════════


class TestIsAllowedSymlinkSafety:
    """_is_allowed() must not grant access when a symlink escapes the sandbox."""

    def test_symlink_escape_is_denied_in_is_allowed(self, tmp_path):
        """ReadTool._is_allowed() must deny a symlink whose real target is outside
        the configured allowed_read_paths."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        secret_file = secret_dir / "secret.txt"
        secret_file.write_text("top secret")

        link = allowed_dir / "escape.txt"
        link.symlink_to(secret_file)

        tool = _make_tool(allowed_paths=[str(allowed_dir)])
        # _is_allowed must deny because real target is outside allowed_dir
        assert tool._is_allowed(link) is False

    def test_real_file_inside_allowed_dir_passes_is_allowed(self, tmp_path):
        """A real (non-symlink) file inside allowed_read_paths must pass."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        real_file = allowed_dir / "doc.txt"
        real_file.write_text("contents")

        tool = _make_tool(allowed_paths=[str(allowed_dir)])
        assert tool._is_allowed(real_file) is True

    def test_nonexistent_path_is_denied_in_is_allowed(self, tmp_path):
        """_is_allowed returns False for a path that doesn't exist."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        tool = _make_tool(allowed_paths=[str(allowed_dir)])
        ghost = allowed_dir / "ghost.txt"
        assert tool._is_allowed(ghost) is False

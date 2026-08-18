"""Line-ending preservation tests for edit_file / write_file (Windows-safety).

The bug: Python text-mode write (`Path.write_text`) translates every ``\\n`` to
``os.linesep`` on write. On native Windows that silently rewrote an LF-only
file's ENTIRE line-ending convention to CRLF on every ``edit_file`` (a massive
spurious whole-file diff); on POSIX the mirror image, editing a CRLF file
stripped it to LF. The fix (``_newlines.py`` + the wiring in edit.py/write.py)
reads and writes bytes explicitly, detecting and restoring the file's on-disk
convention.

Teeth by platform:
- ``test_edit_preserves_crlf`` has teeth on **Linux** (the old code stripped
  CRLF->LF there, because ``os.linesep`` is ``\\n``).
- ``test_edit_preserves_lf`` has teeth on **Windows** (the old code converted
  LF->CRLF there, because ``os.linesep`` is ``\\r\\n``).
"""

from pathlib import Path

import pytest
from amplifier_module_tool_filesystem._newlines import (
    detect_newline,
    read_text_preserving,
    write_text_preserving,
)
from amplifier_module_tool_filesystem.edit import EditTool
from amplifier_module_tool_filesystem.write import WriteTool


class _StubHooks:
    async def emit(self, *args, **kwargs):
        return None


class _StubCoordinator:
    def __init__(self):
        self.hooks = _StubHooks()

    def get_capability(self, name):
        return None


def _tool(cls, tmp_path: Path):
    return cls(
        {"working_dir": str(tmp_path), "allowed_write_paths": [str(tmp_path)]},
        _StubCoordinator(),
    )


# --------------------------------------------------------------------------
# Unit tests of the _newlines helpers
# --------------------------------------------------------------------------


def test_detect_newline():
    assert detect_newline("a\r\nb") == "\r\n"
    assert detect_newline("a\rb") == "\r"
    assert detect_newline("a\nb") == "\n"
    assert detect_newline("no line breaks at all") == "\n"


def test_write_preserving_lf_is_byte_identical(tmp_path):
    # Dominant case: LF content + default newline -> LF bytes on EVERY platform.
    p = tmp_path / "f.txt"
    n = write_text_preserving(p, "a\nb\nc\n")
    assert p.read_bytes() == b"a\nb\nc\n"
    assert n == 6


def test_write_preserving_restores_crlf(tmp_path):
    p = tmp_path / "f.txt"
    write_text_preserving(p, "a\nb\nc\n", "\r\n")
    assert p.read_bytes() == b"a\r\nb\r\nc\r\n"


def test_write_preserving_no_crlf_doubling(tmp_path):
    # Stray CRLF already in the string must not double to \r\r\n when restoring.
    p = tmp_path / "f.txt"
    write_text_preserving(p, "a\r\nb\n", "\r\n")
    assert p.read_bytes() == b"a\r\nb\r\n"


def test_read_preserving_detects_and_normalizes(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"a\r\nb\r\n")
    text, newline = read_text_preserving(p)
    assert text == "a\nb\n"  # normalized to LF for matching
    assert newline == "\r\n"  # original convention preserved for restore


# --------------------------------------------------------------------------
# End-to-end through the real tools
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_preserves_crlf(tmp_path):
    """edit_file on a CRLF file keeps CRLF. Teeth on Linux (old code stripped)."""
    f = tmp_path / "crlf.txt"
    f.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
    res = await _tool(EditTool, tmp_path).execute(
        {"file_path": str(f), "old_string": "beta", "new_string": "BETA"}
    )
    assert res.success, res
    raw = f.read_bytes()
    assert raw == b"alpha\r\nBETA\r\ngamma\r\n"
    # Every LF is part of a CRLF pair -- no bare LF was introduced.
    assert raw.count(b"\n") == raw.count(b"\r\n")


@pytest.mark.asyncio
async def test_edit_preserves_lf(tmp_path):
    """edit_file on an LF file keeps LF. Teeth on Windows (old code -> CRLF)."""
    f = tmp_path / "lf.txt"
    f.write_bytes(b"alpha\nbeta\ngamma\n")
    res = await _tool(EditTool, tmp_path).execute(
        {"file_path": str(f), "old_string": "beta", "new_string": "BETA"}
    )
    assert res.success, res
    raw = f.read_bytes()
    assert raw == b"alpha\nBETA\ngamma\n"
    assert b"\r" not in raw  # no CR introduced


@pytest.mark.asyncio
async def test_write_preserves_existing_crlf_on_overwrite(tmp_path):
    """write_file over an existing CRLF file keeps CRLF."""
    f = tmp_path / "crlf.txt"
    f.write_bytes(b"old\r\ncontent\r\n")
    res = await _tool(WriteTool, tmp_path).execute(
        {"file_path": str(f), "content": "new\nstuff\n"}
    )
    assert res.success, res
    assert f.read_bytes() == b"new\r\nstuff\r\n"


@pytest.mark.asyncio
async def test_write_new_file_is_lf(tmp_path):
    """A brand-new write_file uses LF exactly as given (no os.linesep on Windows)."""
    f = tmp_path / "new.txt"
    res = await _tool(WriteTool, tmp_path).execute(
        {"file_path": str(f), "content": "a\nb\n"}
    )
    assert res.success, res
    assert f.read_bytes() == b"a\nb\n"

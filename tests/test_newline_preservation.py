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


# --------------------------------------------------------------------------
# Mixed-ending files: dominance must be by count, not first appearance
# --------------------------------------------------------------------------


def test_detect_newline_is_by_count_not_first_appearance():
    """A mostly-LF file with a stray CRLF is an LF file.

    First-appearance detection would call this CRLF and reflow every line on
    the next edit -- the exact whole-file diff this module exists to prevent.
    """
    mostly_lf = "a\r\n" + "b\n" * 999
    assert detect_newline(mostly_lf) == "\n"

    mostly_crlf = "a\n" + "b\r\n" * 999
    assert detect_newline(mostly_crlf) == "\r\n"

    # Bare CR (classic Mac) only wins when it actually dominates.
    assert detect_newline("a\rb\rc\nd") == "\r"
    assert detect_newline("a\rb\nc\nd") == "\n"


def test_write_preserving_lf_writes_verbatim(tmp_path):
    """newline='\\n' must not strip CR bytes the caller deliberately supplied."""
    p = tmp_path / "fixture.http"
    n = write_text_preserving(p, "GET / HTTP/1.1\r\nHost: x\r\n\r\nbody\n")
    assert p.read_bytes() == b"GET / HTTP/1.1\r\nHost: x\r\n\r\nbody\n"
    assert n == len(b"GET / HTTP/1.1\r\nHost: x\r\n\r\nbody\n")


@pytest.mark.asyncio
async def test_edit_mostly_lf_file_does_not_reflow_to_crlf(tmp_path):
    """One stray CRLF must not flip the whole file to CRLF.

    Note the residual, deliberate limitation: these helpers normalize for
    matching and restore ONE convention, so a mixed file converges to its
    dominant ending -- the stray CRLF here becomes LF. That is a 1-line diff
    that heals the inconsistency. Before count-based dominance it was the
    opposite and far worse: all 51 LF lines were rewritten to CRLF. Fully
    byte-preserving mixed files would require splicing into the raw text by
    offset, which is not worth the machinery for already-pathological files.
    """
    f = tmp_path / "mixed.txt"
    before = b"alpha\r\n" + b"".join(b"line%d\n" % i for i in range(50)) + b"beta\n"
    f.write_bytes(before)

    res = await _tool(EditTool, tmp_path).execute(
        {"file_path": str(f), "old_string": "beta", "new_string": "BETA"}
    )
    assert res.success, res

    after = f.read_bytes()
    # The 51 untouched LF lines stayed LF -- no whole-file reflow to CRLF.
    assert b"\r" not in after
    assert after == before.replace(b"beta\n", b"BETA\n").replace(b"\r\n", b"\n")
    # Blast radius: one stray CR normalized, not 51 lines rewritten.
    assert after.count(b"\n") == before.count(b"\n")


@pytest.mark.asyncio
async def test_write_new_file_preserves_caller_crlf(tmp_path):
    """write_file to a NEW file writes content verbatim, CR bytes included."""
    f = tmp_path / "fixture.http"
    res = await _tool(WriteTool, tmp_path).execute(
        {"file_path": str(f), "content": "GET / HTTP/1.1\r\nHost: x\r\n"}
    )
    assert res.success, res
    assert f.read_bytes() == b"GET / HTTP/1.1\r\nHost: x\r\n"

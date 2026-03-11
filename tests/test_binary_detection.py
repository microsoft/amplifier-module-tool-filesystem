"""Tests for binary file detection in ReadTool.

Verifies that binary files return metadata instead of crashing,
and that text files (UTF-8 and non-UTF-8) are handled gracefully.
"""

import pytest

from amplifier_module_tool_filesystem.read import _is_binary


@pytest.fixture
def binary_file(tmp_path):
    """Create a binary file with null bytes."""
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 100)
    return f


@pytest.fixture
def utf8_file(tmp_path):
    """Create a normal UTF-8 text file."""
    f = tmp_path / "hello.py"
    f.write_text("print('hello world')\n", encoding="utf-8")
    return f


@pytest.fixture
def latin1_file(tmp_path):
    """Create a non-UTF-8 text file (ISO-8859-1)."""
    f = tmp_path / "legacy.txt"
    # \xe9 is 'e-acute' in latin-1, not valid standalone UTF-8
    f.write_bytes(b"caf\xe9 au lait\n")
    return f


class TestIsBinary:
    """Verify the _is_binary detection function."""

    def test_binary_file_detected(self, binary_file):
        """A file with null bytes must be detected as binary."""
        assert _is_binary(binary_file) is True

    def test_text_file_not_binary(self, utf8_file):
        """A normal text file must NOT be detected as binary."""
        assert _is_binary(utf8_file) is False

    def test_latin1_file_not_binary(self, latin1_file):
        """A non-UTF-8 text file without null bytes is NOT binary."""
        assert _is_binary(latin1_file) is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        """A nonexistent file should return False (not crash)."""
        assert _is_binary(tmp_path / "nope.bin") is False

    def test_empty_file_not_binary(self, tmp_path):
        """An empty file should not be detected as binary."""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        assert _is_binary(f) is False

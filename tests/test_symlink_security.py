"""Tests for symlink security in path validation.

Verifies that symlinks inside allowed directories pointing outside
are blocked, while symlinks pointing inside are permitted.
"""

import pytest

from amplifier_module_tool_filesystem.path_validation import is_path_allowed


@pytest.fixture
def allowed_dir(tmp_path):
    """Create a temporary allowed directory with a test file."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "safe.txt").write_text("safe content")
    return allowed


@pytest.fixture
def outside_dir(tmp_path):
    """Create a directory outside the allowed path."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret content")
    return outside


class TestSymlinkSecurity:
    """Verify symlinks are resolved before path validation."""

    def test_symlink_escaping_allowed_dir_is_blocked(self, allowed_dir, outside_dir):
        """A symlink inside allowed/ pointing to outside/ must be DENIED."""
        symlink_path = allowed_dir / "escape"
        symlink_path.symlink_to(outside_dir / "secret.txt")

        allowed, error = is_path_allowed(
            symlink_path,
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )
        assert allowed is False, (
            f"Symlink {symlink_path} -> {outside_dir / 'secret.txt'} "
            f"should be DENIED but was allowed. Error: {error}"
        )

    def test_symlink_within_allowed_dir_is_permitted(self, allowed_dir):
        """A symlink inside allowed/ pointing to another file inside allowed/ is OK."""
        symlink_path = allowed_dir / "link"
        symlink_path.symlink_to(allowed_dir / "safe.txt")

        allowed, error = is_path_allowed(
            symlink_path,
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )
        assert allowed is True, (
            f"Symlink {symlink_path} -> {allowed_dir / 'safe.txt'} "
            f"should be ALLOWED but was denied: {error}"
        )

    def test_regular_file_in_allowed_dir_unchanged(self, allowed_dir):
        """Non-symlink files must continue to work normally."""
        regular_file = allowed_dir / "safe.txt"

        allowed, error = is_path_allowed(
            regular_file,
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )
        assert allowed is True, f"Regular file should be allowed: {error}"

    def test_symlink_chain_is_fully_resolved(self, allowed_dir, outside_dir):
        """A chain of symlinks must be fully resolved to the final target."""
        (allowed_dir / "link2").symlink_to(outside_dir / "secret.txt")
        (allowed_dir / "link1").symlink_to(allowed_dir / "link2")

        allowed, error = is_path_allowed(
            allowed_dir / "link1",
            allowed_paths=[str(allowed_dir)],
            denied_paths=[],
        )
        assert allowed is False, "Symlink chain escaping allowed dir should be denied"

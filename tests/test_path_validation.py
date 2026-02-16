"""Tests for path validation with tilde expansion.

Verifies that is_in_path_list() correctly handles paths containing ~
in the path_list entries.
"""

from pathlib import Path

from amplifier_module_tool_filesystem.path_validation import is_in_path_list


def test_is_in_path_list_expands_tilde_in_path_list():
    """is_in_path_list should match when path_list contains ~ entries.

    Bug: Path(p).resolve() does NOT expand ~, so a deny rule like
    '~/sensitive' never matches /home/user/sensitive. Adding
    .expanduser() before .resolve() fixes this.
    """
    home = Path.home()
    # Target is a resolved absolute path under $HOME
    target = home / "sensitive" / "secret.txt"

    # path_list uses tilde notation — the common way users configure deny rules
    path_list = ["~/sensitive"]

    assert is_in_path_list(target, path_list), (
        "is_in_path_list should match ~/sensitive against "
        f"{target} but it did not — tilde was not expanded"
    )

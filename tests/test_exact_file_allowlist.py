"""Tests for the equality-only `allowed_write_files` exact-file allow-list.

Two layers of coverage:
  1. Path-level tests against `is_exact_file_allowed()` / `is_path_allowed()`
     directly (fast, no I/O beyond what Path.resolve() itself touches).
  2. Behavioral tests against the real WriteTool/EditTool, exercising the
     full config -> _check_write_access -> execute() path with real files.

See README.md "Exact-file grants (allowed_write_files)" for the contract
this file is pinning: equality-only matching, deny-always-wins, non-strict
resolve() (so brand-new files work), symlink-leaf resolution, tilde
expansion, and full backward compatibility when the option is omitted.
"""

from pathlib import Path

import pytest

from amplifier_module_tool_filesystem.edit import EditTool
from amplifier_module_tool_filesystem.path_validation import (
    is_exact_file_allowed,
    is_path_allowed,
)
from amplifier_module_tool_filesystem.write import WriteTool


class _StubHooks:
    async def emit(self, *args, **kwargs):
        return None


class _StubCoordinator:
    def __init__(self):
        self.hooks = _StubHooks()

    def get_capability(self, name):
        return None


def _tool(cls, config: dict):
    return cls(config, _StubCoordinator())


# ---------------------------------------------------------------------------
# Path-level tests: is_exact_file_allowed()
# ---------------------------------------------------------------------------


def test_exact_file_allowed_matches_configured_file(tmp_path):
    target = tmp_path / "logs" / "NodeA" / "status.json"
    assert is_exact_file_allowed(target, [str(target)])


def test_exact_file_allowed_works_for_nonexistent_target_and_missing_parent(tmp_path):
    """A brand-new file whose parent directory doesn't exist yet must match.

    This is the primary use case: an engine authorizing a status file it is
    about to write for the first time, in a directory that doesn't exist yet.
    """
    target = tmp_path / "logs" / "NodeA" / "status.json"
    assert not target.parent.exists()
    assert is_exact_file_allowed(target, [str(target)])


def test_exact_file_allowed_denies_descendant(tmp_path):
    """Listing a file must not authorize treating it as a directory."""
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    descendant = exact / "child"
    assert not is_exact_file_allowed(descendant, [str(exact)])


def test_exact_file_allowed_denies_sibling(tmp_path):
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    sibling = exact.parent / "other.json"
    assert not is_exact_file_allowed(sibling, [str(exact)])


def test_exact_file_allowed_denies_parent_directory(tmp_path):
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    parent = exact.parent
    assert not is_exact_file_allowed(parent, [str(exact)])


def test_exact_file_allowed_denies_unrelated_file(tmp_path):
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    other = tmp_path / "elsewhere" / "status.json"
    assert not is_exact_file_allowed(other, [str(exact)])


def test_exact_file_allowed_expands_tilde_in_file_list():
    home = Path.home()
    target = home / "exact-file-allowlist-test" / "status.json"
    assert is_exact_file_allowed(target, ["~/exact-file-allowlist-test/status.json"])


def test_exact_file_allowed_empty_list_denies_everything(tmp_path):
    target = tmp_path / "status.json"
    assert not is_exact_file_allowed(target, [])


def test_exact_file_allowed_symlink_leaf_on_target_side(tmp_path):
    """A symlink AT the write-target leaf resolves to its real target."""
    real = tmp_path / "real_status.json"
    real.write_text("{}")
    link = tmp_path / "status.json"
    link.symlink_to(real)

    # Configured entry is the REAL path; the target passed in is the symlink.
    assert is_exact_file_allowed(link, [str(real)])


def test_exact_file_allowed_symlink_leaf_on_configured_entry_side(tmp_path):
    """A symlink in the CONFIGURED entry resolves to its real target too."""
    real = tmp_path / "real_status.json"
    real.write_text("{}")
    link = tmp_path / "status.json"
    link.symlink_to(real)

    # Configured entry is the symlink; the target passed in is the real path.
    assert is_exact_file_allowed(real, [str(link)])


# ---------------------------------------------------------------------------
# Path-level tests: is_path_allowed() combined semantics
# ---------------------------------------------------------------------------


def test_is_path_allowed_grants_via_allowed_files_outside_allowed_paths(tmp_path):
    workspace = tmp_path / "workspace"
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    allowed, err = is_path_allowed(
        exact,
        allowed_paths=[str(workspace)],
        denied_paths=[],
        allowed_files=[str(exact)],
    )
    assert allowed, err


def test_is_path_allowed_denies_sibling_of_exact_file_outside_allowed_paths(tmp_path):
    workspace = tmp_path / "workspace"
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    sibling = exact.parent / "other.json"
    allowed, err = is_path_allowed(
        sibling,
        allowed_paths=[str(workspace)],
        denied_paths=[],
        allowed_files=[str(exact)],
    )
    assert not allowed
    assert err


def test_is_path_allowed_denied_paths_wins_over_allowed_files(tmp_path):
    """Deny always wins, even when the exact file is separately granted."""
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    allowed, err = is_path_allowed(
        exact,
        allowed_paths=[],
        denied_paths=[str(exact.parent)],
        allowed_files=[str(exact)],
    )
    assert not allowed
    assert "denied" in err.lower()


def test_is_path_allowed_denied_paths_wins_when_exact_file_itself_denied(tmp_path):
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    allowed, err = is_path_allowed(
        exact,
        allowed_paths=[],
        denied_paths=[str(exact)],
        allowed_files=[str(exact)],
    )
    assert not allowed
    assert "denied" in err.lower()


def test_is_path_allowed_allowed_files_omitted_is_backward_compatible(tmp_path):
    """Omitting allowed_files (None) must behave exactly as before this option."""
    workspace = tmp_path / "workspace"
    inside = workspace / "file.txt"
    outside = tmp_path / "elsewhere" / "file.txt"

    allowed_inside, _ = is_path_allowed(inside, [str(workspace)], [])
    assert allowed_inside

    allowed_outside, err = is_path_allowed(outside, [str(workspace)], [])
    assert not allowed_outside
    assert err


def test_is_path_allowed_allowed_files_empty_list_is_backward_compatible(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "elsewhere" / "file.txt"
    allowed, err = is_path_allowed(outside, [str(workspace)], [], allowed_files=[])
    assert not allowed
    assert err


def test_is_path_allowed_combined_grants_both_paths_and_files(tmp_path):
    """A config combining a directory grant and an exact-file grant honors both."""
    workspace = tmp_path / "workspace"
    exact = tmp_path / "logs" / "NodeA" / "status.json"

    inside_workspace = workspace / "src" / "app.py"
    allowed_via_paths, err1 = is_path_allowed(
        inside_workspace,
        allowed_paths=[str(workspace)],
        denied_paths=[],
        allowed_files=[str(exact)],
    )
    assert allowed_via_paths, err1

    allowed_via_files, err2 = is_path_allowed(
        exact,
        allowed_paths=[str(workspace)],
        denied_paths=[],
        allowed_files=[str(exact)],
    )
    assert allowed_via_files, err2

    unrelated = tmp_path / "other" / "secret.txt"
    allowed_unrelated, err3 = is_path_allowed(
        unrelated,
        allowed_paths=[str(workspace)],
        denied_paths=[],
        allowed_files=[str(exact)],
    )
    assert not allowed_unrelated
    assert err3


# ---------------------------------------------------------------------------
# Behavioral tests: real WriteTool / EditTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_new_file_via_exact_file_grant_with_missing_parent(tmp_path):
    """WriteTool creates a brand-new file (missing parent dir) authorized
    ONLY via allowed_write_files, not allowed_write_paths."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    assert not exact.parent.exists()

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )
    res = await tool.execute(
        {"file_path": str(exact), "content": '{"outcome": "success"}\n'}
    )
    assert res.success, res
    assert exact.read_text() == '{"outcome": "success"}\n'


@pytest.mark.asyncio
async def test_write_exact_file_success_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    exact.parent.mkdir(parents=True)

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )
    res = await tool.execute({"file_path": str(exact), "content": "hello"})
    assert res.success, res
    assert exact.read_text() == "hello"


@pytest.mark.asyncio
async def test_write_nested_descendant_of_exact_file_denied(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )
    nested = exact / "child.txt"
    res = await tool.execute({"file_path": str(nested), "content": "x"})
    assert not res.success
    assert not nested.exists()


@pytest.mark.asyncio
async def test_write_sibling_of_exact_file_denied(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    exact.parent.mkdir(parents=True)

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )
    sibling = exact.parent / "other.json"
    res = await tool.execute({"file_path": str(sibling), "content": "x"})
    assert not res.success
    assert not sibling.exists()


@pytest.mark.asyncio
async def test_edit_exact_file_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    exact.parent.mkdir(parents=True)
    exact.write_text('{"outcome": "fail"}\n')

    tool = _tool(
        EditTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )
    res = await tool.execute(
        {
            "file_path": str(exact),
            "old_string": '"fail"',
            "new_string": '"success"',
        }
    )
    assert res.success, res
    assert exact.read_text() == '{"outcome": "success"}\n'


@pytest.mark.asyncio
async def test_edit_sibling_of_exact_file_denied(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    exact.parent.mkdir(parents=True)
    exact.write_text("{}")
    sibling = exact.parent / "other.json"
    sibling.write_text("{}")

    tool = _tool(
        EditTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )
    res = await tool.execute(
        {"file_path": str(sibling), "old_string": "{}", "new_string": "{1}"}
    )
    assert not res.success
    assert sibling.read_text() == "{}"


@pytest.mark.asyncio
async def test_write_deny_precedence_over_exact_file_grant(tmp_path):
    """denied_write_paths blocks the exact file even though allowed_write_files
    separately authorizes it -- deny always wins."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    exact.parent.mkdir(parents=True)

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
            "denied_write_paths": [str(exact.parent)],
        },
    )
    res = await tool.execute({"file_path": str(exact), "content": "x"})
    assert not res.success
    assert not exact.exists()


@pytest.mark.asyncio
async def test_write_symlink_leaf_resolution_real_tool(tmp_path):
    """A directory symlink between workspace and the exact-file target
    resolves to the same real path on both sides, so the grant still
    applies through the real WriteTool."""
    real_logs = tmp_path / "real_logs"
    real_logs.mkdir()
    exact_real = real_logs / "NodeA" / "status.json"
    exact_real.parent.mkdir()

    logs_link = tmp_path / "logs"
    logs_link.symlink_to(real_logs)
    exact_via_link = logs_link / "NodeA" / "status.json"

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            # Configured entry uses the REAL path; write target goes through
            # the symlinked directory -- both resolve to the same file.
            "allowed_write_files": [str(exact_real)],
        },
    )
    res = await tool.execute({"file_path": str(exact_via_link), "content": "ok"})
    assert res.success, res
    assert exact_real.read_text() == "ok"


@pytest.mark.asyncio
async def test_write_tilde_in_allowed_write_files(tmp_path, monkeypatch):
    """allowed_write_files entries expand ~ the same way allowed_write_paths
    already does (see test_path_validation.py)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "sensitive" / "status.json"
    exact.parent.mkdir()

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": ["~/sensitive/status.json"],
        },
    )
    res = await tool.execute({"file_path": str(exact), "content": "tilde-ok"})
    assert res.success, res
    assert exact.read_text() == "tilde-ok"


@pytest.mark.asyncio
async def test_write_allowed_write_files_omitted_is_backward_compatible(tmp_path):
    """A config that never mentions allowed_write_files behaves exactly as
    it did before this option existed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = _tool(
        WriteTool,
        {"working_dir": str(workspace), "allowed_write_paths": [str(workspace)]},
    )
    assert tool.allowed_write_files == []

    inside = workspace / "file.txt"
    res_inside = await tool.execute({"file_path": str(inside), "content": "ok"})
    assert res_inside.success, res_inside

    outside = tmp_path / "elsewhere" / "file.txt"
    res_outside = await tool.execute({"file_path": str(outside), "content": "no"})
    assert not res_outside.success
    assert not outside.exists()


@pytest.mark.asyncio
async def test_write_allowed_write_files_empty_is_backward_compatible(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [],
        },
    )
    outside = tmp_path / "elsewhere" / "file.txt"
    res_outside = await tool.execute({"file_path": str(outside), "content": "no"})
    assert not res_outside.success
    assert not outside.exists()


@pytest.mark.asyncio
async def test_write_combined_path_and_file_grants_real_tool(tmp_path):
    """One config combining allowed_write_paths and allowed_write_files
    honors both grants and denies everything else, end to end."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    exact = tmp_path / "logs" / "NodeA" / "status.json"
    exact.parent.mkdir(parents=True)

    tool = _tool(
        WriteTool,
        {
            "working_dir": str(workspace),
            "allowed_write_paths": [str(workspace)],
            "allowed_write_files": [str(exact)],
        },
    )

    # 1. Normal workspace write via allowed_write_paths.
    inside = workspace / "src" / "app.py"
    res1 = await tool.execute({"file_path": str(inside), "content": "code"})
    assert res1.success, res1

    # 2. Exact status file via allowed_write_files, outside the workspace.
    res2 = await tool.execute(
        {"file_path": str(exact), "content": '{"outcome":"success"}'}
    )
    assert res2.success, res2

    # 3. A sibling of the exact file, still outside the workspace: denied.
    sibling = exact.parent / "other.json"
    res3 = await tool.execute({"file_path": str(sibling), "content": "x"})
    assert not res3.success
    assert not sibling.exists()

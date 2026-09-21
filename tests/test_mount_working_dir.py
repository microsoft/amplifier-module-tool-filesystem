"""Session working directories must not leak through reused module config."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from amplifier_core.coordinator import ModuleCoordinator

from amplifier_module_tool_filesystem import mount


def coordinator(workspace):
    result = ModuleCoordinator(
        SimpleNamespace(session_id=workspace.name, parent_id=None, config={})
    )
    result.register_capability("session.working_dir", str(workspace))
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"allowed_read_paths": None}])
async def test_reused_config_keeps_relative_file_operations_in_each_session(
    tmp_path, config
):
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    (parent / "marker.txt").write_text("parent")
    (child / "marker.txt").write_text("child")
    before = deepcopy(config)
    parent_coordinator = coordinator(parent)
    child_coordinator = coordinator(child)
    await mount(parent_coordinator, config)
    await mount(child_coordinator, config)

    tools = child_coordinator.get("tools")
    read = await tools["read_file"].execute({"file_path": "marker.txt"})
    assert read.success and "child" in read.output["content"]
    write = await tools["write_file"].execute(
        {"file_path": "result.txt", "content": "before"}
    )
    assert write.success
    edit = await tools["edit_file"].execute(
        {"file_path": "result.txt", "old_string": "before", "new_string": "after"}
    )
    assert edit.success
    assert (child / "result.txt").read_text() == "after"
    assert not (parent / "result.txt").exists()

    # The child's default write scope must also be its own directory.
    denied = await tools["write_file"].execute(
        {"file_path": str(parent / "outside.txt"), "content": "not allowed"}
    )
    assert not denied.success
    assert not (parent / "outside.txt").exists()
    assert config == before
    assert all(
        tool.working_dir == str(parent)
        for tool in parent_coordinator.get("tools").values()
    )


@pytest.mark.asyncio
async def test_explicit_working_dir_keeps_precedence_without_mutating_config(tmp_path):
    declared = tmp_path / "declared"
    session_workspace = tmp_path / "session"
    declared.mkdir()
    session_workspace.mkdir()
    config = {
        "working_dir": str(declared),
        "denied_write_paths": [str(declared / "blocked")],
    }
    before = deepcopy(config)
    host = coordinator(session_workspace)
    await mount(host, config)

    tool = host.get("tools")["write_file"]
    assert tool.working_dir == str(declared)
    allowed = await tool.execute({"file_path": "allowed.txt", "content": "allowed"})
    denied = await tool.execute({"file_path": "blocked/file.txt", "content": "denied"})
    assert allowed.success and not denied.success
    assert (declared / "allowed.txt").exists()
    assert not (session_workspace / "allowed.txt").exists()
    assert not (declared / "blocked/file.txt").exists()
    assert config == before

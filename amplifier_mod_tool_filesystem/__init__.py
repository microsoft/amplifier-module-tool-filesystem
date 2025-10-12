"""
Filesystem tools with artifact events.
"""

import logging
from pathlib import Path
from typing import Any
from typing import Optional

from amplifier_core import ModuleCoordinator
from amplifier_core import ToolResult
from amplifier_core.events import ARTIFACT_READ
from amplifier_core.events import ARTIFACT_WRITE

logger = logging.getLogger(__name__)


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None):
    config = config or {}
    tools = [
        ReadTool(config, coordinator),
        WriteTool(config, coordinator),
        EditTool(config, coordinator),
    ]
    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
    logger.info("Mounted filesystem tools (desired-state)")
    return


class BaseFsTool:
    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        self.config = config
        self.allowed_paths = config.get("allowed_paths", ["."])
        self.hooks = coordinator.hooks

    def _is_allowed(self, path: Path) -> bool:
        return any(
            Path(ap).resolve() in path.resolve().parents or Path(ap).resolve() == path.resolve()
            for ap in self.allowed_paths
        )


class ReadTool(BaseFsTool):
    name = "read_file"
    description = "Read a file"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        p = Path(input.get("path", ""))
        if not p:
            return ToolResult(success=False, error={"message": "path required"})
        if not self._is_allowed(p):
            return ToolResult(success=False, error={"message": "path not allowed"})
        try:
            data = p.read_text(encoding="utf-8")
            await self.hooks.emit(ARTIFACT_READ, {"data": {"path": str(p), "bytes": len(data.encode("utf-8"))}})
            return ToolResult(success=True, data={"path": str(p), "content": data})
        except Exception as e:
            return ToolResult(success=False, error={"type": type(e).__name__, "message": str(e)})


class WriteTool(BaseFsTool):
    name = "write_file"
    description = "Write a file"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        p = Path(input.get("path", ""))
        content = input.get("content", "")
        if not p:
            return ToolResult(success=False, error={"message": "path required"})
        if not self._is_allowed(p):
            return ToolResult(success=False, error={"message": "path not allowed"})
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        await self.hooks.emit(ARTIFACT_WRITE, {"data": {"path": str(p), "bytes": len(content.encode("utf-8"))}})
        return ToolResult(success=True, data={"path": str(p), "bytes": len(content.encode("utf-8"))})


class EditTool(BaseFsTool):
    name = "edit_file"
    description = "Edit a file by appending content"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}, "append": {"type": "string"}},
            "required": ["path", "append"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        p = Path(input.get("path", ""))
        patch = input.get("append", "")
        if not p.exists():
            return ToolResult(success=False, error={"message": "file does not exist"})
        if not self._is_allowed(p):
            return ToolResult(success=False, error={"message": "path not allowed"})
        with p.open("a", encoding="utf-8") as f:
            f.write(patch)
        await self.hooks.emit(ARTIFACT_WRITE, {"data": {"path": str(p), "bytes": len(patch.encode("utf-8"))}})
        return ToolResult(success=True, data={"path": str(p), "appended": len(patch.encode("utf-8"))})

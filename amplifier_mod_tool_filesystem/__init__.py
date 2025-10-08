"""
Filesystem tool module.
Provides basic file operations: read, write, edit.
"""

import logging
from pathlib import Path
from typing import Any
from typing import Optional

from amplifier_core import ModuleCoordinator
from amplifier_core import ToolResult

logger = logging.getLogger(__name__)


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None):
    """Mount filesystem tools."""
    config = config or {}

    tools = [
        ReadTool(config),
        WriteTool(config),
        EditTool(config),
    ]

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)

    logger.info(f"Mounted {len(tools)} filesystem tools")
    return


class ReadTool:
    """Read file contents."""

    name = "read"
    description = "Read the contents of a file"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.allowed_paths = config.get("allowed_paths", ["."])

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to the file to read"}},
            "required": ["path"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Read a file."""
        path = input.get("path")
        if not path:
            return ToolResult(success=False, error={"message": "Path is required"})

        try:
            file_path = Path(path)

            # Basic safety check
            if not any(file_path.is_relative_to(allowed) for allowed in self.allowed_paths):
                return ToolResult(success=False, error={"message": f"Access denied to {path}"})

            if not file_path.exists():
                return ToolResult(success=False, error={"message": f"File not found: {path}"})

            content = file_path.read_text()
            return ToolResult(success=True, output=content)

        except Exception as e:
            logger.error(f"Error reading file: {e}")
            return ToolResult(success=False, error={"message": str(e)})


class WriteTool:
    """Write file contents."""

    name = "write"
    description = "Write content to a file"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.allowed_paths = config.get("allowed_paths", ["."])
        self.require_approval = config.get("require_approval", True)

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Write to a file."""
        path = input.get("path")
        content = input.get("content")

        if not path or content is None:
            return ToolResult(success=False, error={"message": "Path and content are required"})

        try:
            file_path = Path(path)

            # Basic safety check
            if not any(file_path.is_relative_to(allowed) for allowed in self.allowed_paths):
                return ToolResult(success=False, error={"message": f"Access denied to {path}"})

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write the file
            file_path.write_text(content)

            return ToolResult(success=True, output=f"Wrote {len(content)} characters to {path}")

        except Exception as e:
            logger.error(f"Error writing file: {e}")
            return ToolResult(success=False, error={"message": str(e)})


class EditTool:
    """Edit file contents with diff-based changes."""

    name = "edit"
    description = "Edit a file with line-based replacements"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.allowed_paths = config.get("allowed_paths", ["."])
        self.show_diff = config.get("show_diff", True)

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old_text": {"type": "string", "description": "Text to replace (must be unique in file)"},
                "new_text": {"type": "string", "description": "Text to replace old_text with"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Edit a file with replacements."""
        path = input.get("path")
        old_text = input.get("old_text", "")
        new_text = input.get("new_text", "")

        if not path:
            return ToolResult(success=False, error={"message": "Path is required"})

        try:
            file_path = Path(path)

            # Basic safety check
            if not any(file_path.is_relative_to(allowed) for allowed in self.allowed_paths):
                return ToolResult(success=False, error={"message": f"Access denied to {path}"})

            if not file_path.exists():
                return ToolResult(success=False, error={"message": f"File not found: {path}"})

            # Read current content
            content = file_path.read_text()

            # Check if old_text exists in file
            if old_text not in content:
                return ToolResult(success=False, error={"message": "Old text not found in file"})

            # Count occurrences
            occurrences = content.count(old_text)
            if occurrences > 1:
                return ToolResult(
                    success=False, error={"message": f"Old text appears {occurrences} times. Must be unique."}
                )

            # Perform replacement
            new_content = content.replace(old_text, new_text, 1)

            # Generate diff for display
            if self.show_diff:
                diff = self._generate_diff(content, new_content, path)
            else:
                diff = None

            # Write the file
            file_path.write_text(new_content)

            result_message = f"Edited {path}"
            if diff:
                result_message += f"\n\nDiff:\n{diff}"

            return ToolResult(success=True, output=result_message)

        except Exception as e:
            logger.error(f"Error editing file: {e}")
            return ToolResult(success=False, error={"message": str(e)})

    def _generate_diff(self, old_content: str, new_content: str, filename: str) -> str:
        """Generate a simple diff display."""
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        # Simple line-by-line diff
        diff_lines = []
        diff_lines.append(f"--- {filename}")
        diff_lines.append(f"+++ {filename}")

        # This is a simplified diff - real implementation would use difflib
        import difflib

        differ = difflib.unified_diff(old_lines, new_lines, lineterm="", n=3)

        # Skip the first two lines (filenames) as we already added them
        diff_iter = iter(differ)
        next(diff_iter, None)
        next(diff_iter, None)

        for line in diff_iter:
            diff_lines.append(line)

        return "\n".join(diff_lines) if len(diff_lines) > 2 else "No changes"

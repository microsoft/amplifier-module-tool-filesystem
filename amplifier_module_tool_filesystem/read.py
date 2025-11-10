"""ReadTool - Read files from the local filesystem."""

from pathlib import Path
from typing import Any

from amplifier_core import ModuleCoordinator
from amplifier_core import ToolResult
from amplifier_core.events import ARTIFACT_READ


class ReadTool:
    """Read files from the local filesystem with line numbering and pagination support."""

    name = "read_file"
    description = """
Reads a file from the local filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- This tool can only read files, not directories. To read a directory, use an ls command via the bash tool.
- You can call multiple tools in a single response. It is always better to speculatively read multiple potentially useful files in parallel.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
    """

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize ReadTool with configuration."""
        self.config = config
        self.allowed_paths = config.get("allowed_paths", ["."])
        self.coordinator = coordinator
        self.max_line_length = 2000
        self.default_line_limit = 2000

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "The line number to start reading from (1-indexed). Only provide if the file is too large to read at once",
                },
                "limit": {
                    "type": "integer",
                    "description": "The number of lines to read. Only provide if the file is too large to read at once.",
                },
            },
            "required": ["file_path"],
        }

    def _is_allowed(self, path: Path) -> bool:
        """Check if path is within allowed paths."""
        resolved_path = path.resolve()
        for allowed in self.allowed_paths:
            allowed_resolved = Path(allowed).resolve()
            if allowed_resolved in resolved_path.parents or allowed_resolved == resolved_path:
                return True
        return False

    def _format_with_line_numbers(self, lines: list[str], start_line: int) -> str:
        """Format lines with line numbers in cat -n style."""
        formatted_lines = []
        for i, line in enumerate(lines, start=start_line):
            # Truncate long lines
            if len(line) > self.max_line_length:
                line = line[: self.max_line_length] + "... [truncated]"
            # Format: right-aligned line number with minimum width of 6, tab, then content
            formatted_lines.append(f"{i:6d}\t{line}")
        return "\n".join(formatted_lines)

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """
        Read a file from the filesystem.

        Args:
            input: {
                "file_path": str - The absolute path to the file to read
                "offset": Optional[int] - Line number to start reading from (1-indexed)
                "limit": Optional[int] - Number of lines to read
            }

        Returns:
            ToolResult with formatted file content including line numbers
        """
        file_path = input.get("file_path", "")
        offset = input.get("offset", 1)  # Default to line 1
        limit = input.get("limit", self.default_line_limit)

        if not file_path:
            return ToolResult(success=False, error={"message": "file_path is required"})

        path = Path(file_path)

        # Check if path is allowed
        if not self._is_allowed(path):
            return ToolResult(
                success=False, error={"message": f"Access denied: {file_path} is not within allowed paths"}
            )

        # Check if file exists
        if not path.exists():
            return ToolResult(success=False, error={"message": f"File not found: {file_path}"})

        # Check if it's a directory
        if path.is_dir():
            return ToolResult(
                success=False,
                error={"message": f"Cannot read directory: {file_path}. Use ls command via bash tool for directories."},
            )

        try:
            # Read file content
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()

            # Handle offset and limit (convert to 0-indexed)
            start_idx = max(0, offset - 1)
            end_idx = start_idx + limit

            # Get the requested slice
            selected_lines = lines[start_idx:end_idx]

            # Format with line numbers
            formatted_content = self._format_with_line_numbers(selected_lines, start_line=offset)

            # Emit artifact read event
            await self.coordinator.hooks.emit(
                ARTIFACT_READ, {"data": {"path": str(path), "bytes": len(content.encode("utf-8"))}}
            )

            # Prepare output
            output = {
                "file_path": str(path),
                "content": formatted_content,
                "total_lines": len(lines),
                "lines_read": len(selected_lines),
                "offset": offset,
            }

            # Add warning if file is empty
            if len(lines) == 0:
                output["warning"] = "File exists but has empty contents"

            return ToolResult(success=True, output=output)

        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                error={
                    "message": f"Cannot read file: {file_path} (not a text file or encoding issue)",
                    "type": "UnicodeDecodeError",
                },
            )
        except Exception as e:
            return ToolResult(
                success=False, error={"message": f"Error reading file: {str(e)}", "type": type(e).__name__}
            )

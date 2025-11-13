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
Reads a file or lists a directory from the local filesystem. You can access any file directly by using this tool.
Supports @mention paths for accessing collection files, project files, and user files.

Usage:
- The file_path parameter accepts:
  - Absolute paths: /home/user/file.md
  - @mention paths: @toolkit:scenario-tools/blog-writer/README.md
  - @mention directories: @toolkit:scenario-tools/blog-writer (returns directory listing)
  - @collection:path - Collection resources (e.g., @foundation:context/file.md)
  - @user:path - Shortcut to ~/.amplifier/{path}
  - @project:path - Shortcut to .amplifier/{path}
  - @~/path - User home directory
- By default, reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files)
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- For directories, returns a formatted listing showing DIR/FILE entries
- You can call multiple tools in a single response. It is always better to speculatively read multiple potentially useful files in parallel.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
    """

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize ReadTool with configuration."""
        self.config = config
        # Read operations are permissive by default (None = allow all paths)
        # This allows reading context files from package installations
        self.allowed_read_paths = config.get("allowed_read_paths")
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
                    "description": "The absolute path or @mention to the file/directory to read",
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
        """Check if path is within allowed read paths.

        If allowed_read_paths is None, all reads are permitted (default).
        Otherwise, checks if path is within any allowed directory or its subdirectories.
        """
        # No restrictions if allowed_read_paths is None (default)
        if self.allowed_read_paths is None:
            return True

        # Check if path is within any allowed directory or its subdirectories
        resolved_path = path.resolve()
        for allowed in self.allowed_read_paths:
            allowed_resolved = Path(allowed).resolve()
            # Allow if allowed_path is a parent of or equal to the target path
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
        Read a file or directory from the filesystem.

        Args:
            input: {
                "file_path": str - The absolute path or @mention to the file/directory to read
                "offset": Optional[int] - Line number to start reading from (1-indexed)
                "limit": Optional[int] - Number of lines to read
            }

        Returns:
            ToolResult with formatted file content or directory listing
        """
        file_path = input.get("file_path", "")
        offset = input.get("offset", 1)  # Default to line 1
        limit = input.get("limit", self.default_line_limit)

        if not file_path:
            return ToolResult(success=False, error={"message": "file_path is required"})

        # Handle @mention paths
        if file_path.startswith("@"):
            # Get mention resolver from coordinator capabilities (app-layer provides)
            mention_resolver = self.coordinator.get_capability("mention_resolver")

            if mention_resolver is None:
                return ToolResult(
                    success=False,
                    error={"message": "@mention paths require mention_resolver capability (not available)"},
                )

            resolved_path = mention_resolver.resolve(file_path)

            if resolved_path is None:
                return ToolResult(success=False, error={"message": f"@mention not found: {file_path}"})

            path = resolved_path
        else:
            path = Path(file_path)

        # Check if path is allowed for reading
        if not self._is_allowed(path):
            return ToolResult(
                success=False, error={"message": f"Access denied: {file_path} is not within allowed read paths"}
            )

        # Check if path exists
        if not path.exists():
            return ToolResult(success=False, error={"message": f"Path not found: {file_path}"})

        # Handle directories - return formatted listing
        if path.is_dir():
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
                lines = []
                for entry in entries:
                    entry_type = "DIR " if entry.is_dir() else "FILE"
                    lines.append(f"  {entry_type} {entry.name}")

                listing = "\n".join(lines)
                output_text = f"Directory: {path}\n\n{listing}"

                return ToolResult(
                    success=True,
                    output={
                        "file_path": str(path),
                        "content": output_text,
                        "is_directory": True,
                        "entry_count": len(entries),
                    },
                )
            except Exception as e:
                return ToolResult(
                    success=False, error={"message": f"Error listing directory: {str(e)}", "type": type(e).__name__}
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
            await self.coordinator.hooks.emit(ARTIFACT_READ, {"path": str(path), "bytes": len(content.encode("utf-8"))})

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

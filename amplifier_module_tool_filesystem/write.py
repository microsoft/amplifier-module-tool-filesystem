"""WriteTool - Write files to the local filesystem."""

from pathlib import Path
from typing import Any

from amplifier_core import ModuleCoordinator
from amplifier_core import ToolResult
from amplifier_core.events import ARTIFACT_WRITE


class WriteTool:
    """Write files to the local filesystem."""

    name = "write_file"
    description = """
Writes a file to the local filesystem.
Supports @mention paths for accessing bundle resources.

Usage:
- The file_path parameter accepts:
  - Absolute paths: /home/user/file.md
  - Relative paths: ./docs/README.md
  - @bundle-name:path - Bundle resources (e.g., @mybundle:docs/README.md)
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the read_file tool first to read the file's contents. This tool will fail if you did not read the file first.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.
                   """

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize WriteTool with configuration."""
        self.config = config
        # Write operations are restrictive by default (current directory only)
        # Protects against unintended file modifications outside project
        self.allowed_write_paths = config.get("allowed_write_paths", ["."])
        self.denied_write_paths = config.get("denied_write_paths", [])
        self.coordinator = coordinator

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path or @mention to the file to write",
                },
                "content": {"type": "string", "description": "The content to write to the file"},
            },
            "required": ["file_path", "content"],
        }

    def _check_write_access(self, path: Path) -> tuple[bool, str | None]:
        """Check if path is allowed for writing.
        
        Uses centralized validation that checks denied paths first,
        then allowed paths. Deny always takes priority.
        
        Returns:
            Tuple of (allowed: bool, error_message: str | None)
        """
        from .path_validation import is_path_allowed
        return is_path_allowed(path, self.allowed_write_paths, self.denied_write_paths)

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """
        Write content to a file.

        Args:
            input: {
                "file_path": str - The absolute path to the file to write
                "content": str - The content to write to the file
            }

        Returns:
            ToolResult indicating success and bytes written
        """
        file_path = input.get("file_path", "")
        content = input.get("content", "")

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

            # Cannot write to directories
            if resolved_path.is_dir():
                return ToolResult(success=False, error={"message": f"Cannot write to directory: {file_path}"})

            path = resolved_path
        else:
            path = Path(file_path).expanduser()

        # Check if path is allowed for writing
        allowed, error_msg = self._check_write_access(path)
        if not allowed:
            return ToolResult(success=False, error={"message": error_msg})

        try:
            # Create parent directories if they don't exist
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write content to file
            path.write_text(content, encoding="utf-8")

            # Calculate bytes written
            bytes_written = len(content.encode("utf-8"))

            # Emit artifact write event
            await self.coordinator.hooks.emit(ARTIFACT_WRITE, {"path": str(path), "bytes": bytes_written})

            return ToolResult(success=True, output={"file_path": str(path), "bytes": bytes_written})

        except OSError as e:
            return ToolResult(
                success=False,
                error={"message": f"OS error writing file: {str(e)}", "type": "OSError", "errno": e.errno},
            )
        except Exception as e:
            return ToolResult(
                success=False, error={"message": f"Error writing file: {str(e)}", "type": type(e).__name__}
            )

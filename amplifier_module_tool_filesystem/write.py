"""WriteTool - Write files to the local filesystem."""

from pathlib import Path
from typing import Any

from amplifier_core import ModuleCoordinator, ToolResult
from amplifier_core.events import ARTIFACT_WRITE

from ._newlines import detect_newline, write_text_preserving


class WriteTool:
    """Write files to the local filesystem."""

    name = "write_file"
    description = """
Writes a file to the local filesystem.
Supports @mention paths for accessing bundle resources.

Usage:
- The file_path parameter accepts absolute paths, relative paths, and @bundle-name:path
  bundle resources — see the read_file tool description for the full form.
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the read_file tool first to read the file's contents. This tool will fail if you did not read the file first.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.
                   """

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize WriteTool with configuration."""
        self.config = config
        # Working directory for resolving relative paths (from session.working_dir capability)
        self.working_dir = config.get("working_dir")
        # Write operations are restrictive by default (current directory only)
        # Protects against unintended file modifications outside project
        # If working_dir is set, use it as the default allowed path
        default_allowed = [self.working_dir] if self.working_dir else ["."]
        self.allowed_write_paths = config.get("allowed_write_paths", default_allowed)
        # Optional equality-only grant: authorizes exactly one file each,
        # never a descendant, sibling, or parent. Defaults to empty, which
        # is behaviorally identical to configs that predate this option.
        self.allowed_write_files = config.get("allowed_write_files", [])
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
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
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

        return is_path_allowed(
            path,
            self.allowed_write_paths,
            self.denied_write_paths,
            self.allowed_write_files,
        )

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
            error_msg = "file_path is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        # Handle @mention paths
        if file_path.startswith("@"):
            # Get mention resolver from coordinator capabilities (app-layer provides)
            mention_resolver = self.coordinator.get_capability("mention_resolver")

            if mention_resolver is None:
                error_msg = (
                    "@mention paths require mention_resolver capability (not available)"
                )
                return ToolResult(
                    success=False,
                    output=error_msg,
                    error={"message": error_msg},
                )

            resolved_path = mention_resolver.resolve(file_path)

            if resolved_path is None:
                error_msg = f"@mention not found: {file_path}"
                return ToolResult(
                    success=False, output=error_msg, error={"message": error_msg}
                )

            # Cannot write to directories
            if resolved_path.is_dir():
                error_msg = f"Cannot write to directory: {file_path}"
                return ToolResult(
                    success=False, output=error_msg, error={"message": error_msg}
                )

            path = resolved_path
        else:
            path = Path(file_path).expanduser()
            # Resolve relative paths against working_dir (from session.working_dir capability)
            if not path.is_absolute() and self.working_dir:
                path = Path(self.working_dir) / path

        # Check if path is allowed for writing
        allowed, error_msg = self._check_write_access(path)
        if not allowed:
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        try:
            # Create parent directories if they don't exist
            path.parent.mkdir(parents=True, exist_ok=True)

            # Preserve an existing file's line-ending convention on overwrite;
            # new files are written exactly as given (LF as the caller provided).
            # Either way, no platform \n->os.linesep translation is applied.
            newline = "\n"
            if path.exists():
                try:
                    newline = detect_newline(path.read_bytes().decode("utf-8"))
                except (OSError, UnicodeDecodeError):
                    newline = "\n"
            bytes_written = write_text_preserving(path, content, newline)

            # Emit artifact write event
            await self.coordinator.hooks.emit(
                ARTIFACT_WRITE, {"path": str(path), "bytes": bytes_written}
            )

            return ToolResult(
                success=True, output={"file_path": str(path), "bytes": bytes_written}
            )

        except OSError as e:
            error_msg = f"OS error writing file: {e!s}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": "OSError", "errno": e.errno},
            )
        except Exception as e:
            error_msg = f"Error writing file: {e!s}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": type(e).__name__},
            )

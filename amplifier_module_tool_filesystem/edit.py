"""EditTool - Perform exact string replacements in files."""

from pathlib import Path
from typing import Any

from amplifier_core import ModuleCoordinator
from amplifier_core import ToolResult
from amplifier_core.events import ARTIFACT_WRITE


class EditTool:
    """Perform exact string replacements in files."""

    name = "edit_file"
    description = """
Performs exact string replacements in files.
Supports @mention paths for accessing collection files, project files, and user files.

Usage:
- The file_path parameter accepts:
  - Absolute paths: /home/user/file.md
  - @mention paths: @project:config/settings.yaml
  - @user:path - Shortcut to ~/.amplifier/{path}
  - @project:path - Shortcut to .amplifier/{path}
  - Note: Collection paths (@collection:) are typically read-only
- You must use your read_file tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from read_file tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit_file will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.
    """

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize EditTool with configuration."""
        self.config = config
        self.coordinator = coordinator

        # Extract working directory for path resolution
        # This is the session's amplified_dir, not the daemon's CWD
        self.working_dir = Path(config.get("working_dir", "."))

        # Edit operations are restrictive by default (current directory only)
        # Protects against unintended file modifications outside project
        self.allowed_write_paths = config.get("allowed_write_paths", ["."])

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path or @mention to the file to modify",
                },
                "old_string": {
                    "type": "string",
                    "description": "The text to replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The text to replace it with (must be different from old_string)",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences of old_string (default: false)",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def _is_allowed(self, path: Path) -> bool:
        """Check if path is within allowed write paths.

        Checks if path is within any allowed directory or its subdirectories.
        Edit operations are always restricted for security.

        Paths are resolved relative to working_dir (session's amplified_dir),
        not the daemon's current working directory.
        """
        resolved_path = path.resolve()

        for allowed in self.allowed_write_paths:
            allowed_path = Path(allowed)

            # Resolve relative paths against working_dir, not daemon's CWD
            if not allowed_path.is_absolute():
                allowed_path = self.working_dir / allowed_path

            allowed_resolved = allowed_path.resolve()

            # Allow if allowed_path is a parent of or equal to the target path
            if allowed_resolved in resolved_path.parents or allowed_resolved == resolved_path:
                return True

        return False

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """
        Perform exact string replacement in a file.

        Args:
            input: {
                "file_path": str - The absolute path to the file to modify
                "old_string": str - The text to replace
                "new_string": str - The text to replace it with
                "replace_all": bool - Replace all occurrences (default: false)
            }

        Returns:
            ToolResult indicating success and number of replacements made
        """
        file_path = input.get("file_path", "")
        old_string = input.get("old_string", "")
        new_string = input.get("new_string", "")
        replace_all = input.get("replace_all", False)

        # Validation
        if not file_path:
            return ToolResult(success=False, error={"message": "file_path is required"})

        if not old_string:
            return ToolResult(success=False, error={"message": "old_string is required"})

        if old_string == new_string:
            return ToolResult(
                success=False, error={"message": "old_string and new_string must be different (no changes to make)"}
            )

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

            # Cannot edit directories
            if resolved_path.is_dir():
                return ToolResult(success=False, error={"message": f"Cannot edit directory: {file_path}"})

            path = resolved_path
        else:
            path = Path(file_path)

        # Check if path is allowed for editing
        if not self._is_allowed(path):
            return ToolResult(
                success=False, error={"message": f"Access denied: {file_path} is not within allowed write paths"}
            )

        # Check if file exists
        if not path.exists():
            return ToolResult(success=False, error={"message": f"File not found: {file_path}"})

        try:
            # Read current content
            content = path.read_text(encoding="utf-8")

            # Check if old_string exists
            if old_string not in content:
                return ToolResult(
                    success=False,
                    error={"message": f"old_string not found in file: {file_path}", "old_string": old_string},
                )

            # Check uniqueness if not replace_all
            if not replace_all:
                occurrences = content.count(old_string)
                if occurrences > 1:
                    return ToolResult(
                        success=False,
                        error={
                            "message": f"old_string appears {occurrences} times in file. Either provide more context to make it unique or set replace_all=true",
                            "occurrences": occurrences,
                            "old_string": old_string,
                        },
                    )

            # Perform replacement
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements_made = content.count(old_string)
            else:
                # Replace only the first occurrence
                new_content = content.replace(old_string, new_string, 1)
                replacements_made = 1

            # Write updated content
            path.write_text(new_content, encoding="utf-8")

            # Calculate bytes written
            bytes_written = len(new_content.encode("utf-8"))

            # Emit artifact write event
            await self.coordinator.hooks.emit(ARTIFACT_WRITE, {"path": str(path), "bytes": bytes_written})

            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "replacements_made": replacements_made,
                    "bytes_written": bytes_written,
                },
            )

        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                error={
                    "message": f"Cannot read file: {file_path} (not a text file or encoding issue)",
                    "type": "UnicodeDecodeError",
                },
            )
        except OSError as e:
            return ToolResult(
                success=False,
                error={"message": f"OS error modifying file: {str(e)}", "type": "OSError", "errno": e.errno},
            )
        except Exception as e:
            return ToolResult(
                success=False, error={"message": f"Error modifying file: {str(e)}", "type": type(e).__name__}
            )

"""ReadTool - Read files from the local filesystem.

PR7 fixes applied:
  1. _is_allowed() — resolve(strict=True) so symlinks are followed to their
     real target before the allow-list comparison (mirrors path_validation.py).
  2. Binary-file detection — _is_binary() reads the first 8 KiB and looks for
     null bytes; binary files return a metadata-only ToolResult instead of
     crashing with a UnicodeDecodeError.
  3. UnicodeDecodeError fallback — latin-1 is tried before returning an error
     so files with 8-bit encodings still render rather than hard-failing.
"""

from pathlib import Path
from typing import Any

from amplifier_core import ModuleCoordinator  # type: ignore[import-untyped]
from amplifier_core import ToolResult  # type: ignore[import-untyped]
from amplifier_core.events import ARTIFACT_READ  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# PR7 Fix 2 — binary detection helper
# ---------------------------------------------------------------------------


def _is_binary(filepath: Path | str, sample_size: int = 8192) -> bool:
    """Detect binary files by scanning for null bytes.

    Reads up to *sample_size* bytes from the start of the file and returns
    True if a null byte (0x00) is found.  Null bytes almost never appear in
    legitimate text files but are extremely common in compiled, compressed, or
    media files.

    Args:
        filepath: Path to inspect.
        sample_size: Number of bytes to sample (default 8 KiB).

    Returns:
        True  — file is almost certainly binary.
        False — file looks textual (or could not be opened).
    """
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(sample_size)
            if b"\x00" in chunk:
                return True
        return False
    except OSError:
        return False


class ReadTool:
    """Read files from the local filesystem with line numbering and pagination support."""

    name = "read_file"
    description = """Read a file, or list a directory, from the local filesystem. Any file is directly accessible.

file_path accepts absolute paths (/home/user/file.md), relative paths (./docs/README.md), @bundle-name:path bundle resources (e.g. @mybundle:docs/README.md), and @mention directories (@mybundle:docs, returns a listing).

Reads up to 2000 lines from the start by default; pass offset (1-indexed) and limit for long files. Lines longer than 2000 characters are truncated. Output is cat -n format, line numbers starting at 1; a directory returns a listing of DIR/FILE entries. A file that exists but is empty returns a system-reminder warning in place of contents.

Read multiple potentially useful files in parallel in one response."""

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize ReadTool with configuration."""
        self.config = config
        # Read operations are permissive by default (None = allow all paths)
        # This allows reading context files from package installations
        self.allowed_read_paths = config.get("allowed_read_paths")
        self.coordinator = coordinator
        self.max_line_length = 2000
        self.default_line_limit = 2000
        # Working directory for resolving relative paths (from session.working_dir capability)
        self.working_dir = config.get("working_dir")

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

        PR7: resolve(strict=True) ensures symlinks are followed to their real
        filesystem target before any allow-list comparison, preventing a
        symlink placed inside an allowed directory from granting read access
        to content that lives outside it.
        """
        # No restrictions if allowed_read_paths is None (default)
        if self.allowed_read_paths is None:
            return True

        # PR7: strict=True follows symlinks; OSError means path doesn't exist → deny.
        try:
            resolved_path = path.resolve(strict=True)
        except OSError:
            return False

        for allowed in self.allowed_read_paths:
            try:
                allowed_resolved = Path(allowed).resolve(strict=True)
            except OSError:
                # Configured allowed path doesn't exist on this system — skip it.
                continue
            # Allow if allowed_path is a parent of or equal to the target path
            if (
                allowed_resolved in resolved_path.parents
                or allowed_resolved == resolved_path
            ):
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

            path = resolved_path
        else:
            path = Path(file_path).expanduser()
            # Resolve relative paths against working_dir (from session.working_dir capability)
            if not path.is_absolute() and self.working_dir:
                path = Path(self.working_dir) / path

        # Check if path is allowed for reading
        if not self._is_allowed(path):
            error_msg = f"Access denied: {file_path} is not within allowed read paths"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg},
            )

        # Check if path exists
        if not path.exists():
            error_msg = f"Path not found: {file_path}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

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
                error_msg = f"Error listing directory: {str(e)}"
                return ToolResult(
                    success=False,
                    output=error_msg,
                    error={"message": error_msg, "type": type(e).__name__},
                )

        try:
            # PR7 Fix 2 — Binary file detection.
            # Check for null bytes before attempting text decoding.  Binary
            # files (executables, images, compiled artifacts, archives, …) are
            # returned as a metadata-only result rather than crashing.
            if _is_binary(path):
                size = path.stat().st_size
                suffix = path.suffix.lower()
                return ToolResult(
                    success=True,
                    output={
                        "content": (
                            f"Binary file ({suffix or 'unknown type'}, {size:,} bytes)"
                            " — cannot display as text."
                        ),
                        "file_path": str(path),
                        "is_binary": True,
                        "size_bytes": size,
                    },
                )

            # PR7 Fix 3 — Encoding fallback.
            # Try UTF-8 first; fall back to latin-1 for 8-bit encoded files
            # (ISO-8859-1 can decode any byte sequence, so it never raises).
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # Try latin-1 as fallback
                try:
                    content = path.read_text(encoding="latin-1")
                except Exception:
                    size = path.stat().st_size
                    return ToolResult(
                        success=True,
                        output={
                            "content": f"File cannot be decoded as text ({size:,} bytes).",
                            "file_path": str(path),
                            "is_binary": True,
                        },
                    )

            lines = content.splitlines()

            # Handle offset and limit (convert to 0-indexed)
            start_idx = max(0, offset - 1)
            end_idx = start_idx + limit

            # Get the requested slice
            selected_lines = lines[start_idx:end_idx]

            # Format with line numbers
            formatted_content = self._format_with_line_numbers(
                selected_lines, start_line=offset
            )

            # Emit artifact read event
            await self.coordinator.hooks.emit(
                ARTIFACT_READ,
                {"path": str(path), "bytes": len(content.encode("utf-8"))},
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

        except Exception as e:
            error_msg = f"Error reading file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": type(e).__name__},
            )

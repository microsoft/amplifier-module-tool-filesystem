"""ReadTool - Read files from the local filesystem."""

from contextlib import contextmanager, ExitStack
import io
import os
from pathlib import Path
import stat
from typing import Any
import unicodedata

from amplifier_core import ModuleCoordinator
from amplifier_core import ToolResult
from amplifier_core.events import ARTIFACT_READ


class ReadTool:
    """Read files from the local filesystem with line numbering and pagination support."""

    name = "read_file"
    description = """Read a file, or list a directory, from the local filesystem within this tool's configured access policy.

file_path accepts absolute paths (/home/user/file.md), relative paths (./docs/README.md), @bundle-name:path bundle resources (e.g. @mybundle:docs/README.md), and @mention directories (@mybundle:docs, returns a listing).

Reads up to 2000 lines from the start by default; pass offset (1-indexed) and limit for long files. Lines longer than 2000 characters are truncated. Output is cat -n format, line numbers starting at 1; a directory returns a listing of DIR/FILE entries. A file that exists but is empty returns a system-reminder warning in place of contents.

Static PNG/JPEG images use compatible session media handling; otherwise image unavailable (no pixels). Omit offset/limit for images.

Read multiple potentially useful files in parallel in one response."""

    def __init__(self, config: dict[str, Any], coordinator: ModuleCoordinator):
        """Initialize ReadTool with configuration."""
        self.config = config
        # Read operations are permissive by default (None = allow all paths)
        # This allows reading context files from package installations
        self.allowed_read_paths = config.get("allowed_read_paths")
        self.denied_read_paths = config.get("denied_read_paths")
        if self.denied_read_paths is None:
            self.denied_read_paths = []
        if not isinstance(self.denied_read_paths, list) or any(not isinstance(path, str) for path in self.denied_read_paths):
            raise ValueError("denied_read_paths must be a list of paths or null")
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
        """
        resolved_path = path.resolve()
        def resolve_policy(value):
            root = Path(value).expanduser()
            if not root.is_absolute() and self.working_dir:
                root = Path(self.working_dir) / root
            return root.resolve()

        def contains(root, *, denial=False):
            if resolved_path.is_relative_to(root):
                return True
            # Case-insensitive volumes can preserve a different spelling after
            # resolve(). Compare existing identity, never lowercase every path.
            for candidate in (resolved_path, *resolved_path.parents):
                if not denial and (unicodedata.normalize('NFC', str(candidate)).casefold()
                                   != unicodedata.normalize('NFC', str(root)).casefold()):
                    continue
                try:
                    if candidate.samefile(root):
                        return True
                except OSError:
                    pass
            return False

        # A deliberate denial wins even when reads are otherwise unrestricted.
        if any(contains(resolve_policy(denied), denial=True) for denied in self.denied_read_paths):
            return False
        if self.allowed_read_paths is None:
            return True

        for allowed in self.allowed_read_paths:
            allowed_resolved = resolve_policy(allowed)
            # Allow if allowed_path is a parent of or equal to the target path
            if contains(allowed_resolved):
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

    @contextmanager
    def _open_authorized(self, path: Path):
        """Bind authorization to a regular descriptor, never a decoder pathname.

        Resolve permitted symlinks once, then pin and verify every canonical
        ancestor. Opening only the leaf with O_NOFOLLOW would still follow a
        replacement parent symlink. No payload read occurs until verification.
        Platforms without directory-relative no-follow opens retain ordinary
        text reads, but must not enable the media path.
        """
        policy = self._snapshot_policy()
        resolved = path.resolve(strict=True)
        if not self._is_allowed(resolved):
            raise PermissionError("Access denied by read policy")
        chain = [*reversed(resolved.parents), resolved]
        snapshots = [item.stat(follow_symlinks=False) for item in chain]
        if not stat.S_ISREG(snapshots[-1].st_mode):
            raise ValueError("Only regular files can be read")
        secure = (
            os.open in os.supports_dir_fd
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and (hasattr(os, "O_PATH") or hasattr(os, "O_SEARCH"))
        )
        with ExitStack() as stack:
            parent_fd = None
            held = list(snapshots)
            for index, (item, expected) in enumerate(zip(chain, snapshots)):
                if not secure and index != len(chain) - 1:
                    continue
                flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                if secure:
                    flags |= os.O_NOFOLLOW | os.O_NONBLOCK
                    if index != len(chain) - 1:
                        # Traversal needs search, not directory listing access.
                        flags = (getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY))
                                 | os.O_DIRECTORY | os.O_NOFOLLOW
                                 | getattr(os, "O_CLOEXEC", 0))
                    fd = os.open(str(item) if parent_fd is None else item.name,
                                 flags, dir_fd=parent_fd)
                else:
                    fd = os.open(str(item), flags | getattr(os, "O_BINARY", 0))
                stack.callback(os.close, fd)
                actual = os.fstat(fd)
                held[index] = actual
                if (not os.path.samestat(expected, actual)
                        or (secure and index == len(chain) - 1
                            and self._file_version(expected) != self._file_version(actual))):
                    raise PermissionError("File identity changed during read authorization")
                parent_fd = fd
            # Verify the still-held descriptor and its whole path binding before
            # reading even the signature. A rename/replacement is not permission.
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("Only regular files can be read")
            if (not self._descriptor_allowed(chain, held, policy)
                    or not self._policy_unchanged(policy)
                    or path.resolve(strict=True) != resolved
                    or any(not os.path.samestat(expected, item.stat(follow_symlinks=False))
                           for item, expected in zip(chain, snapshots))):
                raise PermissionError("Path changed during read authorization")
            with os.fdopen(os.dup(fd), "rb") as source:
                yield source, secure and all(entry[3] is not False for entry in policy)

    def _snapshot_policy(self):
        """Capture roots independently of attacker-controlled target lookups."""
        result = []
        for denial, values in ((True, self.denied_read_paths),
                               (False, self.allowed_read_paths or [])):
            for value in values:
                original = Path(value).expanduser()
                if not original.is_absolute() and self.working_dir:
                    original = Path(self.working_dir) / original
                resolved = original.resolve()
                try:
                    identity = resolved.stat()
                except FileNotFoundError:
                    identity = None
                except PermissionError:
                    # Legacy text reads tolerate an inaccessible unrelated root.
                    # Its unknown alias identity MUST disable image staging.
                    identity = False
                result.append((denial, original, resolved, identity))
        return result

    @staticmethod
    def _policy_unchanged(policy):
        for _, original, resolved, identity in policy:
            if original.resolve() != resolved:
                return False
            try:
                current = resolved.stat()
            except FileNotFoundError:
                current = None
            except PermissionError:
                if identity is False:
                    continue
                return False
            if identity is False:
                return False
            if (current is None) != (identity is None):
                return False
            if current is not None and not os.path.samestat(current, identity):
                return False
        return True

    def _descriptor_allowed(self, chain, held, policy):
        """Evaluate deny aliases on held identities, not a second path stat.

        Repeated pathname checks cannot prevent ABA swaps: a decoy can satisfy
        samefile while a different, denied inode is already open.
        """
        allowed = self.allowed_read_paths is None
        target = chain[-1]
        for denial, _, root, identity in policy:
            matches = target.is_relative_to(root)
            if identity is not None and identity is not False:
                for candidate, actual in zip(chain, held):
                    spelling = (unicodedata.normalize("NFC", str(candidate)).casefold()
                                == unicodedata.normalize("NFC", str(root)).casefold())
                    if (denial or spelling) and os.path.samestat(actual, identity):
                        matches = True
            if matches:
                if denial:
                    return False
                allowed = True
        return allowed

    @staticmethod
    def _file_version(info):
        return (info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    @staticmethod
    def _image_kind(header: bytes, path: Path) -> str | None:
        """Detect image candidates; the media owner must verify the full file."""
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if (header.startswith((b"GIF87a", b"GIF89a"))
                or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")):
            return "unsupported"
        return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "unsupported", ".webp": "unsupported"}.get(path.suffix.lower())

    @staticmethod
    def _image_unavailable(path: Path, reason: str) -> ToolResult:
        message = f"Image unavailable: {reason}; no pixels were sent."
        return ToolResult(
            success=False,
            output={"file_path": str(path), "is_image": True, "content": message},
            error={"message": message, "type": "ImageUnavailable"},
        )

    async def _read_image(self, path, source, kind, input, secure):
        """Stage authorized original bytes; acceptance belongs to loop posthooks."""
        if "offset" in input or "limit" in input:
            return self._image_unavailable(
                path, "offset and limit are text-line parameters; retry without them"
            )
        if kind == "unsupported":
            return self._image_unavailable(path, "only static PNG/JPEG are supported")
        if not secure:
            return self._image_unavailable(
                path, "secure descriptor-bound image reads are unsupported on this platform"
            )
        lookup = getattr(self.coordinator, "get_capability", None)
        media = lookup("experimental.media.v1") if lookup else None
        if (type(getattr(media, "version", None)) is not int or media.version != 1
                or any(not callable(getattr(media, name, None)) for name in
                       ("ingest", "publish", "validate", "resolve", "prepare_request", "report"))):
            return self._image_unavailable(
                path, "compatible session media handling is not installed"
            )
        try:
            # Readiness is a host enablement observation, not a grant created by
            # this report. A merely present library must not activate producers.
            readiness = media.report(
                "tool-filesystem.read_file", event="consumer-ready", outcome="ready",
                details={"contract": 1, "role": "producer"},
            )
            if not isinstance(readiness, dict) or readiness.get("enabled") is not True:
                return self._image_unavailable(path, "session media delivery is not enabled")
            before = os.fstat(source.fileno())
            staged = await media.ingest(
                {"stream": source, "mime": kind}, source_format="image-bytes",
                origin=None, policy=None,
            )
            # The host-bound origin resolver supplies the actual call identity.
            # Tool arguments (including extra origin/id/policy fields) never do.
            if self._file_version(before) != self._file_version(os.fstat(source.fileno())):
                return self._image_unavailable(path, "source changed during image ingestion")
            ref = staged["value"]
            if (not isinstance(ref, dict) or staged["staged_refs"] != [ref]
                    or set(ref) != {"v", "session_id", "sha256", "mime", "bytes",
                                    "width", "height", "provenance"}
                    or ref["mime"] != kind):
                return self._image_unavailable(path, "incompatible media ingestion result")
        except Exception:
            # Decoder/authority errors may contain private staging paths or bytes.
            # Do not serialize those exceptions or retry ingestion elsewhere.
            return self._image_unavailable(
                path, "media validation or staging refused; check session media policy and file integrity"
            )
        await self.coordinator.hooks.emit(
            ARTIFACT_READ, {"path": str(path), "bytes": ref["bytes"]}
        )
        return ToolResult(success=True, output={
            "file_path": str(path), "is_image": True,
            "content": "Static image staged for post-hook acceptance; pixels have not been sent.",
            "experimental.media.v1": {"refs": [ref]},
        })

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

            path = Path(resolved_path)
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
                entries = sorted((entry for entry in path.iterdir() if self._is_allowed(entry)),
                                 key=lambda p: (not p.is_dir(), p.name))
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
            with self._open_authorized(path) as (source, secure):
                kind = self._image_kind(source.read(16), path)
                source.seek(0)
                if kind:
                    return await self._read_image(path, source, kind, input, secure)
                # Preserve read_text's UTF-8 and universal-newline semantics.
                content = io.TextIOWrapper(source, encoding="utf-8").read()
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

        except UnicodeDecodeError:
            error_msg = (
                f"Cannot read file: {file_path} (not a text file or encoding issue)"
            )
            return ToolResult(
                success=False,
                output=error_msg,
                error={
                    "message": error_msg,
                    "type": "UnicodeDecodeError",
                },
            )
        except Exception as e:
            error_msg = f"Error reading file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": type(e).__name__},
            )

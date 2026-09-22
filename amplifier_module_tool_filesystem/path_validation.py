"""Path validation for filesystem operations.

Provides centralized allow/deny path checking logic.
Key principle: DENY always takes priority over ALLOW.

PR7 fix — symlink bypass (strict=True):
    All resolve() calls now use strict=True so that symlinks are followed
    to their real on-disk target before any allow/deny comparison.

    strict=True behaviour:
      • Raises OSError when the path does not exist  →  prevents TOCTOU races
        by making "does this path escape the sandbox?" a one-step atomic check.
      • Returns the REAL target of a symlink, not the symlink's own location,
        so a link placed inside an allowed directory that points outside it
        will be resolved to the external target and correctly denied.

    Each resolve call is wrapped in try/except OSError so that non-existent
    paths produce a safe denial rather than an unhandled exception.
"""

from pathlib import Path


def is_in_path_list(target: Path, path_list: list[str]) -> bool:
    """Check if target path is within any path in the list.

    A path is considered "within" if:
    - It exactly matches a path in the list, OR
    - A path in the list is a parent directory of the target

    Args:
        target: The path to check (should already be resolved)
        path_list: List of paths to check against

    Returns:
        True if target is within any path in the list.
        False if the target does not exist (strict=True → OSError).
    """
    # PR7: strict=True resolves symlinks to their real target and raises
    # OSError for non-existent paths, closing the TOCTOU window.
    try:
        resolved = target.resolve(strict=True)
    except OSError:
        return False

    for p in path_list:
        try:
            p_resolved = Path(p).expanduser().resolve(strict=True)
        except OSError:
            # Configured path doesn't exist on this system — skip it.
            continue
        if p_resolved == resolved or p_resolved in resolved.parents:
            return True
    return False


def is_path_allowed(
    path: Path,
    allowed_paths: list[str],
    denied_paths: list[str],
) -> tuple[bool, str | None]:
    """Check if path is allowed for writing.

    Validation order:
    1. Check denied_paths first - if match, DENY
    2. Check allowed_paths - if match, ALLOW
    3. Default - DENY (not in allowed list)

    Args:
        path: Target path to validate
        allowed_paths: List of allowed directory paths
        denied_paths: List of denied directory paths

    Returns:
        Tuple of (allowed: bool, error_message: str | None)
        - (True, None) if path is allowed
        - (False, error_message) if path is denied
    """
    # PR7: strict=True — if the path does not exist (or is a dangling symlink)
    # deny immediately; also resolves symlinks to real targets before comparing.
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return (False, f"Access denied: {path} does not exist or cannot be resolved")

    # Deny takes priority - check first
    if denied_paths and is_in_path_list(resolved, denied_paths):
        return (False, f"Access denied: {path} is within denied directories")

    # Then check allow list
    if is_in_path_list(resolved, allowed_paths):
        return (True, None)

    # Default: not allowed
    return (False, f"Access denied: {path} is not within allowed write paths")

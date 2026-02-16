"""Path validation for filesystem operations.

Provides centralized allow/deny path checking logic.
Key principle: DENY always takes priority over ALLOW.
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
        True if target is within any path in the list
    """
    resolved = target.resolve()
    for p in path_list:
        p_resolved = Path(p).expanduser().resolve()
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
    resolved = path.resolve()

    # Deny takes priority - check first
    if denied_paths and is_in_path_list(resolved, denied_paths):
        return (False, f"Access denied: {path} is within denied directories")

    # Then check allow list
    if is_in_path_list(resolved, allowed_paths):
        return (True, None)

    # Default: not allowed
    return (False, f"Access denied: {path} is not within allowed write paths")

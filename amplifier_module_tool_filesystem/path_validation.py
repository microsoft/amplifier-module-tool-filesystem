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


def is_exact_file_allowed(target: Path, file_list: list[str]) -> bool:
    """Check if target path is EXACTLY one of the configured file paths.

    Unlike is_in_path_list(), this is equality-only: an entry in file_list
    authorizes exactly that one file and confers no authorization on:
      - descendants (e.g. if the path later becomes a directory)
      - siblings in the same directory
      - the parent directory
      - any other path whatsoever

    This exists for narrow "authorize exactly this one file" grants (e.g. a
    single engine-managed status file), where the existing directory-prefix
    semantics of is_in_path_list()/allowed_write_paths would be too broad --
    granting a directory entry there also grants every path beneath it.

    Both target and each configured entry are normalized identically
    (~expanduser + resolve()) before comparison, so a symlink at the leaf --
    in either the write target or a configured entry -- is compared by its
    resolved real path, exactly like is_in_path_list() already does.

    Non-existent targets resolve without error: Path.resolve() (no
    strict=True) never raises for a missing path, it just resolves as far
    as it can and appends the remaining unresolved components lexically.
    This intentionally mirrors is_in_path_list()'s existing non-strict
    behavior, so a brand-new file (parent directory not yet created) can
    still be matched -- this is the common case this allow-list exists to
    support (e.g. an engine writing a fresh status file on first run).

    NOTE (interaction with PR #8): an open PR (microsoft/amplifier-module-
    tool-filesystem#8) proposes switching is_in_path_list()/is_path_allowed()
    to Path.resolve(strict=True) to close a symlink/TOCTOU gap. strict=True
    raises for any non-existent path -- which would also reject the ordinary
    "write a brand-new file" case both allowed_write_paths and this exact-
    file allow-list exist to support. If/when #8 lands, its author needs to
    reconcile strict=True with legitimate new-file writes (in both the
    directory-prefix path and this equality-only path), not silently break
    them. This function intentionally does NOT adopt strict=True today.

    Args:
        target: The path to check (should already be resolved-compatible)
        file_list: List of exact file paths to check against

    Returns:
        True if target resolves to exactly one of the paths in file_list
    """
    resolved = target.resolve()
    for f in file_list:
        f_resolved = Path(f).expanduser().resolve()
        if f_resolved == resolved:
            return True
    return False


def is_path_allowed(
    path: Path,
    allowed_paths: list[str],
    denied_paths: list[str],
    allowed_files: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Check if path is allowed for writing.

    Validation order:
    1. Check denied_paths first - if match, DENY (always wins, regardless
       of whether the match would otherwise be authorized via allowed_paths
       or allowed_files)
    2. Check allowed_paths - directory-prefix match, if match, ALLOW
    3. Check allowed_files - equality-only match, if match, ALLOW
    4. Default - DENY (not in either allow list)

    Args:
        path: Target path to validate
        allowed_paths: List of allowed directory paths (prefix match --
            authorizes the path itself and everything beneath it)
        denied_paths: List of denied directory paths (prefix match)
        allowed_files: Optional list of exact file paths (equality-only
            match -- authorizes exactly that file, never descendants,
            siblings, or the parent directory). Defaults to no exact-file
            grants when omitted or empty, which is behaviorally identical
            to callers that predate this parameter.

    Returns:
        Tuple of (allowed: bool, error_message: str | None)
        - (True, None) if path is allowed
        - (False, error_message) if path is denied
    """
    resolved = path.resolve()

    # Deny takes priority - check first, before either allow list
    if denied_paths and is_in_path_list(resolved, denied_paths):
        return (False, f"Access denied: {path} is within denied directories")

    # Then check the directory-prefix allow list (existing behavior)
    if is_in_path_list(resolved, allowed_paths):
        return (True, None)

    # Then check the equality-only exact-file allow list (new, narrow grant)
    if allowed_files and is_exact_file_allowed(resolved, allowed_files):
        return (True, None)

    # Default: not allowed
    return (False, f"Access denied: {path} is not within allowed write paths")

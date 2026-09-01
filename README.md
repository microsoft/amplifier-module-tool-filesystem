# Amplifier Filesystem Tools Module

Provides basic file operations for Amplifier agents.

## Prerequisites

- **Python 3.11+**
- **[UV](https://github.com/astral-sh/uv)** - Fast Python package manager

### Installing UV

```bash
# macOS/Linux/WSL
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Purpose

Enables agents to read and write files within configured safe paths.

## Contract

**Module Type:** Tool
**Mount Point:** `tools`
**Entry Point:** `amplifier_module_tool_filesystem:mount`

## Module Structure

The module is split into three specialized tools, each in its own file following the modular design philosophy:

- `read.py` - ReadTool for reading files with line numbering and pagination
- `write.py` - WriteTool for writing/overwriting files
- `edit.py` - EditTool for exact string replacements

## Tools Provided

### `read_file`

Read the contents of a file with cat-n style line numbering and pagination support.

**Input:**

- `file_path` (string, required): Absolute path to the file to read
- `offset` (integer, optional): Line number to start reading from (1-indexed). Use for large files.
- `limit` (integer, optional): Number of lines to read. Defaults to 2000. Use for large files.

**Output:**

- File contents formatted with line numbers (cat -n style)
- Lines longer than 2000 characters are truncated
- Total line count and lines read
- Warning if file is empty

**Example:**
```
     1→# This is line 1
     2→# This is line 2
     3→# This is line 3
```

### `write_file`

Write content to a file (overwrites if exists).

**Input:**

- `file_path` (string, required): Absolute path to the file to write
- `content` (string, required): Content to write to the file

**Output:**

- Success with bytes written
- Creates parent directories automatically if needed

**Note:** You should read the file first before overwriting to avoid data loss.

### `edit_file`

Perform exact string replacements in files.

**Input:**

- `file_path` (string, required): Absolute path to the file to modify
- `old_string` (string, required): The exact text to replace
- `new_string` (string, required): The text to replace it with (must be different)
- `replace_all` (boolean, optional): Replace all occurrences. Defaults to false. If false and multiple occurrences exist, operation fails.

**Output:**

- Success with number of replacements made and bytes written
- Fails if old_string not found or not unique (unless replace_all=true)

**Note:** Read the file first to see the exact text including indentation. When copying from read_file output, exclude the line number prefix (everything before and including the tab character).

## Configuration

```toml
[[tools]]
module = "tool-filesystem"
config = {
    # Read operations (permissive by default)
    allowed_read_paths = null,  # null = allow all reads (default), or ["path1", "path2"]

    # Write/Edit operations (restrictive by default)
    allowed_write_paths = ["."],  # Default: current directory and subdirectories only

    # Optional: narrow, equality-only grants for individual files that live
    # outside allowed_write_paths (e.g. a single engine-managed status file).
    # Each entry authorizes EXACTLY that one file -- never its descendants,
    # siblings, or parent directory. Defaults to [] (no exact-file grants).
    allowed_write_files = [],

    require_approval = false
}
```

**Philosophy**: Reads are low-risk (consuming data), writes are high-risk (modifying system state).

## Security

**Read operations (read_file)**:
- Permissive by default (`allowed_read_paths = null` allows all reads)
- Enables reading context files from package installations
- Can be restricted with `allowed_read_paths = ["dir1", "dir2"]`

**Write operations (write_file, edit_file)**:
- Restrictive by default (`allowed_write_paths = ["."]`)
- Current directory and all subdirectories allowed
- Prevents unintended modifications outside project

**Path validation**:
- All paths resolved before checking
- Subdirectory traversal supported (parent path check)
- Path traversal attacks prevented

**Exact-file grants (`allowed_write_files`)**:

- **Purpose**: sometimes a caller needs to authorize writing to exactly one
  file that lives *outside* the directories granted by `allowed_write_paths`
  -- for example, a single engine-managed status file in a coordination
  directory the tool should otherwise never touch. Listing that whole
  coordination directory in `allowed_write_paths` would grant every path
  beneath it; `allowed_write_files` grants only the one named file.
- **Equality-only matching**: unlike `allowed_write_paths` (a directory-prefix
  match -- an entry also authorizes everything beneath it), each
  `allowed_write_files` entry is matched by **exact equality only** after the
  same normalization (`~` expansion + `resolve()`) used everywhere else in
  this module. It does **not** authorize:
  - descendants (e.g. the file later becomes a directory and gains children)
  - siblings in the same directory
  - the parent directory
  - any other path, however similar
- **Deny still wins**: `denied_write_paths` is checked before *both*
  `allowed_write_paths` and `allowed_write_files`. A denied directory that
  contains an `allowed_write_files` entry still blocks that file.
- **Non-existent targets are fine**: matching uses non-strict
  `Path.resolve()`, exactly like the rest of this module, so a brand-new
  file (parent directory not yet created) can still match -- this is the
  common case the option exists to support (e.g. an engine writing a fresh
  status file on first run). `write_file`'s existing `mkdir(parents=True)`
  still creates the missing parent directories as usual.
- **Symlinks**: both the write target and each configured entry are
  resolved (symlinks followed to their real target) before comparison, so a
  symlink at the leaf on either side compares by real path -- consistent
  with how `allowed_write_paths`/`denied_write_paths` already behave.
- **Backward compatible**: omitting `allowed_write_files`, or leaving it
  `[]`, is behaviorally identical to configurations that predate this
  option -- no exact-file grants are added, and `allowed_write_paths` /
  `denied_write_paths` behavior is unchanged.
- **Scope of guarantee**: this is tool-level least privilege for
  `write_file`/`edit_file`, not a sandbox or process isolation boundary. A
  session that also has a shell/bash tool can already reach paths this
  module would deny; `allowed_write_files` only narrows what these two
  specific tools will do.

## Dependencies

- `amplifier-core>=1.0.0`

## Contributing

> [!NOTE]
> This project is not currently accepting external contributions, but we're actively working toward opening this up. We value community input and look forward to collaborating in the future. For now, feel free to fork and experiment!

Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.

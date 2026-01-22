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

Read the contents of a file with cat-n style line numbering and pagination support. Automatically handles both text and image files.

**Input:**

- `file_path` (string, required): Absolute path to the file to read
- `offset` (integer, optional): Line number to start reading from (1-indexed). Use for large files.
- `limit` (integer, optional): Number of lines to read. Defaults to 2000. Use for large files.

**Output:**

**For text files:**
- File contents formatted with line numbers (cat -n style)
- Lines longer than 2000 characters are truncated
- Total line count and lines read
- Warning if file is empty

**For image files (.png, .jpg, .jpeg, .gif, .webp, .bmp):**
- ImageBlock structure with base64-encoded image data
- Automatically detects image files by extension
- Compatible with vision-enabled AI providers (Claude, GPT-4V, etc.)
- Size limit: 20MB (configurable)
- Info warning for images >5MB

**Example (text file):**
```
     1→# This is line 1
     2→# This is line 2
     3→# This is line 3
```

**Example (image file):**
```json
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/png",
    "data": "<base64 encoded data>"
  },
  "file_path": "/path/to/image.png",
  "size_bytes": 12345
}
```

**Usage with @mentions:**
```
> Analyze @screenshot.png
> Compare @diagram1.jpg and @diagram2.jpg
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

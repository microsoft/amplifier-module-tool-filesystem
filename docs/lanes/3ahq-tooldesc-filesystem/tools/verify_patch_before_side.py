#!/usr/bin/env python3
"""Verify zc6t's tool-description patches against this repo's head, with ZERO fuzz.

`$0`, offline. This is the check that replaces `patch(1)` / `git apply`, and the
reason it exists is a hard rule in `model_performance-3ahq`:

    If a patch does not apply cleanly at today's head, PORT IT BY HAND and state
    exactly what diverged. NEVER force it with fuzz.

Precedent: lane l4s1 hit "Hunk #1 succeeded at 56 with fuzz 2" and hand-ported
instead, because fuzz is a silent placement decision; elsewhere in the same batch
a fuzzy apply put a diff 147 lines out of position, caught only by grepping for
numbers that should have been there.

TWO THINGS MAKE `patch(1)` THE WRONG TOOL HERE ANYWAY:

1. The patches are against pseudo-files (`read_file.description`), not against
   `.py` source. There is no file for `patch` to target.
2. They were generated from text with NO trailing newline and NO
   `\\ No newline at end of file` marker, so the final removed line and the first
   line added after it SHARE ONE PHYSICAL LINE, e.g.

       -    +Reads up to 2000 lines from the start by default; ...

   `patch` cannot resolve that without guessing.

So both sides are reconstructed here instead, and the split is made
DETERMINISTIC rather than guessed: the suffix after `+` must be *exactly* a line
of the authoritative `<tool>.lean.txt` artifact. If it is not, nothing is split.

WHAT IS ASSERTED
  * BEFORE side == the description at the merge-base, byte for byte
    (proves the patch was cut against text identical to today's head).
  * AFTER side == `<tool>.lean.txt`, byte for byte
    (proves the reconstruction is faithful to the shipped artifact).

`grep` and `glob` have NO target in this repository -- they live in
`amplifier-module-tool-search`. See FINDINGS.md F1. Their AFTER side is still
verified here so the artifacts travel intact to whoever gets that repo.

Usage:
    python3 docs/lanes/3ahq-tooldesc-filesystem/tools/verify_patch_before_side.py [--base <ref>]
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE.parent / "upstream-patches"
REPO = HERE.parents[3]
PKG = "amplifier_module_tool_filesystem"

# Only three of the five patches have a target in this repository.
IN_REPO = {
    "read_file": ("read.py", "ReadTool"),
    "write_file": ("write.py", "WriteTool"),
    "edit_file": ("edit.py", "EditTool"),
}
OUT_OF_REPO = {
    "grep": "amplifier-module-tool-search",
    "glob": "amplifier-module-tool-search",
}

# `<tool>.lean.txt` for the three in-repo tools is single-sourced from the test
# pins; only the two out-of-repo ones are carried in the artifact directory.
LEAN_DIRS = [REPO / "tests" / "pins" / "v1", ARTIFACTS]


def lean_text(tool: str) -> str:
    for d in LEAN_DIRS:
        p = d / f"{tool}.lean.txt"
        if p.exists():
            return p.read_bytes().decode("utf-8")
    raise FileNotFoundError(f"{tool}.lean.txt not found in {[str(d) for d in LEAN_DIRS]}")


def description_at(ref: str, fn: str, cls: str) -> str:
    src = subprocess.run(
        ["git", "show", f"{ref}:{PKG}/{fn}"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls)
    assign = next(
        s
        for s in node.body
        if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", None) == "description"
    )
    return assign.value.value


def reconstruct(patch_text: str, lean: str) -> tuple[str, str, int]:
    lean_lines = {line for line in lean.split("\n") if line}
    before: list[str] = []
    after: list[str] = []
    in_hunk = False
    eof_splits = 0
    for line in patch_text.split("\n"):
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            after.append(line[1:])
        elif line.startswith("-"):
            body = line[1:]
            split_at = None
            for i, ch in enumerate(body):
                if ch == "+" and body[i + 1 :] in lean_lines:
                    split_at = i
            if split_at is None:
                before.append(body)
            else:
                before.append(body[:split_at])
                after.append(body[split_at + 1 :])
                eof_splits += 1
        else:
            content = line[1:] if line.startswith(" ") else line
            before.append(content)
            after.append(content)
    return "\n".join(before), "\n".join(after), eof_splits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="stock ref (default: merge-base with origin/main)")
    args = ap.parse_args()

    base = args.base
    if base is None:
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    print(f"stock ref (merge-base): {base}\n")
    ok = True
    for tool in ["read_file", "write_file", "edit_file", "grep", "glob"]:
        patch = (ARTIFACTS / f"{tool}.patch").read_bytes().decode("utf-8")
        lean = lean_text(tool)
        b, a, splits = reconstruct(patch, lean)
        after_ok = a == lean
        ok &= after_ok
        if tool in IN_REPO:
            fn, cls = IN_REPO[tool]
            before_ok = b == description_at(base, fn, cls)
            ok &= before_ok
            note = f"before==merge_base_stock: {before_ok}"
        else:
            note = f"before: NO TARGET IN THIS REPO (lives in {OUT_OF_REPO[tool]}) -- see FINDINGS.md F1"
        print(
            f"{tool:11s} before={len(b):5d} after={len(a):5d} eof_splits={splits}  "
            f"after==lean.txt: {after_ok}  {note}"
        )

    print("\nPASS -- every patch reconstructed exactly; no fuzz used, none needed." if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

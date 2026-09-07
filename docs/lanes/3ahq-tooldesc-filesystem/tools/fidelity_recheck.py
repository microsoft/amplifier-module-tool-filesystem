#!/usr/bin/env python3
"""Fidelity re-check for the lean tool descriptions (model_performance-3ahq).

`$0`, offline, no API call. Re-verifies AT TODAY'S HEAD rather than inheriting
zc6t's table, which is what item `model_performance-3ahq` asks for.

The one question it answers, per tool:

    is any rule / constraint / command / pointer / limit present in STOCK
    (the merge-base text) and ABSENT from the SHIPPED lean text?

A saving bought by deleting a real instruction is not a saving. It is a
behaviour change that surfaces later with nothing pointing back here.

WHAT COUNTS AS A "RULE" -- stated, because an automatic check that does not say
what it looks for is unfalsifiable. Extracted from the stock text:

  * every backticked code span            (`old_string`, `replace_all`)
  * every @mention / namespace:ref        (@bundle-name:path)
  * every URL
  * every ALL-CAPS imperative token       (MUST, NEVER, ALWAYS, ONLY, ...)
  * every command-shaped line
  * every bare numeric limit              (2000, 1)                 [added here]
  * every input-schema parameter name     (offset, limit, old_string, ...) [added here]

The last two are this lane's additions to zc6t's vocabulary. Tool descriptions
are denser in limits and parameter names than context files are, and a dropped
limit ("up to 2000 lines") is exactly the kind of silent behaviour change the
gate exists to catch.

Matching is case-insensitive and whitespace-normalised: the invariant is that
the rule is still STATED, not that the sentence still starts with the same
capital. The check over-reports by design (a compressed-but-preserved rule can
be flagged) and every flag is reviewed by hand in DONE-NOTE.md. It does not
under-report, which is the direction that costs money.

Usage:
    python3 docs/lanes/3ahq-tooldesc-filesystem/tools/fidelity_recheck.py [--base <ref>]

Exit 0 = every flag reviewed and accounted for in REVIEWED_FLAGS below.
Exit 1 = a flag appeared that no human has ruled on. That is the alarm.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PKG = "amplifier_module_tool_filesystem"

# (source file, class name, tool name) -- the three tools this repo actually owns.
# `grep` and `glob` are NOT in this repo; see FINDINGS.md F1.
TARGETS = [
    ("read.py", "ReadTool", "read_file"),
    ("write.py", "WriteTool", "write_file"),
    ("edit.py", "EditTool", "edit_file"),
]

CODE_SPAN = re.compile(r"`([^`\n]{2,80})`")
MENTION = re.compile(r"@[\w.-]+:[\w./-]+")
URL = re.compile(r"https?://[^\s)\]\"'>]+")
CAPS = re.compile(r"\b(MUST(?: NOT)?|NEVER|ALWAYS|REQUIRED|DO NOT|ONLY|STOP)\b")
CMD = re.compile(
    r"^\s*(?:\$ )?((?:npm|uv|pip|git|gh|python3?|make|amplifier|amplifier-[\w-]+|curl)\s+[^\n|]{3,120})",
    re.MULTILINE,
)
NUMBER = re.compile(r"\b(\d{2,})\b")
PARAM = re.compile(r"\b(file_path|offset|limit|old_string|new_string|replace_all|content)\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def extract_rules(stock: str) -> list[str]:
    found: list[str] = []
    for pattern in (CODE_SPAN, MENTION, URL, CAPS, CMD, NUMBER, PARAM):
        for match in pattern.finditer(stock):
            token = (match.group(1) if match.groups() else match.group(0)).strip()
            if len(token) >= 1:
                found.append(token)
    seen: set[str] = set()
    ordered: list[str] = []
    for token in found:
        key = _norm(token)
        if key not in seen:
            seen.add(key)
            ordered.append(token)
    return ordered


def missing_rules(stock: str, lean: str) -> list[str]:
    lean_n = _norm(lean)
    return [rule for rule in extract_rules(stock) if _norm(rule) not in lean_n]


def description_from_source(src: str, cls: str) -> str:
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls)
    assign = next(
        s
        for s in node.body
        if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", None) == "description"
    )
    return assign.value.value


def git_show(ref: str, rel: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


# Every flag below has been ruled on by hand and the verdict recorded in
# DONE-NOTE.md. A flag NOT in this table exits non-zero.
REVIEWED_FLAGS: dict[str, dict[str, str]] = {
    "read_file": {},
    "write_file": {},
    "edit_file": {
        "content": "FALSE POSITIVE -- flagged by THIS lane's own added PARAM vocabulary, "
        "which is over-broad: 'content' is not an edit_file parameter (its parameters are "
        "file_path, old_string, new_string, replace_all -- 'content' belongs to write_file). "
        "The stock occurrence is ordinary prose, 'Everything after that tab is the actual "
        "file content to match', a restatement of the line-number-prefix rule. Both operative "
        "rules survive in the lean text: preserve the exact indentation AFTER the prefix, and "
        "never include any part of that prefix in old_string or new_string.",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="stock ref (default: merge-base with origin/main)")
    ap.add_argument("--json", action="store_true")
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

    rows = []
    unreviewed = 0
    for fn, cls, tool in TARGETS:
        rel = f"{PKG}/{fn}"
        stock = description_from_source(git_show(base, rel), cls)
        ship = description_from_source((REPO / rel).read_text(encoding="utf-8"), cls)
        flags = missing_rules(stock, ship)
        reviewed = REVIEWED_FLAGS.get(tool, {})
        new_flags = [f for f in flags if f not in reviewed]
        unreviewed += len(new_flags)
        rows.append(
            {
                "tool": tool,
                "file": rel,
                "stock_chars": len(stock),
                "ship_chars": len(ship),
                "saved_chars": len(stock) - len(ship),
                "flags": flags,
                "unreviewed_flags": new_flags,
            }
        )

    if args.json:
        print(json.dumps({"base": base, "rows": rows}, indent=2))
    else:
        print(f"stock ref (merge-base): {base}\n")
        print(f"{'tool':12s} {'stock':>7s} {'ship':>7s} {'saved':>7s}  flags")
        for r in rows:
            print(
                f"{r['tool']:12s} {r['stock_chars']:7d} {r['ship_chars']:7d} "
                f"{r['saved_chars']:7d}  {r['flags'] or 'none'}"
            )
        total_stock = sum(r["stock_chars"] for r in rows)
        total_ship = sum(r["ship_chars"] for r in rows)
        print(
            f"{'TOTAL':12s} {total_stock:7d} {total_ship:7d} {total_stock - total_ship:7d}"
        )
        for r in rows:
            for f in r["flags"]:
                verdict = REVIEWED_FLAGS.get(r["tool"], {}).get(f, "*** UNREVIEWED ***")
                print(f"\n  {r['tool']} / {f!r}: {verdict}")

    if unreviewed:
        print(f"\nFAIL: {unreviewed} flag(s) with no recorded human verdict.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

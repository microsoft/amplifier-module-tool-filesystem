# Upstream patch artifacts (zc6t), carried verbatim

Source: `microsoft/amplifier-foundation` **main**, PR **#372**, commit **`4384805`**,
path `docs/lanes/zc6t-lean-head-ship/patches/tool-descriptions/` (plus
`patches/fidelity-report.json` one level up). Fetched with `git show`, unmodified.

## What is here

| File | Note |
|---|---|
| `read_file.patch`, `write_file.patch`, `edit_file.patch` | **Applied in this PR.** |
| `grep.patch`, `grep.lean.txt`, `glob.patch`, `glob.lean.txt` | **NOT applicable here** — these tools live in `amplifier-module-tool-search`, not this repo. Carried intact for that lane. See `../FINDINGS.md` F1. |
| `fidelity-report.json` | zc6t's original table, for comparison against this lane's re-derived one. Its `grep`/`glob` rows name the wrong repo — that is the defect F1 reports. |

## Where the three in-repo `.lean.txt` files are

Deliberately **not** duplicated here. They are single-sourced at
`tests/pins/v1/<tool>.lean.txt`, where the pin test reads them, so the reference
text and the thing asserting against it cannot drift apart.

## Do not run `patch(1)` on these

They target pseudo-files (`a/read_file.description`) that exist in no repository,
and four of the five concatenate the final removed line with the first added line
because they were generated without a trailing newline. Use
`../tools/verify_patch_before_side.py`, which reconstructs both sides with a
deterministic split and no fuzz. Full explanation in `../FINDINGS.md` F4.

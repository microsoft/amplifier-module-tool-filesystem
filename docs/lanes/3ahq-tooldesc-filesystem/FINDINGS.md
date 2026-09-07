# 3ahq-tooldesc-filesystem — findings

Lane `3ahq-tooldesc-filesystem` · item `model_performance-3ahq` · 2026-09-07
Repo: `microsoft/amplifier-module-tool-filesystem`, branch `lane/3ahq-tooldesc-filesystem`
Stock ref (merge-base with `origin/main`): `aeadf4e3d1e2308415166ebccdad7fda17d6db04`

---

## F1 — GOAL DEFECT: `grep` and `glob` are not in this repository, and never were

**Reported against the goal, not absorbed**, per GOAL.md's own clause:

> every option this goal offers you must have at least one target inside the paths
> it says you own. If the only way to satisfy a deliverable is to write a file
> outside your worktree (another repo …), that is a DEFECT IN THIS GOAL, not a
> task. Report it against the goal, ship the patch as an artifact under your
> ARTIFACT ROOT, and resolve — do not edit another repo.

GOAL.md and the work item both scope this lane to five tools:
`read_file`, `write_file`, `edit_file`, **`grep`**, **`glob`**.

This repository ships **three**. `amplifier_module_tool_filesystem/__init__.py`
mounts exactly `ReadTool`, `WriteTool`, `EditTool`; there is no `grep.py`, no
`glob.py`, and no reference to either anywhere outside the copy of GOAL.md
sitting in the worktree.

`grep` and `glob` live in a **different repository**, `amplifier-module-tool-search`:

```
~/.amplifier/cache/amplifier-module-tool-search-40722917c1f96bb4/
├── pyproject.toml                       name = "amplifier-module-tool-search"
│                                        description = "Reference tool module -
│                                        Search tools (grep/glob) for Amplifier"
└── amplifier_module_tool_search/
    ├── grep.py    GrepTool.description  1365 chars
    └── glob.py    GlobTool.description   904 chars
```

**Provenance of the error — it is upstream of this lane and upstream of the item.**
zc6t's generator hard-codes the wrong repo in its own source. From
`docs/lanes/zc6t-lean-head-ship/tools/fidelity_diff.py` on foundation main:

```python
"grep": ("amplifier-module-tool-filesystem", "amplifier_module_tool_filesystem"),
"glob": ("amplifier-module-tool-filesystem", "amplifier_module_tool_filesystem"),
```

That map is what produced `fidelity-report.json`'s `"repo":
"amplifier-module-tool-filesystem"` rows for both tools, which the item copied
verbatim into its five-tool table, which GOAL.md then copied again. It is a
single mistake propagated three times, never re-derived. zc6t never had either
repo on disk (its F1 lists both as "not cloned on this host"), so nothing in that
chain ever checked.

**What this lane did instead of editing another repo.** Both patches are carried
intact under `upstream-patches/` with their `.lean.txt` texts, verified
reconstructible (below), and are drop-in for whoever gets
`amplifier-module-tool-search`. Nothing outside this worktree was touched.

**Consequence for the saving.** This lane realises **1,071 chars of the 3,926**
in zc6t's total, not the 1,783 the five-tool framing implies. The
`grep` + `glob` remainder (**676 chars**, 356 + 320) is unreachable from here by
construction, not by underperformance.

**What would close it:** one more sibling lane on `amplifier-module-tool-search`,
sequenced ahead of that repo's `j1e6-ci-*` lane for the same reason this one is
sequenced ahead of `j1e6-ci-tool-filesystem` — the pin test is the thing worth
guarding, so it must exist before CI runs.

---

## F2 — GOAL DEFECT: the "+450 chars" `edit_file` restoration is a misread; the real figure is ~35

GOAL.md says, three times and in bold:

> ONE genuine loss — `edit_file`, restored in-repo at **+450 chars** and pinned.
> Read that report before you touch anything, and carry the restoration forward.

**The +450 does not belong to `edit_file`.** zc6t's FINDINGS F4 is explicit, and
the two claims sit in adjacent paragraphs of the same section:

| zc6t F4 says | About |
|---|---|
| "REAL WEAKENING, not a loss … Recommendation for the `tool-filesystem` lane: **restore the qualifier at a cost of ~35 chars** against that description's 458-char saving. **Out of this repo — advisory only.**" | `edit_file` — **this lane** |
| "**Byte delta of the restoration: +450 chars** (169 + 281) … pinned by `TestFidelityBeatsCompression`" | **span 9** — `bundles/anchors/context/system.md` + `bundles/anchors-amp-dev/context/amplifier-ecosystem.md`, a *context file* in *foundation*, already shipped in PR #372 |

Two different targets, two different repos, two different numbers. The goal
merged them.

**Why it matters rather than being pedantry.** `edit_file`'s entire measured
saving is 458 chars. Carrying a "+450 char restoration" forward would have
cancelled 98% of it and left a lane reporting an 8-char win as success. Taken at
face value the instruction destroys the deliverable it is asking for.

**What was actually done:** the qualifier is restored at **+36 chars**
(887 → 923; saving 458 → 422), which is zc6t's "~35" to within one character —
the difference being that this lane reused the exact phrasing v1 already uses in
`write_file` so the two descriptions agree, rather than inventing a third
wording. See F3.

---

## F3 — fidelity re-verified at today's head: 1 flag, reviewed, false positive

Re-derived, not inherited — `tools/fidelity_recheck.py`, `$0`, offline. Stock is
read from the merge-base with `git show`; lean is read from the working tree.

| tool | stock | shipped | saved | flags |
|---|---:|---:|---:|---|
| `read_file` | 1,074 | 725 | **349** | none |
| `write_file` | 867 | 567 | **300** | none |
| `edit_file` | 1,345 | 923 | **422** | `content` — false positive |
| **TOTAL** | **3,286** | **2,215** | **1,071** | |

The one flag, `content`, was raised by **this lane's own added vocabulary**
(parameter names), which zc6t's extractor did not check. It is over-broad:
`content` is not an `edit_file` parameter — that tool takes `file_path`,
`old_string`, `new_string`, `replace_all`; `content` belongs to `write_file`. The
stock occurrence is ordinary prose ("Everything after that tab is the actual file
content to match"), a restatement of the line-number-prefix rule. Both operative
rules survive in the lean text. Verdict recorded in `REVIEWED_FLAGS`; the script
**exits non-zero on any flag with no recorded human verdict**, so a future
weakening cannot pass silently.

**zc6t's `ALWAYS` flag on `edit_file` reproduces exactly** when the restoration is
removed — see `evidence/ratchet-demo.txt` step 4. That is the check verifying
itself against a known answer rather than asserting its own correctness.

**The restoration, verbatim.**

```
stock:    ALWAYS prefer editing existing files in the codebase. NEVER write new
          files unless explicitly required.
v1 lean:  Prefer editing existing files over creating new ones.
shipped:  ALWAYS prefer editing an existing file; NEVER write new files unless
          explicitly required.
```

The shipped clause is byte-identical to the one v1 already uses in `write_file`,
which zc6t did **not** flag. So the two descriptions now state the same rule the
same way, and the flagged asymmetry between them is gone.

---

## F4 — the patch artifacts cannot be applied by `patch(1)` at all, for two reasons

Neither is a divergence at today's head — the text matches byte for byte — but
both would have forced a guess, which is the failure mode the item names.

**(a) They target pseudo-files.** The diffs are `--- a/read_file.description` →
`+++ b/read_file.description`. No such file exists in any repo; the text lives
inside a Python triple-quoted string in `read.py`. There is nothing for `patch`
to open.

**(b) The final removed line and the first added line share a physical line.**
The patches were generated from text with no trailing newline and no
`\ No newline at end of file` marker, so e.g. `read_file.patch` line 22 reads:

```
-    +Reads up to 2000 lines from the start by default; pass offset (1-indexed) …
```

— one physical line meaning "remove `    `" and "add `Reads up to 2000 …`". Four
of the five patches carry exactly one such line (`grep` is the exception).
`patch(1)` cannot resolve that without guessing, and a guess here is precisely the
silent placement decision that put a diff 147 lines out of position elsewhere in
this batch.

**What was done instead.** `tools/verify_patch_before_side.py` reconstructs both
sides and makes the split **deterministic rather than guessed**: the suffix after
`+` must be *exactly* a line of the authoritative `<tool>.lean.txt`, or nothing is
split. It then asserts, byte for byte:

```
stock ref (merge-base): aeadf4e3d1e2308415166ebccdad7fda17d6db04

read_file   before= 1074 after=  725 eof_splits=1  after==lean.txt: True  before==merge_base_stock: True
write_file  before=  867 after=  567 eof_splits=1  after==lean.txt: True  before==merge_base_stock: True
edit_file   before= 1345 after=  887 eof_splits=1  after==lean.txt: True  before==merge_base_stock: True
grep        before= 1364 after= 1009 eof_splits=0  after==lean.txt: True  before: NO TARGET IN THIS REPO
glob        before=  904 after=  584 eof_splits=1  after==lean.txt: True  before: NO TARGET IN THIS REPO

PASS -- every patch reconstructed exactly; no fuzz used, none needed.
```

**All three in-repo before-sides are byte-identical to today's head.** The two
commits that landed after zc6t cut these patches (`51aaf2d` line-ending
preservation, `aeadf4e` `file_path` dedup) did not move the description text.
**Nothing diverged, nothing was hand-ported, no fuzz was used or needed.**

---

## F5 — advisory for the `amplifier-module-tool-search` lane: the `grep` patch loses a trailing newline

Checked while verifying the two out-of-repo artifacts against the installed
package (read-only, from `~/.amplifier/cache/`):

| tool | patch before-side | installed `description` | equal |
|---|---:|---:|---|
| `glob` | 904 | 904 | **yes** |
| `grep` | 1,364 | 1,365 | **no — off by one** |

The difference is entirely at the tail: the installed text ends
`…to know how many exist beyond the limit\n`, the patch's before-side ends
`…to know how many exist beyond the limit` with the final newline dropped —
the same missing-EOF-newline artifact as F4(b), landing on a `-` line instead of
between two. `fidelity-report.json` records `grep` `stock_chars: 1365`, which
matches the installed text and **not** its own patch.

Consequence for that lane: a naive `patch` would silently drop a trailing
newline, and the resulting `saved_chars` would be 356 as recorded only if the
newline is preserved. Reconstruct-and-compare rather than apply, same as here.

---

## F6 — this repo has NO CI, stated plainly

`.github/workflows` does not exist:

```
$ ls -la .github/workflows
ls: cannot access '.github/workflows': No such file or directory
```

There is no green CI run to point at and this PR does not imply one. The
evidence is the local suite (`evidence/test-suite.txt`, **30 passed**, 22
pre-existing + 8 new) and the fail-before/pass-after ratchet demonstration
(`evidence/ratchet-demo.txt`). This repo is one of the 18 in `j1e6`; that CI lane
is sequenced **after** this one deliberately, so that CI executes a suite which
already contains the pin rather than one that predates it.

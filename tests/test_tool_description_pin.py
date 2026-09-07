"""Byte-for-byte pins on the three tool descriptions this module ships.

WHY THIS EXISTS. A tool description renders into the tool-schema block of
*every* request of *every* session, whether or not the tool is called. The lean
rewrites pinned here were measured (`model_performance-g7h3`: the full lean head
at -13.57% $/task, 95% CI [-22.27%, -4.86%], all three pre-registered estimators
excluding zero) and then sat unapplied for three cycles. Nothing but a pin stops
a later "just make the docs friendlier" edit from silently buying that cost back.

WHAT IS PINNED, and against what:

  * `tests/pins/<tool>.description.txt` is the SHIPPED text, byte for byte.
  * `tests/pins/v1/<tool>.lean.txt` is zc6t's v1 lean text, copied verbatim from
    `docs/lanes/zc6t-lean-head-ship/patches/tool-descriptions/` on
    `microsoft/amplifier-foundation` main (PR #372, 4384805).

`read_file` and `write_file` ship the v1 text unchanged -- pinned equal.

`edit_file` deliberately does NOT. zc6t's fidelity sweep found exactly one real
weakening across all 23 targets: the v1 `edit_file` text softened stock's
"ALWAYS prefer editing existing files in the codebase. NEVER write new files
unless explicitly required." into "Prefer editing existing files over creating
new ones.", dropping both the imperative force and the `unless explicitly
required` qualifier. zc6t's own FINDINGS F4 recommends restoring it here at a
cost of ~35 chars. This module restores it (+36 chars, 887 -> 923) using the
same phrasing v1 already uses in `write_file`, so the two agree.

`test_edit_file_restoration_is_the_only_deviation_from_v1` pins that deviation
as a deviation: it asserts the shipped text differs from v1 in exactly that one
clause and nowhere else. Fidelity beats compression at every point of conflict,
so the cost is paid and stated rather than hidden -- and cannot be quietly
un-restored by a later compression pass.

TO CHANGE A DESCRIPTION ON PURPOSE: edit the source, then regenerate the pin
    python3 -c "import pathlib,ast;..."   # or simply copy the new text in
and update the sha256 below. Both must be changed deliberately; that is the
point.
"""

import hashlib
from pathlib import Path

import pytest

from amplifier_module_tool_filesystem import EditTool
from amplifier_module_tool_filesystem import ReadTool
from amplifier_module_tool_filesystem import WriteTool

PINS = Path(__file__).parent / "pins"

# (tool class, tool name, sha256 of the SHIPPED description, char count)
CASES = [
    (ReadTool, "read_file", "a3a6c31fa1acf3617bb22b7fc3de5650a7ab733a3ec5c683b25e0289145de0a5", 725),
    (WriteTool, "write_file", "319efcd238bbbc0bdc38e42b283f33634b25d588f42867ae9523b6a71fa276bb", 567),
    (EditTool, "edit_file", "e80c838e9c20e0af39ec43d38fbddfedcd012b99a6259c4ac5525683474b1580", 923),
]

# The one clause zc6t flagged as a REAL weakening, and its restoration.
V1_WEAKENED = "Prefer editing existing files over creating new ones."
RESTORED = "ALWAYS prefer editing an existing file; NEVER write new files unless explicitly required."


def _pin(name: str) -> str:
    """Read a pin as exact bytes. No strip(), no newline coercion."""
    return (PINS / f"{name}.description.txt").read_bytes().decode("utf-8")


def _v1(name: str) -> str:
    return (PINS / "v1" / f"{name}.lean.txt").read_bytes().decode("utf-8")


@pytest.mark.parametrize("tool_cls,name,digest,chars", CASES, ids=[c[1] for c in CASES])
def test_description_matches_pin_byte_for_byte(tool_cls, name, digest, chars):
    """The shipped description is byte-identical to its pin file."""
    actual = tool_cls.description
    assert actual == _pin(name), (
        f"{name}'s description no longer matches tests/pins/{name}.description.txt. "
        "If the change is intentional, update the pin and its sha256 in this file."
    )
    assert len(actual) == chars
    assert hashlib.sha256(actual.encode("utf-8")).hexdigest() == digest


@pytest.mark.parametrize("name", ["read_file", "write_file"])
def test_ships_the_v1_lean_text_unchanged(name):
    """read_file and write_file ship zc6t's v1 lean text with no deviation."""
    assert _pin(name) == _v1(name)


def test_edit_file_restoration_is_the_only_deviation_from_v1():
    """edit_file deviates from v1 in exactly one clause -- the fidelity restoration.

    This is the `TestFidelityBeatsCompression` role for this repo: it pins the
    restoration so a later compression pass cannot quietly drop it again, and it
    pins that nothing ELSE was changed while the door was open.
    """
    v1, shipped = _v1("edit_file"), _pin("edit_file")

    assert V1_WEAKENED in v1, "v1 no longer contains the weakened clause; re-read zc6t F4"
    assert V1_WEAKENED not in shipped
    assert RESTORED in shipped

    # Byte-for-byte: v1 with that one substitution applied IS the shipped text.
    assert v1.replace(V1_WEAKENED, RESTORED) == shipped
    assert len(shipped) - len(v1) == 36


def test_restored_clause_survives_in_the_live_description():
    """The imperative force and the qualifier are both present, not just the gist."""
    assert RESTORED in EditTool.description
    for token in ("ALWAYS", "NEVER", "unless explicitly required"):
        assert token in EditTool.description
        assert token in WriteTool.description


def test_no_description_regrew_a_bulleted_usage_block():
    """A cheap ratchet: the stock shape ('Usage:' + a '- ' bullet list) is gone.

    Not a substitute for the byte pins above -- a guard against the specific
    regression of someone re-expanding a description back toward the stock form.
    """
    for tool_cls, name, _digest, _chars in CASES:
        assert "\nUsage:\n" not in tool_cls.description, name

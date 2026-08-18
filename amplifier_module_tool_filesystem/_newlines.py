"""Line-ending-preserving UTF-8 text I/O for the filesystem tools.

Python's text-mode write (`open(..., "w")`, `Path.write_text`) translates every
``\\n`` in the string to ``os.linesep`` on write -- which is ``\\r\\n`` on native
Windows. For an *editing* tool that must be a good citizen of an existing file,
that is a real defect on every platform:

* On native Windows, editing an LF-only file (the default in most Unix-targeted
  repos, Docker projects, and anything with ``* text eol=lf`` in .gitattributes)
  rewrites the file's ENTIRE line-ending convention to CRLF -- not just the
  edited region -- producing a massive spurious whole-file diff on every edit.
* On POSIX, the mirror image: editing a CRLF file silently strips it to LF,
  because ``os.linesep`` is ``\\n`` there.

The read side has the matching hazard: default text-mode read performs universal
newline translation, so callers can't tell what the file actually used on disk.

These helpers read and write **bytes** explicitly (no platform newline
translation at all), detect the file's existing convention on read, and restore
it on write. For an LF-only file the written bytes are identical on every
platform to what the previous ``write_text`` produced on POSIX -- so the common
case is unchanged; only the previously-broken cases are fixed.
"""

from __future__ import annotations

from pathlib import Path


def detect_newline(text: str) -> str:
    """Return the dominant on-disk line ending: ``\\r\\n``, ``\\r``, or ``\\n``.

    ``\\n`` is the default when the text has no line breaks (or is LF-only).
    """
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def read_text_preserving(path: Path) -> tuple[str, str]:
    """Read UTF-8 text, returning ``(lf_normalized_text, original_newline)``.

    The returned text always uses ``\\n`` so callers can match/replace in a
    single convention -- identical to what the previous
    ``read_text(encoding="utf-8")`` produced. ``original_newline`` is what the
    file actually used on disk, for restoring on write.
    """
    raw = path.read_bytes().decode("utf-8")
    newline = detect_newline(raw)
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, newline


def write_text_preserving(path: Path, text: str, newline: str = "\n") -> int:
    """Write UTF-8 text using ``newline``, with NO platform translation.

    ``text`` is first normalized to ``\\n`` (so any stray CRLF introduced by a
    replacement can't double up into ``\\r\\r\\n``), then every ``\\n`` becomes
    ``newline``. With the default ``newline="\\n"`` the bytes written are
    identical to a plain LF write on every platform.

    Returns the number of bytes written.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    data = normalized.replace("\n", newline).encode("utf-8")
    path.write_bytes(data)
    return len(data)

"""Image reads never obtain more authority than ordinary filesystem reads."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from amplifier_module_tool_filesystem.read import ReadTool

SECURE_OPENS = (os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
                and hasattr(os, "O_DIRECTORY")
                and (hasattr(os, "O_PATH") or hasattr(os, "O_SEARCH")))


def coordinator(capability=None, mention=None):
    return SimpleNamespace(
        hooks=SimpleNamespace(emit=AsyncMock()),
        get_capability=lambda key: (
            mention if key == "mention_resolver" else capability
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["absolute", "relative", "traversal", "symlink", "mention"])
@pytest.mark.parametrize("allowed", [None, ["."]])
async def test_denied_image_never_opens_or_ingests(tmp_path, monkeypatch, kind, allowed):
    private = tmp_path / "private"
    private.mkdir()
    target = private / "secret.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\nprivate-pixel-bytes")
    (tmp_path / "alias").symlink_to(private, target_is_directory=True)
    cap = SimpleNamespace(ingest=AsyncMock())
    host = coordinator(cap, SimpleNamespace(resolve=lambda _: target))
    tool = ReadTool({
        "working_dir": str(tmp_path), "allowed_read_paths": allowed,
        "denied_read_paths": ["private"],
    }, host)
    requests = {
        "absolute": str(target), "relative": "private/secret.png",
        "traversal": "other/../private/secret.png",
        "symlink": "alias/secret.png", "mention": "@bundle:secret",
    }

    def forbidden(*args, **kwargs):
        pytest.fail("denied files must not be opened")

    monkeypatch.setattr(os, "open", forbidden)
    result = await tool.execute({"file_path": requests[kind]})
    assert not result.success
    assert "private-pixel-bytes" not in str(result)
    cap.ingest.assert_not_called()
    host.hooks.emit.assert_not_called()


def test_authorized_regular_descriptor_and_symlink(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"original")
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    tool = ReadTool({"allowed_read_paths": [str(tmp_path)]}, coordinator())
    with tool._open_authorized(alias) as (source, secure):
        assert source.read() == b"original"
        assert secure is SECURE_OPENS
    assert source.closed


@pytest.mark.skipif(not SECURE_OPENS, reason="descriptor-relative race primitives unavailable")
@pytest.mark.parametrize("replacement", ["leaf_symlink", "leaf_file", "parent_symlink"])
def test_replacement_races_never_read_payload(tmp_path, monkeypatch, replacement):
    public, private = tmp_path / "public", tmp_path / "private"
    public.mkdir()
    private.mkdir()
    target = public / "image.png"
    target.write_bytes(b"public")
    secret = private / "image.png"
    secret.write_bytes(b"private")
    tool = ReadTool({"allowed_read_paths": [str(public)],
                     "denied_read_paths": [str(private)]}, coordinator())
    original_open = os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        trigger = "public" if replacement == "parent_symlink" else "image.png"
        if path == trigger and not swapped:
            swapped = True
            if replacement == "parent_symlink":
                public.rename(tmp_path / "previous")
                public.symlink_to(private, target_is_directory=True)
            else:
                target.unlink()
                if replacement == "leaf_symlink":
                    target.symlink_to(secret)
                else:
                    target.write_bytes(b"replacement")
        return original_open(path, flags, *args, **kwargs)

    # The wrapper is still the platform's directory-relative open operation.
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {racing_open})
    monkeypatch.setattr(os, "open", racing_open)
    monkeypatch.setattr(os, "fdopen", lambda *a, **k: pytest.fail("must not read"))
    with pytest.raises((OSError, ValueError)):
        with tool._open_authorized(target):
            pytest.fail("replaced file must not be admitted")
    assert swapped


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_nonregular_file_rejected_before_open(tmp_path, monkeypatch):
    target = tmp_path / "pipe.png"
    os.mkfifo(target)
    tool = ReadTool({}, coordinator())
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("must not open FIFO"))
    with pytest.raises(ValueError, match="regular"):
        with tool._open_authorized(target):
            pytest.fail("FIFO must not be admitted")


@pytest.mark.asyncio
async def test_ordinary_text_pagination_empty_and_listing_unchanged(tmp_path):
    host = coordinator()
    tool = ReadTool({"working_dir": str(tmp_path)}, host)
    (tmp_path / "text").write_bytes(b"one\r\ntwo\r\nthree")
    (tmp_path / "empty").touch()
    result = await tool.execute({"file_path": "text", "offset": 2, "limit": 1})
    assert result.success
    assert result.output == {
        "file_path": str(tmp_path / "text"), "content": "     2\ttwo",
        "total_lines": 3, "lines_read": 1, "offset": 2,
    }
    empty = await tool.execute({"file_path": "empty"})
    assert empty.output["warning"] == "File exists but has empty contents"
    directory = await tool.execute({"file_path": "."})
    assert directory.success and directory.output["entry_count"] == 2


@pytest.mark.parametrize("header,suffix,expected", [
    (b"\x89PNG\r\n\x1a\n", ".dat", "image/png"),
    (b"\xff\xd8\xff", ".dat", "image/jpeg"),
    (b"not an image", ".PNG", "image/png"),
    (b"not an image", ".jpeg", "image/jpeg"),
    (b"GIF89a", ".dat", "unsupported"),
    (b"RIFFxxxxWEBP", ".dat", "unsupported"),
    (b"ordinary text", ".txt", None),
])
def test_image_detection_is_not_extension_only(header, suffix, expected):
    assert ReadTool._image_kind(header, Path("file" + suffix)) == expected


class RecordingMedia:
    """Structural boundary fixture, not a substitute for decoder conformance."""

    version = 1

    def __init__(self, *, enabled=True, refusal=None):
        self.enabled = enabled
        self.refusal = refusal
        self.calls = []
        self.publish = AsyncMock(side_effect=AssertionError("producer must not publish"))
        self.resolve = self.validate = self.prepare_request = lambda *a, **k: None

    def report(self, origin, **kwargs):
        assert origin == "tool-filesystem.read_file"
        assert kwargs == {
            "event": "consumer-ready", "outcome": "ready",
            "details": {"contract": 1, "role": "producer"},
        }
        return {"enabled": self.enabled}

    async def ingest(self, value, *, source_format, origin, policy):
        self.source = value["stream"]
        self.calls.append((source_format, origin, policy))
        if self.refusal:
            raise self.refusal
        data = self.source.read(4096)
        self.observed = data
        ref = {
            "v": 1, "session_id": "owner", "sha256": hashlib.sha256(data).hexdigest(),
            "mime": value["mime"], "bytes": len(data), "width": 3, "height": 2,
            "provenance": {
                "kind": "tool", "session_id": "owner", "id": "actual-call",
                "created_at": "2026-01-01T00:00:00+00:00", "expires_at": None,
            },
        }
        return {"value": ref, "staged_refs": [ref]}


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="image emission requires secure opens")
@pytest.mark.parametrize("kind", ["relative", "mention", "symlink"])
@pytest.mark.parametrize("header,mime", [
    (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
])
async def test_image_stream_identity_ref_only_and_no_publication(tmp_path, kind, header, mime):
    data = header + b"original-encoded-observation"
    target = tmp_path / "image.bin"
    target.write_bytes(data)
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    media = RecordingMedia()
    host = coordinator(media, SimpleNamespace(resolve=lambda _: target))
    tool = ReadTool({"working_dir": str(tmp_path)}, host)
    request = {"relative": "image.bin", "mention": "@bundle:image", "symlink": "alias"}[kind]
    result = await tool.execute({
        "file_path": request, "origin": {"id": "forged-user-call"},
        "policy": {"max_bytes": 10**30},
    })
    assert result.success, result
    assert media.calls == [("image-bytes", None, None)]
    assert media.observed == data and media.source.closed
    ref = result.output["experimental.media.v1"]["refs"][0]
    assert ref["mime"] == mime
    assert ref["sha256"] == hashlib.sha256(data).hexdigest()
    assert (ref["width"], ref["height"], ref["bytes"]) == (3, 2, len(data))
    assert ref["provenance"]["id"] == "actual-call"
    assert result.model_dump().get("content") is None
    serialized = json.dumps(result.model_dump())
    assert "original-encoded-observation" not in serialized
    assert "forged-user-call" not in serialized
    media.publish.assert_not_called()
    host.hooks.emit.assert_awaited_once()
    assert target.read_bytes() == data


@pytest.mark.asyncio
@pytest.mark.parametrize("media", [
    None, SimpleNamespace(version=2), SimpleNamespace(version=True),
    SimpleNamespace(version=1, ingest=AsyncMock()), RecordingMedia(enabled=False),
])
async def test_absent_incompatible_or_disabled_media_never_ingests(tmp_path, media):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\nprivate-pixels")
    result = await ReadTool({}, coordinator(media)).execute({"file_path": str(target)})
    assert not result.success
    assert "no pixels were sent" in result.output["content"]
    assert "experimental.media.v1" not in result.output
    assert "private-pixels" not in str(result)
    if isinstance(media, RecordingMedia):
        assert media.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("pagination", [{"offset": 1}, {"limit": 2000}, {"offset": None}])
async def test_image_pagination_is_actionable_even_explicit_defaults(tmp_path, pagination):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    media = RecordingMedia()
    result = await ReadTool({}, coordinator(media)).execute(
        {"file_path": str(target), **pagination}
    )
    assert not result.success
    assert "retry without" in result.output["content"]
    assert media.calls == []


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="image staging requires secure opens")
@pytest.mark.parametrize("message", [
    "corrupt PNG", "truncated JPEG", "decompression bomb", "encoded size limit",
    "decoder unavailable", "missing trusted origin", "animated PNG",
])
async def test_media_validation_refusals_are_not_raw_fallback(tmp_path, message):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    media = RecordingMedia(refusal=ValueError(message + ": private-staging/secret"))
    host = coordinator(media)
    result = await ReadTool({}, host).execute({"file_path": str(target)})
    assert not result.success
    assert "no pixels were sent" in result.output["content"]
    assert "private-staging" not in str(result)
    assert "experimental.media.v1" not in result.output
    assert media.source.closed
    host.hooks.emit.assert_not_called()


@pytest.mark.asyncio
async def test_unqualified_platform_never_ingests(tmp_path, monkeypatch):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    media = RecordingMedia()
    monkeypatch.setattr(os, "supports_dir_fd", set())
    result = await ReadTool({}, coordinator(media)).execute({"file_path": str(target)})
    assert not result.success
    assert "unsupported on this platform" in result.output["content"]
    assert media.calls == []


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="image staging requires secure opens")
async def test_cancellation_closes_descriptor_without_publication(tmp_path):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    media = RecordingMedia(refusal=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await ReadTool({}, coordinator(media)).execute({"file_path": str(target)})
    assert media.source.closed
    media.publish.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_format_truthful_without_decoder(tmp_path):
    target = tmp_path / "image.gif"
    target.write_bytes(b"GIF89a")
    media = RecordingMedia()
    result = await ReadTool({}, coordinator(media)).execute({"file_path": str(target)})
    assert not result.success
    assert "only static PNG/JPEG" in result.output["content"]
    assert media.calls == []


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="image staging requires secure opens")
async def test_source_mutation_during_staging_emits_no_ref(tmp_path):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\noriginal")
    media = RecordingMedia()
    ingest = media.ingest

    async def mutate(*args, **kwargs):
        result = await ingest(*args, **kwargs)
        target.write_bytes(b"changed-in-place")
        return result

    media.ingest = mutate
    host = coordinator(media)
    result = await ReadTool({}, host).execute({"file_path": str(target)})
    assert not result.success
    assert "source changed" in result.output["content"]
    assert "experimental.media.v1" not in result.output
    assert media.source.closed
    media.publish.assert_not_called()
    host.hooks.emit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="image staging requires secure opens")
async def test_oversize_sparse_file_is_not_materialized_by_reader(tmp_path):
    target = tmp_path / "image.png"
    with target.open("wb") as source:
        source.write(b"\x89PNG\r\n\x1a\n")
        source.truncate(2**30)
    media = RecordingMedia()

    async def bounded_ingest(value, **kwargs):
        source = media.source = value["stream"]
        # The real capability selects its bound policy and may inspect fstat;
        # the filesystem must pass a stream, never source.read() / source bytes.
        assert os.fstat(source.fileno()).st_size == 2**30
        assert len(source.read(33)) == 33
        raise ValueError("host byte limit")

    media.ingest = bounded_ingest
    result = await ReadTool({}, coordinator(media)).execute({"file_path": str(target)})
    assert not result.success
    assert "no pixels were sent" in result.output["content"]
    assert media.source.closed


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="descriptor-relative race primitives unavailable")
async def test_aba_alias_denial_uses_held_inode_not_decoy_path(tmp_path, monkeypatch):
    target, secret = tmp_path / "target.png", tmp_path / "secret.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\npublic")
    secret.write_bytes(b"\x89PNG\r\n\x1a\nprivate-pixels")
    decoy = tmp_path / "decoy"
    target.rename(decoy)
    target.hardlink_to(decoy)
    media = RecordingMedia()
    host = coordinator(media)
    reader = ReadTool({"denied_read_paths": [str(secret)]}, host)
    original_check = reader._is_allowed
    checks = 0

    def swap_after_authorization(path):
        nonlocal checks
        result = original_check(path)
        checks += 1
        # Outer execute + helper initial authorization see the decoy; snapshots
        # and the opened leaf see a hardlink to the denied physical inode.
        if checks == 2:
            target.unlink()
            target.hardlink_to(secret)
        return result

    monkeypatch.setattr(reader, "_is_allowed", swap_after_authorization)
    result = await reader.execute({"file_path": str(target)})
    assert not result.success
    assert media.calls == []
    assert "private-pixels" not in str(result)
    host.hooks.emit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="descriptor-relative race primitives unavailable")
async def test_policy_root_retarget_during_open_is_refused(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    root = tmp_path / "policy-root"
    root.symlink_to(allowed, target_is_directory=True)
    other = tmp_path / "other"
    other.mkdir()
    reader = ReadTool({"allowed_read_paths": [str(root)]}, coordinator(RecordingMedia()))
    original_open = os.open

    def change_root(path, flags, *args, **kwargs):
        if path == "image.png":
            root.unlink()
            root.symlink_to(other, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {change_root})
    monkeypatch.setattr(os, "open", change_root)
    result = await reader.execute({"file_path": str(target)})
    assert not result.success
    assert reader.coordinator.get_capability("").calls == []


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="Linux search-only handle regression")
async def test_text_in_search_only_directory_does_not_require_listing(tmp_path):
    directory = tmp_path / "search-only"
    directory.mkdir()
    target = directory / "text"
    target.write_text("readable")
    directory.chmod(0o111)
    try:
        assert target.read_text() == "readable"
        result = await ReadTool({}, coordinator()).execute({"file_path": str(target)})
        assert result.success and "readable" in result.output["content"]
    finally:
        directory.chmod(0o700)


@pytest.mark.asyncio
@pytest.mark.skipif(not SECURE_OPENS, reason="image staging requires secure opens")
@pytest.mark.parametrize("mutation", ["missing_refs", "different_refs", "mime", "extra"])
async def test_malformed_ingestion_result_emits_no_ref(tmp_path, mutation):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    media = RecordingMedia()
    ingest = media.ingest

    async def malformed(*args, **kwargs):
        value = await ingest(*args, **kwargs)
        if mutation == "missing_refs":
            del value["staged_refs"]
        elif mutation == "different_refs":
            value["staged_refs"] = []
        elif mutation == "mime":
            value["value"]["mime"] = "image/jpeg"
        else:
            value["value"]["binary"] = b"private-bytes"
        return value

    media.ingest = malformed
    host = coordinator(media)
    result = await ReadTool({}, host).execute({"file_path": str(target)})
    assert not result.success
    assert "experimental.media.v1" not in result.output
    assert "private-bytes" not in str(result)
    assert media.source.closed
    host.hooks.emit.assert_not_called()


@pytest.mark.skipif(not SECURE_OPENS, reason="descriptor-relative primitives unavailable")
@pytest.mark.parametrize("failure", ["open", "body"])
def test_all_descriptors_closed_after_failure(tmp_path, monkeypatch, failure):
    target = tmp_path / "file"
    target.write_text("contents")
    opened = []
    original_open = os.open

    def record_open(path, flags, *args, **kwargs):
        if failure == "open" and path == "file":
            raise OSError("injected leaf failure")
        fd = original_open(path, flags, *args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {record_open})
    monkeypatch.setattr(os, "open", record_open)
    with pytest.raises(OSError):
        with ReadTool({}, coordinator())._open_authorized(target):
            raise OSError("injected consumer failure")
    assert opened
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.asyncio
async def test_no_search_handle_primitives_keeps_text_but_disables_images(tmp_path, monkeypatch):
    text, image = tmp_path / "text", tmp_path / "image.png"
    text.write_text("readable")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    for name in ("O_PATH", "O_SEARCH"):
        monkeypatch.delattr(os, name, raising=False)
    media = RecordingMedia()
    reader = ReadTool({}, coordinator(media))
    assert (await reader.execute({"file_path": str(text)})).success
    result = await reader.execute({"file_path": str(image)})
    assert not result.success and "no pixels were sent" in result.output["content"]
    assert media.calls == []


@pytest.mark.asyncio
async def test_unsearchable_denied_root_preserves_text_not_media(tmp_path, monkeypatch):
    denied = tmp_path / "restricted" / "secret"
    text, image = tmp_path / "text", tmp_path / "image.png"
    text.write_text("readable")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    original_stat = Path.stat

    def inaccessible(path, *args, **kwargs):
        if path == denied:
            raise PermissionError("unsearchable policy root")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", inaccessible)
    media = RecordingMedia()
    reader = ReadTool({"denied_read_paths": [str(denied)]}, coordinator(media))
    assert (await reader.execute({"file_path": str(text)})).success
    result = await reader.execute({"file_path": str(image)})
    assert not result.success and "no pixels were sent" in result.output["content"]
    assert media.calls == []


@pytest.mark.asyncio
async def test_text_fallback_does_not_require_path_and_fd_timestamp_equivalence(tmp_path, monkeypatch):
    target = tmp_path / "text"
    target.write_text("readable")
    monkeypatch.setattr(os, "supports_dir_fd", set())
    # Windows stat/fstat timestamp representations are not equivalent across
    # supported Python versions. The unqualified text-only lane still checks
    # regular type and inode identity; it cannot stage images.
    monkeypatch.setattr(
        ReadTool, "_file_version",
        staticmethod(lambda _: pytest.fail("text fallback must not compare timestamps")),
    )
    result = await ReadTool({}, coordinator()).execute({"file_path": str(target)})
    assert result.success and "readable" in result.output["content"]
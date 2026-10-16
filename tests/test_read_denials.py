"""Explicit denials remain authoritative over otherwise ordinary reads."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from amplifier_module_tool_filesystem.read import ReadTool
from amplifier_module_tool_filesystem.write import WriteTool


@pytest.mark.asyncio
async def test_read_policy_is_independent_of_write_roots(tmp_path):
    workspace, installed = tmp_path / 'workspace', tmp_path / 'installed'
    workspace.mkdir()
    installed.mkdir()
    source = installed / 'producer.py'
    source.write_text('public source\n')
    coordinator = SimpleNamespace(hooks=SimpleNamespace(emit=AsyncMock()))
    config = {'working_dir': str(workspace), 'allowed_write_paths': [str(workspace)]}
    assert (await ReadTool(config, coordinator).execute({'file_path': str(source)})).success
    assert not (await WriteTool(config, coordinator).execute({'file_path': str(source), 'content': 'changed'})).success
    assert source.read_text() == 'public source\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed', [None, ['.']])
@pytest.mark.parametrize('request_kind', ['absolute', 'relative', 'traversal', 'symlink', 'mention'])
async def test_explicit_deny_wins_before_open(tmp_path, monkeypatch, allowed, request_kind):
    private = tmp_path / 'private'
    private.mkdir()
    secret = private / 'secret.txt'
    secret.write_text('private-token')
    alias = tmp_path / 'alias'
    alias.symlink_to(private, target_is_directory=True)
    coordinator = SimpleNamespace(hooks=SimpleNamespace(emit=AsyncMock()),
        get_capability=lambda name: SimpleNamespace(resolve=lambda value: secret))
    tool = ReadTool({'working_dir': str(tmp_path), 'allowed_read_paths': allowed,
                     'denied_read_paths': ['private']}, coordinator)
    paths = {'absolute': str(secret), 'relative': 'private/secret.txt',
             'traversal': 'other/../private/secret.txt', 'symlink': 'alias/secret.txt', 'mention': '@bundle:secret'}
    def must_not_read(*args, **kwargs):
        pytest.fail('denied contents must not be opened')
    monkeypatch.setattr(type(secret), 'read_text', must_not_read)
    result = await tool.execute({'file_path': paths[request_kind]})
    assert not result.success
    assert 'private-token' not in str(result)
    coordinator.hooks.emit.assert_not_called()


@pytest.mark.asyncio
async def test_directory_listing_omits_denied_entries_and_empty_allowlist_denies_all(tmp_path):
    (tmp_path / 'public.txt').write_text('public')
    (tmp_path / 'private.txt').write_text('private')
    (tmp_path / 'alias').symlink_to(tmp_path / 'private.txt')
    coordinator = SimpleNamespace(hooks=SimpleNamespace(emit=AsyncMock()))
    tool = ReadTool({'working_dir': str(tmp_path), 'denied_read_paths': ['private.txt']}, coordinator)
    result = await tool.execute({'file_path': '.'})
    assert result.success
    assert result.output['entry_count'] == 1
    assert 'private.txt' not in result.output['content']
    assert 'alias' not in result.output['content']
    denied = ReadTool({'working_dir': str(tmp_path), 'allowed_read_paths': []}, coordinator)
    assert not (await denied.execute({'file_path': 'public.txt'})).success


@pytest.mark.asyncio
async def test_case_alias_and_null_denials(tmp_path):
    secret = tmp_path / 'Secret.txt'
    secret.write_text('private-token')
    alias = tmp_path / 'SECRET.TXT'
    if not alias.exists():
        alias.write_text('public-token')
    coordinator = SimpleNamespace(hooks=SimpleNamespace(emit=AsyncMock()))
    cfg = {'working_dir': str(tmp_path), 'denied_read_paths': ['Secret.txt']}
    result = await ReadTool(cfg, coordinator).execute({'file_path': str(alias)})
    assert result.success is not alias.samefile(secret)
    assert 'private-token' not in str(result)
    assert (await ReadTool({**cfg, 'denied_read_paths': None}, coordinator).execute({'file_path': str(secret)})).success
    for invalid in (False, 0, '', [None]):
        with pytest.raises(ValueError, match='denied_read_paths'):
            ReadTool({**cfg, 'denied_read_paths': invalid}, coordinator)


@pytest.mark.asyncio
@pytest.mark.parametrize('alias_kind', ['unicode', 'hardlink'])
async def test_physical_alias_denial(tmp_path, monkeypatch, alias_kind):
    secret = tmp_path / ('cafe\u0301.txt' if alias_kind == 'unicode' else 'secret.txt')
    secret.write_text('private-token')
    alias = tmp_path / ('caf\u00e9.txt' if alias_kind == 'unicode' else 'hardlink.txt')
    if alias_kind == 'hardlink':
        alias.hardlink_to(secret)
    elif not alias.exists():
        pytest.skip('This filesystem keeps Unicode spellings distinct')
    coordinator = SimpleNamespace(hooks=SimpleNamespace(emit=AsyncMock()))
    tool = ReadTool({'working_dir': str(tmp_path), 'denied_read_paths': [str(alias)]}, coordinator)
    def must_not_read(*args, **kwargs):
        pytest.fail('denied physical alias must not be opened')
    monkeypatch.setattr(Path, 'read_text', must_not_read)
    assert not (await tool.execute({'file_path': str(secret)})).success
    listing = await tool.execute({'file_path': str(tmp_path)})
    assert listing.success and listing.output['entry_count'] == 0


def test_allowlist_does_not_grant_unrelated_hardlink(tmp_path):
    allowed = tmp_path / 'allowed.txt'
    allowed.write_text('content')
    other = tmp_path / 'outside.txt'
    other.hardlink_to(allowed)
    tool = ReadTool({'allowed_read_paths': [str(allowed)]}, SimpleNamespace())
    assert tool._is_allowed(allowed)
    assert not tool._is_allowed(other)

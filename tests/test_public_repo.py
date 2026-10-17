"""Publication safeguards; all credentials here are constructed synthetic data."""
import importlib.util
import json
import stat
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('public_check', Path(__file__).resolve().parents[1] / 'scripts/check_public_repo.py')
public_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public_check)


@pytest.mark.parametrize('name', ['projects/demo/project.json', '.agents/skills/example.md', 'memory/session.md', 'AGENTS.md', 'notes.sqlite3-wal', 'video.mp4', '.env', 'credentials.local.json', 'Clarity.app/Contents/Info.plist', '../outside.txt', '/absolute/file.txt'])
def test_private_paths_are_rejected(name):
    assert public_check.private_path(name)


@pytest.mark.parametrize('name', ['README.md', 'docs/ai-cli.md', 'uv.lock', 'web/logo.svg', '.github/workflows/checks.yml', '.env.example'])
def test_public_source_paths_are_allowed(name):
    assert not public_check.private_path(name)


def test_findings_are_redacted_and_cover_secret_and_home_path():
    token = 'sk-or-' + 'v1-' + 'a' * 48
    private_path = '/' + 'Users' + '/someone/' + 'private'
    data = ('first line\n' + token + '\n' + private_path).encode()
    rows = public_check.scan_content(data, 'example.py')
    assert {row['rule'] for row in rows} >= {'openrouter-token', 'home-directory-path'}
    assert rows[0]['line'] == 2
    serialized = json.dumps(rows)
    assert token not in serialized and private_path not in serialized


def test_benign_metadata_and_placeholder_are_not_credentials():
    assert public_check.scan_content(b'https://pypi.org/simple\nOPENROUTER_API_KEY=YOUR_KEY\nsha256:' + b'a' * 64, 'example') == []


def test_secret_in_filename_is_redacted_too():
    token = 'gh' + 'p_' + 'b' * 40
    rows = public_check.scan_content(token.encode(), token + '.txt')
    assert rows and token not in json.dumps(rows)


def test_source_archive_has_no_git_metadata_and_preserves_launch_mode(tmp_path):
    snapshot = {'README.md': (b'Documentation\n', 0o644), 'clarity-cli': (b'#!/bin/zsh\n', 0o755)}
    output = tmp_path / 'dist/source.zip'
    result = public_check.write_archive(tmp_path, output, snapshot)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {'clarity-studio/README.md', 'clarity-studio/clarity-cli'}
        assert archive.read('clarity-studio/README.md') == b'Documentation\n'
        assert stat.S_IMODE(archive.getinfo('clarity-studio/clarity-cli').external_attr >> 16) == 0o755
    manifest = json.loads((tmp_path / result['manifest']).read_text())
    assert manifest['git_metadata_included'] is False
    assert len(manifest['files']) == 2


@pytest.mark.parametrize('name', ['.git/config', 'projects/demo/project.json', '../outside.txt'])
def test_archive_rejects_private_and_traversal_names(tmp_path, name):
    with pytest.raises(ValueError):
        public_check.write_archive(tmp_path, tmp_path / 'dist/source.zip', {name: (b'private', 0o644)})
    assert not (tmp_path / 'dist/source.zip').exists()


def test_archive_cannot_overwrite_source(tmp_path):
    with pytest.raises(ValueError):
        public_check.write_archive(tmp_path, tmp_path / 'source.zip', {'README.md': (b'public', 0o644)})


def test_source_symlink_is_not_followed(tmp_path, monkeypatch):
    (tmp_path / 'leak.txt').symlink_to(tmp_path / 'outside.txt')
    (tmp_path / 'outside.txt').write_text('private value')
    def fake_git(root, *args, **kwargs):
        if args[0] == 'ls-files':
            return b'leak.txt\0'
        return b''
    monkeypatch.setattr(public_check, 'git', fake_git)
    report, snapshot = public_check.audit(tmp_path)
    assert not report['ok']
    assert snapshot == {}
    assert {'location': 'leak.txt', 'rule': 'symlink-needs-review'} in report['findings']


def test_historical_private_alias_of_public_blob_is_detected(tmp_path, monkeypatch):
    # One identical blob is public in a commit tree and private in a directly
    # referenced tree. rev-list --objects would emit only one blob pathname.
    blob = 'b' * 40
    def fake_git(root, *args, **kwargs):
        if args == ('rev-parse', 'commit^{tree}'):
            return b'public-tree\n'
        if args[0] == 'for-each-ref':
            return b'refs/heads/main\nrefs/local/snapshot\n'
        if args == ('rev-parse', 'refs/heads/main^{}'):
            return b'commit\n'
        if args == ('rev-parse', 'refs/local/snapshot^{}'):
            return b'private-tree\n'
        if args[0] == 'cat-file':
            return b'commit\n' if args[-1] == 'commit' else b'tree\n'
        if args[0] == 'ls-tree':
            name = 'README.md' if args[-1] == 'public-tree' else 'projects/private/project.json'
            return f'100644 blob {blob}\t{name}\0'.encode()
        raise AssertionError(args)
    monkeypatch.setattr(public_check, 'git', fake_git)
    findings, trees, paths = public_check.inspect_history_paths(tmp_path, ['commit'])
    assert trees == 2 and paths == 2
    assert len(findings) == 1
    assert findings[0]['rule'] == 'private-path-in-history'
    assert findings[0]['location'].endswith(':projects/private/project.json')

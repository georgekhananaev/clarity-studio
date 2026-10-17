"""Audit publishable source and reachable history; optionally export source only.

Standard library only. Findings contain locations/rules, never matching values.
This is a focused signature/path check, not a general secret-detection guarantee.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {
    '.git', 'projects', 'recordings', 'imports', 'exports', 'renders', 'screenshots',
    'artifacts', 'skills', 'memory', '.agents', '.codex', '.claude', '.cursor',
    '.gemini', '.ai', '.local', '.improve-loop', '.venv', 'venv', 'node_modules',
    '.memory', '.skills', '.copilot', '.continue', '.windsurf', '.opencode',
    '.roo', '.kilocode', '.trae', '.clinerules', 'prompts',
    '__pycache__', '.pytest_cache', '.cache', 'tmp', 'temp', 'dist', 'build',
    'private', 'auth', '.auth', 'logs', 'backups',
}
PRIVATE_NAMES = (
    'agents*.md', 'agent.md', 'claude*.md', 'gemini*.md', 'memory*.md', 'skill.md',
    '.env', '.env.*', '*credentials*.json', '*secrets*.json', '.mcp.json',
    '*.sqlite*', '*.db', '*.db-*', '*.key', '*.pem', '*.p12', '*.pfx',
    '*.mp4', '*.mov', '*.mkv', '*.avi', '*.webm', '*.m4v', '*.mp3', '*.wav',
    '*.m4a', '*.aac', '*.flac', '*.ogg', '*.srt', '*.vtt', '*.log', '*.pid',
    '*.zip', '*.tar', '*.tgz', '*.7z', '*.bak', '*.har', '*.pyc', '*.dmg', '*.pkg',
)
PATTERNS = {
    'openrouter-token': rb'sk-or-v1-[A-Za-z0-9_-]{20,}',
    'api-secret-key': rb'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}',
    'github-token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'aws-access-key': rb'(?:AKIA|ASIA)[A-Z0-9]{16}',
    'google-api-key': rb'AIza[A-Za-z0-9_-]{35}',
    'slack-token': rb'xox[baprs]-[A-Za-z0-9-]{20,}',
    'private-key': rb'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----',
    'jwt': rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{20,}',
    'home-directory-path': rb'/(?:Users|home)/[A-Za-z0-9_.-]+/',
}
REQUIRED = {
    '.gitignore', 'README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md',
    'pyproject.toml', 'uv.lock', 'clarity-cli', 'setup.command',
    'Launch Clarity.command', 'docs/ai-cli.md',
}
MAX_FILE_BYTES = 4 * 1024 * 1024


def private_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        return True
    if any(part.lower() in PRIVATE_PARTS or part.lower().endswith('.app') for part in path.parts):
        return True
    if len(path.parts) > 1 and path.parts[0] == '.github' and path.parts[1] in {'agents', 'instructions', 'skills', 'prompts'}:
        return True
    if path.name in {'.env.example', '.env.sample', '.env.template'}:
        return False
    return any(fnmatch.fnmatchcase(path.name.lower(), pattern) for pattern in PRIVATE_NAMES)


def redacted_location(location: str) -> str:
    for pattern in PATTERNS.values():
        location = re.sub(pattern.decode(), '[redacted]', location)
    return location


def scan_content(data: bytes, location: str) -> list[dict]:
    location = redacted_location(location)
    findings = []
    if b'\0' in data:
        findings.append({'location': location, 'rule': 'binary-file-needs-review'})
    for rule, pattern in PATTERNS.items():
        for match in re.finditer(pattern, data):
            findings.append({'location': location, 'rule': rule, 'line': data.count(b'\n', 0, match.start()) + 1})
    return findings


def git(root: Path, *args: str, input: bytes | None = None, allow_no_match=False) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], input=input, capture_output=True)
    if result.returncode and not (allow_no_match and result.returncode == 1):
        raise ValueError('Git inspection failed. Run this command inside a Git checkout.')
    return result.stdout


def inspect_history_paths(root: Path, commits: list[str]) -> tuple[list[dict], int, int]:
    # A blob's representative rev-list name is insufficient: the same bytes can
    # have both public and private aliases. Inspect complete root trees instead.
    trees = {git(root, 'rev-parse', f'{oid}^{{tree}}').strip().decode() for oid in commits}
    for ref in git(root, 'for-each-ref', '--format=%(refname)').decode().splitlines():
        oid = git(root, 'rev-parse', f'{ref}^{{}}').strip().decode()
        if git(root, 'cat-file', '-t', oid).strip() == b'tree':
            trees.add(oid)
    findings = []
    paths = 0
    for tree in sorted(trees):
        for entry in git(root, 'ls-tree', '-r', '--full-tree', '-z', tree).split(b'\0'):
            if not entry:
                continue
            metadata, name = entry.split(b'\t', 1)
            name = name.decode('utf-8', errors='surrogateescape')
            paths += 1
            location = f'history-tree:{tree[:12]}:{name}'
            if private_path(name):
                findings.append({'location': location, 'rule': 'private-path-in-history'})
            if metadata.startswith(b'120000 '):
                findings.append({'location': location, 'rule': 'history-symlink-needs-review'})
    return findings, len(trees), paths


def audit(root: Path) -> tuple[dict, dict[str, tuple[bytes, int]]]:
    names = sorted(set(filter(None, git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0'))))
    ignored = set(filter(None, git(root, 'check-ignore', '--no-index', '--stdin', '-z', input=b''.join(name.encode() + b'\0' for name in names), allow_no_match=True).decode().split('\0')))
    findings = []
    snapshot = {}
    for name in names:
        path = root / name
        if private_path(name) or name in ignored:
            findings.append({'location': name, 'rule': 'private-or-ignored-path-in-source'})
            continue
        if path.is_symlink():
            findings.append({'location': name, 'rule': 'symlink-needs-review'})
            continue
        if not path.exists():  # tracked deletion; it is not part of this snapshot
            continue
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            findings.append({'location': name, 'rule': 'unsupported-or-oversized-source-file'})
            continue
        data = path.read_bytes()
        findings.extend(scan_content(data, name))
        snapshot[name] = (data, 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644)
    for name in sorted(REQUIRED - snapshot.keys()):
        findings.append({'location': name, 'rule': 'required-community-file-missing'})

    blobs = 0
    commits = []
    head = git(root, 'rev-parse', '--verify', '--quiet', 'HEAD', allow_no_match=True).strip().decode()
    history_args = ['--all', head] if head else ['--all']
    for record in git(root, 'rev-list', '--objects', *history_args).decode().splitlines():
        oid, _, name = record.partition(' ')
        kind = git(root, 'cat-file', '-t', oid).strip()
        if kind not in (b'blob', b'commit'):
            continue
        label = f'history:{oid[:12]}' + (f':{name}' if name else '')
        if kind == b'blob':
            blobs += 1
        else:
            commits.append(oid)
        size = int(git(root, 'cat-file', '-s', oid))
        if size > MAX_FILE_BYTES:
            findings.append({'location': label, 'rule': 'oversized-history-object-needs-review'})
            continue
        findings.extend(scan_content(git(root, 'cat-file', kind.decode(), oid), label))
    path_findings, tree_count, path_count = inspect_history_paths(root, commits)
    findings.extend(path_findings)
    emails = git(root, 'log', *history_args, '--format=%ae%n%ce').decode().splitlines()
    metadata_notice = any(email and not email.endswith('@users.noreply.github.com') for email in emails)
    for finding in findings:
        finding['location'] = redacted_location(finding['location'])
    return {
        'ok': not findings, 'source_files': len(snapshot), 'history_commits': len(commits),
        'history_blobs': blobs, 'history_root_trees': tree_count,
        'history_tree_paths': path_count, 'findings': findings,
        'history_has_non_noreply_author_email': metadata_notice,
        'scope': 'Tracked and eligible untracked working files; reachable Git tree paths, blobs and commits. Commit emails are reported separately; no values are printed.',
    }, snapshot


def write_archive(root: Path, output: Path, snapshot: dict[str, tuple[bytes, int]]) -> dict:
    output = output.resolve()
    if not output.is_relative_to(root.resolve() / 'dist') or output.suffix != '.zip':
        raise ValueError('Choose a .zip output under this checkout\'s ignored dist/ directory.')
    if any(private_path(name) or PurePosixPath(name).is_absolute() for name in snapshot):
        raise ValueError('Refusing to archive a private or unsafe path.')
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(output, 'w') as archive:
        for name, (data, mode) in sorted(snapshot.items()):
            entry = zipfile.ZipInfo('clarity-studio/' + name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)
            manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'mode': oct(mode)})
    manifest_path = output.with_suffix('.manifest.json')
    manifest_path.write_text(json.dumps({'files': manifest, 'git_metadata_included': False}, indent=2) + '\n')
    return {'archive': str(output.relative_to(root.resolve())), 'manifest': str(manifest_path.relative_to(root.resolve())), 'files': len(manifest), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Also save a source-only ZIP under dist/ after the audit passes')
    args = parser.parse_args()
    try:
        report, snapshot = audit(ROOT)
        if args.archive and report['ok']:
            report['export'] = write_archive(ROOT, args.archive, snapshot)
        print(json.dumps(report, indent=2))
        return 0 if report['ok'] else 1
    except (OSError, ValueError):
        # Exception text can include user-controlled filenames. Keep errors generic.
        print(json.dumps({'ok': False, 'error': 'Could not inspect or export source. Check Git availability and use an ignored dist/*.zip archive path.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

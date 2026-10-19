"""Stamp clean reviewed Git source before a CLI upload, without any credentials.

Run after committing the release candidate and before creating build output.
A package without Git must carry this receipt; it cannot invent a revision.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from postriff_phase2.release_provenance import (
    MANIFEST_PATH, WITNESS_PATHS, read_regular, release_source_proof, valid_revision,
)


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(['git', '-C', str(root), *arguments],
                                capture_output=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Source receipt requires readable local Git history') from None
    return result.stdout


def _clean(root: Path) -> None:
    if _git(root, 'status', '--porcelain', '--untracked-files=no').strip():
        raise ValueError('Commit reviewed tracked changes before stamping a release')


def stamp(root: Path = SOURCE_ROOT) -> dict:
    """Write a deterministic receipt only for clean source equal to real Git HEAD."""
    root = Path(root).resolve(strict=True)
    top = Path(_git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    if top != root:
        raise ValueError('Stamp only the exact Git worktree root')
    revision = _git(root, 'rev-parse', 'HEAD').decode().strip()
    if not valid_revision(revision):
        raise ValueError('Invalid Git source revision')
    _clean(root)
    files = {}
    for name in WITNESS_PATHS:
        try:
            raw = read_regular(root, name, 8 * 1024 * 1024)
        except (OSError, ValueError, RuntimeError):
            raise ValueError('A required regular runtime witness is unavailable') from None
        if raw != _git(root, 'show', revision + ':' + name):
            raise ValueError('Runtime witness does not match the committed source')
        files[name] = hashlib.sha256(raw).hexdigest()
    _clean(root)
    if _git(root, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise ValueError('Git revision changed during source capture')
    manifest = {'schemaVersion': 1, 'sourceRevision': revision,
                'coverage': 'selected_runtime_files', 'files': files}
    raw = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode()
    target = root / MANIFEST_PATH
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError('Source receipt destination is not a regular file')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.source-receipt-', dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    proof = release_source_proof({}, root=root)
    if not proof['verifiedSelectedRuntimeFiles']:
        raise ValueError('Source changed before stamped receipt readback')
    return proof


def build_source_proof(values: Mapping[str, str], root: Path = SOURCE_ROOT) -> dict:
    """Validate bytes; if Git exists, also require clean source at the receipt's HEAD."""
    root = Path(root).resolve(strict=True)
    has_git = os.path.lexists(root / '.git')
    revision = None
    if has_git:
        top = Path(_git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
        if top != root:
            raise ValueError('Build only the exact Git worktree root')
        revision = _git(root, 'rev-parse', 'HEAD').decode().strip()
        if not valid_revision(revision):
            raise ValueError('Invalid Git source revision')
        _clean(root)
    proof = release_source_proof(values, root=root)
    if proof['status'] in ('missing', 'metadata_only') and has_git:
        declared = values.get('VERCEL_GIT_COMMIT_SHA', '')
        if declared and (not valid_revision(declared)
                         or revision != declared):
            raise ValueError('Build metadata does not match the local Git revision')
        stamp(root)
        proof = release_source_proof(values, root=root)
    if not proof['verifiedSelectedRuntimeFiles']:
        raise ValueError('Missing, stale or conflicting source receipt; restamp reviewed clean source before upload')
    if has_git:
        _clean(root)
        if (proof['sourceRevision'] != revision
                or _git(root, 'rev-parse', 'HEAD').decode().strip() != revision):
            raise ValueError('Source receipt does not match the current clean Git revision')
    return proof


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=SOURCE_ROOT)
    arguments = parser.parse_args(argv)
    try:
        proof = stamp(arguments.root)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'failed', 'reason': 'Clean Git source and all runtime witnesses are required; nothing was deployed.'}))
        return 1
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

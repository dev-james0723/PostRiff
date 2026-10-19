"""Read-only integrity witnesses for a pre-upload, Git-bound source receipt.

This is deliberately not a signed attestation, complete bundle inventory,
customer qualification, or evidence of a successful provider action.
"""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

MANIFEST_PATH = 'src/postriff_phase2/release-source.json'
WITNESS_PATHS = (
    'api/index.py',
    'src/postriff_phase2/hosted_app.py',
    'src/postriff_phase2/hosted_worker.py',
    'src/postriff_phase2/official_social.py',
    'src/postriff_phase2/providers.py',
    'src/postriff_phase2/deployment.py',
    'src/postriff_phase2/linkedin_fleet.py',
    'src/postriff_phase2/release_provenance.py',
    'runtime/verify_release_target.py',
    'runtime/stamp_release_source.py',
    'vercel.json',
    'requirements.txt',
)
_ROOT = Path(__file__).resolve().parents[2]
_MAX_RECEIPT = 65536
_MAX_WITNESS = 8 * 1024 * 1024


def valid_revision(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{40}', value)) and value != '0' * 40


def read_regular(root: Path, name: str, limit: int) -> bytes:
    """Read only an in-root regular file, with bounded bytes and no symlinks."""
    root = root.resolve(strict=True)
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid witness path')
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink is not a source witness')
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Witness must remain inside the release root')
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError('Invalid witness file')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Witness identity changed')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    if (len(raw) > limit or opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
        raise ValueError('Witness changed during read')
    return raw


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate source receipt field')
        value[key] = item
    return value


def _empty(status: str) -> dict:
    return {'status': status, 'sourceRevision': None,
            'verifiedSelectedRuntimeFiles': False, 'coverage': 'selected_runtime_files',
            'witnessCount': 0, 'expectedWitnessCount': len(WITNESS_PATHS),
            'receiptSha256': None}


def _inspect(root: Path) -> dict:
    try:
        raw = read_regular(root, MANIFEST_PATH, _MAX_RECEIPT)
    except FileNotFoundError:
        return _empty('missing')
    except (OSError, ValueError, RuntimeError):
        return _empty('unavailable')
    try:
        manifest = json.loads(raw, object_pairs_hook=_unique_object)
        if (type(manifest) is not dict
                or set(manifest) != {'schemaVersion', 'sourceRevision', 'coverage', 'files'}
                or type(manifest['schemaVersion']) is not int
                or manifest['schemaVersion'] != 1
                or not valid_revision(manifest['sourceRevision'])
                or manifest['coverage'] != 'selected_runtime_files'
                or type(manifest['files']) is not dict
                or set(manifest['files']) != set(WITNESS_PATHS)):
            return _empty('invalid_receipt')
        for name in WITNESS_PATHS:
            digest = manifest['files'][name]
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                return _empty('invalid_receipt')
            if hashlib.sha256(read_regular(root, name, _MAX_WITNESS)).hexdigest() != digest:
                return _empty('witness_mismatch')
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, RecursionError):
        return _empty('invalid_receipt')
    return {'status': 'verified', 'sourceRevision': manifest['sourceRevision'],
            'verifiedSelectedRuntimeFiles': True, 'coverage': 'selected_runtime_files',
            'witnessCount': len(WITNESS_PATHS), 'expectedWitnessCount': len(WITNESS_PATHS),
            'receiptSha256': hashlib.sha256(raw).hexdigest()}


@lru_cache(maxsize=1)
def _packaged_proof() -> dict:
    # A deployed function's source bundle is immutable. Do not reread megabytes
    # on every liveness request. Explicit-root validation never uses this cache.
    return _inspect(_ROOT)


def release_source_proof(values: Mapping[str, str], *, root: Path | None = None) -> dict:
    """Return safe source metadata; never initialize services or contact Git/API/DB."""
    proof = dict(_packaged_proof() if root is None else _inspect(Path(root)))
    reported = values.get('VERCEL_GIT_COMMIT_SHA', '')
    if proof['verifiedSelectedRuntimeFiles']:
        if reported and (not valid_revision(reported) or reported != proof['sourceRevision']):
            return _empty('metadata_conflict')
    elif proof['status'] == 'missing' and valid_revision(reported):
        # Preserve the existing metadata field without upgrading it to byte proof.
        proof.update(status='metadata_only', sourceRevision=reported)
    return proof

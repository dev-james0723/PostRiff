"""Read-only integrity witnesses for a pre-upload, Git-bound source receipt.

This is deliberately not a signed attestation, complete bundle inventory,
customer qualification, or evidence of a successful provider action.
"""
from functools import lru_cache
from contextlib import ExitStack
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
    """Read bounded regular bytes via pinned directories and nonblocking/no-follow opens."""
    root = root.resolve(strict=True)
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Invalid witness path')
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    with ExitStack() as descriptors:
        directory = os.open(root, flags | os.O_DIRECTORY)
        descriptors.callback(os.close, directory)
        parents = [os.fstat(directory)]
        for part in relative.parts[:-1]:
            directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            descriptors.callback(os.close, directory)
            parents.append(os.fstat(directory))
        leaf = relative.parts[-1]
        before = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        descriptor = os.open(leaf, flags, dir_fd=directory)
        descriptors.callback(os.close, descriptor)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise ValueError('Invalid witness file')
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Witness identity changed')
        # ExitStack owns the descriptor even if creating/reading the stream fails.
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(descriptor)
        current = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        if (len(raw) > limit or opened.st_size != after.st_size
                or opened.st_mtime_ns != after.st_mtime_ns
                or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError('Witness changed during read')
        # A pinned descriptor can outlive a renamed directory. Reopen the actual
        # release path so detached-but-unchanged bytes cannot certify its replacement.
        checked_directory = os.open(root, flags | os.O_DIRECTORY)
        descriptors.callback(os.close, checked_directory)
        root_now = os.fstat(checked_directory)
        if (root_now.st_dev, root_now.st_ino) != (parents[0].st_dev, parents[0].st_ino):
            raise ValueError('Release root identity changed')
        for part, prior in zip(relative.parts[:-1], parents[1:]):
            checked_directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=checked_directory)
            descriptors.callback(os.close, checked_directory)
            parent_now = os.fstat(checked_directory)
            if (parent_now.st_dev, parent_now.st_ino) != (prior.st_dev, prior.st_ino):
                raise ValueError('Witness parent identity changed')
        named = os.stat(leaf, dir_fd=checked_directory, follow_symlinks=False)
        if ((named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                or not stat.S_ISREG(named.st_mode)
                or named.st_size != after.st_size or named.st_mtime_ns != after.st_mtime_ns):
            raise ValueError('Witness release path changed during read')
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
    # Contract: default-root callers run in an immutable deployed function bundle.
    # Success AND failure stay cached for its process lifetime. Mutable local/build
    # trees must pass an explicit root; they never use this cache.
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

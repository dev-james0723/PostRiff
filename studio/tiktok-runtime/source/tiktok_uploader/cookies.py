"""Encrypted local session storage; legacy pickle files are never loaded."""
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet

DEFAULT_ROOT = Path.home() / 'Library/Application Support/James Au TikTok Uploader/sessions'


def _root(cookies_path=None):
    root = Path(cookies_path) if cookies_path else DEFAULT_ROOT
    root = root.absolute()
    for part in reversed((root, *root.parents)):
        if part.is_symlink():
            raise ValueError('session_path_symlink')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.getuid():
        raise ValueError('session_owner_mismatch')
    root.chmod(0o700)
    return root


def _path(filename, cookies_path=None):
    if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,100}', filename):
        raise ValueError('invalid_session_label')
    return _root(cookies_path) / (filename + '.cookie')


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
            raise ValueError('unsafe_session_permissions')
        raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('session_too_large')
        return raw


def _cipher(root):
    path = root / '.session-key'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(Fernet.generate_key())
            stream.flush()
            os.fsync(stream.fileno())
    return Fernet(_read(path))


def _validate(cookies):
    if not isinstance(cookies, list) or len(cookies) > 100:
        raise ValueError('invalid_session')
    for cookie in cookies:
        if not isinstance(cookie, dict) or not isinstance(cookie.get('name'), str) or not isinstance(cookie.get('value'), str):
            raise ValueError('invalid_cookie')
    return cookies


def load_cookies_from_file(filename, cookies_path=None):
    path = _path(filename, cookies_path)
    try:
        raw = _read(path)
    except FileNotFoundError:
        return []
    try:
        return _validate(json.loads(_cipher(path.parent).decrypt(raw)))
    except Exception:
        raise ValueError('invalid_encrypted_session_relogin_required') from None


def save_cookies_to_file(cookies, filename, cookies_path=None):
    path = _path(filename, cookies_path)
    if path.is_symlink():
        raise ValueError('session_path_symlink')
    raw = json.dumps(_validate(cookies)).encode()
    if len(raw) > 512 * 1024:
        raise ValueError('session_too_large')
    encrypted = _cipher(path.parent).encrypt(raw)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.session-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def delete_cookies_file(filename, cookies_path=None):
    path = _path(filename, cookies_path)
    if path.is_symlink():
        raise ValueError('session_path_symlink')
    path.unlink(missing_ok=True)


def delete_all_cookies_files(cookies_path=None):
    raise RuntimeError('bulk_session_deletion_disabled')


def update_dc_location(filename, new_dc_location):
    raise NotImplementedError('Explicit session refresh required')

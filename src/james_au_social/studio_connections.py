"""Owner-only control of a token-blind local OAuth broker.

Only the broker receives OAuth codes/tokens. Studio sees bounded identity metadata.
The content agent cannot invoke these routes or access the broker data directory.
"""
import json
import hashlib
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from .studio import StudioError, _no_symlinks
from .xiaohongshu_mcp import XiaohongshuMcpSupervisor


class XiaohongshuBrowserIdentity:
    """Store only public, owner-confirmed RedNote identity evidence."""

    PROVIDER = "xiaohongshu"
    SCOPE = "public_profile_browser_observation"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "xiaohongshu-browser-identity.json"
        _no_symlinks(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)

    @classmethod
    def _empty(cls):
        return {
            "provider": cls.PROVIDER, "available": True, "state": "not_connected",
            "nickname": None, "profileId": None, "rednoteId": None, "profileUrl": None,
            "scope": cls.SCOPE, "verifiedAt": None, "expiresAt": None,
            "identitySignals": [], "publishReady": False, "publishing": False,
        }

    def _read(self):
        if not self.path.exists():
            return self._empty()
        if self.path.is_symlink():
            raise StudioError("connection_record_invalid", "The local identity record is invalid.", 500)
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "r", encoding="utf-8") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
                    raise ValueError("invalid_identity_record")
                value = json.load(source)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise StudioError("connection_record_invalid", "The local identity record is invalid.", 500) from error
        if set(value) != set(self._empty()) or value.get("provider") != self.PROVIDER:
            raise StudioError("connection_record_invalid", "The local identity record is invalid.", 500)
        if value["publishReady"] is not False or value["publishing"] is not False:
            raise StudioError("connection_record_invalid", "The local identity record is invalid.", 500)
        return value

    def _write(self, value):
        if self.path.exists() and self.path.is_symlink():
            raise StudioError("connection_record_invalid", "The local identity record is invalid.", 500)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".xiaohongshu-identity-", suffix=".json", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                os.fchmod(output.fileno(), 0o600)
                json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _profile_id(profile_url):
        if not isinstance(profile_url, str) or len(profile_url) > 240:
            raise StudioError("invalid_identity", "Use the exact public RedNote profile URL.", 422)
        parts = urlsplit(profile_url)
        if (parts.scheme != "https" or parts.netloc != "www.rednote.com" or parts.query or parts.fragment
                or parts.username or parts.password):
            raise StudioError("invalid_identity", "Use the exact public RedNote profile URL.", 422)
        import re
        match = re.fullmatch(r"/user/profile/([0-9a-f]{24})", parts.path)
        if match is None:
            raise StudioError("invalid_identity", "Use the exact public RedNote profile URL.", 422)
        return match.group(1)

    @staticmethod
    def _text(value, field, pattern):
        import re
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise StudioError("invalid_identity", f"Use a valid public {field}.", 422)
        return value

    def status(self):
        return self._read()

    def observe_profile(self, profile_url, nickname, rednote_id):
        profile_id = self._profile_id(profile_url)
        nickname = self._text(nickname, "profile name", r"[^\r\n\x00]{1,80}")
        rednote_id = self._text(rednote_id, "RedNote ID", r"[0-9]{5,20}")
        current = self._read()
        if current["state"] == "identity_connected" and (
                current["profileId"] != profile_id or current["rednoteId"] != rednote_id):
            raise StudioError("identity_mismatch", "A different Xiaohongshu identity is already connected. Account replacement requires a separate review.", 409)
        record = self._empty() | {
            "state": "browser_profile_observed", "nickname": nickname, "profileId": profile_id,
            "rednoteId": rednote_id, "profileUrl": profile_url,
            "identitySignals": ["public_profile_url", "rendered_rednote_id"],
        }
        self._write(record)
        return record

    def confirm_creator_centre(self, rednote_id):
        rednote_id = self._text(rednote_id, "RedNote ID", r"[0-9]{5,20}")
        current = self._read()
        if current["state"] != "browser_profile_observed" or current["rednoteId"] != rednote_id:
            raise StudioError("identity_mismatch", "The Creator Center identity must match the recorded public RedNote profile.", 409)
        record = current | {
            "state": "identity_connected",
            "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "identitySignals": ["public_profile_url", "rendered_rednote_id", "owner_confirmed_creator_centre_rednote_id"],
        }
        self._write(record)
        return record


class ConnectionBroker:
    def __init__(self, project_root, data_dir, studio_port):
        self.root = Path(project_root)
        self.data = Path(data_dir).parent / (Path(data_dir).name + '-Connections')
        self.studio_port = studio_port
        self.port = studio_port + 2
        self.child = None
        self.youtube_child = None
        self.instagram_child = None
        self.facebook_child = None
        self.tiktok_child = None
        self.threads_child = None
        self.pinterest_child = None
        self.reddit_child = None
        self.x_child = None
        self.linkedin_child = None
        self.xiaohongshu_identity = XiaohongshuBrowserIdentity(self.data)
        self.xiaohongshu_mcp = XiaohongshuMcpSupervisor(self.data)
        self.capability = secrets.token_hex(32)
        self.begin_path = None
        self.instagram_begin_path = None
        self.instagram_public_base_url = self._instagram_public_base_url()
        self.facebook_begin_path = None
        self.facebook_public_base_url = self._facebook_public_base_url()
        self.tiktok_begin_path = None
        self.threads_begin_path = None
        self.pinterest_begin_path = None
        self.reddit_begin_path = None
        self.x_begin_path = None
        self.linkedin_begin_path = None

    def _instagram_public_base_url(self):
        path = self.data / 'instagram-oauth-tunnel.json'
        if not path.exists() or path.is_symlink():
            return None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'r', encoding='utf-8') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 or (info.st_mode & 0o077):
                    return None
                value = json.load(source)
            if set(value) != {'baseUrl'} or not isinstance(value['baseUrl'], str):
                return None
            parts = urlsplit(value['baseUrl'])
            if (parts.scheme != 'https' or not parts.netloc or parts.path not in ('', '/') or parts.query or parts.fragment
                    or parts.username or parts.password or parts.port is not None):
                return None
            return f'https://{parts.netloc}'
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _facebook_public_base_url(self):
        path = self.data / 'facebook-oauth-tunnel.json'
        if not path.exists() or path.is_symlink():
            return None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'r', encoding='utf-8') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 or (info.st_mode & 0o077):
                    return None
                value = json.load(source)
            if set(value) != {'baseUrl'} or not isinstance(value['baseUrl'], str):
                return None
            parts = urlsplit(value['baseUrl'])
            if (parts.scheme != 'https' or not parts.netloc or parts.path not in ('', '/') or parts.query or parts.fragment
                    or parts.username or parts.password or parts.port is not None):
                return None
            return f'https://{parts.netloc}'
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def start(self):
        self.xiaohongshu_mcp.start()
        self._start_youtube()
        self._start_instagram()
        self._start_facebook()
        self._start_tiktok()
        self._start_threads()
        self._start_pinterest()
        self._start_reddit()
        self._start_x()
        self._start_linkedin()
        script = self.root / 'studio/broker/start.mjs'
        dependency = self.root / 'studio/broker/node_modules/@atproto/oauth-client-node/package.json'
        node = shutil.which('node')
        if not node or not script.is_file() or not dependency.is_file() or self.port > 65535:
            return
        _no_symlinks(self.data)
        self.child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      env={key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ})
        config = {'port': self.port, 'studioPort': self.studio_port,
                  'root': str(self.data), 'capability': self.capability}
        self.child.stdin.write((json.dumps(config) + '\n').encode())
        self.child.stdin.flush()
        for _ in range(40):
            if self.child.poll() is not None:
                break
            if self.status()['available']:
                break
            time.sleep(0.05)

    def _start_youtube(self):
        script = self.root / 'studio/broker/start-youtube.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 1 > 65535:
            return
        _no_symlinks(self.data)
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.youtube_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        def keychain(account):
            security=shutil.which('security')
            if not security: return None
            try:
                result=subprocess.run([security,'find-generic-password','-s','James Au Studio YouTube OAuth','-a',account,'-w'],capture_output=True,text=True,timeout=5)
                return result.stdout.rstrip('\n') if result.returncode==0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        config = {'port': self.port + 1, 'studioPort': self.studio_port,
                  'root': str(self.data), 'capability': self.capability,
                  'clientId': os.environ.get('JAMES_STUDIO_YOUTUBE_CLIENT_ID') or keychain('client-id'),
                  'clientSecret': os.environ.get('JAMES_STUDIO_YOUTUBE_CLIENT_SECRET') or keychain('client-secret')}
        self.youtube_child.stdin.write((json.dumps(config) + '\n').encode()); self.youtube_child.stdin.flush()

    def _start_instagram(self):
        script = self.root / 'studio/broker/start-instagram.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 2 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio Instagram OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.instagram_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 2, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id'), 'clientSecret': keychain('client-secret'), 'publicBaseUrl': self.instagram_public_base_url}
        self.instagram_child.stdin.write((json.dumps(config) + '\n').encode()); self.instagram_child.stdin.flush(); self.instagram_child.stdin.close()

    def _start_facebook(self):
        script = self.root / 'studio/broker/start-facebook.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 7 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio Facebook OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.facebook_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 7, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id'), 'clientSecret': keychain('client-secret'),
                  'configurationId': '2961092884234131', 'publicBaseUrl': self.facebook_public_base_url}
        self.facebook_child.stdin.write((json.dumps(config) + '\n').encode()); self.facebook_child.stdin.flush(); self.facebook_child.stdin.close()

    def _start_tiktok(self):
        script = self.root / 'studio/broker/start-tiktok.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 3 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio TikTok OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.tiktok_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 3, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientKey': keychain('client-key'), 'clientSecret': keychain('client-secret')}
        self.tiktok_child.stdin.write((json.dumps(config) + '\n').encode()); self.tiktok_child.stdin.flush()

    def _start_threads(self):
        script = self.root / 'studio/broker/start-threads.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 4 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio Threads OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        tls_dir = self.data / 'threads-tls'
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.threads_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 4, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id'), 'clientSecret': keychain('client-secret'),
                  'certificatePath': str(tls_dir / 'threads-jamesau.meta.pem'), 'privateKeyPath': str(tls_dir / 'threads-jamesau.meta-key.pem')}
        self.threads_child.stdin.write((json.dumps(config) + '\n').encode()); self.threads_child.stdin.flush()

    def _start_pinterest(self):
        script = self.root / 'studio/broker/start-pinterest.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 5 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio Pinterest OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.pinterest_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 5, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id'), 'clientSecret': keychain('client-secret')}
        self.pinterest_child.stdin.write((json.dumps(config) + '\n').encode()); self.pinterest_child.stdin.flush()

    def _start_reddit(self):
        script = self.root / 'studio/broker/start-reddit.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 6 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio Reddit OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.reddit_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 6, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id'), 'clientSecret': keychain('client-secret')}
        self.reddit_child.stdin.write((json.dumps(config) + '\n').encode()); self.reddit_child.stdin.flush()

    def _start_x(self):
        script = self.root / 'studio/broker/start-x.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 8 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio X OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.x_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 8, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id')}
        self.x_child.stdin.write((json.dumps(config) + '\n').encode()); self.x_child.stdin.flush()

    def _start_linkedin(self):
        script = self.root / 'studio/broker/start-linkedin.mjs'
        node = shutil.which('node')
        if not node or not script.is_file() or self.port + 9 > 65535:
            return
        _no_symlinks(self.data)
        def keychain(account):
            security = shutil.which('security')
            if not security:
                return None
            try:
                result = subprocess.run([security, 'find-generic-password', '-s', 'James Au Studio LinkedIn OAuth', '-a', account, '-w'], capture_output=True, text=True, timeout=5)
                return result.stdout.rstrip('\n') if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        self.linkedin_child = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        config = {'port': self.port + 9, 'studioPort': self.studio_port, 'root': str(self.data), 'capability': self.capability,
                  'clientId': keychain('client-id'), 'clientSecret': keychain('client-secret')}
        self.linkedin_child.stdin.write((json.dumps(config) + '\n').encode()); self.linkedin_child.stdin.flush()

    def _request(self, method, path, body=None):
        if not self.child or self.child.poll() is not None:
            raise StudioError('connection_broker_unavailable', 'The private connection service is unavailable. Restart Studio.', 503)
        try:
            with httpx.Client(trust_env=False, timeout=35) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port}{path}', json=body,
                                          headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'invalid_handle': 'Enter a public Bluesky handle, such as name.bsky.social.',
                                'signin_already_pending': 'A sign-in is already pending. Complete it or wait ten minutes before starting again.',
                                'account_already_connected': 'A Bluesky account is already connected. Account replacement needs a separate review.',
                                'authorization_unavailable': 'Bluesky authorization could not start. Check that the handle exists and try again.'}
                    if code not in messages:
                        code = 'connection_request_failed'
                    raise StudioError(code, messages.get(code, 'The private connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private connection request failed. No account is confirmed.', 503) from None

    def status(self):
        try:
            value = self._request('GET', '/status')
            allowed = {'provider', 'available', 'state', 'handle', 'did', 'scope', 'verifiedAt',
                       'expiresAt', 'identitySignals', 'publishReady', 'publishing'}
            if set(value) != allowed or value['publishReady'] is not False or value['publishing'] is not False:
                raise ValueError('invalid_broker_status')
            return value
        except (StudioError, ValueError):
            return {'provider': 'bluesky', 'available': False, 'state': 'broker_unavailable',
                    'handle': None, 'did': None, 'scope': 'atproto', 'verifiedAt': None, 'expiresAt': None,
                    'identitySignals': [], 'publishReady': False, 'publishing': False}

    def youtube_status(self):
        try:
            value = self._youtube_request('GET', '/status')
            allowed = {'provider','available','state','email','channelId','channelTitle','handle','scope','verifiedAt','expiresAt','identitySignals','publishReady','publishing'}
            if set(value) != allowed or type(value['publishReady']) is not bool or value['publishing'] is not False:
                raise ValueError('invalid_youtube_status')
            return value
        except (StudioError, ValueError):
            return {'provider':'youtube','available':False,'state':'broker_unavailable','email':None,'channelId':None,'channelTitle':None,'handle':None,
                    'scope':'openid email https://www.googleapis.com/auth/youtube.readonly','verifiedAt':None,'expiresAt':None,'identitySignals':[],'publishReady':False,'publishing':False}

    def verify_youtube(self):
        self._youtube_request('POST', '/verify', {})
        return self.youtube_status()

    def upload_youtube(self, manifest, content):
        if not self.youtube_status()['publishReady']:
            raise StudioError('publish_connection_required', 'Reconnect YouTube with upload access first.', 409)
        upload_dir = self.data / 'youtube-upload-staging'
        _no_symlinks(upload_dir); upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True); upload_dir.chmod(0o700)
        key = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\0' + content).hexdigest()
        target = upload_dir / (secrets.token_hex(24) + '.video')
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(content); output.flush(); os.fsync(output.fileno())
            return self._youtube_request('POST', '/upload', {**manifest, 'filePath': str(target), 'idempotencyKey': key})
        finally:
            target.unlink(missing_ok=True)

    def instagram_status(self):
        try:
            value = self._instagram_request('GET', '/status')
            allowed = {'provider','available','state','username','userId','accountType','scope','route','routeDriver','verifiedAt','expiresAt','identitySignals','routeState','routeTestId','routeTestedAt','routeTestSignals','publicationPolicy','publishReady','publishing'}
            route_ready = value.get('state') == 'connected_identity' and value.get('routeState') == 'publish_ready' and isinstance(value.get('routeTestId'), str) and value.get('routeTestSignals') == ['identity_reverified','publishing_quota_read']
            if set(value) != allowed or type(value['publishReady']) is not bool or (value['publishReady'] and not route_ready) or value['scope'] != 'instagram_business_basic,instagram_business_content_publish' or value['route'] != 'official_api' or value['routeDriver'] != 'instagram_api_with_instagram_login' or value['publicationPolicy'] != 'exact_post_approval_required':
                raise ValueError('invalid_instagram_status')
            return value
        except (StudioError, ValueError):
            return {'provider':'instagram','available':False,'state':'broker_unavailable','username':None,'userId':None,'accountType':None,'scope':'instagram_business_basic,instagram_business_content_publish','route':'official_api','routeDriver':'instagram_api_with_instagram_login','verifiedAt':None,'expiresAt':None,'identitySignals':[],'routeState':'not_tested','routeTestId':None,'routeTestedAt':None,'routeTestSignals':[],'publicationPolicy':'exact_post_approval_required','publishReady':False,'publishing':False}

    def _instagram_request(self, method, path, body=None):
        if not self.instagram_child or self.instagram_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 2}{path}', json=body, headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required': 'Add the approved Meta OAuth client configuration and restart Studio.',
                                'signin_already_pending': 'An Instagram sign-in is already pending.',
                                'account_already_connected': 'An Instagram identity is already connected.',
                                'invalid_identity': 'Enter the exact Instagram username.',
                                'reconciliation_required': 'The previous Instagram authorization is unresolved.',
                                'invalid_route_test_manifest': 'The Instagram route test must target @jamesaucreates and the official image-post API.',
                                'publish_route_not_ready': 'Run the read-only Instagram publishing route test first.',
                                'invalid_publish_manifest': 'Review the exact Instagram image, caption, account and approval receipt.',
                                'idempotency_conflict': 'This Instagram idempotency key belongs to different content.',
                                'instagram_publish_unresolved': 'Instagram did not return independently verified media evidence. Check the profile before retrying.'}
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private Instagram connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private Instagram connection request failed.', 503) from None

    def prepare_instagram(self, username, scope):
        value = self._instagram_request('POST', '/prepare', {'username': username, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.instagram_begin_path = value['beginPath']
        return {'authorizationPath': '/api/connections/instagram/authorize'}

    def instagram_authorize_url(self):
        path, self.instagram_begin_path = self.instagram_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        return f'{self.instagram_public_base_url}{path}' if self.instagram_public_base_url else f'http://127.0.0.1:{self.port + 2}{path}'

    def verify_instagram(self):
        self._instagram_request('POST', '/verify', {})
        return self.instagram_status()

    def test_instagram_route(self, manifest):
        return self._instagram_request('POST', '/route-test', manifest)

    def publish_instagram_image(self, manifest):
        return self._instagram_request('POST', '/publish-image', manifest)

    def facebook_status(self):
        try:
            value = self._facebook_request('GET', '/status')
            allowed = {'provider','available','state','userName','userId','pageName','pageId','tasks','scope','configurationId','route','routeDriver','verifiedAt','expiresAt','identitySignals','routeState','routeTestId','routeTestedAt','routeTestSignals','publicationPolicy','publishReady','publishing'}
            route_ready = value.get('state') == 'connected_identity' and value.get('routeState') == 'publish_ready' and isinstance(value.get('routeTestId'), str) and value.get('routeTestSignals') == ['page_identity_reverified','page_published_posts_readable']
            if set(value) != allowed or type(value['publishReady']) is not bool or (value['publishReady'] and not route_ready) or value['scope'] != 'pages_show_list,pages_read_engagement,pages_manage_posts' or value['configurationId'] != '2961092884234131' or value['routeDriver'] != 'facebook_pages_api':
                raise ValueError('invalid_facebook_status')
            return value
        except (StudioError, ValueError):
            return {'provider':'facebook','available':False,'state':'broker_unavailable','userName':None,'userId':None,'pageName':None,'pageId':None,'tasks':[],'scope':'pages_show_list,pages_read_engagement,pages_manage_posts','configurationId':'2961092884234131','route':'official_api','routeDriver':'facebook_pages_api','verifiedAt':None,'expiresAt':None,'identitySignals':[],'routeState':'not_tested','routeTestId':None,'routeTestedAt':None,'routeTestSignals':[],'publicationPolicy':'exact_post_approval_required','publishReady':False,'publishing':False}

    def _facebook_request(self, method, path, body=None):
        if not self.facebook_child or self.facebook_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 7}{path}', json=body, headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required':'Add the Facebook app ID and app secret privately, plus a stable HTTPS callback, then restart Studio.','invalid_identity':'Enter the exact Facebook Page name and numeric Page ID.','account_already_connected':'A Facebook Page is already connected.','reconciliation_required':'The previous Facebook authorization is unresolved.','invalid_route_test_manifest':'The Facebook route test must match the connected Page.','facebook_page_posts_unreadable':'Meta verified the Page identity but did not allow a read of its published Page posts.','publish_route_not_ready':'Run the read-only Facebook publishing route test first.','invalid_publish_manifest':'Review the exact Facebook Page post, destination and approval receipt.','idempotency_conflict':'This Facebook idempotency key belongs to different content.','facebook_publish_unresolved':'Facebook did not return independently verified post evidence. Check the Page before retrying.'}
                    message = messages.get(code,'The private Facebook connection request failed.')
                    if code == 'facebook_page_posts_unreadable':
                        safe_parts = []
                        for label, field in (('HTTP', 'providerStatus'), ('Graph code', 'providerCode'), ('subcode', 'providerSubcode')):
                            value = response.json().get(field)
                            if type(value) is int and 0 <= value <= 999999:
                                safe_parts.append(f'{label} {value}')
                        if safe_parts:
                            message += ' Meta returned ' + ', '.join(safe_parts) + '.'
                    raise StudioError(code if code in messages else 'connection_request_failed', message, response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed','The private Facebook connection request failed.',503) from None

    def prepare_facebook(self, page_name, page_id, scope):
        value=self._facebook_request('POST','/prepare',{'pageName':page_name,'pageId':page_id,'scope':scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response',status=502)
        self.facebook_begin_path=value['beginPath']
        return {'authorizationPath':'/api/connections/facebook/authorize'}

    def facebook_authorize_url(self):
        path,self.facebook_begin_path=self.facebook_begin_path,None
        if not path:
            raise StudioError('signin_not_prepared','Prepare the exact Facebook Page connection in Studio first.',409)
        return f'{self.facebook_public_base_url}{path}' if self.facebook_public_base_url else f'http://127.0.0.1:{self.port + 7}{path}'

    def verify_facebook(self):
        self._facebook_request('POST','/verify',{})
        return self.facebook_status()

    def test_facebook_route(self, manifest):
        return self._facebook_request('POST','/route-test',manifest)

    def publish_facebook_post(self, manifest):
        return self._facebook_request('POST','/publish-post',manifest)

    def tiktok_status(self):
        try:
            value = self._tiktok_request('GET', '/status')
            allowed = {'provider', 'available', 'state', 'username', 'openId', 'displayName', 'scope', 'verifiedAt', 'expiresAt', 'identitySignals', 'publishReady', 'publishing'}
            if set(value) != allowed or value['publishReady'] is not False or value['publishing'] is not False or value['scope'] != 'user.info.basic,user.info.profile':
                raise ValueError('invalid_tiktok_status')
            return value
        except (StudioError, ValueError):
            return {'provider': 'tiktok', 'available': False, 'state': 'broker_unavailable', 'username': None, 'openId': None, 'displayName': None,
                    'scope': 'user.info.basic,user.info.profile', 'verifiedAt': None, 'expiresAt': None, 'identitySignals': [], 'publishReady': False, 'publishing': False}

    def _tiktok_request(self, method, path, body=None):
        if not self.tiktok_child or self.tiktok_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 3}{path}', json=body, headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required': 'Add the approved TikTok OAuth client configuration and restart Studio.',
                                'signin_already_pending': 'A TikTok sign-in is already pending.',
                                'account_already_connected': 'A TikTok identity is already connected.',
                                'invalid_identity': 'Enter the exact TikTok username.'}
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private TikTok connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private TikTok connection request failed.', 503) from None

    def prepare_tiktok(self, username, scope):
        value = self._tiktok_request('POST', '/prepare', {'username': username, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.tiktok_begin_path = value['beginPath']
        return {'authorizationPath': '/api/connections/tiktok/authorize'}

    def tiktok_authorize_url(self):
        path, self.tiktok_begin_path = self.tiktok_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        return f'http://127.0.0.1:{self.port + 3}{path}'

    def verify_tiktok(self):
        self._tiktok_request('POST', '/verify', {})
        return self.tiktok_status()

    def threads_status(self):
        try:
            value = self._threads_request('GET', '/status')
            allowed = {'provider', 'available', 'state', 'username', 'userId', 'scope', 'route', 'routeDriver',
                       'verifiedAt', 'expiresAt', 'identitySignals', 'routeState', 'routeTestId',
                       'routeTestedAt', 'routeTestSignals', 'publicationPolicy', 'publishReady', 'publishing'}
            route_ready = (value['state'] == 'connected_identity'
                           and value['route'] == 'official_api'
                           and value['routeDriver'] == 'threads_graph_api'
                           and value['routeState'] == 'publish_ready'
                           and isinstance(value['routeTestId'], str)
                           and __import__('re').fullmatch(r'threads-[a-f0-9]{40}', value['routeTestId'])
                           and isinstance(value['routeTestedAt'], str)
                           and value['routeTestSignals'] == ['identity_reverified', 'publishing_quota_read']
                           and value['publicationPolicy'] == 'exact_post_approval_required')
            if (set(value) != allowed or value['publishing'] is not False
                    or value['publishReady'] not in {False, True}
                    or (value['publishReady'] is True and not route_ready)
                    or (value['publishReady'] is False and value['routeState'] != 'not_tested')
                    or value['scope'] != 'threads_basic,threads_content_publish'
                    or value['route'] != 'official_api' or value['routeDriver'] != 'threads_graph_api'
                    or value['publicationPolicy'] != 'exact_post_approval_required'):
                raise ValueError('invalid_threads_status')
            return value
        except (StudioError, ValueError):
            return {'provider': 'threads', 'available': False, 'state': 'broker_unavailable', 'username': None, 'userId': None,
                    'scope': 'threads_basic,threads_content_publish', 'route': 'official_api',
                    'routeDriver': 'threads_graph_api', 'verifiedAt': None, 'expiresAt': None,
                    'identitySignals': [], 'routeState': 'not_tested', 'routeTestId': None,
                    'routeTestedAt': None, 'routeTestSignals': [],
                    'publicationPolicy': 'exact_post_approval_required', 'publishReady': False, 'publishing': False}

    def _threads_request(self, method, path, body=None):
        if not self.threads_child or self.threads_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55, verify=False) as client:
                response = client.request(method, f'https://127.0.0.1:{self.port + 4}{path}', json=body, headers={'Host': f'threads-jamesau.meta:{self.port + 4}', 'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required': 'Add the approved Threads OAuth configuration and trusted local TLS files, then restart Studio.',
                                'signin_already_pending': 'A Threads sign-in is already pending.',
                                'account_already_connected': 'A Threads identity is already connected.',
                                'invalid_identity': 'Enter the exact Threads username.',
                                'reconciliation_required': 'The previous Threads authorization outcome is unresolved. Reconcile it before retrying.',
                                'invalid_route_test_manifest': 'The Threads route test must target @jamesaucreates and the official text-post API.',
                                'publish_route_not_ready': 'Run the read-only Threads publishing route test first.',
                                'invalid_publish_manifest': 'Review the exact Threads text, account, destination and approval receipt.',
                                'idempotency_conflict': 'This Threads idempotency key belongs to different content.',
                                'threads_publish_unresolved': 'Threads did not return independently verified post evidence. Check the profile before retrying.'}
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private Threads connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private Threads connection request failed.', 503) from None

    def prepare_threads(self, username, scope):
        value = self._threads_request('POST', '/prepare', {'username': username, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.threads_begin_path = value['beginPath']
        return {'authorizationUrl': self.threads_authorize_url()}

    def threads_authorize_url(self):
        path, self.threads_begin_path = self.threads_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        return f'https://threads-jamesau.meta:{self.port + 4}{path}'

    def verify_threads(self):
        self._threads_request('POST', '/verify', {})
        return self.threads_status()

    def test_threads_route(self, value):
        self._threads_request('POST', '/route-test', value)
        return self.threads_status()

    def publish_threads_text(self, value):
        result = self._threads_request('POST', '/publish-text', value)
        expected = {'threadId', 'url', 'username', 'text', 'mediaType', 'timestamp', 'verifiedAt', 'replayed'}
        if (set(result) != expected or result['username'] != 'jamesaucreates'
                or result['mediaType'] != 'TEXT_POST' or not isinstance(result['threadId'], str)
                or not isinstance(result['url'], str) or not result['url'].startswith(('https://www.threads.com/', 'https://threads.com/', 'https://www.threads.net/', 'https://threads.net/'))
                or not isinstance(result['text'], str) or not isinstance(result['timestamp'], str)
                or not isinstance(result['verifiedAt'], str) or result['replayed'] not in {False, True}):
            raise StudioError('threads_publish_unresolved', 'Threads did not return independently verified post evidence. Check the profile before retrying.', 502)
        return result

    def pinterest_status(self):
        try:
            value = self._pinterest_request('GET', '/status')
            allowed = {'provider', 'available', 'state', 'username', 'accountId', 'accountType', 'scope', 'routeDriver', 'verifiedAt', 'expiresAt', 'identitySignals', 'publishReady', 'publishing'}
            allowed_scopes = {'user_accounts:read,boards:read,boards:write,boards:read_secret,boards:write_secret,pins:read,pins:write,pins:read_secret,pins:write_secret,ads:read,ads:write,billing:read,billing:write', 'controlled_browser_session'}
            if set(value) != allowed or value['publishReady'] is not False or value['publishing'] is not False or value['scope'] not in allowed_scopes or value['routeDriver'] not in {'official_api_oauth', 'controlled_browser'}:
                raise ValueError('invalid_pinterest_status')
            return value
        except (StudioError, ValueError):
            return {'provider': 'pinterest', 'available': False, 'state': 'broker_unavailable', 'username': None, 'accountId': None, 'accountType': None,
                    'scope': 'user_accounts:read,boards:read,boards:write,boards:read_secret,boards:write_secret,pins:read,pins:write,pins:read_secret,pins:write_secret,ads:read,ads:write,billing:read,billing:write', 'routeDriver': 'official_api_oauth', 'verifiedAt': None, 'expiresAt': None, 'identitySignals': [], 'publishReady': False, 'publishing': False}

    def _pinterest_request(self, method, path, body=None):
        if not self.pinterest_child or self.pinterest_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 5}{path}', json=body, headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required': 'Add the approved Pinterest OAuth app configuration and restart Studio.',
                                'signin_already_pending': 'A Pinterest sign-in is already pending.',
                                'account_already_connected': 'A Pinterest identity is already connected.',
                                'invalid_identity': 'Enter the exact Pinterest username: jamesaucreates.',
                                'reconciliation_required': 'The previous Pinterest authorization outcome is unresolved. Reconcile it before retrying.'}
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private Pinterest connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private Pinterest connection request failed.', 503) from None

    def prepare_pinterest(self, username, scope):
        value = self._pinterest_request('POST', '/prepare', {'username': username, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.pinterest_begin_path = value['beginPath']
        return {'authorizationPath': '/api/connections/pinterest/authorize'}

    def pinterest_authorize_url(self):
        path, self.pinterest_begin_path = self.pinterest_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        return f'http://127.0.0.1:{self.port + 5}{path}'

    def verify_pinterest(self):
        self._pinterest_request('POST', '/verify', {})
        return self.pinterest_status()

    def connect_pinterest_browser(self, username, identity_signals):
        return self._pinterest_request('POST', '/browser-connect', {'username': username, 'identitySignals': identity_signals})

    def reddit_status(self):
        try:
            value = self._reddit_request('GET', '/status')
            allowed = {'provider', 'available', 'state', 'username', 'accountId', 'profileUrl', 'scope', 'route', 'routeDriver', 'preferredPublishDrivers', 'sessionState', 'verifiedAt', 'expiresAt', 'identitySignals', 'routeState', 'routeTestId', 'routeTestedAt', 'routeTestSignals', 'publicationPolicy', 'publishReady', 'publishing'}
            route_signals = ['identity_reverified', 'composer_loaded', 'community_selector_present',
                             'title_and_body_fields_present', 'semantic_post_control_present']
            browser_ready = (value['state'] == 'connected_browser_identity'
                             and value['route'] == 'controlled_browser'
                             and value['routeDriver'] == 'in_app_browser'
                             and value['routeState'] == 'browser_publish_ready'
                             and isinstance(value['routeTestId'], str)
                             and value['routeTestId'].startswith('reddit-browser-')
                             and len(value['routeTestId']) == 47
                             and isinstance(value['routeTestedAt'], str)
                             and value['routeTestSignals'] == route_signals
                             and value['publicationPolicy'] == 'exact_post_approval_required')
            if (set(value) != allowed or value['publishing'] is not False
                    or value['publishReady'] not in {False, True}
                    or (value['publishReady'] is True and not browser_ready)
                    or (value['publishReady'] is False and value['routeState'] not in {'not_tested'})
                    or value['scope'] not in {'identity', 'browser_identity_only'}
                    or value['route'] not in {'official_api', 'controlled_browser'}
                    or value['routeDriver'] not in {'reddit_oauth', 'in_app_browser'}
                    or value['preferredPublishDrivers'] != ['computer_use', 'chrome']
                    or value['sessionState'] not in {'not_established', 'oauth_token_active', 'verify_before_each_action'}):
                raise ValueError('invalid_reddit_status')
            return value
        except (StudioError, ValueError):
            return {'provider': 'reddit', 'available': False, 'state': 'broker_unavailable', 'username': None, 'accountId': None,
                    'profileUrl': None, 'scope': 'identity', 'route': 'official_api', 'routeDriver': 'reddit_oauth',
                    'preferredPublishDrivers': ['computer_use', 'chrome'], 'sessionState': 'not_established',
                    'verifiedAt': None, 'expiresAt': None, 'identitySignals': [], 'routeState': 'not_tested',
                    'routeTestId': None, 'routeTestedAt': None, 'routeTestSignals': [],
                    'publicationPolicy': 'exact_post_approval_required', 'publishReady': False, 'publishing': False}

    def xiaohongshu_status(self):
        return self.xiaohongshu_identity.status() | self.xiaohongshu_mcp.status()

    def observe_xiaohongshu_profile(self, profile_url, nickname, rednote_id):
        return self.xiaohongshu_identity.observe_profile(profile_url, nickname, rednote_id)

    def confirm_xiaohongshu_creator_centre(self, rednote_id):
        self.xiaohongshu_identity.confirm_creator_centre(rednote_id)
        return self.xiaohongshu_status()

    def begin_xiaohongshu_private_login(self):
        identity = self.xiaohongshu_identity.status()
        if identity['state'] != 'identity_connected':
            raise StudioError('xiaohongshu_identity_required', 'Confirm the exact Xiaohongshu identity before private login.', 409)
        return self.xiaohongshu_mcp.begin_private_login()

    def verify_xiaohongshu_private_login(self):
        identity = self.xiaohongshu_identity.status()
        if identity['state'] != 'identity_connected':
            raise StudioError('xiaohongshu_identity_required', 'Confirm the exact Xiaohongshu identity before session verification.', 409)
        self.xiaohongshu_mcp.verify_identity(
            expected_rednote_id=identity['rednoteId'], expected_nickname=identity['nickname'])
        return self.xiaohongshu_status()

    def _reddit_request(self, method, path, body=None):
        if not self.reddit_child or self.reddit_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 6}{path}', json=body, headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required': 'Reddit API approval and the approved identity-only OAuth app configuration are required.',
                                'signin_already_pending': 'A Reddit sign-in is already pending.',
                                'account_already_connected': 'A Reddit identity is already connected.',
                                'invalid_identity': 'Enter the exact Reddit username: Ok-External401.',
                                'reconciliation_required': 'The previous Reddit authorization outcome is unresolved. Reconcile it before retrying.'}
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private Reddit connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private Reddit connection request failed.', 503) from None

    def prepare_reddit(self, username, scope):
        value = self._reddit_request('POST', '/prepare', {'username': username, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.reddit_begin_path = value['beginPath']
        return {'authorizationPath': '/api/connections/reddit/authorize'}

    def reddit_authorize_url(self):
        path, self.reddit_begin_path = self.reddit_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        return f'http://127.0.0.1:{self.port + 6}{path}'

    def verify_reddit(self):
        self._reddit_request('POST', '/verify', {})
        return self.reddit_status()

    def connect_reddit_browser(self, value):
        return self._reddit_request('POST', '/browser-connect', value)

    def enable_reddit_browser_publishing(self, value):
        return self._reddit_request('POST', '/enable-browser-publishing', value)

    def _x_request(self, method, path, body=None):
        if not self.x_child or self.x_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=35) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 8}{path}', json=body,
                                          headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {
                        'configuration_required': 'X OAuth configuration is required. Store the public OAuth client ID in this Mac’s Keychain, then restart Studio.',
                        'signin_already_pending': 'An X sign-in is already pending.',
                        'account_already_connected': 'An X identity is already connected.',
                        'invalid_identity': 'Enter the exact X handle: jamesaucreates.',
                        'reconciliation_required': 'The prior X authorization outcome is unresolved. Reconcile it before retrying.',
                    }
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private X connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private X connection request failed.', 503) from None

    def x_status(self):
        empty = {'provider': 'x', 'available': False, 'state': 'broker_unavailable', 'username': None, 'accountId': None,
                 'profileUrl': None, 'scope': 'tweet.read users.read tweet.write offline.access', 'route': 'official_api',
                 'routeDriver': 'x_oauth2_pkce', 'sessionState': 'not_established', 'verifiedAt': None, 'expiresAt': None,
                 'identitySignals': [], 'routeState': 'not_tested', 'routeTestId': None, 'routeTestedAt': None,
                 'routeTestSignals': [], 'publicationPolicy': 'exact_post_approval_required', 'publishReady': False, 'publishing': False}
        try:
            value = self._x_request('GET', '/status')
            if set(value) != set(empty) or value['publishing'] is not False or type(value['publishReady']) is not bool:
                raise ValueError('invalid_x_status')
            return value
        except (StudioError, ValueError):
            return empty

    def prepare_x(self, username, scope):
        value = self._x_request('POST', '/prepare', {'username': username, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.x_begin_path = value['beginPath']
        return {'authorizationPath': '/api/connections/x/authorize'}

    def x_authorize_url(self):
        path, self.x_begin_path = self.x_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        return f'http://127.0.0.1:{self.port + 8}{path}'

    def verify_x(self):
        self._x_request('POST', '/verify', {})
        return self.x_status()

    def _linkedin_request(self, method, path, body=None):
        if not self.linkedin_child or self.linkedin_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=35) as client:
                response = client.request(method, f'http://127.0.0.1:{self.port + 9}{path}', json=body,
                                          headers={'X-Studio-Broker': self.capability})
                if response.status_code != 200:
                    code = response.json().get('error')
                    messages = {'configuration_required': 'LinkedIn OAuth credentials are required in this Mac’s Keychain.',
                                'identity_not_connected': 'The LinkedIn identity is not connected.',
                                'account_already_connected': 'A LinkedIn identity is already connected.',
                                'invalid_identity': 'Use the approved LinkedIn email: jamesaucreates@gmail.com.'}
                    raise StudioError(code if code in messages else 'connection_request_failed', messages.get(code, 'The private LinkedIn connection request failed.'), response.status_code)
                return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError('connection_request_failed', 'The private LinkedIn connection request failed.', 503) from None

    def linkedin_status(self):
        empty = {'provider':'linkedin','available':False,'state':'broker_unavailable','email':None,'subject':None,'name':None,'profileUrl':None,
                 'scope':'openid profile email w_member_social','route':'official_api','routeDriver':'linkedin_oauth2_posts_api','sessionState':'not_established',
                 'verifiedAt':None,'expiresAt':None,'identitySignals':[],'publicationPolicy':'exact_post_approval_required','publishReady':False,'publishing':False,'schedulingAvailable':False}
        try:
            value = self._linkedin_request('GET', '/status')
            if set(value) != set(empty) or value['publishing'] is not False or type(value['publishReady']) is not bool:
                raise ValueError('invalid_linkedin_status')
            return value
        except (StudioError, ValueError):
            return empty

    def prepare_linkedin(self, email, scope):
        value = self._linkedin_request('POST', '/prepare', {'email':email, 'scope':scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.linkedin_begin_path = value['beginPath']
        return {'authorizationPath':'/api/connections/linkedin/authorize'}

    def linkedin_authorize_url(self):
        path, self.linkedin_begin_path = self.linkedin_begin_path, None
        if not path:
            raise StudioError('signin_not_prepared', 'Prepare the exact LinkedIn connection first.', 409)
        return f'http://127.0.0.1:{self.port + 9}{path}'

    def verify_linkedin(self):
        self._linkedin_request('POST', '/verify', {})
        return self.linkedin_status()

    def publish_linkedin_text(self, value):
        return self._linkedin_request('POST', '/publish-text', value)

    def preview_linkedin_schedule(self, value):
        return self._linkedin_request('POST', '/schedule-preview', value)

    def schedule_linkedin_text(self, value):
        return self._linkedin_request('POST', '/schedule-text', value)

    def linkedin_scheduled(self):
        return self._linkedin_request('GET', '/scheduled')

    def _youtube_request(self, method, path, body=None):
        if not self.youtube_child or self.youtube_child.poll() is not None:
            raise StudioError('connection_broker_unavailable', status=503)
        try:
            with httpx.Client(trust_env=False, timeout=55) as client:
                response=client.request(method,f'http://127.0.0.1:{self.port + 1}{path}',json=body,headers={'X-Studio-Broker':self.capability})
                if response.status_code != 200:
                    code=response.json().get('error'); messages={'configuration_required':'Add the Google OAuth client configuration and restart Studio.','signin_already_pending':'A YouTube sign-in is already pending.','account_already_connected':'A YouTube account with upload access is already connected.','invalid_identity':'Enter the exact Google email and YouTube channel ID.','publish_connection_required':'Reconnect YouTube with upload access first.','invalid_upload_manifest':'Review every required video field.','invalid_publish_time':'Scheduling requires Private visibility and a future time.','invalid_video_file':'Choose a non-empty video up to 256 MiB.','youtube_upload_unresolved':'YouTube did not return independently verified upload evidence. Check YouTube Studio before retrying.'}
                    raise StudioError(code if code in messages else 'connection_request_failed',messages.get(code,'The private YouTube connection request failed.'),response.status_code)
                return response.json()
        except StudioError: raise
        except (httpx.HTTPError,ValueError): raise StudioError('connection_request_failed','The private YouTube connection request failed.',503) from None

    def prepare_youtube(self,email,channel_id,scope):
        value=self._youtube_request('POST','/prepare',{'email':email,'channelId':channel_id,'scope':scope})
        import re
        if set(value)!={'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}',value['beginPath']): raise StudioError('invalid_signin_response',status=502)
        self.youtube_begin_path=value['beginPath'];return {'authorizationPath':'/api/connections/youtube/authorize'}

    def youtube_authorize_url(self):
        path=getattr(self,'youtube_begin_path',None);self.youtube_begin_path=None
        if not path: raise StudioError('signin_not_prepared','Prepare the exact connection in Studio first.',409)
        return f'http://127.0.0.1:{self.port + 1}{path}'

    def prepare(self, handle, scope):
        value = self._request('POST', '/prepare', {'handle': handle, 'scope': scope})
        import re
        if set(value) != {'beginPath'} or not re.fullmatch(r'/begin/[a-f0-9]{64}', value['beginPath']):
            raise StudioError('invalid_signin_response', status=502)
        self.begin_path = value['beginPath']
        # Neither provider URL nor secret-bearing parameters enter Studio JSON.
        return {'authorizationPath': '/api/connections/bluesky/authorize'}

    def authorize_url(self):
        if not self.begin_path:
            raise StudioError('signin_not_prepared', 'Prepare the exact connection in Studio first.', 409)
        path, self.begin_path = self.begin_path, None
        return f'http://127.0.0.1:{self.port}{path}'

    def shutdown(self):
        self.xiaohongshu_mcp.shutdown()
        if self.child:
            if self.child.stdin:
                self.child.stdin.close()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                self.child.wait(timeout=5)
            self.child = None
        if self.youtube_child:
            if self.youtube_child.stdin: self.youtube_child.stdin.close()
            try: self.youtube_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.youtube_child.terminate(); self.youtube_child.wait(timeout=5)
            self.youtube_child=None
        if self.instagram_child:
            if self.instagram_child.stdin and not self.instagram_child.stdin.closed: self.instagram_child.stdin.close()
            try: self.instagram_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.instagram_child.terminate(); self.instagram_child.wait(timeout=5)
            self.instagram_child=None
        if self.facebook_child:
            if self.facebook_child.stdin and not self.facebook_child.stdin.closed: self.facebook_child.stdin.close()
            try: self.facebook_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.facebook_child.terminate(); self.facebook_child.wait(timeout=5)
            self.facebook_child=None

        if self.tiktok_child:
            if self.tiktok_child.stdin: self.tiktok_child.stdin.close()
            try: self.tiktok_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.tiktok_child.terminate(); self.tiktok_child.wait(timeout=5)
            self.tiktok_child=None
        if self.threads_child:
            if self.threads_child.stdin: self.threads_child.stdin.close()
            try: self.threads_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.threads_child.terminate(); self.threads_child.wait(timeout=5)
            self.threads_child=None
        if self.pinterest_child:
            if self.pinterest_child.stdin: self.pinterest_child.stdin.close()
            try: self.pinterest_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.pinterest_child.terminate(); self.pinterest_child.wait(timeout=5)
            self.pinterest_child=None
        if self.reddit_child:
            if self.reddit_child.stdin: self.reddit_child.stdin.close()
            try: self.reddit_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.reddit_child.terminate(); self.reddit_child.wait(timeout=5)
            self.reddit_child=None
        if self.linkedin_child:
            if self.linkedin_child.stdin: self.linkedin_child.stdin.close()
            try: self.linkedin_child.wait(timeout=5)
            except subprocess.TimeoutExpired: self.linkedin_child.terminate(); self.linkedin_child.wait(timeout=5)
            self.linkedin_child=None


def register_connection_routes(app, broker, body_parser):
    @app.get('/api/connections')
    def status():
        return {'bluesky': broker.status(), 'youtube': broker.youtube_status(), 'instagram': broker.instagram_status(), 'facebook': broker.facebook_status(), 'tiktok': broker.tiktok_status(), 'threads': broker.threads_status(), 'pinterest': broker.pinterest_status(), 'reddit': broker.reddit_status(), 'x': broker.x_status(), 'linkedin': broker.linkedin_status(), 'xiaohongshu': broker.xiaohongshu_status()}

    @app.get('/api/connections/linkedin')
    def linkedin_status():
        return broker.linkedin_status()

    @app.post('/api/connections/xiaohongshu/observe-profile')
    async def observe_xiaohongshu_profile(request: Request):
        value = await body_parser(request)
        if set(value) != {'profileUrl', 'nickname', 'rednoteId', 'identityConsent'} or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed public Xiaohongshu identity. No publishing access is requested.', 422)
        return await run_in_threadpool(broker.observe_xiaohongshu_profile, value['profileUrl'], value['nickname'], value['rednoteId'])

    @app.post('/api/connections/xiaohongshu/confirm-creator-centre')
    async def confirm_xiaohongshu_creator_centre(request: Request):
        value = await body_parser(request)
        if set(value) != {'rednoteId', 'creatorCentreConfirmed', 'identityConsent'} or value.get('creatorCentreConfirmed') is not True or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Confirm that the Creator Center displays the same RedNote ID before connecting this identity.', 422)
        return await run_in_threadpool(broker.confirm_xiaohongshu_creator_centre, value['rednoteId'])

    @app.post('/api/connections/xiaohongshu/begin-private-login')
    async def begin_xiaohongshu_private_login(request: Request):
        value = await body_parser(request)
        if set(value) != {'privateHandoff', 'accountLocked'} or value.get('privateHandoff') is not True or value.get('accountLocked') is not True:
            raise StudioError('private_handoff_consent_required', 'Review the exact account and close other RedNote web sessions before private login.', 422)
        return await run_in_threadpool(broker.begin_xiaohongshu_private_login)

    @app.post('/api/connections/xiaohongshu/verify-private-login')
    async def verify_xiaohongshu_private_login(request: Request):
        value = await body_parser(request)
        if value != {'sensitiveSurfaceClosed': True}:
            raise StudioError('private_handoff_incomplete', 'Close the sensitive login surface before session verification.', 422)
        return await run_in_threadpool(broker.verify_xiaohongshu_private_login)

    @app.post('/api/connections/bluesky/prepare')
    async def prepare(request: Request):
        value = await body_parser(request)
        if set(value) != {'handle', 'scope', 'identityConsent'} or value['scope'] != 'atproto' or value['identityConsent'] is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed account and identity-only access.', 422)
        if not isinstance(value['handle'], str) or len(value['handle']) > 253:
            raise StudioError('invalid_handle', status=422)
        return await run_in_threadpool(broker.prepare, value['handle'], value['scope'])

    @app.get('/api/connections/bluesky/authorize')
    def authorize():
        return RedirectResponse(broker.authorize_url(), status_code=303)

    @app.post('/api/connections/youtube/prepare')
    async def prepare_youtube(request: Request):
        value=await body_parser(request)
        scope='openid email https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload'
        if set(value)!={'email','channelId','scope','identityConsent'} or value.get('scope')!=scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required','Review and confirm the displayed YouTube identity and video-upload access.',422)
        if not isinstance(value.get('email'),str) or not isinstance(value.get('channelId'),str): raise StudioError('invalid_identity',status=422)
        return await run_in_threadpool(broker.prepare_youtube,value['email'],value['channelId'],scope)

    @app.post('/api/connections/youtube/verify')
    async def verify_youtube(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_youtube)

    @app.get('/api/connections/youtube/authorize')
    def authorize_youtube(): return RedirectResponse(broker.youtube_authorize_url(),status_code=303)

    @app.post('/api/connections/youtube/upload')
    async def upload_youtube(request: Request):
        if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
            raise StudioError('multipart_required', 'Choose a local video file.', 422)
        async with request.form(max_files=1, max_fields=8, max_part_size=256 * 1024 * 1024) as form:
            expected={'file','title','description','categoryId','privacyStatus','publishAt','madeForKids','publicationConsent'}
            if set(form) != expected or len(form.getlist('file')) != 1 or form.get('publicationConsent') != 'true':
                raise StudioError('exact_publication_approval_required', 'Review and approve this exact video, account, visibility and time.', 422)
            file=form.get('file'); content=await file.read(256 * 1024 * 1024 + 1)
            if len(content)>256 * 1024 * 1024 or not content:
                raise StudioError('invalid_video_file', 'Choose a non-empty video up to 256 MiB.', 422)
            made_for_kids={'true':True,'false':False}.get(form.get('madeForKids'))
            if made_for_kids is None: raise StudioError('invalid_upload_manifest', status=422)
            manifest={'title':form.get('title'),'description':form.get('description'),'categoryId':form.get('categoryId'),'privacyStatus':form.get('privacyStatus'),'publishAt':form.get('publishAt') or None,'madeForKids':made_for_kids}
            if not all(isinstance(manifest[key], str) for key in ('title','description','categoryId','privacyStatus')):
                raise StudioError('invalid_upload_manifest', status=422)
            return await run_in_threadpool(broker.upload_youtube, manifest, content)

    @app.post('/api/connections/instagram/prepare')
    async def prepare_instagram(request: Request):
        value = await body_parser(request)
        scope = 'instagram_business_basic,instagram_business_content_publish'
        if set(value) != {'username', 'scope', 'identityConsent'} or value.get('scope') != scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed Instagram identity and approval-gated publishing access.', 422)
        if not isinstance(value.get('username'), str) or not __import__('re').fullmatch(r'[A-Za-z0-9._]{1,30}', value['username']):
            raise StudioError('invalid_identity', status=422)
        return await run_in_threadpool(broker.prepare_instagram, value['username'], scope)

    @app.post('/api/connections/instagram/verify')
    async def verify_instagram(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_instagram)

    @app.get('/api/connections/instagram/authorize')
    def authorize_instagram(): return RedirectResponse(broker.instagram_authorize_url(), status_code=303)

    @app.post('/api/connections/instagram/route-test')
    async def test_instagram_route(request: Request):
        value = await body_parser(request)
        manifest = {'account':'@jamesaucreates','destination':'main_profile_feed','nativeFormat':'instagram.feed_image','mediaType':'IMAGE','route':'official_api','routeDriver':'instagram_api_with_instagram_login'}
        if value != manifest:
            raise StudioError('invalid_route_test_manifest','The Instagram route test must target @jamesaucreates and the official image-post API.',422)
        return await run_in_threadpool(broker.test_instagram_route, manifest)

    @app.post('/api/connections/instagram/publish-image')
    async def publish_instagram_image(request: Request):
        value = await body_parser(request)
        expected={'account','destination','nativeFormat','mediaType','imageUrl','caption','altText','visibility','scheduledAt','derivatives','approvalReceiptHash','idempotencyKey','publicationConsent'}
        if set(value) != expected or value.get('publicationConsent') is not True:
            raise StudioError('exact_publication_approval_required','Review and approve this exact Instagram image, caption, account and timing.',422)
        manifest={key:value.get(key) for key in ('account','destination','nativeFormat','mediaType','imageUrl','caption','altText','visibility','scheduledAt','derivatives')}
        canonical=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        approval_hash=hashlib.sha256(canonical.encode()).hexdigest()
        idempotency_key=hashlib.sha256(('instagram.publish\0'+approval_hash).encode()).hexdigest()
        if value.get('approvalReceiptHash') != approval_hash or value.get('idempotencyKey') != idempotency_key:
            raise StudioError('exact_publication_approval_required','The Instagram approval receipt does not match the exact post.',422)
        return await run_in_threadpool(broker.publish_instagram_image, manifest | {'approvalReceiptHash':approval_hash,'idempotencyKey':idempotency_key})

    @app.post('/api/connections/facebook/prepare')
    async def prepare_facebook(request: Request):
        value=await body_parser(request)
        scope='pages_show_list,pages_read_engagement,pages_manage_posts'
        if set(value) != {'pageName','pageId','scope','identityConsent'} or value.get('scope') != scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required','Review and confirm the exact Facebook Page and approval-gated publishing access.',422)
        if not isinstance(value.get('pageName'),str) or not isinstance(value.get('pageId'),str):
            raise StudioError('invalid_identity',status=422)
        return await run_in_threadpool(broker.prepare_facebook,value['pageName'],value['pageId'],scope)

    @app.get('/api/connections/facebook/authorize')
    def authorize_facebook(): return RedirectResponse(broker.facebook_authorize_url(),status_code=303)

    @app.post('/api/connections/facebook/verify')
    async def verify_facebook(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request',status=422)
        return await run_in_threadpool(broker.verify_facebook)

    @app.post('/api/connections/facebook/route-test')
    async def test_facebook_route(request: Request):
        value=await body_parser(request)
        state=broker.facebook_status()
        manifest={'account':state.get('pageName'),'pageId':state.get('pageId'),'destination':'page_feed','nativeFormat':'facebook.page_post','route':'official_api','routeDriver':'facebook_pages_api'}
        if value != manifest:
            raise StudioError('invalid_route_test_manifest','The Facebook route test must match the connected Page.',422)
        return await run_in_threadpool(broker.test_facebook_route,manifest)

    @app.post('/api/connections/facebook/publish-post')
    async def publish_facebook_post(request: Request):
        value=await body_parser(request)
        expected={'account','pageId','destination','nativeFormat','message','link','visibility','scheduledAt','derivatives','approvalReceiptHash','idempotencyKey','publicationConsent'}
        if set(value) != expected or value.get('publicationConsent') is not True:
            raise StudioError('exact_publication_approval_required','Review and approve this exact Facebook Page post, destination and timing.',422)
        manifest={key:value.get(key) for key in ('account','pageId','destination','nativeFormat','message','link','visibility','scheduledAt','derivatives')}
        canonical=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        approval_hash=hashlib.sha256(canonical.encode()).hexdigest()
        idempotency_key=hashlib.sha256(('facebook.publish\0'+approval_hash).encode()).hexdigest()
        if value.get('approvalReceiptHash') != approval_hash or value.get('idempotencyKey') != idempotency_key:
            raise StudioError('exact_publication_approval_required','The Facebook approval receipt does not match the exact post.',422)
        return await run_in_threadpool(broker.publish_facebook_post,manifest | {'approvalReceiptHash':approval_hash,'idempotencyKey':idempotency_key})

    @app.post('/api/connections/tiktok/prepare')
    async def prepare_tiktok(request: Request):
        value = await body_parser(request)
        scope = 'user.info.basic,user.info.profile'
        if set(value) != {'username', 'scope', 'identityConsent'} or value.get('scope') != scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed TikTok identity and identity-only access.', 422)
        if not isinstance(value.get('username'), str) or not __import__('re').fullmatch(r'[A-Za-z0-9._]{1,24}', value['username']):
            raise StudioError('invalid_identity', status=422)
        return await run_in_threadpool(broker.prepare_tiktok, value['username'], scope)

    @app.post('/api/connections/tiktok/verify')
    async def verify_tiktok(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_tiktok)

    @app.get('/api/connections/tiktok/authorize')
    def authorize_tiktok(): return RedirectResponse(broker.tiktok_authorize_url(), status_code=303)

    @app.post('/api/connections/threads/prepare')
    async def prepare_threads(request: Request):
        value = await body_parser(request)
        scope = 'threads_basic,threads_content_publish'
        if set(value) != {'username', 'scope', 'identityConsent'} or value.get('scope') != scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed Threads identity and the future approved-publishing access.', 422)
        if value.get('username') != 'jamesaucreates':
            raise StudioError('invalid_identity', 'Enter the approved Threads username: jamesaucreates.', 422)
        return await run_in_threadpool(broker.prepare_threads, value['username'], scope)

    @app.post('/api/connections/threads/verify')
    async def verify_threads(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_threads)

    @app.post('/api/connections/threads/route-test')
    async def test_threads_route(request: Request):
        value = await body_parser(request)
        manifest = {
            'account': '@jamesaucreates',
            'destination': 'main_profile_feed',
            'nativeFormat': 'threads.post',
            'mediaType': 'TEXT',
            'route': 'official_api',
            'routeDriver': 'threads_graph_api',
        }
        if value != manifest:
            raise StudioError('invalid_route_test_manifest', 'The Threads route test must target @jamesaucreates and the official text-post API.', 422)
        return await run_in_threadpool(broker.test_threads_route, manifest)

    @app.post('/api/connections/threads/publish-text')
    async def publish_threads_text(request: Request):
        value = await body_parser(request)
        expected = {'account', 'destination', 'nativeFormat', 'mediaType', 'text', 'visibility',
                    'replyControl', 'scheduledAt', 'media', 'derivatives', 'approvalReceiptHash',
                    'idempotencyKey', 'publicationConsent'}
        if set(value) != expected or value.get('publicationConsent') is not True:
            raise StudioError('exact_publication_approval_required', 'Review and approve this exact Threads post, account, destination and timing.', 422)
        manifest = {
            'account': value.get('account'),
            'destination': value.get('destination'),
            'nativeFormat': value.get('nativeFormat'),
            'mediaType': value.get('mediaType'),
            'text': value.get('text'),
            'visibility': value.get('visibility'),
            'replyControl': value.get('replyControl'),
            'scheduledAt': value.get('scheduledAt'),
            'media': value.get('media'),
            'derivatives': value.get('derivatives'),
        }
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        approval_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        idempotency_key = hashlib.sha256(('threads.publish\0' + approval_hash).encode('utf-8')).hexdigest()
        if (value.get('approvalReceiptHash') != approval_hash
                or value.get('idempotencyKey') != idempotency_key):
            raise StudioError('exact_publication_approval_required', 'The Threads approval receipt does not match the exact post.', 422)
        return await run_in_threadpool(broker.publish_threads_text, manifest | {
            'approvalReceiptHash': approval_hash,
            'idempotencyKey': idempotency_key,
        })

    @app.get('/api/connections/threads/authorize')
    def authorize_threads(): return RedirectResponse(broker.threads_authorize_url(), status_code=303)

    @app.post('/api/connections/pinterest/prepare')
    async def prepare_pinterest(request: Request):
        value = await body_parser(request)
        scope = 'user_accounts:read,boards:read,boards:write,boards:read_secret,boards:write_secret,pins:read,pins:write,pins:read_secret,pins:write_secret,ads:read,ads:write,billing:read,billing:write'
        if set(value) != {'username', 'scope', 'identityConsent'} or value.get('scope') != scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed Pinterest identity and per-Pin approval-gated access.', 422)
        if value.get('username') != 'jamesaucreates':
            raise StudioError('invalid_identity', 'Enter the approved Pinterest username: jamesaucreates.', 422)
        return await run_in_threadpool(broker.prepare_pinterest, value['username'], scope)

    @app.post('/api/connections/pinterest/verify')
    async def verify_pinterest(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_pinterest)

    @app.get('/api/connections/pinterest/authorize')
    def authorize_pinterest(): return RedirectResponse(broker.pinterest_authorize_url(), status_code=303)

    @app.post('/api/connections/pinterest/browser-connect')
    async def connect_pinterest_browser(request: Request):
        value = await body_parser(request)
        signals = ['business_hub_name_and_handle', 'public_profile_name_and_handle']
        if set(value) != {'username', 'identitySignals', 'identityConsent'} or value.get('username') != 'jamesaucreates' or value.get('identitySignals') != signals or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Confirm the exact browser-verified Pinterest identity evidence.', 422)
        return await run_in_threadpool(broker.connect_pinterest_browser, value['username'], signals)

    @app.post('/api/connections/reddit/prepare')
    async def prepare_reddit(request: Request):
        value = await body_parser(request)
        if set(value) != {'username', 'scope', 'identityConsent'} or value.get('scope') != 'identity' or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed Reddit identity and identity-only access.', 422)
        if value.get('username') != 'Ok-External401':
            raise StudioError('invalid_identity', 'Enter the approved Reddit username: Ok-External401.', 422)
        return await run_in_threadpool(broker.prepare_reddit, value['username'], 'identity')

    @app.post('/api/connections/reddit/verify')
    async def verify_reddit(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_reddit)

    @app.post('/api/connections/reddit/browser-connect')
    async def connect_reddit_browser(request: Request):
        value = await body_parser(request)
        expected = {
            'username': 'Ok-External401',
            'profileUrl': 'https://www.reddit.com/user/Ok-External401/',
            'identitySignals': ['signed_in_preferences_account_link', 'owner_profile_edit_controls_and_canonical_url'],
            'route': 'controlled_browser',
            'routeDriver': 'in_app_browser',
            'preferredPublishDrivers': ['computer_use', 'chrome'],
            'identityConsent': True,
        }
        if value != expected:
            raise StudioError('exact_connection_consent_required', 'Confirm the exact browser-verified Reddit identity and controlled-browser route.', 422)
        broker_value = {key: item for key, item in value.items() if key != 'identityConsent'}
        return await run_in_threadpool(broker.connect_reddit_browser, broker_value)

    @app.post('/api/connections/reddit/enable-browser-publishing')
    async def enable_reddit_browser_publishing(request: Request):
        value = await body_parser(request)
        expected = {
            'username': 'Ok-External401',
            'identitySignals': ['signed_in_preferences_account_link', 'owner_profile_edit_controls_and_canonical_url'],
            'route': 'controlled_browser',
            'routeDriver': 'in_app_browser',
            'routeTestSignals': ['identity_reverified', 'composer_loaded', 'community_selector_present',
                                 'title_and_body_fields_present', 'semantic_post_control_present'],
            'publicationPolicy': 'exact_post_approval_required',
            'userAuthorization': True,
        }
        if value != expected:
            raise StudioError('exact_publish_enablement_required', 'Confirm this exact Reddit account and the completed non-mutating composer route test.', 422)
        return await run_in_threadpool(broker.enable_reddit_browser_publishing, value)

    @app.get('/api/connections/reddit/authorize')
    def authorize_reddit(): return RedirectResponse(broker.reddit_authorize_url(), status_code=303)

    @app.post('/api/connections/x/prepare')
    async def prepare_x(request: Request):
        value = await body_parser(request)
        scope = 'tweet.read users.read tweet.write offline.access'
        if set(value) != {'username', 'scope', 'identityConsent'} or value.get('scope') != scope or value.get('identityConsent') is not True:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the displayed X identity, post-write access, and persistent refresh access.', 422)
        if value.get('username') != 'jamesaucreates':
            raise StudioError('invalid_identity', 'Enter the approved X handle: jamesaucreates.', 422)
        return await run_in_threadpool(broker.prepare_x, value['username'], scope)

    @app.post('/api/connections/x/verify')
    async def verify_x(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_x)

    @app.get('/api/connections/x/authorize')
    def authorize_x(): return RedirectResponse(broker.x_authorize_url(), status_code=303)

    @app.post('/api/connections/linkedin/prepare')
    async def prepare_linkedin(request: Request):
        value = await body_parser(request)
        scope = 'openid profile email w_member_social'
        if value != {'email':'jamesaucreates@gmail.com','scope':scope,'identityConsent':True}:
            raise StudioError('exact_connection_consent_required', 'Review and confirm the exact LinkedIn identity and scopes.', 422)
        return await run_in_threadpool(broker.prepare_linkedin, value['email'], scope)

    @app.post('/api/connections/linkedin/verify')
    async def verify_linkedin(request: Request):
        if await body_parser(request) != {}:
            raise StudioError('invalid_request', status=422)
        return await run_in_threadpool(broker.verify_linkedin)

    @app.get('/api/connections/linkedin/authorize')
    def authorize_linkedin(): return RedirectResponse(broker.linkedin_authorize_url(), status_code=303)

    @app.post('/api/connections/linkedin/publish-text')
    async def publish_linkedin_text(request: Request):
        value = await body_parser(request)
        expected = {
            'text': 'Testing the LinkedIn connection for James Au Studio. This post was reviewed and sent through my local approval workflow.',
            'approvalReceiptHash': 'sha256:8a311cb35fe270fc880e24b3fa6319c48f338b39711e3a12e5b0c436cbbc67df',
            'idempotencyKey': 'linkedin-route-test-2026-09-14-v1',
            'publicationConsent': True,
        }
        if value != expected:
            raise StudioError('exact_publish_approval_required', 'This endpoint accepts only the approved LinkedIn route-test receipt.', 422)
        return await run_in_threadpool(broker.publish_linkedin_text, value)

    @app.post('/api/connections/linkedin/schedule-preview')
    async def preview_linkedin_schedule(request: Request):
        value = await body_parser(request)
        if set(value) != {'text', 'scheduledAt'}:
            raise StudioError('invalid_schedule', 'Enter exact post text and a future scheduled time.', 422)
        return await run_in_threadpool(broker.preview_linkedin_schedule, value)

    @app.post('/api/connections/linkedin/schedule-text')
    async def schedule_linkedin_text(request: Request):
        value = await body_parser(request)
        if set(value) != {'text', 'scheduledAt', 'approvalReceiptHash', 'idempotencyKey', 'publicationConsent'} or value.get('publicationConsent') is not True:
            raise StudioError('exact_schedule_approval_required', 'Review and approve the exact scheduled LinkedIn post.', 422)
        return await run_in_threadpool(broker.schedule_linkedin_text, value)

    @app.get('/api/connections/linkedin/scheduled')
    async def linkedin_scheduled():
        return await run_in_threadpool(broker.linkedin_scheduled)

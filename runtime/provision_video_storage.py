"""Build-time, create-only setup of Rafii's existing private Supabase video bucket.

No objects are uploaded, listed, changed or removed. An existing bucket's settings
are only verified. Disabled releases make no network request. Secrets and response
bodies never appear in build output. Run only in the existing Vercel cloud build.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import runpy
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

BUCKET = 'postriff-video'
MAX_BYTES = 50_000_000
MIMES = ['video/mp4', 'video/quicktime']
TIMEOUT = 12
MAX_RESPONSE = 64 * 1024


class ProvisionError(Exception):
    """Messages are fixed public operational reasons, never provider details."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, url, headers, body=None):
    opener = build_opener(NoRedirect(), HTTPSHandler())
    try:
        with opener.open(Request(url, data=body, headers=headers, method=method), timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ProvisionError('Private video storage response exceeded its safe limit.')
            return response.status, raw
    except HTTPError as error:
        status = error.code
        error.close()
        return status, b''
    except (URLError, TimeoutError, OSError):
        raise ProvisionError('Private video storage request failed.') from None


def configuration(env):
    if env.get('VERCEL') != '1' or env.get('VERCEL_ENV') not in ('production', 'preview'):
        raise ProvisionError('Video storage provisioning requires a pinned Vercel release environment.')
    if env['VERCEL_ENV'] == 'preview':
        # This existing guard checks distinct staging/production projects, matching
        # DB/auth/storage, pinned staging secrets and disabled external operations.
        guard = Path(__file__).resolve().parents[1] / 'src/postriff_phase2/deployment.py'
        try:
            runpy.run_path(str(guard))['isolated_environment'](env)
        except (OSError, ValueError, KeyError, TypeError):
            raise ProvisionError('Preview video storage requires the existing staging isolation checks.') from None
        expected = env.get('POSTRIFF_STAGING_PROJECT_REF', '')
    else:
        expected = env.get('POSTRIFF_PRODUCTION_PROJECT_REF', '')
    if not re.fullmatch(r'[a-z0-9]{20}', expected):
        raise ProvisionError('Video storage requires the pinned release project reference.')
    project = 'https://' + expected + '.supabase.co'
    for name in ('POSTRIFF_SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL'):
        raw = env.get(name, '')
        parsed = urlparse(raw)
        if raw.rstrip('/') != project or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
            raise ProvisionError('Video storage identity must match the pinned release project.')
    if (env.get('POSTRIFF_VIDEO_BUCKET') or BUCKET) != BUCKET:
        raise ProvisionError('Video storage provisioning is limited to the approved private video bucket.')
    secret = env.get('POSTRIFF_SUPABASE_SECRET_KEY', '')
    if not isinstance(secret, str) or not secret.isascii() or any(character.isspace() for character in secret):
        raise ProvisionError('Video storage requires the existing server-only storage credential.')
    if secret.startswith('sb_secret_'):
        valid = bool(re.fullmatch(r'sb_secret_[A-Za-z0-9_-]{20,}', secret))
    else:
        try:
            payload = secret.split('.')[1]
            decoded = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            valid = decoded.get('role') == 'service_role' and decoded.get('ref') == expected
        except (ValueError, TypeError, IndexError, AttributeError):
            valid = False
    if not valid:
        raise ProvisionError('Video storage requires the existing server-only storage credential.')
    return project, {'Authorization': 'Bearer ' + secret, 'apikey': secret, 'Content-Type': 'application/json'}


def verify(raw):
    try:
        found = json.loads(raw)
    except (ValueError, TypeError):
        raise ProvisionError('Private video bucket configuration could not be verified.') from None
    if (not isinstance(found, dict) or found.get('id') != BUCKET or found.get('name', BUCKET) != BUCKET
            or found.get('public') is not False
            or type(found.get('file_size_limit')) is not int
            or not 0 < found['file_size_limit'] <= MAX_BYTES
            or not isinstance(found.get('allowed_mime_types'), list)
            or sorted(found['allowed_mime_types']) != MIMES):
        raise ProvisionError('Existing video bucket must be private, allow only MP4/MOV and have a limit of at most 50 MB. Existing settings were not changed.')
    return found


def provision(env, send=request):
    if str(env.get('RAFII_VIDEO_UPLOADS_ENABLED', '')).strip().lower() not in ('1', 'true', 'yes', 'on'):
        return {'status': 'disabled', 'changed': False}
    project, headers = configuration(env)
    endpoint = project + '/storage/v1/bucket/' + BUCKET
    status, raw = send('GET', endpoint, headers)
    if status == 200:
        verify(raw)
        return {'status': 'verified', 'changed': False}
    if status != 404:
        raise ProvisionError('Private video bucket lookup failed. No creation was attempted.')
    body = json.dumps({'id': BUCKET, 'name': BUCKET, 'public': False, 'file_size_limit': MAX_BYTES, 'allowed_mime_types': MIMES}).encode()
    # A concurrent release may create this bucket. Reconcile by reading the same
    # target exactly once; never retry a POST with an unknown outcome.
    try:
        created_status, _ = send('POST', project + '/storage/v1/bucket', headers, body)
    except ProvisionError:
        created_status = None
    status, raw = send('GET', endpoint, headers)
    if status != 200:
        raise ProvisionError('Private video bucket creation could not be verified. No retry or update was attempted.')
    verify(raw)
    return {'status': 'created' if created_status in (200, 201) else 'verified_after_create_attempt', 'changed': created_status in (200, 201)}


def main(env=None):
    try:
        result = provision(os.environ if env is None else env)
    except ProvisionError as error:
        print(json.dumps({'status': 'failed', 'reason': str(error)}))
        return 1
    except (ValueError, TypeError):
        # Preserve fixed reasons from our own validation while preventing any
        # provider, URL parser or untrusted body from leaking into build logs.
        print(json.dumps({'status': 'failed', 'reason': 'Private video storage provisioning failed closed. Verify the pinned environment, server credential and existing bucket policy.'}))
        return 1
    print(json.dumps({'videoStorage': result}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

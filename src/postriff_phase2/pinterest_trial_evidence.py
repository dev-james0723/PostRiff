"""Redacted Sandbox probe transport around the existing Hosted Pinterest adapter.

This records requests, not acceptance. A 2xx receipt alone is not identity, OAuth,
Board-selection, refresh, or Standard verification. Resource mutations are denied.
"""
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from postriff_alpha.domain import AlphaError


class SandboxReadOnlyEvidenceTransport:
    HOST = 'api-sandbox.pinterest.com'
    SCOPES = frozenset({'user_accounts:read', 'boards:read', 'pins:read', 'pins:write'})

    def __init__(self, record, *, mock_transport=None):
        from .providers import http_transport
        self.transport = mock_transport if mock_transport is not None else http_transport
        self.mode = 'mock' if mock_transport is not None else 'real_trial_request'
        self.record = record

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        safe_read = (method == 'GET' and parts.path in ('/v5/user_account', '/v5/boards')
                     and set(query).issubset({'page_size', 'bookmark'}) and form is None and body is None and data is None)
        token_request = (method == 'POST' and parts.path == '/v5/oauth/token' and not query
                         and isinstance(form, dict) and form.get('grant_type') in ('authorization_code', 'refresh_token')
                         and body is None and data is None)
        if (parts.scheme != 'https' or parts.hostname != self.HOST or parts.port not in (None, 443)
                or parts.username or parts.password or parts.fragment or not (safe_read or token_request)):
            raise AlphaError('The Trial evidence probe permits only Sandbox identity, board reads and OAuth token operations.', 403)
        base = {'requestId': uuid.uuid4().hex, 'mode': self.mode, 'method': method,
                'origin': 'https://' + self.HOST, 'path': parts.path, 'queryKeys': sorted(query),
                'grantType': form.get('grant_type') if token_request else None}
        # If the journal cannot record intent, do not issue the request.
        self.record({**base, 'phase': 'started', 'at': datetime.now(timezone.utc).isoformat()})
        try:
            response = self.transport(method, url, headers=headers, form=form, body=body, data=data)
        except Exception:
            self.record({**base, 'phase': 'network_failure', 'at': datetime.now(timezone.utc).isoformat(), 'status': None})
            raise
        payload = response.get('body') if isinstance(response.get('body'), dict) else {}
        summary = {}
        if parts.path == '/v5/oauth/token':
            scopes = set(re.split(r'[\s,]+', payload.get('scope', '').strip())) if isinstance(payload.get('scope'), str) else set()
            summary = {'accessTokenPresent': bool(payload.get('access_token')), 'refreshTokenPresent': bool(payload.get('refresh_token')),
                       'recognizedScopes': sorted(scopes & self.SCOPES), 'unexpectedScopesPresent': bool(scopes - self.SCOPES - {''})}
        elif parts.path == '/v5/boards':
            items = payload.get('items')
            summary = {'itemsShapeValid': isinstance(items, list), 'itemCount': len(items) if isinstance(items, list) else None,
                       'bookmarkPresent': bool(payload.get('bookmark'))}
        else:
            summary = {'usernamePresent': bool(payload.get('username')), 'accountIdPresent': bool(payload.get('id'))}
        status = response.get('status')
        self.record({**base, 'phase': 'response', 'at': datetime.now(timezone.utc).isoformat(),
                     'status': status if isinstance(status, int) else None, 'summary': summary})
        return response

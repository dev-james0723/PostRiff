"""Google web-server OAuth with incremental, feature-specific authorization."""
import json
import re
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from ..provider_base import OAuthProvider
from .model import READ, UPLOAD as UPLOAD_PERMISSION, MANAGE, ANALYTICS, MONEY, MEMBERS, project_public_gate


class YouTubeProvider(OAuthProvider):
    id, platform, capability_version = 'youtube', 'YouTube', 2
    AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
    TOKEN = 'https://oauth2.googleapis.com/token'
    REVOKE = 'https://oauth2.googleapis.com/revoke'
    TOKENINFO = 'https://oauth2.googleapis.com/tokeninfo'
    API = 'https://www.googleapis.com/youtube/v3'
    UPLOAD = 'https://www.googleapis.com/upload/youtube/v3/videos'
    UPLOAD_SCOPE, READ_SCOPE = UPLOAD_PERMISSION, READ
    SCOPES = {'identity': [READ], 'posts_read': [READ], 'publish': [READ, UPLOAD_PERMISSION], 'schedule': [READ, MANAGE],
              'manage_video': [READ, MANAGE], 'captions': [READ, MANAGE], 'playlists': [READ, MANAGE],
              'comments_read': [READ, MANAGE], 'reply': [READ, MANAGE], 'moderate': [READ, MANAGE],
              'analytics': [READ, ANALYTICS], 'live': [READ, MANAGE], 'reporting': [READ, ANALYTICS],
              'monetary_analytics': [READ, MONEY], 'memberships': [READ, MEMBERS]}
    EXPLAIN = {'identity': 'Read the identity and status of the YouTube channel you select. Publishing remains separately authorized.',
               'publish': 'Upload videos only after you approve the exact video and declarations. Public access depends on separate Google and YouTube approval.',
               'schedule': 'Manage your videos and YouTube’s native schedule after an exact video approval.',
               'manage_video': 'Edit your videos only after reviewing the exact change; deletion needs an explicit resource confirmation.',
               'captions': 'Manage caption tracks for your videos after reviewing each track.',
               'playlists': 'Manage playlists and podcast shows after reviewing each change.',
               'comments_read': 'Read available comments on your videos. Replies require separate permission and human approval.',
               'reply': 'Reply to comments only after you approve the exact text and thread.',
               'moderate': 'Moderate comments only where your channel has authority, with an audit record for each action.',
               'analytics': 'Read creator performance reports. Revenue and memberships remain off.',
               'reporting': 'Read bulk creator reports after you intentionally create a reporting job.',
               'live': 'Manage Live broadcasts, streams and chat after reviewing each action.',
               'monetary_analytics': 'Read sensitive creator revenue reports only after you intentionally enable revenue analytics.',
               'memberships': 'Read sensitive channel membership data only after you intentionally enable memberships and YouTube grants eligibility.'}
    account_requirement = 'A Google identity with a YouTube channel. Public-upload approval and creator eligibility are separate gates.'
    read_scope, publish_scope = READ, UPLOAD_PERMISSION
    publish_required = frozenset({UPLOAD_PERMISSION})
    refresh_margin = 300
    native_schedule = True
    shared_remote = True  # Google revocation covers the account/project; a Channel ID does not identify that grant.

    def __init__(self, client_id, client_secret, transport=None, production_reviewed=False, *, creator_enabled=False, project_evidence=None):
        super().__init__(client_id, client_secret, transport, production_reviewed)
        from ..provider_base import default_transport
        self.real_transport = self.transport is default_transport()
        self.creator_enabled = bool(creator_enabled)
        self.project_evidence = project_evidence or {}

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        proof = {}
        try:
            supplied = json.loads(values.get('POSTRIFF_YOUTUBE_PROJECT_EVIDENCE', '{}'))
            proof = supplied if isinstance(supplied, dict) else {}
        except (ValueError, TypeError):
            diagnostic['projectEvidenceInvalid'] = True
        adapter = cls(client_id, secret, transport, creator_enabled=values.get('POSTRIFF_YOUTUBE_CREATOR_ENABLED') == '1', project_evidence=proof) if valid else None
        diagnostic['creatorEnabled'] = bool(adapter and adapter.creator_enabled)
        diagnostic['publicUploadGateVerified'] = bool(adapter and project_public_gate(adapter))
        return adapter, diagnostic

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + '?' + urlencode({'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': redirect,
            'scope': ' '.join(scopes), 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
            'access_type': 'offline', 'prompt': 'consent select_account', 'include_granted_scopes': 'true'})

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = re.split(r'\s+', body['scope'].strip()) if isinstance(body.get('scope'), str) and body['scope'].strip() else []
        return {'accessToken': json.dumps({'v': 1, 'at': body['access_token'], 'scope': scopes}),
                'refreshToken': body.get('refresh_token') or refresh_token, 'expiresIn': body.get('expires_in'), 'scopes': scopes}

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport('POST', self.TOKEN, form={'code': code, 'client_id': self.client_id,
            'client_secret': self.client_secret, 'redirect_uri': redirect, 'grant_type': 'authorization_code', 'code_verifier': verifier}), 'access_token')
        return self._grant(body)

    def refresh(self, refresh_token):
        response = self.transport('POST', self.TOKEN, form={'client_id': self.client_id, 'client_secret': self.client_secret,
            'refresh_token': refresh_token, 'grant_type': 'refresh_token'})
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        if body.get('error') == 'invalid_grant':
            raise AlphaError('Google authorization was revoked or expired. Reconnect this channel.', 409, code='youtube_revoked_oauth')
        if body.get('error') == 'invalid_client':
            raise AlphaError('Google rejected this project’s OAuth client configuration. Review its credentials; the creator grant was not classified as revoked.', 503, code='youtube_project_restriction')
        return self._grant(self._ok(response, 'access_token'), refresh_token)

    @staticmethod
    def bearer(access_token):
        try:
            token = json.loads(access_token)
            if token.get('v') == 1 and isinstance(token.get('at'), str) and token['at']:
                return token['at']
        except (ValueError, TypeError):
            pass
        raise AlphaError('Reconnect this YouTube channel.', 409, code='youtube_revoked_oauth')

    def api(self, access_token, method, url, **kwargs):
        headers = {'Authorization': 'Bearer ' + self.bearer(access_token), **kwargs.pop('headers', {})}
        return self.transport(method, url, headers=headers, **kwargs)

    def discover_channels(self, access_token):
        response = self.api(access_token, 'GET', self.API + '/channels?' + urlencode({'part': 'snippet,statistics,contentDetails,status,brandingSettings', 'mine': 'true', 'maxResults': 50}))
        body = self._ok(response)
        return [item for item in body.get('items', []) if isinstance(item, dict) and re.fullmatch(r'UC[A-Za-z0-9_-]{22}', str(item.get('id', '')))]

    def identity(self, access_token):
        channels = self.discover_channels(access_token)
        if not channels:
            raise AlphaError('This Google identity has no YouTube channel. Create one, then reconnect.', 409)
        if len(channels) != 1:
            raise AlphaError('Google returned multiple channels. Reconnect using the exact channel identity you intend to authorize.', 409, code='youtube_channel_selection_required')
        item = channels[0]
        snippet = item.get('snippet') or {}
        thumbnail = ((snippet.get('thumbnails') or {}).get('default') or {}).get('url')
        return {'providerAccountId': item['id'], 'handle': str(snippet.get('customUrl') or snippet.get('title') or item['id']),
                'accountType': 'channel', 'pictureUrl': thumbnail if isinstance(thumbnail, str) else None, 'channelMetadata': item}

    def inspect_scopes(self, access_token, expected_account_id=None):
        response = self.transport('GET', self.TOKENINFO + '?' + urlencode({'access_token': self.bearer(access_token)}))
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        if response.get('status') in (400, 401) and (body.get('error') in ('invalid_token', 'invalid_grant') or response.get('status') == 401):
            raise AlphaError('Google authorization was revoked or expired. Reconnect this channel.', 409, code='youtube_revoked_oauth')
        if response.get('status') != 200 or body.get('aud') != self.client_id or not isinstance(body.get('scope'), str):
            return None
        return sorted(set(body['scope'].split()))

    def revoke(self, token):
        return self.transport('POST', self.REVOKE, form={'token': self.bearer(token)}).get('status') == 200

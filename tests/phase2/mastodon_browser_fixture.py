"""Cloud loopback application browser fixture; Mastodon/identity are synthetic."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts'), str(ROOT / 'tests')]
# Reuse the existing disposable PostgreSQL socket/privilege wrapper. Replace
# only its service factory; no Google fixture or provider is mounted here.
import youtube_browser_fixture as disposable
from postriff_phase2.social_connectors import MastodonProvider
from mastodon_after134_fixture import prepare as prepare_after134

SCOPES = list(MastodonProvider.SCOPES['management'])


class SyntheticMastodon:
    def __init__(self):
        self.deleted = set()

    def __call__(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.hostname not in ('mastodon.social', 'mastodon.online'):
            raise AssertionError('No network egress in this synthetic fixture.')
        path = parsed.path
        value, status = {}, 200
        if path == '/api/v2/instance':
            value = {'version': '4.6.1' if parsed.hostname == 'mastodon.social' else '4.2.9',
                     'configuration': {'urls': {'streaming': 'wss://' + parsed.hostname},
                         **({'accounts': {'max_display_name_length': 60, 'max_note_length': 600,
                             'max_profile_fields': 6, 'profile_field_name_limit': 64, 'profile_field_value_limit': 255,
                             'max_avatar_description_length': 120, 'max_header_description_length': 120}}
                            if parsed.hostname == 'mastodon.social' else {})}}
        elif path == '/.well-known/oauth-authorization-server':
            status = 404
        elif path == '/api/v1/apps':
            value = {'client_id': 'synthetic-client', 'client_secret': 'synthetic-secret'}
        elif path == '/oauth/token':
            value = {'access_token': 'synthetic-token', 'scope': ' '.join(SCOPES)}
        elif path == '/oauth/revoke':
            pass
        elif path == '/api/v1/apps/verify_credentials':
            value = {'scopes': SCOPES}
        elif path == '/api/v1/accounts/verify_credentials':
            value = {'id': '100', 'username': 'SYNTHETIC', 'acct': 'SYNTHETIC', 'followers_count': 12, 'following_count': 3, 'statuses_count': 2}
        elif path == '/api/v1/accounts/update_credentials' and method == 'PATCH':
            value = {'id': '100'}
        elif path == '/api/v1/accounts/100/statuses':
            value = [{'id': '123', 'account': {'id': '100'}, 'visibility': 'public', 'created_at': '2026-10-01T00:00:00Z',
                      'favourites_count': 2, 'reblogs_count': 1, 'replies_count': 0, 'content': '<p>SYNTHETIC public post</p>'},
                     {'id': '124', 'account': {'id': '100'}, 'visibility': 'direct', 'content': 'PRIVATE_FIXTURE_EXCLUDED_FROM_ANALYTICS'}]
        elif path == '/api/v1/statuses/123/favourite' and method == 'POST':
            value = {'id': '123', 'favourited': True}
        elif path == '/api/v1/statuses/123':
            if method == 'DELETE': self.deleted.add(path)
            elif path in self.deleted: status = 404
            else: value = {'id': '123', 'account': {'id': '100'}, 'visibility': 'public', 'content': '<p>SYNTHETIC public post</p>'}
        elif method == 'GET':
            value = []
        else:
            raise AssertionError('Unsupported synthetic request: ' + method + ' ' + path)
        return {'status': status, 'body': value, 'headers': {}}


def service(*args, **kwargs):
    # This is the existing dev harness's dedicated loopback cluster, not the
    # focused PG suite. Shared setup verifies actual server port/data directory.
    prepare_after134(args[0], 'host=127.0.0.1 port=55448 dbname=postgres', fixture_route='management-browser')
    provider = MastodonProvider('http://127.0.0.1:4448', transport=SyntheticMastodon(), production_reviewed=True,
                               resolver=lambda *_args, **_kwargs: [(2, 1, 6, '', ('93.184.216.34', 443))])
    provider.publish_live_tested = provider.publishing_permission = True  # Synthetic fixture only.
    from postriff_phase2.mastodon_streaming import parse_events
    def stream(origin, token):
        if origin not in ('https://mastodon.social', 'https://mastodon.online') or token != 'synthetic-token':
            raise AssertionError('Synthetic stream binding changed.')
        raw = b'event: notification\ndata: {"id":"22","type":"mention","status":{"id":"31","visibility":"direct","content":"<p>PRIVATE_EPHEMERAL_STREAM</p>"}}\n\n'
        return {'status': 200, 'events': parse_events(raw)}
    provider.streaming_transport = stream
    kwargs['providers']['mastodon'] = provider
    return disposable.original(*args, **kwargs)


disposable.harness.HostedWorkspaceService = service
if __name__ == '__main__':
    if sys.platform != 'linux' or os.environ.get('CI', '').lower() not in ('1', 'true'):
        raise SystemExit('Requires cloud Linux CI.')
    print(json.dumps({'execution': 'CLOUD SYNTHETIC MASTODON BROWSER AFTER134', 'realMastodonAcceptance': False,
                      'schema': 'locked separately approved management-after134 proposal; never production adoption'}), flush=True)
    disposable.harness.main()

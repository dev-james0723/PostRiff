"""Loopback-only Rafii browser fixture. Google transport/identity are synthetic, never real E2E.

Run with the existing disposable hosted harness arguments. No production credentials are read.
"""
import copy
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import postriff_dev_hosted as harness
from postriff_phase2.youtube.model import READ, UPLOAD, MANAGE, ANALYTICS
from postriff_phase2.youtube.provider import YouTubeProvider

CHANNEL, VIDEO = 'UC' + 'a' * 22, 'abcdefghijk'
ASSET = 'b' * 32
STANDARD_CLIENT = 'local-synthetic.apps.googleusercontent.com'
AGENTIC_CLIENT = 'local-agentic-synthetic.apps.googleusercontent.com'

class SyntheticGoogle:
    scopes = [READ, UPLOAD, MANAGE, ANALYTICS]
    def __init__(self, client_id=STANDARD_CLIENT):
        self.client_id = client_id
        self.playlists, self.writes = {}, 0
        self.video = {'id': VIDEO, 'snippet': {'channelId': CHANNEL, 'title': 'Local synthetic video',
                      'description': 'Keep this exact description.', 'categoryId': '22', 'tags': ['preserve']},
                      'status': {'privacyStatus': 'private', 'uploadStatus': 'processed', 'selfDeclaredMadeForKids': False,
                                 'containsSyntheticMedia': False}, 'processingDetails': {'processingStatus': 'succeeded'}}
    def __call__(self, method, url, **kwargs):
        parsed, query = urlsplit(url), parse_qs(urlsplit(url).query)
        if parsed.hostname not in ('oauth2.googleapis.com', 'www.googleapis.com', 'youtubeanalytics.googleapis.com', 'youtubereporting.googleapis.com'):
            raise AssertionError('Fixture does not support network egress.')
        path = parsed.path
        result = {}
        if path == '/token':
            result = {'access_token': 'local-synthetic-token', 'refresh_token': 'local-synthetic-refresh', 'expires_in': 3600, 'scope': ' '.join(self.scopes)}
        elif path == '/tokeninfo': result = {'aud': self.client_id, 'scope': ' '.join(self.scopes)}
        elif path == '/revoke': pass
        elif path.endswith('/channels'):
            result = {'items': [{'id': CHANNEL, 'snippet': {'title': 'LOCAL SYNTHETIC CREATOR', 'description': 'Browser verification only; no Google channel is connected.'},
                                'statistics': {'viewCount': '120', 'subscriberCount': '12', 'videoCount': '1'},
                                'status': {'longUploadsStatus': 'allowed'}, 'contentDetails': {'relatedPlaylists': {'uploads': 'UU' + 'a' * 22}}}]}
        elif path.endswith('/videos'):
            if method == 'PUT':
                for key, value in kwargs['body'].items():
                    if key != 'id': self.video[key] = copy.deepcopy(value)
                self.video['snippet']['channelId'] = CHANNEL
                self.video['status']['uploadStatus'] = 'processed'
                self.writes += 1
                result = copy.deepcopy(self.video)
            else: result = {'items': [copy.deepcopy(self.video)] if query.get('id') == [VIDEO] else []}
        elif path.endswith('/playlistItems'):
            result = {'items': [{'id': 'local-upload', 'snippet': {'title': self.video['snippet']['title'], 'resourceId': {'videoId': VIDEO}}, 'contentDetails': {'videoId': VIDEO}}]}
        elif path.endswith('/playlists'):
            if method == 'POST':
                self.writes += 1
                item = {'id': 'PLlocal-' + str(self.writes), **copy.deepcopy(kwargs['body'])}
                item['snippet']['channelId'] = CHANNEL
                self.playlists[item['id']] = item
                result = item
            elif method == 'DELETE':
                self.writes += 1; self.playlists.pop(query['id'][0], None)
            else:
                result = {'items': [copy.deepcopy(self.playlists[query['id'][0]])] if query.get('id') and query['id'][0] in self.playlists else list(self.playlists.values()) if query.get('mine') else []}
        elif path.endswith('/commentThreads'): result = {'items': []}
        elif path.endswith('/liveBroadcasts'): result = {'items': []}
        elif path.endswith('/liveStreams'):
            result = {'items': [{'id': 'local-stream', 'snippet': {'channelId': CHANNEL, 'title': 'Local stream'}, 'cdn': {'ingestionType': 'rtmp', 'resolution': '1080p', 'frameRate': '30fps', 'ingestionInfo': {'streamName': 'synthetic-private-stream-key', 'ingestionAddress': 'rtmp://local.invalid/live'}}, 'status': {'streamStatus': 'inactive'}}]}
        elif parsed.hostname == 'youtubeanalytics.googleapis.com' and path == '/v2/reports':
            columns = query.get('dimensions', ['day'])[0].split(',') + query['metrics'][0].split(',')
            result = {'columnHeaders': [{'name': name} for name in columns], 'rows': [['2026-10-01'] + [1] * (len(columns) - 1)]}
        elif path == '/v1/reportTypes': result = {'reportTypes': [{'id': 'channel_basic_a4', 'name': 'Local non-monetary type'}]}
        elif path == '/v1/jobs': result = {'jobs': []}
        else: raise AssertionError('Unsupported fixture request: ' + method + ' ' + path)
        return {'status': 204 if method == 'DELETE' else 200, 'body': result, 'headers': {}}

original = harness.HostedWorkspaceService
def local_service(*args, **kwargs):
    with args[0]() as db:
        db.execute((ROOT / 'migrations/postriff/089_youtube_creator.sql').read_text())
        db.execute((ROOT / 'migrations/postriff/097_youtube_capacity.sql').read_text())
    provider = YouTubeProvider(STANDARD_CLIENT, 'local-synthetic-secret', transport=SyntheticGoogle(), creator_enabled=True)
    provider.agentic_provider = YouTubeProvider(AGENTIC_CLIENT, 'local-agentic-synthetic-secret',
        transport=SyntheticGoogle(AGENTIC_CLIENT), creator_enabled=True, authorization_lane='agentic')
    provider.execution_enabled = provider.agentic_provider.execution_enabled = True
    kwargs['providers']['youtube'] = provider
    service = original(*args, **kwargs)
    upsert = service.commands.upsert_verified_channel
    def with_library_fixture(state, *arguments, **options):
        result = upsert(state, *arguments, **options)
        if not any(asset.get('id') == ASSET for asset in state['phase2']['assets']):
            state['phase2']['assets'].append({'id': ASSET, 'hash': 'f' * 64, 'mime': 'video/mp4', 'processing': 'ready',
                'originalFilename': 'SYNTHETIC_browser_plan.mp4', 'displayTitle': 'SYNTHETIC browser plan',
                'width': 1080, 'height': 1920, 'bytes': 1000, 'duration': 60, 'durationSource': 'container',
                'bucket': 'postriff-video', 'objectName': ASSET + '.mp4', 'etag': 'synthetic-immutable',
                'verified': {'container': True, 'locationChecked': True}, 'deleted': False})
        return result
    service.commands.upsert_verified_channel = with_library_fixture
    return service
harness.HostedWorkspaceService = local_service

# Only PostgreSQL subprocesses drop OS privileges when the ephemeral CI runner
# itself is root. Python/Next remain the runner user; no project files are chowned.
_run = subprocess.run
def fixture_run(command, *arguments, **options):
    command = list(command)
    if Path(command[0]).name == 'pg_ctl' and command[-1] == 'start':
        # Minimal CI images may not provide /var/run/postgresql. Keep the socket
        # beside this fixture's mode-0700 disposable data, never in a global path.
        socket_directory = Path(command[command.index('-D') + 1]).parent
        command[command.index('-o') + 1] += f' -k {socket_directory}'
    if Path(command[0]).name == 'initdb':
        command.extend(['-U', 'postriff_test'])
    if os.geteuid() == 0 and Path(command[0]).name in ('initdb', 'pg_ctl'):
        owner = pwd.getpwnam('postgres')
        if owner.pw_uid == 0:
            raise RuntimeError('Disposable PostgreSQL requires an unprivileged OS account.')
        directory = Path(command[command.index('-D') + 1]).parent
        if Path(command[0]).name == 'initdb':
            os.chown(directory, owner.pw_uid, owner.pw_gid)
        options.update(user=owner.pw_uid, group=owner.pw_gid, extra_groups=[], cwd=directory)
    return _run(command, *arguments, **options)
harness.subprocess = type('FixtureProcess', (), {'run': staticmethod(fixture_run), 'DEVNULL': subprocess.DEVNULL,
    'CalledProcessError': subprocess.CalledProcessError, 'TimeoutExpired': subprocess.TimeoutExpired})
if __name__ == '__main__':
    if sys.platform != 'linux' or os.environ.get('CI', '').lower() not in ('1', 'true'):
        raise SystemExit('Browser database fixture requires cloud Linux CI; no Mac execution.')
    print(json.dumps({'execution': 'CLOUD SYNTHETIC BROWSER FIXTURE', 'realGoogleE2E': False, 'credentials': 'generated test strings only'}), flush=True)
    harness.main()

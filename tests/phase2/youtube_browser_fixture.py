"""Loopback-only Rafii browser fixture. Google transport/identity are synthetic, never real E2E.

Run with the existing disposable hosted harness arguments. No production credentials are read.
"""
import copy
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import postriff_dev_hosted as harness
from postriff_phase2.youtube.model import READ, UPLOAD, MANAGE, ANALYTICS
from postriff_phase2.youtube.provider import YouTubeProvider

CHANNEL, VIDEO = 'UC' + 'a' * 22, 'abcdefghijk'

class SyntheticGoogle:
    scopes = [READ, UPLOAD, MANAGE, ANALYTICS]
    def __init__(self):
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
        elif path == '/tokeninfo': result = {'aud': 'local-synthetic.apps.googleusercontent.com', 'scope': ' '.join(self.scopes)}
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
    kwargs['providers']['youtube'] = YouTubeProvider('local-synthetic.apps.googleusercontent.com', 'local-synthetic-secret', transport=SyntheticGoogle(), creator_enabled=True)
    return original(*args, **kwargs)
harness.HostedWorkspaceService = local_service
if __name__ == '__main__':
    print(json.dumps({'execution': 'LOCAL SYNTHETIC BROWSER FIXTURE', 'realGoogleE2E': False, 'credentials': 'generated test strings only'}), flush=True)
    harness.main()

"""Cloud loopback Queue journey; synthetic provider and explicitly advanced clock."""
import html
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import mastodon_browser_fixture as base

harness = base.disposable.harness
offset = 0
worker = None


def now(): return time.time() + offset


class QueueAPI(base.SyntheticMastodon):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.posts, self.schedules, self.media, self.keys = {}, {}, {}, {}
        self.sequence, self.writes = 2000, 0

    def identifier(self):
        self.sequence += 1
        return str(self.sequence)

    def publish(self, host, body):
        identifier = self.identifier()
        value = {'id': identifier, 'account': {'id': '100'}, 'content': '<p>' + html.escape(body['status']).replace('\n', '<br />') + '</p>',
                 'visibility': body.get('visibility', 'public'), 'spoiler_text': body.get('spoiler_text', ''),
                 'sensitive': body.get('sensitive', False), 'language': body.get('language'),
                 'in_reply_to_id': body.get('in_reply_to_id'), 'media_attachments': [self.media[i] for i in body.get('media_ids', [])],
                 'created_at': datetime.fromtimestamp(now(), timezone.utc).isoformat(),
                 'url': f'https://{host}/@SYNTHETIC/{identifier}', 'favourites_count': 0, 'reblogs_count': 0, 'replies_count': 0}
        self.posts[(host, identifier)] = value
        return value

    def __call__(self, method, url, **kwargs):
        parsed = urlsplit(url); host, path = parsed.hostname, parsed.path
        assert host in ('mastodon.social', 'mastodon.online'), 'No network egress permitted.'
        with self.lock:
            for key, schedule in list(self.schedules.items()):
                if datetime.fromisoformat(schedule['scheduled_at'].replace('Z', '+00:00')).timestamp() <= now():
                    self.publish(key[0], schedule['_body']); del self.schedules[key]
            body = kwargs.get('body') or {}
            value, status = None, 200
            if path in ('/api/v2/media', '/api/v1/media') and method == 'POST':
                identifier = self.identifier(); self.writes += 1
                raw = kwargs.get('data', b'')
                kind = 'audio' if b'audio/wav' in raw else 'image'
                value = {'id': identifier, 'type': kind, 'url': f'https://{host}/media/{identifier}',
                         'preview_url': f'https://{host}/media/{identifier}.png'}
                self.media[identifier] = value
            elif path.startswith('/api/v1/media/') and method == 'GET':
                value = self.media.get(path.rsplit('/', 1)[1]); status = 200 if value else 404
            elif path == '/api/v1/statuses' and method == 'POST':
                key = (host, (kwargs.get('headers') or {}).get('Idempotency-Key'))
                assert key[1], 'Real publisher must supply its durable idempotency key.'
                if key in self.keys: return self.keys[key]
                self.writes += 1
                if body.get('scheduled_at'):
                    identifier = self.identifier()
                    value = {'id': identifier, 'scheduled_at': body['scheduled_at'],
                             'params': {**body, 'text': body['status']}, 'media_attachments': [self.media[i] for i in body.get('media_ids', [])]}
                    self.schedules[(host, identifier)] = {**value, '_body': body}
                else:
                    value = self.publish(host, body)
                self.keys[key] = {'status': 200, 'body': value, 'headers': {}}
            elif path.startswith('/api/v1/scheduled_statuses/'):
                key = (host, path.rsplit('/', 1)[1]); value = self.schedules.get(key)
                if method == 'DELETE':
                    self.schedules.pop(key, None); value = {}; self.writes += 1
                elif method == 'PUT' and value:
                    value['scheduled_at'] = body['scheduled_at']; value['_body']['scheduled_at'] = body['scheduled_at']; self.writes += 1
                elif not value: value, status = {}, 404
                if isinstance(value, dict): value = {k: v for k, v in value.items() if k != '_body'}
            elif path.startswith('/api/v1/statuses/') and (host, path.rsplit('/', 1)[1]) in self.posts:
                value = self.posts[(host, path.rsplit('/', 1)[1])]
            elif path == '/api/v1/accounts/100/statuses':
                value = [p for (instance, _identifier), p in reversed(list(self.posts.items())) if instance == host][:40]
            if value is not None: return {'status': status, 'body': value, 'headers': {}}
            return super().__call__(method, url, **kwargs)


transport = QueueAPI()
original_service = base.service


def service(*args, **kwargs):
    kwargs['clock'] = now
    created = original_service(*args, **kwargs)
    created.publishing_live = True
    created.oauth.providers['mastodon'].transport = transport
    upsert = created.commands.upsert_verified_channel
    def seed(state, *arguments, **options):
        result = upsert(state, *arguments, **options)
        if not any(v['id'] == 'synthetic-mastodon-queue' for v in state['variants']):
            state['variants'].append({'id': 'synthetic-mastodon-queue', 'platform': 'Mastodon', 'language': 'en',
                'text': 'SYNTHETIC Queue root', 'revision': 1, 'voiceRevision': state['speaker']['activeRevision'],
                'briefRevision': state['brief']['revision'], 'styleRevision': 1, 'speakerId': state['speaker']['id'],
                'sourceIds': [], 'warnings': [], 'unknowns': [], 'needsReview': False, 'blockedByRetraction': False,
                'customized': True, 'selectedOpening': 0, 'openings': ['SYNTHETIC Queue root'] * 3,
                'runId': 'synthetic-no-model-call', 'revisions': [], 'localPreferences': {}})
        return result
    created.commands.upsert_verified_channel = seed
    return created


original_worker = harness.PostgresWorker
class ClockWorker(original_worker):
    def __init__(self, *args, **kwargs):
        global worker
        kwargs['clock'] = now
        super().__init__(*args, **kwargs)
        worker = self


original_make_server = harness.make_server
def make_server(host, port, application, *args, **kwargs):
    assert host == '127.0.0.1'
    def controlled(environ, start_response):
        global offset
        if environ.get('PATH_INFO') == '/dev/mastodon/tick' and environ['REQUEST_METHOD'] == 'POST':
            payload = json.loads(environ['wsgi.input'].read(int(environ.get('CONTENT_LENGTH') or 0)) or b'{}')
            seconds = payload.get('seconds', 0)
            assert type(seconds) in (int, float) and 0 <= seconds <= 600
            if payload.get('resetClock') is True:
                assert seconds == 0
                offset = 0  # Separate responsive journeys begin at real OAuth/SQL time.
            offset += seconds
            result = worker.tick(max_jobs=5, max_seconds=5) if seconds else {'processed': 0}
            raw = json.dumps({'now': now(), 'writes': transport.writes, 'worker': result,
                              'execution': 'SYNTHETIC provider and advanced fixture clock; actual shared worker/SQL'}).encode()
            start_response('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(raw)))]); return [raw]
        return application(environ, start_response)
    return original_make_server(host, port, controlled, *args, **kwargs)


harness.HostedWorkspaceService = service
harness.PostgresWorker = ClockWorker
harness.make_server = make_server
harness.DevVerifier.auth_time = staticmethod(lambda *_args: now())
if __name__ == '__main__':
    if sys.platform != 'linux' or os.environ.get('CI', '').lower() not in ('1', 'true'):
        raise SystemExit('Requires cloud Linux CI.')
    harness.main()

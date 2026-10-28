#!/usr/bin/env python3
"""Mock Discord for the W-02 capacity harness (scripts/discord_lane_capacity_run.py).

A synthetic Discord REST API on 127.0.0.1 that implements exactly the routes Rafii's sender and its connect flow use
(found in social_connectors.py, discord/oauth.py and hosted_social.py):

  GET  /oauth2/@me                       the linked person's bearer (installation identity proof, every post)
  GET  /users/@me                        bot identity (and the person's profile, connect flow only)
  GET  /oauth2/applications/@me          bot identity
  GET  /users/@me/guilds                 the person's servers (connect flow only)
  GET  /guilds/{g}                       permission preflight
  GET  /guilds/{g}/members/{id}          bot and person membership
  GET  /guilds/{g}/channels              channel permissions
  POST /channels/{c}/messages            the create (nonce, enforce_nonce)
  GET  /channels/{c}/messages/{m}        the read-back

The world is deterministic: workspace index i owns Discord user USER0+i, guild GUILD0+i and channel CHANNEL0+i, and
the person's bearer is 'cap-user-bearer-<i>'. Nothing is real; no network is reached.

Limits, all counted at the mock's own clock (time.time() when the request is processed, after half its latency):
  - a hard global ceiling of 50 bot-token requests in any trailing second: above it the answer is 429 with
    Retry-After, X-RateLimit-Global: true and X-RateLimit-Scope: global, and the request is counted as a violation;
  - every request is also counted against 25 in any trailing second (the reviewed policy ceiling) and against 50 for
    all credentials together; those are counted, never refused;
  - per-channel create buckets of 5 per 5 seconds, per-route read buckets (default 50 per second), with Discord's
    x-ratelimit-* headers so the shared coordinator learns them;
  - every create is recorded with its nonce and the post id carried in its synthetic text, so duplicate creates are
    counted twice over.

The full request log (arrival, processing and answer time, route class, status, credential kind, nonce, post id) is
written as JSON lines at shutdown and the running counters every few seconds, so a run can be analysed afterwards
from the mock's own record only.
"""
import argparse
import hashlib
import json
import os
import random
import re
import signal
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

API_PREFIX = '/api/v10'
APP = '1390000000000000001'
BOT = '1390000000000000002'
BOT_TOKEN = 'cap-bot-token-synthetic-0000000000000000'
OWNER = '1390000000000000003'
USER0, GUILD0, CHANNEL0 = 1391000000000000000, 1392000000000000000, 1393000000000000000
MESSAGE0 = 1394000000000000000
# View Channel, Send Messages, Attach Files, Read Message History, Manage Server (social_connectors.DiscordProvider).
PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 15) | (1 << 16) | (1 << 5)
POST_MARK = re.compile(r'\[cap-post ([A-Za-z0-9_.:-]{1,80})\]')
_SNOWFLAKE = re.compile(r'^[0-9]{5,25}$')


def user_id(index):
    return str(USER0 + index)


def guild_id(index):
    return str(GUILD0 + index)


def channel_id(index):
    return str(CHANNEL0 + index)


def bearer(index):
    return 'cap-user-bearer-%d' % index


def refresh_token(index):
    return 'cap-user-refresh-%d' % index


def index_of(value, base):
    try:
        number = int(value) - base
    except (TypeError, ValueError):
        return None
    return number if 0 <= number < 10 ** 9 else None


class Latency:
    """Per-request latency in seconds: uniform:LOW:HIGH (ms), fixed:MS, with an optional tail."""
    def __init__(self, spec='uniform:50:150', tail_probability=0.0, tail_ms=0.0, seed=None):
        parts = spec.split(':')
        if parts[0] == 'fixed' and len(parts) == 2:
            self.low = self.high = float(parts[1]) / 1000
        elif parts[0] == 'uniform' and len(parts) == 3:
            self.low, self.high = float(parts[1]) / 1000, float(parts[2]) / 1000
        else:
            raise ValueError('latency spec must be uniform:LOW_MS:HIGH_MS or fixed:MS')
        if not 0 <= self.low <= self.high <= 30:
            raise ValueError('latency out of range')
        self.spec, self.tail_probability, self.tail = spec, float(tail_probability), float(tail_ms) / 1000
        self.random = random.Random(seed)
        self.lock = threading.Lock()

    def draw(self):
        with self.lock:
            value = self.random.uniform(self.low, self.high)
            if self.tail_probability and self.random.random() < self.tail_probability:
                value += self.tail
        return value

    def describe(self):
        return {'spec': self.spec, 'tailProbability': self.tail_probability, 'tailMs': self.tail * 1000}


class World:
    """Discord's answers for the synthetic world. Thread-safe; used by the HTTP server and in-process by the seeder."""
    CREATE_LIMIT = (5, 5.0)

    def __init__(self, *, workspaces=10 ** 6, read_limit=(50, 1.0), global_ceiling=50, policy_ceiling=25,
                 double_accept_every=0, injections=None, clock=time.time, bearer_ceiling=10):
        self.workspaces = workspaces
        self.injections = [dict(rule, used=0) for rule in (injections or [])]
        self.read_limit = read_limit
        self.global_ceiling, self.policy_ceiling = global_ceiling, policy_ceiling
        # With a bearer budget (the limiter's, from 0cb19962) the person's own bearer calls (kind `user`) have a ceiling of their own
        # and the application's `policy_ceiling` counts every other credential: the mock keeps both classes' trailing seconds
        # beside the all-credential one (which stays what the standard's own line counts).
        self.bearer_ceiling = bearer_ceiling
        self.double_accept_every = double_accept_every
        self.clock = clock
        self.lock = threading.Lock()
        self.windows = {}
        self.messages = {}
        self.nonces = {}
        self.sequence = MESSAGE0
        self.trail_all, self.trail_bot = deque(), deque()
        self.trail_app, self.trail_user = deque(), deque()  # the application's class (every credential but the bearer) and the bearer's
        self.log = []
        self.counters = dict.fromkeys(('requests', 'botRequests', 'userRequests', 'creates', 'createAttempts',
                                       'duplicateNonceCreates', 'duplicatePostCreates', 'doubleAccepted',
                                       'readbacks', 'global429', 'route429', 'aboveGlobalBot', 'abovePolicyAll',
                                       'aboveGlobalAll', 'abovePolicyApp', 'aboveBearer', 'unauthorized', 'unknownRoute',
                                       'notFound', 'injected', 'misrouted'), 0)
        self.peak_all = self.peak_bot = self.peak_app = self.peak_user = 0
        self.posts_created = {}

    # -- credentials ----------------------------------------------------------------------------------------------

    @staticmethod
    def credential(headers):
        value = headers.get('authorization') or ''
        if value == 'Bot ' + BOT_TOKEN:
            return 'bot', None
        if value.startswith('Bearer cap-user-bearer-'):
            index = index_of(value.rsplit('-', 1)[1], 0)
            return ('user', index) if index is not None else (None, None)
        if value.startswith('Basic '):
            return 'oauth', None
        return None, None

    # -- buckets --------------------------------------------------------------------------------------------------

    def _bucket(self, name, major, limit, window, now):
        start, used = self.windows.get((name, major), (now, 0))
        if now >= start + window:
            start, used = now, 0
        reset_after = max(.001, start + window - now)
        common = {'x-ratelimit-bucket': name, 'x-ratelimit-limit': str(limit),
                  'x-ratelimit-reset-after': '%.3f' % reset_after}
        if used >= limit:
            return False, {**common, 'x-ratelimit-remaining': '0', 'x-ratelimit-scope': 'user',
                           'retry-after': '%.3f' % reset_after}
        self.windows[(name, major)] = (start, used + 1)
        return True, {**common, 'x-ratelimit-remaining': str(limit - used - 1)}

    def _trail(self, trail, now):
        while trail and trail[0] <= now - 1.0:
            trail.popleft()
        trail.append(now)
        return len(trail)

    # -- the API --------------------------------------------------------------------------------------------------

    def handle(self, method, path, headers, body, *, arrived=None, wire_path=None):
        """(status, headers, body, record) for one request processed now. `wire_path` is the request target as sent,
        query string included (the coordinator digests that string); `path` is the routed part."""
        now = self.clock()
        kind, person = self.credential(headers)
        template = route_class(method, path)
        record = {'arrived': arrived if arrived is not None else now, 'processed': now, 'method': method,
                  'route': template, 'credential': kind or 'none',
                  # The coordinator's own path digest (sha256 of the same path), shortened: joins each admission to
                  # its arrival here (admission-to-wire jitter).
                  'pathKey': hashlib.sha256((path if wire_path is None else wire_path).encode('utf-8')).hexdigest()[:16]}
        # The harness's invocation wrapper tags each request it forwards: which cron route made it (so traffic that is
        # not the lane's is visible at the mock) and the wall-clock time just before the HTTP call was made (so the
        # delay inside the application is told apart from the delay between the call and this arrival).
        source = headers.get('x-cap-source')
        if source:
            record['src'] = str(source)[:16]
        if headers.get('x-cap-permit'):
            record['permit'] = str(headers['x-cap-permit'])[:36]  # the coordinator's admission id: an exact join
        try:
            record['callAt'] = round(float(headers['x-cap-call-at']), 6)
        except (KeyError, TypeError, ValueError):
            pass
        if kind == 'user' and person is not None:
            record['tenant'] = person  # the workspace whose person's bearer this is (request ledger)
        # Which tenant a server or channel route serves, before any injection decides the answer (an injected ban page
        # on a server route must still name its server).
        parts = path.strip('/').split('/')
        if len(parts) >= 2 and parts[0] == 'guilds':
            index = index_of(parts[1], GUILD0)
            if index is not None:
                record['guild'] = index
        elif len(parts) >= 2 and parts[0] == 'channels':
            index = index_of(parts[1], CHANNEL0)
            if index is not None:
                record['tenant'] = index
        with self.lock:
            self.counters['requests'] += 1
            count_all = self._trail(self.trail_all, now)
            self.peak_all = max(self.peak_all, count_all)
            record['trailingAll'] = count_all
            if count_all > self.policy_ceiling:
                self.counters['abovePolicyAll'] += 1
            if count_all > self.global_ceiling:
                self.counters['aboveGlobalAll'] += 1
            if kind == 'user':
                count_user = self._trail(self.trail_user, now)
                self.peak_user = max(self.peak_user, count_user)
                record['trailingUser'] = count_user
                if count_user > self.bearer_ceiling:
                    self.counters['aboveBearer'] += 1
            else:
                count_app = self._trail(self.trail_app, now)
                self.peak_app = max(self.peak_app, count_app)
                record['trailingApp'] = count_app
                if count_app > self.policy_ceiling:
                    self.counters['abovePolicyApp'] += 1
            if kind == 'bot':
                self.counters['botRequests'] += 1
                count_bot = self._trail(self.trail_bot, now)
                self.peak_bot = max(self.peak_bot, count_bot)
                record['trailingBot'] = count_bot
                if count_bot > self.global_ceiling:
                    # Discord's documented global limit for a bot: refuse, and say it is global.
                    self.counters['aboveGlobalBot'] += 1
                    self.counters['global429'] += 1
                    retry = max(.001, self.trail_bot[0] + 1.0 - now)
                    record.update(status=429, global429=True)
                    self.log.append(record)
                    return 429, {'retry-after': '%.3f' % retry, 'x-ratelimit-global': 'true',
                                 'x-ratelimit-scope': 'global'}, {
                        'message': 'You are being rate limited.', 'retry_after': round(retry, 3), 'global': True}, record
            elif kind == 'user':
                self.counters['userRequests'] += 1
            injected = self._inject(method, path, kind, body, now, record)
            if injected is not None:
                status, answer_headers, answer = injected
                record['status'] = status
                self.counters['injected'] += 1
                self.log.append(record)
                return status, answer_headers, answer, record
            status, answer_headers, answer = self._answer(method, path, kind, person, body, now, record)
            record['status'] = status
            if status == 429:
                self.counters['route429'] += 1
            elif status == 401:
                self.counters['unauthorized'] += 1
            elif status == 404:
                self.counters['notFound'] += 1
            self.log.append(record)
            return status, answer_headers, answer, record

    def _rule(self, kinds, route, now):
        for rule in self.injections:
            if (rule['kind'] in kinds and rule.get('route', route) == route and now >= rule.get('after', 0)
                    and (rule['kind'] != 'global429' or rule['at'] <= now < rule['at'] + rule.get('seconds', 1.0))
                    and (rule['kind'] == 'global429' or rule['used'] < rule.get('count', 0))):
                return rule
        return None

    def _inject(self, method, path, kind, body, now, record):
        """Failure injection (scenario rules). Returns (status, headers, body) or None for the normal answer.

        Creates that are injected are fully described in the record (nonce, post, landed) so the analysis can follow
        each affected post."""
        if not self.injections:
            return None
        route = route_class(method, path)
        is_create = method == 'POST' and route == 'POST /channels/{id}/messages'
        if is_create:
            # Every injected create names its post, so the analysis can follow it.
            content = (body or {}).get('content') if isinstance(body, dict) else None
            mark = POST_MARK.search(content or '')
            record.update(nonce=(body or {}).get('nonce') if isinstance(body, dict) else None,
                          post=mark.group(1) if mark else None)
        rule = self._rule(('global429',), route, now) if kind == 'bot' else None
        if rule is not None:
            record.update(injected='global429', global429=True)
            retry = float(rule.get('retryAfter', 5))
            return 429, {'retry-after': '%.3f' % retry, 'x-ratelimit-global': 'true', 'x-ratelimit-scope': 'global'}, {
                'message': 'You are being rate limited.', 'retry_after': retry, 'global': True}
        rule = self._rule(('route429', 'html429', 'create500', 'createTimeout', 'holdCreate'), route, now)
        if rule is None:
            return None
        if rule['kind'] in ('create500', 'createTimeout', 'holdCreate') and not is_create:
            return None
        rule['used'] += 1
        record['injected'] = rule['kind']
        if rule['kind'] == 'route429':
            retry = float(rule.get('retryAfter', 3))
            return 429, {'x-ratelimit-bucket': injected_bucket_id(route),
                         'x-ratelimit-limit': '5', 'x-ratelimit-remaining': '0',
                         'x-ratelimit-reset-after': '%.3f' % retry, 'x-ratelimit-scope': 'user',
                         'retry-after': '%.3f' % retry}, {'message': 'You are being rate limited.',
                                                          'retry_after': retry, 'global': False}
        if rule['kind'] == 'html429':
            return 429, {'content-type': 'text/html; charset=UTF-8', 'server': 'cloudflare'}, {
                '_html': '<!DOCTYPE html><title>Access denied | discord.com used Cloudflare to restrict access</title> Error 1015'}
        landed = bool(rule.get('landed'))
        record['landed'] = landed
        if landed:
            channel = path.strip('/').split('/')[1]
            status, headers, answer = self._create(channel, body, now, record)
            if status != 200:
                return status, headers, answer
        if rule['kind'] == 'create500':
            return 500, {}, {'message': '500: Internal Server Error', 'code': 0}
        # createTimeout / holdCreate: the answer is delayed by the HTTP layer (record['delayAnswer']).
        record['delayAnswer'] = float(rule.get('delay', rule.get('hold', 25)))
        record['announceKill'] = rule['kind'] == 'holdCreate'
        return 500 if not landed else 200, {}, ({'message': 'late answer'} if not landed else
                                                 {k: v for k, v in self.messages.get((path.strip('/').split('/')[1], record.get('message')), {}).items()
                                                  if not k.startswith('_')})

    def _read_bucket(self, method, path, major, now):
        template = route_class(method, path)
        name = hashlib.sha256(template.encode()).hexdigest()[:20]
        return self._bucket(name, major, *self.read_limit, now)

    def _answer(self, method, path, kind, person, body, now, record):
        parts = path.strip('/').split('/')
        if kind is None:
            return 401, {}, {'message': '401: Unauthorized', 'code': 0}
        # The person's bearer: identity proof and profile (the connect flow also lists servers).
        if kind == 'user':
            if person is None or person >= self.workspaces:
                return 401, {}, {'message': '401: Unauthorized', 'code': 0}
            ok, headers = self._read_bucket(method, path, 'user:%d' % person, now)
            if not ok:
                return 429, headers, {'message': 'You are being rate limited.', 'retry_after': float(headers['retry-after']), 'global': False}
            if method == 'GET' and path == '/oauth2/@me':
                return 200, headers, {'application': {'id': APP, 'name': 'Rafii', 'bot_public': True},
                                      'scopes': ['identify', 'guilds'],
                                      'expires': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(now + 6 * 86400)),
                                      'user': {'id': user_id(person), 'username': 'capuser%d' % person,
                                               'global_name': 'Capacity user %d' % person}}
            if method == 'GET' and path == '/users/@me':
                return 200, headers, {'id': user_id(person), 'username': 'capuser%d' % person,
                                      'global_name': 'Capacity user %d' % person}
            if method == 'GET' and path == '/users/@me/guilds':
                return 200, headers, [{'id': guild_id(person), 'name': 'Capacity server %d' % person, 'owner': True,
                                       'permissions': str((1 << 53) - 1)}]
            self.counters['unknownRoute'] += 1
            return 404, headers, {'message': 'Unknown route', 'code': 0}
        if kind == 'oauth':
            self.counters['unknownRoute'] += 1
            return 400, {}, {'error': 'invalid_grant'}
        # Bot token.
        if method == 'POST' and len(parts) == 3 and parts[0] == 'channels' and parts[2] == 'messages':
            return self._create(parts[1], body, now, record)
        major = parts[1] if len(parts) > 1 else 'none'
        ok, headers = self._read_bucket(method, path, major, now)
        if not ok:
            return 429, headers, {'message': 'You are being rate limited.', 'retry_after': float(headers['retry-after']), 'global': False}
        if method != 'GET':
            self.counters['unknownRoute'] += 1
            return 404, headers, {'message': 'Unknown route', 'code': 0}
        if path == '/oauth2/applications/@me':
            return 200, headers, {'id': APP, 'name': 'Rafii', 'bot_public': True}
        if path == '/users/@me':
            return 200, headers, {'id': BOT, 'bot': True, 'username': 'Rafii'}
        if parts[0] == 'guilds' and len(parts) >= 2:
            index = index_of(parts[1], GUILD0)
            if index is None or index >= self.workspaces:
                return 404, headers, {'message': 'Unknown Guild', 'code': 10004}
            guild = parts[1]
            record['guild'] = index
            if len(parts) == 2:
                return 200, headers, {'id': guild, 'name': 'Capacity server %d' % index, 'owner_id': OWNER,
                                      'roles': [{'id': guild, 'permissions': str(PERMISSIONS)}]}
            if len(parts) == 4 and parts[2] == 'members' and parts[3] in (BOT, user_id(index)):
                return 200, headers, {'user': {'id': parts[3]}, 'roles': [], 'pending': False,
                                      'communication_disabled_until': None}
            if len(parts) == 3 and parts[2] == 'channels':
                record['items'] = 1  # one text channel per server (production servers list many)
                return 200, headers, [{'id': channel_id(index), 'guild_id': guild, 'name': 'capacity', 'type': 0,
                                       'position': 0, 'permission_overwrites': []}]
            return 404, headers, {'message': 'Unknown Member', 'code': 10007}
        if len(parts) == 4 and parts[0] == 'channels' and parts[2] == 'messages':
            record['tenant'] = index_of(parts[1], CHANNEL0)
            message = self.messages.get((parts[1], parts[3]))
            if message is None:
                return 404, headers, {'message': 'Unknown Message', 'code': 10008}
            self.counters['readbacks'] += 1
            record.update(readback=message['id'], post=message.get('_post'))
            return 200, headers, {k: v for k, v in message.items() if not k.startswith('_')}
        self.counters['unknownRoute'] += 1
        return 404, headers, {'message': 'Unknown route', 'code': 0}

    def _create(self, channel, body, now, record):
        index = index_of(channel, CHANNEL0)
        self.counters['createAttempts'] += 1
        if index is None or index >= self.workspaces:
            return 404, {}, {'message': 'Unknown Channel', 'code': 10003}
        ok, headers = self._bucket('create-' + channel, channel, *self.CREATE_LIMIT, now)
        if not ok:
            record['createRefused'] = True
            return 429, headers, {'message': 'You are being rate limited.', 'retry_after': float(headers['retry-after']), 'global': False}
        body = body if isinstance(body, dict) else {}
        content, nonce = body.get('content'), body.get('nonce')
        mark = POST_MARK.search(content or '')
        post = mark.group(1) if mark else None
        record.update(nonce=nonce, post=post, channel=index)
        tenant = index_of(post.split('-')[0][1:], 0) if post and post.startswith('w') and '-' in post else None
        if tenant is not None and tenant != index:
            record['misrouted'] = True
            self.counters['misrouted'] += 1
        self.accepted_creates = getattr(self, 'accepted_creates', 0) + 1
        copies = 2 if self.double_accept_every and self.accepted_creates % self.double_accept_every == 0 else 1
        message = None
        for copy_number in range(copies):
            self.sequence += 1
            message = {'id': str(self.sequence), 'channel_id': channel, 'content': content, 'type': 0,
                       'author': {'id': BOT, 'bot': True, 'username': 'Rafii'}, 'mention_everyone': False,
                       'mentions': [], 'mention_roles': [], 'attachments': [], 'nonce': nonce,
                       'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(now)), '_post': post}
            self.messages[(channel, message['id'])] = message
            self.counters['creates'] += 1
            if copy_number:
                self.counters['doubleAccepted'] += 1
            if nonce in self.nonces:
                self.counters['duplicateNonceCreates'] += 1
            self.nonces.setdefault(nonce, []).append(now)
            if post is not None:
                if post in self.posts_created:
                    self.counters['duplicatePostCreates'] += 1
                self.posts_created.setdefault(post, []).append(now)
        record.update(message=message['id'], created=True, copies=copies)
        return 200, headers, {k: v for k, v in message.items() if not k.startswith('_')}

    def snapshot(self):
        with self.lock:
            return {'counters': dict(self.counters), 'peakTrailingSecondAll': self.peak_all,
                    'peakTrailingSecondBot': self.peak_bot, 'peakTrailingSecondApp': self.peak_app,
                    'peakTrailingSecondUser': self.peak_user, 'logged': len(self.log), 'at': self.clock(),
                    'injections': [{k: v for k, v in rule.items()} for rule in self.injections]}


def route_class(method, path):
    """The route template with ids masked, e.g. GET /guilds/{id}/members/{id}."""
    return method + ' ' + '/'.join('{id}' if _SNOWFLAKE.match(part) else part for part in path.split('/'))


# What the coordinator accepts as a bucket id (rate_limits.SharedPostgresBudget.observe: re.fullmatch on this pattern).
BUCKET_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def injected_bucket_id(route):
    """The x-ratelimit-bucket id of an injected route 429, always a valid bucket id.

    A route template carries braces ("GET /guilds/{id}"), which are not allowed in a bucket id. The coordinator, by
    reviewed design, holds a route whose 429 names an invalid bucket as a manual hold that only an operator releases;
    the first injected id ("injected-guilds-{id}") did exactly that and left five posts of F429 scheduled. The
    braces are dropped ("injected-guilds-id"), so the answer looks like the provider's, which names a valid bucket."""
    name = re.sub(r'[^A-Za-z0-9_-]+', '', route.split()[-1].replace('/', '-')).strip('-')
    return ('injected-' + name)[:128]


class InProcessTransport:
    """The World as the application's transport (seeding only): same answers, no HTTP, no latency, not logged."""
    def __init__(self, world):
        self.world = world
        self.calls = 0

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        path = urlsplit(url).path
        if not path.startswith(API_PREFIX):
            raise AssertionError('seeding transport reached a non-Discord URL')
        self.calls += 1
        lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
        status, answer_headers, answer, _ = self.world.handle(method, path[len(API_PREFIX):], lowered,
                                                              body if body is not None else form)
        with self.world.lock:
            self.world.log.clear()
        return {'status': status, 'headers': dict(answer_headers), 'body': answer}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'cap-mock-discord/1'

    def log_message(self, *_):
        pass

    def _reply(self, status, headers, body):
        if isinstance(body, dict) and '_html' in body:
            raw = body['_html'].encode()
            content_type = headers.pop('content-type', 'text/html; charset=UTF-8')
        else:
            raw = json.dumps(body).encode()
            content_type = 'application/json'
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def _serve(self, method):
        arrived = time.time()
        server = self.server
        path = urlsplit(self.path).path
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        if path.startswith('/__harness/'):
            return self._control(path, raw)
        if not path.startswith(API_PREFIX):
            return self._reply(404, {}, {'message': 'not a Discord API path'})
        body = None
        if raw:
            content_type = self.headers.get('Content-Type') or ''
            if 'json' in content_type:
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
            else:
                body = {'_form': raw.decode('utf-8', 'replace')[:200]}
        latency = server.latency.draw()
        time.sleep(latency / 2)
        headers = {k.lower(): v for k, v in self.headers.items()}
        status, answer_headers, answer, record = server.world.handle(method, path[len(API_PREFIX):], headers, body,
                                                                     arrived=arrived,
                                                                     wire_path=self.path[len(API_PREFIX):])
        delay = record.pop('delayAnswer', None)
        if delay:
            if record.pop('announceKill', False):
                announcement = {'port': self.client_address[1], 'nonce': record.get('nonce'), 'post': record.get('post'),
                                'at': time.time(), 'landed': record.get('landed')}
                with server.announce_lock:
                    with open(server.announce_path, 'a') as handle:
                        handle.write(json.dumps(announcement) + '\n')
            time.sleep(delay)
        time.sleep(latency / 2)
        record['latency'] = round(latency, 4)
        record['answered'] = time.time()
        try:
            return self._reply(status, answer_headers, answer)
        except (BrokenPipeError, ConnectionResetError):
            record['clientGone'] = True
            return None

    def _control(self, path, raw):
        server = self.server
        if path == '/__harness/stats':
            return self._reply(200, {}, server.world.snapshot())
        if path == '/__harness/shutdown':
            self._reply(200, {}, {'stopping': True})
            threading.Thread(target=server.shutdown, daemon=True).start()
            return None
        return self._reply(404, {}, {'message': 'unknown control path'})

    def do_GET(self):
        self._serve('GET')

    def do_POST(self):
        self._serve('POST')

    def do_DELETE(self):
        self._serve('DELETE')

    def do_PUT(self):
        self._serve('PUT')

    def do_PATCH(self):
        self._serve('PATCH')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


def write_outputs(world, directory):
    directory = os.path.abspath(directory)
    os.makedirs(directory, exist_ok=True)
    with world.lock:
        log = list(world.log)
        snapshot = {'counters': dict(world.counters), 'peakTrailingSecondAll': world.peak_all,
                    'peakTrailingSecondBot': world.peak_bot, 'peakTrailingSecondApp': world.peak_app,
                    'peakTrailingSecondUser': world.peak_user, 'logged': len(log), 'at': world.clock(),
                    'injections': [dict(rule) for rule in world.injections]}
        nonces = {nonce: times for nonce, times in world.nonces.items()}
        posts = {post: times for post, times in world.posts_created.items()}
    with open(os.path.join(directory, 'mock-requests.jsonl.tmp'), 'w') as handle:
        for record in log:
            handle.write(json.dumps(record, separators=(',', ':')) + '\n')
    os.replace(os.path.join(directory, 'mock-requests.jsonl.tmp'), os.path.join(directory, 'mock-requests.jsonl'))
    with open(os.path.join(directory, 'mock-summary.json.tmp'), 'w') as handle:
        json.dump({**snapshot, 'createsByNonce': nonces, 'createsByPost': posts}, handle)
    os.replace(os.path.join(directory, 'mock-summary.json.tmp'), os.path.join(directory, 'mock-summary.json'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Mock Discord for the W-02 capacity harness (localhost only).')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--out', required=True, help='directory for mock-requests.jsonl and mock-summary.json')
    parser.add_argument('--workspaces', type=int, default=10 ** 6)
    parser.add_argument('--latency', default='uniform:50:150')
    parser.add_argument('--tail-probability', type=float, default=0.0)
    parser.add_argument('--tail-ms', type=float, default=0.0)
    parser.add_argument('--read-limit', default='50:1', help='per-route read bucket LIMIT:SECONDS')
    parser.add_argument('--global-ceiling', type=int, default=50)
    parser.add_argument('--policy-ceiling', type=int, default=25)
    parser.add_argument('--bearer-ceiling', type=int, default=10,
                        help="the person's own bearer calls' ceiling per trailing second (the policy's bearer budget)")
    parser.add_argument('--double-accept-every', type=int, default=0,
                        help='negative control: every Nth create is accepted twice (0 = never)')
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--injections', help='JSON file with failure-injection rules (scenario F*)')
    args = parser.parse_args(argv)
    limit, window = args.read_limit.split(':')
    injections = json.loads(open(args.injections).read()) if args.injections else []
    world = World(workspaces=args.workspaces, read_limit=(int(limit), float(window)),
                  global_ceiling=args.global_ceiling, policy_ceiling=args.policy_ceiling,
                  bearer_ceiling=args.bearer_ceiling,
                  double_accept_every=args.double_accept_every, injections=injections)
    server = Server(('127.0.0.1', args.port), Handler)
    server.world, server.latency = world, Latency(args.latency, args.tail_probability, args.tail_ms, args.seed)
    server.announce_path, server.announce_lock = os.path.join(args.out, 'kill-requests.jsonl'), threading.Lock()
    stop = threading.Event()

    def periodic():
        # A checkpoint every few seconds, so a run cut short (a container restart) can still be analysed:
        # the request log so far (mock-requests.partial.jsonl) and the counters (mock-live.json).
        written = 0
        while not stop.wait(3):
            try:
                with world.lock:
                    fresh = world.log[written:]
                    written = len(world.log)
                if fresh:
                    with open(os.path.join(args.out, 'mock-requests.partial.jsonl'), 'a') as handle:
                        for record in fresh:
                            handle.write(json.dumps(record, separators=(',', ':')) + '\n')
                snapshot = world.snapshot()
                with world.lock:
                    snapshot['createsByNonce'] = {nonce: list(times) for nonce, times in world.nonces.items()}
                with open(os.path.join(args.out, 'mock-live.json.tmp'), 'w') as handle:
                    json.dump(snapshot, handle)
                os.replace(os.path.join(args.out, 'mock-live.json.tmp'), os.path.join(args.out, 'mock-live.json'))
            except OSError:
                pass

    def terminate(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'mock-config.json'), 'w') as handle:
        json.dump({'latency': server.latency.describe(), 'readLimit': [int(limit), float(window)],
                   'createLimit': list(World.CREATE_LIMIT), 'globalCeiling': args.global_ceiling,
                   'policyCeiling': args.policy_ceiling, 'bearerCeiling': args.bearer_ceiling,
                   'doubleAcceptEvery': args.double_accept_every,
                   'injections': injections, 'pid': os.getpid(), 'port': args.port}, handle)
    threading.Thread(target=periodic, daemon=True).start()
    print(json.dumps({'event': 'mock.ready', 'port': args.port, 'pid': os.getpid()}), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        stop.set()
        server.server_close()
        write_outputs(world, args.out)
        usage = os.times()
        with open(os.path.join(args.out, 'mock-process.json'), 'w') as handle:
            json.dump({'cpuSeconds': round(usage.user + usage.system, 3)}, handle)
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Mock Discord transport for the Q-05 sender-name cases (local harness only; never a socket).

Extends the target checkout's own LifecycleWire (identity / installation OAuth) with what the
customer sender-name feature needs:

* incoming webhooks: an OAuth code exchange that returns a `webhook` object (per-tenant webhook
  id and secret), GET /webhooks/{id}/{secret}, POST /webhooks/{id}/{secret}?wait=true (execute: the
  body's `username` is recorded and echoed as the message author's username, as Discord does), and
  GET /webhooks/{id}/{secret}/messages/{message} for reconciliation;
* the SHARED per-server bot member nickname: PATCH /guilds/{guild}/members/@me sets one nickname per
  guild (every workspace whose installation is in that server sees it), and GET of the bot member
  returns it;
* nickname permission bits on the synthetic server's @everyone role (Manage Nicknames for the
  authorizer, Change Nickname for the bot), which the sender-name GET/POST require;
* a thread-safe log of EVERY provider request (method, path), used for the per-HTTP-request
  provider-call attribution and for the send-level name-pollution checks.

The class is built by `make_wire(LifecycleWire, APP, BOT, GUILD)` because LifecycleWire and the
constants come from the checkout under test (Q05_TARGET_ROOT), not from this branch.
"""
import copy
import hashlib
import threading
from urllib.parse import urlsplit

CHANGE_NICKNAME = 1 << 26
MANAGE_NICKNAMES = 1 << 27


def make_wire(LifecycleWire, APP, BOT, GUILD, USER=None):
    class Q05Wire(LifecycleWire):
        def __init__(self, nickname_bits=True):
            super().__init__()
            # Only the sender-name target needs the nickname bits; without them (and without webhook
            # codes) this behaves exactly like LifecycleWire, plus the request log.
            self.nickname_bits = nickname_bits
            self.q05_lock = threading.RLock()
            self.q05_calls = []          # (method, path) of EVERY provider request, in order
            self.hooks = {}              # webhook id -> {secret, guild, channel, name, messages}
            self.hook_codes = {}         # OAuth code -> webhook id
            self.nick = {}               # guild id -> the shared bot member's nickname (None = unset)
            self.sent = []               # executed webhook messages, in order
            self.bot_sent = []           # bot channel messages created, in order (channel, message, nick at send)
            self.bot_messages = {}       # message id -> message (for the receipt read-back)
            self.patches = []            # nickname PATCHes: (guild, nick, audit-log reason header)
            self.on_request = None       # scenario hook: called once with (method, path) before answering
            self._message_seq = 0

        # -- setup ------------------------------------------------------------- #
        def add_hook(self, code, hook_id, secret, channel, name='Rafii'):
            with self.q05_lock:
                self.hooks[hook_id] = {'secret': secret, 'guild': GUILD, 'channel': channel,
                                       'name': name, 'messages': {}}
                self.hook_codes[code] = hook_id

        # -- observation ------------------------------------------------------- #
        def provider_calls(self):
            with self.q05_lock:
                return len(self.q05_calls)

        def provider_writes(self):
            """Requests that can change something at Discord (any non-GET except the OAuth token
            endpoints, which exchange/refresh credentials and change no Discord resource)."""
            with self.q05_lock:
                return sum(1 for method, path in self.q05_calls
                           if method != 'GET' and path not in ('/oauth2/token', '/oauth2/token/revoke'))

        def state(self):
            """A comparable snapshot of provider-side state a cross-tenant write could change."""
            with self.q05_lock:
                return {'nick': dict(self.nick), 'sent': len(self.sent),
                        'calls': len(self.q05_calls), 'writes': self.provider_writes()}

        # -- transport --------------------------------------------------------- #
        def __call__(self, method, url, **kwargs):
            return self._rate_headers(method, url, self._answer(method, url, **kwargs))

        @staticmethod
        def _rate_headers(method, url, result):
            """Discord answers every request with its rate-limit bucket headers; the shared admission
            coordinator learns each route's bucket from them (an unlearned route is probed at one request per
            second). A generous synthetic bucket per exact path, as the checkout's own engagement tests use."""
            if isinstance(result, dict):
                headers = dict(result.get('headers') or {})      # never mutate a dict the base wire may share
                result['headers'] = headers
                if not any(str(k).lower() == 'x-ratelimit-bucket' for k in headers):
                    path = urlsplit(url).path
                    headers.update({'X-RateLimit-Bucket': hashlib.sha256(f'{method} {path}'.encode()).hexdigest()[:16],
                                    'X-RateLimit-Limit': '1000', 'X-RateLimit-Remaining': '999',
                                    'X-RateLimit-Reset-After': '1'})
            return result

        def _answer(self, method, url, **kwargs):
            parts = urlsplit(url)
            path = parts.path.removeprefix('/api/v10')
            with self.q05_lock:
                self.q05_calls.append((method, path))
                hook, self.on_request = self.on_request, None
            if hook is not None and not hook(method, path):
                with self.q05_lock:          # not the request the hook waits for: re-arm it
                    if self.on_request is None:
                        self.on_request = hook
            form = kwargs.get('form') or {}
            if path == '/oauth2/token' and str(form.get('code', '')).startswith('webhook-'):
                return self._webhook_token(method, path, form)
            if path.startswith('/webhooks/'):
                return self._webhook(method, path, parts.query, kwargs)
            if method == 'PATCH' and path.startswith('/guilds/') and path.endswith('/members/@me'):
                guild = path.split('/')[2]
                nick = (kwargs.get('body') or {}).get('nick')
                reason = next((v for k, v in (kwargs.get('headers') or {}).items()
                               if str(k).lower() == 'x-audit-log-reason'), None)
                with self.q05_lock:
                    self.nick[guild] = nick
                    self.patches.append((guild, nick, reason))
                return {'status': 200, 'headers': {},
                        'body': {'user': {'id': BOT, 'bot': True, 'username': 'Rafii'}, 'nick': nick, 'roles': []}}
            if self.nickname_bits and path.startswith('/channels/') and '/messages' in path:
                return self._bot_message(method, path, kwargs)
            result = super().__call__(method, url, **kwargs)
            body = result.get('body') if isinstance(result, dict) else None
            if method == 'GET' and isinstance(body, dict):
                segs = path.split('/')
                if (self.nickname_bits and len(segs) == 3 and segs[1] == 'guilds'
                        and isinstance(body.get('roles'), list)):
                    for role in body['roles']:
                        if isinstance(role, dict) and str(role.get('permissions', '')).isdigit():
                            role['permissions'] = str(int(role['permissions']) | CHANGE_NICKNAME | MANAGE_NICKNAMES)
                    if USER is not None:
                        body['owner_id'] = USER     # the installing person owns the server (above the bot)
                if (self.nickname_bits and len(segs) == 5 and segs[1] == 'guilds' and segs[3] == 'members'
                        and segs[4] == BOT):
                    with self.q05_lock:
                        body['nick'] = self.nick.get(segs[2])
                    body.setdefault('user', {}).setdefault('username', 'Rafii')
            return result

        def _webhook_token(self, method, path, form):
            with self.q05_lock:
                hook_id = self.hook_codes[form['code']]
                hook = self.hooks[hook_id]
                access = 'synthetic-webhook-access-' + str(len(self.tokens))
                self.tokens[access] = ['identify']   # the bearer's own scopes (webhook.incoming is the grant)
            self.lifecycle_calls.append((method, path))
            return {'status': 200, 'headers': {}, 'body': {
                'token_type': 'Bearer', 'access_token': access, 'expires_in': 3600, 'scope': 'webhook.incoming',
                'webhook': {'id': hook_id, 'token': hook['secret'], 'type': 1, 'guild_id': hook['guild'],
                            'channel_id': hook['channel'], 'application_id': APP, 'name': hook['name']}}}

        def _webhook(self, method, path, query, kwargs):
            segs = path.split('/')           # ['', 'webhooks', id, secret, ('messages', mid)]
            hook = self.hooks.get(segs[2]) if len(segs) > 2 else None
            if not hook or len(segs) < 4 or hook['secret'] != segs[3]:
                return {'status': 404, 'headers': {}, 'body': {'message': 'Unknown Webhook', 'code': 10015}}
            hook_id = segs[2]
            if method == 'GET' and len(segs) == 4:
                return {'status': 200, 'headers': {}, 'body': {
                    'id': hook_id, 'application_id': APP, 'guild_id': hook['guild'],
                    'channel_id': hook['channel'], 'type': 1, 'name': hook['name']}}
            if method == 'POST' and len(segs) == 4:
                body = kwargs.get('body') or {}
                with self.q05_lock:
                    self._message_seq += 1
                    mid = str(880000000000 + self._message_seq)
                    message = {'id': mid, 'channel_id': hook['channel'], 'webhook_id': hook_id,
                               'author': {'id': hook_id, 'bot': True, 'username': body.get('username') or hook['name']},
                               'content': body.get('content'), 'mentions': [], 'mention_roles': [],
                               'mention_everyone': False, 'attachments': [], 'embeds': [],
                               'flags': body.get('flags', 0)}
                    hook['messages'][mid] = message
                    self.sent.append({'hook': hook_id, 'channel': hook['channel'], 'username': body.get('username'),
                                      'content': body.get('content'), 'keys': sorted(body), 'query': query,
                                      'message': mid, 'thread': threading.current_thread().name})
                return {'status': 200, 'headers': {}, 'body': copy.deepcopy(message)}
            if method == 'GET' and len(segs) == 6 and segs[4] == 'messages':
                with self.q05_lock:
                    message = hook['messages'].get(segs[5])
                if message is None:
                    return {'status': 404, 'headers': {}, 'body': {'message': 'Unknown Message', 'code': 10008}}
                return {'status': 200, 'headers': {}, 'body': copy.deepcopy(message)}
            return {'status': 405, 'headers': {}, 'body': {'message': '405: Method Not Allowed'}}

        def _bot_message(self, method, path, kwargs):
            segs = path.split('/')            # ['', 'channels', channel, 'messages', (id)]
            if method == 'POST' and len(segs) == 4:
                body = kwargs.get('body') or {}
                with self.q05_lock:
                    self._message_seq += 1
                    mid = str(990000000000 + self._message_seq)
                    message = {'id': mid, 'channel_id': segs[2], 'content': body.get('content'),
                               'author': {'id': BOT, 'bot': True, 'username': 'Rafii'}, 'mentions': [],
                               'mention_roles': [], 'mention_everyone': False, 'attachments': [], 'embeds': [],
                               'flags': body.get('flags', 0)}
                    self.bot_messages[mid] = message
                    self.bot_sent.append({'channel': segs[2], 'message': mid, 'nick': self.nick.get(GUILD),
                                          'content': body.get('content'), 'thread': threading.current_thread().name})
                return {'status': 200, 'headers': {}, 'body': copy.deepcopy(message)}
            if method == 'GET' and len(segs) == 5:
                with self.q05_lock:
                    message = self.bot_messages.get(segs[4])
                if message is None or message['channel_id'] != segs[2]:
                    return {'status': 404, 'headers': {}, 'body': {'message': 'Unknown Message', 'code': 10008}}
                return {'status': 200, 'headers': {}, 'body': copy.deepcopy(message)}
            return {'status': 405, 'headers': {}, 'body': {'message': '405: Method Not Allowed'}}

    return Q05Wire

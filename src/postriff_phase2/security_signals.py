"""Cross-tenant denial signal (H-07): one structured WARNING line, `security.cross_tenant_denied`.

Called from the workspace gate that answers the uniform 403 "Workspace unavailable." for workspace-scoped requests
through `PostgresWorkspaceRepository.transaction` in hosted.py, after the denial is decided and only on that path. It
is not every such 403: modules that re-implement the gate (for example time_savings, the agent runtime's own binding,
library metadata, account deletion, api token scopes) answer the same 403 without this signal. It never changes the
denial, never raises into the caller, touches no database and adds nothing to an allowed request. That 403 is the same
for a foreign workspace, a nonexistent one and a membership that ended, on purpose; this signal does not tell them
apart either (no extra query, no oracle). Many denials for one member in a few minutes is the probing pattern; one now
and then is usually a stale tab or an old link. A denial is the gate working: no data left.

The line carries only: `routeFamily` (the subsystem that asked for the workspace: 'discord', 'connections',
'workspace' or 'other', read from the calling module's name, never from the request), `status` (403), `actorKey` (the
first 10 hex digits of SHA-256 over ACTOR_LABEL followed by the member id: 40 bits, enough to correlate one member's
lines, not to identify them; the owner can recompute it for a known member, nobody can reverse it), `count` (this
process's running count for that key, family and minute), `minute` (epoch minutes), `final` (the minute's last word)
and `instance` (a random label of this process, so counts of different processes add up). Never a workspace id,
object id, path, body, token or e-mail.

Volume: a line at the running counts 1, 10, 100 and 1,000 (then every further 1,000) of each actor key and family in a
minute, and one final line when the minute is over if its last count was not already logged: a burst is never
reported as one denial. The final line is written at this process's next denial or health summary after the minute,
so a process that stops first leaves its last marked count (within a factor of ten). The tables are bounded (MAX_KEYS
distinct keys a minute; beyond that one 'overflow' key per family) and keep 16 minutes.

summary() gives the health payload the same counts without any key, for THIS process only (a serverless instance
sees its own requests): denials by family in the last 15 minutes, the largest count of one actor in the last 10
minutes and how many actors were denied. Fleet-wide numbers come from the log lines (scripts/discord_ops_check.py
reads them).
"""
import hashlib
import json
import logging
import secrets
import sys
import threading
import time

EVENT = 'security.cross_tenant_denied'
ACTOR_LABEL = 'rafii.cross-tenant:'
FAMILIES = ('discord', 'connections', 'workspace', 'other')
MAX_KEYS = 2048
KEEP_MINUTES = 16
MAX_FRAMES = 12
OVERFLOW = 'overflow'
INSTANCE = secrets.token_hex(4)   # a random label of this process, never derived from anything about it
# The modules between the denial and the subsystem that asked: the gate itself, its context managers, this module.
_SKIP = ('postriff_phase2.hosted', 'postriff_phase2.security_signals', 'contextlib')
_MODULES = (('postriff_phase2.discord', 'discord'), ('postriff_phase2.oauth', 'connections'),
            ('postriff_phase2.productivity_connectors', 'connections'), ('postriff_phase2.hosted_app', 'workspace'))


def actor_key(member):
    return hashlib.sha256((ACTOR_LABEL + str(member)).encode('utf-8')).hexdigest()[:10]


def caller_family(frame):
    """The route family from the first calling module outside the gate. Bounded; module names only."""
    for _ in range(MAX_FRAMES):
        if frame is None:
            break
        module = frame.f_globals.get('__name__', '')
        if not isinstance(module, str):
            break
        if module in _SKIP:
            frame = frame.f_back
            continue
        for prefix, name in _MODULES:
            if module == prefix or module.startswith(prefix + '.'):
                return name
        return 'workspace' if module.startswith('postriff_phase2.') else 'other'
    return 'other'


def marked(count):
    """The running counts that get a line: 1, 10, 100, 1,000, then every further 1,000."""
    return count in (1, 10, 100, 1000) or (count > 1000 and count % 1000 == 0)


class DenialSignal:
    """Bounded per-process counts, lines at marked running counts and a final line per minute. Thread-safe; no I/O
    except the log lines, which are written after the lock is released."""

    def __init__(self, *, clock=time.time, logger=None, instance=INSTANCE):
        self.clock = clock
        self.logger = logger or logging.getLogger('postriff.request')
        self.instance = instance
        self.lock = threading.Lock()
        self.minutes = {}       # minute -> {(actor, family): count}
        self.logged = {}        # (minute, (actor, family)) -> the count of its last line
        self.swept = None       # the minute old entries were last dropped and earlier minutes flushed

    def _line(self, key, minute, count, status=403, final=False):
        # Counts and codes only: no workspace, object, path, body, token or e-mail.
        return json.dumps({'event': EVENT, 'routeFamily': key[1], 'status': int(status), 'actorKey': key[0], 'count': count,
                           'minute': minute, 'final': final, 'instance': self.instance})

    def _rollover(self, minute):
        """Under the lock, once per new minute: the final lines of earlier minutes, and old entries dropped."""
        if self.swept == minute:
            return []
        self.swept = minute
        lines = []
        for at in sorted(m for m in self.minutes if m < minute):
            for key, count in self.minutes[at].items():
                if self.logged.get((at, key), 0) < count:
                    self.logged[(at, key)] = count
                    lines.append(self._line(key, at, count, final=True))
        for old in [m for m in self.minutes if m < minute - KEEP_MINUTES]:
            del self.minutes[old]
        for logged in [k for k in self.logged if k[0] < minute - KEEP_MINUTES]:
            del self.logged[logged]
        return lines

    def _emit(self, lines):
        for line in lines:
            self.logger.warning(line)

    def denied(self, member, family='other', status=403):
        family = family if family in FAMILIES else 'other'
        now = self.clock()
        minute = int(now // 60)
        actor = actor_key(member)
        with self.lock:
            lines = self._rollover(minute)
            bucket = self.minutes.setdefault(minute, {})
            key = (actor, family)
            if key not in bucket and len(bucket) >= MAX_KEYS:
                key = (OVERFLOW, family)
            count = bucket[key] = bucket.get(key, 0) + 1
            mine = marked(count)
            if mine:
                self.logged[(minute, key)] = count
                lines.append(self._line(key, minute, count, status))
        self._emit(lines)
        return mine

    def summary(self, now=None):
        now = self.clock() if now is None else now
        minute = int(now // 60)
        families = dict.fromkeys(FAMILIES, 0)
        actors = {}
        with self.lock:
            flushed = self._rollover(minute)
            for at, bucket in self.minutes.items():
                for (actor, family), count in bucket.items():
                    if at > minute - 15:
                        families[family] += count
                    if at > minute - 10 and actor != OVERFLOW:
                        actors[actor] = actors.get(actor, 0) + count
        self._emit(flushed)
        return {'scope': 'instance', 'windowSeconds': 900, 'denied': families, 'deniedTotal': sum(families.values()),
                'actors10m': len(actors), 'topActorDenials10m': max(actors.values(), default=0)}


SIGNAL = DenialSignal()


def cross_tenant_denied(member, status=403):
    """The gate's one call. Never raises; returns whether a line was written."""
    try:
        return SIGNAL.denied(member, caller_family(sys._getframe(1)), status)
    except Exception:  # the denial stands whatever happens here
        return False


def summary():
    try:
        return SIGNAL.summary()
    except Exception:
        return {'scope': 'instance', 'status': 'unavailable'}

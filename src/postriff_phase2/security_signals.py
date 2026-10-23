"""Cross-tenant denial signal (H-07): one structured WARNING line, `security.cross_tenant_denied`.

Called from the one place that answers the uniform 403 "Workspace unavailable." for workspace-scoped requests
(`PostgresWorkspaceRepository.transaction` in hosted.py), after the denial is decided and only on that path. It never
changes the denial, never raises into the caller, touches no database and adds nothing to an allowed request. That
403 is the same for a foreign workspace, a nonexistent one and a membership that ended, on purpose; this signal does
not tell them apart either (no extra query, no oracle). Many denials for one member in a few minutes is the probing
pattern; one now and then is usually a stale tab or an old link.

The line carries only: `routeFamily` (the subsystem that asked for the workspace: 'discord', 'connections',
'workspace' or 'other', read from the calling module's name, never from the request), `status` (403), `actorKey` (the
first 10 hex digits of SHA-256 over ACTOR_LABEL followed by the member id; the owner can recompute it for a known
member, nobody can reverse it) and `suppressed` (denials of the same key and family this process did not log since its
previous line). Never a workspace id, object id, path, body, token or e-mail.

Volume: at most one line per actor key and route family per minute per process. The tables are bounded (MAX_KEYS
distinct keys a minute; beyond that one 'overflow' line per family a minute) and keep 16 minutes.

summary() gives the health payload the same counts without any key, for THIS process only (a serverless instance
sees its own requests): denials by family in the last 15 minutes, the largest count of one actor in the last 10
minutes and how many actors were denied. Fleet-wide numbers come from the log lines (scripts/discord_ops_check.py
reads them).
"""
import hashlib
import json
import logging
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


class DenialSignal:
    """Bounded per-process counts and the one-line-a-minute cap. Thread-safe; no I/O except the log line."""

    def __init__(self, *, clock=time.time, logger=None):
        self.clock = clock
        self.logger = logger or logging.getLogger('postriff.request')
        self.lock = threading.Lock()
        self.minutes = {}       # minute -> {(actor, family): count}
        self.logged = {}        # (actor, family) -> minute of its last line
        self.suppressed = {}    # (actor, family) -> denials not logged since that line
        self.swept = None       # the minute old entries were last dropped: once a minute, not on every denial

    def denied(self, member, family='other', status=403):
        family = family if family in FAMILIES else 'other'
        now = self.clock()
        minute = int(now // 60)
        actor = actor_key(member)
        with self.lock:
            if self.swept != minute:
                self.swept = minute
                for old in [m for m in self.minutes if m < minute - KEEP_MINUTES]:
                    del self.minutes[old]
                for key in [k for k, m in self.logged.items() if m < minute - KEEP_MINUTES]:
                    self.logged.pop(key, None)
                    self.suppressed.pop(key, None)
            bucket = self.minutes.setdefault(minute, {})
            key = (actor, family)
            if key not in bucket and len(bucket) >= MAX_KEYS:
                key = (OVERFLOW, family)
            bucket[key] = bucket.get(key, 0) + 1
            if self.logged.get(key) == minute:
                self.suppressed[key] = self.suppressed.get(key, 0) + 1
                return False
            suppressed = self.suppressed.pop(key, 0)
            self.logged[key] = minute
        # Counts and codes only: no workspace, object, path, body, token or e-mail.
        self.logger.warning(json.dumps({'event': EVENT, 'routeFamily': family, 'status': int(status),
                                        'actorKey': key[0], 'suppressed': suppressed}))
        return True

    def summary(self, now=None):
        now = self.clock() if now is None else now
        minute = int(now // 60)
        families = dict.fromkeys(FAMILIES, 0)
        actors = {}
        with self.lock:
            for at, bucket in self.minutes.items():
                for (actor, family), count in bucket.items():
                    if at > minute - 15:
                        families[family] += count
                    if at > minute - 10 and actor != OVERFLOW:
                        actors[actor] = actors.get(actor, 0) + count
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

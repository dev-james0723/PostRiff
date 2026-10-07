"""Founder reliability request metrics (CONTRACTS §8.D, PRD §7.1 M25, §8.7, §8.9): minute x route pattern x status class.

Boundaries. `observe()` runs in HostedApplication.__call__'s finally block, after the request.completed log line, and only
updates a bounded in-process buffer: no I/O, no exception escapes, nothing is added to the request's own work or its
transaction. A daemon thread upserts the buffered minutes into public.pr_request_metrics (migration 060) through the consumer
runtime's own connection factory (the runtime the deployment checks validated), at most once every FLUSH_SECONDS per process.
Writes happen only in a deployed process: POSTRIFF_DATABASE_URL set (off with POSTRIFF_REQUEST_METRICS=0) and the runtime
built; until then nothing is recorded or the buffer simply waits, bounded.

What is stored: the request method, a route pattern that keeps only known static route words (every other path segment becomes
':id', non-API paths become '/:other', a full buffer folds into '/:overflow'), the status class, a count, a duration sum and
a fixed 20-bucket latency histogram. Never the raw path, query string, body, header, identity, address or token.

Failure handling. Production may run this code before 060 is applied: a missing table, column or privilege (UndefinedTable,
UndefinedColumn, InsufficientPrivilege) means "not installed yet": it is logged once per process (exception class only) and
flushing pauses for ten minutes, dropping what was buffered. Any other failure is logged by class and pauses for five minutes.
Logs go to 'postriff.request_metrics', never to the request logger.
"""
import bisect
import json
import logging
import os
import threading
import time

# Upper bounds (ms) of the first 19 histogram buckets; the 20th is open-ended. Must equal
# rafii_control.founder_metrics_ops.BOUNDS_MS (the reader) and the bounds documented in migration 060.
BOUNDS_MS = (10, 25, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 20000, 30000)
BUCKETS = len(BOUNDS_MS) + 1
METHODS = frozenset(('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'))
MAX_ROUTE_LENGTH = 160      # = the founder metric-query filter value limit, so every stored route can be filtered on
MAX_SEGMENTS = 9
MAX_KEYS = 600              # distinct (minute, route, status class) keys held between flushes
OVERFLOW_KEYS = 64          # extra keys for the per-method '/:overflow' buckets; beyond that a sample is dropped and counted
FLUSH_SECONDS = 15
NOT_INSTALLED_PAUSE = 600
FAILURE_PAUSE = 300
NOT_INSTALLED = frozenset(('UndefinedTable', 'UndefinedColumn', 'InsufficientPrivilege'))
LOGGER = 'postriff.request_metrics'

# Static route words of the consumer API, the founder Control API (/api/control/v2) and provider ids. A segment outside this
# set is stored as ':id', so a missing word only lowers the resolution of one route; it can never leak an identifier.
ROUTE_WORDS = frozenset('''
api health catalog privacy notice content-types content-formats content-type-packs content-dna auth config verify verify-call
logout sessions session revoke revoke-others mfa me channels security-events invitations accept decline workspaces workspace
tokens tools invoke skills ideas models rescan credit-quotes credit-estimates media-notes quick-start conversations navigation
search onboarding turns messages window moments attachments runs events cancel apply site-agent compose proposals dismiss
compound continue feedback help insights agent voice tasks approvals approve decide decision interrupt state status end
transcript phone calls call schedules preferences number numbers verification inbound inbound-codes trusted-callers answer
webhooks webhook dial twilio telnyx fake coworker notifications notification-preferences push-subscriptions sms email
unsubscribe growth radar trends genome postmortems post-doctor check checks scans history quotes rewrite advance
provider-readiness providers billing credit-packs credit-checkout checkout portal usage subscription data-requests analytics
summary posts time-savings activity calibrations audience threads reply-drafts reply-preview reply oauth start complete
callback destinations creator-info destination import history-import picture media videos commit url members memory versions
audit leave transfer-ownership actions export profile-export account cron worker telegram xiaohongshu client-metadata.json
jwks.json connectors refresh templates recipes
control v2 exchange overview metrics query receipts incidents ack follow-ups contact-policy briefing-schedules test unknown
reconcile preview confirm credits accounts block unblock refunds revenue movements customers risk users engineering sources
dashboards recommendations demo scenario scenarios reset rename reports briefings
bilibili bluesky discord douyin facebook google_business_profile instagram kuaishou line_official_account linkedin mastodon
pinterest pixelfed reddit threads tiktok weibo x youtube zhihu gmail notion
'''.split())


def route_key(method, path):
    """'<METHOD> <pattern>' with every non-route word masked; bounded to MAX_ROUTE_LENGTH at a segment boundary."""
    method = method.upper() if isinstance(method, str) else ''
    method = method if method in METHODS else 'OTHER'
    path = path if isinstance(path, str) else ''
    segments = [part for part in path.split('/') if part]
    if not segments or segments[0] != 'api':
        return method + ' /:other'
    route = method + ' /api'
    for index, part in enumerate(segments[1:]):
        piece = '/' + (part if part in ROUTE_WORDS else ':id')
        if index >= MAX_SEGMENTS - 1 or len(route) + len(piece) > MAX_ROUTE_LENGTH - len('/:more'):
            return route + '/:more'
        route += piece
    return route


def status_class(status):
    try:
        code = int(status)
    except (TypeError, ValueError):
        return '5xx'
    return f'{code // 100}xx' if 100 <= code <= 599 else '5xx'


def bucket_index(milliseconds):
    """Index of the histogram bucket whose upper bound is the first >= the duration (Prometheus 'le' semantics)."""
    return bisect.bisect_left(BOUNDS_MS, milliseconds)


UPSERT = ('INSERT INTO public.pr_request_metrics AS m (minute,route_pattern,status_class,request_count,duration_sum_ms,duration_buckets) '
          'VALUES (to_timestamp(%s),%s,%s,%s,%s,%s::bigint[]) ON CONFLICT (minute,route_pattern,status_class) DO UPDATE SET '
          'request_count=m.request_count+excluded.request_count,duration_sum_ms=m.duration_sum_ms+excluded.duration_sum_ms,'
          'duration_buckets=(SELECT array_agg(coalesce(u.a,0)+coalesce(u.b,0) ORDER BY u.i) FROM unnest(m.duration_buckets,excluded.duration_buckets) WITH ORDINALITY AS u(a,b,i)),'
          'updated_at=now()')


def _spawn(work):
    threading.Thread(target=work, name='request-metrics-flush', daemon=True).start()


class Recorder:
    """Bounded per-process aggregation plus a single background flusher. Thread-safe; `record` and `maybe_flush` do no I/O."""

    def __init__(self, *, clock=time.time, spawn=_spawn, logger=None):
        self.clock, self.spawn = clock, spawn
        self.logger = logger or logging.getLogger(LOGGER)
        self.lock = threading.Lock()
        self.buffer, self.dropped = {}, 0
        self.flushing, self.last_flush, self.paused_until = False, 0.0, 0.0
        self.not_installed_logged = False

    def record(self, method, path, status, seconds, now=None):
        now = self.clock() if now is None else now
        if now < self.paused_until:
            return
        minute = int(now // 60) * 60
        route, klass = route_key(method, path), status_class(status)
        milliseconds = max(0.0, float(seconds) * 1000.0)
        index = bucket_index(milliseconds)
        with self.lock:
            key = (minute, route, klass)
            entry = self.buffer.get(key)
            if entry is None and len(self.buffer) >= MAX_KEYS:
                key = (minute, route.split(' ', 1)[0] + ' /:overflow', klass)
                entry = self.buffer.get(key)
                if entry is None and len(self.buffer) >= MAX_KEYS + OVERFLOW_KEYS:
                    self.dropped += 1
                    return
            if entry is None:
                entry = self.buffer[key] = [0, 0.0, [0] * BUCKETS]
            entry[0] += 1
            entry[1] += milliseconds
            entry[2][index] += 1

    def maybe_flush(self, factory, now=None):
        """Hand the buffered minutes to the background flusher when due. Returns True when a flush was started."""
        now = self.clock() if now is None else now
        with self.lock:
            if self.flushing or not self.buffer or now < self.paused_until or now - self.last_flush < FLUSH_SECONDS:
                return False
            batch, self.buffer = self.buffer, {}
            self.flushing, self.last_flush = True, now
        try:
            self.spawn(lambda: self.flush(factory, batch))
        except Exception as error:   # a thread that cannot start is a failed flush, never a failed request
            self._failed(error)
            with self.lock:
                self.flushing = False
        return True

    def flush(self, factory, batch):
        rows = [(minute, route, klass, entry[0], round(entry[1], 3), list(entry[2])) for (minute, route, klass), entry in sorted(batch.items())]
        try:
            with factory() as db:
                with db.cursor() as cur:
                    # Own short transaction on the consumer connection; sorted keys keep concurrent instances' row locks ordered.
                    cur.execute('SET LOCAL statement_timeout = 2000')
                    cur.executemany(UPSERT, rows)
                db.commit()
        except Exception as error:
            self._failed(error)
        finally:
            with self.lock:
                self.flushing = False

    def _failed(self, error):
        not_installed = any(cls.__name__ in NOT_INSTALLED for cls in type(error).__mro__)
        pause = NOT_INSTALLED_PAUSE if not_installed else FAILURE_PAUSE
        with self.lock:
            self.paused_until = self.clock() + pause
            self.buffer = {}
            log = not (not_installed and self.not_installed_logged)
            self.not_installed_logged = self.not_installed_logged or not_installed
        if log:
            self.logger.warning(json.dumps({'event': 'request_metrics.not_installed' if not_installed else 'request_metrics.flush_failed',
                                            'error': type(error).__name__, 'pauseSeconds': pause}, sort_keys=True))


RECORDER = Recorder()


def enabled(environ=None):
    environ = os.environ if environ is None else environ
    return bool(environ.get('POSTRIFF_DATABASE_URL')) and environ.get('POSTRIFF_REQUEST_METRICS', '1') != '0'


def connection_factory(service):
    """The consumer runtime's validated connection factory, or None before the runtime is built."""
    factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
    return factory if callable(factory) else None


def observe(app, method, path, status, seconds):
    """Request-completion hook (HostedApplication.__call__). Records one request and schedules a background flush. Never raises."""
    try:
        if not enabled():
            return
        RECORDER.record(method, path, status, seconds)
        factory = connection_factory(getattr(app, 'service', None))
        if factory is not None:
            RECORDER.maybe_flush(factory)
    except Exception:
        pass

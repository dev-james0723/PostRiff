"""Rafii agent metrics (P0.7): minute x metric x label counters, written off the request path to public.pr_agent_metrics.

The same shape and boundaries as request_metrics (founder reliability, migration 060), for the agent runtime:
- `record()` only updates a bounded in-process buffer: no I/O, no exception escapes, nothing joins a request's transaction.
- `maybe_flush()` hands the buffer to one daemon thread that upserts it through the consumer runtime's own connection
  factory, at most once every FLUSH_SECONDS per process, in its own short transaction (statement timeout 2 s).
- Writes happen only in a deployed process (POSTRIFF_DATABASE_URL set); POSTRIFF_AGENT_OBSERVABILITY=0 turns everything off.
- A missing table, column or privilege (migration 110 not applied yet) is "not installed": logged once per process
  (exception class only), flushing pauses for ten minutes and the buffer is dropped. Any other failure pauses five minutes.

What is stored: a fixed metric name (METRICS), a bounded label made of codes from agent_observability (path, status, tool,
reason, provider, surface; never an id, a name, a title or any text), a count, a value sum and, for millisecond metrics, a
fixed 20-bucket histogram. No workspace, person, conversation, run or trace id: the founder view reads aggregates only.
"""
from __future__ import annotations

import bisect
import json
import logging
import os
import re
import threading
import time

# Upper bounds (ms) of the first 19 buckets; the 20th is open-ended. From 50 ms (a read tool) to an hour (an approval that
# waited). Must equal rafii_control.founder_agent_observability.BOUNDS_MS and migration 110's comment.
BOUNDS_MS = (50, 100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000, 15000, 20000, 30000, 45000, 60000, 120000, 300000, 900000, 3600000)
BUCKETS = len(BOUNDS_MS) + 1
# metric -> unit of its value. 'ms' values fill the histogram; 'usd_micro' values only add to the sum; 'count' has no value.
METRICS = {
    "agent.turn": "ms",              # label path:status (end-to-end latency of one runtime turn)
    "agent.turn.fallback": "count",  # label fallback code (why a turn ended deterministic or on the site agent)
    "agent.turn.cost": "usd_micro",  # label path, or path:unknown when the spend could not be priced
    "agent.run.closed": "count",     # label path:status, a run persisted outside a turn (phone, reaper)
    "agent.tool": "ms",              # label tool:status (verified | unverified | failed | blocked)
    "agent.tool.error": "count",     # label tool:code
    "agent.authz": "count",          # label mode:outcome:reason
    "agent.approval": "ms",          # label surface:outcome (how long the proposal waited)
    "agent.provider_auth": "count",  # label provider:reason
    "agent.outcome": "count",        # label verified | unverified | failed | cancelled | pending_approval | no_change
    "agent.change": "count",         # label verified | unverified (each changed entity, re-read)
    "agent.retry": "count",          # label kind
    "agent.recovery": "count",       # label kind:result
    "agent.genui": "count",          # label eligible | the handoff's reason code
    "agent.task": "ms",              # label name:state (CF-3 task engine, lane A2)
}
LABEL = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,119}$")
MAX_KEYS = 800
OVERFLOW_KEYS = 64
FLUSH_SECONDS = 15
NOT_INSTALLED_PAUSE = 600
FAILURE_PAUSE = 300
PURGE_SECONDS = 6 * 3600
RETENTION_DAYS = 30
NOT_INSTALLED = frozenset(("UndefinedTable", "UndefinedColumn", "InsufficientPrivilege"))
LOGGER = "postriff.agent_metrics"

UPSERT = ("INSERT INTO public.pr_agent_metrics AS m (minute,metric,label,event_count,value_sum,value_buckets) "
          "VALUES (to_timestamp(%s),%s,%s,%s,%s,%s::bigint[]) ON CONFLICT (minute,metric,label) DO UPDATE SET "
          "event_count=m.event_count+excluded.event_count,value_sum=m.value_sum+excluded.value_sum,"
          "value_buckets=(SELECT array_agg(coalesce(u.a,0)+coalesce(u.b,0) ORDER BY u.i) FROM unnest(m.value_buckets,excluded.value_buckets) WITH ORDINALITY AS u(a,b,i)),"
          "updated_at=now()")
PURGE = ("DELETE FROM public.pr_agent_metrics WHERE ctid IN (SELECT ctid FROM public.pr_agent_metrics "
         "WHERE minute < now() - make_interval(days => %s) LIMIT 5000)")


def bucket_index(milliseconds: float) -> int:
    return bisect.bisect_left(BOUNDS_MS, milliseconds)


def label_key(label) -> str:
    """A stored label: lowercase codes joined by ':'; anything else becomes 'other' (it can never carry text or an id)."""
    if not isinstance(label, str) or not LABEL.match(label):
        return "other"
    from .agent_observability import _SECRET
    return "other" if _SECRET.search(label) else label


def _spawn(work):
    threading.Thread(target=work, name="agent-metrics-flush", daemon=True).start()


class Recorder:
    """Bounded per-process aggregation plus a single background flusher. Thread-safe; `record` and `maybe_flush` do no I/O."""

    def __init__(self, *, clock=time.time, spawn=_spawn, logger=None):
        self.clock, self.spawn = clock, spawn
        self.logger = logger or logging.getLogger(LOGGER)
        self.lock = threading.Lock()
        self.buffer, self.dropped = {}, 0
        self.flushing, self.last_flush, self.paused_until, self.last_purge = False, 0.0, 0.0, 0.0
        self.not_installed_logged = False

    def record(self, metric, label, value=None, count=1, now=None) -> bool:
        try:
            unit = METRICS.get(metric)
            if unit is None or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10_000:
                return False
            now = self.clock() if now is None else now
            if now < self.paused_until:
                return False
            number = float(value) if unit != "count" and isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value >= 0 else None
            minute = int(now // 60) * 60
            key = (minute, metric, label_key(label))
            with self.lock:
                entry = self.buffer.get(key)
                if entry is None and len(self.buffer) >= MAX_KEYS:
                    key = (minute, metric, "overflow")
                    entry = self.buffer.get(key)
                    if entry is None and len(self.buffer) >= MAX_KEYS + OVERFLOW_KEYS:
                        self.dropped += count
                        return False
                if entry is None:
                    entry = self.buffer[key] = [0, 0.0, [0] * BUCKETS]
                entry[0] += count
                if number is not None:
                    entry[1] += number * count
                    if unit == "ms":
                        entry[2][bucket_index(number)] += count
            return True
        except Exception:  # noqa: BLE001 — a metric is never a reason for a request to fail
            return False

    def snapshot(self) -> dict:
        with self.lock:
            return {key: [entry[0], entry[1], list(entry[2])] for key, entry in self.buffer.items()}

    def maybe_flush(self, factory, now=None) -> bool:
        """Hand the buffered minutes to the background flusher when due. Returns True when a flush was started."""
        now = self.clock() if now is None else now
        with self.lock:
            if self.flushing or not self.buffer or now < self.paused_until or now - self.last_flush < FLUSH_SECONDS:
                return False
            batch, self.buffer = self.buffer, {}
            purge = now - self.last_purge >= PURGE_SECONDS
            self.flushing, self.last_flush = True, now
            if purge:
                self.last_purge = now
        try:
            self.spawn(lambda: self.flush(factory, batch, purge=purge))
        except Exception as error:  # noqa: BLE001 — a thread that cannot start is a failed flush, never a failed request
            self._failed(error)
            with self.lock:
                self.flushing = False
        return True

    def flush(self, factory, batch, *, purge=False) -> None:
        rows = [(minute, metric, label, entry[0], round(entry[1], 3), list(entry[2])) for (minute, metric, label), entry in sorted(batch.items())]
        try:
            with factory() as db:
                with db.cursor() as cur:
                    # Own short transaction on the consumer connection; sorted keys keep concurrent instances' row locks ordered.
                    cur.execute("SET LOCAL statement_timeout = 2000")
                    cur.executemany(UPSERT, rows)
                    if purge:
                        cur.execute(PURGE, (RETENTION_DAYS,))
                db.commit()
        except Exception as error:  # noqa: BLE001
            self._failed(error)
        finally:
            with self.lock:
                self.flushing = False

    def _failed(self, error) -> None:
        not_installed = any(cls.__name__ in NOT_INSTALLED for cls in type(error).__mro__)
        pause = NOT_INSTALLED_PAUSE if not_installed else FAILURE_PAUSE
        with self.lock:
            self.paused_until = self.clock() + pause
            self.buffer = {}
            log = not (not_installed and self.not_installed_logged)
            self.not_installed_logged = self.not_installed_logged or not_installed
        if log:
            self.logger.warning(json.dumps({"event": "agent_metrics.not_installed" if not_installed else "agent_metrics.flush_failed",
                                            "error": type(error).__name__, "pauseSeconds": pause}, sort_keys=True))


RECORDER = Recorder()


def writes_enabled(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    from .agent_observability import enabled
    return bool(environ.get("POSTRIFF_DATABASE_URL")) and enabled(environ)


def maybe_flush(service) -> bool:
    """Schedule a background flush through the consumer runtime's validated connection factory. Never raises."""
    try:
        if not writes_enabled():
            return False
        from .request_metrics import connection_factory
        factory = connection_factory(service)
        return RECORDER.maybe_flush(factory) if factory is not None else False
    except Exception:  # noqa: BLE001
        return False

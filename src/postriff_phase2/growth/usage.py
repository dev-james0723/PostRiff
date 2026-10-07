"""Per-call AI usage and cost ledger for growth features (growth Phase 0).

Every model or evaluation attempt, successful or not, becomes one UsageEvent. Cost is the Gateway-reported
figure when present (`cost_source="gateway"`); otherwise it stays unknown (None), never zero. Events carry
opaque identifiers only (workspace id, subject hash), never prompt or post text.

Founder Admin §8.B (PRD §8.1): `PostgresUsageSink` also records each event as one `public.pr_ai_call_events` row, the
all-feature attempt table, through `ai_call_events` (inside the caller's transaction under a savepoint, so a missing
table never touches the growth write); `pr_model_usage_events` keeps its rows and readers.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

from .. import ai_call_events

STATUSES_OK = ("ok",)
# Growth task prefix → the bounded feature label of pr_ai_call_events (the task itself is the workload).
FEATURES = {"radar": "radar", "trend": "trends", "scout": "scout", "postdoctor": "post_doctor", "audience": "audience",
            "postmortem": "postmortem", "genome": "genome", "golden": "golden"}
# Router status codes → attempt statuses. A refusal (rate limit, auth, budget, bad request) was never processed and costs
# nothing; an upstream error or an unreadable outcome stays unknown.
STATUSES = {"ok": "ok", "rate_limited": "rate_limited", "timeout": "timeout", "cancelled": "cancelled", "malformed": "failed",
            "auth": "failed", "budget": "failed", "bad_request": "failed"}
REFUSED = frozenset({"rate_limited", "auth", "budget", "bad_request"})


@dataclass(frozen=True)
class UsageEvent:
    task: str
    model: str
    route: str                   # "primary" | "fallback"
    status: str                  # "ok" or an error code such as "rate_limited", "timeout", "malformed"
    latency_ms: int
    stage: str | None = None
    provider: str | None = None
    generation_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str = "unknown"  # "gateway" | "table:<version>" | "unknown"
    workspace_id: str | None = None
    subject: str | None = None
    # 1 for the first attempt of a (task, workspace, subject, route) call, +1 for each retry after a failure (set by
    # MemoryUsageSink; None when an event was never numbered). Not part of equality: the same attempt is the same event.
    attempt_no: int | None = field(default=None, compare=False)

    def cost_usd_micro(self):
        if self.cost_usd is None or not math.isfinite(self.cost_usd) or self.cost_usd < 0:
            return None
        return math.ceil(self.cost_usd * 1_000_000)


class MemoryUsageSink:
    def __init__(self):
        self.events = []
        self._last = None

    def record(self, event):
        if isinstance(event, UsageEvent) and event.attempt_no is None:
            key = (event.task, event.workspace_id, event.subject, event.route)
            last = getattr(self, "_last", None)
            number = last[1] + 1 if last and last[0] == key and last[2] not in STATUSES_OK else 1
            self._last = (key, number, event.status)
            event = replace(event, attempt_no=number)
        self.events.append(event)

    def total_usd(self):
        known = [e.cost_usd for e in self.events if e.cost_usd is not None]
        return sum(known), len(self.events) - len(known)


def call_event_attempt(event):
    """One UsageEvent as a pr_ai_call_events attempt (ids, counts and amounts only)."""
    refused = event.status in REFUSED
    cost, source = (0, "provider") if refused else (event.cost_usd_micro(), event.cost_source)
    return {"workspace_id": event.workspace_id, "feature": FEATURES.get(str(event.task).split(".", 1)[0], "growth"), "workload": event.task,
            "attempt_no": event.attempt_no or 1, "provider": (event.provider or "unknown") if event.cost_source == "provider" else "vercel-ai-gateway",
            "model": event.model, "route": event.route, "provider_request_id": event.generation_id, "status": STATUSES.get(event.status, "unknown"),
            "latency_ms": event.latency_ms, "input_tokens": 0 if refused else event.input_tokens, "output_tokens": 0 if refused else event.output_tokens,
            "cost_usd_micro": cost, "cost_source": source}


class PostgresUsageSink:
    """Writes to public.pr_model_usage_events using a cursor owned by the caller's transaction."""

    COLUMNS = ("workspace_id", "task", "stage", "model", "route", "provider", "generation_id", "input_tokens",
               "output_tokens", "cost_usd_micro", "cost_source", "latency_ms", "status", "subject")

    def __init__(self, cursor):
        self.cursor = cursor

    def record(self, event):
        # The all-feature attempt row first, under its own savepoint (never raises, never touches this transaction).
        try:
            ai_call_events.write_attempts({}, [call_event_attempt(event)], cursor=self.cursor)
        except Exception:  # noqa: BLE001 - recording never fails a growth write
            pass
        row = asdict(event)
        row["cost_usd_micro"] = event.cost_usd_micro()
        values = [row[c] for c in self.COLUMNS]
        placeholders = ",".join(["%s"] * len(self.COLUMNS))
        self.cursor.execute(f"INSERT INTO public.pr_model_usage_events({','.join(self.COLUMNS)}) VALUES({placeholders})", values)

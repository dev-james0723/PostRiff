"""Per-call AI usage and cost ledger for growth features (growth Phase 0).

Every model or evaluation attempt, successful or not, becomes one UsageEvent. Cost is the Gateway-reported
figure when present (`cost_source="gateway"`); otherwise it stays unknown (None), never zero. Events carry
opaque identifiers only (workspace id, subject hash), never prompt or post text.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from uuid import UUID

STATUSES_OK = ("ok",)
MAX_USD_MICRO = 2**63 - 1  # PostgreSQL signed bigint, shared by events/ledger/budgets.


def cost_usd_micro(cost):
    """A reported charge is known only when its rounded-up microdollars fit storage."""
    if type(cost) not in (int, float): return None
    try:
        if not math.isfinite(cost) or cost < 0: return None
        scaled = cost * 1_000_000
        if not math.isfinite(scaled): return None
        amount = math.ceil(scaled)
    except (ValueError, OverflowError):
        return None
    return amount if amount <= MAX_USD_MICRO else None


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

    def __post_init__(self):
        if cost_usd_micro(self.cost_usd) is None:
            object.__setattr__(self, 'cost_usd', None)
            object.__setattr__(self, 'cost_source', 'unknown')

    def cost_usd_micro(self):
        return cost_usd_micro(self.cost_usd)


class MemoryUsageSink:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)

    def total_usd(self):
        known = [e.cost_usd for e in self.events if e.cost_usd is not None]
        return sum(known), len(self.events) - len(known)


class PostgresUsageSink:
    """Writes to public.pr_model_usage_events using a cursor owned by the caller's transaction."""

    COLUMNS = ("workspace_id", "task", "stage", "model", "route", "provider", "generation_id", "input_tokens",
               "output_tokens", "cost_usd_micro", "cost_source", "latency_ms", "status", "subject")

    def __init__(self, cursor):
        self.cursor = cursor

    def record(self, event):
        row = asdict(event)
        row["cost_usd_micro"] = event.cost_usd_micro()
        values = [row[c] for c in self.COLUMNS]
        placeholders = ",".join(["%s"] * len(self.COLUMNS))
        sql = f"INSERT INTO public.pr_model_usage_events({','.join(self.COLUMNS)}) VALUES({placeholders})"
        try:
            UUID(str(event.workspace_id))
            scoped = True
        except (ValueError, TypeError):
            scoped = False
        if scoped:
            self.cursor.execute(sql + ' RETURNING id::text', values)
            row = self.cursor.fetchone()
            if row:
                from .. import pricing_events
                pricing_events.growth_usage(self.cursor, event, row[0])
        else:
            self.cursor.execute(sql, values)

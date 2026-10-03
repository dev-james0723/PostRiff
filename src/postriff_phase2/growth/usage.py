"""Per-call AI usage and cost ledger for growth features (growth Phase 0).

Every model or evaluation attempt, successful or not, becomes one UsageEvent. Cost is the Gateway-reported
figure when present (`cost_source="gateway"`); otherwise it stays unknown (None), never zero. Events carry
opaque identifiers only (workspace id, subject hash), never prompt or post text.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from uuid import UUID

STATUSES_OK = ("ok",)
MAX_USD_MICRO = 2**63 - 1  # PostgreSQL signed bigint, shared by events/ledger/budgets.


def _usd_micro(cost):
    # Decimal context is caller-local; never let a low precision round the invoice.
    with localcontext() as context:
        context.prec = max(28, len(cost.as_tuple().digits) + 6)
        return int((cost * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def _reported_cost_usd(cost):
    """Preserve the reported decimal value, under the existing known-cost domain."""
    if type(cost) not in (int, float): return None
    try:
        value = Decimal(str(cost))
        if not value.is_finite() or value < 0: return None
        return value if _usd_micro(value) <= MAX_USD_MICRO else None
    except (ValueError, OverflowError, InvalidOperation):
        return None


def cost_usd_micro(cost):
    """Per-attempt telemetry only; task settlement uses the raw-cost aggregate."""
    value = _reported_cost_usd(cost)
    return _usd_micro(value) if value is not None else None


def task_cost_basis(events):
    """Keep exact reported task USD alongside conservative audit microdollars.

    Unknown attempts keep the task unknown even when a known subtotal exists.
    Detail events remain independently rounded; they are never the debit basis.
    """
    values = [_reported_cost_usd(event.cost_usd) for event in events]
    known = [value for value in values if value is not None]
    unknown = len(known) != len(values)
    if not known: return 0, unknown, '0'
    # Retain even a subnormal positive charge beside a large storage-safe cost.
    # Enough digits for the full exponent range, carries, and USD-micro scaling.
    with localcontext() as context:
        context.prec = max(28, max(value.adjusted() for value in known)
                           - min(value.as_tuple().exponent for value in known)
                           + len(str(len(known))) + 7)
        exact = sum(known, Decimal(0))
        total = _usd_micro(exact)
    return total, unknown or total > MAX_USD_MICRO, str(exact)


def task_cost_usd_micro(events):
    total, unknown, _ = task_cost_basis(events)
    return total, unknown


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

"""Lane B — presentation accounting (spec §9; G13; A-DECISIONS D-A23, D-A39).

Every physical presenter attempt (the initial generation, its single automatic repair, an explicit retry or an explicit
edit) reserves its own hold on the existing usage ledger BEFORE the provider is called, and settles it exactly once:

- ledger key ``agent:{parentRunId}:ui:{attemptId}`` with ``run_id = parent run``: the ``agent`` prefix keeps the Founder
  feature attribution (LEDGER_FEATURES) and the parent run keeps the turn's lineage; no new ledger feature;
- the parent turn's credit authority is inherited (``AgentRuntimeService._reservation_approval``); a credit-mode workspace
  without one is refused by the ledger exactly like a text turn, never run unbilled;
- the combined admission plan: a presentation chain (initial + repair + explicit retries) must fit in the room the person's
  original turn left — its reserved ceiling minus its settled spend minus what earlier UI attempts used or still hold. An
  explicit edit is a new request with the same per-request allowance as the turn, shared only with its own repair. An
  unknown parent or attempt spend is never treated as zero: the presenter is refused (native answer, no call);
- no hidden retries: one reservation is one physical request (the presenter client uses ``max_retries=0``);
- settlement: known usage → ``completed`` at the priced cost; a provider refusal before any work (4xx/429) or an attempt
  that was never dispatched → ``failed``/0 (released); anything uncertain (timeout, 5xx, a cut stream, a cancel after
  dispatch, missing usage, an unpriced model) → ``unknown``, which keeps the hold until an operator reconciles it.

Column ownership on ``pr_ui_attempts`` (D-A39): this module is the only writer of ``reservation_id``, ``provider_attempts``,
``usage``, ``cost_usd_micro`` and ``cost_state``. ``ui_store`` (lane F) owns state, lease, checkpoint and source columns; its
``reap_expired`` calls :func:`settle_attempt` with ``usage={"costState": "unknown"}`` (runtime and auth may be None there).

Frozen entry points:
- reserve_attempt(runtime, cur, auth, artifact, attempt, route) -> dict  (raises AlphaError 402/429/503 -> native fallback, no call)
- settle_attempt(runtime, cur, auth, attempt, usage) -> dict            (idempotent; unknown keeps the hold, never assumed zero)

``route`` is the presenter's :class:`ui_presenter.PresentationPlan` (config route + deterministic cost ceiling + budget chain);
a plain ``config.Route`` is accepted when the caller passes ``ceiling_usd_micro``.
"""
from __future__ import annotations

import json
import os

from postriff_alpha.domain import AlphaError

RESERVE_VIA = "rafii_agent_ui"
RECORDED_FEATURE = "agent"           # pr_ai_call_events.feature: the founder AI views already count it
RECORDED_WORKLOAD = "ui_presenter"   # pr_ai_call_events.workload: presenter attempts apart from Manager spans
PRESENTATION_CHAIN = "presentation"
COST_STATES = ("none", "known", "unknown", "estimated")


def ledger_key(parent_run_id: str, attempt_id: str) -> str:
    return f"agent:{parent_run_id}:ui:{attempt_id}"


def parent_key(parent_run_id: str) -> str:
    return f"agent:{parent_run_id}"


def chain_for(kind: str, base_attempt_id: str | None = None) -> str:
    """The allowance an attempt draws on: the turn's presentation chain, or one explicit edit's own chain."""
    return f"edit:{base_attempt_id}" if kind == "edit" or (kind == "repair" and base_attempt_id) else PRESENTATION_CHAIN


def reason_for(error) -> str:
    """The stable REASON_CODES value of a refused reservation (the native answer stays; nothing was sent)."""
    code = getattr(error, "code", None)
    if code == "ui_ai_paused":
        return "disabled"
    if code == "ui_price_unknown":
        return "price_unknown"
    if getattr(error, "status", None) in (402, 403, 429, 503) or code in ("ui_budget", "ui_budget_unknown"):
        return "budget"
    return "internal_error"


# --- the combined admission plan -----------------------------------------------------------------------------------------
USAGE_ROWS_SQL = (
    "/* rafii-ui:usage_rows */ SELECT r.idempotency_key, r.estimated_usd_micro, "
    "(SELECT s.actual_usd_micro FROM public.pr_usage_ledger s WHERE s.workspace_id=r.workspace_id AND s.reservation_id=r.id "
    "AND s.cost_state IN ('actual','released') ORDER BY s.at LIMIT 1), "
    "EXISTS (SELECT 1 FROM public.pr_usage_ledger u WHERE u.workspace_id=r.workspace_id AND u.reservation_id=r.id AND u.cost_state='estimated_unknown'), "
    "coalesce(r.meta->>'chain','') "
    "FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' AND (r.idempotency_key=%s OR r.idempotency_key LIKE %s)")


def allowance(cur, workspace_id: str, parent_run_id: str, chain: str = PRESENTATION_CHAIN) -> dict:
    """{ceiling, parentSpent, chainUsed, room}: the room left for one more presenter attempt on `chain`. `room` is None when a
    figure it depends on is unknown (unknown is never zero) or the parent turn was not metered."""
    cur.execute(USAGE_ROWS_SQL, (workspace_id, parent_key(parent_run_id), parent_key(parent_run_id) + ":ui:%"))
    ceiling, parent_spent, used = None, None, 0
    for key, estimate, actual, _unknown, row_chain in cur.fetchall() or []:
        if key == parent_key(parent_run_id):
            ceiling, parent_spent = int(estimate or 0), (int(actual) if actual is not None else None)
            continue
        if (row_chain or PRESENTATION_CHAIN) != chain:
            continue
        # Settled: its actual. Held or settled unknown: the estimate stays committed until it is reconciled.
        used += int(actual) if actual is not None else int(estimate or 0)
    if ceiling is None:
        return {"ceiling": None, "parentSpent": None, "chainUsed": used, "room": None, "reason": "parent_unmetered"}
    if chain == PRESENTATION_CHAIN:
        if parent_spent is None:
            return {"ceiling": ceiling, "parentSpent": None, "chainUsed": used, "room": None, "reason": "parent_spend_unknown"}
        return {"ceiling": ceiling, "parentSpent": parent_spent, "chainUsed": used, "room": ceiling - parent_spent - used, "reason": None}
    return {"ceiling": ceiling, "parentSpent": parent_spent, "chainUsed": used, "room": ceiling - used, "reason": None}


# --- reserve ---------------------------------------------------------------------------------------------------------------
def _plan_figures(route, ceiling_usd_micro=None):
    inner = getattr(route, "route", None)
    config_route = inner if inner is not None else route
    ceiling = getattr(route, "ceiling_usd_micro", None) if ceiling_usd_micro is None else ceiling_usd_micro
    return config_route, ceiling, getattr(route, "chain", None) or PRESENTATION_CHAIN, getattr(route, "prompt_hash", None)


def reserve_attempt(runtime, cur, auth, artifact, attempt, route, *, ceiling_usd_micro=None) -> dict:
    """Reserve one physical presenter attempt inside the caller's short ui_transaction, before any provider dispatch.
    Raises AlphaError (402 budget, 503 paused/price) → the caller keeps the native answer and makes no call."""
    from .. import billing
    if billing.ai_paused():
        raise AlphaError("AI requests that cost money are paused by the operator. Nothing was sent or charged.", 503, code="ui_ai_paused")
    config_route, ceiling, chain, prompt_hash = _plan_figures(route, ceiling_usd_micro)
    if type(ceiling) is not int or ceiling <= 0:
        raise AlphaError("Configure a verified price for the presenter model before using generated views.", 503, code="ui_price_unknown")
    parent_run_id, attempt_id = str(artifact.get("runId") or ""), str(attempt.get("attemptId") or "")
    if not parent_run_id or not attempt_id:
        raise AlphaError("This presentation has no parent run.", 409, code="ui_parent_run")
    plan = allowance(cur, auth.workspace_id, parent_run_id, chain)
    if plan["room"] is None:
        raise AlphaError("The original request's cost isn't settled, so no interactive view was started. Your answer is unchanged.", 402, code="ui_budget_unknown")
    if ceiling > plan["room"]:
        raise AlphaError("This request's AI limit has no room left for an interactive view. Your answer is unchanged.", 402, code="ui_budget")
    approve = getattr(runtime, "_reservation_approval", None)
    authority, extra_meta = (approve(cur, auth.workspace_id, auth.principal, auth.workspace_revision, ceiling, config_route, parent_run_id)
                             if callable(approve) else (None, {}))
    meta = {"via": RESERVE_VIA, "attemptId": attempt_id, "artifactId": artifact.get("artifactId"), "kind": attempt.get("kind"), "chain": chain,
            "parentRunId": parent_run_id, **({"promptHash": prompt_hash} if prompt_hash else {}), **(extra_meta or {})}
    reservation = runtime.service.ledger.reserve(cur, auth.workspace_id, auth.principal, "text_model", ceiling, ledger_key(parent_run_id, attempt_id),
                                                 charge_batch=False, provider=getattr(config_route, "provider", None) or "",
                                                 model=getattr(config_route, "model", None) or "", run_id=parent_run_id, credit_authority=authority, meta=meta)
    cur.execute("/* rafii-ui:attempt_reserved */ UPDATE public.pr_ui_attempts SET reservation_id=%s,provider_attempts=1,updated_at=now() "
                "WHERE id::text=%s AND workspace_id=%s", (reservation["reservationId"], attempt_id, auth.workspace_id))
    return {**reservation, "estimateUsdMicro": ceiling, "key": ledger_key(parent_run_id, attempt_id), "chain": chain, "room": plan["room"]}


# --- settle ----------------------------------------------------------------------------------------------------------------
ATTEMPT_ROW_SQL = ("/* rafii-ui:attempt_accounting */ SELECT a.reservation_id, a.kind, x.parent_run_id::text, x.actor::text "
                   "FROM public.pr_ui_attempts a JOIN public.pr_ui_artifacts x ON x.id=a.artifact_id WHERE a.id::text=%s AND a.workspace_id=%s")


def _count(value):
    return value if type(value) is int and value >= 0 else None


def outcome_of(cfg, usage: dict) -> tuple[str, int | None, str]:
    """(ledger outcome, actual micro-USD, cost state) of one attempt's usage record."""
    usage = usage or {}
    if usage.get("costState") == "unknown":
        return "unknown", None, "unknown"
    if usage.get("dispatched") is False or usage.get("status") == "refused":
        return "failed", 0, "none"          # never sent, or refused before any work (4xx/429): the hold is released
    if usage.get("known"):
        given = _count(usage.get("costUsdMicro"))
        if given is not None:
            return "completed", given, "known"
        model, inp, out = usage.get("model"), _count(usage.get("inputTokens")), _count(usage.get("outputTokens"))
        cost = cfg.estimate_usd_micro(model, inp, out) if cfg is not None and model and inp is not None and out is not None else None
        if cost is not None:
            return "completed", cost, "known"
    return "unknown", None, "unknown"


def _call_row(cfg, usage: dict, outcome: str, cost, attempt_id: str) -> dict:
    """One content-free pr_ai_call_events attempt: ids, enums, counts and amounts only."""
    from .. import ai_call_events
    from .manager import price_version
    status = {"refused": "failed", "incomplete": "ok"}.get(usage.get("status"), usage.get("status"))
    if status not in ai_call_events.STATUSES or (outcome == "unknown" and status == "ok"):
        status = "unknown"
    row = {"workload": RECORDED_WORKLOAD, "model": usage.get("model"), "provider": usage.get("provider"), "status": status,
           "http_status": usage.get("httpStatus"), "latency_ms": usage.get("latencyMs"), "started_at": usage.get("startedAt"),
           "provider_request_id": usage.get("requestId"), "physical_attempt_id": f"{attempt_id}:p1"}
    if outcome == "completed":
        computed, source, _ = ai_call_events.table_cost(cost, price_version(cfg, usage.get("model")) if cfg is not None else None)
        row.update(input_tokens=usage.get("inputTokens"), output_tokens=usage.get("outputTokens"), cached_input_tokens=usage.get("cachedTokens"),
                   reasoning_tokens=usage.get("reasoningTokens"), cost_usd_micro=computed, cost_source=source)
    elif outcome == "failed":
        row.update(input_tokens=0, output_tokens=0, cached_input_tokens=0, reasoning_tokens=0, cost_usd_micro=0, cost_source="provider")
    return row


def _ledger(runtime):
    ledger = getattr(getattr(runtime, "service", None), "ledger", None)
    if ledger is not None:
        return ledger
    from .. import billing
    return billing.Ledger(credits_enabled=os.environ.get("POSTRIFF_CREDITS_ENABLED") == "1")


def settle_attempt(runtime, cur, auth, attempt, usage) -> dict:
    """Settle one attempt's reservation exactly once, then record its accounting columns and its pr_ai_call_events row.
    Idempotent: the ledger's terminal states win, the call event is deduplicated, the columns are rewritten with the same
    values. `runtime` and `auth` may be None (lane F's lease reaper): the ledger and the owner then come from the row."""
    attempt = attempt or {}
    attempt_id = str(attempt.get("attemptId") or attempt.get("id") or "")
    workspace_id = getattr(auth, "workspace_id", None) or attempt.get("workspaceId")
    if not attempt_id or not workspace_id:
        raise AlphaError("Attempt unavailable.", 404, code="ui_attempt")
    cur.execute(ATTEMPT_ROW_SQL, (attempt_id, workspace_id))
    row = cur.fetchone()
    if not row:
        raise AlphaError("Attempt unavailable.", 404, code="ui_attempt")
    reservation_id, _kind, parent_run_id, actor = row
    reservation_id = reservation_id or attempt.get("reservationId")
    cfg = getattr(runtime, "cfg", None)
    usage = dict(usage or {})
    outcome, cost, cost_state = outcome_of(cfg, usage)
    if not reservation_id:
        # Refused at admission: never reserved, never dispatched; nothing to settle.
        _write_columns(cur, workspace_id, attempt_id, usage, None, "none")
        return {"outcome": "none", "costUsdMicro": None, "costState": "none", "reservationId": None}
    settled = _ledger(runtime).settle(cur, workspace_id, reservation_id, outcome, cost)
    _write_columns(cur, workspace_id, attempt_id, usage, cost, cost_state)
    if not (outcome == "failed" and usage.get("dispatched") is False):
        try:
            from .. import ai_call_events
            base = {"workspace_id": workspace_id, "user_id": getattr(auth, "principal", None) or actor, "feature": RECORDED_FEATURE,
                    "run_id": parent_run_id, "reservation_id": reservation_id}
            ai_call_events.write_attempts(base, [_call_row(cfg, usage, outcome, cost, attempt_id)], cursor=cur)
        except Exception:  # noqa: BLE001 — recording never undoes a settlement
            pass
    return {"outcome": outcome, "costUsdMicro": cost, "costState": cost_state, "reservationId": reservation_id,
            "ledger": settled.get("state") if isinstance(settled, dict) else None}


_USAGE_KEYS = ("status", "known", "dispatched", "model", "provider", "inputTokens", "outputTokens", "cachedTokens", "reasoningTokens", "latencyMs",
               "requestId", "httpStatus", "incomplete", "finishReason")


def _write_columns(cur, workspace_id, attempt_id, usage, cost, cost_state):
    safe = {k: (usage[k][:200] if isinstance(usage[k], str) else usage[k]) for k in _USAGE_KEYS
            if k in usage and (usage[k] is None or isinstance(usage[k], (bool, int, float, str)))}
    cur.execute("/* rafii-ui:attempt_usage */ UPDATE public.pr_ui_attempts SET usage=%s::jsonb,cost_usd_micro=%s,cost_state=%s,updated_at=now() "
                "WHERE id::text=%s AND workspace_id=%s", (json.dumps(safe, sort_keys=True), cost, cost_state, attempt_id, workspace_id))


# --- orphaned holds ------------------------------------------------------------------------------------------------------
ORPHAN_GRACE_SECONDS = 150   # > the producer lease (generation timeout + 30 s) + finalize time
ORPHAN_SQL = ("/* rafii-ui:orphan_holds */ SELECT t.id::text, t.reservation_id FROM public.pr_ui_attempts t WHERE t.workspace_id=%s "
              "AND t.reservation_id IS NOT NULL AND t.state NOT IN ('queued','streaming','validating') "
              "AND coalesce(t.finished_at, t.updated_at) < now() - make_interval(secs => %s) "
              "AND NOT EXISTS (SELECT 1 FROM public.pr_usage_ledger s WHERE s.workspace_id=t.workspace_id AND s.reservation_id::text=t.reservation_id "
              "AND s.kind IN ('settle','release')) ORDER BY t.updated_at LIMIT 20")


def settle_orphans(runtime, cur, workspace_id) -> int:
    """A terminal attempt whose producer died before settling (for example canceled by the person, then the function was killed)
    keeps an open hold that no lease reaper sees. Book each as `unknown`: the hold stays until reconciled, never zero, never an
    estimate. Called at admission inside the caller's transaction (workspace row locked)."""
    cur.execute(ORPHAN_SQL, (workspace_id, ORPHAN_GRACE_SECONDS))
    rows = cur.fetchall() or []
    for attempt_id, reservation_id in rows:
        _ledger(runtime).settle(cur, workspace_id, reservation_id, "unknown")
        cur.execute("/* rafii-ui:attempt_usage_state */ UPDATE public.pr_ui_attempts SET cost_state='unknown', updated_at=now() WHERE id::text=%s AND workspace_id=%s",
                    (attempt_id, workspace_id))
    return len(rows)

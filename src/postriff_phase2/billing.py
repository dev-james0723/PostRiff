"""Entitlements, append-only usage ledger with reserve/settle/release, budgets, and billing
webhooks behind a provider interface (architecture §17; improvement SPEC §6).

Nothing here charges money. `FixturePaymentProvider` is labelled fixture; a live provider
is a separate, authorized selection. Prices come from versioned `pr_plan_terms` rows whose
status is 'proposed' until an explicit commercial decision.
"""
import hashlib
import hmac
import json
from . import pricing_events
import math
import os
import time
from postriff_alpha.domain import AlphaError
from .contracts import digest
from .credit_meter import SUPPORTED_POLICY_VERSIONS, V2_POLICY_VERSION
from .credit_wallet import CreditBook, project_credit_wallet
from .developer_usage import ai_usage_exempt
from .plan_pricing import DEFAULT_VARIANT, PlanPricing
from .growth.usage import MAX_USD_MICRO

USD = 1_000_000  # micro-dollars


def plan_display_label(label):
    """The plan name a customer sees. A trailing parenthetical on a `pr_plan_terms` label is an internal
    note ("Studio Assist (bounded-batch experiment)"): the row keeps it, customer copy never shows it."""
    text = (label or "").strip()
    if text.endswith(")") and "(" in text:
        shown = text[: text.rindex("(")].strip()
        if shown:
            return shown
    return text or "Rafii"


def customer_entitlements(raw):
    """Catalog limits only; operator/provider fields never cross the customer boundary."""
    limits = ('writingBatches', 'mediaCredits', 'members', 'connectedAccounts', 'brands', 'storageMb', 'monthlyCredits')
    shown = {key: raw[key] for key in limits if type(raw.get(key)) is int and raw[key] >= 0}
    if isinstance(raw.get('creditPolicy'), str) and raw['creditPolicy'] in SUPPORTED_POLICY_VERSIONS:
        shown['creditPolicy'] = raw['creditPolicy']
    if raw.get('overage') == 'stop':
        shown['overage'] = 'stop'
    return shown

# Candidate ceilings from improvement SPEC §6 — "待價格與品質評估修正的候選上限", flagged 'candidate' in data.
CANDIDATE_BUDGETS = {
    "global": {"window_kind": "day", "warn": 5 * USD, "stop": 10 * USD},
    "workspace": {"window_kind": "month", "warn": 4 * USD, "stop": 6 * USD},
}
DEFAULT_RESERVE_TEXT = USD // 2  # $0.50 per batch (SPEC §6)

# Launch budget policies (provider cost in USD, not customer prices). An operator turns one on per deployment with
# POSTRIFF_BUDGET_POLICY=<id>: its budgets are approved with these caps, and the per-person and per-request limits
# apply. Without a policy every budget stays 'candidate' and paid requests are refused (402), as before. A budget an
# owner approved with other caps keeps them. Basis: docs/launch-20260923/BUDGET-AND-PRICING.md.
BUDGET_POLICIES = {
    # While real charges are off (no revenue), every paid call is the operator's cost: keep the month under US$100.
    "launch-2026-09-24": {
        "global": {"window_kind": "day", "warn": 5 * USD, "stop": 10 * USD},
        "global-month": {"window_kind": "month", "warn": 60 * USD, "stop": 100 * USD},
        "workspace": {"window_kind": "month", "warn": 6 * USD, "stop": 10 * USD},
        "personDayStop": 3 * USD,    # one person, all workspaces, rolling 24 hours
        "requestMax": 1 * USD,       # one reservation's worst case
    },
    # Once live charges are on: a workspace can use its plan's monthly credits (8,000 credits ≈ US$27 of provider cost).
    "paid-2026-09-24": {
        "global": {"window_kind": "day", "warn": 25 * USD, "stop": 50 * USD},
        "global-month": {"window_kind": "month", "warn": 300 * USD, "stop": 500 * USD},
        "workspace": {"window_kind": "month", "warn": 30 * USD, "stop": 40 * USD},
        "personDayStop": 5 * USD,
        "requestMax": 2 * USD,
    },
}


def active_budget_policy():
    """The operator-selected policy, or None. An unknown id refuses paid work rather than guessing."""
    name = os.environ.get("POSTRIFF_BUDGET_POLICY")
    if not name:
        return None
    if name not in BUDGET_POLICIES:
        raise AlphaError("Paid AI requests are off: POSTRIFF_BUDGET_POLICY names no known policy.", 503)
    return {"id": name, **BUDGET_POLICIES[name]}


def ai_paused():
    """Operator kill switch for everything that costs provider money (POSTRIFF_AI_PAUSED=1)."""
    return os.environ.get("POSTRIFF_AI_PAUSED") == "1"


def _budget_key(scope):
    return scope if scope in ("global", "global-month") else "workspace"


def _stop_message(scope, stop):
    if scope == "workspace":
        return (f"This workspace has reached its AI spending limit for this month (US${stop / USD:.2f} of provider cost). "
                "Nothing was sent or charged. Drafts, edits and publishing still work; new AI drafts resume next month or when the limit is raised.")
    period = "today (UTC)" if scope == "global" else "this month"
    return f"Rafii has reached its AI safety limit for {period}. Nothing was sent or charged; new AI drafts resume when the period ends."


def _window_start_sql(kind):
    return "date_trunc('day', now())" if kind == "day" else "date_trunc('month', now())"


class Ledger:
    """All methods take an open cursor inside the caller's transaction (workspace row locked)."""

    def __init__(self, credits_enabled=False, clock=time.time, pricing_v2_enabled=False):
        self.clock, self.pricing_v2_enabled = clock, pricing_v2_enabled
        self._credit_book = CreditBook(clock)
        self.credits = self._credit_book if credits_enabled else None

    def _budget(self, cur, scope, kind=None, policy=None, *, approve_candidate=True):
        spec = (policy or {}).get(_budget_key(scope)) or CANDIDATE_BUDGETS[_budget_key(scope)]
        cur.execute(f"INSERT INTO public.pr_budgets(scope,window_kind,window_start,warn_usd_micro,stop_usd_micro,status) VALUES(%s,%s,{_window_start_sql(spec['window_kind'])},%s,%s,%s) ON CONFLICT(scope) DO NOTHING", (scope, spec["window_kind"], spec["warn"], spec["stop"], "approved" if policy else "candidate"))
        if policy and approve_candidate:
            # The policy approves a budget still waiting for a decision, with the policy's caps; one already approved keeps its caps.
            cur.execute("UPDATE public.pr_budgets SET status='approved',window_kind=%s,warn_usd_micro=%s,stop_usd_micro=%s,updated_at=now() WHERE scope=%s AND status='candidate'", (spec["window_kind"], spec["warn"], spec["stop"], scope))
        cur.execute("SELECT window_kind,window_start,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,status FROM public.pr_budgets WHERE scope=%s FOR UPDATE", (scope,))
        row = cur.fetchone()
        # Outstanding/unknown reservations survive a calendar boundary.
        cur.execute(f"UPDATE public.pr_budgets SET window_start={_window_start_sql(row[0])},spent_usd_micro=0,updated_at=now() WHERE scope=%s AND window_start < {_window_start_sql(row[0])} RETURNING 1", (scope,))
        if cur.fetchone():
            cur.execute("SELECT window_kind,window_start,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,status FROM public.pr_budgets WHERE scope=%s", (scope,))
            row = cur.fetchone()
        return {"windowKind": row[0], "warn": row[2], "stop": row[3], "spent": row[4], "reserved": row[5], "status": row[6]}

    @staticmethod
    def _person_day(cur, member_id):
        """Provider cost one person started in the last 24 hours, across workspaces: actual where known, else the hold."""
        cur.execute(
            "SELECT coalesce(sum(coalesce((SELECT s.actual_usd_micro FROM public.pr_usage_ledger s WHERE s.workspace_id=r.workspace_id "
            "AND s.reservation_id=r.id AND s.cost_state IN ('actual','released') LIMIT 1), r.estimated_usd_micro)),0) "
            "FROM public.pr_usage_ledger r WHERE r.member_id=%s AND r.kind='reserve' AND r.at > now() - interval '24 hours'", (member_id,))
        return int(cur.fetchone()[0])

    def ensure_entitlement(self, cur, workspace_id, plan):
        from .free_lifecycle import lifecycle
        lifecycle(cur, workspace_id, self.clock(), pricing_v2_enabled=self.pricing_v2_enabled)
        cur.execute("SELECT plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,extract(epoch from resets_at),source,version FROM public.pr_entitlements WHERE workspace_id=%s FOR UPDATE", (workspace_id,))
        row = cur.fetchone()
        if row:
            return {"planTermsId": row[0], "writingBatchesRemaining": row[1], "mediaCreditsRemaining": row[2], "connectedAccounts": row[3], "members": row[4], "storageMb": row[5], "resetsAt": float(row[6]) if row[6] else None, "source": row[7], "version": row[8]}
        # First use: derive from the trial terms (the only entitlement a workspace has before a live subscription).
        cur.execute("SELECT id,entitlements FROM public.pr_plan_terms WHERE plan='trial' ORDER BY version DESC LIMIT 1")
        terms_id, ent = cur.fetchone()
        cur.execute("SELECT extract(epoch from t.expires_at) FROM public.pr_trials t WHERE t.workspace_id=%s", (workspace_id,))
        trial = cur.fetchone()
        resets = float(trial[0]) if trial and trial[0] else None
        # A concurrent first use may insert the same row; the loser waits, then re-reads the winner's row.
        cur.execute("INSERT INTO public.pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,resets_at,source) VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),'trial') ON CONFLICT(workspace_id) DO NOTHING", (workspace_id, terms_id, ent["writingBatches"], ent["mediaCredits"], ent["connectedAccounts"], ent["members"], ent["storageMb"], resets))
        cur.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,%s,'trial',to_timestamp(%s)) ON CONFLICT(workspace_id) DO NOTHING", (workspace_id, terms_id, resets))
        return self.ensure_entitlement(cur, workspace_id, plan)

    def growth_mode(self, cur, workspace_id):
        """Effective server entitlement, never a client plan/classification or quota exemption."""
        cur.execute("SELECT p.plan,p.entitlements->>'creditPolicy' FROM public.pr_entitlements e JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id WHERE e.workspace_id=%s", (workspace_id,))
        row = cur.fetchone()
        if row and row[0] == 'free': return 'free'
        if row and row[1] == V2_POLICY_VERSION: return 'managed_credits'
        return 'legacy'

    def reserve(self, cur, workspace_id, member_id, dimension, estimated_usd_micro, idempotency_key, *, charge_batch, provider="", model="", run_id=None, job_id=None, meta=None, credit_authority=None, platform_preview=None):
        """Lock budgets → check ceilings and entitlement → insert reservation → return it. Same key returns the same row."""
        if dimension not in ("text_model", "image_generation", "tool", "storage", "action") or type(estimated_usd_micro) is not int or estimated_usd_micro < 0:
            raise AlphaError("Invalid usage reservation.", 400)
        if self.credits:
            cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        entitlement = self.ensure_entitlement(cur, workspace_id, None)
        preview = platform_preview
        if preview is not None:
            from .growth.preview import PreviewAuthority, unavailable
            if not isinstance(preview, PreviewAuthority): raise unavailable()
            preview.validate(cur, workspace_id, dimension, estimated_usd_micro, provider, model, run_id, charge_batch)
        exempt = ai_usage_exempt(member_id) and preview is None
        if preview is None and entitlement["planTermsId"] == "free-v1" and (estimated_usd_micro > 0 or (charge_batch and not exempt)):
            raise AlphaError("Free has no managed writing allowance. Drafts, edits and exports remain available.", 402, code="free_managed_writing_unavailable")
        fingerprint = digest({"dimension": dimension, "estimate": estimated_usd_micro, "chargeBatch": charge_batch, "provider": provider, "model": model, **({"platformPreview":preview.record()} if preview else {})})
        cur.execute("SELECT id::text,reservation_id::text,meta FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, idempotency_key))
        existing = cur.fetchone()
        if existing:
            if (existing[2] or {}).get("fingerprint") != fingerprint:
                raise AlphaError("This usage key belongs to a different operation.", 409)
            return {"reservationId": existing[1] or existing[0], "duplicate": True}
        policy = active_budget_policy() if estimated_usd_micro > 0 and preview is None else None
        if estimated_usd_micro > 0 and ai_paused():
            raise AlphaError("AI requests that cost money are paused by the operator. Nothing was sent or charged; drafts, edits and publishing still work.", 503)
        if policy and not exempt and estimated_usd_micro > policy["requestMax"]:
            raise AlphaError(f"This request could cost up to US${estimated_usd_micro / USD:.2f} of provider time, over the US${policy['requestMax'] / USD:.2f} "
                             "limit for one request. Nothing was sent; select fewer sources, a lighter model or quicker reasoning.", 402)
        if not preview and not exempt and self.credits is None and (charge_batch or estimated_usd_micro > 0):
            cur.execute("SELECT entitlements->>'creditPolicy' FROM public.pr_plan_terms WHERE id=%s", (entitlement["planTermsId"],))
            plan_policy = cur.fetchone()
            if plan_policy and plan_policy[0]:
                raise AlphaError("Credit billing is paused; no provider request was made.", 503)
        credit = self.credits.prepare(cur, workspace_id, member_id, estimated_usd_micro, model, provider, credit_authority) if not preview and not exempt and self.credits and (charge_batch or estimated_usd_micro > 0) else None
        if credit or exempt: charge_batch = False
        cur.execute("SELECT count(*) FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' AND r.charge_batch AND NOT EXISTS (SELECT 1 FROM public.pr_usage_ledger s WHERE s.workspace_id=r.workspace_id AND s.reservation_id=r.id AND s.cost_state IN ('actual','released'))", (workspace_id,))
        pending_batches = cur.fetchone()[0]
        if charge_batch and entitlement["writingBatchesRemaining"] <= pending_batches:
            raise AlphaError("No writing allowance left in this plan. Drafts, exports and reviews remain available; overage is not charged silently.", 402)
        if not exempt and not credit and dimension == "image_generation" and entitlement["mediaCreditsRemaining"] <= 0:
            raise AlphaError("No media credits left in this plan.", 402)
        if policy and member_id and not exempt:
            used = self._person_day(cur, member_id)
            if used + estimated_usd_micro > policy["personDayStop"]:
                raise AlphaError(f"You have reached the AI spending limit for one person over 24 hours (US${policy['personDayStop'] / USD:.2f} of provider cost). "
                                 "Nothing was sent or charged; it frees up as the day's earlier requests age out. Drafts, edits and publishing still work.", 402)
        scopes = [("workspace", f"workspace:{workspace_id}", "month"), ("global", "global", "day")] + ([("global-month", "global-month", "month")] if policy else [])
        if preview:
            from .growth.preview import SCOPES
            scopes = [('platform', SCOPES[0], 'day'), ('platform', SCOPES[1], 'month')]
            budgets = [(label, scope, self._budget(cur, scope, kind, {'workspace': {'window_kind':kind,
                       'warn':stop, 'stop':stop}}, approve_candidate=False)) for (label, scope, kind), stop in zip(scopes,
                       (preview.policy.dailyUsdMicro, preview.policy.monthlyUsdMicro))]
            # An older approved budget can only tighten the currently approved preview policy.
            for (_, _, budget), stop in zip(budgets, (preview.policy.dailyUsdMicro, preview.policy.monthlyUsdMicro)):
                budget['stop'] = min(budget['stop'], stop)
        else:
            budgets = [(label, scope, self._budget(cur, scope, kind, policy)) for label, scope, kind in scopes]
        for label, _, budget in budgets:
            if estimated_usd_micro > 0 and budget['status'] != 'approved':
                raise AlphaError("Paid AI drafting is not switched on yet. Nothing was sent or charged.", 402)
            if not exempt and budget["spent"] + budget["reserved"] + estimated_usd_micro > budget["stop"]:
                raise AlphaError(_stop_message(label, budget["stop"]), 402)
        # Developer costs remain in the immutable ledger, without consuming other
        # members' shared budgets or plan allowances.
        charged = [] if exempt else [scope for _, scope, _ in budgets]
        cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,run_id,job_id,kind,dimension,provider,model,estimated_usd_micro,cost_state,charge_batch,idempotency_key,meta) VALUES(%s,%s,%s,%s,'reserve',%s,%s,%s,%s,'estimated',%s,%s,%s::jsonb) RETURNING id::text", (workspace_id, member_id, run_id, job_id, dimension, provider, model, estimated_usd_micro, charge_batch, idempotency_key, json.dumps({**{k:v for k,v in (meta or {}).items() if k not in ("credits", "budgetScopes", "aiUsageExempt", "platformPreview")}, "fingerprint": fingerprint, "budgetScopes": charged, **({"platformPreview":preview.record(),"userCreditDebit":0} if preview else {}), **({"aiUsageExempt": True} if exempt else {}), **({"credits":credit} if credit else {})})))
        reservation_id = cur.fetchone()[0]
        if credit: self.credits.claim(cur, workspace_id, reservation_id, credit)
        cur.execute("UPDATE public.pr_usage_ledger SET reservation_id=id WHERE id::text=%s", (reservation_id,))
        for scope in charged:
            cur.execute("UPDATE public.pr_budgets SET reserved_usd_micro=reserved_usd_micro+%s,updated_at=now() WHERE scope=%s", (estimated_usd_micro, scope))
        warnings = [f"{label} budget past its warning line" for label, _, b in budgets if not exempt and b["spent"] + b["reserved"] + estimated_usd_micro > b["warn"]]
        crossed = [label for label, _, b in budgets if not exempt and b["spent"] + b["reserved"] <= b["warn"] < b["spent"] + b["reserved"] + estimated_usd_micro]
        if crossed:
            # Operators' signal in the function logs (no workspace or person identifiers): a warning line was just crossed.
            print(json.dumps({"event": "budget.warning_crossed", "scopes": crossed, "policy": (policy or {}).get("id")}), flush=True)
        return {"reservationId": reservation_id, "duplicate": False, "warnings": warnings, "entitlement": entitlement}

    def revalidate_preview(self, cur, workspace_id, reservation_id, preview):
        """Recheck the original hold and current shared approval under short locks, before each I/O."""
        from .growth.preview import unavailable, SCOPES
        preview.validate(cur, workspace_id, 'tool', preview.maximum_micro, preview.policy.provider,
                         preview.policy.model, preview.run_id, False)
        cur.execute("SELECT dimension,estimated_usd_micro,charge_batch,provider,model,run_id::text,meta FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve' FOR UPDATE", (workspace_id, reservation_id))
        original = cur.fetchone()
        if (not original or original[:6] != ('tool', preview.maximum_micro, False, preview.policy.provider,
                preview.policy.model, preview.run_id) or original[6].get('platformPreview') != preview.record()
                or original[6].get('budgetScopes') != list(SCOPES)):
            raise unavailable()
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release') LIMIT 1", (workspace_id, reservation_id))
        if cur.fetchone(): raise unavailable()
        for scope, kind, cap in zip(SCOPES, ('day','month'), (preview.policy.dailyUsdMicro, preview.policy.monthlyUsdMicro)):
            cur.execute("SELECT status,window_kind,stop_usd_micro,reserved_usd_micro,CASE WHEN window_start>=date_trunc(window_kind,now()) THEN spent_usd_micro ELSE 0 END FROM public.pr_budgets WHERE scope=%s FOR UPDATE", (scope,))
            budget = cur.fetchone()
            if (not budget or budget[0] != 'approved' or budget[1] != kind
                    or budget[3] < preview.maximum_micro or budget[3]+budget[4] > min(budget[2],cap)):
                raise unavailable()

    def settle(self, cur, workspace_id, reservation_id, outcome, actual_usd_micro=None, idempotency_key=None):
        """completed → actual cost, batch consumed; failed → provider cost still booked, batch refunded;
        unknown → reservation kept and cost booked as estimated_unknown until reconciled."""
        if outcome not in ("completed", "failed", "unknown"):
            raise AlphaError("Invalid settlement outcome.", 400)
        if actual_usd_micro is not None and (type(actual_usd_micro) is not int or actual_usd_micro < 0):
            raise AlphaError("Invalid actual usage amount.", 400)
        cur.execute("SELECT meta FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve'", (workspace_id, reservation_id))
        original = cur.fetchone()
        uses_credits = bool(original and original[0].get("credits"))
        meta = (original[0] or {}) if original else {}
        # Platform usage without verified cost retains its reservation too.
        if actual_usd_micro is None and (meta.get("platformPreview") or meta.get("aiUsageExempt")):
            outcome = "unknown"
        if uses_credits:
            cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
            if actual_usd_micro is None:
                outcome = "unknown"
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("pr_ledger:" + str(reservation_id),))
        # A release or known settlement is terminal for the reservation, even if
        # another caller supplies a different outcome/idempotency key.
        cur.execute("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND cost_state IN ('actual','released') LIMIT 1", (workspace_id, reservation_id))
        terminal = cur.fetchone()
        if terminal:
            return {"reservationId": reservation_id, "duplicate": True, "state": terminal[0]}
        cur.execute("SELECT dimension,estimated_usd_micro,charge_batch,provider,model,run_id,job_id,member_id FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve'", (workspace_id, reservation_id))
        reservation = cur.fetchone()
        if not reservation:
            raise AlphaError("Reservation unavailable.", 404)
        dimension, estimate, charge_batch, provider, model, run_id, job_id, member_id = reservation
        # Individual events may fit while their sum, or the budget total, cannot fit bigint.
        # Retain the original hold and record unknown instead of rolling back all accounting.
        scopes = (original[0] or {}).get("budgetScopes") if original else None
        if scopes is None:
            scopes = [f"workspace:{workspace_id}", "global"]
        if actual_usd_micro is not None and actual_usd_micro > MAX_USD_MICRO:
            outcome = "unknown"
        if outcome != "unknown":
            actual = int(actual_usd_micro or 0)
            for scope in scopes:
                cur.execute("SELECT spent_usd_micro FROM public.pr_budgets WHERE scope=%s FOR UPDATE", (scope,))
                budget = cur.fetchone()
                if budget and budget[0] + actual > MAX_USD_MICRO:
                    outcome = "unknown"
                    break
        key = idempotency_key or f"settle:{reservation_id}:{outcome}"
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
        if cur.fetchone():
            return {"reservationId": reservation_id, "duplicate": True}
        if outcome == "unknown":
            cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,run_id,job_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,charge_batch,idempotency_key) VALUES(%s,%s,%s,%s,%s,'settle',%s,%s,%s,%s,NULL,'estimated_unknown',%s,%s)", (workspace_id, member_id, run_id, job_id, reservation_id, dimension, provider, model, estimate, charge_batch, key))
            pricing_events.settled(cur, workspace_id, reservation_id, 'unknown', None, meta.get('credits'), None, meta)
            return {"reservationId": reservation_id, "state": "estimated_unknown", "note": "Reservation retained until provider usage is reconciled; cost is not recorded as zero."}
        actual = int(actual_usd_micro or 0)
        credit = self._credit_book.settlement(cur, workspace_id, reservation_id, outcome, actual) if uses_credits else None
        if credit and credit.get("absorbed"):
            # Retain the surviving Task10–11 operator audit alongside private metrics.
            cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,NULL,'usage.absorbed_over_max',%s,%s::jsonb)",
                        (workspace_id, str(reservation_id)[:200], json.dumps({"absorbedMilliCredits": credit["absorbed"], "usedMilliCredits": credit["used"]})))
        kind = "settle" if outcome == "completed" else "release"
        cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,run_id,job_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,charge_batch,idempotency_key,meta) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)", (workspace_id, member_id, run_id, job_id, reservation_id, kind, dimension, provider, model, estimate, actual, "actual" if outcome == "completed" else "released", charge_batch, key, json.dumps({"credits":credit} if credit else {})))
        pricing_events.settled(cur, workspace_id, reservation_id, outcome, actual, meta.get('credits'), credit, meta)
        # Exactly the budgets this reservation held, already locked/checked above.
        for scope in scopes:
            cur.execute("UPDATE public.pr_budgets SET reserved_usd_micro=greatest(reserved_usd_micro-%s,0),spent_usd_micro=spent_usd_micro+%s,updated_at=now() WHERE scope=%s", (estimate, actual, scope))
        if outcome == "completed" and charge_batch:
            column = "media_credits_remaining" if dimension == "image_generation" else "writing_batches_remaining"
            cur.execute(f"UPDATE public.pr_entitlements SET {column}=greatest({column}-1,0),version=version+1,updated_at=now() WHERE workspace_id=%s", (workspace_id,))
        return {"reservationId": reservation_id, "state": "actual" if outcome == "completed" else "released", "actualUsdMicro": actual}

    def unknown_reservations(self, cur, workspace_id=None, limit=100):
        """Reservations still waiting for provider usage: settled as unknown, never finalized."""
        cur.execute(
            "SELECT u.workspace_id::text,u.reservation_id::text,u.run_id::text,u.provider,u.model,u.estimated_usd_micro,extract(epoch from u.at),"
            "(SELECT r.status FROM public.pr_agent_runs r WHERE r.id=u.run_id) "
            "FROM public.pr_usage_ledger u WHERE u.cost_state='estimated_unknown' AND (%s::uuid IS NULL OR u.workspace_id=%s::uuid) "
            "AND NOT EXISTS (SELECT 1 FROM public.pr_usage_ledger t WHERE t.workspace_id=u.workspace_id AND t.reservation_id=u.reservation_id AND t.cost_state IN ('actual','released')) "
            "ORDER BY u.at LIMIT %s", (workspace_id, workspace_id, int(limit)))
        return [{"workspaceId": r[0], "reservationId": r[1], "runId": r[2], "provider": r[3], "model": r[4], "estimatedUsdMicro": r[5], "since": float(r[6]), "runStatus": r[7]} for r in cur.fetchall()]

    def reconcile_unknown(self, cur, workspace_id, reservation_id, outcome, actual_usd_micro, *, operator, evidence):
        """Finalize one unknown reservation from provider evidence, once. `failed` never charges the customer;
        `completed` charges the actual cost within the amount they approved. Both book the provider cost."""
        if outcome not in ("completed", "failed"):
            raise AlphaError("Reconcile to completed or failed.", 400)
        if type(actual_usd_micro) is not int or actual_usd_micro < 0:
            raise AlphaError("Record the actual provider cost in micro-dollars.", 400)
        if not isinstance(operator, str) or not operator.strip() or not isinstance(evidence, str) or not evidence.strip():
            raise AlphaError("Name the operator and the provider evidence (for example a gateway request id).", 400)
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND cost_state='estimated_unknown'", (workspace_id, reservation_id))
        if not cur.fetchone():
            raise AlphaError("This reservation is not waiting for reconciliation.", 409)
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND cost_state IN ('actual','released')", (workspace_id, reservation_id))
        if cur.fetchone():
            raise AlphaError("This reservation is not waiting for reconciliation.", 409)
        result = self.settle(cur, workspace_id, reservation_id, outcome, actual_usd_micro, idempotency_key=f"reconcile:{reservation_id}")
        cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,NULL,'usage.reconciled',%s,%s::jsonb)",
                    (workspace_id, str(reservation_id)[:200], json.dumps({"outcome": outcome, "actualUsdMicro": actual_usd_micro, "operator": operator.strip()[:80], "evidence": evidence.strip()[:200]})))
        return result

    def usage_view(self, cur, workspace_id, member_id=None, *, pricing=None):
        entitlement = self.ensure_entitlement(cur, workspace_id, None)
        cur.execute("SELECT p.plan,p.entitlements->>'creditPolicy',p.status FROM public.pr_entitlements e JOIN public.pr_plan_terms p ON p.id=e.plan_terms_id WHERE e.workspace_id=%s", (workspace_id,))
        plan, policy, policy_status = cur.fetchone()
        entitlement['plan'] = plan
        mode = 'free_preview' if plan == 'free' else 'managed_credits' if policy in SUPPORTED_POLICY_VERSIONS else 'legacy_allowances'
        credits = None
        # Reading immutable balances is independent of spend/checkout activation. In
        # particular policy() is a spend guard and raises for inactive terms.
        if mode == 'managed_credits' and not ai_usage_exempt(member_id):
            # Lot allocations and internal grant IDs stay in the accounting book.
            # Customer usage gets only safe purchased-credit facts plus aggregate balances.
            book = self._credit_book.view(cur, workspace_id)
            lots = book.get('lots', [])
            credits = {key: value for key, value in book.items() if key != 'lots'}
            cur.execute("SELECT id::text,meta->'credits'->>'source' FROM public.pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'", (workspace_id,))
            sources = dict(cur.fetchall())
            credits['purchasedCredits'] = [
                {'available': lot['available'], 'held': lot['held'], 'expiresAt': lot['expiresAt']}
                for lot in lots if sources.get(lot['grantId']) == 'verified-stripe-checkout'
            ]
            reason = ('credits_disabled' if self.credits is None else 'policy_inactive' if policy_status != 'active'
                      else 'ai_paused' if ai_paused() else 'credit_debt' if credits['debtMilliCredits'] else None)
            # Existing qualified media-notes also use credits. This does not qualify
            # image/video generation or the forthcoming Growth rewrite bridge.
            credits.update(mode="credits", policy=policy, quoteType="spending_limit", textOnly=False,
                           spendAvailable=reason is None, spendUnavailableReason=reason)
        cur.execute("SELECT to_regclass('public.pr_plan_price_variants') IS NOT NULL")
        catalog_v2 = cur.fetchone()[0]
        cur.execute("SELECT s.plan_terms_id,s.provider,s.status,extract(epoch from s.current_period_end),s.cancel_at_period_end,extract(epoch from s.grace_until),p.plan,p.label,p.price_cents,p.currency,p.status,p.version FROM public.pr_subscriptions s JOIN public.pr_plan_terms p ON p.id=s.plan_terms_id WHERE s.workspace_id=%s", (workspace_id,))
        sub = cur.fetchone()
        subscription = None if not sub else {"planTermsId": sub[0], "provider": sub[1], "status": sub[2], "currentPeriodEnd": float(sub[3]) if sub[3] else None, "cancelAtPeriodEnd": sub[4], "graceUntil": float(sub[5]) if sub[5] else None, "plan": sub[6], "label": plan_display_label(sub[7]), "priceCents": sub[8], "currency": sub[9], "priceStatus": sub[10], "termsVersion": sub[11], "live": sub[1] != "fixture", "priceVariantId": None}
        creator_price = None
        if catalog_v2:
            pricing = pricing or PlanPricing()
            cur.execute('SELECT price_variant_id FROM public.pr_subscriptions WHERE workspace_id=%s', (workspace_id,))
            bound = cur.fetchone()
            if bound and bound[0]:
                variant = pricing.variant(cur, bound[0])
                if subscription and variant['planTermsId'] == subscription['planTermsId']:
                    subscription.update(priceVariantId=variant['priceVariantId'], priceCents=variant['amountCents'], currency=variant['currency'])
            try:
                creator_price = pricing.assign(cur, workspace_id)
            except AlphaError:
                # A legacy subscriber keeps their current terms; the public Creator
                # reference remains default, with checkout unavailable to that user.
                creator_price = pricing.variant(cur, DEFAULT_VARIANT)
        cur.execute("SELECT kind,dimension,cost_state,estimated_usd_micro,actual_usd_micro,extract(epoch from at),provider,model,charge_batch,reservation_id::text,run_id::text,job_id::text FROM public.pr_usage_ledger WHERE workspace_id=%s ORDER BY at DESC LIMIT 100", (workspace_id,))
        ledger = [{"kind": r[0], "dimension": r[1], "costState": r[2], "estimatedUsdMicro": r[3], "actualUsdMicro": r[4], "at": float(r[5]), "provider": r[6], "model": r[7], "chargeBatch": r[8], "reservationId": r[9], "runId": r[10], "jobId": r[11]} for r in cur.fetchall()]
        ws_budget = self._budget(cur, f"workspace:{workspace_id}", "month")
        if catalog_v2:
            cur.execute("SELECT id,plan,version,label,price_cents,currency,status,entitlements,catalog_state,new_checkout_enabled FROM public.pr_plan_terms WHERE (catalog_state='public' AND plan IN ('free','creator')) OR id=%s ORDER BY plan,version", (sub[0] if sub else entitlement['planTermsId'],))
        else:
            cur.execute("SELECT id,plan,version,label,price_cents,currency,status,entitlements,'legacy',(status='active' AND nullif(btrim(provider_price_id),'') IS NOT NULL) FROM public.pr_plan_terms ORDER BY plan,version")
        terms = []
        for r in cur.fetchall():
            effective = creator_price if r[0] == 'creator-v1' else None
            terms.append({"id": r[0], "plan": r[1], "version": r[2], "label": plan_display_label(r[3]),
                          "priceCents": effective['amountCents'] if effective else r[4], "defaultPriceCents": r[4],
                          "currency": effective['currency'] if effective else r[5], "status": r[6],
                          "priceVariantId": effective['priceVariantId'] if effective else None,
                          "catalogState": r[8], "newCheckoutEnabled": bool(r[9] and (r[8] == 'public' and r[0] == 'creator-v1' if catalog_v2 else r[1] != 'trial')),
                          "checkoutAvailable": False, "current": r[0] == entitlement['planTermsId'],
                          "entitlements": customer_entitlements(r[7]), "priceLabel": "proposed" if r[6] != "active" else "active"})
        return {
            "billingMode": mode,
            "freePreview": None,
            "entitlement": entitlement,
            "credits": credits,
            "aiUsageExempt": ai_usage_exempt(member_id),
            "subscription": subscription,
            "budget": {"windowKind": ws_budget["windowKind"], "spentUsdMicro": ws_budget["spent"], "reservedUsdMicro": ws_budget["reserved"], "warnUsdMicro": ws_budget["warn"], "stopUsdMicro": ws_budget["stop"], "status": ws_budget["status"]},
            "overage": "stop",
            "ledger": ledger,
            "planTerms": terms,
            "note": "Prices marked 'proposed' aren't final. Nothing is charged yet.",
        }


class FixturePaymentProvider:
    """Labelled fixture. Verifies an HMAC signature and yields typed events; never contacts a processor."""
    id = "fixture"

    def __init__(self, secret="fixture-webhook-secret"):
        self.secret = secret.encode()

    def sign(self, body):
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def parse_webhook(self, signature, body):
        # The secret above is published; a hosted deployment must never accept a fixture-signed payment.
        if os.environ.get("VERCEL") == "1":
            raise AlphaError("Fixture payments are not available on a hosted deployment.", 503)
        if not isinstance(body, (bytes, bytearray)) or not isinstance(signature, str) or not hmac.compare_digest(self.sign(body), signature):
            raise AlphaError("Webhook signature rejected.", 401)
        try:
            event = json.loads(body)
        except ValueError as error:
            raise AlphaError("Webhook body invalid.", 400) from error
        for key in ("id", "type", "createdAt", "workspaceId"):
            if key not in event:
                raise AlphaError("Webhook event incomplete.", 400)
        return event


class DisabledPaymentProvider:
    """Mounted when no live provider is configured. Every webhook is refused; nothing is purchasable.
    The fixture provider is never the production default: its secret is public."""
    id = "disabled"

    def __init__(self, reason="Billing isn't available yet."):
        self.reason = reason

    def parse_webhook(self, signature, body):
        raise AlphaError(self.reason, 503)



class Billing:
    TRANSITIONS = {
        "subscription.activated": "active", "subscription.updated": "active", "invoice.payment_failed": "past_due",
        "subscription.grace": "grace", "subscription.cancelled": "cancelled", "subscription.expired": "expired",
    }

    def __init__(self, provider=None, ledger=None, clock=time.time, on_applied=None, pricing_v2_enabled=False, creator_experiment_enabled=False, creator_experiment_cohort=()):
        """`on_applied(event, status)` runs only for outcome 'applied' (e.g. notifications); its failures never break the webhook."""
        self.provider, self.ledger, self.clock, self.on_applied = provider or FixturePaymentProvider(), ledger or Ledger(clock=clock, pricing_v2_enabled=pricing_v2_enabled), clock, on_applied

        self.pricing_v2_enabled = pricing_v2_enabled
        self.pricing = PlanPricing(pricing_v2_enabled and creator_experiment_enabled, creator_experiment_cohort, ledger=self.ledger)

    def assign_creator_price(self, cur, workspace_id):
        return self.pricing.assign(cur, workspace_id)

    def process_webhook(self, cur, signature, body):
        """Signature-verified, replay-safe (unique provider+event id), out-of-order safe (event_at vs last_event_at)."""
        event = self.provider.parse_webhook(signature, body)
        payload_digest = hashlib.sha256(body).hexdigest()
        # Serialize same-event deliveries before the replay lookup; the workspace lock alone
        # cannot prevent two deliveries from both observing an absent event row.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (self.provider.id + ":" + event["id"],))
        cur.execute("SELECT outcome FROM public.pr_billing_events WHERE provider=%s AND event_id=%s", (self.provider.id, event["id"]))
        if cur.fetchone():
            return {"eventId": event["id"], "outcome": "duplicate"}
        versioned = False
        valid = not event.get("metadataConflict", False)
        if self.provider.id == "stripe" and self.TRANSITIONS.get(event["type"]):
            # Old default-off deployments may not have 048. Existing v2 subscriptions
            # still reconcile after the acquisition flag is disabled.
            cur.execute("SELECT to_regclass('public.pr_plan_price_variants') IS NOT NULL")
            schema = cur.fetchone()
            versioned = bool(schema and schema[0])
            if versioned:
                valid = valid and self.pricing.resolve_event(cur, event)
            elif event.get("priceVariantId"):
                valid = False
        if not versioned and not event.get("planTermsId") and event.get("invoicePriceLines"):
            valid = valid and self.pricing.invoice_price(cur, event, versioned=False)
        if not versioned and not event.get("planTermsId") and event.get("priceId"):
            # Live providers carry their price id; only an 'active' terms row (D3) may be bound to it.
            cur.execute("SELECT id FROM public.pr_plan_terms WHERE provider_price_id=%s AND status='active'", (event["priceId"],))
            resolved = cur.fetchone()
            if resolved:
                event["planTermsId"] = resolved[0]
        kind = event["type"]
        status = self.TRANSITIONS.get(kind)
        outcome = "ignored" if status is None else "applied"
        if status is not None and not valid:
            outcome, status = "rejected", None
        if status is not None and not event.get("workspaceId"):
            outcome, status = "ignored", None  # no PostRiff workspace on the event: recorded, never applied
        if status is not None:
            cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (event["workspaceId"],))
            cur.execute("SELECT extract(epoch from last_event_at) FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE", (event["workspaceId"],))
            row = cur.fetchone()
            if row and row[0] and float(row[0]) > float(event["createdAt"]):
                outcome = "stale"
                if versioned and event.get("priceVariantId"):
                    # Fill a missing historical paid identity without touching newer lifecycle state.
                    cur.execute("UPDATE public.pr_subscriptions SET price_variant_id=%s WHERE workspace_id=%s AND provider=%s AND provider_subscription_id=%s AND plan_terms_id=%s AND price_variant_id IS NULL",
                                (event["priceVariantId"], event["workspaceId"], self.provider.id, event.get("subscriptionId"), event.get("planTermsId")))
            else:
                terms_id = event.get("planTermsId")
                if terms_id:
                    cur.execute("SELECT entitlements FROM public.pr_plan_terms WHERE id=%s", (terms_id,))
                    terms = cur.fetchone()
                    if not terms:
                        outcome = "rejected"  # unknown plan id from the client side never creates entitlement
                if outcome == "applied":
                    grace = float(event["createdAt"]) + 7 * 86400 if status == "past_due" else None
                    variant_columns = ",price_variant_id" if versioned else ""
                    variant_values = ",%s" if versioned else ""
                    variant_update = ",price_variant_id=excluded.price_variant_id" if versioned else ""
                    cur.execute(f"INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,provider_customer_id,provider_subscription_id,status,current_period_end,cancel_at_period_end,grace_until,last_event_at{variant_columns}) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,to_timestamp(%s),to_timestamp(%s){variant_values}) ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=coalesce(excluded.plan_terms_id,public.pr_subscriptions.plan_terms_id),provider=excluded.provider,provider_customer_id=coalesce(excluded.provider_customer_id,public.pr_subscriptions.provider_customer_id),provider_subscription_id=coalesce(excluded.provider_subscription_id,public.pr_subscriptions.provider_subscription_id),status=excluded.status,current_period_end=coalesce(excluded.current_period_end,public.pr_subscriptions.current_period_end),cancel_at_period_end=excluded.cancel_at_period_end,grace_until=excluded.grace_until,last_event_at=excluded.last_event_at,updated_at=now(){variant_update}", (event["workspaceId"], terms_id or "trial-v1", self.provider.id, event.get("customerId"), event.get("subscriptionId"), status, event.get("currentPeriodEnd"), bool(event.get("cancelAtPeriodEnd")), grace, float(event["createdAt"]), *((event.get("priceVariantId"),) if versioned else ())))
                    if terms_id and status == "active":
                        self._reconcile_entitlement(cur, event["workspaceId"], terms_id, terms[0], event.get("currentPeriodEnd"))
        # A verified paid plan invoice grants its period's credits even when its status update is stale.
        if event.get("stripeType") == "invoice.paid" and event.get("workspaceId") and outcome in ("applied", "stale"):
            self._grant_period_credits(cur, event)
        if outcome in ("applied", "stale"):
            pricing_events.signed_billing(cur, event, self.provider.id)
        cur.execute("INSERT INTO public.pr_billing_events(provider,event_id,kind,event_at,payload_digest,outcome) VALUES(%s,%s,%s,to_timestamp(%s),%s,%s)", (self.provider.id, event["id"], kind, float(event["createdAt"]), payload_digest, outcome))
        if outcome == "applied" and self.on_applied is not None:
            try:
                self.on_applied(event, status)
            except Exception:  # noqa: BLE001 — a notification failure must never fail the webhook
                pass
        return {"eventId": event["id"], "outcome": outcome, "status": status, "type": kind, "workspaceId": event.get("workspaceId") or None}

    def _grant_period_credits(self, cur, event):
        """Versioned monthly-credit policy: subscription_create and subscription_cycle invoices grant
        the plan's monthlyCredits once per invoice id, expiring at the period end. Other invoices are recorded
        with a note and grant nothing. Legacy plans without a credit policy are untouched."""
        cur.execute("SELECT to_regclass('public.pr_credit_subscription_grants') IS NOT NULL")
        if not cur.fetchone()[0]:
            return None
        terms_id, invoice_id = event.get("planTermsId"), event.get("invoiceId")
        if not terms_id or not invoice_id or not event.get("invoicePaid") or event.get("amountPaid") is None or not event.get("currency"):
            return None
        cur.execute("SELECT entitlements FROM public.pr_plan_terms WHERE id=%s", (terms_id,))
        row = cur.fetchone()
        ent = row[0] if row and isinstance(row[0], dict) else {}
        if not isinstance(ent.get("creditPolicy"), str) or ent["creditPolicy"] not in SUPPORTED_POLICY_VERSIONS or type(ent.get("monthlyCredits")) is not int or ent["monthlyCredits"] <= 0:
            return None
        reason = event.get("billingReason") or ""
        grants = reason in ("subscription_create", "subscription_cycle")
        note = "" if grants else f"{reason or 'unknown'} invoice: no automatic credits (policy pending)"[:200]
        if grants and ent["creditPolicy"] == V2_POLICY_VERSION:
            start, end = event.get("periodStart"), event.get("currentPeriodEnd")
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or end <= start):
                grants = False
                note = "Incomplete paid period: no automatic credits."
        cur.execute("INSERT INTO public.pr_credit_subscription_grants(invoice_id,workspace_id,subscription_id,plan_terms_id,billing_reason,period_start,period_end,amount_cents,currency,payment_intent_id,millicredits,livemode,note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(invoice_id) DO NOTHING RETURNING invoice_id",
                    (invoice_id, event["workspaceId"], event.get("subscriptionId"), terms_id, reason, event.get("periodStart"), event.get("currentPeriodEnd"), event["amountPaid"], event["currency"], event.get("paymentIntentId"), ent["monthlyCredits"] * 1000 if grants else 0, bool(getattr(self.provider, "live", False)), note))
        if not cur.fetchone() or not grants:
            return None
        try:
            granted = self.ledger._credit_book.grant(cur, event["workspaceId"], None, "subscription-invoice:" + invoice_id, ent["monthlyCredits"] * 1000, event.get("currentPeriodEnd"), source="verified-stripe-invoice", policy_version=ent["creditPolicy"])
        except AlphaError as error:
            # The workspace is not on active credit terms: keep the paid invoice on record for review.
            cur.execute("UPDATE public.pr_credit_subscription_grants SET note=%s WHERE invoice_id=%s", (f"not granted: {error}"[:200], invoice_id))
            return None
        cur.execute("UPDATE public.pr_credit_subscription_grants SET grant_id=%s WHERE invoice_id=%s", (granted["entryId"], invoice_id))
        return granted

    def availability(self, cur, workspace_id):
        """'billing' block for the usage view: mounted provider and whether checkout/portal can be offered.
        Checkout needs the live provider plus at least one 'active' terms row bound to a provider price (D3)."""
        live = self.provider.id == "stripe"
        if self.pricing_v2_enabled:
            try:
                self.pricing.checkout(cur, workspace_id, "creator-v1")
                purchasable = True
            except AlphaError:
                purchasable = False
        else:
            cur.execute("SELECT 1 FROM public.pr_plan_terms WHERE status='active' AND coalesce(provider_price_id,'')<>'' AND plan NOT IN ('creator','starter','free') AND id<>'studio-v2' AND coalesce((to_jsonb(pr_plan_terms)->>'new_checkout_enabled')::boolean,true) LIMIT 1")
            purchasable = cur.fetchone() is not None
        cur.execute("SELECT provider_customer_id FROM public.pr_subscriptions WHERE workspace_id=%s AND provider=%s", (workspace_id, self.provider.id))
        row = cur.fetchone()
        return {"provider": self.provider.id, "checkoutAvailable": live and purchasable, "portalAvailable": live and bool(row and row[0])}

    @staticmethod
    def _reconcile_entitlement(cur, workspace_id, terms_id, ent, period_end):
        cur.execute("INSERT INTO public.pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,resets_at,source) VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),'subscription') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=excluded.plan_terms_id,writing_batches_remaining=CASE WHEN public.pr_entitlements.source<>'subscription' OR (public.pr_entitlements.resets_at IS NOT NULL AND excluded.resets_at>public.pr_entitlements.resets_at) THEN excluded.writing_batches_remaining ELSE least(public.pr_entitlements.writing_batches_remaining,excluded.writing_batches_remaining) END,media_credits_remaining=CASE WHEN public.pr_entitlements.source<>'subscription' OR (public.pr_entitlements.resets_at IS NOT NULL AND excluded.resets_at>public.pr_entitlements.resets_at) THEN excluded.media_credits_remaining ELSE least(public.pr_entitlements.media_credits_remaining,excluded.media_credits_remaining) END,connected_accounts=excluded.connected_accounts,members=excluded.members,storage_mb=excluded.storage_mb,resets_at=greatest(excluded.resets_at,public.pr_entitlements.resets_at),source='subscription',version=public.pr_entitlements.version+1,updated_at=now()", (workspace_id, terms_id, ent["writingBatches"], ent["mediaCredits"], ent["connectedAccounts"], ent["members"], ent["storageMb"], period_end))

    def lifecycle(self, cur, workspace_id, now):
        """Lifecycle derivation shared with the before-I/O entitlement boundary."""
        from .free_lifecycle import lifecycle
        return lifecycle(cur, workspace_id, now, pricing_v2_enabled=self.pricing_v2_enabled)



def require_plan_capacity(cur, workspace_id, dimension, connection_id=None, *, ledger=None):
    cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
    entitlement = (ledger or Ledger()).ensure_entitlement(cur, workspace_id, None)
    if dimension == "members":
        cur.execute("SELECT count(*) FROM public.pr_memberships WHERE workspace_id=%s AND status='active'", (workspace_id,))
        count, limit = cur.fetchone()[0], entitlement["members"]
    elif dimension == "connected_accounts":
        cur.execute("SELECT connection_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND revoked_at IS NULL", (workspace_id,))
        existing = {row[0] for row in cur.fetchall()}
        if connection_id in existing:
            return  # Reauthorizing an existing account consumes no new slot.
        count, limit = len(existing), entitlement["connectedAccounts"]
    else:
        raise ValueError("Unknown plan dimension")
    if count >= limit:
        raise AlphaError("This plan has no remaining member seats." if dimension == "members" else "This plan has no remaining connected-account slots.", 402, code="plan_limit_reached")


def require_publishing(cur, workspace_id, now):
    if not Billing().lifecycle(cur, workspace_id, now).get("canPublish", False):
        raise AlphaError("Publishing is paused because this trial or subscription has ended. Drafts and exports remain available.", 402, code="publishing_plan_inactive")

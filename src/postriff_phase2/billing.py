"""Entitlements, append-only usage ledger with reserve/settle/release, budgets, and billing
webhooks behind a provider interface (architecture §17; improvement SPEC §6).

Nothing here charges money. `FixturePaymentProvider` is labelled fixture; a live provider
is a separate, authorized selection. Prices come from versioned `pr_plan_terms` rows whose
status is 'proposed' until an explicit commercial decision.
"""
import hashlib
import hmac
import json
import time
from postriff_alpha.domain import AlphaError
from .contracts import digest

USD = 1_000_000  # micro-dollars
# Candidate ceilings from improvement SPEC §6 — "待價格與品質評估修正的候選上限", flagged 'candidate' in data.
CANDIDATE_BUDGETS = {
    "global": {"window_kind": "day", "warn": 5 * USD, "stop": 10 * USD},
    "workspace": {"window_kind": "month", "warn": 4 * USD, "stop": 6 * USD},
}
DEFAULT_RESERVE_TEXT = USD // 2  # $0.50 per batch (SPEC §6)


def _window_start_sql(kind):
    return "date_trunc('day', now())" if kind == "day" else "date_trunc('month', now())"


class Ledger:
    """All methods take an open cursor inside the caller's transaction (workspace row locked)."""

    def _budget(self, cur, scope, kind):
        spec = CANDIDATE_BUDGETS["global" if scope == "global" else "workspace"]
        cur.execute(f"INSERT INTO public.pr_budgets(scope,window_kind,window_start,warn_usd_micro,stop_usd_micro) VALUES(%s,%s,{_window_start_sql(spec['window_kind'])},%s,%s) ON CONFLICT(scope) DO NOTHING", (scope, spec["window_kind"], spec["warn"], spec["stop"]))
        cur.execute("SELECT window_kind,window_start,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,status FROM public.pr_budgets WHERE scope=%s FOR UPDATE", (scope,))
        row = cur.fetchone()
        # Roll the window forward when it lapsed (fixed window; spent/reserved reset).
        cur.execute(f"UPDATE public.pr_budgets SET window_start={_window_start_sql(row[0])},spent_usd_micro=0,reserved_usd_micro=0,updated_at=now() WHERE scope=%s AND window_start < {_window_start_sql(row[0])} RETURNING 1", (scope,))
        if cur.fetchone():
            cur.execute("SELECT window_kind,window_start,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,status FROM public.pr_budgets WHERE scope=%s", (scope,))
            row = cur.fetchone()
        return {"windowKind": row[0], "warn": row[2], "stop": row[3], "spent": row[4], "reserved": row[5], "status": row[6]}

    def ensure_entitlement(self, cur, workspace_id, plan):
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
        cur.execute("INSERT INTO public.pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,resets_at,source) VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),'trial')", (workspace_id, terms_id, ent["writingBatches"], ent["mediaCredits"], ent["connectedAccounts"], ent["members"], ent["storageMb"], resets))
        cur.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,%s,'trial',to_timestamp(%s)) ON CONFLICT(workspace_id) DO NOTHING", (workspace_id, terms_id, resets))
        return self.ensure_entitlement(cur, workspace_id, plan)

    def reserve(self, cur, workspace_id, member_id, dimension, estimated_usd_micro, idempotency_key, *, charge_batch, provider="", model="", run_id=None, job_id=None, meta=None):
        """Lock budgets → check ceilings and entitlement → insert reservation → return it. Same key returns the same row."""
        if dimension not in ("text_model", "image_generation", "tool", "storage", "action") or type(estimated_usd_micro) is not int or estimated_usd_micro < 0:
            raise AlphaError("Invalid usage reservation.", 400)
        fingerprint = digest({"dimension": dimension, "estimate": estimated_usd_micro, "chargeBatch": charge_batch, "provider": provider, "model": model})
        cur.execute("SELECT id::text,reservation_id::text,meta FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, idempotency_key))
        existing = cur.fetchone()
        if existing:
            if (existing[2] or {}).get("fingerprint") != fingerprint:
                raise AlphaError("This usage key belongs to a different operation.", 409)
            return {"reservationId": existing[1] or existing[0], "duplicate": True}
        entitlement = self.ensure_entitlement(cur, workspace_id, None)
        if charge_batch and entitlement["writingBatchesRemaining"] <= 0:
            raise AlphaError("No writing allowance left in this plan. Drafts, exports and reviews remain available; overage is not charged silently.", 402)
        if dimension == "image_generation" and entitlement["mediaCreditsRemaining"] <= 0:
            raise AlphaError("No media credits left in this plan.", 402)
        ws_budget = self._budget(cur, f"workspace:{workspace_id}", "month")
        gl_budget = self._budget(cur, "global", "day")
        for scope, budget in (("workspace", ws_budget), ("global", gl_budget)):
            if budget["spent"] + budget["reserved"] + estimated_usd_micro > budget["stop"]:
                raise AlphaError(f"The {scope} spending stop-line would be exceeded; this request is refused before any provider call.", 402)
        cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,run_id,job_id,kind,dimension,provider,model,estimated_usd_micro,cost_state,charge_batch,idempotency_key,meta) VALUES(%s,%s,%s,%s,'reserve',%s,%s,%s,%s,'estimated',%s,%s,%s::jsonb) RETURNING id::text", (workspace_id, member_id, run_id, job_id, dimension, provider, model, estimated_usd_micro, charge_batch, idempotency_key, json.dumps({**(meta or {}), "fingerprint": fingerprint})))
        reservation_id = cur.fetchone()[0]
        cur.execute("UPDATE public.pr_usage_ledger SET reservation_id=id WHERE id::text=%s", (reservation_id,))
        for scope in (f"workspace:{workspace_id}", "global"):
            cur.execute("UPDATE public.pr_budgets SET reserved_usd_micro=reserved_usd_micro+%s,updated_at=now() WHERE scope=%s", (estimated_usd_micro, scope))
        warnings = [f"{scope} budget past its warning line" for scope, b in (("workspace", ws_budget), ("global", gl_budget)) if b["spent"] + b["reserved"] + estimated_usd_micro > b["warn"]]
        return {"reservationId": reservation_id, "duplicate": False, "warnings": warnings, "entitlement": entitlement}

    def settle(self, cur, workspace_id, reservation_id, outcome, actual_usd_micro=None, idempotency_key=None):
        """completed → actual cost, batch consumed; failed → provider cost still booked, batch refunded;
        unknown → reservation kept and cost booked as estimated_unknown until reconciled."""
        if outcome not in ("completed", "failed", "unknown"):
            raise AlphaError("Invalid settlement outcome.", 400)
        cur.execute("SELECT dimension,estimated_usd_micro,charge_batch,provider,model,run_id,job_id,member_id FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve'", (workspace_id, reservation_id))
        reservation = cur.fetchone()
        if not reservation:
            raise AlphaError("Reservation unavailable.", 404)
        dimension, estimate, charge_batch, provider, model, run_id, job_id, member_id = reservation
        key = idempotency_key or f"settle:{reservation_id}:{outcome}"
        cur.execute("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
        if cur.fetchone():
            return {"reservationId": reservation_id, "duplicate": True}
        if outcome == "unknown":
            cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,run_id,job_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,charge_batch,idempotency_key) VALUES(%s,%s,%s,%s,%s,'settle',%s,%s,%s,%s,NULL,'estimated_unknown',%s,%s)", (workspace_id, member_id, run_id, job_id, reservation_id, dimension, provider, model, estimate, charge_batch, key))
            return {"reservationId": reservation_id, "state": "estimated_unknown", "note": "Reservation retained until provider usage is reconciled; cost is not recorded as zero."}
        actual = int(actual_usd_micro or 0)
        kind = "settle" if outcome == "completed" else "release"
        cur.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,run_id,job_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,charge_batch,idempotency_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (workspace_id, member_id, run_id, job_id, reservation_id, kind, dimension, provider, model, estimate, actual, "actual" if outcome == "completed" else "released", charge_batch, key))
        for scope in (f"workspace:{workspace_id}", "global"):
            cur.execute("UPDATE public.pr_budgets SET reserved_usd_micro=greatest(reserved_usd_micro-%s,0),spent_usd_micro=spent_usd_micro+%s,updated_at=now() WHERE scope=%s", (estimate, actual, scope))
        if outcome == "completed" and charge_batch:
            column = "media_credits_remaining" if dimension == "image_generation" else "writing_batches_remaining"
            cur.execute(f"UPDATE public.pr_entitlements SET {column}=greatest({column}-1,0),version=version+1,updated_at=now() WHERE workspace_id=%s", (workspace_id,))
        return {"reservationId": reservation_id, "state": "actual" if outcome == "completed" else "released", "actualUsdMicro": actual}

    def usage_view(self, cur, workspace_id):
        entitlement = self.ensure_entitlement(cur, workspace_id, None)
        cur.execute("SELECT s.plan_terms_id,s.provider,s.status,extract(epoch from s.current_period_end),s.cancel_at_period_end,extract(epoch from s.grace_until),p.plan,p.label,p.price_cents,p.currency,p.status,p.version FROM public.pr_subscriptions s JOIN public.pr_plan_terms p ON p.id=s.plan_terms_id WHERE s.workspace_id=%s", (workspace_id,))
        sub = cur.fetchone()
        cur.execute("SELECT kind,dimension,cost_state,estimated_usd_micro,actual_usd_micro,extract(epoch from at),provider,model FROM public.pr_usage_ledger WHERE workspace_id=%s ORDER BY at DESC LIMIT 100", (workspace_id,))
        ledger = [{"kind": r[0], "dimension": r[1], "costState": r[2], "estimatedUsdMicro": r[3], "actualUsdMicro": r[4], "at": float(r[5]), "provider": r[6], "model": r[7]} for r in cur.fetchall()]
        ws_budget = self._budget(cur, f"workspace:{workspace_id}", "month")
        cur.execute("SELECT id,plan,version,label,price_cents,currency,status,entitlements FROM public.pr_plan_terms ORDER BY plan,version")
        terms = [{"id": r[0], "plan": r[1], "version": r[2], "label": r[3], "priceCents": r[4], "currency": r[5], "status": r[6], "entitlements": r[7], "priceLabel": "proposed" if r[6] != "active" else "active"} for r in cur.fetchall()]
        return {
            "entitlement": entitlement,
            "subscription": None if not sub else {"planTermsId": sub[0], "provider": sub[1], "status": sub[2], "currentPeriodEnd": float(sub[3]) if sub[3] else None, "cancelAtPeriodEnd": sub[4], "graceUntil": float(sub[5]) if sub[5] else None, "plan": sub[6], "label": sub[7], "priceCents": sub[8], "currency": sub[9], "priceStatus": sub[10], "termsVersion": sub[11], "live": sub[1] != "fixture"},
            "budget": {"windowKind": ws_budget["windowKind"], "spentUsdMicro": ws_budget["spent"], "reservedUsdMicro": ws_budget["reserved"], "warnUsdMicro": ws_budget["warn"], "stopUsdMicro": ws_budget["stop"], "status": ws_budget["status"]},
            "overage": "stop",
            "ledger": ledger,
            "planTerms": terms,
            "note": "Prices marked 'proposed' are decision records, not offers. Nothing is charged by this deployment.",
        }


class FixturePaymentProvider:
    """Labelled fixture. Verifies an HMAC signature and yields typed events; never contacts a processor."""
    id = "fixture"

    def __init__(self, secret="fixture-webhook-secret"):
        self.secret = secret.encode()

    def sign(self, body):
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def parse_webhook(self, signature, body):
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


class Billing:
    TRANSITIONS = {
        "subscription.activated": "active", "subscription.updated": "active", "invoice.payment_failed": "past_due",
        "subscription.grace": "grace", "subscription.cancelled": "cancelled", "subscription.expired": "expired",
    }

    def __init__(self, provider=None, ledger=None, clock=time.time, on_applied=None):
        """`on_applied(event, status)` runs only for outcome 'applied' (e.g. notifications); its failures never break the webhook."""
        self.provider, self.ledger, self.clock, self.on_applied = provider or FixturePaymentProvider(), ledger or Ledger(), clock, on_applied

    def process_webhook(self, cur, signature, body):
        """Signature-verified, replay-safe (unique provider+event id), out-of-order safe (event_at vs last_event_at)."""
        event = self.provider.parse_webhook(signature, body)
        payload_digest = hashlib.sha256(body).hexdigest()
        cur.execute("SELECT outcome FROM public.pr_billing_events WHERE provider=%s AND event_id=%s", (self.provider.id, event["id"]))
        if cur.fetchone():
            return {"eventId": event["id"], "outcome": "duplicate"}
        if not event.get("planTermsId") and event.get("priceId"):
            # Live providers carry their price id; only an 'active' terms row (D3) may be bound to it.
            cur.execute("SELECT id FROM public.pr_plan_terms WHERE provider_price_id=%s AND status='active'", (event["priceId"],))
            resolved = cur.fetchone()
            if resolved:
                event["planTermsId"] = resolved[0]
        kind = event["type"]
        status = self.TRANSITIONS.get(kind)
        outcome = "ignored" if status is None else "applied"
        if status is not None:
            cur.execute("SELECT extract(epoch from last_event_at) FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE", (event["workspaceId"],))
            row = cur.fetchone()
            if row and row[0] and float(row[0]) > float(event["createdAt"]):
                outcome = "stale"
            else:
                terms_id = event.get("planTermsId")
                if terms_id:
                    cur.execute("SELECT entitlements FROM public.pr_plan_terms WHERE id=%s", (terms_id,))
                    terms = cur.fetchone()
                    if not terms:
                        outcome = "rejected"  # unknown plan id from the client side never creates entitlement
                if outcome == "applied":
                    grace = float(event["createdAt"]) + 7 * 86400 if status == "past_due" else None
                    cur.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,provider_customer_id,provider_subscription_id,status,current_period_end,cancel_at_period_end,grace_until,last_event_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=coalesce(excluded.plan_terms_id,public.pr_subscriptions.plan_terms_id),provider=excluded.provider,provider_customer_id=coalesce(excluded.provider_customer_id,public.pr_subscriptions.provider_customer_id),provider_subscription_id=coalesce(excluded.provider_subscription_id,public.pr_subscriptions.provider_subscription_id),status=excluded.status,current_period_end=coalesce(excluded.current_period_end,public.pr_subscriptions.current_period_end),cancel_at_period_end=excluded.cancel_at_period_end,grace_until=excluded.grace_until,last_event_at=excluded.last_event_at,updated_at=now()", (event["workspaceId"], terms_id or "trial-v1", self.provider.id, event.get("customerId"), event.get("subscriptionId"), status, event.get("currentPeriodEnd"), bool(event.get("cancelAtPeriodEnd")), grace, float(event["createdAt"])))
                    if terms_id and status == "active":
                        self._reconcile_entitlement(cur, event["workspaceId"], terms_id, terms[0], event.get("currentPeriodEnd"))
        cur.execute("INSERT INTO public.pr_billing_events(provider,event_id,kind,event_at,payload_digest,outcome) VALUES(%s,%s,%s,to_timestamp(%s),%s,%s)", (self.provider.id, event["id"], kind, float(event["createdAt"]), payload_digest, outcome))
        if outcome == "applied" and self.on_applied is not None:
            try:
                self.on_applied(event, status)
            except Exception:  # noqa: BLE001 — a notification failure must never fail the webhook
                pass
        return {"eventId": event["id"], "outcome": outcome, "status": status}

    def availability(self, cur, workspace_id):
        """'billing' block for the usage view: mounted provider and whether checkout/portal can be offered.
        Checkout needs the live provider plus at least one 'active' terms row bound to a provider price (D3)."""
        live = self.provider.id == "stripe"
        cur.execute("SELECT 1 FROM public.pr_plan_terms WHERE status='active' AND coalesce(provider_price_id,'')<>'' LIMIT 1")
        purchasable = cur.fetchone() is not None
        cur.execute("SELECT provider_customer_id FROM public.pr_subscriptions WHERE workspace_id=%s AND provider=%s", (workspace_id, self.provider.id))
        row = cur.fetchone()
        return {"provider": self.provider.id, "checkoutAvailable": live and purchasable, "portalAvailable": live and bool(row and row[0])}

    @staticmethod
    def _reconcile_entitlement(cur, workspace_id, terms_id, ent, period_end):
        cur.execute("INSERT INTO public.pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,resets_at,source) VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),'subscription') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=excluded.plan_terms_id,writing_batches_remaining=excluded.writing_batches_remaining,media_credits_remaining=excluded.media_credits_remaining,connected_accounts=excluded.connected_accounts,members=excluded.members,storage_mb=excluded.storage_mb,resets_at=excluded.resets_at,source='subscription',version=public.pr_entitlements.version+1,updated_at=now()", (workspace_id, terms_id, ent["writingBatches"], ent["mediaCredits"], ent["connectedAccounts"], ent["members"], ent["storageMb"], period_end))

    def lifecycle(self, cur, workspace_id, now):
        """Consistent state derivation: grace expiry → cancelled; cancelled keeps export; deletion is separate."""
        cur.execute("SELECT status,extract(epoch from grace_until),cancel_at_period_end,extract(epoch from current_period_end) FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE", (workspace_id,))
        row = cur.fetchone()
        if not row:
            return {"status": "trial"}
        status, grace_until, cancel_at_end, period_end = row
        if status == "past_due" and grace_until and now > float(grace_until):
            status = "cancelled"
        elif status == "active" and cancel_at_end and period_end and now > float(period_end):
            status = "cancelled"
        cur.execute("UPDATE public.pr_subscriptions SET status=%s,updated_at=now() WHERE workspace_id=%s", (status, workspace_id))
        return {"status": status, "exportAvailable": True, "draftsRetained": True, "canPublish": status in ("trial", "active", "grace", "past_due")}

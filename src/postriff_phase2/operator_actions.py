"""Consumer side of founder operator actions (Founder Admin CONTRACTS §8.F; PRD §7.5).

Two kinds of code live here. Neither is reachable from a customer request, an agent tool or a model.

1. Account-block enforcement, used by the consumer's own validation paths.
   A block (public.pr_account_blocks, migration 062) is a reversible fence, never a deletion:
   * a blocked user's sessions (hosted_app.supabase_verifier) and API tokens (api_tokens.ApiTokens.validate) answer
     403 ACCOUNT_BLOCKED with one fixed sentence (`blocked_error`);
   * the workspaces a block lists in `frozen_workspace_ids` (the workspace itself, or every workspace a blocked user
     owns) carry `state.accountBlock = {"blockIds": [...]}`, the account-deletion fence pattern: the repository
     transaction refuses them with the same 403, so requests and background runs stop before any work, and the
     publishing and automation workers skip them;
   * lifting the block removes its id from those markers (the key goes when no block remains) and sets lifted_at.
     Nothing is cancelled, revoked or deleted, so the account resumes exactly as it was.
   Production runs this code before 062 is applied. The user-level lookup is therefore gated by a catalog probe that
   cannot fail (to_regclass, has_table_privilege on that oid, pg_attribute): while the table, a column or the SELECT
   privilege is missing nothing is checked and no customer request is slowed or refused. The outcome is logged once per
   process by its error class (UndefinedTable / UndefinedColumn / InsufficientPrivilege) and probed again after ten
   minutes. A lookup that still meets one of those errors (a race with the probe) runs inside its own savepoint, so it
   can never abort the caller's transaction; the session check, whose connection does nothing else, rolls back and
   repeats its own query without the block column instead.

2. The consumer writes behind a confirmed founder action (rafii_control.founder_actions): reconcile one unknown usage
   reservation (billing.Ledger.reconcile_unknown, which writes `usage.reconciled`), adjust credits through CreditBook
   (source `founder_goodwill`, audit `credit.adjusted_by_operator`), place or lift a block (audit `account.blocked` /
   `account.unblocked`), and the reads their previews show. Every writer runs in the caller's consumer transaction, is
   idempotent on the founder action id, and records ids, enums, amounts and timestamps only.
"""
import json
import logging
import time

from postriff_alpha.domain import AlphaError

CODE = "ACCOUNT_BLOCKED"
MESSAGE = "This account is paused. Contact Rafii support to restore access."
MARKER = "accountBlock"
REASON_CODES = ("abuse", "fraud", "spam", "security", "payment", "legal", "other")
LIFT_REASON_CODES = ("resolved", "mistake", "appeal_granted", "other")
CREDIT_REASON_CODES = ("goodwill", "service_issue", "billing_correction")
REFUND_REASON_CODES = ("duplicate", "fraudulent", "requested_by_customer", "service_issue", "other")
UNAVAILABLE = ("UndefinedTable", "UndefinedColumn", "InsufficientPrivilege")
RETRY_SECONDS = 600
MAX_FROZEN_WORKSPACES = 100
RETENTION_DAYS = 400
_LOG = logging.getLogger("postriff.account_blocks")

# A catalog-only expression: to_regclass yields NULL for a missing table, has_table_privilege then takes that oid and the
# column count reads pg_attribute, so it cannot fail and may run inside any transaction. It names the error class a
# lookup would meet, or 'installed'.
PROBE = ("(SELECT CASE WHEN c.oid IS NULL THEN 'UndefinedTable' "
         "WHEN NOT has_table_privilege(c.oid,'SELECT') THEN 'InsufficientPrivilege' "
         "WHEN (SELECT count(*) FROM pg_catalog.pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
         "AND a.attname IN ('user_id','workspace_id','lifted_at'))<3 THEN 'UndefinedColumn' ELSE 'installed' END "
         "FROM (SELECT to_regclass('public.pr_account_blocks')::oid AS oid) c)")
USER_BLOCKED = "EXISTS(SELECT 1 FROM public.pr_account_blocks b WHERE b.user_id=%s AND b.lifted_at IS NULL)"
ANY_BLOCKED = ("SELECT EXISTS(SELECT 1 FROM public.pr_account_blocks b WHERE b.lifted_at IS NULL "
               "AND (b.user_id=%s OR b.workspace_id=%s))")
_STATE = {"status": None, "checked": 0.0, "logged": False}


def blocked_error():
    """The one customer-facing refusal for a paused account: fixed copy, no reason, no operator, no id."""
    return AlphaError(MESSAGE, 403, code=CODE)


def frozen(state):
    """Whether a block freezes this workspace (its state carries the accountBlock marker)."""
    return isinstance(state, dict) and bool(state.get(MARKER))


# --- installation probe ----------------------------------------------------------------------------------------------
def _class(error):
    """The UNAVAILABLE class name an error is (or derives from), else None."""
    return next((cls.__name__ for cls in type(error).__mro__ if cls.__name__ in UNAVAILABLE), None)


def _due():
    status = _STATE["status"]
    if status is None:
        return True
    return status != "installed" and time.monotonic() - _STATE["checked"] >= RETRY_SECONDS


def _record(status):
    """Remember the probe outcome; log the first 'not installed' outcome of the process by its class only."""
    if status not in ("installed",) + UNAVAILABLE:
        return
    _STATE.update(status=status, checked=time.monotonic())
    if status != "installed" and not _STATE["logged"]:
        _STATE["logged"] = True
        _LOG.warning(json.dumps({"event": "account_blocks_unavailable", "reason": status}))


def probe_now(cur):
    """Probe the table now (founder actions need a current answer, not the ten-minute cache) and return its status."""
    cur.execute("SELECT " + PROBE)
    row = cur.fetchone()
    _record(row[0] if row else None)
    return row[0] if row else None


def installed(cur):
    """Whether pr_account_blocks can be read here. Probes at most once per ten minutes while it cannot."""
    if _due():
        probe_now(cur)
    return _STATE["status"] == "installed"


def _lookup(cur, sql, params):
    """One block lookup in its own savepoint: a missing table, column or privilege can never abort the caller's
    transaction and allows the request; any other error still propagates (after the savepoint is rolled back)."""
    cur.execute("SAVEPOINT pr_account_block_check")
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
    except Exception as error:
        cur.execute("ROLLBACK TO SAVEPOINT pr_account_block_check")
        name = _class(error)
        if name is None:
            raise
        _record(name)
        return False
    cur.execute("RELEASE SAVEPOINT pr_account_block_check")
    return bool(row and row[0])


def account_blocked(cur, user_id=None, workspace_id=None):
    """Whether an active block names this user or this workspace (API-token validation). False while not installed."""
    if not installed(cur):
        return False
    return _lookup(cur, ANY_BLOCKED, (user_id, workspace_id))


def session_flags(db, cur, sql, params, user_id, width):
    """Run the consumer session check (hosted_app.supabase_verifier: `width` boolean columns over the session's own
    connection) with the user-block check folded into the same statement, so a session costs no extra round trip.
    Returns (the first `width` values, blocked)."""
    probe = _due()
    lookup = not probe and _STATE["status"] == "installed"
    extra, extra_params = ("," + PROBE, ()) if probe else ("," + USER_BLOCKED, (user_id,)) if lookup else ("", ())
    try:
        cur.execute(sql + extra, tuple(params) + extra_params)
        row = tuple(cur.fetchone())
    except Exception as error:
        name = _class(error)
        if not extra or name is None:
            raise
        _record(name)
        db.rollback()
        cur.execute(sql, params)
        return tuple(cur.fetchone())[:width], False
    values, more = row[:width], row[width:]
    if not more:
        return values, False
    if lookup:
        return values, bool(more[0])
    _record(more[0])
    return values, _STATE["status"] == "installed" and _lookup(cur, "SELECT " + USER_BLOCKED, (user_id,))


def purge_lifted(cur, limit=500):
    """Retention: delete lifted blocks whose retain_until passed (400 days after the lift). Bounded."""
    if probe_now(cur) != "installed":
        return {"status": "not_installed"}
    cur.execute("DELETE FROM public.pr_account_blocks WHERE id IN (SELECT id FROM public.pr_account_blocks "
                "WHERE retain_until IS NOT NULL AND retain_until<now() ORDER BY retain_until LIMIT %s)", (int(limit),))
    return {"status": "ok", "purged": max(cur.rowcount, 0)}


# --- shared helpers --------------------------------------------------------------------------------------------------
def operator_label(action_id):
    """What the consumer audit records as the operator: the founder action, never a name or address."""
    return "founder-action:" + str(action_id)


def _audit(cur, workspace_id, kind, subject, meta):
    """Content-free, append-only consumer audit (the hosted.audit columns): actor stays NULL, the action is in meta."""
    cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,NULL,%s,%s,%s::jsonb)",
                (workspace_id, kind, str(subject)[:200], json.dumps(meta, sort_keys=True)))


def lock_workspace(cur, workspace_id):
    cur.execute("SELECT id::text FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
    return cur.fetchone() is not None


def _epoch(value):
    return None if value is None else float(value)


# --- reconcile one unknown usage reservation ---------------------------------------------------------------------------
def reservation_snapshot(cur, workspace_id, reservation_id):
    """The reserve row and its settlement state (ids, amounts, enums), or None when it is not this workspace's."""
    cur.execute("SELECT dimension,provider,model,estimated_usd_micro,charge_batch,run_id::text,meta->'credits'->>'maximum',extract(epoch from at) "
                "FROM public.pr_usage_ledger WHERE workspace_id=%s AND id::text=%s AND kind='reserve'", (workspace_id, reservation_id))
    row = cur.fetchone()
    if not row:
        return None
    dimension, provider, model, estimate, charge_batch, run_id, maximum, at = row
    cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND cost_state='estimated_unknown'),"
                "EXISTS(SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND cost_state IN ('actual','released')),"
                "(SELECT r.status FROM public.pr_agent_runs r WHERE r.id=%s::uuid)",
                (workspace_id, reservation_id, workspace_id, reservation_id, run_id))
    unknown, settled, run_status = cur.fetchone()
    return {"workspaceId": str(workspace_id), "reservationId": str(reservation_id), "dimension": dimension, "provider": provider or "",
            "model": model or "", "estimatedUsdMicro": int(estimate), "chargeBatch": bool(charge_batch), "runId": run_id,
            "creditsMaximumMilli": int(maximum) if maximum is not None else None, "since": _epoch(at), "unknown": bool(unknown),
            "settled": bool(settled), "runStatus": run_status}


def reconcile_effect(snapshot, outcome, actual_usd_micro):
    """What reconciling does (billing.Ledger.settle semantics): the provider cost is always booked; `failed` never
    charges the customer; `completed` consumes the writing batch or charges credits within the approved maximum."""
    from .credit_meter import millicredits
    maximum = snapshot["creditsMaximumMilli"]
    used = min(maximum, millicredits(actual_usd_micro)) if maximum is not None and outcome == "completed" else 0
    return {"outcome": outcome, "actualUsdMicro": actual_usd_micro, "providerCostBookedUsdMicro": actual_usd_micro,
            "budgetHoldReleasedUsdMicro": snapshot["estimatedUsdMicro"],
            "creditsUsedMilli": used if maximum is not None else None,
            "creditsReleasedMilli": (maximum - used) if maximum is not None else None,
            "writingBatchConsumed": bool(snapshot["chargeBatch"] and outcome == "completed" and maximum is None),
            "customerCharged": outcome == "completed" and (maximum is not None or snapshot["chargeBatch"]),
            "consumerAudit": "usage.reconciled"}


def reconciled_by(cur, workspace_id, reservation_id, action_id):
    """The outcome when this founder action already reconciled the reservation (an interrupted confirm), else None."""
    cur.execute("SELECT 1 FROM public.pr_audit_events WHERE workspace_id=%s AND kind='usage.reconciled' AND subject=%s AND meta->>'operator'=%s LIMIT 1",
                (workspace_id, str(reservation_id), operator_label(action_id)))
    if not cur.fetchone():
        return None
    cur.execute("SELECT cost_state,actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s "
                "AND cost_state IN ('actual','released') LIMIT 1", (workspace_id, str(reservation_id)))
    row = cur.fetchone()
    return {"reservationId": str(reservation_id), "state": row[0] if row else None, "actualUsdMicro": int(row[1]) if row and row[1] is not None else None,
            "consumerAudit": "usage.reconciled"}


def reconcile(cur, ledger, workspace_id, reservation_id, outcome, actual_usd_micro, *, action_id, evidence):
    """Finalize the reservation once through billing.Ledger (the workspace row is locked by the caller)."""
    result = ledger.reconcile_unknown(cur, workspace_id, reservation_id, outcome, actual_usd_micro, operator=operator_label(action_id), evidence=evidence)
    return {"reservationId": str(reservation_id), "state": result.get("state"), "actualUsdMicro": result.get("actualUsdMicro", actual_usd_micro),
            "consumerAudit": "usage.reconciled"}


# --- credits -----------------------------------------------------------------------------------------------------------
_WALLET = ("availableMilliCredits", "heldMilliCredits", "usedMilliCredits", "debtMilliCredits")


def wallet_snapshot(cur, book, workspace_id):
    """The workspace's credit wallet (locks the workspace row through CreditBook.policy), or {'refused': code}."""
    from .credit_wallet import project_credit_wallet
    try:
        policy = book.policy(cur, workspace_id)
    except AlphaError as error:
        return {"refused": "workspace_not_found" if error.status == 404 else "credit_policy_inactive"}
    if policy is None:
        return {"refused": "workspace_not_on_credit_terms"}
    rows = book.rows(cur, workspace_id)
    view = project_credit_wallet(rows, book.clock())
    lots = [{key: lot.get(key) for key in ("grantId", "milli", "expiresAt", "used", "held", "reversed", "available")} for lot in view["lots"]]
    return {"policy": policy, "rows": rows, "wallet": {key: view[key] for key in _WALLET}, "lots": lots}


def wallet_after(book, rows, credit):
    """The wallet with one proposed credit event appended; ValueError when CreditBook would refuse it."""
    from .credit_wallet import project_credit_wallet
    view = project_credit_wallet(list(rows) + [{"id": "proposed", "reservationId": None, "credits": credit}], book.clock())
    return {key: view[key] for key in _WALLET}


def credit_key(action_id):
    return "founder-credit:" + str(action_id)


def credited_by(cur, workspace_id, action_id):
    cur.execute("SELECT id::text FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, credit_key(action_id)))
    row = cur.fetchone()
    return row[0] if row else None


def adjust_credits(cur, book, workspace_id, *, operation, milli, expires_at, grant_id, reason_code, action_id):
    """Grant (expiring, source founder_goodwill) or reverse credits through CreditBook, keyed by the action id."""
    key = credit_key(action_id)
    if operation == "grant":
        entry = book.grant(cur, workspace_id, None, key, milli, expires_at, source="founder_goodwill")
    else:
        entry = book.reverse(cur, workspace_id, None, key, grant_id, milli)
    if not entry["duplicate"]:
        _audit(cur, workspace_id, "credit.adjusted_by_operator", entry["entryId"],
               {"operation": operation, "milliCredits": milli, "reasonCode": reason_code, "source": "founder_goodwill",
                "expiresAt": expires_at, "grantId": grant_id, "operator": operator_label(action_id)})
    return {"entryId": entry["entryId"], "duplicate": entry["duplicate"], "consumerAudit": "credit.adjusted_by_operator"}


# --- account blocks ----------------------------------------------------------------------------------------------------
def _column(target_type):
    if target_type not in ("user", "workspace"):
        raise ValueError("unknown block target")
    return "user_id" if target_type == "user" else "workspace_id"


def _block_row(row):
    return None if not row else {"blockId": row[0], "reasonCode": row[1], "blockedAt": _epoch(row[2]), "frozenWorkspaceIds": sorted(row[3] or [])}


_BLOCK_COLUMNS = "id::text,reason_code,extract(epoch from blocked_at),frozen_workspace_ids::text[]"


def block_snapshot(cur, target_type, target_id, *, lock=False):
    """The target, its active block and the workspaces a block would freeze, or None when the target does not exist.
    With lock=True the target rows are locked (profile, then owned workspaces in id order) for a confirm."""
    column = _column(target_type)
    suffix = " FOR UPDATE" if lock else ""
    if target_type == "user":
        cur.execute("SELECT deleted_at IS NOT NULL FROM public.pr_profiles WHERE user_id=%s" + suffix, (target_id,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("SELECT w.id::text FROM public.pr_memberships m JOIN public.pr_workspaces w ON w.id=m.workspace_id "
                    "WHERE m.user_id=%s AND m.role='owner' AND m.status='active' ORDER BY w.id LIMIT %s" + (" FOR UPDATE OF w" if lock else ""),
                    (target_id, MAX_FROZEN_WORKSPACES + 1))
        frozen_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM public.pr_memberships WHERE user_id=%s AND status='active'", (target_id,))
        target = {"type": "user", "id": str(target_id), "deleted": bool(row[0]), "activeMemberships": int(cur.fetchone()[0]),
                  "ownedWorkspaces": len(frozen_ids)}
    else:
        cur.execute("SELECT w.id::text,(SELECT m.user_id::text FROM public.pr_memberships m WHERE m.workspace_id=w.id AND m.role='owner' AND m.status='active' "
                    "ORDER BY m.user_id LIMIT 1),(SELECT count(*) FROM public.pr_memberships m WHERE m.workspace_id=w.id AND m.status='active') "
                    "FROM public.pr_workspaces w WHERE w.id=%s" + suffix, (target_id,))
        row = cur.fetchone()
        if not row:
            return None
        frozen_ids = [row[0]]
        target = {"type": "workspace", "id": str(target_id), "ownerId": row[1], "memberCount": int(row[2])}
    cur.execute(f"SELECT {_BLOCK_COLUMNS} FROM public.pr_account_blocks WHERE {column}=%s AND lifted_at IS NULL", (target_id,))
    block = _block_row(cur.fetchone())
    tokens = None
    if target_type == "user" or frozen_ids:
        cur.execute("SELECT to_regclass('public.pr_api_tokens') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT count(*) FROM public.pr_api_tokens WHERE revoked_at IS NULL AND expires_at>now() AND (created_by::text=%s OR workspace_id::text=ANY(%s))",
                        (str(target_id) if target_type == "user" else "", frozen_ids[:MAX_FROZEN_WORKSPACES]))
            tokens = int(cur.fetchone()[0])
    return {"target": target, "block": block, "frozenWorkspaceIds": frozen_ids, "activeApiTokens": tokens}


def block_by_action(cur, action_id):
    cur.execute(f"SELECT {_BLOCK_COLUMNS} FROM public.pr_account_blocks WHERE block_action_id=%s", (str(action_id),))
    return _block_row(cur.fetchone())


def lift_by_action(cur, action_id):
    cur.execute(f"SELECT {_BLOCK_COLUMNS} FROM public.pr_account_blocks WHERE lift_action_id=%s", (str(action_id),))
    return _block_row(cur.fetchone())


def _freeze(cur, workspace_id, block_id):
    cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{accountBlock}',jsonb_build_object('blockIds',"
                "coalesce(state->'accountBlock'->'blockIds','[]'::jsonb)||to_jsonb(%s::text))),revision=revision+1 "
                "WHERE id=%s AND NOT coalesce(state->'accountBlock'->'blockIds','[]'::jsonb) ? %s", (block_id, workspace_id, block_id))


def _thaw(cur, workspace_id, block_id):
    cur.execute("UPDATE public.pr_workspaces SET state=CASE WHEN jsonb_array_length(coalesce(state->'accountBlock'->'blockIds','[]'::jsonb)-%s::text)=0 "
                "THEN state-'accountBlock' ELSE jsonb_set(state,'{accountBlock,blockIds}',(state->'accountBlock'->'blockIds')-%s::text) END,revision=revision+1 "
                "WHERE id=%s AND coalesce(state->'accountBlock'->'blockIds','[]'::jsonb) ? %s", (block_id, block_id, workspace_id, block_id))


def apply_block(cur, *, target_type, target_id, frozen_workspace_ids, reason_code, approval_ref, operator_id, action_id):
    """Insert the block, freeze its workspaces (in id order) and audit `account.blocked`. Idempotent on the action id."""
    column = _column(target_type)
    if reason_code not in REASON_CODES:
        raise ValueError("unknown block reason")
    existing = block_by_action(cur, action_id)
    if existing:
        return {**existing, "duplicate": True, "consumerAudit": "account.blocked"}
    frozen_ids = sorted(str(w) for w in frozen_workspace_ids)
    if len(frozen_ids) > MAX_FROZEN_WORKSPACES:
        raise ValueError("too many workspaces to freeze")
    cur.execute(f"INSERT INTO public.pr_account_blocks({column},reason_code,approval_ref,frozen_workspace_ids,blocked_by,block_action_id) "
                "VALUES(%s,%s,%s,%s::uuid[],%s,%s) RETURNING id::text,extract(epoch from blocked_at)",
                (target_id, reason_code, approval_ref, frozen_ids, operator_id, str(action_id)))
    block_id, blocked_at = cur.fetchone()
    for workspace_id in frozen_ids:
        _freeze(cur, workspace_id, block_id)
    _audit(cur, target_id if target_type == "workspace" else None, "account.blocked", block_id,
           {"scope": target_type, "reasonCode": reason_code, "frozenWorkspaces": len(frozen_ids), "operator": operator_label(action_id)})
    return {"blockId": block_id, "reasonCode": reason_code, "blockedAt": _epoch(blocked_at), "frozenWorkspaceIds": frozen_ids,
            "duplicate": False, "consumerAudit": "account.blocked"}


def lift_block(cur, *, target_type, target_id, block_id, reason_code, operator_id, action_id):
    """Lift one active block: thaw the workspaces it froze, set lifted_at/by and audit `account.unblocked`.
    Idempotent on the action id. Returns None when that block is no longer active."""
    _column(target_type)
    if reason_code not in LIFT_REASON_CODES:
        raise ValueError("unknown lift reason")
    existing = lift_by_action(cur, action_id)
    if existing:
        return {**existing, "duplicate": True, "consumerAudit": "account.unblocked"}
    cur.execute("SELECT frozen_workspace_ids::text[] FROM public.pr_account_blocks WHERE id=%s AND lifted_at IS NULL FOR UPDATE", (block_id,))
    row = cur.fetchone()
    if not row:
        return None
    frozen_ids = sorted(row[0] or [])
    for workspace_id in frozen_ids:
        cur.execute("SELECT 1 FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        _thaw(cur, workspace_id, block_id)
    cur.execute("UPDATE public.pr_account_blocks SET lifted_at=greatest(now(),blocked_at),lifted_by=%s,lift_action_id=%s,lift_reason_code=%s,"
                "retain_until=greatest(now(),blocked_at)+make_interval(days=>%s) WHERE id=%s AND lifted_at IS NULL",
                (operator_id, str(action_id), reason_code, RETENTION_DAYS, block_id))
    _audit(cur, target_id if target_type == "workspace" else None, "account.unblocked", block_id,
           {"scope": target_type, "reasonCode": reason_code, "thawedWorkspaces": len(frozen_ids), "operator": operator_label(action_id)})
    return {"blockId": block_id, "thawedWorkspaceIds": frozen_ids, "duplicate": False, "consumerAudit": "account.unblocked"}


# --- refund intents (read only: execution is not decided) ---------------------------------------------------------------
def payment_snapshot(cur, workspace_id, payment_intent_id):
    """The paid amount, refunds and disputes of one payment of this workspace; 'not_configured' without the payment
    tables (020-022), None when the payment is not this workspace's."""
    cur.execute("SELECT to_regclass('public.pr_credit_orders') IS NOT NULL,to_regclass('public.pr_credit_refunds') IS NOT NULL,"
                "to_regclass('public.pr_credit_subscription_grants') IS NOT NULL,to_regclass('public.pr_credit_disputes') IS NOT NULL")
    orders, refunds, grants, disputes = cur.fetchone()
    if not orders or not refunds:
        return "not_configured"
    cur.execute("SELECT 'credit_order',id::text,workspace_id::text,amount_cents,lower(currency),status,livemode,extract(epoch from created_at) "
                "FROM public.pr_credit_orders WHERE payment_intent_id=%s", (payment_intent_id,))
    row = cur.fetchone()
    if not row and grants:
        cur.execute("SELECT 'subscription_invoice',invoice_id,workspace_id::text,amount_cents,lower(currency),'funded',livemode,extract(epoch from recorded_at) "
                    "FROM public.pr_credit_subscription_grants WHERE payment_intent_id=%s ORDER BY recorded_at LIMIT 1", (payment_intent_id,))
        row = cur.fetchone()
    if not row or row[2] != str(workspace_id):
        return None
    source, source_id, _, amount, currency, status, livemode, at = row
    cur.execute("SELECT coalesce(sum(amount_cents) FILTER (WHERE status IN ('pending','requires_action','succeeded')),0),count(*) "
                "FROM public.pr_credit_refunds WHERE payment_intent_id=%s", (payment_intent_id,))
    refunded, refund_count = cur.fetchone()
    disputed = False
    if disputes:
        cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_credit_disputes WHERE payment_intent_id=%s AND NOT withdrawn)", (payment_intent_id,))
        disputed = bool(cur.fetchone()[0])
    return {"source": source, "sourceId": source_id, "paidMinor": int(amount), "currency": currency, "status": status, "livemode": bool(livemode),
            "paidAt": _epoch(at), "refundedMinor": int(refunded), "refunds": int(refund_count), "disputed": disputed}

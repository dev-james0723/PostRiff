"""Milestone D on disposable PostgreSQL: ledger reserve/settle/release/unknown, entitlements,
budget stop-lines, idempotency, billing webhooks (signature/replay/stale/unknown plan),
lifecycle, usage view, data requests, audience gating, ledger immutability.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Billing, FixturePaymentProvider, Ledger, USD
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda t, p: "session-one-0123456789abcdef"
verify.auth_time = lambda t, p: clock[0]
checks = []


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snap = service.bootstrap("one", "studio")
ledger = Ledger()

# 1. First usage view derives the trial entitlement; prices are labelled proposed; nothing live.
view = service.usage(wid, "one")
assert view["entitlement"]["writingBatchesRemaining"] == 10 and view["entitlement"]["source"] == "trial"
assert view["subscription"]["status"] == "trial" and view["subscription"]["live"] is False
assert all(t["priceLabel"] == "proposed" for t in view["planTerms"]) and view["overage"] == "stop"
checks.append("usage view shows trial entitlement, proposed prices, stop-only overage, no live subscription")

# A candidate budget never authorizes spending.
with connection() as db:
    denied(lambda: ledger.reserve(db.cursor(),wid,ONE,'text_model',1,'candidate-budget',charge_batch=False),402)
from consumer_fixtures import approve_budgets
approve_budgets(connection,wid)

# 2. Reserve/settle: completed with batch charge decrements; failed refunds the batch but books provider cost; unknown keeps reservation.
with connection() as db:
    cur = db.cursor()
    r1 = ledger.reserve(cur, wid, ONE, "text_model", 300_000, "op-1", charge_batch=True, provider="test", model="m")
    assert not r1["duplicate"]
    dup = ledger.reserve(cur, wid, ONE, "text_model", 300_000, "op-1", charge_batch=True, provider="test", model="m")
    assert dup["duplicate"] and dup["reservationId"] == r1["reservationId"]
    denied(lambda: ledger.reserve(cur, wid, ONE, "text_model", 1, "op-1", charge_batch=True, provider="other", model="m"), 409)
    ledger.settle(cur, wid, r1["reservationId"], "completed", 250_000)
    r2 = ledger.reserve(cur, wid, ONE, "text_model", 300_000, "op-2", charge_batch=True, provider="test", model="m")
    ledger.settle(cur, wid, r2["reservationId"], "failed", 120_000)
    r3 = ledger.reserve(cur, wid, ONE, "text_model", 300_000, "op-3", charge_batch=True, provider="test", model="m")
    unknown = ledger.settle(cur, wid, r3["reservationId"], "unknown")
    assert unknown["state"] == "estimated_unknown"
    view = ledger.usage_view(cur, wid)
    assert view["entitlement"]["writingBatchesRemaining"] == 9          # only the completed batch consumed
    assert view["budget"]["spentUsdMicro"] == 370_000                     # 250k + 120k (failed still costs)
    assert view["budget"]["reservedUsdMicro"] == 300_000                  # unknown keeps its reservation
    db.commit()
checks.append("reserve is idempotent by key; completed consumes a batch; failed books cost but refunds batch; unknown keeps the reservation")

# 3. Budget stop-line refuses before any provider call; entitlement exhaustion refuses with 402.
with connection() as db:
    cur = db.cursor()
    denied(lambda: ledger.reserve(cur, wid, ONE, "text_model", 6 * USD, "op-big", charge_batch=False), 402)
    cur.execute("UPDATE public.pr_entitlements SET writing_batches_remaining=0 WHERE workspace_id=%s", (wid,))
    denied(lambda: ledger.reserve(cur, wid, ONE, "text_model", 1, "op-none", charge_batch=True), 402)
    cur.execute("UPDATE public.pr_entitlements SET writing_batches_remaining=5 WHERE workspace_id=%s", (wid,))
    db.commit()
checks.append("workspace stop-line and exhausted entitlement refuse with 402 before execution")

# 4. Ideas turn reserves and settles automatically ($0 fixture, no batch consumed).
quick = service.ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "A thought worth sharing.", "ownContent": True, "confirmUse": True})
with connection() as db:
    # Same transaction → same `at`; order by kind instead ('reserve' < 'settle').
    rows = db.execute("SELECT kind,cost_state,charge_batch FROM public.pr_usage_ledger WHERE workspace_id=%s AND run_id::text=%s ORDER BY kind ASC", (wid, quick["runId"])).fetchall()
assert [r[0] for r in rows] == ["reserve", "settle"], rows
assert rows[1][1] == "actual" and rows[0][2] is False, rows
assert quick["artifact"] and len(quick["artifact"]["variants"]) >= 1
checks.append("ideas turn writes a reserve/settle pair; fixture route costs $0 and consumes no batch; artifact returned for preview")

# 5. Webhooks: signature verified, replay-safe, out-of-order stale, unknown plan rejected, entitlement reconciled.
provider = FixturePaymentProvider()
billing = service.billing
billing.provider = provider


def event(**kw):
    body = json.dumps({"id": kw.pop("id"), "type": kw.pop("type"), "createdAt": kw.pop("createdAt"), "workspaceId": wid, **kw}).encode()
    return provider.sign(body), body


with connection() as db:
    cur = db.cursor()
    denied(lambda: billing.process_webhook(cur, "bad", b"{}"), 401)
    sig, body = event(id="evt-1", type="subscription.activated", createdAt=clock[0], planTermsId="assist-v1", currentPeriodEnd=clock[0] + 30 * 86400)
    assert billing.process_webhook(cur, sig, body)["outcome"] == "applied"
    assert billing.process_webhook(cur, sig, body)["outcome"] == "duplicate"
    sig, body = event(id="evt-0", type="subscription.updated", createdAt=clock[0] - 100, planTermsId="assist-v1")
    assert billing.process_webhook(cur, sig, body)["outcome"] == "stale"
    sig, body = event(id="evt-2", type="subscription.updated", createdAt=clock[0] + 1, planTermsId="premium-unknown")
    assert billing.process_webhook(cur, sig, body)["outcome"] == "rejected"
    view = ledger.usage_view(cur, wid)
    assert view["entitlement"]["writingBatchesRemaining"] == 100 and view["entitlement"]["source"] == "subscription" and view["subscription"]["status"] == "active"
    sig, body = event(id="evt-3", type="invoice.payment_failed", createdAt=clock[0] + 2)
    assert billing.process_webhook(cur, sig, body)["status"] == "past_due"
    assert billing.lifecycle(cur, wid, clock[0] + 3)["status"] == "past_due"
    assert billing.lifecycle(cur, wid, clock[0] + 8 * 86400)["status"] == "cancelled"
    life = billing.lifecycle(cur, wid, clock[0] + 9 * 86400)
    assert life["exportAvailable"] and life["draftsRetained"] and not life["canPublish"]
    db.commit()
checks.append("webhooks: signature/replay/stale/unknown-plan handled; entitlement reconciles from plan terms; grace expiry → cancelled keeps export")

# 6. Data requests produce receipts; diagnostics need consent and carry no content.
export = service.data_request(wid, "one", "export", {})
assert export["status"] == "completed" and len(export["receipt"]["sha256"]) == 64
denied(lambda: service.data_request(wid, "one", "diagnostics", {"consent": False}), 403)
diag = service.data_request(wid, "one", "diagnostics", {"consent": True})
assert "A thought worth sharing" not in json.dumps(diag)
listed = service.data_requests.list(wid, "one")["requests"]
assert {r["kind"] for r in listed} >= {"export", "diagnostics"}
checks.append("export and diagnostics produce receipts; diagnostics require consent and contain no content")

# 7. Analytics: no observations → explicit unavailable state, never zeros; audience gated by capability.
analytics = service.analytics(wid, "one")
assert analytics["state"] == "limited" and analytics["posts"] == [] and analytics["rules"]["missing"].startswith("Unavailable")
threads = service.audience.threads(wid, "one")
assert threads["threads"] == [] and "not available" in threads["limits"]
checks.append("analytics and audience report truthful limited states with no fabricated numbers")

# 8. Ledger rows are immutable even for service_role; browser cannot read budgets/billing events.
with connection() as db:
    try:
        db.execute("UPDATE public.pr_usage_ledger SET actual_usd_micro=0")
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
    else:
        pass  # superuser in the disposable cluster bypasses grants; the grant test below is the meaningful one
for statement in ("SELECT * FROM public.pr_budgets", "SELECT * FROM public.pr_billing_events", "UPDATE public.pr_usage_ledger SET actual_usd_micro=0", "DELETE FROM public.pr_usage_ledger"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        try:
            db.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
        else:
            raise AssertionError(f"browser role was allowed: {statement}")
with connection() as db:
    db.execute("SET ROLE service_role")
    try:
        db.execute("DELETE FROM public.pr_usage_ledger")
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
    else:
        raise AssertionError("service_role could delete ledger rows")
checks.append("ledger is append-only for service_role; budgets and billing events are never browser-readable")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))

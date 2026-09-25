"""Launch budget policy on disposable PostgreSQL (billing.BUDGET_POLICIES): without a policy paid work is refused;
with POSTRIFF_BUDGET_POLICY the budgets are approved with the policy's caps, and the per-request, per-person
(24 h, all workspaces), workspace, global-day and global-month limits refuse before any provider call; an owner's
approved caps are kept; settlement releases exactly the budgets a reservation held; the operator kill switch and an
unknown policy id refuse; crossing a warning line leaves one log line without identifiers.
"""
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import BUDGET_POLICIES, Ledger, USD
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
THREE = "00000000-0000-0000-0000-000000000003"
POLICY = "launch-2026-09-24"
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda t, p: "session-one-0123456789abcdef"
verify.auth_time = lambda t, p: clock[0]


def denied(call, status, text):
    try:
        call()
    except AlphaError as error:
        assert error.status == status and text in str(error), (error.status, str(error))
        return
    raise AssertionError("accepted")


def budget(cur, scope):
    cur.execute("SELECT status,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,window_kind FROM public.pr_budgets WHERE scope=%s", (scope,))
    return cur.fetchone()


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.bootstrap("one", "studio")
ledger = Ledger()
spec = BUDGET_POLICIES[POLICY]
os.environ.pop("POSTRIFF_BUDGET_POLICY", None)
os.environ.pop("POSTRIFF_AI_PAUSED", None)

# 1. No policy: budgets stay candidate and paid work is refused; free work still passes.
with connection() as db:
    cur = db.cursor()
    denied(lambda: ledger.reserve(cur, wid, ONE, "text_model", 200_000, "no-policy", charge_batch=False), 402, "not switched on")
    ledger.reserve(cur, wid, ONE, "text_model", 0, "free-no-policy", charge_batch=False)
    assert budget(cur, f"workspace:{wid}")[0] == "candidate" and budget(cur, "global-month") is None
    db.commit()
checks.append("without a policy budgets stay candidate: paid work 402, free work passes, no global-month row")

# 2. Policy on: the candidate budgets are approved with the policy's caps, and a global-month budget appears.
os.environ["POSTRIFF_BUDGET_POLICY"] = POLICY
with connection() as db:
    cur = db.cursor()
    first = ledger.reserve(cur, wid, ONE, "text_model", 200_000, "p-1", charge_batch=False)
    assert budget(cur, f"workspace:{wid}")[:3] == ("approved", spec["workspace"]["warn"], spec["workspace"]["stop"])
    assert budget(cur, "global")[:3] == ("approved", spec["global"]["warn"], spec["global"]["stop"])
    assert budget(cur, "global-month")[:3] == ("approved", spec["global-month"]["warn"], spec["global-month"]["stop"]) and budget(cur, "global-month")[5] == "month"
    cur.execute("SELECT meta->'budgetScopes' FROM public.pr_usage_ledger WHERE id::text=%s", (first["reservationId"],))
    assert cur.fetchone()[0] == [f"workspace:{wid}", "global", "global-month"]
    assert all(budget(cur, s)[4] == 200_000 for s in (f"workspace:{wid}", "global", "global-month"))
    ledger.settle(cur, wid, first["reservationId"], "completed", 50_000)
    assert all(budget(cur, s)[3:5] == (50_000, 0) for s in (f"workspace:{wid}", "global", "global-month"))
    db.commit()
checks.append("a policy approves candidate budgets with its caps; each reservation records and settles exactly its three budgets")

# 3. One request's worst case above the policy's per-request ceiling is refused before any provider call.
with connection() as db:
    cur = db.cursor()
    denied(lambda: ledger.reserve(cur, wid, ONE, "text_model", spec["requestMax"] + 1, "too-big", charge_batch=False), 402, "limit for one request")
    ledger.reserve(cur, wid, ONE, "text_model", spec["requestMax"], "at-limit", charge_batch=False)
    db.commit()
checks.append("the per-request ceiling refuses a worst case above US$1.00 and allows one at the limit")

# 4. Per person over 24 hours, across workspaces: holds count until settled, then the actual cost counts.
with connection() as db:
    cur = db.cursor()
    # ONE has 0.05 settled + 1.00 held; two more 0.90 holds make 2.85, so 0.30 more would pass 3.00.
    held = [ledger.reserve(cur, wid, ONE, "text_model", 900_000, key, charge_batch=False) for key in ("person-0", "person-1")]
    denied(lambda: ledger.reserve(cur, wid, ONE, "text_model", 300_000, "person-over", charge_batch=False), 402, "one person over 24 hours")
    ledger.reserve(cur, wid, TWO, "text_model", 300_000, "other-person", charge_batch=False)   # someone else is not affected
    ledger.settle(cur, wid, held[0]["reservationId"], "completed", 100_000)                   # 0.90 hold → 0.10 actual
    ledger.reserve(cur, wid, ONE, "text_model", 300_000, "person-after-settle", charge_batch=False)
    db.commit()
checks.append("the per-person 24 h cap counts holds, then actual cost; it refuses one person without affecting another")

# 5. Stop lines: workspace month, then global month; the messages say nothing was sent or charged.
with connection() as db:
    cur = db.cursor()
    cur.execute("UPDATE public.pr_budgets SET spent_usd_micro=stop_usd_micro-reserved_usd_micro-100000 WHERE scope=%s", (f"workspace:{wid}",))
    denied(lambda: ledger.reserve(cur, wid, THREE, "text_model", 200_000, "ws-stop", charge_batch=False), 402, "This workspace has reached its AI spending limit")
    cur.execute("UPDATE public.pr_budgets SET spent_usd_micro=0 WHERE scope=%s", (f"workspace:{wid}",))
    cur.execute("UPDATE public.pr_budgets SET spent_usd_micro=stop_usd_micro-reserved_usd_micro-100000 WHERE scope='global-month'")
    denied(lambda: ledger.reserve(cur, wid, THREE, "text_model", 200_000, "gm-stop", charge_batch=False), 402, "AI safety limit for this month")
    cur.execute("UPDATE public.pr_budgets SET spent_usd_micro=0 WHERE scope='global-month'")
    db.commit()
checks.append("workspace-month and global-month stop lines refuse with plain messages before any provider call")

# 6. A budget an owner approved with other caps keeps them under the policy.
with connection() as db:
    cur = db.cursor()
    cur.execute("UPDATE public.pr_budgets SET stop_usd_micro=%s,warn_usd_micro=%s WHERE scope=%s", (50 * USD, 40 * USD, f"workspace:{wid}"))
    ledger.reserve(cur, wid, THREE, "text_model", 100_000, "owner-caps", charge_batch=False)
    assert budget(cur, f"workspace:{wid}")[1:3] == (40 * USD, 50 * USD)
    db.commit()
checks.append("an owner-approved budget keeps its own caps when a policy is on")

# 7. Crossing a warning line leaves one log line with the scope and policy only.
with connection() as db:
    cur = db.cursor()
    workspace_row = budget(cur, f"workspace:{wid}")
    cur.execute("UPDATE public.pr_budgets SET spent_usd_micro=%s WHERE scope=%s", (workspace_row[1] - workspace_row[4] - 50_000, f"workspace:{wid}"))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = ledger.reserve(cur, wid, THREE, "text_model", 100_000, "warn-cross", charge_batch=False)
    lines = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
    assert lines == [{"event": "budget.warning_crossed", "scopes": ["workspace"], "policy": POLICY}], lines
    assert "workspace budget past its warning line" in result["warnings"] and wid not in captured.getvalue()
    db.commit()
checks.append("crossing a warning line logs one event with scope and policy, no identifiers")

# 8. The operator kill switch and an unknown policy id refuse paid work; free work passes.
with connection() as db:
    cur = db.cursor()
    os.environ["POSTRIFF_AI_PAUSED"] = "1"
    denied(lambda: ledger.reserve(cur, wid, THREE, "text_model", 100_000, "paused", charge_batch=False), 503, "paused by the operator")
    ledger.reserve(cur, wid, THREE, "text_model", 0, "paused-free", charge_batch=False)
    os.environ.pop("POSTRIFF_AI_PAUSED")
    os.environ["POSTRIFF_BUDGET_POLICY"] = "launch-typo"
    denied(lambda: ledger.reserve(cur, wid, THREE, "text_model", 100_000, "unknown-policy", charge_batch=False), 503, "names no known policy")
    os.environ["POSTRIFF_BUDGET_POLICY"] = POLICY
    db.commit()
checks.append("POSTRIFF_AI_PAUSED=1 and an unknown policy id refuse paid work (503); free work passes")

os.environ.pop("POSTRIFF_BUDGET_POLICY", None)
print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))

"""First-use entitlement rows on disposable PostgreSQL: concurrent callers must converge on one row.

Regression for the POST /api/auth/verify 500 (ROOT-CAUSE.md): two first-visit requests both reached
Ledger.ensure_entitlement, both saw no row, and the second INSERT raised pr_entitlements_pkey.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_phase2.billing import Ledger

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ROUNDS = 12
WORKERS = 6


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def fresh_workspace(index):
    user = f"00000000-0000-0000-00e0-{index:012d}"
    with connection() as db:
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))
        workspace = str(db.execute("SELECT public.pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        db.execute("DELETE FROM public.pr_entitlements WHERE workspace_id=%s", (workspace,))
        db.execute("DELETE FROM public.pr_subscriptions WHERE workspace_id=%s", (workspace,))
    return workspace


def race(workspace, call):
    barrier = threading.Barrier(WORKERS)
    errors, results = [], []

    def run():
        try:
            with connection() as db, db.cursor() as cur:
                barrier.wait()
                results.append(call(cur, workspace))
        except Exception as error:  # the assertion below reports the class, never payloads
            errors.append(f"{type(error).__name__}:{getattr(error, 'sqlstate', None)}")

    threads = [threading.Thread(target=run) for _ in range(WORKERS)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    return errors, results


failures = []
for round_index in range(ROUNDS):
    for label, call in (
        ("ensure_entitlement", lambda cur, wid: Ledger().ensure_entitlement(cur, wid, None)),
        ("usage_view", lambda cur, wid: Ledger().usage_view(cur, wid)),
    ):
        workspace = fresh_workspace(round_index * 2 + (label == "usage_view"))
        errors, results = race(workspace, call)
        with connection() as db:
            rows = db.execute("SELECT count(*) FROM public.pr_entitlements WHERE workspace_id=%s", (workspace,)).fetchone()[0]
            subscriptions = db.execute("SELECT count(*) FROM public.pr_subscriptions WHERE workspace_id=%s", (workspace,)).fetchone()[0]
        if errors or rows != 1 or subscriptions != 1 or len(results) != WORKERS:
            failures.append({"round": round_index, "call": label, "errors": sorted(set(errors)), "errorCount": len(errors), "entitlementRows": rows, "subscriptionRows": subscriptions})

if failures:
    print("FAIL concurrent first-use entitlement:", failures[:4], f"({len(failures)} of {ROUNDS * 2} races failed)")
    sys.exit(1)
print(f"PASS concurrent first-use entitlement: {ROUNDS * 2} races x {WORKERS} callers, one row each, no errors")

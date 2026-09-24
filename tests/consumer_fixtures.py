"""Explicit local-fixture spending permission; never loaded by application code."""
def approve_budgets(connection, workspace_id):
    from postriff_phase2.billing import Ledger
    with connection() as db, db.cursor() as cur:
        for scope,kind in [('workspace:'+workspace_id,'month'),('global','day')]:
            Ledger()._budget(cur,scope,kind)
            cur.execute("UPDATE public.pr_budgets SET status='approved' WHERE scope=%s",(scope,))

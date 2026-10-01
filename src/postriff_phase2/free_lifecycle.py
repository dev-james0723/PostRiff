"""Effective lifecycle under the workspace lock; never erase subscription or wallet history.

Acquisition rollback affects new workspaces. Already-Free and paid v2 workspaces
keep their fallback, even with the flag off. Legacy paid allowances stay intact.
"""


def restore_free(cur, workspace_id):
    cur.execute("INSERT INTO public.pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,resets_at,source) "
                "SELECT %s,id,0,0,(entitlements->>'connectedAccounts')::integer,(entitlements->>'members')::integer,(entitlements->>'storageMb')::integer,NULL,'free' "
                "FROM public.pr_plan_terms WHERE id='free-v1' AND plan='free' "
                "ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=excluded.plan_terms_id,writing_batches_remaining=0,media_credits_remaining=0,"
                "connected_accounts=excluded.connected_accounts,members=excluded.members,storage_mb=excluded.storage_mb,resets_at=NULL,source='free',"
                "version=public.pr_entitlements.version+1,updated_at=now() WHERE public.pr_entitlements.plan_terms_id<>'free-v1' OR public.pr_entitlements.source<>'free'",
                (workspace_id,))


def lifecycle(cur, workspace_id, now, *, pricing_v2_enabled=False):
    """Derive before projections AND reservations/quotes, not only on a Usage GET.

    Caller holds the workspace lock. No provider I/O or new trial/subscription here.
    A denied caller may roll the transaction back; the next request re-derives it.
    """
    cur.execute("SELECT status,extract(epoch from grace_until),cancel_at_period_end,extract(epoch from current_period_end),plan_terms_id FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE", (workspace_id,))
    row = cur.fetchone()
    terms_id = row[4] if row else None
    if row:
        previous, grace_until, cancel_at_end, period_end, _ = row
        status = previous
        if status == 'trial' and (period_end is None or now >= float(period_end)):
            status = 'expired'
        elif status in ('past_due', 'grace') and grace_until and now >= float(grace_until):
            status = 'cancelled'
        elif status == 'active' and cancel_at_end and period_end and now >= float(period_end):
            status = 'cancelled'
        if status != previous:
            cur.execute("UPDATE public.pr_subscriptions SET status=%s,updated_at=now() WHERE workspace_id=%s", (status, workspace_id))
    else:
        cur.execute("SELECT extract(epoch from expires_at) FROM public.pr_trials WHERE workspace_id=%s", (workspace_id,))
        trial = cur.fetchone()
        status = 'trial' if trial and trial[0] is not None and now < float(trial[0]) else 'expired'
    cur.execute("SELECT plan_terms_id FROM public.pr_entitlements WHERE workspace_id=%s", (workspace_id,))
    entitlement = cur.fetchone()
    already_free = bool(entitlement and entitlement[0] == 'free-v1')
    ended = status in ('expired', 'cancelled')
    free = ended and (already_free or terms_id in ('creator-v1', 'starter-v1', 'studio-v2')
                      or (pricing_v2_enabled and terms_id in (None, 'trial-v1', 'free-v1')))
    if free:
        restore_free(cur, workspace_id)
    if free and not row:
        status = 'free' if not trial else status
    return {'status': status, 'plan': 'free' if free else terms_id or 'trial',
            'exportAvailable': True, 'draftsRetained': True,
            'canPublish': not free and status in ('trial', 'active', 'grace', 'past_due')}

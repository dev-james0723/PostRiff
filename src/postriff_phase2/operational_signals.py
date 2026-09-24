"""Server-only aggregate signals. No content, tenant identifiers or outbound notifications."""
import time


def snapshot(connection_factory, now=None):
    now = time.time() if now is None else now
    with connection_factory() as db, db.cursor() as cur:
        cur.execute('SET LOCAL statement_timeout = 3000')
        cur.execute("""SELECT
          count(*) FILTER (WHERE job->>'state' IN ('uncertain','submitting') AND coalesce((job->>'leaseUntil')::numeric,0)<%s),
          count(*) FILTER (WHERE job->>'state' IN ('queued','scheduled','claimed') AND coalesce((job->>'nextAt')::numeric,0)<%s),
          count(*) FILTER (WHERE job->>'state'='failed'),
          count(*) FILTER (WHERE job->>'state'='held')
          FROM public.pr_workspaces w CROSS JOIN LATERAL jsonb_array_elements(coalesce(w.state->'phase2'->'jobs','[]'::jsonb)) job""", (now, now-120))
        stuck, delayed, failed, held = cur.fetchone()
        cur.execute("SELECT count(*) FROM public.pr_agent_runs WHERE status='running' AND updated_at<to_timestamp(%s)", (now-600,))
        model_stuck = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_research_requests WHERE status='pending' AND created_at<to_timestamp(%s)", (now-600,))
        research_stuck = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_usage_ledger r WHERE kind='reserve' AND at<to_timestamp(%s) AND NOT EXISTS(SELECT 1 FROM public.pr_usage_ledger s WHERE s.reservation_id=r.id AND s.cost_state IN ('actual','released'))", (now-600,))
        unsettled = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_budgets WHERE status='approved' AND spent_usd_micro+reserved_usd_micro>=stop_usd_micro")
        budgets = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_billing_events WHERE outcome='rejected' AND processed_at>to_timestamp(%s)", (now-86400,))
        billing = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_notifications WHERE NOT sent AND created_at<to_timestamp(%s)", (now-600,))
        notifications = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_data_requests WHERE kind='deletion' AND status='requested'")
        deletions = cur.fetchone()[0]
    counts = dict(publicationUncertain=stuck, queueDelayed=delayed, publicationFailed=failed, publicationHeld=held,
                  modelStuck=model_stuck, researchStuck=research_stuck, costUnsettled=unsettled,
                  budgetStops=budgets, billingRejected24h=billing, notificationsUnsent=notifications, deletionPending=deletions)
    return {'status':'attention' if any(counts.values()) else 'ok', 'observedAt':now, 'counts':counts,
            'notificationDelivery':'not_configured'}

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
        # Writing runs only. The Rafii Agent Runtime's rows (agent:/task:/voice:) are not stalled models: a task plan stays
        # 'running' until the person finishes its steps, and the runtime closes its own dead turns and live sessions.
        cur.execute("SELECT count(*) FROM public.pr_agent_runs WHERE status='running' AND updated_at<to_timestamp(%s) "
                    "AND idempotency_key NOT LIKE 'agent:%%' AND idempotency_key NOT LIKE 'task:%%' AND idempotency_key NOT LIKE 'voice:%%'", (now-600,))
        model_stuck = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_research_requests WHERE status='pending' AND created_at<to_timestamp(%s)", (now-600,))
        research_stuck = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.pr_usage_ledger r WHERE kind='reserve' AND at<to_timestamp(%s) AND NOT EXISTS(SELECT 1 FROM public.pr_usage_ledger s WHERE s.reservation_id=r.id AND s.cost_state IN ('actual','released'))", (now-600,))
        unsettled = cur.fetchone()[0]
        cur.execute("SELECT count(*) FILTER (WHERE spent_usd_micro+reserved_usd_micro>=stop_usd_micro), "
                    "count(*) FILTER (WHERE spent_usd_micro+reserved_usd_micro>=warn_usd_micro AND spent_usd_micro+reserved_usd_micro<stop_usd_micro) "
                    "FROM public.pr_budgets WHERE status='approved'")
        budgets, budget_warnings = cur.fetchone()
        cur.execute("SELECT count(*) FROM public.pr_billing_events WHERE outcome='rejected' AND processed_at>to_timestamp(%s)", (now-86400,))
        billing = cur.fetchone()[0]
        from .coworker import flags
        from .email import V2_KINDS
        v2 = flags.enabled("RAFII_NOTIFICATIONS_V2_ENABLED")
        # With notifications v2 on, the legacy ledger still records the kinds v2 now sends (unsent by design).
        cur.execute("SELECT count(*) FROM public.pr_notifications WHERE NOT sent AND created_at<to_timestamp(%s) AND NOT (kind = ANY(%s))",
                    (now-600, sorted(V2_KINDS) if v2 else []))
        notifications = cur.fetchone()[0]
        delivery_backlog = delivery_dead = 0
        if v2:
            cur.execute("""SELECT count(*) FILTER (WHERE status IN ('pending','claimed') AND next_attempt_at < to_timestamp(%s)),
                                  count(*) FILTER (WHERE status='dead' AND updated_at > to_timestamp(%s))
                           FROM public.pr_notification_deliveries WHERE channel IN ('email','push')""", (now-600, now-86400))
            delivery_backlog, delivery_dead = cur.fetchone()
        cur.execute("SELECT count(*) FROM public.pr_data_requests WHERE kind='deletion' AND status='requested'")
        deletions = cur.fetchone()[0]
        # Growth Phase 0 queues (migration 032), only while POSTRIFF_METRIC_READS is on (after a rollback the leftover
        # rows are not an incident): fresh readings overdue by 10 min, backfill readings still pending a day after they
        # were scheduled, dead readings and failed imports in the last 24 h.
        reads_overdue = backfill_stale = reads_dead = imports_failed = purges_pending = 0
        # Disconnect purges still owed are a privacy obligation, counted whatever the growth flags say.
        cur.execute("SELECT to_regclass('public.pr_growth_purges') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT count(*) FROM public.pr_growth_purges WHERE requested_at < to_timestamp(%s)", (now-600,))
            purges_pending = cur.fetchone()[0]
        import os
        from .growth import metric_schedule
        cur.execute("SELECT to_regclass('public.pr_metric_reads') IS NOT NULL AND to_regclass('public.pr_history_imports') IS NOT NULL")
        if cur.fetchone()[0] and metric_schedule.enabled(os.environ):
            cur.execute("""SELECT count(*) FILTER (WHERE source='verification' AND status IN ('pending','claimed') AND due_at < to_timestamp(%s)),
                                  count(*) FILTER (WHERE source<>'verification' AND status IN ('pending','claimed') AND scheduled_at < to_timestamp(%s)),
                                  count(*) FILTER (WHERE status='dead' AND updated_at > to_timestamp(%s))
                           FROM public.pr_metric_reads""", (now-600, now-86400, now-86400))
            reads_overdue, backfill_stale, reads_dead = cur.fetchone()
            cur.execute("SELECT count(*) FROM public.pr_history_imports WHERE status='failed' AND updated_at > to_timestamp(%s)", (now-86400,))
            imports_failed = cur.fetchone()[0]
    counts = dict(publicationUncertain=stuck, queueDelayed=delayed, publicationFailed=failed, publicationHeld=held,
                  modelStuck=model_stuck, researchStuck=research_stuck, costUnsettled=unsettled,
                  budgetStops=budgets, budgetWarnings=budget_warnings, billingRejected24h=billing, notificationsUnsent=notifications, deletionPending=deletions,
                  notificationBacklog=delivery_backlog, notificationDead24h=delivery_dead,
                  metricReadsOverdue=reads_overdue, metricBackfillStale=backfill_stale, metricReadsDead24h=reads_dead,
                  historyImportsFailed24h=imports_failed, historyPurgesPending=purges_pending)
    return {'status':'attention' if any(counts.values()) else 'ok', 'observedAt':now, 'counts':counts,
            'notificationDelivery':'rafii_v2' if v2 else 'not_configured'}

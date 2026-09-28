"""Reviewed retention admission and flag-independent, durable bounded cleanup."""
import json
from . import analytics_retention, config, retention
from .store import json_value

SCOPE = 'shared:rafii-analytics-maintenance'
PROVIDER = 'rafii.local.analytics'
PARTITION = 'privacy-retention-v1'


def record(store, cur, workspace_id, actor_id, exposure_id, *, values=None):
    if not config.enabled('ANALYTICS_RETENTION', values) or not config.workspace_allowed(workspace_id, values):
        return {'status': 'disabled'}
    # The caller cannot choose or create its own legal authority. Ambiguous
    # reviewed policies abstain; grants are validated again by retain_exposure.
    cur.execute("""SELECT provider_id,version FROM public.pr_trend_source_policies
        WHERE scope_key=%s AND readiness='ready' AND revoked_at IS NULL
          AND valid_from<=clock_timestamp() AND expires_at>clock_timestamp()
          AND manifest->>'operation'=%s AND manifest->'analytics_retention'->>'enabled'='true'
        ORDER BY provider_id,version LIMIT 2 FOR SHARE""",
        ('workspace:'+workspace_id, analytics_retention.OPERATION))
    policies = cur.fetchall()
    if len(policies) != 1:
        return {'status': 'unavailable', 'reason': 'one_current_reviewed_analytics_authority_required'}
    return analytics_retention.retain_exposure(store,cur,workspace_id,actor_id,exposure_id,
        authority={'provider_id':policies[0][0], 'policy_version':policies[0][1]}, enabled=True)


def maintain(store, *, limit=25):
    """Called before the ordinary sweep, even with every rollout flag OFF."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('analytics_maintenance_bound')
    with store.transaction() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('trend-analytics-maintenance-v1',0))")
        if not cur.fetchone()[0]:
            return {'state':'busy'}
        # Avoid creating a maintenance scope on untouched/disabled installations.
        cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_trend_observations WHERE metric_id=%s AND purged_at IS NULL)",
                    (analytics_retention.VERSION,))
        if not cur.fetchone()[0]:
            return {'checked':0, 'physical_purge':retention.sweep(store,limit=100,cursor=cur)}
        store.ensure_scope(SCOPE,cursor=cur)
        cur.execute('INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                    (SCOPE,PROVIDER,PARTITION))
        cur.execute('SELECT cursor_value FROM public.pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE',
                    (SCOPE,PROVIDER,PARTITION))
        saved = cur.fetchone()[0] or {}
        result = analytics_retention.sweep(store,limit=limit,after=saved.get('after'),cursor=cur)
        if not result.get('deferred'):
            cur.execute("""UPDATE public.pr_trend_provider_cursors SET cursor_value=%s::jsonb,generation=generation+1,updated_at=clock_timestamp()
                WHERE scope_key=%s AND provider_id=%s AND partition_key=%s""",
                (json.dumps({'after':json_value(result.get('next_key'))}),SCOPE,PROVIDER,PARTITION))
        return result

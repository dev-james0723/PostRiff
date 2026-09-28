"""Bounded physical purge after immediate rights suppression; independent of feature flags."""
from .store import row, rows


def sweep(store, *, limit=100, cursor=None):
    if type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('invalid_purge_limit')
    with store.transaction(cursor) as cur:
        cur.execute('SELECT reads_ready FROM public.pr_trend_runtime_guard WHERE singleton FOR SHARE')
        if not row(cur)['reads_ready']:
            return {'purged_nodes':0,'deferred':'restore_in_progress'}
        # Frozen040's generic validity predicate predates independent storage
        # grants. Revoke a bounded page of newly unretainable evidence roots;
        # the existing canonical reverse cascade then removes their raw recipes
        # and dependent claims. Unrelated licensed aggregate branches survive.
        cur.execute("""WITH policy_storage AS MATERIALIZED (
            SELECT p.scope_key,p.provider_id,p.version,
                ('store_raw'=ANY(p.operations) AND 'store_raw'=ANY(c.operations)
                 AND postriff_private.trend_permits(p.rights,'store_raw',p.scope_key)) AS raw_allowed,
                ('store_metrics'=ANY(p.operations) AND 'store_metrics'=ANY(c.operations)
                 AND postriff_private.trend_permits(p.rights,'store_metrics',p.scope_key)) AS metrics_allowed
            FROM public.pr_trend_source_policies p JOIN public.pr_trend_provider_contracts c
            ON(c.provider_id,c.version)=(p.provider_id,p.provider_contract_version))
            SELECT n.scope_key,n.node_id FROM public.pr_trend_observations o
            JOIN public.pr_trend_nodes n ON(n.scope_key,n.node_id)=(o.scope_key,o.observation_id)
            JOIN policy_storage p ON(p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
            WHERE n.validity='valid' AND o.purged_at IS NULL AND n.available_at<=clock_timestamp()
            AND CASE WHEN o.kind='aggregate_metric' THEN
                NOT p.metrics_allowed OR NOT postriff_private.trend_permits(o.rights,'store_metrics',o.scope_key)
             ELSE coalesce(o.payload->>'text','')<>'' AND
                (NOT p.raw_allowed OR NOT postriff_private.trend_permits(o.rights,'store_raw',o.scope_key)) END
            ORDER BY n.retention_until,n.node_id LIMIT %s FOR UPDATE OF n SKIP LOCKED""",(limit,))
        storage_roots=rows(cur)
        for n in storage_roots:
            cur.execute("UPDATE public.pr_trend_nodes SET validity='revoked' WHERE scope_key=%s AND node_id=%s",
                (n['scope_key'],n['node_id']))
        # Prefilter invalid roots once and walk the reverse dependency index.
        # The final predicate is deliberately identical to the original purge
        # authorization: preselection alone can NEVER authorize erasure.
        cur.execute("""WITH RECURSIVE policy_state AS MATERIALIZED (
            SELECT p.scope_key,p.provider_id,p.version,p.rights,
                (NOT sc.enabled OR p.revoked_at IS NOT NULL OR p.expires_at<=clock_timestamp() OR p.valid_from>clock_timestamp()
                 OR p.readiness<>'ready' OR NOT 'retrieve'=ANY(p.operations)
                 OR c.revoked_at IS NOT NULL OR c.expires_at<=clock_timestamp() OR c.valid_from>clock_timestamp()
                 OR NOT 'retrieve'=ANY(c.operations)
                 OR NOT postriff_private.trend_permits(p.rights,'retrieve',p.scope_key)) AS unavailable
            FROM public.pr_trend_source_policies p
            JOIN public.pr_trend_provider_contracts c ON(c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
            JOIN public.pr_trend_scopes sc ON sc.scope_key=p.scope_key), source_state AS MATERIALIZED (
            SELECT o.scope_key,o.observation_id,
                (o.operation='delete' OR o.purged_at IS NOT NULL OR p.unavailable
                 OR NOT postriff_private.trend_permits(o.rights,'retrieve',o.scope_key)) AS unavailable
            FROM public.pr_trend_observations o
            JOIN policy_state p ON(p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)), roots(scope_key,node_id) AS (
            SELECT n.scope_key,n.node_id FROM public.pr_trend_nodes n JOIN public.pr_trend_scopes s USING(scope_key)
            WHERE n.validity IN ('revoked','stale','purged') OR n.retention_until<=clock_timestamp() OR NOT s.enabled
            UNION SELECT scope_key,observation_id FROM source_state WHERE unavailable
            UNION SELECT o.scope_key,o.observation_id FROM public.pr_trend_observations o
                JOIN public.pr_trend_deletion_tombstones t USING(scope_key,provider_id,source_identity_digest)
            UNION SELECT o.scope_key,o.observation_id FROM public.pr_trend_observations o
                JOIN public.pr_trend_author_tombstones t ON t.provider_id=o.provider_id
                AND t.author_digest=encode(sha256(convert_to(o.author_key,'UTF8')),'hex')
            UNION SELECT d.scope_key,d.node_id FROM public.pr_trend_dependencies d JOIN public.pr_trend_observations o
                ON(o.scope_key,o.observation_id)=(d.input_scope_key,d.input_node_id)
                JOIN policy_state p ON(p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
                WHERE NOT postriff_private.trend_permits(o.rights,'derive_metrics',o.scope_key)
                OR NOT postriff_private.trend_permits(p.rights,'derive_metrics',o.scope_key)
                OR NOT postriff_private.trend_permits(o.rights,'retain_derivatives',o.scope_key)
                OR NOT postriff_private.trend_permits(p.rights,'retain_derivatives',o.scope_key)
                OR (d.scope_key<>o.scope_key AND (NOT postriff_private.trend_permits(o.rights,'share_across_workspaces',o.scope_key)
                    OR NOT postriff_private.trend_permits(p.rights,'share_across_workspaces',o.scope_key)))
            UNION SELECT d.scope_key,d.node_id FROM public.pr_trend_dependencies d
                JOIN public.pr_trend_scopes s ON s.scope_key=d.scope_key WHERE d.scope_key<>d.input_scope_key
                AND NOT EXISTS(SELECT 1 FROM public.pr_trend_entitlements e WHERE e.workspace_id=s.workspace_id
                    AND e.scope_key=d.input_scope_key AND e.revoked_at IS NULL AND e.expires_at>clock_timestamp()
                    AND 'derive_metrics'=ANY(e.operations))
            UNION SELECT p.scope_key,p.projection_id FROM public.pr_trend_projections p JOIN public.pr_trend_method_versions m
                ON(m.method_id,m.version)=(p.method_id,p.method_version) WHERE m.revoked_at IS NOT NULL OR m.qualification='withdrawn'
            UNION SELECT r.scope_key,r.receipt_id FROM public.pr_trend_trust_receipts r JOIN public.pr_trend_method_versions m
                ON(m.method_id,m.version)=(r.method_id,r.method_version) WHERE m.revoked_at IS NOT NULL OR m.qualification='withdrawn'
        ), affected(scope_key,node_id) AS (
            SELECT scope_key,node_id FROM roots UNION
            SELECT d.scope_key,d.node_id FROM public.pr_trend_dependencies d JOIN affected a
                ON(d.input_scope_key,d.input_node_id)=(a.scope_key,a.node_id)), selected AS MATERIALIZED (
            SELECT n.scope_key,n.node_id FROM affected a JOIN public.pr_trend_nodes n USING(scope_key,node_id)
            WHERE n.validity<>'purged' AND n.available_at<=clock_timestamp()
            ORDER BY n.retention_until,n.node_id LIMIT %s)
        SELECT n.scope_key,n.node_id FROM selected candidate JOIN public.pr_trend_nodes n USING(scope_key,node_id)
            WHERE n.validity<>'purged' AND n.available_at<=clock_timestamp()
            AND NOT postriff_private.trend_node_valid(candidate.scope_key,candidate.node_id)
            AND (retention_until<=clock_timestamp() OR validity IN ('revoked','stale') OR EXISTS(
                SELECT 1 FROM public.pr_trend_observations o WHERE(o.scope_key,o.observation_id)=(n.scope_key,n.node_id))
                OR node_kind IN ('manifest','receipt','projection'))
            ORDER BY n.retention_until,n.node_id FOR UPDATE OF n SKIP LOCKED""",(limit,))
        candidates = rows(cur)
        for n in candidates:
            args = (n['scope_key'],n['node_id'])
            cur.execute("""UPDATE public.pr_trend_observations SET payload='{}',payload_digest=NULL,source_identity='sha256:'||source_identity_digest,
                revision_identity='sha256:'||encode(sha256(convert_to(revision_identity,'UTF8')),'hex'),
                rights='{}',provenance='{}',deletion_key='',native_item_id=NULL,author_key=NULL,author_status=NULL,canonical_url=NULL,
                metric_value=NULL,metric_null_reason=NULL,population=NULL,aggregation_semantics=NULL,purged_at=clock_timestamp()
                WHERE scope_key=%s AND observation_id=%s AND purged_at IS NULL""",args)
            cur.execute("UPDATE public.pr_trend_projections SET payload='{}',context_digest=NULL,draft_id=NULL,draft_revision=NULL WHERE scope_key=%s AND projection_id=%s",args)
            cur.execute("UPDATE public.pr_trend_trust_receipts SET payload='{}',verification_record='{}',verified_at=NULL WHERE scope_key=%s AND receipt_id=%s",args)
            cur.execute("UPDATE public.pr_trend_input_manifests SET digest=NULL,document_digest=NULL,recipe='{}' WHERE scope_key=%s AND manifest_id=%s",args)
            cur.execute("UPDATE public.pr_trend_manifest_chunks SET digest=NULL,payload='{}' WHERE scope_key=%s AND manifest_id=%s",args)
            cur.execute("UPDATE public.pr_trend_outbox SET payload='{}' WHERE scope_key=%s AND node_id=%s",args)
            cur.execute("UPDATE public.pr_trend_nodes SET validity='purged' WHERE scope_key=%s AND node_id=%s",args)
        cur.execute("""UPDATE public.pr_trend_deletion_tasks t SET state='done',updated_at=clock_timestamp() WHERE state='queued'
            AND NOT EXISTS(WITH RECURSIVE affected(scope_key,node_id) AS (
                SELECT o.scope_key,o.observation_id FROM public.pr_trend_observations o
                WHERE(o.scope_key,o.provider_id,o.source_identity_digest)=(t.scope_key,t.provider_id,t.source_identity_digest)
                UNION SELECT d.scope_key,d.node_id FROM public.pr_trend_dependencies d JOIN affected a
                ON(d.input_scope_key,d.input_node_id)=(a.scope_key,a.node_id))
                SELECT 1 FROM affected a JOIN public.pr_trend_nodes n USING(scope_key,node_id) WHERE n.validity<>'purged')""")
        # Retry controls are not an audit archive. Unknown spend stays in its
        # reservation, so erasing a terminal request never loses cost exposure.
        cur.execute("""SELECT scope_key,job_id FROM public.pr_trend_jobs WHERE payload<>'{}'::jsonb
            AND state IN ('succeeded','failed_terminal','cancelled','outcome_unknown')
            ORDER BY created_at,job_id LIMIT %s FOR UPDATE SKIP LOCKED""",(limit,))
        terminal = rows(cur)
        for job in terminal:
            cur.execute("UPDATE public.pr_trend_jobs SET payload='{}' WHERE scope_key=%s AND job_id=%s",(job['scope_key'],job['job_id']))
        cur.execute("""SELECT j.scope_key,j.job_id FROM public.pr_trend_jobs j
            JOIN public.pr_trend_source_policies p ON(p.scope_key,p.provider_id,p.version)=(j.scope_key,j.provider_id,j.source_policy_version)
            JOIN public.pr_trend_provider_contracts c ON(c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
            JOIN public.pr_trend_scopes s ON s.scope_key=j.scope_key
            WHERE j.state IN ('queued','retry_wait','leased','running') AND (
                NOT s.enabled OR p.revoked_at IS NOT NULL OR c.revoked_at IS NOT NULL OR p.readiness<>'ready'
                OR p.expires_at<=clock_timestamp() OR c.expires_at<=clock_timestamp()
                OR NOT postriff_private.trend_permits(p.rights,'retrieve',p.scope_key)
                OR j.created_at+p.max_retention_seconds*interval '1 second'<=clock_timestamp())
            ORDER BY j.created_at,j.job_id LIMIT %s FOR UPDATE OF j SKIP LOCKED""",(limit,))
        invalid_jobs = rows(cur)
        from .jobs import TrendJobs
        for job in invalid_jobs:
            TrendJobs(store).cancel(job['scope_key'],job['job_id'],cursor=cur)
        # Scrub pre-existing ingestion marker copies too; account DIDs are only
        # needed by the verified deletion handler before this event is emitted.
        cur.execute("""SELECT scope_key,event_id,payload FROM public.pr_trend_outbox
            WHERE event_type='trend.ingested' AND EXISTS(SELECT 1 FROM jsonb_object_keys(payload) k
                WHERE k NOT IN ('provider_id','coverage_epoch','decision_cutoff','observation_ids','pending_observation_indices','completeness','coverage_interval','marker_counts'))
            ORDER BY created_at,event_id LIMIT %s FOR UPDATE SKIP LOCKED""",(limit,))
        events = rows(cur)
        from .outbox import ingestion_payload
        from .store import bounded_json
        for event in events:
            cur.execute('UPDATE public.pr_trend_outbox SET payload=%s WHERE scope_key=%s AND event_id=%s',
                (bounded_json(ingestion_payload(event['payload'])),event['scope_key'],event['event_id']))
        return {'purged_nodes':len(candidates),'scrubbed_jobs':len(terminal)+len(invalid_jobs),'scrubbed_events':len(events)}

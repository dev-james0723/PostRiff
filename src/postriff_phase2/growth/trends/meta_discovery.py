"""Authenticated, bounded user discovery. Reads and submissions perform no I/O.

Selections are immutable and refer to an independently reviewed server grant.
Queue payloads contain only opaque request IDs and reviewed bounded controls.
Click idempotency lasts for the retained request; provider quota counters survive
request deletion and still bound a subsequent submission using the same key.
"""
from dataclasses import fields
from datetime import timedelta
import re
from uuid import uuid4

from .contracts import ContractError, digest, instant, iso, permits, uuid
from .jobs import TrendJobs
from .planner import FrontierPlanner
from .policy import SourcePolicy
from .providers import meta_public as meta
from .providers.registry import ProviderRegistry
from .service import envelope, error, ident
from .store import bounded_json, identity_digest, row, rows, trust_lock, utcnow

OPERATIONS = {'threads': 'keyword_search', 'instagram': 'hashtag_discovery', 'facebook': 'page_public_posts'}
COVERAGE = 'Selected public sample only; not all public posts or a population estimate.'


def validate_selection(provider, selection, proof=None):
    keys = {'threads': {'query', 'search_type'}, 'instagram': {'hashtag'}, 'facebook': {'reviewed_page_id'}}
    if provider not in keys or not isinstance(selection, dict) or set(selection) != keys[provider]:
        raise ContractError('meta_discovery_selection_invalid')
    if provider == 'threads':
        if selection['search_type'] not in ('TOP', 'RECENT'):
            raise ContractError('meta_search_type_invalid')
        return {'query': meta._query(selection['query']), 'search_type': selection['search_type']}
    if provider == 'instagram':
        return {'hashtag': meta._query(selection['hashtag'], hashtag=True)}
    page = selection['reviewed_page_id']
    if (not isinstance(page, str) or not re.fullmatch(r'[0-9]{1,40}', page)
            or proof is not None and page not in proof.reviewed_page_ids):
        raise ContractError('meta_discovery_page_unreviewed')
    return {'reviewed_page_id': page}


def validate_input(payload):
    if (not isinstance(payload, dict) or set(payload) != {'provider', 'selection', 'idempotency_key'}
            or not isinstance(payload['provider'], str)
            or not isinstance(payload['idempotency_key'], str)
            or not 1 <= len(payload['idempotency_key']) <= 200
            or any(ord(c) < 32 for c in payload['idempotency_key'])):
        raise ContractError('meta_discovery_input_invalid')
    return {**payload, 'selection': validate_selection(payload['provider'], payload['selection'])}


def load_request(store, request_id, policy, authorization_id, *, at, cursor=None):
    request_id = uuid(request_id)
    with store.transaction(cursor) as cur:
        cur.execute('''SELECT *,postriff_private.trend_meta_discovery_request_valid(request_id) AS active
            FROM public.pr_trend_meta_discovery_requests
            WHERE request_id=%s AND workspace_id=%s AND provider_id=%s
            AND authorization_id=%s AND source_policy_version=%s FOR SHARE''',
            (request_id, policy.scope_key[10:], policy.provider_id, authorization_id, policy.version))
        value = row(cur)
        if (not value or value.get('request_id') != request_id
                or value.get('workspace_id') != policy.scope_key[10:]
                or value.get('provider_id') != policy.provider_id
                or value.get('authorization_id') != authorization_id
                or value.get('source_policy_version') != policy.version
                or value.get('active') is not True
                or value.get('coverage_epoch') != 'discovery:' + request_id
                or instant(value['expires_at']) <= instant(at)
                or digest(value['selection']) != value['selection_digest']):
            raise ContractError('meta_discovery_request_unavailable')
        return value


def _admitted(service, store, cur, workspace_id, provider, at):
    from .providers.meta_runtime import MetaCollector, load_authorization
    if not getattr(store, 'meta_vault', None):
        store.meta_vault = getattr(getattr(service.hosted, 'oauth', None), 'vault', None)
    trust_lock(cur)
    cur.execute('''SELECT a.authorization_id,a.source_policy_version FROM public.pr_trend_meta_authorizations a
        WHERE a.workspace_id=%s AND a.provider_id=%s AND a.operation=%s
        AND postriff_private.trend_meta_authorization_valid(a.authorization_id)
        ORDER BY a.consent_at DESC,a.authorization_id DESC LIMIT 1 FOR SHARE''',
        (workspace_id, provider, OPERATIONS[provider]))
    grant = row(cur)
    if not grant: raise ContractError('meta_public_authorization_unavailable')
    scope = 'workspace:' + workspace_id
    stored = store._policy(cur, scope, provider, grant['source_policy_version'], at=at)
    required = {'retrieve', 'store_metrics', 'derive_metrics', 'retain_derivatives'}
    if (not required <= set(stored['operations']) or not required <= set(stored['contract_operations'])
            or any(not permits(stored['rights'], permission, scope, at) for permission in required)):
        raise ContractError('meta_discovery_metrics_rights_denied')
    manifest = stored['manifest']
    policy = SourcePolicy(**{f.name: manifest[f.name] for f in fields(SourcePolicy) if f.name in manifest})
    if manifest.get('meta_authorization_id') != grant['authorization_id']:
        raise ContractError('meta_public_authorization_unavailable')
    value, proof, _token = load_authorization(store, grant['authorization_id'], policy, at=at, cursor=cur)
    registry = ProviderRegistry()
    registry.register(meta.CAPABILITIES[provider, policy.operation], policy, MetaCollector(store, grant['authorization_id']))
    planner = FrontierPlanner(store, registry, values=service.values)
    policy, cap, controls, _ = planner.admitted(cur, scope, provider, policy.version, at=at)
    # This seam authorizes provider quota, never monetary collection or model use.
    if controls['reservation_microusd'] != 0:
        raise ContractError('meta_discovery_monetary_authority_denied')
    value = {**value, '_request_expires_at': iso(min(instant(value['expires_at']), instant(proof.expires_at),
        instant(proof.verified_at) + timedelta(seconds=900), instant(policy.expires_at),
        instant(stored['contract_end']), *(instant(policy.rights[p]['expires_at']) for p in required)))}
    return value, proof, policy, cap, controls


def _quota_available(cur, value, proof, selection):
    provider = value['provider_id']
    names = {'threads': ('threads_keyword_search',),
             'instagram': ('instagram_graph_request', 'instagram_distinct_hashtag_7d'),
             'facebook': ('facebook_public_page_read',)}[provider]
    for name in names:
        rule = value['quota_rules'].get(name)
        if (not isinstance(rule, dict) or set(rule) != {'limit', 'window_seconds'}
                or type(rule['limit']) is not int or rule['limit'] <= 0
                or type(rule['window_seconds']) is not int or not 1 <= rule['window_seconds'] <= 604800):
            raise ContractError('meta_quota_rule_unverified')
        distinct = name == 'instagram_distinct_hashtag_7d'
        if name != 'instagram_graph_request' and (rule['limit'] != proof.quota_limit or rule['window_seconds'] != proof.quota_window_seconds):
            raise ContractError('meta_quota_rule_unverified')
        subject = digest((proof.account_id + ':' + selection['hashtag']).casefold()) if distinct else None
        bucket = digest([provider, proof.app_id, proof.account_id, name])
        cur.execute('''SELECT count(DISTINCT subject_digest) AS used,bool_or(subject_digest=%s) AS repeated
            FROM public.pr_trend_meta_quota_events WHERE bucket_digest=%s
            AND reserved_at>clock_timestamp()-make_interval(secs=>%s)''', (subject, bucket, rule['window_seconds']))
        used = row(cur)
        if used['used'] >= rule['limit'] and not (distinct and used['repeated']):
            raise error('budget_or_rate_limited', 429)


def submit(service, workspace_id, token, payload):
    with service.transaction(workspace_id, token, 'edit') as (store, cur, _workspace, actor, _state, _scopes):
        try: body = validate_input(payload)
        except (ContractError, TypeError): raise error('invalid_request', 400) from None
        cur.execute("SELECT to_regclass('public.pr_trend_meta_discovery_requests') AS installed")
        if not row(cur)['installed']: raise error('source_unavailable', 503)
        # One workspace serialization order bounds concurrent queued clicks and
        # makes an idempotency replay independent of grant renewal or expiry.
        trust_lock(cur)
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('meta-discovery:' + workspace_id,))
        cur.execute('''SELECT * FROM public.pr_trend_meta_discovery_requests
            WHERE workspace_id=%s AND creator_id=%s AND idempotency_key=%s''',
            (workspace_id, actor, body['idempotency_key']))
        existing = row(cur)
        if existing:
            if existing['input_digest'] != digest(body): raise error('revision_conflict', 409)
            return envelope(_receipts(cur, workspace_id, existing['request_id'])[0], utcnow())
        at = utcnow()
        try:
            value, proof, policy, cap, controls = _admitted(service, store, cur, workspace_id, body['provider'], at)
            selection = validate_selection(body['provider'], body['selection'], proof)
        except ContractError: raise error('source_unavailable', 503) from None
        _quota_available(cur, value, proof, selection)
        cur.execute('''SELECT count(*) AS queued FROM public.pr_trend_meta_discovery_requests r
            JOIN public.pr_trend_jobs j ON j.scope_key='workspace:'||r.workspace_id::text AND j.job_id=r.job_id
            WHERE r.workspace_id=%s AND r.expires_at>clock_timestamp()
            AND j.state IN ('queued','leased','running','retry_wait')''', (workspace_id,))
        if row(cur)['queued'] >= 20: raise error('budget_or_rate_limited', 429)
        request_id = str(uuid4())
        epoch = 'discovery:' + request_id
        job_payload = {**FrontierPlanner.payload(policy, controls, epoch), 'discovery_request_id': request_id}
        job = TrendJobs(store).enqueue(policy.scope_key, 'trend.ingest', job_payload,
            provider_id=policy.provider_id, source_policy_version=policy.version,
            idempotency_key='meta-discovery:' + request_id, max_attempts=cap.max_attempts, cursor=cur)
        expires = iso(min(instant(at) + timedelta(seconds=policy.retention_seconds),
                          instant(value['_request_expires_at'])))
        cur.execute('''INSERT INTO public.pr_trend_meta_discovery_requests
            (request_id,workspace_id,creator_id,authorization_id,provider_id,source_policy_version,
             selection,selection_digest,input_digest,idempotency_key,coverage_epoch,job_id,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (request_id, workspace_id, actor, value['authorization_id'], policy.provider_id, policy.version,
             bounded_json(selection), digest(selection), digest(body), body['idempotency_key'], epoch, job['job_id'], expires))
        load_request(store, request_id, policy, value['authorization_id'], at=at, cursor=cur)
        return envelope(_receipts(cur, workspace_id, request_id)[0], at)


def _receipts(cur, workspace_id, request_id=None):
    cur.execute('''SELECT r.*,j.state AS job_state,result.observation_ids,result.retrieved_at,result.completeness,
        postriff_private.trend_meta_discovery_request_valid(r.request_id) AS active
        FROM public.pr_trend_meta_discovery_requests r
        LEFT JOIN public.pr_trend_jobs j ON j.scope_key='workspace:'||r.workspace_id::text AND j.job_id=r.job_id
        LEFT JOIN public.pr_trend_meta_discovery_results result USING(request_id)
        WHERE r.workspace_id=%s AND (%s::uuid IS NULL OR r.request_id=%s::uuid)
        ORDER BY r.created_at DESC,r.request_id DESC LIMIT 20''', (workspace_id, request_id, request_id))
    result = []
    for value in rows(cur):
        active = value['active'] is True
        state = value['job_state']
        status = ('unavailable' if not active else 'queued' if state in ('queued', 'retry_wait')
                  else 'running' if state in ('leased', 'running') else 'completed'
                  if state == 'succeeded' and value['retrieved_at'] else 'failed'
                  if state in ('failed_terminal', 'cancelled', 'outcome_unknown') else 'unavailable')
        sample, first, last, retrieved = None, None, None, None
        completeness = 'unknown'
        expires_at = value['expires_at']
        if status == 'completed':
            cur.execute('''SELECT count(*) AS sample_size,min(o.event_at) AS earliest_source_at,max(o.event_at) AS latest_source_at,
                min(least(o.retention_until,n.retention_until,p.expires_at,c.expires_at,a.expires_at,cred.access_expires_at,
                  (a.review->>'expires_at')::timestamptz,(a.review->>'verified_at')::timestamptz+interval '15 minutes',
                  (SELECT min((v->>'expires_at')::timestamptz) FROM jsonb_each(o.rights) AS rights(k,v)
                    WHERE k IN ('retrieve','store_metrics','derive_metrics','retain_derivatives')
                      OR k='store_raw' AND coalesce(o.payload->>'text','')<>''),
                  (SELECT min((v->>'expires_at')::timestamptz) FROM jsonb_each(p.rights) AS rights(k,v)
                    WHERE k IN ('retrieve','store_metrics','derive_metrics','retain_derivatives')
                      OR k='store_raw' AND coalesce(o.payload->>'text','')<>''))) AS expires_at
                FROM public.pr_trend_observations o
                JOIN public.pr_trend_nodes n ON (n.scope_key,n.node_id)=(o.scope_key,o.observation_id)
                JOIN public.pr_trend_source_policies p ON (p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
                JOIN public.pr_trend_provider_contracts c ON (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
                JOIN public.pr_trend_meta_authorizations a ON a.authorization_id::text=o.provenance->>'review_id'
                  AND 'workspace:'||a.workspace_id::text=o.scope_key
                JOIN public.pr_encrypted_credentials cred USING(workspace_id,connection_id)
                WHERE o.scope_key=%s AND o.provider_id=%s
                AND o.observation_id=ANY(%s::uuid[]) AND o.purged_at IS NULL
                AND postriff_private.trend_node_valid(o.scope_key,o.observation_id)
                AND postriff_private.trend_permits(o.rights,'store_metrics',o.scope_key)
                AND postriff_private.trend_permits(o.rights,'derive_metrics',o.scope_key)
                AND postriff_private.trend_permits(o.rights,'retain_derivatives',o.scope_key)
                AND EXISTS(SELECT 1 FROM public.pr_trend_source_policies p WHERE
                    (p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
                    AND ARRAY['store_metrics','derive_metrics','retain_derivatives']::text[] <@ p.operations
                    AND EXISTS(SELECT 1 FROM public.pr_trend_provider_contracts c
                      WHERE (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
                      AND ARRAY['store_metrics','derive_metrics','retain_derivatives']::text[] <@ c.operations)
                    AND postriff_private.trend_permits(p.rights,'store_metrics',p.scope_key)
                    AND postriff_private.trend_permits(p.rights,'derive_metrics',p.scope_key)
                    AND postriff_private.trend_permits(p.rights,'retain_derivatives',p.scope_key))''',
                ('workspace:' + workspace_id, value['provider_id'], value['observation_ids']))
            stats = row(cur)
            if stats['expires_at']:
                expires_at = iso(min(instant(expires_at), instant(stats['expires_at'])))
            if stats['sample_size'] != len(value['observation_ids']) or instant(expires_at) <= instant(utcnow()):
                status, active = 'unavailable', False
            else:
                sample = stats['sample_size']
                first, last = stats['earliest_source_at'], stats['latest_source_at']
                retrieved, completeness = value['retrieved_at'], value['completeness']
        result.append(dict(request_id=value['request_id'], provider=value['provider_id'],
            selection=value['selection'] if active else None, status=status, sample_size=sample,
            earliest_source_at=first, latest_source_at=last, retrieved_at=retrieved,
            created_at=value['created_at'], expires_at=expires_at, completeness=completeness, coverage=COVERAGE))
    return result


def read(service, workspace_id, token, request_id=None):
    if request_id is not None: request_id = ident(request_id)
    with service.transaction(workspace_id, token) as (store, cur, _workspace, _actor, _state, _scopes):
        at = utcnow()
        cur.execute("SELECT to_regclass('public.pr_trend_meta_discovery_requests') AS installed")
        if not row(cur)['installed']:
            return envelope({'requests': [], 'options': [dict(provider=p, enabled=False, reviewed_page_ids=[]) for p in OPERATIONS]}, at)
        trust_lock(cur)
        receipts = _receipts(cur, workspace_id, request_id)
        options = []
        from ...permissions import require
        from postriff_alpha.domain import AlphaError
        editable = False
        try:
            require(service.hosted.ideas._member(_workspace), 'edit')
            editable = True
        except (AlphaError, AttributeError): pass
        for provider in OPERATIONS:
            pages, enabled = [], False
            try:
                _value, proof, _policy, _cap, _controls = _admitted(service, store, cur, workspace_id, provider, at)
                enabled = editable
                if provider == 'facebook' and editable: pages = list(proof.reviewed_page_ids)
            except ContractError: pass
            options.append(dict(provider=provider, enabled=enabled, reviewed_page_ids=pages))
        return envelope({'requests': receipts, 'options': options}, at)


def record_batch(store, claim, batch, *, cursor):
    """Called in the ingestion commit, after canonical observation insertion."""
    request_id = claim['payload'].get('discovery_request_id')
    if not request_id: return
    from .providers.meta_runtime import load_authorization
    at = utcnow()
    stored = store._policy(cursor, claim['scope_key'], claim['provider_id'], claim['source_policy_version'], at=at)
    manifest = stored['manifest']
    policy = SourcePolicy(**{f.name: manifest[f.name] for f in fields(SourcePolicy) if f.name in manifest})
    aid = manifest['meta_authorization_id']
    load_authorization(store, aid, policy, at=at, cursor=cursor)
    request = load_request(store, request_id, policy, aid, at=at, cursor=cursor)
    if request['job_id'] != claim['job_id'] or request['coverage_epoch'] != claim['payload']['coverage_epoch']:
        raise ContractError('meta_discovery_job_mismatch')
    if len(batch.observations) > 1000: raise ContractError('meta_discovery_sample_bound')
    ids = set()
    for observation in batch.observations:
        provenance = observation['provenance']
        if (observation['scope_key'] != policy.scope_key or observation['provider_id'] != policy.provider_id
                or observation['source_policy_version'] != policy.version
                or provenance.get('discovery_request_id') != request_id
                or provenance.get('discovery_selection_digest') != request['selection_digest']
                or provenance.get('review_id') != aid):
            raise ContractError('meta_discovery_sample_mismatch')
        # Resolve the canonical ID from native revision identity, including
        # observations already stored by another search or scheduled sample.
        cursor.execute('''SELECT observation_id FROM public.pr_trend_observations WHERE scope_key=%s
            AND provider_id=%s AND source_identity_digest=%s AND revision_identity=%s
            AND payload_digest=%s AND purged_at IS NULL
            AND postriff_private.trend_node_valid(scope_key,observation_id)''',
            (policy.scope_key, policy.provider_id, identity_digest(observation['source_identity']),
             observation['revision_identity'], observation['payload_digest']))
        canonical = row(cursor)
        if not canonical: raise ContractError('meta_discovery_sample_unavailable')
        ids.add(canonical['observation_id'])
    cursor.execute('''INSERT INTO public.pr_trend_meta_discovery_results(request_id,observation_ids,completeness)
        VALUES(%s,%s,%s)''', (request_id, sorted(ids), 'gap' if batch.quarantined or batch.completeness == 'gap' else 'partial'))


def purge_expired(store, *, limit=100, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 1000: raise ContractError('meta_discovery_purge_bound')
    with store.transaction(cursor) as cur:
        cur.execute("SELECT to_regclass('public.pr_trend_meta_discovery_requests') AS installed")
        if not row(cur)['installed']: return 0
        trust_lock(cur)
        cur.execute('''DELETE FROM public.pr_trend_meta_discovery_requests WHERE request_id IN (
            SELECT r.request_id FROM public.pr_trend_meta_discovery_requests r
            WHERE NOT postriff_private.trend_meta_discovery_request_valid(r.request_id)
            ORDER BY r.expires_at,r.request_id LIMIT %s FOR UPDATE SKIP LOCKED) RETURNING request_id''', (limit,))
        return len(rows(cur))

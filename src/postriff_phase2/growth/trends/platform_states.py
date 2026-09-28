"""Read-only composition of explicitly linked, independently verified episodes.

The same read cutoff applies to discovery and every authenticated projection read.
Each receipt keeps its original decision cutoff. A relationship is lexical only;
this adapter neither merges episodes nor infers a global stage or person identity.
Service owns feature/qualification presentation gates and copies only the existing
wire platform_states and limitations fields. snapshots is internal provenance.
"""
from copy import deepcopy
import json

from . import contracts
from .store import TrendStorageError, json_value, trust_lock, utcnow

MAX_RELATIONS = 20


def _current(row, as_of, now, *, verified=False):
    return bool(row and row.get('validity') == 'valid' and isinstance(row.get('payload'), dict)
        and contracts.instant(row['available_at']) <= contracts.instant(as_of)
        and contracts.instant(row['expires_at']) > contracts.instant(now)
        and all(row.get('policy', {}).get(p) is True for p in ('derive_metrics','retain_derivatives'))
        and (not verified or row.get('verification_state') == 'verified'))


def _metadata(cur, row):
    cur.execute('''SELECT manifest_id::text,decision_cutoff FROM public.pr_trend_projections
        WHERE scope_key=%s AND projection_id=%s''', (row['scope_key'], row['projection_id']))
    saved = cur.fetchone()
    if not saved:
        raise TrendStorageError('platform_snapshot_unavailable')
    return saved[0], contracts.iso(contracts.instant(json_value(saved[1])))


def _source_inputs(store, cur, scope, manifest, cutoff):
    """Resolve the verified receipt's bounded source/member anchor layer.

    Old receipts use direct source references. New receipts have at most two
    explicit dependency-anchor manifests, each with at most1000 references.
    Relation manifests remain plain recipes and never use this receipt helper.
    """
    inputs = manifest['inputs']
    anchors = manifest.get('recipe', {}).get('dependency_anchors')
    if anchors is None:
        if len(inputs) > 1000:
            raise TrendStorageError('platform_source_input_bound')
        return {(r['scope_key'],str(r['node_id'])) for r in inputs}
    if (not isinstance(anchors,list) or not 1 <= len(anchors) <= 2
            or len({a['kind'] for a in anchors}) != len(anchors)
            or inputs != [{'scope_key':scope,'node_id':a['manifest_id']} for a in anchors]):
        raise TrendStorageError('platform_source_anchor_binding')
    sources = set()
    for anchor in anchors:
        identity = contracts.uuid(anchor['manifest_id'])
        recipe = {k:v for k,v in anchor.items() if k != 'manifest_id'}
        if (set(recipe) != {'schema','kind','input_digest'}
                or recipe['schema'] != 'rafii.trend-dependency-anchor.v1'
                or recipe['kind'] not in {'source','membership'}):
            raise TrendStorageError('platform_source_anchor_kind')
        saved = store.get_manifest(scope,identity,cursor=cur)
        children = saved['inputs']
        if (not 1 <= len(children) <= 1000 or saved.get('recipe') != recipe or saved.get('chunks')
                or saved.get('document_digest') != recipe['input_digest']
                or contracts.digest(children) != recipe['input_digest']
                or contracts.instant(saved['decision_cutoff']) > contracts.instant(cutoff)
                or any(r['scope_key'] != scope for r in children)):
            raise TrendStorageError('platform_source_anchor_mismatch')
        if recipe['kind'] == 'source':
            sources.update((r['scope_key'],contracts.uuid(r['node_id'])) for r in children)
    if not sources:
        raise TrendStorageError('platform_source_anchor_missing')
    return sources


def related_platform_states(store, *, workspace_id, actor_id, trend_id, as_of=None, cursor=None, limit=20):
    """Return existing wire states plus internal receipt refs, with no writes/dispatch.

    Bounds at most twenty relationships. Stale primary receipt bindings are omitted:
    a current card never silently borrows a relationship to an older primary card.
    Related states always come from the exact receipt recorded by the relationship,
    including when the other episode has a newer receipt. No global stage is returned.
    Unavailable primary evidence raises TrendStorageError; invalid links are omitted.
    """
    wid, actor, tid = (contracts.uuid(v) for v in (workspace_id, actor_id, trend_id))
    if type(limit) is not int or not 1 <= limit <= MAX_RELATIONS:
        raise ValueError('invalid_platform_state_bound')
    now = utcnow(); at = contracts.iso(contracts.instant(as_of or now))
    if contracts.instant(at) > contracts.instant(now):
        raise ValueError('future_platform_state_cutoff')
    with store.transaction(cursor) as cur:
        trust_lock(cur)
        scopes = store.authorized_scopes(wid, actor, cursor=cur)
        primary = store.get_projection(wid, actor, 'trend', tid, as_of=at, cursor=cur)
        if not _current(primary, at, now, verified=True):
            raise TrendStorageError('platform_primary_unavailable')
        primary_rid = contracts.uuid(primary['receipt_id'])
        cache = {}

        def snapshot(rid):
            if rid in cache:
                return cache[rid]
            receipt = store.get_receipt(wid, actor, rid, as_of=at, cursor=cur)
            if not _current(receipt, at, now, verified=True) or str(receipt.get('receipt_id')) != rid:
                raise TrendStorageError('platform_receipt_unavailable')
            p = receipt['payload']; states = p.get('platform_states')
            if not isinstance(states, list) or len(states) != 1:
                raise TrendStorageError('platform_snapshot_not_independent')
            state = states[0]
            if (not isinstance(state, dict) or not isinstance(state.get('platform'), str)
                    or not isinstance(state.get('inferred'), dict) or not isinstance(state.get('coverage'), dict)):
                raise TrendStorageError('platform_snapshot_unavailable')
            manifest_id, cutoff = _metadata(cur, receipt)
            if contracts.instant(cutoff) > contracts.instant(at):
                raise TrendStorageError('platform_snapshot_future')
            manifest = store.get_manifest(receipt['scope_key'], manifest_id, cursor=cur)
            cur.execute('SELECT qualification,revoked_at FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s',
                        (receipt['method_bundle']['method_id'],receipt['method_bundle']['version']))
            method = cur.fetchone()
            if not method or method[1] is not None or method[0] == 'withdrawn':
                raise TrendStorageError('platform_method_unavailable')
            # There is no durable qualified lifecycle-cohort resolver yet. A stored
            # bool or a model narrative cannot supply that missing artifact binding.
            # Keep each snapshot's coverage, but abstain from lifecycle claims.
            inferred = {'stage':None,'data_state':'collecting','confidence':'unknown',
                'calibration_state':'insufficient','evidence_refs':[],
                'explanation':'Lifecycle claims require this receipt, current method and a qualified cohort artifact.'}
            wire = {'platform':state['platform'],'inferred':inferred,'coverage':deepcopy(state['coverage'])}
            ref = {'platform':state['platform'], 'trend_id':contracts.uuid(p['trend_id']),
                'episode_id':contracts.uuid(p['episode_id']), 'trust_receipt_id':rid,
                'scope_key':receipt['scope_key'], 'decision_cutoff':cutoff,
                'available_at':receipt['available_at'], 'expires_at':receipt['expires_at'],
                'verification_state':receipt['verification_state'],'cohort_qualified':False,
                'method_state':'production' if method[0] == 'qualified' else 'shadow'}
            sources = _source_inputs(store,cur,receipt['scope_key'],manifest,cutoff)
            cache[rid] = (wire, ref, sources)
            return cache[rid]

        own, own_ref, _ = snapshot(primary_rid)
        if own_ref['trend_id'] != tid or own_ref['episode_id'] != primary['payload'].get('episode_id'):
            raise TrendStorageError('platform_primary_binding_changed')
        states = {own['platform']:own}; refs = {own['platform']:own_ref}
        cur.execute('''SELECT p.object_id::text FROM public.pr_trend_projections p
            WHERE p.scope_key=ANY(%s) AND p.kind='topic_association'
              AND p.payload->'topic_ids' @> %s::jsonb AND p.available_at<=%s
              AND NOT EXISTS (SELECT 1 FROM public.pr_trend_projections newer
                WHERE (newer.scope_key,newer.kind,newer.object_id)=(p.scope_key,p.kind,p.object_id)
                  AND newer.revision>p.revision AND newer.available_at<=%s)
            ORDER BY p.available_at DESC,p.object_id LIMIT %s''', (scopes,json.dumps([tid]),at,at,limit+1))
        candidates = cur.fetchall(); skipped = False
        for candidate in candidates[:limit]:
            try:
                edge = store.get_projection(wid,actor,'topic_association',candidate[0],as_of=at,cursor=cur)
                if not _current(edge,at,now):
                    raise TrendStorageError('platform_relation_unavailable')
                p = edge['payload']
                if (p.get('edge_type') != 'lexical_topic_association' or p.get('mode') != 'lexical_only'
                        or p.get('semantic_qualification') != 'unqualified'):
                    raise TrendStorageError('platform_relation_kind')
                for field in ('receipt_ids','topic_ids','episode_ids','evidence_refs'):
                    if not isinstance(p.get(field),list) or len(p[field]) != 2 or len(set(p[field])) != 2:
                        raise TrendStorageError('platform_relation_bound')
                    for identity in p[field]: contracts.uuid(identity)
                if (tid not in p['topic_ids'] or primary_rid not in p['receipt_ids']
                        or contracts.instant(p['available_at']) > contracts.instant(at)):
                    raise TrendStorageError('platform_relation_binding')
                manifest_id, _ = _metadata(cur,edge)
                manifest = store.get_manifest(edge['scope_key'],manifest_id,cursor=cur)
                if (manifest.get('recipe') != p or manifest.get('chunks')
                        or {(r['scope_key'],str(r['node_id'])) for r in manifest['inputs']}
                        != {(edge['scope_key'],rid) for rid in p['receipt_ids']}):
                    raise TrendStorageError('platform_relation_manifest_binding')
                pair = [snapshot(rid) for rid in p['receipt_ids']]
                if ({r[1]['trend_id'] for r in pair} != set(p['topic_ids'])
                        or {r[1]['episode_id'] for r in pair} != set(p['episode_ids'])
                        or {r[1]['platform'] for r in pair} != set(p.get('platforms',[]))
                        or len({r[1]['platform'] for r in pair}) != 2
                        or any(r[1]['scope_key'] != edge['scope_key'] for r in pair)
                        or any(not any((edge['scope_key'],e) in r[2] for e in p['evidence_refs']) for r in pair)):
                    raise TrendStorageError('platform_relation_snapshot_binding')
                for wire, ref, _ in pair:
                    # Deterministic newest relationship wins; no averaging/stage merge.
                    if wire['platform'] not in states:
                        states[wire['platform']] = wire
                        refs[wire['platform']] = {**ref,'association_id':edge['object_id']}
            except (contracts.ContractError, KeyError, TypeError, ValueError):
                skipped = True
        ordered = [own['platform'], *sorted(set(states)-{own['platform']})]
        snapshots = [refs[p] for p in ordered]
        limitations = ['Lexical topic association only; each platform retains its own episode and lifecycle.']
        limitations.extend(f"{r['platform']} snapshot: receipt {r['trust_receipt_id']}; decision cutoff {r['decision_cutoff']}." for r in snapshots)
        if skipped: limitations.append('Some stored relationships are unavailable under current evidence or bindings.')
        truncated = len(candidates) > limit
        if truncated: limitations.append('Related platform lookup reached its bounded page limit.')
        return {'as_of':at,'expires_at':min((r['expires_at'] for r in snapshots),key=contracts.instant),
            'platform_states':[states[p] for p in ordered],'snapshots':snapshots,'limitations':limitations,'truncated':truncated}

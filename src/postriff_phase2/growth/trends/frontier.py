"""Reviewed, bounded discovery requests; no provider or model I/O.

Worker seam: tick() before scanning ingest jobs; dispatch_context(job) before
claim, after start and before attachment. Use its partition/checkpoint with the
existing complete_batch generation fence. Claim still owns atomic reservation.
This worker-only API never establishes truth, narrative meaning or burst power.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, fields
from datetime import timedelta
import json
import os
import re
import unicodedata
import uuid

from . import config
from .contracts import ContractError, canonical, digest, instant, iso, permits
from .discovery import ROUTES
from .jobs import partition_key
from .outbox import TrendOutbox
from .planner import FrontierPlanner, integer, schedule_controls
from .policy import SourcePolicy, admit
from .store import row, rows, utcnow

VERSION = 'discovery-frontier-v1'
EVENT = 'trend.frontier.decision'
TERMINAL = {'succeeded', 'failed_terminal', 'cancelled', 'outcome_unknown'}


def normalized_query(value):
    if not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value):
        raise ContractError('frontier_query_invalid')
    value = ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()
    # Plain literal searches only. No domains, URLs, provider operators or code.
    if len(value) > 300 or re.search(r"[^\w\s#'’\-]", value) or re.search(r'\b(?:and|or|not)\b', value):
        raise ContractError('frontier_operator_denied')
    return value


def controls(manifest):
    c = manifest.get('frontier')
    if not isinstance(c, dict) or c.get('enabled') is not True:
        raise ContractError('frontier_disabled')
    c = dict(c)
    required = {'enabled', 'routes', 'categories', 'excluded_terms', 'query_version', 'ranking_version',
                'filter', 'window_seconds', 'budget_units', 'protected_units', 'required_watch_units',
                'watch_queries', 'allocation', 'rejected_sample_modulus'}
    if set(c) != required:
        raise ContractError('frontier_configuration_invalid')
    if (not isinstance(c['routes'], dict) or not c['routes'] or set(c['routes']) - set(ROUTES)
            or any(v not in ('sample', 'query') for v in c['routes'].values())
            or c['routes'].get('keyword_independent_sample') not in (None, 'sample')):
        raise ContractError('frontier_routes_invalid')
    for name in ('categories', 'excluded_terms', 'watch_queries'):
        if not isinstance(c[name], list) or len(c[name]) > 50 or any(not isinstance(s, str) or not 1 <= len(s) <= 300 for s in c[name]):
            raise ContractError('frontier_configuration_invalid')
    if not c['categories'] or any(not re.fullmatch(r'[a-z_]{1,40}', s) for s in c['categories']):
        raise ContractError('frontier_categories_required')
    for name in ('query_version', 'ranking_version'):
        if not isinstance(c[name], str) or not re.fullmatch(r'[\w.\-]{1,64}', c[name]):
            raise ContractError('frontier_version_required')
    # The reviewed native adapter filter is opaque to the frontier, bounded,
    # and part of both the epoch and cursor partition. No arbitrary nested text.
    if (not isinstance(c['filter'], dict) or len(c['filter']) > 10
            or any(not re.fullmatch(r'[a-z_]{1,40}', k) or type(v) not in (str, bool, int)
                   or isinstance(v, str) and not re.fullmatch(r'[\w.\-]{0,80}', v) for k, v in c['filter'].items())):
        raise ContractError('frontier_filter_invalid')
    for name, lo, hi in (('window_seconds', 60, 86400), ('budget_units', 1, 100), ('protected_units', 0, 100),
                         ('required_watch_units', 0, 100), ('rejected_sample_modulus', 1, 100)):
        integer(c[name], lo, hi, 'frontier_bounds')
    a = c['allocation']
    if (not isinstance(a, dict) or set(a) != {'watch', 'exploration', 'corroboration'}
            or any(type(v) is not int or not 0 <= v <= 100 for v in a.values()) or sum(a.values()) != 100):
        raise ContractError('frontier_allocation_invalid')
    c['watch_queries'] = sorted({normalized_query(q) for q in c['watch_queries']})
    return c


def allocate(c, units):
    protected = min(units, c['protected_units'])
    left = units - protected
    watch = min(left, max(c['required_watch_units'], left*c['allocation']['watch']//100))
    corroboration = min(left-watch, left*c['allocation']['corroboration']//100)
    exploration = min(left-watch-corroboration, (left*c['allocation']['exploration']+99)//100)
    return {'protected': protected, 'watch': watch, 'corroboration': corroboration, 'exploration': exploration,
            'coverage_reduced': units < c['budget_units'] or watch < c['required_watch_units'] or exploration == 0}


class DiscoveryFrontier:
    def __init__(self, store, registry, *, values=None, clock=utcnow):
        self.store, self.registry, self.values, self.clock = store, registry, values, clock
        self.planner = FrontierPlanner(store, registry, values=values, clock=clock)
        self.jobs, self.outbox = self.planner.jobs, TrendOutbox(store)

    def _authority(self, cur, scope, provider, version, at, *, budget=False):
        if not all(config.enabled(n, self.values) for n in ('INTELLIGENCE', 'RADAR', 'PROVIDER_OPERATIONS')):
            raise ContractError('dispatch_disabled')
        if budget:
            policy, cap, schedule, manifest = self.planner.admitted(cur, scope, provider, version, at=at)
        else:
            stored = self.store._policy(cur, scope, provider, version, at=at)
            manifest = stored['manifest']
            policy = SourcePolicy(**{k: v for k, v in manifest.items() if k in {f.name for f in fields(SourcePolicy)}})
            cap, registered, _ = self.registry.resolve(provider, policy.operation, scope, version, at=at)
            if canonical(asdict(policy)) != canonical(asdict(registered)) or stored['provider_contract_version'] != cap.version:
                raise ContractError('planner_contract_mismatch')
            schedule = schedule_controls(manifest)
            admit(cap, policy, at=at, requested_scope=scope,
                  enabled=config.dispatch_allowed(provider, policy.operation, self.values),
                  item_limit=schedule['max_items'], byte_limit=cap.max_response_bytes,
                  reservation_microusd=schedule['reservation_microusd'],
                  entitlement_current=self.planner._scope_allowed(cur, scope, at),
                  billable=cap.billable_unit != 'unmetered_live_bytes_bounded')
            cur.execute('SELECT * FROM public.pr_trend_source_health WHERE scope_key=%s AND provider_id=%s FOR SHARE', (scope, provider))
            h = row(cur)
            if h and (h['status'] == 'revoked' or h.get('next_allowed_at') and instant(h['next_allowed_at']) > instant(at)):
                raise ContractError('source_paused')
        for permission in ('store_metrics', 'derive_metrics', 'retain_derivatives'):
            self.store._policy(cur, scope, provider, version, permission=permission, at=at)
        cur.execute('SELECT reads_ready FROM public.pr_trend_runtime_guard WHERE singleton')
        if not row(cur)['reads_ready']:
            raise ContractError('frontier_restore_guard')
        if scope.startswith('workspace:'):
            cur.execute("SELECT state ? 'accountDeletion' AS deleted FROM public.pr_workspaces WHERE id=%s FOR SHARE", (scope[10:],))
            workspace = row(cur)
            if not workspace or workspace['deleted']:
                raise ContractError('workspace_access_denied')
        return policy, cap, schedule, controls(manifest)

    def _modes(self, cap, policy, at):
        known = {('bluesky', 'live_sample'): {'sample'}, ('mastodon', 'public_timeline'): {'sample'},
                 ('web', 'corroborate'): {'query'}}
        if (cap.provider_id, cap.operation) in known:
            return known[cap.provider_id, cap.operation]
        _, _, adapter = self.registry.resolve(cap.provider_id, cap.operation, policy.scope_key, policy.version, at=at)
        # New adapters must explicitly implement this narrow protocol. A policy
        # alone cannot upgrade an adapter which silently ignores the query.
        declared = getattr(adapter, 'discovery_modes', ())
        return set(declared) if isinstance(declared, (tuple, list)) and set(declared) <= {'sample', 'query'} else set()

    def _event(self, cur, scope, key):
        cur.execute('SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s AND event_key=%s', (scope, key))
        return row(cur)

    def _valid(self, cur, scope, node):
        cur.execute('SELECT retention_until,postriff_private.trend_node_valid(scope_key,node_id) AS valid FROM public.pr_trend_nodes WHERE scope_key=%s AND node_id=%s', (scope, node))
        n = row(cur)
        if not n or not n['valid'] or not self.store._storage_current(cur, scope, node):
            raise ContractError('frontier_evidence_unavailable')
        return n

    def _record(self, cur, scope, key, value, policy, at, dependencies=()):
        existing = self._event(cur, scope, key)
        if existing:
            return existing
        until = min(instant(policy.expires_at), instant(at)+timedelta(seconds=min(policy.retention_seconds, 86400)))
        for node in dependencies:
            until = min(until, instant(self._valid(cur, scope, node)['retention_until']))
        node = str(uuid.uuid4())
        self.store._node(cur, scope, node, 'frontier_control', at, iso(until))
        for dependency in sorted(set(dependencies)):
            self.store.add_dependency(scope, node, scope, dependency, cursor=cur)
        return self.outbox.enqueue(scope, key, EVENT, value, node_id=node, cursor=cur)

    def _evidence(self, cur, scope, ids, at, query):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 20:
            raise ContractError('frontier_evidence_required')
        try:
            ids = sorted({str(uuid.UUID(i)) for i in ids})
        except (ValueError, TypeError, AttributeError):
            raise ContractError('frontier_evidence_invalid') from None
        authors, native_seed = set(), False
        for sid in ids:
            self._valid(cur, scope, sid)
            cur.execute('SELECT * FROM public.pr_trend_observations WHERE scope_key=%s AND observation_id=%s', (scope, sid))
            o = row(cur)
            if not o or instant(o['available_at']) > instant(at) or o['payload'].get('is_repost'):
                raise ContractError('frontier_evidence_unavailable')
            for permission in ('derive_metrics', 'retain_derivatives'):
                self.store._policy(cur, scope, o['provider_id'], o['source_policy_version'], permission=permission, at=at)
                if not permits(o['rights'], permission, scope, at):
                    raise ContractError('frontier_evidence_rights')
            if query and o['payload'].get('text'):
                self.store._policy(cur, scope, o['provider_id'], o['source_policy_version'], permission='store_raw', at=at)
                if not permits(o['rights'], 'store_raw', scope, at):
                    raise ContractError('frontier_evidence_rights')
            if o['kind'] == 'trend_seed':
                native_seed = True
            if o.get('author_status') == 'known' and o.get('author_key'):
                authors.add((o['provider_id'], o['author_key']))
        if not native_seed and len(authors) < 2:
            raise ContractError('frontier_diversity_insufficient')
        return ids, 'platform_seed' if native_seed else 'diverse_observations'

    def _stored_proposals(self, cur, scope, at, provider=None, version=None):
        """Read bounded native detail manifests, not display glosses/model labels."""
        cur.execute("""SELECT * FROM (SELECT DISTINCT ON(kind,object_id) * FROM public.pr_trend_projections
            WHERE scope_key=%s AND kind IN ('language_pattern','genome') AND available_at<=%s
            ORDER BY kind,object_id,revision DESC) p ORDER BY available_at DESC,projection_id LIMIT 20""", (scope, at))
        proposals = []
        for p in rows(cur):
            try:
                state = self.store._status(cur, p)
                if state['validity'] != 'valid' or not state['policy']['derive_metrics'] or not state['policy']['retain_derivatives']:
                    continue
                saved = self.store.get_manifest(scope, p['manifest_id'], cursor=cur)
                codec = saved['recipe'].get('detail_codec', {})
                if codec.get('codec') != 'json-fragments-v1' or len(saved['chunks']) != codec.get('chunk_count'):
                    continue
                if digest({'inputs': saved['inputs'], 'recipe': saved['recipe'], 'chunks': [c['digest'] for c in saved['chunks']]}) != saved['digest']:
                    continue
                fragments = []
                for i, chunk in enumerate(saved['chunks']):
                    if chunk['ordinal'] != i or digest(chunk['payload']) != chunk['digest']:
                        raise ContractError('frontier_detail_mismatch')
                    fragments.append(chunk['payload']['json'])
                document = json.loads(''.join(fragments))
                checksum = digest({k: v for k, v in document.items() if k != 'manifest_digest'})
                if checksum != document['manifest_digest'] or checksum != saved['document_digest'] or checksum != codec.get('pure_manifest_digest'):
                    continue
                details = document['details']
                items = details.get('patterns', []) if p['kind'] == 'language_pattern' else details.get('context_and_seeds', {}).get('seeds', [])
                for item in items[:50]:
                    expression = item.get('expression')
                    if p['kind'] == 'genome':
                        spans = item.get('original_spans', [])
                        expression = spans[0].get('text') if spans else None
                    if not isinstance(expression, str) or not expression:
                        continue
                    candidate = {'route': 'hashtag' if item.get('kind') == 'hashtag' else 'related_topic',
                        'query': expression, 'language': item.get('language', 'und'), 'category': 'general',
                        'evidence_ids': item.get('evidence_refs', [])[:20], 'projection_id': p['projection_id']}
                    if provider:
                        # Previously admitted overlapping evidence can seed the
                        # next generation; text remains in this exact scope.
                        cur.execute("""SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s
                            AND event_key LIKE 'frontier-request:%%' AND payload->>'provider_id'=%s
                            AND payload->>'policy_version'=%s AND payload->'evidence_ids' ?| %s
                            ORDER BY created_at DESC,event_id LIMIT 5""", (scope,provider,version,candidate['evidence_ids']))
                        for parent in rows(cur):
                            if parent['payload'].get('query_digest') != digest([scope, normalized_query(expression)]):
                                self._valid(cur, scope, parent['node_id'])
                                candidate['parent_id'] = parent['payload']['request_id']
                                break
                    proposals.append(candidate)
                    if len(proposals) == 50:
                        return proposals
            except (ContractError, KeyError, TypeError, ValueError):
                continue
        return proposals

    def produce(self, scope, provider, version, proposals=(), *, cursor=None):
        if not isinstance(proposals, (list, tuple)) or len(proposals) > 50:
            raise ContractError('frontier_proposal_bound')
        at = self.clock()
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('frontier|'+scope+'|'+provider,))
            policy, cap, schedule, c = self._authority(cur, scope, provider, version, at, budget=True)
            start = instant(schedule['start_at'])
            slot = int((instant(at)-start).total_seconds()//schedule['interval_seconds'])
            if not 0 <= slot < schedule['max_samples']:
                return {'status': 'outside_schedule', 'jobs': []}
            epoch = digest([VERSION, scope, provider, version, c])
            cycle = digest([epoch, slot])
            # Align intervals to the slot so retries of the same cycle are stable.
            end = iso(start+timedelta(seconds=slot*schedule['interval_seconds']))
            begin = iso(instant(end)-timedelta(seconds=c['window_seconds']))
            allocation_key = 'frontier-allocation:'+cycle
            allocation_event = self._event(cur, scope, allocation_key)
            if allocation_event:
                self._valid(cur, scope, allocation_event['node_id'])
                quotas = allocation_event['payload']['allocation']
            else:
                cur.execute('SELECT * FROM public.pr_trend_budget_limits WHERE budget_key=ANY(%s)', (schedule['budget_keys'],))
                budgets = rows(cur)
                units = c['budget_units']
                cost = schedule['reservation_microusd']
                if cost:
                    for b in budgets:
                        cur.execute("""SELECT coalesce(sum((payload->>'reservation_microusd')::bigint),0) AS n
                            FROM public.pr_trend_jobs WHERE state IN ('queued','retry_wait')
                            AND payload->'budget_keys' ? %s""", (b['budget_key'],))
                        pending = row(cur)['n']
                        units = min(units, max(0, (b['cap_micro_usd']-b['reserved_micro_usd']-b['settled_micro_usd']-b['unknown_micro_usd']-pending)//cost))
                quotas = allocate(c, units)
                allocation_event = self._record(cur, scope, allocation_key, {'record': 'allocation', 'cycle': cycle,
                    'provider_id': provider, 'policy_version': version, 'configuration_digest': epoch,
                    'allocation': quotas, 'window_start': begin, 'window_end': end,
                    'reservation_microusd_per_attempt': cost, 'budget_keys': schedule['budget_keys'],
                    'reservation_state': 'intent_only_until_job_claim', 'counts_scope': 'bounded_candidate_sample'}, policy, at)
            cur.execute("SELECT * FROM public.pr_trend_outbox WHERE scope_key=%s AND event_type=%s AND payload->>'cycle'=%s AND payload->>'record'='decision' ORDER BY event_key LIMIT 101", (scope, EVENT, cycle))
            previous = [e for e in rows(cur) if e['payload'].get('record') == 'decision']
            used = Counter(e['payload']['bucket'] for e in previous if e['payload']['decision'] == 'admitted')
            entries = list(proposals)
            entries += [{'route': 'watch', 'query': q, 'category': 'general'} for q in c['watch_queries']]
            if 'keyword_independent_sample' in c['routes']:
                entries.insert(0, {'route': 'keyword_independent_sample', 'query': '', 'category': 'general'})
            entries.sort(key=lambda p: 0 if isinstance(p, dict) and p.get('route') == 'watch' else 1 if isinstance(p, dict) and p.get('route') in ('corroboration','refresh') else 2)
            result = {'status': 'ok', 'cycle': cycle, 'allocation': quotas, 'jobs': [], 'decisions': []}
            for proposal in entries[:100]:
                if len(previous) >= 100:
                    result['truncated'] = True
                    break
                # Digests are scoped even for rejected/unsafe prose; none of it
                # enters the evaluation sample or an outbox payload.
                fingerprint = digest([scope, provider, version, proposal])
                key = 'frontier-decision:'+digest([cycle, fingerprint])
                existing = self._event(cur, scope, key)
                if existing:
                    result['decisions'].append(existing['payload'])
                    if existing['payload'].get('job_id'):
                        result['jobs'].append(existing['payload']['job_id'])
                    continue
                route = proposal.get('route') if isinstance(proposal, dict) else None
                route = route if route in ROUTES else 'unknown'
                language = proposal.get('language', 'und') if isinstance(proposal, dict) else 'und'
                language = language if isinstance(language, str) and re.fullmatch(r'[a-zA-Z0-9-]{1,35}', language) else 'und'
                bucket = 'watch' if route == 'watch' else 'corroboration' if route in ('corroboration','refresh') else 'exploration'
                value = {'record': 'decision', 'candidate_id': fingerprint, 'cycle': cycle,
                    'provider_id': provider, 'policy_version': version, 'configuration_digest': epoch,
                    'route': route, 'language': language, 'bucket': bucket, 'decision': 'dropped',
                    'reason': 'frontier_proposal_invalid', 'sampling_probability': None,
                    'depth': 0, 'parent_id': None, 'root_id': None, 'evaluated_at': at}
                dependencies = [allocation_event['node_id']]
                try:
                    if not isinstance(proposal, dict) or set(proposal)-{'route','query','language','community','category','parent_id','evidence_ids','projection_id','priority','sampling_probability'}:
                        raise ContractError('frontier_proposal_invalid')
                    query = normalized_query(proposal.get('query'))
                    value['query_digest'] = digest([scope, query])
                    if proposal.get('category') not in c['categories'] or any(t.casefold() in query for t in c['excluded_terms']):
                        raise ContractError('frontier_category_excluded')
                    mode = c['routes'].get(route)
                    if mode not in self._modes(cap, policy, at):
                        raise ContractError('frontier_query_capability_unknown')
                    if (mode == 'sample' and query) or (mode == 'query' and not query):
                        raise ContractError('frontier_mode_mismatch')
                    community = proposal.get('community')
                    if community is not None and (not isinstance(community, str) or not re.fullmatch(r'[\w-]{1,64}', community)):
                        raise ContractError('frontier_community_invalid')
                    priority = integer(proposal.get('priority', 0), 0, 10, 'frontier_priority_invalid')
                    probability = proposal.get('sampling_probability')
                    if probability is not None and (type(probability) not in (int,float) or not 0 < probability <= 1):
                        raise ContractError('frontier_probability_invalid')
                    value['sampling_probability'] = probability
                    parent = None
                    if proposal.get('parent_id'):
                        parent_id = proposal['parent_id']
                        if not isinstance(parent_id, str) or not re.fullmatch(r'[a-f0-9]{64}', parent_id):
                            raise ContractError('frontier_parent_invalid')
                        parent = self._event(cur, scope, 'frontier-request:'+parent_id)
                        if not parent or parent['payload']['provider_id'] != provider or parent['payload']['policy_version'] != version:
                            raise ContractError('frontier_parent_unavailable')
                        self._valid(cur, scope, parent['node_id'])
                        value.update(parent_id=parent_id, root_id=parent['payload']['root_id'], depth=parent['payload']['depth']+1)
                        dependencies.append(parent['node_id'])
                        if value['depth'] > 2:
                            raise ContractError('frontier_depth_limit')
                        cur.execute("""SELECT count(*) AS n FROM public.pr_trend_outbox WHERE scope_key=%s
                            AND event_key LIKE 'frontier-request:%%' AND payload->>'root_id'=%s AND payload->>'depth'=%s""",
                            (scope, value['root_id'], str(value['depth'])))
                        if row(cur)['n'] >= 5:
                            raise ContractError('frontier_child_limit')
                    if route == 'keyword_independent_sample':
                        if parent or proposal.get('evidence_ids'):
                            raise ContractError('frontier_independent_seed_required')
                        evidence, reason = [], 'independent_sample'
                    elif route == 'watch':
                        if query not in c['watch_queries']:
                            raise ContractError('frontier_watch_not_reviewed')
                        evidence, reason = [], 'reviewed_watch'
                    else:
                        evidence, reason = self._evidence(cur, scope, proposal.get('evidence_ids'), at, query)
                        dependencies.extend(evidence)
                    if proposal.get('projection_id'):
                        projection_id = str(uuid.UUID(proposal['projection_id']))
                        self._valid(cur, scope, projection_id)
                        dependencies.append(projection_id)
                    request = {'scope_key': scope, 'provider_id': provider, 'policy_version': version,
                        'route': route, 'query_digest': value['query_digest'], 'language': language, 'community': community,
                        'configuration_digest': epoch, 'window_start': begin, 'window_end': end}
                    request_id = digest(request)
                    value.update(request_id=request_id, root_id=value['root_id'] or request_id)
                    if self._event(cur, scope, 'frontier-request:'+request_id):
                        raise ContractError('frontier_duplicate')
                    if used[bucket] >= quotas[bucket]:
                        raise ContractError('frontier_allocation_exhausted')
                    filter_value = {**c['filter'], 'frontier_query_digest': value['query_digest'], 'frontier_route': route,
                                    'frontier_language': language, 'frontier_community': community,
                                    'frontier_configuration': epoch}
                    partition = partition_key(instance_id=cap.endpoint, protocol_version=cap.version,
                        filter_digest=digest({'operation': policy.operation, 'scope': scope, 'filter': filter_value}))
                    checkpoint = self.jobs.get_cursor(scope, provider, partition, cursor=cur)
                    coverage_epoch = 'frontier:'+digest([epoch, route, value['query_digest'], filter_value])
                    control = {**request, 'request_id': request_id, 'parent_id': value['parent_id'], 'root_id': value['root_id'],
                        'depth': value['depth'], 'priority': priority, 'next_eligible_at': end, 'evidence_ids': evidence,
                        'partition_key': partition, 'cursor_generation': checkpoint['generation'],
                        'checkpoint_digest': digest(checkpoint['cursor_value'])}
                    payload = {**self.planner.payload(policy, schedule, coverage_epoch), 'query': query,
                               'filter': filter_value, 'frontier': control}
                    job = self.jobs.enqueue(scope, 'trend.ingest', payload, idempotency_key='discovery:'+request_id,
                        provider_id=provider, source_policy_version=version, due_at=end,
                        priority=(100 if bucket == 'watch' else 50 if bucket == 'corroboration' else 0)+priority,
                        max_attempts=cap.max_attempts, cursor=cur)
                    value.update(decision='admitted', reason=reason, job_id=job['job_id'], request=request, evidence_ids=evidence,
                        payload_digest=digest(payload), partition_key=partition, cursor_generation=checkpoint['generation'],
                        reservation_microusd=schedule['reservation_microusd'], reservation_state='intent_only_until_job_claim')
                    admitted = self._record(cur, scope, 'frontier-request:'+request_id, {**value,'record':'request'}, policy, at, dependencies)
                    dependencies = [admitted['node_id']]
                    used[bucket] += 1
                    result['jobs'].append(job['job_id'])
                except (ContractError, ValueError, TypeError) as exc:
                    value['reason'] = exc.code if isinstance(exc, ContractError) else 'frontier_proposal_invalid'
                    value['evaluation_sample'] = int(fingerprint[:8],16) % c['rejected_sample_modulus'] == 0
                    value['evaluation_sampling_probability'] = 1/c['rejected_sample_modulus']
                    # Invalid/unavailable evidence must not become an authority.
                    dependencies = [allocation_event['node_id']]
                recorded = self._record(cur, scope, key, value, policy, at, dependencies)
                previous.append(recorded)
                result['decisions'].append(value)
            return result

    def dispatch_context(self, job, *, cursor=None):
        at = self.clock()
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s', (job['scope_key'], job['job_id']))
            current = row(cur)
            if not current or current['state'] in TERMINAL or current['cancellation_requested'] or current['payload'] != job['payload']:
                raise ContractError('frontier_job_unavailable')
            if job['state'] in ('leased','running') and (current['lease_owner'],current['lease_generation']) != (job['lease_owner'],job['lease_generation']):
                raise ContractError('stale_job_fence')
            scope, payload = current['scope_key'], current['payload']
            policy, cap, schedule, c = self._authority(cur, scope, current['provider_id'], current['source_policy_version'], at)
            control = payload.get('frontier', {})
            event = self._event(cur, scope, 'frontier-request:'+control.get('request_id', ''))
            if not event or event['payload'].get('job_id') != current['job_id'] or event['payload'].get('payload_digest') != digest(payload):
                raise ContractError('frontier_job_binding_mismatch')
            self._valid(cur, scope, event['node_id'])
            if control['configuration_digest'] != digest([VERSION, scope, cap.provider_id, policy.version, c]):
                raise ContractError('frontier_configuration_changed')
            if c['routes'].get(control['route']) not in self._modes(cap, policy, at):
                raise ContractError('frontier_query_capability_unknown')
            if control['evidence_ids']:
                self._evidence(cur, scope, control['evidence_ids'], at, payload['query'])
            if current['state'] in ('leased', 'running'):
                cur.execute('SELECT * FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s', (scope, current['reservation_id']))
                reservation = row(cur)
                if (not reservation or reservation['state'] not in ('reserved','dispatched','settled')
                        or reservation['amount_micro_usd'] != schedule['reservation_microusd']):
                    raise ContractError('frontier_reservation_required')
                cur.execute('SELECT budget_key FROM public.pr_trend_reservation_dimensions WHERE scope_key=%s AND reservation_id=%s ORDER BY budget_key', (scope,current['reservation_id']))
                if [r['budget_key'] for r in rows(cur)] != schedule['budget_keys']:
                    raise ContractError('frontier_reservation_required')
            checkpoint = self.jobs.get_cursor(scope, cap.provider_id, control['partition_key'], cursor=cur)
            if checkpoint['generation'] != control['cursor_generation'] or digest(checkpoint['cursor_value']) != control['checkpoint_digest']:
                raise ContractError('frontier_cursor_changed')
            return {'partition_key': control['partition_key'], 'checkpoint': checkpoint, 'request_id': control['request_id']}

    def report(self, scope, provider, version, *, cursor=None):
        """Worker descriptor; HTTP consumers need their own actor/scope boundary."""
        with self.store.transaction(cursor) as cur:
            self._authority(cur, scope, provider, version, self.clock())
            cur.execute("""SELECT e.*,j.state AS job_state,j.error_code AS job_error FROM public.pr_trend_outbox e LEFT JOIN public.pr_trend_jobs j
                ON j.scope_key=e.scope_key AND j.job_id::text=e.payload->>'job_id'
                WHERE e.scope_key=%s AND e.event_type=%s AND e.payload->>'record'='decision'
                AND e.payload->>'provider_id'=%s AND e.payload->>'policy_version'=%s
                ORDER BY e.created_at DESC,e.event_id LIMIT 1001""", (scope, EVENT, provider, version))
            found = rows(cur); counts = defaultdict(Counter); sample = []
            for event in found[:1000]:
                try:
                    self._valid(cur, scope, event['node_id'])
                except ContractError:
                    continue
                p = event['payload']; count = counts[p['route'],p['language']]
                count['examined'] += 1; count[p['decision']] += 1
                count['failed'] += event['job_state'] in ('failed_terminal','outcome_unknown')
                count['reason:'+p['reason']] += 1
                if event['job_state'] in ('failed_terminal','outcome_unknown'):
                    code = event['job_error']
                    code = code if isinstance(code,str) and re.fullmatch(r'[a-z_]{1,80}',code) else 'unknown'
                    count['failure_reason:'+code] += 1
                if p.get('evaluation_sample'):
                    sample.append({k:p[k] for k in ('candidate_id','route','language','reason','evaluation_sampling_probability')})
            return {'status': 'bounded_current', 'truncated': len(found)>1000,
                'counts': [{'route': r,'language': l, **dict(n)} for (r,l),n in sorted(counts.items())],
                'rejected_sample': sample[:100], 'claim_scope': 'retained_discovery_candidates_only'}

    def tick(self, *, limit=20):
        integer(limit, 1, 20, 'frontier_tick_bound')
        if not all(config.enabled(n, self.values) for n in ('INTELLIGENCE','RADAR','PROVIDER_OPERATIONS')):
            return {'status': 'disabled', 'results': [], 'blocked': 0}
        at = self.clock()
        env = os.environ if self.values is None else self.values
        workspaces = [w.strip() for w in str(env.get('RAFII_TREND_WORKSPACE_ALLOWLIST','')).split(',')
                      if config.workspace_allowed(w.strip(), self.values)]
        operations = [o.strip() for o in str(env.get('RAFII_TREND_ALLOWED_OPERATIONS','')).split(',') if o.strip()]
        with self.store.transaction() as cur:
            cur.execute("""SELECT scope_key,provider_id,version FROM public.pr_trend_source_policies
                WHERE readiness='ready' AND revoked_at IS NULL AND valid_from<=%s AND expires_at>%s
                AND manifest->'frontier'->'enabled'='true'::jsonb
                AND provider_id||':'||(manifest->>'operation')=ANY(%s)
                AND (scope_key=ANY(%s) OR EXISTS(SELECT 1 FROM public.pr_trend_entitlements e
                    WHERE e.scope_key=pr_trend_source_policies.scope_key AND e.workspace_id::text=ANY(%s)
                    AND e.revoked_at IS NULL AND e.expires_at>%s AND 'retrieve'=ANY(e.operations)))
                ORDER BY scope_key,provider_id,version LIMIT %s""", (at,at,operations,['workspace:'+w for w in workspaces],workspaces,at,limit))
            candidates = rows(cur)
        result = {'status': 'ok', 'results': [], 'blocked': 0}
        for candidate in candidates:
            try:
                with self.store.transaction() as cur:
                    self._authority(cur, candidate['scope_key'], candidate['provider_id'], candidate['version'], at)
                    proposals = self._stored_proposals(cur, candidate['scope_key'], at, candidate['provider_id'], candidate['version'])
                    result['results'].append(self.produce(candidate['scope_key'], candidate['provider_id'], candidate['version'], proposals, cursor=cur))
            except ContractError:
                result['blocked'] += 1
        return result

    def maintenance(self, *, limit=100, after=None, cursor=None):
        """Before canonical retention.sweep; persist next_key for fair paging.

        Runs with flags OFF too. An operation flag/backoff is not a revocation.
        Only invalid current policy/storage/TTL/dependencies cancel a request.
        Canonical retention then physically purges these node-backed events.
        """
        integer(limit, 1, 100, 'frontier_maintenance_bound')
        with self.store.transaction(cursor) as cur:
            cur.execute('SELECT reads_ready FROM public.pr_trend_runtime_guard WHERE singleton')
            if not row(cur)['reads_ready']:
                return {'status': 'restore_deferred', 'next_key': after, 'cancelled': 0}
            cur.execute("""SELECT * FROM public.pr_trend_outbox WHERE event_type=%s
                AND payload<>'{}'::jsonb AND (%s::text IS NULL OR scope_key||'|'||event_key>%s)
                ORDER BY scope_key,event_key LIMIT %s""", (EVENT,after,after,limit))
            events = rows(cur); cancelled = 0
            for event in events:
                p, scope = event['payload'], event['scope_key']
                invalid = False
                try:
                    self._valid(cur, scope, event['node_id'])
                    for permission in ('retrieve','store_metrics','derive_metrics','retain_derivatives'):
                        self.store._policy(cur, scope, p['provider_id'], p['policy_version'], permission=permission)
                    if scope.startswith('workspace:'):
                        cur.execute("SELECT state ? 'accountDeletion' AS deleted FROM public.pr_workspaces WHERE id=%s", (scope[10:],))
                        w = row(cur)
                        if not w or w['deleted']:
                            raise ContractError('workspace_access_denied')
                except ContractError:
                    invalid = True
                if invalid:
                    cur.execute("UPDATE public.pr_trend_nodes SET validity='revoked' WHERE scope_key=%s AND node_id=%s AND validity<>'purged'", (scope,event['node_id']))
                    if p.get('job_id'):
                        cur.execute('SELECT state FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s', (scope,p['job_id']))
                        job = row(cur)
                        if job and job['state'] not in TERMINAL:
                            self.jobs.cancel(scope, p['job_id'], cursor=cur)
                            cancelled += 1
            return {'status': 'ok', 'cancelled': cancelled,
                    'next_key': events[-1]['scope_key']+'|'+events[-1]['event_key'] if len(events)==limit else None}

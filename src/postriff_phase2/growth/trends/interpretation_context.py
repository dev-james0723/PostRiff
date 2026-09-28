"""Current stored interpretations for Genome/Lab; no dispatch or persistence.

``load`` belongs inside the caller's authenticated transaction, after the current
receipt's AdvancedPipeline.build_inputs adaptation. Persist ``bindings`` in job
controls and compare via ``expected`` before commit. Add every ``refs`` entry to
the output manifest. Re-run on reads: native metric receipts are not 040 nodes.

Existing TrendEnrichment generates the native spread/platform choice envelopes.
Choices alone cannot supply excerpts, alternatives, reviews or qualified priors.
Optional operator artifacts use ordinary TrendStore.put_projection, never SQL
inserts here. ``review_id``/``prior_id`` define their discoverable identities:
* interpretation_review: SCHEMA, role=spread, state=qualified, fixture=false,
  judgment_digest, context_digest, trust_receipt_id, hypotheses, provenance.
  Each hypothesis has mechanism, original evidence_spans, alternatives,
  contradictions, uncertainty, risk_blocked (explicit boolean).
* platform_prior: SCHEMA, role=prior, state=qualified, fixture=false, cohort,
  prior_version (= registry version), drifted=false, finding, uncertainty,
  basis=permitted_observations or actual_published_outcomes, workspace_id
  (null for shared), source_bindings=[{scope_key,node_id}], provenance.
  Private priors additionally require outcome_frame, job_ids, outcomes_digest.
Both require evaluation_digest and a qualified nonrevoked method with config.
interpretation_context={state:production,role,schema_version:SCHEMA,
runtime_digest:runtime_digest(),review_authority,reviewer_ids,cohort (priors),
minimum_samples (priors),allowed_access_methods (priors),period (priors)}.
period={id,start,end,preregistered_at} binds the workflow's opaque period ID;
registry created_at <= preregistered_at < start, and every source event falls
in [start,end). A newly registered method cannot invent an earlier registration.
Provenance has
reviewer_id, review_workspace_id, authority, decision=approved, reviewed_at,
evidence_ref. Shared reviewers must still be editors in that review workspace;
private reviewers must be editors in the requesting workspace. This module
never creates/promotes these artifacts. Synthetic tests confer no qualification.
"""
from copy import deepcopy
import inspect
import json
import sys
from types import SimpleNamespace
import uuid

from postriff_alpha.domain import AlphaError
from ... import memory
from ..questions import load as load_questions, SETS_DIR
from . import config, context, contracts, enrichment, platform_priors, relevance, spread
from .store import TrendStorageError, bounded_json, json_value, rows, trust_lock, utcnow

SCHEMA = 'rafii.trend-interpretation-context.v1'
COHORT_KEYS = ('platform', 'format', 'language', 'niche', 'period')
MECHANISMS = dict(zip(('utility', 'relatability', 'identity', 'aspiration', 'surprise',
    'humor', 'participation', 'information_gap', 'debate', 'urgency'),
    ('practical_utility', 'relatability', 'identity_expression', 'status_aspiration',
     'surprise', 'humor', 'participation', 'information_gap', 'debate_outrage', 'fear_urgency')))
MAX_PRIOR_SOURCES = 100


def runtime_digest():
    from . import learning, lab_enrichment
    return contracts.digest({m.__name__: inspect.getsource(m) for m in
        (sys.modules[__name__], spread, platform_priors, context, enrichment,
         learning, lab_enrichment, relevance, memory)})


def review_id(workspace_id, judgment_id):
    return str(uuid.uuid5(uuid.UUID(workspace_id), 'trend-spread-review-v1:' + contracts.uuid(judgment_id)))


def prior_id(scope_key, cohort):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, contracts.canonical(['trend-platform-prior-v1', scope_key, cohort])))


def _deny(reason):
    raise TrendStorageError('interpretation_' + reason)


def _text(value, limit=800):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _iso(value):
    return contracts.iso(contracts.instant(value))


def _strings(value, *, minimum=0):
    return isinstance(value, list) and minimum <= len(value) <= 8 and all(_text(v, 400) for v in value)


def _node(record):
    return {'scope_key': record['scope_key'], 'node_id': record['projection_id']}


def _binding(record):
    return {**{k: record[k] for k in ('kind', 'object_id', 'revision', 'scope_key', 'projection_id')},
        'payload_digest': contracts.digest(record['payload']), 'method_bundle': deepcopy(record['method_bundle'])}


def _usable(record, now, permissions=('derive_metrics', 'retain_derivatives')):
    return (isinstance(record, dict) and record.get('validity') == 'valid'
        and isinstance(record.get('payload'), dict)
        and contracts.instant(record['available_at']) <= contracts.instant(now) < contracts.instant(record['expires_at'])
        and all(record.get('policy', {}).get(p) is True for p in permissions))


def _lock(cur, store, wid, actor, records):
    store.lock_dependencies(wid, actor, [{k: r[k] for k in ('kind', 'object_id', 'revision')} for r in records], cursor=cur)


def _attached(cur, record, refs):
    if not refs:
        _deny('empty_support')
    pairs = sorted({(r['scope_key'], r['node_id']) for r in refs})
    cur.execute('''/* interpretation:ancestry */ WITH RECURSIVE a(scope_key,node_id) AS (
        SELECT %s::text,%s::uuid UNION SELECT d.input_scope_key,d.input_node_id
        FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
        SELECT count(*) FROM a JOIN unnest(%s::text[],%s::uuid[]) r(scope_key,node_id) USING(scope_key,node_id)''',
        (record['scope_key'], record['projection_id'], [p[0] for p in pairs], [p[1] for p in pairs]))
    if cur.fetchone()[0] != len(pairs):
        _deny('support_dag_missing')


def _review(cur, store, wid, record, role, now, cohort=None):
    if not _usable(record, now):
        _deny('review_unavailable')
    p = record['payload']; bounded_json(p)
    if (p.get('schema_version') != SCHEMA or p.get('role') != role or p.get('state') != 'qualified'
            or p.get('fixture') is not False or not _text(p.get('evaluation_digest'), 128)):
        _deny('review_required')
    cur.execute('''/* interpretation:method */ SELECT qualification,revoked_at,config,created_at
        FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE''',
        tuple(record['method_bundle'][k] for k in ('method_id', 'version')))
    saved = json_value(cur.fetchone()); gate = saved[2].get('interpretation_context', {}) if saved and isinstance(saved[2], dict) else {}
    if (not saved or saved[0] != 'qualified' or saved[1] is not None
            or not isinstance(gate, dict)
            or any(gate.get(k) != v for k, v in {'state': 'production', 'role': role,
                'schema_version': SCHEMA, 'runtime_digest': runtime_digest()}.items())
            or (role == 'prior' and gate.get('cohort') != cohort)):
        _deny('review_method_unqualified')
    provenance = p.get('provenance', {})
    if (not isinstance(provenance, dict) or set(provenance) != {'reviewer_id', 'review_workspace_id', 'authority', 'decision', 'reviewed_at', 'evidence_ref'}
            or provenance['decision'] != 'approved' or not _text(provenance['authority'], 160)
            or provenance['authority'] != gate.get('review_authority')
            or provenance['reviewer_id'] not in gate.get('reviewer_ids', [])
            or not _text(provenance['evidence_ref'], 256)
            or not contracts.instant(provenance['reviewed_at']) <= contracts.instant(record['available_at'])):
        _deny('review_provenance')
    rwid = contracts.uuid(provenance['review_workspace_id'])
    if record['scope_key'].startswith('workspace:') and rwid != wid:
        _deny('review_tenant')
    store._actor(cur, rwid, contracts.uuid(provenance['reviewer_id']), write=True)
    return {**gate, '_registry_created_at': saved[3]}


def _policy_digest(cur, store, wid, actor, refs, task, now):
    if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
        _deny('policy_bound')
    policies, reviewed = [], None
    for ref in sorted(refs, key=lambda r: (r['scope_key'], r['provider_id'], r['version'])):
        current = store._policy(cur, ref['scope_key'], ref['provider_id'], ref['version'], 'llm_process', at=now)
        limits = enrichment.reviewed_config(current, task, wid)
        if reviewed is not None and limits != reviewed:
            _deny('policy_conflict')
        reviewed = limits; policies.append(current['manifest'])
    return contracts.digest({'source_policies': policies, 'review': reviewed,
        'entitlements': store.scope_signature(wid, actor, cursor=cur)})


def _native(cur, store, wid, actor, inputs, receipt_id, state, values, task, now):
    """Reconstruct the real cache identity; no scan for vaguely related answers."""
    worker = enrichment.TrendEnrichment(SimpleNamespace(repository=SimpleNamespace(
        connection_factory=store.connection_factory)), store=store, values=values)
    loaded = worker._load(cur, wid, actor, receipt_id, task, state)
    if loaded['context_revision'] != relevance.context_revision(state):
        _deny('judgment_context')
    result = worker._cached(cur, wid, actor, loaded)
    if not result:
        return None
    saved = store.get_projection(wid, actor, 'model_judgment', loaded['result_id'], cursor=cur)
    if (not _usable(saved, now, ('derive_metrics', 'retain_derivatives', 'llm_process'))
            or saved['scope_key'] != 'workspace:' + wid or saved['method_bundle'] != {
                'method_id': loaded['method_id'], 'version': loaded['method_version']}):
        _deny('judgment_method_or_rights')
    raw = saved['payload']['result']; qs = load_questions(SETS_DIR / ('trend_' + task + '.v1.json'))
    if (not isinstance(raw, dict) or saved['payload'].get('key') != loaded['key']
            or raw.get('status') != 'ok' or raw.get('invalid') or raw.get('evaluation_kind') != 'native_evaluation'
            or raw.get('route') != 'primary' or raw.get('interpretation_only') is not True
            or raw.get('executed_model') != loaded['config']['model']
            or raw.get('question_set') != qs.key or raw.get('question_digest') != qs.digest
            or raw.get('input_digest') != loaded['pack']['input_digest']
            or not isinstance(raw.get('answers'), dict) or set(raw['answers']) != set(qs.names)):
        _deny('judgment_contract')
    choices = {}
    for key, answer in raw['answers'].items():
        if (not isinstance(answer, dict) or set(answer) != {'value', 'abstained', 'type'}
                or answer['type'] != 'choice' or type(answer['abstained']) is not bool
                or (answer['value'] is not None if answer['abstained'] else answer['value'] not in qs.question(key).options())):
            _deny('judgment_answer')
        choices[MECHANISMS.get(key, key)] = 'unknown' if answer['abstained'] else answer['value']
    # The sealed recipe and current pack must refer to this caller's exact receipt.
    pack = loaded['pack']
    if pack['receipt_id'] != receipt_id or pack['evidence_scope'] != inputs['common']['scope_key']:
        _deny('judgment_receipt')
    current_sources = {s['source_id']: s for s in inputs['common']['sources']}
    for e in pack['evidence']:
        s = current_sources.get(e['observation_id'], {})
        original = inputs['facts'].get(e['observation_id'], {}).get('text')
        if (any(s.get('rights', {}).get(k) is not True for k in ('analysis', 'creative', 'llm'))
                or not isinstance(original, str) or not original.startswith(e['text'])
                or contracts.instant(s['expires_at']) <= contracts.instant(now)):
            _deny('judgment_source_changed')
    _lock(cur, store, wid, actor, [saved])
    _attached(cur, saved, [_node(loaded['receipt']), _node(loaded['trend'])])
    cur.execute('''/* interpretation:policy_refs */ SELECT DISTINCT scope_key,provider_id,source_policy_version
        FROM public.pr_trend_observations WHERE scope_key=%s AND observation_id=ANY(%s::uuid[])
        ORDER BY scope_key,provider_id,source_policy_version LIMIT 21''',
        (pack['evidence_scope'], loaded['source_ids']))
    policy_refs = [{'scope_key': r[0], 'provider_id': r[1], 'version': r[2]} for r in cur.fetchall()]
    if _policy_digest(cur, store, wid, actor, policy_refs, task, now) != loaded['policy_digest']:
        _deny('policy_changed')
    return {'projection': saved, 'loaded': loaded, 'result': raw,
        'current_binding': {'task': task, 'object_id': saved['object_id'], 'policy_refs': policy_refs,
            'policy_digest': loaded['policy_digest'], 'input_digest': pack['input_digest'],
            'key': loaded['key'], 'question_digest': raw['question_digest']},
        'typed': {'task': task, 'choices': choices, 'qualification': 'unqualified',
            'causal_claim': False, 'evidence_refs': [e['observation_id'] for e in pack['evidence']],
            'result_digest': contracts.digest(raw)}}


def _spread(cur, store, wid, actor, inputs, entry, now, brand_exclusions):
    judgment = entry['projection']; oid = review_id(wid, judgment['object_id'])
    review = store.get_projection(wid, actor, 'interpretation_review', oid, cursor=cur)
    _review(cur, store, wid, review, 'spread', now)
    p = review['payload']; loaded = entry['loaded']
    if (review['scope_key'] != 'workspace:' + wid or any(p.get(k) != v for k, v in {
            'judgment_digest': contracts.digest(entry['result']), 'trust_receipt_id': loaded['pack']['receipt_id'],
            'context_digest': loaded['context_revision']}.items())):
        _deny('spread_binding')
    candidates = p.get('hypotheses')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 10:
        _deny('hypothesis_bound')
    evidence = {e['observation_id']: e['text'] for e in loaded['pack']['evidence']}
    hypotheses = []; seen = set()
    for h in candidates:
        if not isinstance(h, dict):
            _deny('hypothesis_contract')
        mechanism = h.get('mechanism')
        if (mechanism not in spread.MECHANISMS or mechanism in seen
                or entry['typed']['choices'].get(mechanism) != 'supported'
                or not _strings(h.get('alternatives'), minimum=1) or not _strings(h.get('contradictions'))
                or not _text(h.get('uncertainty')) or type(h.get('risk_blocked')) is not bool):
            _deny('hypothesis_contract')
        seen.add(mechanism); spans = h.get('evidence_spans')
        if not isinstance(spans, list) or not 1 <= len(spans) <= 12:
            _deny('span_bound')
        for span in spans:
            if not isinstance(span, dict):
                _deny('span_mismatch')
            text = evidence.get(span.get('observation_id'))
            if (set(span) != {'observation_id', 'start', 'end', 'text'} or text is None
                    or type(span['start']) is not int or type(span['end']) is not int
                    or not 0 <= span['start'] < span['end'] <= len(text)
                    or span['end'] - span['start'] > 240 or text[span['start']:span['end']] != span['text']):
                _deny('span_mismatch')
        hypotheses.append({**deepcopy(h), 'evidence_refs': sorted({s['observation_id'] for s in spans}),
            'available_at': contracts.iso(max(map(contracts.instant, (review['available_at'], judgment['available_at'])))),
            'expires_at': min((review['expires_at'], judgment['expires_at'], inputs['expires_at']), key=contracts.instant)})
    _lock(cur, store, wid, actor, [review]); _attached(cur, review, [_node(judgment)])
    pure = spread.project_spread_hypotheses({**inputs['common'], 'decision_cutoff': now,
        'hypotheses': hypotheses, 'brand_exclusions': brand_exclusions})
    # Original spans remain explicit; the pure rubric intentionally only returns refs.
    for h in pure['hypotheses']:
        original = next(v for v in hypotheses if v['mechanism'] == h['mechanism'])
        h['evidence_spans'] = original['evidence_spans']
        h['review_status'] = 'reviewed_content_hypothesis'
    return pure, review


def _prior_sources(cur, store, wid, record, gate, now):
    period = gate.get('period', {})
    if (not isinstance(period, dict) or set(period) != {'id', 'start', 'end', 'preregistered_at'}
            or period['id'] != record['payload']['cohort']['period']
            or not contracts.instant(gate['_registry_created_at']) <= contracts.instant(period['preregistered_at']) < contracts.instant(period['start'])
                < contracts.instant(period['end']) <= contracts.instant(record['available_at'])):
        _deny('prior_preregistered_period')
    refs = record['payload'].get('source_bindings')
    if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_PRIOR_SOURCES:
        _deny('prior_source_bound')
    identities = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {'scope_key', 'node_id'}:
            _deny('prior_source_binding')
        scope, sid = contracts.scope(ref['scope_key']), contracts.uuid(ref['node_id'])
        if ((record['scope_key'].startswith('shared:') and scope != record['scope_key'])
                or (record['scope_key'].startswith('workspace:') and scope != record['scope_key'] and not scope.startswith('shared:'))
                or (scope, sid) in identities):
            _deny('prior_source_scope')
        identities.add((scope, sid))
    _attached(cur, record, refs)
    expiry = record['expires_at']
    for scope in sorted({s for s, _ in identities if s.startswith('shared:')}):
        cur.execute('''/* interpretation:entitlement */ SELECT operations,expires_at,revoked_at
            FROM public.pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s FOR SHARE''', (wid, scope))
        entitlement = json_value(cur.fetchone())
        if (not entitlement or entitlement[2] is not None or contracts.instant(entitlement[1]) <= contracts.instant(now)
                or not {'retrieve', 'derive_metrics', 'share_across_workspaces'} <= set(entitlement[0])):
            _deny('prior_entitlement')
        expiry = min((expiry, entitlement[1]), key=contracts.instant)
    ordered = sorted(identities)
    cur.execute('''/* interpretation:sources */ SELECT observation_id::text,scope_key,provider_id,
        source_policy_version,kind,operation,event_at,available_at,retention_until,rights,payload,provenance
        FROM public.pr_trend_observations WHERE (scope_key,observation_id) IN
        (SELECT * FROM unnest(%s::text[],%s::uuid[])) FOR SHARE''',
        ([v[0] for v in ordered], [v[1] for v in ordered]))
    originals = rows(cur)
    if {(r['scope_key'], r['observation_id']) for r in originals} != identities:
        _deny('prior_source_missing')
    if len({sid for _, sid in identities}) != len(identities):
        _deny('prior_source_id_collision')
    result = []; policies = {}
    for o in originals:
        if (o['kind'] not in ('raw_post', 'owned_post') or o['operation'] == 'delete'
                or o['provenance'].get('access_method') not in gate.get('allowed_access_methods', [])
                or not o.get('event_at') or not contracts.instant(period['start']) <= contracts.instant(o['event_at']) < contracts.instant(period['end'])
                or contracts.instant(o['available_at']) > contracts.instant(record['available_at'])
                or contracts.instant(o['retention_until']) <= contracts.instant(now)):
            _deny('prior_evidence_unavailable')
        key = (o['scope_key'], o['provider_id'], o['source_policy_version'])
        if key not in policies:
            policies[key] = store._policy(cur, *key, 'derive_metrics', at=now)
        policy = policies[key]; operations = ['derive_metrics', 'retain_derivatives', 'store_raw']
        if o['scope_key'].startswith('shared:'):
            operations.append('share_across_workspaces')
        for op in operations:
            if (op not in policy['contract_operations'] or op not in policy['operations']
                    or not all(contracts.permits(r, op, o['scope_key'], now) for r in (o['rights'], policy['rights']))):
                _deny('prior_source_rights')
            expiry = min((expiry, o['rights'][op]['expires_at'], policy['rights'][op]['expires_at']), key=contracts.instant)
        expiry = min((expiry, policy['expires_at'], policy['contract_end'], o['retention_until']), key=contracts.instant)
        result.append({'source_id': o['observation_id'], 'scope_key': 'workspace:' + wid,
            'platform': o['payload'].get('platform'), 'language': o['payload'].get('language'),
            'event_at': _iso(o['event_at']), 'available_at': _iso(o['available_at']),
            'expires_at': _iso(expiry), 'original': o['payload'].get('is_repost') is False,
            'rights': {'analysis': True, 'creative': True}})
    return result, _iso(expiry)


def _owned(cur, store, wid, actor, state, payload, now, *, read_only=False, period=None):
    """Existing native publication/metric path; never use a review's claimed counts."""
    from . import learning, lab_enrichment
    from .service import validate_stored_bindings
    ids = payload.get('job_ids'); frame = payload.get('outcome_frame')
    if (not isinstance(ids, list) or not 3 <= len(ids) <= 10 or len(set(ids)) != len(ids)
            or any(not _text(i, 128) for i in ids) or not isinstance(frame, dict)):
        _deny('owned_frame_required')
    jobs = {j['id']: j for j in (state.get('phase2') or {}).get('jobs', []) if j.get('id') in ids}
    if set(jobs) != set(ids):
        _deny('owned_publication_missing')
    outcomes, dependencies, native_posts = [], [], set()
    cutoff = contracts.instant(now).timestamp()
    for jid in sorted(ids):
        job = jobs[jid]; bindings = job.get('manifest', {}).get('trendLineage', [])
        if not isinstance(bindings, list) or len(bindings) != 1:
            _deny('owned_lineage')
        native = (job['manifest'].get('channelId'), job.get('providerReference'))
        if not all(native) or native in native_posts:
            _deny('owned_duplicate_native_post')
        native_posts.add(native)
        validate_stored_bindings(store.connection_factory, cur, wid, actor, state, bindings, cutoff,
            model_visible=False, store_factory=lambda _: store, **({'read_only': True} if read_only else {}))
        binding = bindings[0]
        outcome = learning._publication(cur, wid, state, binding, binding, job, cutoff, frame.get('window'))
        published = outcome.get('publication', {}).get('published_at')
        if period and (type(published) not in (int, float) or not
                contracts.instant(period['start']).timestamp() <= published < contracts.instant(period['end']).timestamp()):
            _deny('owned_period')
        outcomes.append(outcome)
        dependencies.extend(store.get_projection(wid, actor, kind, binding[key], cursor=cur) for kind, key in
            (('opportunity', 'opportunity_id'), ('receipt', 'trust_receipt_id'), ('trend', 'trend_id')))
    history = lab_enrichment.comparable_history(outcomes, frame, cutoff)
    if (not history['comparable'] or len(history['observations']) != len(ids)
            or contracts.digest(history) != payload.get('outcomes_digest')):
        _deny('owned_history_changed')
    if not read_only:
        _lock(cur, store, wid, actor, dependencies)
    return history, dependencies


def _prior(cur, store, wid, actor, state, record, cohort, now, *, read_only=False):
    gate = _review(cur, store, wid, record, 'prior', now, cohort)
    p = record['payload']; private = record['scope_key'] == 'workspace:' + wid
    if (p.get('cohort') != cohort or p.get('drifted') is not False
            or p.get('prior_version') != record['method_bundle']['version']
            or p.get('workspace_id') != (wid if private else None)
            or p.get('basis') != ('actual_published_outcomes' if private else 'permitted_observations')
            or not _text(p.get('finding')) or not _text(p.get('uncertainty'))):
        _deny('prior_binding_or_drift')
    sources, expiry = _prior_sources(cur, store, wid, record, gate, now)
    minimum = gate.get('minimum_samples')
    if (type(minimum) is not int or not 1 <= minimum <= MAX_PRIOR_SOURCES or len(sources) < minimum
            or any(s[k] != cohort[k] for s in sources for k in ('platform', 'language'))):
        _deny('prior_sparse_or_cohort')
    dependencies = []; history = None
    if private:
        frame = p.get('outcome_frame', {})
        if any(frame.get(k) != cohort[v] for k, v in (('provider', 'platform'), ('language', 'language'), ('format', 'format'))):
            _deny('owned_cohort')
        history, dependencies = _owned(cur, store, wid, actor, state, p, now, read_only=read_only, period=gate['period'])
        _attached(cur, record, [_node(r) for r in dependencies])
        expiry = min([expiry] + [r['expires_at'] for r in dependencies], key=contracts.instant)
    if not read_only:
        _lock(cur, store, wid, actor, [record])
    prior = {**deepcopy(cohort), 'workspace_id': wid if private else None, 'qualification': 'qualified',
        'basis': p['basis'], 'finding': p['finding'], 'uncertainty': p['uncertainty'], 'drifted': False,
        'prior_version': p['prior_version'], 'evidence_refs': [s['source_id'] for s in sources],
        'available_at': _iso(record['available_at']), 'expires_at': expiry,
        'causal_claim': False, 'observed_source_count': len(sources)}
    return prior, sources, dependencies, history


def load(cur, store, wid, actor, inputs, *, receipt_id, state, values=None, cohort=None,
         brand_exclusions=(), expected=None, now=None):
    """Return {evidence, bindings, refs, projection_fields, expires_at} (stored only).

    Unknown/malformed optional evidence is omitted with safe reason codes. An
    expected-binding mismatch is an error, including qualified→unknown changes.
    The caller must recheck expires_at immediately before committing an output.
    """
    wid, actor, receipt_id = map(contracts.uuid, (wid, actor, receipt_id)); now = now or utcnow()
    output_scope = 'workspace:' + wid
    empty = {**inputs['common'], 'decision_cutoff': now, 'scope_key': output_scope, 'sources': []}
    spread_result = spread.project_spread_hypotheses(empty)
    prior_result = platform_priors.resolve_prior({**empty, 'cohort': cohort or {}, 'workspace_id': wid})
    result = {'evidence': [], 'refs': [], 'bindings': {'schema_version': SCHEMA,
        'runtime_digest': runtime_digest(), 'receipt_id': receipt_id,
        'context_digest': relevance.context_revision(state), 'cohort': deepcopy(cohort),
        'boundaries_digest': contracts.digest(memory.boundary_fields(state)),
        'workflow_cohort': deepcopy((state.get('coworker') or {}).get('trendPlatformCohort')),
        'brand_exclusions': list(brand_exclusions), 'inputs_digest': contracts.digest(inputs),
        'artifacts': [], 'native': []},
        'projection_fields': {'spread': spread_result, 'platform_dna': prior_result},
        'expires_at': inputs['expires_at'], 'limitations': [], 'provider_attempts': 0}
    enabled = config.workspace_allowed(wid, values) and all(config.enabled(n, values)
        for n in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS'))
    if not enabled:
        result['limitations'].append('disabled')
    else:
        if (contracts.instant(inputs['expires_at']) <= contracts.instant(now)
                or contracts.instant(inputs['common']['decision_cutoff']) > contracts.instant(now)):
            _deny('inputs_outside_current_time')
        if (not isinstance(brand_exclusions, (list, tuple)) or len(brand_exclusions) > 10
                or any(m not in spread.MECHANISMS for m in brand_exclusions)):
            _deny('brand_exclusions')
        trust_lock(cur); scopes = store.authorized_scopes(wid, actor, cursor=cur)
        cur.execute('/* interpretation:workspace */ SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE', (wid,))
        stored_state = cur.fetchone()
        if not stored_state:
            _deny('workspace_unavailable')
        current_state = json.loads(stored_state[0]) if isinstance(stored_state[0], str) else stored_state[0]
        if contracts.digest(current_state) != contracts.digest(state):
            _deny('workspace_state_changed')
        receipt = store.get_receipt(wid, actor, receipt_id, cursor=cur)
        if (not _usable(receipt, now) or receipt.get('verification_state') != 'verified'
                or receipt['scope_key'] != inputs['common']['scope_key']):
            _deny('receipt_unavailable')
        _lock(cur, store, wid, actor, [receipt])
        def include(record):
            binding = _binding(record)
            if binding not in result['bindings']['artifacts']:
                result['bindings']['artifacts'].append(binding); result['refs'].append(_node(record))
                result['expires_at'] = min((result['expires_at'], record['expires_at']), key=contracts.instant)
        include(receipt)
        for task in ('spread_mechanism', 'platform_fit'):
            try:
                entry = _native(cur, store, wid, actor, inputs, receipt_id, state, values, task, now)
                if entry is None:
                    result['limitations'].append(task + '_unavailable'); continue
                include(entry['projection']); result['evidence'].append(entry['typed'])
                result['bindings']['native'].append(entry['current_binding'])
                result['expires_at'] = min((result['expires_at'], entry['loaded']['expires_at']), key=contracts.instant)
                if task == 'spread_mechanism':
                    try:
                        if any(str(f.get('value', '')).strip() for f in memory.boundary_fields(state)):
                            _deny('uninterpreted_brand_boundaries')
                        projected, review = _spread(cur, store, wid, actor, inputs, entry, now, brand_exclusions)
                        projected['scope_key'] = output_scope
                        result['projection_fields']['spread'] = projected; include(review)
                    except (contracts.ContractError, AlphaError, KeyError, TypeError, ValueError):
                        result['limitations'].append('spread_review_unavailable')
            except (contracts.ContractError, AlphaError, KeyError, TypeError, ValueError):
                result['limitations'].append(task + '_unavailable')
        prior_rows, prior_sources = [], {}
        prior_bound_exceeded = False
        if (not isinstance(cohort, dict) or set(cohort) != set(COHORT_KEYS)
                or any(not _text(v, 200) for v in cohort.values())
                or cohort != (state.get('coworker') or {}).get('trendPlatformCohort')
                or any(cohort[k] != inputs['frame'][k] for k in ('platform', 'language'))):
            result['limitations'].append('explicit_cohort_required')
        else:
            if len(scopes) > 20:
                result['limitations'].append('prior_scope_bound')
                scopes = []  # No recency-based selection of a "representative" subset.
            for scope in sorted(scopes):
                record = store.get_projection(wid, actor, 'platform_prior', prior_id(scope, cohort), cursor=cur)
                if not record or record['scope_key'] != scope:
                    continue
                try:
                    prior, sources, dependencies, history = _prior(cur, store, wid, actor, state, record, cohort, now)
                    if len(set(prior_sources) | {s['source_id'] for s in sources}) > 1000:
                        prior_bound_exceeded = True
                        _deny('prior_total_bound')
                    prior_rows.append(prior); prior_sources.update({s['source_id']: s for s in sources})
                    include(record)
                    for dependency in dependencies:
                        include(dependency)
                    if history:
                        result['bindings'].setdefault('outcomes', []).append(contracts.digest(history))
                    result['expires_at'] = min((result['expires_at'], prior['expires_at']), key=contracts.instant)
                except (contracts.ContractError, AlphaError, KeyError, TypeError, ValueError):
                    result['limitations'].append('prior_unqualified_drifted_or_unavailable')
            if prior_bound_exceeded:
                # A truncated set cannot establish absence of disagreement.
                prior_rows, prior_sources = [], {}
                result['limitations'].append('prior_total_bound')
            result['projection_fields']['platform_dna'] = platform_priors.resolve_prior({**empty,
                'workspace_id': wid, 'cohort': cohort, 'sources': list(prior_sources.values()), 'priors': prior_rows})
        if not prior_rows:
            result['limitations'].append('qualified_prior_unavailable')
    result['bindings']['artifacts'].sort(key=contracts.canonical)
    result['refs'].sort(key=contracts.canonical)
    result['limitations'] = sorted(set(result['limitations']))
    # Job controls must fit the existing 64KiB job payload with room for the
    # parent's other opaque controls. Full typed details belong in chunk storage.
    bounded_json(result['bindings'], 48000)
    if expected is not None and result['bindings'] != expected:
        _deny('binding_changed')
    return result


def validate_current(cur, store, wid, actor, inputs, *, receipt_id, state, bindings, values=None, now=None):
    """Viewer-safe GET gate for frozen output; returns True or raises unavailable.

    No edit locks, jobs, model objects, packs or prompts. Read exact current heads,
    policy/registry/cohort and native outcome receipts in the caller's transaction.
    An unchanged frozen output is still historical, never a new qualification.
    """
    now = now or utcnow(); wid, actor, receipt_id = map(contracts.uuid, (wid, actor, receipt_id))
    if not config.workspace_allowed(wid, values) or not all(config.enabled(n, values)
            for n in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS')):
        _deny('read_disabled')
    store.authorized_scopes(wid, actor, cursor=cur)
    cur.execute('/* interpretation:workspace */ SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE', (wid,))
    saved_state = cur.fetchone()
    current_state = (json.loads(saved_state[0]) if isinstance(saved_state[0], str) else saved_state[0]) if saved_state else None
    if current_state is None or contracts.digest(current_state) != contracts.digest(state):
        _deny('workspace_state_changed')
    if (not isinstance(bindings, dict) or bindings.get('schema_version') != SCHEMA
            or bindings.get('runtime_digest') != runtime_digest() or bindings.get('receipt_id') != receipt_id
            or bindings.get('context_digest') != relevance.context_revision(state)
            or bindings.get('boundaries_digest') != contracts.digest(memory.boundary_fields(state))
            or bindings.get('inputs_digest') != contracts.digest(inputs)
            or bindings.get('workflow_cohort') != (state.get('coworker') or {}).get('trendPlatformCohort')
            or contracts.instant(inputs['expires_at']) <= contracts.instant(now)):
        _deny('read_binding_changed')
    artifacts = bindings.get('artifacts', [])
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 100:
        _deny('read_binding_bound')
    current = {}
    for b in artifacts:
        record = store.get_projection(wid, actor, b['kind'], b['object_id'], cursor=cur)
        if not _usable(record, now) or _binding(record) != b:
            _deny('read_artifact_changed')
        current[(b['kind'], b['object_id'])] = record
    receipt = current.get(('receipt', receipt_id))
    if not receipt or receipt['verification_state'] != 'verified' or receipt['scope_key'] != inputs['common']['scope_key']:
        _deny('read_receipt_unavailable')
    natives = bindings.get('native', [])
    if not isinstance(natives, list) or len(natives) > 2:
        _deny('read_native_bound')
    for native in natives:
        if not config.enabled('MODEL_ENRICHMENT', values):
            _deny('read_model_disabled')
        task = native['task']
        if task not in ('spread_mechanism', 'platform_fit'):
            _deny('read_task')
        record = current.get(('model_judgment', native['object_id']))
        method_id, version, _artifact = enrichment.method_identity()
        qs = load_questions(SETS_DIR / ('trend_' + task + '.v1.json'))
        if (not _usable(record, now, ('derive_metrics', 'retain_derivatives', 'llm_process'))
                or record['method_bundle'] != {'method_id': method_id, 'version': version}
                or record['scope_key'] != 'workspace:' + wid
                or native['question_digest'] != qs.digest
                or _policy_digest(cur, store, wid, actor, native['policy_refs'], task, now) != native['policy_digest']):
            _deny('read_judgment_changed')
        envelope = record['payload']
        if (envelope.get('key') != native['key'] or envelope.get('context_revision') != bindings['context_digest']
                or envelope.get('policy_digest') != native['policy_digest']
                or envelope.get('result', {}).get('input_digest') != native['input_digest']
                or contracts.instant(envelope['expires_at']) <= contracts.instant(now)):
            _deny('read_cache_changed')
    for record in current.values():
        if record['kind'] == 'interpretation_review':
            _review(cur, store, wid, record, 'spread', now)
        elif record['kind'] == 'platform_prior':
            # Rereads native metrics via the existing Lab/learning path; no edit
            # lock and no frozen review-provided metric values are trusted.
            _prior(cur, store, wid, actor, state, record, bindings['cohort'], now, read_only=True)
    return True

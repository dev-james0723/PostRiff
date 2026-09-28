"""V2 receipt manifests, complete recomputation and bounded revocation projections.

No storage or model/provider calls. Caller owns retention/purge and current policy
lookup. Method registries must be constructed by the trusted executable loader.
"""
from copy import deepcopy
import math
from .metrics import aggregate_window, canonical_digest, instant, latest_revisions, source_policy_allowed
from .baselines import build_baseline
from .momentum import compute_momentum
from .membership import resolve_memberships
from .methods import metric_definitions, resolve_method, validate_method
from .confidence import assess_confidence
from .lifecycle import evaluate_lifecycle

VERIFICATION_STATES = ('pending','verified','mismatch','inputs_expired','inputs_deleted','policy_revoked','method_unavailable')
ALGORITHMS = {'normalization': 'canonical-observation-v1', 'deduplication': 'source-revision-v1',
              'clustering': 'temporal-membership-v1', 'baseline': 'robust-baseline-v1',
              'momentum': 'finite-difference-v1', 'lifecycle': 'lifecycle-shadow-1', 'confidence': 'component-support-v1'}


def _artifacts(artifacts):
    by_name = {}
    for artifact in artifacts:
        validate_method(artifact)
        name = artifact['name']
        if name not in ALGORITHMS or artifact['algorithm_id'] != ALGORITHMS[name] or name in by_name:
            raise ValueError('unsupported_or_duplicate_method')
        if name not in ('baseline', 'momentum') and artifact['config']:
            raise ValueError('unsupported_method_configuration')
        by_name[name] = artifact
    if set(by_name) != set(ALGORITHMS): raise ValueError('complete_method_set_required')
    return by_name


def _recompute(manifest):
    methods = _artifacts(manifest['method_artifacts'])
    recipe = manifest['recipe']
    cutoff = recipe['decision_cutoff']
    members = resolve_memberships(manifest['membership_revisions'], cutoff, observations=manifest['source_revisions'], source_policies=manifest['policy_versions'])
    def compute(spec):
        return aggregate_window(manifest['source_revisions'], decision_cutoff=cutoff,
                                memberships=members, episode_id=recipe['episode_id'], source_policies=manifest['policy_versions'], **spec)
    windows = [compute(s) for s in recipe['window_specs']]
    history = [compute(s) for s in recipe['baseline_window_specs']]
    if not windows: raise ValueError('receipt_requires_windows')
    windows.sort(key=lambda w: instant(w['window_start']))
    baseline = build_baseline(history, current_window=windows[-1], decision_cutoff=cutoff, **methods['baseline']['config'])
    enriched = []
    for i, row in enumerate(windows):
        enriched.append({**row, 'episode_id': recipe['episode_id'], 'baseline': baseline,
                         'momentum': compute_momentum(windows[:i+1], baseline, **methods['momentum']['config'])})
    inferred = evaluate_lifecycle(None, enriched)
    observed = {**deepcopy(windows[-1]['observed']), 'platform': windows[-1]['comparison_scope']['platform'],
                'provider_ids': [windows[-1]['comparison_scope']['provider_id']],
                'window_start': windows[-1]['window_start'], 'window_end': windows[-1]['window_end'],
                'previous_window_original_counts': [w['observed']['qualifying_original_count'] for w in windows[:-1]]}
    return {'windows': windows, 'baseline_snapshots': history, 'baseline': baseline, 'observed': observed,
            'calculated': enriched[-1]['momentum'], 'inferred': inferred,
            'confidence': assess_confidence(windows[-1])}


def _manifest_digest(manifest):
    return canonical_digest({k:v for k,v in manifest.items() if k != 'manifest_digest'})


def _chunks(rows, size=256):
    return [{'offset': i, 'count': len(rows[i:i+size]), 'digest': canonical_digest(rows[i:i+size])} for i in range(0,len(rows),size)]


def create_receipt(*, observations, membership_events, window_specs, baseline_window_specs, source_policies,
                   method_artifacts, scope_key, trend_id, episode_id, decision_cutoff, computed_at,
                   execution_state='synthetic_fixture', supersedes_receipt_id=None, correction_reason=None, original_decision_cutoff=None):
    if instant(computed_at) < instant(decision_cutoff): raise ValueError('computation_precedes_cutoff')
    if supersedes_receipt_id:
        if correction_reason not in ('late_revision','late_observation','continued_membership','source_deletion') or original_decision_cutoff is None:
            raise ValueError('explicit_correction_lineage_required')
        if instant(original_decision_cutoff)>instant(decision_cutoff): raise ValueError('future_original_cutoff')
    elif correction_reason is not None or original_decision_cutoff is not None:
        raise ValueError('correction_requires_prior_receipt')
    _artifacts(method_artifacts)
    sources = latest_revisions([r for r in observations if r['scope_key'] == scope_key], decision_cutoff)
    members = sorted((deepcopy(m) for m in membership_events if m['scope_key'] == scope_key and instant(m['available_at']) <= instant(decision_cutoff)), key=lambda m:(m['revision_sequence'],m['event_id']))
    policies = sorted((deepcopy(p) for p in source_policies if p['scope_key'] == scope_key and instant(p.get('available_at',p['effective_at'])) <= instant(decision_cutoff)), key=lambda p:(p['provider_id'],p['version']))
    manifest = {'schema': 'rafii.trend-input-manifest.v2', 'scope_key': scope_key,
                'source_revisions': sources, 'source_chunks': _chunks(sources), 'membership_revisions': members,
                'metric_definitions': metric_definitions(), 'method_artifacts': sorted(deepcopy(method_artifacts),key=lambda m:m['name']),
                'policy_versions': policies,
                'recipe': {'decision_cutoff': decision_cutoff, 'episode_id': episode_id,
                           'window_specs': deepcopy(window_specs), 'baseline_window_specs': deepcopy(baseline_window_specs)}}
    outputs = _recompute(manifest)
    manifest['baseline_snapshots'] = outputs['baseline_snapshots']
    manifest['normalized_inputs'] = {'windows': outputs['windows'], 'baseline': outputs['baseline']}
    manifest['manifest_digest'] = _manifest_digest(manifest)
    current = outputs['windows'][-1]
    receipt = {'schema': 'rafii.trend-trust-receipt.v2', 'trend_id': trend_id, 'episode_id': episode_id,
               'as_of': decision_cutoff, 'computed_at': computed_at, 'decision_cutoff': decision_cutoff,
               'scope': {'scope_key':scope_key},
               'method_versions': {m['name']: {'version':m['version'],'artifact_digest':m['artifact_digest']} for m in method_artifacts},
               'observed': outputs['observed'], 'calculated': outputs['calculated'], 'inferred': outputs['inferred'],
               'interpretation': None, 'coverage': deepcopy(current['coverage']), 'confidence': outputs['confidence'],
               'limitations': ['Filtered sample; platform-wide prevalence unknown', 'Candidate method; no public prediction claim'],
               'input_manifest_digest': manifest['manifest_digest'],
               'snapshot_refs': [w['snapshot_id'] for w in outputs['windows']+outputs['baseline_snapshots']],
               'calibration_ref': None, 'execution_state': execution_state,
               'verification': {'state':'pending', 'absolute_tolerance':1e-9,'relative_tolerance':1e-6},
               'supersedes_receipt_id':supersedes_receipt_id, 'correction_reason':correction_reason,
               'original_decision_cutoff':original_decision_cutoff,
               'replay_mode':'correction' if supersedes_receipt_id else 'historical_live_decision'}
    receipt['receipt_id'] = 'receipt_' + canonical_digest(receipt)
    return {'receipt':receipt, 'manifest':manifest}


def current_receipt_status(manifest, *, at, deleted_observation_ids=(), revoked_policy_versions=(), current_policies=None):
    """Complete dependency check; storage may index it to supply a bounded read status.

    Current policy snapshots MUST be supplied separately by the caller. Historical
    policy versions in the manifest cannot authorize a current read by themselves.
    """
    status = {'state':'verified', 'checked_at':at, 'manifest_digest':manifest['manifest_digest']}
    deleted, revoked = set(deleted_observation_ids), set(revoked_policy_versions)
    if current_policies is None: return {**status,'state':'policy_revoked','reason':'current_policy_lookup_required'}
    for row in manifest['source_revisions']:
        if row['observation_id'] in deleted or row['operation'] == 'delete': return {**status,'state':'inputs_deleted'}
        if row['source_policy_version'] in revoked: return {**status,'state':'policy_revoked'}
        if instant(row['retention_until']) <= instant(at): return {**status,'state':'inputs_expired'}
        if not source_policy_allowed(row, current_policies, at): return {**status,'state':'policy_revoked'}
    return status


def _equal(actual, expected):
    if isinstance(expected,bool) or expected is None or isinstance(expected,str): return actual == expected and type(actual) is type(expected)
    if isinstance(expected,int): return type(actual) is int and actual == expected
    if isinstance(expected,float):
        return type(actual) in (int,float) and math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected) <= max(1e-9,1e-6*abs(expected))
    if isinstance(expected,dict): return isinstance(actual,dict) and actual.keys() == expected.keys() and all(_equal(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list): return isinstance(actual,list) and len(actual) == len(expected) and all(_equal(a,b) for a,b in zip(actual,expected))
    return False


def verify_receipt(receipt, manifest, method_registry, *, at, current_policies, deleted_observation_ids=(), revoked_policy_versions=()):
    """Recompute complete deterministic inputs; numeric claims fail closed."""
    result = {'state':'pending','checked_at':at,'manifest_digest':receipt.get('input_manifest_digest'),
              'receipt_digest':canonical_digest(receipt)}
    status = current_receipt_status(manifest, at=at, deleted_observation_ids=deleted_observation_ids,
                                    revoked_policy_versions=revoked_policy_versions,current_policies=current_policies)
    if status['state'] != 'verified': return {**result,'state':status['state']}
    try:
        if receipt.get('receipt_id') != 'receipt_' + canonical_digest({k:v for k,v in receipt.items() if k!='receipt_id'}):
            return {**result,'state':'mismatch','reason':'receipt_seal_integrity'}
        if (manifest['manifest_digest'] != _manifest_digest(manifest) or receipt['input_manifest_digest'] != manifest['manifest_digest']
            or manifest['source_chunks'] != _chunks(manifest['source_revisions'])
            or manifest['metric_definitions'] != metric_definitions()):
            return {**result,'state':'mismatch','reason':'manifest_integrity'}
        for method in manifest['method_artifacts']:
            resolved = resolve_method(method_registry, method['name'],method['version'],method['artifact_digest'])
            if resolved != method: return {**result,'state':'method_unavailable','reason':'recorded_implementation_not_supported','method_name':method['name'],'method_version':method['version']}
        expected_versions = {m['name']:{'version':m['version'],'artifact_digest':m['artifact_digest']} for m in manifest['method_artifacts']}
        if receipt['method_versions'] != expected_versions: return {**result,'state':'mismatch','reason':'method_references'}
        if manifest['recipe']['decision_cutoff'] != receipt['decision_cutoff'] or manifest['scope_key'] != receipt['scope']['scope_key']:
            return {**result,'state':'mismatch','reason':'recipe_scope_or_cutoff'}
        outputs = _recompute(manifest)
        checks = [(receipt['observed'],outputs['observed']), (receipt['calculated'],outputs['calculated']),
                  (receipt['inferred'],outputs['inferred']), (receipt['coverage'],outputs['windows'][-1]['coverage']),
                  (receipt['confidence'],outputs['confidence']),
                  (manifest['normalized_inputs'],{'windows':outputs['windows'],'baseline':outputs['baseline']}),
                  (manifest['baseline_snapshots'],outputs['baseline_snapshots']),
                  (receipt['snapshot_refs'],[w['snapshot_id'] for w in outputs['windows']+outputs['baseline_snapshots']])]
        if not all(_equal(a,b) for a,b in checks): return {**result,'state':'mismatch','reason':'recomputation'}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {**result,'state':'mismatch','reason':'invalid_input_or_artifact'}
    return {**result,'state':'verified'}


def project_receipt(receipt, verification, *, at, current_status):
    """Bounded read projection. No replay; requires fresh current dependency status.

    Caller supplies trusted verifier output and an indexed current status for this
    manifest. Returning a historical 'verified' row alone is insufficient.
    """
    state = verification.get('state','pending')
    if state not in VERIFICATION_STATES: state = 'pending'
    if current_status.get('state') not in VERIFICATION_STATES or current_status.get('checked_at') != at or current_status.get('manifest_digest') != receipt['input_manifest_digest']:
        state = 'pending'
    elif current_status['state'] != 'verified': state = current_status['state']
    if verification.get('receipt_digest') != canonical_digest(receipt) or verification.get('manifest_digest') != receipt['input_manifest_digest']:
        state = 'mismatch'
    safe = {'receipt_id':receipt['receipt_id'], 'verification_state':state, 'as_of':receipt['as_of'],
            'observed':None, 'calculated':None, 'inferred':{'stage':None}, 'interpretation':None,
            'publication_state':'shadow_only'}
    if state == 'verified':
        safe.update(observed=deepcopy(receipt['observed']),calculated=deepcopy(receipt['calculated']),
                    inferred=deepcopy(receipt['inferred']),coverage=deepcopy(receipt['coverage']),
                    confidence=deepcopy(receipt['confidence']),method_versions=deepcopy(receipt['method_versions']),
                    limitations=deepcopy(receipt['limitations']))
    return safe

"""Explicit synthetic seed for Tier C browser tests; import has no database effects.

Intentionally NOT named postgres_*: the PostgreSQL acceptance wildcard must never
execute seed helpers. Caller owns a fresh disposable cluster and applies040.
"""
from __future__ import annotations
import json
import time
import uuid
from postriff_phase2.growth.trends import contracts, opportunities, relevance
from postriff_phase2.growth.trends.service import coverage
from postriff_phase2.growth.trends.store import TrendStore


def seed_browser(service, connection, *, scenario='radar'):
    assert scenario in ('radar', 'lab', 'dismiss', 'pool_accept', 'pool_dismiss', 'learning')
    platform = 'Threads' if scenario == 'learning' else 'Bluesky'
    native_platform = platform.lower()
    store = TrendStore(connection)
    rows = []
    for width in (1440, 390):
        actor = str(uuid.uuid4())
        token = 'dev:' + actor
        wid = service.bootstrap(token)['workspaceId']
        scope = 'workspace:' + wid
        channel = str(uuid.uuid4())
        with connection() as db:
            state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]
            if isinstance(state, str):
                state = json.loads(state)
            state['workspace']['name'] = 'Synthetic Tier C ' + scenario + ' browser ' + str(width)
            state['phase2']['channels'] = [{'id': channel, 'platform': platform, 'language': 'en',
                'account': 'Synthetic local destination', 'revoked': False, 'configured': True,
                'identityVerified': True, 'capabilityVerified': False, 'displayState': 'read_verified',
                'execution': 'synthetic-test-only', 'expiresAt': time.time()+3600, 'verifiedAt': time.time(),
                'scopes': ['synthetic:read'], 'capabilityVersion': 1, 'accountType': 'profile'}]
            if scenario.startswith('pool_'):
                # Explicit stored plan, paused recipe, no recurring drafting authorization.
                slot = {'id': 'synthetic-planned-slot', 'day': '2026-09-28', 'localTime': '09:00',
                    'platform': platform, 'account': 'Synthetic local destination', 'language': 'en',
                    'contentType': 'personal_reflection', 'goal': 'Keep existing planned work',
                    'angle': 'My original planned post', 'status': 'needs_input', 'reason': None,
                    'question': 'What did you notice?', 'variantId': None, 'quality': None, 'creative': None}
                state.setdefault('coworker', {})['weekly'] = {'revision': 1,
                    'recipes': [{'id': 'synthetic-paused-recipe', 'name': 'Demo existing plan', 'status': 'paused',
                        'version': 1, 'destinations': [], 'goals': [], 'contentMix': {}, 'timeZone': 'UTC',
                        'planningDay': 1, 'planningHour': 9}],
                    'weeks': [{'id': 'synthetic-existing-week', 'recipeId': 'synthetic-paused-recipe',
                        'weekOf': '2026-09-28', 'state': 'ready_for_review', 'blockedReason': None, 'slots': [slot]}]}
            db.execute('UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), wid))
        now = time.time()
        past, end = opportunities.iso(now-3600), opportunities.iso(now+3600)
        provider = 'synthetic-tier-c-' + scenario + '-' + str(width)
        store.ensure_scope(scope)
        store.register_contract(provider, 'fixture-v1', list(contracts.PERMISSIONS), past, end, {'execution': 'synthetic-test-only'})
        rights = {p: {'state': 'allow', 'policy_ref': 'synthetic-browser.v1', 'audience_scope': scope, 'expires_at': end} for p in contracts.PERMISSIONS}
        store.register_policy({'scope_key': scope, 'provider_id': provider, 'version': 'fixture-v1', 'rights': rights,
            'effective_at': past, 'expires_at': end, 'retention_seconds': 7200, 'readiness': 'ready'}, provider_contract_version='fixture-v1')
        oid, tid, rid = (str(uuid.uuid4()) for _ in range(3))
        payload = {'platform': native_platform, 'native_id': 'synthetic-'+str(width), 'author_status': 'known',
            'author_key': 'did:fixture:browser', 'text': 'Synthetic Tier C source: compare your own two practice speeds.',
            'canonical_url': 'https://fixture.invalid/trend-browser', 'language': 'en'}
        observed = opportunities.iso(time.time()-60)
        store.put_observation({'observation_id': oid, 'scope_key': scope, 'provider_id': provider, 'provider_contract_version': 'fixture-v1',
            'source_policy_version': 'fixture-v1', 'source_identity': 'browser-'+str(width), 'revision_identity': 'r1', 'revision_sequence': 1,
            'kind': 'raw_post', 'operation': 'create', 'event_at': observed, 'received_at': observed, 'available_at': observed,
            'time_basis': 'provider_event', 'coverage_epoch': 'synthetic-browser.v1', 'provenance': {'access_method': 'synthetic'},
            'retention_until': end, 'rights': rights, 'deletion_key': 'browser-'+str(width), 'payload': payload,
            'payload_digest': contracts.digest(payload), 'schema_version': contracts.SCHEMA_VERSION})
        method, artifact = 'synthetic.browser.stored', contracts.digest({'algorithm': 'synthetic-count', 'v': 1})
        store.put_method(method, 'v1', artifact, {'execution': 'synthetic-test-only'}, qualification='shadow')
        with connection() as db:
            cutoff = contracts.iso(db.execute('SELECT clock_timestamp()').fetchone()[0])
        manifest = store.put_manifest(scope, [{'scope_key': scope, 'node_id': oid}], decision_cutoff=cutoff,
            available_at=cutoff, retention_until=end)
        common = {'scope_key': scope, 'revision': 1, 'manifest_id': manifest['manifest_id'], 'method_id': method,
            'method_version': 'v1', 'decision_cutoff': cutoff, 'available_at': cutoff, 'retention_until': end}
        receipt = {'schema': 'rafii.trend-trust-receipt.v2', 'trend_id': tid,
            'observed': {'count': 1, 'execution': 'synthetic-test-only'}, 'method': {'id': method, 'version': 'v1',
            'formula': 'Synthetic fixture count / one observed hour; no population claim', 'calibration_cohort': None, 'snapshot_refs': [oid]}}
        store.put_receipt({**common, 'receipt_id': rid, 'payload': receipt})
        verification = store.record_verification(scope, rid, recomputed_digest=contracts.digest(receipt),
            input_manifest_digest=manifest['digest'], method_artifact_digest=artifact)
        assert verification['state'] == 'verified'
        metric = {'value': 1, 'unit': 'posts/hour', 'definition_id': 'mention_rate', 'definition_version': 'synthetic-v1',
            'window': {'start': past, 'end': cutoff}, 'baseline_ref': None, 'denominator': 'One synthetic observed hour', 'null_reason': None}
        cov = {**coverage(scope=scope), 'availability': 'available', 'representation': 'sampled_posts',
            'completeness': 'complete_within_scope', 'scope_ref': scope, 'latest_successful_read': cutoff,
            'freshness_deadline': end, 'sources': [{'platform': native_platform, 'availability': 'available', 'reason': 'Synthetic local seed'}]}
        title = 'Synthetic Tier C ' + scenario + ' practice ' + str(width)
        trend = {'id': tid, 'canonical_topic': title, 'platform': native_platform, 'language': 'en', 'niche': 'music',
            'observed': {'summary': 'Synthetic stored observation for real API and database integration.', 'first_detected': observed,
                'latest_observed': observed, 'metrics': {'mention_rate': metric}, 'timeline': []},
            'calculated': {'mention_rate': metric}, 'inferred': {}, 'coverage': cov, 'trust_receipt_id': rid, 'expires_at': end,
            'limitations': ['Demo data: Synthetic seed only. No provider observation or calibrated stage claim.'],
            'evidence': [{'id': oid, 'platform': native_platform, 'language': 'en', 'excerpt': payload['text'], 'url': payload['canonical_url'],
                'observed_at': observed, 'expires_at': end, 'rights': rights, 'scope_key': scope}]}
        store.put_projection({**common, 'kind': 'trend', 'object_id': tid, 'receipt_id': rid, 'payload': trend})
        opportunity = opportunities.candidate(trend, relevance.evaluate(trend, state), state, wid, now,
            angles=[{'id': 'synthetic-angle', 'title': 'Compare your own practice', 'contribution': 'Use two recordings of your own playing.',
                'factual_requirements': ['Your own recordings'], 'format_reason': 'A direct comparison'}], platform_targets=[native_platform])
        # Test-only eligibility is explicit. Production screening stays unqualified.
        opportunity.update(state='suggested', qualified=True, title='Synthetic original practice comparison',
            contribution='Explain what you heard in your own recordings.', uncertainty='Audience response is unknown.')
        if scenario.startswith('pool_') or scenario == 'learning':
            opportunity.update(qualified=False, executable_ready=True,
                uncertainty='Demo data: Unqualified interpretation; audience response is unknown.')
        store.put_projection({**common, 'kind': 'opportunity', 'object_id': opportunity['id'], 'receipt_id': rid,
            'payload': opportunity, 'context_digest': opportunity['context_digest']})
        rows.append({'scenario': scenario, 'width': width, 'principal': actor, 'workspace_id': wid, 'trend_id': tid, 'receipt_id': rid,
            'opportunity_id': opportunity['id'], 'channel_id': channel, 'title': title})
    for row in rows:
        service.get(row['workspace_id'], 'dev:'+row['principal'])  # Real presenter must accept the fixture before a browser starts.
    return rows


def seed_lab_drafts(service, connection, rows):
    """Explicit synthetic saved drafts; real acceptance and server-derived lineage.

    Mirrors DurableServiceTests' selective Lab fixture. No generation endpoint,
    provider or model is invoked, and no claim of Ideas generation E2E is made.
    Separate workspaces leave the original Radar no-draft assertion intact.
    """
    for row in rows:
        assert row['scenario'] == 'lab'
        token = 'dev:' + row['principal']
        accepted = service.coworker.trends.accept(row['workspace_id'], token, row['opportunity_id'], {
            'revision': 1, 'angle_id': 'synthetic-angle', 'channel_id': row['channel_id'],
            'goal': 'Synthetic Lab browser check only', 'idempotency_key': 'synthetic-lab-browser-seed'})
        sid = accepted['data']['source_id']
        phrase = service.coworker.trends.get(row['workspace_id'], token, row['trend_id'])['data']['evidence'][0]['excerpt']
        did = str(uuid.uuid4())
        original = 'Demo data: My independently supplied practice observation. ' + phrase
        with connection() as db:
            state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s FOR UPDATE', (row['workspace_id'],)).fetchone()[0]
            state['variants'] = [{'id': did, 'text': original, 'revision': 1, 'platform': 'Bluesky', 'language': 'en',
                'sourceIds': [sid], 'unknowns': [], 'warnings': [], 'revisions': [], 'needsReview': False,
                'voiceRevision': state.get('speaker', {}).get('activeRevision'),
                'trendLineage': opportunities.lineage(state, [sid])}]
            db.execute('UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), row['workspace_id']))
        row.update(source_id=sid, draft_id=did, original_text=original, repeated_phrase=phrase,
                   seed_kind='explicit_synthetic_saved_draft_with_server_accepted_source_lineage')
        service.get(row['workspace_id'], token)


def seed_learning_sources(service, connection, rows):
    """Explicit synthetic Threads seed; real exposure/acceptance, shadow inference.

    Does not publish, manufacture qualification, choose metrics or read providers.
    The later browser must explicitly select the current native catalog options.
    """
    for row in rows:
        assert row['scenario'] == 'learning'
        wid, token = row['workspace_id'], 'dev:' + row['principal']
        page = service.coworker.trends.list(wid, token, kind='opportunity')
        op = next(o for o in page['data'] if o['id'] == row['opportunity_id'])
        view = service.coworker.trends.exposure(wid, token, {
            'event_id': str(uuid.uuid4()), 'exposure_token': page['exposure_token'],
            'opportunity_id': op['id'], 'opportunity_revision': op['revision'],
            'trust_receipt_id': op['trust_receipt_id'], 'context_digest': op['context_digest'],
            'eligible_candidates': [{'opportunity_id': o['id'], 'revision': o['revision']} for o in page['data']]})
        accepted = service.coworker.trends.accept(wid, token, op['id'], {
            'revision': op['revision'], 'angle_id': 'synthetic-angle', 'channel_id': row['channel_id'],
            'goal': 'Demo only: a free goal must not infer a measurement objective',
            'idempotency_key': 'synthetic-learning-accept', 'exposure_id': view['data']['exposure_id']})
        row.update(source_id=accepted['data']['source_id'], exposure_id=view['data']['exposure_id'])
        descriptor = service.coworker.performance_view(wid, token)['trend_learning']
        assert len(descriptor['choice_options']) == 1
        assert descriptor['choice_options'][0]['provider'] == 'threads'
        assert descriptor['choice_options'][0]['saved_choice'] is None
        assert descriptor['outcome_states'] == {}
        with connection() as db:
            row['initial_revision'] = db.execute('SELECT revision FROM pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]

def seed_learning_publications(connection, row):
    """Test-only stored publication records bracketing the actual browser choice.

    These are NOT provider-confirmed publications or external publishing. No native
    metric observations are invented; the later record must remain pending/null.
    """
    import copy
    with connection() as db:
        state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s FOR UPDATE', (row['workspace_id'],)).fetchone()[0]
        source = next(s for s in state['sources'] if s['id'] == row['source_id'])
        binding = source['origin']['trendLineage']
        choices = state['coworker']['trendLearning']['metricChoices']
        assert len(choices) == 1
        choice = choices[0]
        chosen = opportunities.epoch(choice['selected_at'])
        accepted = opportunities.epoch(binding['accepted_at'])
        assert accepted < chosen
        jobs = []
        for label, at in [('before-choice', (accepted + chosen) / 2), ('after-choice', max(time.time(), chosen + .001))]:
            jid = str(uuid.uuid4())
            text = 'Demo data: synthetic stored publication record ' + label
            manifest = {'channelId': row['channel_id'], 'platform': 'Threads', 'variantId': jid,
                'payload': {'text': text, 'language': 'en'}, 'contentType': {'id': 'personal_reflection'},
                'timing': {'timestamp': at}, 'paidPromotion': False, 'trendLineage': [copy.deepcopy(binding)],
                'trendPublication': {'variantRevision': 1, 'textDigest': contracts.digest(text),
                    'channelId': row['channel_id'], 'platform': 'Threads'}}
            jobs.append({'id': jid, 'state': 'verified', 'providerReference': 'synthetic-native-' + jid,
                'verifiedAt': at, 'manifest': manifest, 'execution': 'synthetic-test-only'})
        state['phase2']['jobs'] = jobs
        db.execute('UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), row['workspace_id']))
    return {'past_job': jobs[0]['id'], 'future_job': jobs[1]['id'], 'choice_id': choice['id'],
            'execution': 'synthetic stored publication records; no external publication or native observations'}


def revoke_learning_fixture(connection, row):
    """Revoke only this isolated seed's policy through the real revocation API."""
    from postriff_phase2.growth.trends import revocation
    revocation.revoke_policy(TrendStore(connection), 'workspace:' + row['workspace_id'],
        'synthetic-tier-c-learning-' + str(row['width']), 'fixture-v1')

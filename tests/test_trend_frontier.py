"""No-network contracts and actual disposable PostgreSQL frontier behavior."""
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
import json
import os
import unittest
import uuid
from unittest.mock import Mock

from postriff_phase2.growth.trends import contracts as C, frontier, retention, revocation
from postriff_phase2.growth.trends.jobs import TrendJobs
from postriff_phase2.growth.trends.pipeline import encode_manifest
from postriff_phase2.growth.trends.policy import SourcePolicy, ProviderCapability
from postriff_phase2.growth.trends.providers.base import observation
from postriff_phase2.growth.trends.providers.registry import ProviderRegistry
from postriff_phase2.growth.trends.store import TrendStore, row, utcnow
from test_trend_integration import DurableServiceTests


def configuration(**overrides):
    return dict(enabled=True, routes={'related_topic':'query','hashtag':'query','watch':'query',
                'keyword_independent_sample':'sample','corroboration':'query'}, categories=['general'],
                excluded_terms=['forbidden'], query_version='literal-v1', ranking_version='bounded-v1', filter={},
                window_seconds=3600, budget_units=20, protected_units=0, required_watch_units=0,
                watch_queries=[], allocation={'watch':60,'exploration':25,'corroboration':15},
                rejected_sample_modulus=1) | overrides


class FrontierOffline(unittest.TestCase):
    def test_native_normalization_and_operator_rejection(self):
        self.assertEqual(frontier.normalized_query('  原生 ＡＢＣ  #話題  '),'原生 abc #話題')
        for value in ('https://example.com','site:example.com','a OR b','x\nsecret','a;bad','x'*301,True):
            with self.subTest(value=value), self.assertRaises(C.ContractError): frontier.normalized_query(value)

    def test_default_off_and_explicit_bounded_controls(self):
        for value in ({},{'enabled':True},configuration(enabled=1),configuration(budget_units=True),
                      configuration(routes={'other':'query'}),configuration(filter={'query':{'nested':'raw'}})):
            with self.subTest(value=value), self.assertRaises(C.ContractError): frontier.controls({'frontier':value})
        self.assertEqual(frontier.controls({'frontier':configuration()})['allocation']['exploration'],25)

    def test_default_allocation_and_pressure_preserve_protected_and_watches(self):
        c = configuration(budget_units=100,protected_units=4,required_watch_units=3)
        a = frontier.allocate(c,104)
        self.assertEqual([a[k] for k in ('protected','watch','exploration','corroboration')],[4,60,25,15])
        a = frontier.allocate(c,5)
        self.assertEqual([a[k] for k in ('protected','watch','exploration')],[4,1,0])
        self.assertTrue(a['coverage_reduced'])


@unittest.skipUnless(os.environ.get('TREND_SERVICE_TEST_DSN'), 'explicit isolated SQL fixture required')
class FrontierSQL(unittest.TestCase):
    def setUp(self):
        DurableServiceTests.setUpClass.__func__(type(self))
        self.store = TrendStore(self.connect, offline_replay=True)
        self.scope = 'workspace:'+self.wid
        self.at = utcnow()
        self.before = C.iso(C.instant(self.at)-timedelta(hours=1))
        self.end = C.iso(C.instant(self.at)+timedelta(hours=1))
        self.provider = 'frontier-fixture-'+uuid.uuid4().hex[:8]
        self.keys = [self.wid+':'+d for d in ('system','provider','workspace')]
        self.rights = {n:{'state':'allow','policy_ref':'synthetic','audience_scope':self.scope,'expires_at':self.end} for n in C.PERMISSIONS}
        self.cap = ProviderCapability(self.provider,'search','1',('raw_post','trend_seed'),
            'https://fixture.invalid','synthetic','fixture',('read',),20,4096,10,3,'synthetic_unit','fixture-delete')
        self.adapter = Mock(side_effect=AssertionError('no provider invocation'))
        self.adapter.discovery_modes = ('query','sample')
        self.registry = ProviderRegistry()
        self.jobs = TrendJobs(self.store)
        for key, dimension in zip(self.keys,('system','provider','workspace')):
            self.jobs.configure_budget(key,dimension,10000,self.before,self.end)
        self.flags = {'RAFII_TREND_'+n+'_ENABLED':True for n in ('INTELLIGENCE','RADAR','PROVIDER_OPERATIONS')}
        self.flags.update(RAFII_TREND_WORKSPACE_ALLOWLIST=self.wid,RAFII_TREND_ALLOWED_OPERATIONS=self.provider+':search')
        self.engine = frontier.DiscoveryFrontier(self.store,self.registry,values=self.flags,clock=lambda:self.at)
        self.install(configuration())
        self.sources = [self.source('author-'+str(i), '原生 話題 musical phrase #music') for i in range(3)]

    def tearDown(self):
        self.adapter.assert_not_called()

    def install(self, c, version=None):
        self.version = version or str(uuid.uuid4())
        self.policy = SourcePolicy('synthetic',self.version,self.provider,'search',self.scope,self.rights,
            'synthetic-reviewer','synthetic-review',self.before,self.end,1800,'ready',verified_scopes=('read',),
            price_ref='synthetic-price',approved_attempt_cap_microusd=100)
        self.store.register_contract(self.provider,'1',list(C.PERMISSIONS),self.before,self.end)
        schedule = dict(enabled=True,start_at=self.before,interval_seconds=60,max_samples=120,max_items=10,
            seconds=5,budget_keys=self.keys,reservation_microusd=25)
        self.store.register_policy({**asdict(self.policy),'schedule':schedule,'frontier':c},provider_contract_version='1')
        self.registry.register(self.cap,self.policy,self.adapter)

    def source(self, author, text, kind='raw_post'):
        sid = str(uuid.uuid4())
        payload = {'platform':'synthetic','native_id':sid,'author_status':'known','author_key':author,'text':text,'language':'zh-Hant'}
        if kind == 'trend_seed': payload = {'topic_id':text,'native_score_semantics':'fixture seed'}
        o = observation(policy=self.policy,source_identity=sid,revision_identity='1',sequence=1,kind=kind,
            operation='create',payload=payload,event_at=self.at,received_at=self.at,available_at=self.at,
            coverage_epoch='synthetic',contract_version='1',access_method='synthetic')
        self.store.put_observation(o)
        return o['observation_id']

    def proposal(self, query='原生 話題', **kw):
        return {'route':'related_topic','query':query,'category':'general','language':'zh','evidence_ids':self.sources,**kw}

    def produce(self, proposals=()):
        return self.engine.produce(self.scope,self.provider,self.version,proposals)

    def admitted(self, result, route='related_topic'):
        return next(p for p in result['decisions'] if p['decision']=='admitted' and p['route']==route)

    def job(self, jid):
        with self.connect() as db, db.cursor() as cur:
            cur.execute('SELECT * FROM pr_trend_jobs WHERE scope_key=%s AND job_id=%s',(self.scope,jid))
            return row(cur)

    def fetch(self, sql, args=()):
        with self.connect() as db: return db.execute(sql,args).fetchone()

    def details(self, expression='原生 話題', kind='language_pattern', object_id=None, revision=1):
        refs = [{'scope_key':self.scope,'node_id':sid} for sid in self.sources]
        raw = {'patterns':[{'expression':expression,'language':'zh','kind':'phrase','evidence_refs':self.sources}]}
        if kind=='genome': raw = {'context_and_seeds':{'seeds':[{'original_spans':[{'text':expression}], 'language':'zh','evidence_refs':self.sources}]}}
        document = {'input_digest':C.digest(refs),'details':raw}
        document['manifest_digest'] = C.digest(document)
        codec,chunks = encode_manifest(document)
        expiry = C.iso(C.instant(self.at)+timedelta(seconds=1700))
        manifest = self.store.put_manifest(self.scope,refs,decision_cutoff=self.at,available_at=self.at,
            retention_until=expiry,recipe={'detail_codec':codec},chunks=chunks,document_digest=document['manifest_digest'])
        method = 'frontier-test-'+uuid.uuid4().hex
        self.store.put_method(method,'1',C.digest(method),{'synthetic':True})
        oid = object_id or str(uuid.uuid4())
        self.store.put_projection({'scope_key':self.scope,'kind':kind,'object_id':oid,'revision':revision,
            'manifest_id':manifest['manifest_id'],'method_id':method,'method_version':'1','decision_cutoff':self.at,
            'available_at':self.at,'retention_until':expiry,'payload':{'synthetic':True}})
        return oid

    def test_tick_reaches_current_native_patterns_without_caller_proposals(self):
        self.details()
        result = self.engine.tick(limit=20)
        self.assertEqual(result['blocked'],0)
        admitted = self.admitted(result['results'][0])
        job = self.job(admitted['job_id'])
        self.assertEqual(job['payload']['query'],'原生 話題')
        self.assertEqual(job['payload']['frontier']['evidence_ids'],sorted(self.sources))
        self.assertEqual(admitted['reason'],'diverse_observations')
        self.assertEqual(len(result['results'][0]['jobs']),2)
        self.assertIsNone(self.job(result['results'][0]['jobs'][0])['reservation_id'])

    def test_tick_expands_from_persisted_genome_and_persisted_parent(self):
        self.details(kind='genome')
        first = self.admitted(self.engine.tick()['results'][0])
        self.details('musical phrase',kind='genome')
        result = self.engine.tick()['results'][0]
        child = next(d for d in result['decisions'] if d.get('parent_id')==first['request_id'] and d['decision']=='admitted')
        self.assertEqual(child['depth'],1)
        self.assertEqual(child['root_id'],first['request_id'])

    def test_parent_two_generations_and_five_children_per_root_generation(self):
        self.install(configuration(allocation={'watch':0,'exploration':100,'corroboration':0}))
        parent = self.admitted(self.produce([self.proposal()]))
        batch = self.produce([self.proposal('child '+str(i),parent_id=parent['request_id']) for i in range(6)])
        children = [d for d in batch['decisions'] if d['route']=='related_topic' and d['decision']=='admitted']
        self.assertEqual(len(children),5)
        self.assertIn('frontier_child_limit',[d['reason'] for d in batch['decisions']])
        grandchild = self.admitted(self.produce([self.proposal('grandchild',parent_id=children[0]['request_id'])]))
        result = self.produce([self.proposal('third',parent_id=grandchild['request_id'])])
        self.assertIn('frontier_depth_limit',[d['reason'] for d in result['decisions']])

    def test_equivalent_requests_and_concurrent_ticks_are_deduplicated(self):
        proposal = self.proposal()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _:self.produce([proposal]),range(3)))
        self.assertEqual(len({self.admitted(r)['job_id'] for r in results}),1)
        result = self.produce([self.proposal('  原生  話題 ')])
        self.assertIn('frontier_duplicate',[d['reason'] for d in result['decisions']])
        self.assertEqual(self.fetch("SELECT count(*) FROM pr_trend_jobs WHERE scope_key=%s AND idempotency_key LIKE 'discovery:%%'",(self.scope,))[0],2)

    def test_rejected_sample_has_reason_denominator_and_no_query_text(self):
        bad = self.proposal('forbidden SECRET')
        result = self.produce([bad,self.proposal('site:private.test')])
        self.assertEqual(len([d for d in result['decisions'] if d['decision']=='dropped']),2)
        report = self.engine.report(self.scope,self.provider,self.version)
        self.assertEqual(sum(d['examined'] for d in report['counts']),3)
        self.assertEqual(len(report['rejected_sample']),2)
        saved = self.fetch('SELECT jsonb_agg(payload)::text FROM pr_trend_outbox WHERE scope_key=%s AND event_type=%s',(self.scope,frontier.EVENT))[0]
        self.assertNotIn('SECRET',saved); self.assertNotIn('private.test',saved)
        self.assertEqual(result['allocation']['exploration'],5)

    def test_unsupported_query_adapter_and_unreviewed_routes_abstain(self):
        self.adapter.discovery_modes = ('sample',)
        result = self.produce([self.proposal()])
        self.assertIn('frontier_query_capability_unknown',[d['reason'] for d in result['decisions']])
        self.assertEqual(len(result['jobs']),1)

    def test_unknown_rights_and_budget_exhaustion_cannot_queue(self):
        with self.connect() as db:
            db.execute('UPDATE pr_trend_budget_limits SET unknown_micro_usd=cap_micro_usd WHERE budget_key=%s',(self.keys[0],))
        with self.assertRaises(C.ContractError): self.produce([self.proposal()])
        self.assertEqual(self.fetch("SELECT count(*) FROM pr_trend_jobs WHERE scope_key=%s AND idempotency_key LIKE 'discovery:%%'",(self.scope,))[0],0)

    def test_pressure_preserves_protected_watches_and_exposes_reduced_breadth(self):
        self.install(configuration(protected_units=2,required_watch_units=2,watch_queries=['reviewed watch']))
        with self.connect() as db:
            db.execute('UPDATE pr_trend_budget_limits SET cap_micro_usd=75 WHERE budget_key=%s',(self.keys[0],))
        result = self.produce([self.proposal()])
        self.assertEqual(result['allocation']['exploration'],0)
        self.assertTrue(result['allocation']['coverage_reduced'])
        self.assertEqual(len(result['jobs']),1)
        self.assertEqual(self.job(result['jobs'][0])['payload']['query'],'reviewed watch')

    def test_claim_reserves_actual_dimensions_and_dispatch_checks_current_cursor(self):
        d = self.admitted(self.produce([self.proposal()]))
        queued = self.job(d['job_id'])
        context = self.engine.dispatch_context(queued)
        claim = self.jobs.claim('frontier-test',job_id=d['job_id'],scope_key=self.scope,budget_keys=self.keys,amount_micro_usd=25)
        self.assertIsNotNone(claim['reservation_id'])
        self.assertEqual(self.fetch('SELECT reserved_micro_usd FROM pr_trend_budget_limits WHERE budget_key=%s',(self.keys[0],))[0],25)
        self.engine.dispatch_context(claim)
        running = self.jobs.start(claim)
        self.engine.dispatch_context(running)
        with self.connect() as db:
            db.execute("INSERT INTO pr_trend_provider_cursors(scope_key,provider_id,partition_key,generation,cursor_value,coverage_state) VALUES(%s,%s,%s,1,'{}','partial')",(self.scope,self.provider,context['partition_key']))
        with self.assertRaisesRegex(C.ContractError,'frontier_cursor_changed'): self.engine.dispatch_context(running)

    def test_payload_tamper_and_missing_actual_reservation_fail_closed(self):
        d = self.admitted(self.produce([self.proposal()]))
        job = self.job(d['job_id']); altered = copy.deepcopy(job); altered['payload']['query']='tampered'
        with self.assertRaises(C.ContractError): self.engine.dispatch_context(altered)
        claim = self.jobs.claim('frontier-test',job_id=d['job_id'],scope_key=self.scope)
        with self.assertRaisesRegex(C.ContractError,'frontier_reservation_required'): self.engine.dispatch_context(claim)

    def test_source_deletion_cancels_query_and_purges_dependent_audit(self):
        produced = self.produce([self.proposal()])
        d = self.admitted(produced)
        unrelated = {identifier: self.job(identifier)['state'] for identifier in produced['jobs']
                     if identifier != d['job_id']}
        with self.connect() as db:
            db.execute("UPDATE pr_trend_nodes SET validity='revoked' WHERE scope_key=%s AND node_id=%s",(self.scope,self.sources[0]))
        with self.assertRaises(C.ContractError): self.engine.dispatch_context(self.job(d['job_id']))
        self.maintain_until_cancelled([d['job_id']])
        self.assertEqual(self.job(d['job_id'])['payload'],{})
        for identifier, state in unrelated.items():
            self.assertEqual(self.job(identifier)['state'], state)
        # The suite intentionally shares an isolated database and earlier tests
        # leave many independently purgeable nodes. This assertion is about the
        # revoked dependency cascade, not the worker's 100-row page boundary.
        retention.sweep(self.store,limit=1000)
        self.assertEqual(self.fetch('SELECT payload FROM pr_trend_outbox WHERE scope_key=%s AND event_key=%s',(self.scope,'frontier-request:'+d['request_id']))[0],{})

    def test_revoked_policy_cannot_read_dispatch_or_retain_query(self):
        produced = self.produce([self.proposal()])
        self.assertEqual(len(produced['jobs']),2)
        d = self.admitted(produced)
        with self.connect() as db:
            db.execute('UPDATE pr_trend_source_policies SET revoked_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s',(self.scope,self.provider))
        with self.assertRaises(C.ContractError): self.engine.report(self.scope,self.provider,self.version)
        with self.assertRaises(C.ContractError): self.engine.dispatch_context(self.job(d['job_id']))
        self.maintain_until_cancelled(produced['jobs'])
        for identifier in produced['jobs']:
            self.assertEqual(self.job(identifier)['payload'],{})

    def maintain_until_cancelled(self, identifiers):
        # Other tests retain valid events in this isolated shared database.
        # Their randomly ordered scopes can fill the first 100-row page.
        after = None
        for _ in range(20):
            receipt = self.engine.maintenance(limit=100, after=after)
            if all(self.job(identifier)['state'] == 'cancelled' for identifier in identifiers):
                return
            self.assertIsNotNone(receipt['next_key'], 'Target cancellation is missing from the bounded scan.')
            after = receipt['next_key']
        self.fail('Target jobs were not cancelled within 20 bounded maintenance pages.')

    def test_private_evidence_never_becomes_a_cross_scope_parent(self):
        first = self.admitted(self.produce([self.proposal()]))
        other = 'workspace:'+str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)',(other[10:],))
        self.store.ensure_scope(other)
        # Exact-scoped lookup cannot resolve a private parent's key elsewhere.
        with self.connect() as db, db.cursor() as cur:
            self.assertIsNone(self.engine._event(cur,other,'frontier-request:'+first['request_id']))
        result = self.produce([self.proposal(parent_id='a'*64)])
        self.assertIn('frontier_parent_unavailable',[d['reason'] for d in result['decisions']])

    def test_configuration_change_creates_new_coverage_epoch(self):
        old = self.job(self.admitted(self.produce([self.proposal()]))['job_id'])
        self.install(configuration(ranking_version='ranking-v2'))
        new = self.job(self.admitted(self.produce([self.proposal()]))['job_id'])
        self.assertNotEqual(old['payload']['coverage_epoch'],new['payload']['coverage_epoch'])
        self.assertNotEqual(old['payload']['frontier']['partition_key'],new['payload']['frontier']['partition_key'])

    def test_health_backoff_flags_and_restore_guard_stop_tick(self):
        self.flags['RAFII_TREND_RADAR_ENABLED']=False
        self.assertEqual(self.engine.tick()['status'],'disabled')
        self.flags['RAFII_TREND_RADAR_ENABLED']=True
        with self.connect() as db: db.execute('UPDATE pr_trend_runtime_guard SET reads_ready=false WHERE singleton')
        try:
            self.assertEqual(self.engine.tick()['blocked'],1)
            self.assertEqual(self.engine.maintenance()['status'],'restore_deferred')
        finally:
            with self.connect() as db: db.execute('UPDATE pr_trend_runtime_guard SET reads_ready=true WHERE singleton')

    def test_actual_source_tombstone_blocks_current_reads_and_cancel_is_paged(self):
        d = self.admitted(self.produce([self.proposal()]))
        identity = self.fetch('SELECT source_identity FROM pr_trend_observations WHERE scope_key=%s AND observation_id=%s',(self.scope,self.sources[0]))[0]
        revocation.revoke_source(self.store,self.scope,self.provider,identity)
        with self.assertRaises(C.ContractError): self.engine.dispatch_context(self.job(d['job_id']))
        self.assertEqual(sum(c['examined'] for c in self.engine.report(self.scope,self.provider,self.version)['counts']),1)
        after = None
        for _ in range(300):
            receipt = self.engine.maintenance(limit=1,after=after)
            after = receipt['next_key']
            if self.job(d['job_id'])['state']=='cancelled': break
        self.assertEqual(self.job(d['job_id'])['payload'],{})

    def test_actual_author_tombstone_blocks_frozen_genome_producer(self):
        self.details(kind='genome')
        revocation.revoke_author(self.store,self.provider,'author-0')
        result = self.engine.tick()['results'][0]
        self.assertEqual([self.job(j)['payload']['frontier']['route'] for j in result['jobs']],['keyword_independent_sample'])

    def test_missing_diversity_and_unknown_storage_rights_abstain(self):
        result = self.produce([self.proposal(evidence_ids=[self.sources[0]])])
        self.assertIn('frontier_diversity_insufficient',[d['reason'] for d in result['decisions']])
        with self.connect() as db:
            db.execute("UPDATE pr_trend_source_policies SET rights=jsonb_set(rights,'{retain_derivatives,state}','\"unknown\"') WHERE scope_key=%s AND provider_id=%s",(self.scope,self.provider))
        with self.assertRaises(C.ContractError): self.produce([self.proposal()])

    def test_precommit_after_settlement_preserves_complete_batch_generation_fence(self):
        d = self.admitted(self.produce([self.proposal()]))
        claim = self.jobs.claim('frontier-test',job_id=d['job_id'],scope_key=self.scope,budget_keys=self.keys,amount_micro_usd=25)
        running = self.jobs.start(claim)
        self.jobs.settle(self.scope,running['reservation_id'],actual_micro_usd=20,usage_event_id='synthetic-usage')
        context = self.engine.dispatch_context(running)
        receipt = self.jobs.complete_batch(running,partition_key=context['partition_key'],expected_generation=context['checkpoint']['generation'],
            batch_key=C.digest(d['job_id']),observations=[],cursor_value={'position':1},terminal_page=False,
            coverage_state='partial',outbox_events=[],actual_micro_usd=20,usage_event_id='synthetic-usage')
        self.assertEqual(receipt['generation'],1)
        self.assertEqual(self.job(d['job_id'])['payload'],{})
        with self.assertRaises(C.ContractError): self.engine.dispatch_context(running)

    def test_failed_jobs_remain_in_evaluation_denominator_with_reason(self):
        d = self.admitted(self.produce([self.proposal()]))
        with self.connect() as db:
            db.execute("UPDATE pr_trend_jobs SET state='failed_terminal',payload='{}',error_code='synthetic_failed' WHERE scope_key=%s AND job_id=%s",(self.scope,d['job_id']))
        report = self.engine.report(self.scope,self.provider,self.version)
        counts = next(c for c in report['counts'] if c['route']=='related_topic')
        self.assertEqual((counts['examined'],counts['admitted'],counts['failed'],counts['failure_reason:synthetic_failed']),(1,1,1,1))

    def test_backoff_is_not_permission_to_requeue_or_skip_current_health(self):
        self.produce([self.proposal()])
        with self.connect() as db:
            db.execute("INSERT INTO pr_trend_source_health(scope_key,provider_id,status,observed_at,next_allowed_at,notes_code) VALUES(%s,%s,'unavailable',%s,%s,'synthetic_backoff')",(self.scope,self.provider,self.at,self.end))
        with self.assertRaisesRegex(C.ContractError,'source_paused'): self.produce([self.proposal('next')])

    def test_query_text_cannot_outlive_source_ttl(self):
        d = self.admitted(self.produce([self.proposal()]))
        with self.connect() as db:
            db.execute("UPDATE pr_trend_nodes SET available_at=clock_timestamp()-interval '2 hours',retention_until=clock_timestamp()-interval '1 second' WHERE scope_key=%s AND node_id=%s",(self.scope,self.sources[0]))
        with self.assertRaises(C.ContractError): self.engine.dispatch_context(self.job(d['job_id']))
        after = None
        for _ in range(10):
            receipt = self.engine.maintenance(limit=100,after=after); after=receipt['next_key']
            if self.job(d['job_id'])['state']=='cancelled': break
        self.assertEqual(self.job(d['job_id'])['payload'],{})

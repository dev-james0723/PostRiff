"""Local pipeline acceptance; PostgreSQL cases require an explicit private test DB.

TREND_PIPELINE_TEST_DSN must name trend_pipeline_* on /private/tmp:56447.
POSTRIFF_TEST_DSN must match the selected loopback runner (default55438/postgres).
Never reads application credentials or touches a hosted database.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from test_trend_metrics import fixture, OfflineCase
from postriff_phase2.growth.trends import contracts
from postriff_phase2.growth.trends.pipeline import (TrendPipeline, uuid_map, encode_manifest, decode_manifest,
                                                   implementation_methods, representative_evidence, _CandidateIndex, _coverage)
from postriff_phase2.growth.trends.store import TrendStore, row, rows
from postriff_phase2.growth.trends.outbox import TrendOutbox


def dedicated_test_dsn(environ=None):
    """Fail before connecting unless the explicit target is a disposable local DB."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from local_pg_target import selected_target
    env=os.environ if environ is None else environ
    target=selected_target(env, validate_fixture_dsns=False)
    if any(env.get(name) for name in ('PGSERVICE','PGHOSTADDR')):
        raise ValueError('libpq service/address environment overrides are forbidden')
    dedicated=env.get('TREND_PIPELINE_TEST_DSN')
    runner=env.get('POSTRIFF_TEST_DSN')
    raw=dedicated or runner
    if not raw: raise ValueError('explicit disposable pipeline test DSN required')
    params=conninfo_to_dict(raw)
    # Forbid service/hostaddr/multi-host overrides and inherited application options.
    if set(params)-{'host','port','dbname','user'}:
        raise ValueError('only explicit host/port/dbname/user test DSN fields permitted')
    if dedicated:
        valid=(params.get('host')=='/private/tmp' and params.get('port')=='56447'
               and params.get('dbname','').startswith('trend_pipeline_'))
    else:
        valid=(params.get('host')=='127.0.0.1' and params.get('port')==str(target.port)
               and params.get('dbname')=='postgres')
    if not valid: raise ValueError('dedicated local pipeline database or exact disposable runner required')
    return make_conninfo(**params,connect_timeout='5')


class PipelineHelpers(OfflineCase):
    def test_disposable_dsn_rejects_app_remote_and_address_overrides(self):
        try: import psycopg
        except ImportError: self.skipTest('psycopg needed for libpq DSN guard')
        local='host=/private/tmp port=56447 dbname=trend_pipeline_test'
        runner='host=127.0.0.1 port=55438 dbname=postgres'
        self.assertIn('trend_pipeline_test',dedicated_test_dsn({'TREND_PIPELINE_TEST_DSN':local}))
        self.assertIn('55438',dedicated_test_dsn({'POSTRIFF_TEST_DSN':runner}))
        for env in ({'POSTRIFF_DATABASE_URL':runner}, {'POSTRIFF_TEST_DSN':runner.replace('55438','5432')},
                    {'POSTRIFF_TEST_DSN':runner.replace('postgres','production')},
                    {'POSTRIFF_TEST_DSN':runner.replace('127.0.0.1','db.example.com')},
                    {'TREND_PIPELINE_TEST_DSN':local+' hostaddr=198.51.100.1'},
                    {'TREND_PIPELINE_TEST_DSN':local.replace('trend_pipeline_test','postgres')},
                    {'POSTRIFF_TEST_DSN':runner,'PGSERVICE':'app'},
                    {'POSTRIFF_TEST_DSN':runner,'PGHOSTADDR':'198.51.100.1'}):
            with self.subTest(env=env),self.assertRaises(ValueError):dedicated_test_dsn(env)

    def test_uuid_namespaces_and_immutable_executable_artifacts(self):
        first=uuid_map('shared:one','receipt','receipt_x')
        self.assertEqual(first,str(uuid.UUID(first)))
        self.assertEqual(first,uuid_map('shared:one','receipt','receipt_x'))
        self.assertNotEqual(first,uuid_map('shared:two','receipt','receipt_x'))
        self.assertNotEqual(first,uuid_map('shared:one','episode','receipt_x'))
        a=implementation_methods();self.assertEqual(a,implementation_methods())
        self.assertEqual([m['name'] for m in a],sorted(m['name'] for m in a))
        self.assertEqual(len(a),7);self.assertTrue(all(m['qualification']=='unqualified' for m in a))

    def test_full_manifest_chunks_round_trip_and_tampering(self):
        manifest={'source_revisions':[{'original':'廣東話😀'*10000}], 'recipe':{'cutoff':'frozen'}}
        manifest['manifest_digest']=contracts.digest(manifest)
        recipe,chunks=encode_manifest(manifest)
        inputs=[{'scope_key':'shared:fixture','node_id':str(uuid.uuid4())}]
        saved={'inputs':inputs,'recipe':recipe,'chunks':[{'ordinal':i,'payload':c,'digest':contracts.digest(c)} for i,c in enumerate(chunks)],
               'document_digest':manifest['manifest_digest'],'digest':contracts.digest({'inputs':inputs,'recipe':recipe,'chunks':[contracts.digest(c) for c in chunks]})}
        self.assertEqual(decode_manifest(saved),manifest)
        self.assertTrue(all(len(contracts.canonical(c).encode())<=48000 for c in chunks))
        saved['chunks'][0]['payload']['json']='tampered'
        with self.assertRaisesRegex(ValueError,'chunk_mismatch'):decode_manifest(saved)

    def test_candidate_retrieval_is_bounded_and_time_cohort_scoped(self):
        f=fixture();records=f['observations'];index=_CandidateIndex(7)
        for record in records:index.add(record)
        candidates=index.get(records[200])
        self.assertLessEqual(len(candidates),7)
        self.assertTrue(all(abs((contracts.instant(r['event_at'])-contracts.instant(records[200]['event_at'])).total_seconds())<=48*3600 for r in candidates))

    def test_batch_completion_cannot_certify_unobserved_hour(self):
        f=fixture();event={'scope_key':'shared:fixture','payload':{'decision_cutoff':f['decision_cutoff'],'completeness':'complete'}}
        spec=f['window_specs'][0]
        self.assertEqual(_coverage(event,f['scope'],spec['start'],spec['end'])['completeness'],'partial')
        event['payload']['coverage_interval']={'start':spec['start'],'end':spec['end']}
        self.assertEqual(_coverage(event,f['scope'],spec['start'],spec['end'])['completeness'],'complete_within_scope')


@unittest.skipUnless(os.environ.get('TREND_PIPELINE_TEST_DSN') or os.environ.get('POSTRIFF_TEST_DSN'),'dedicated local PostgreSQL DSN required')
class DurablePipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.psycopg=psycopg;cls.dsn=dedicated_test_dsn()
        cls.now=datetime.now(timezone.utc)
        cls.cutoff=contracts.iso(cls.now.replace(minute=0,second=0,microsecond=0))
        cls.at=contracts.iso(cls.now)
        cls.end=contracts.iso(cls.now+timedelta(days=2));cls.start=contracts.iso(cls.now-timedelta(days=35))
        cls.actor=str(uuid.uuid4());cls.workspace=str(uuid.uuid4());cls.scope='shared:pipeline-'+uuid.uuid4().hex[:10]
        cls.provider='pipeline-fixture-'+uuid.uuid4().hex[:8]
        with psycopg.connect(cls.dsn) as db:
            for table in ('pr_profiles','pr_workspaces','pr_memberships'):
                db.execute('DROP POLICY IF EXISTS trend_pipeline_service_test ON '+table)
                db.execute('CREATE POLICY trend_pipeline_service_test ON '+table+' FOR ALL TO service_role USING(true) WITH CHECK(true)')
            db.execute('INSERT INTO auth.users(id) VALUES(%s)',(cls.actor,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(cls.actor,))
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)',(cls.workspace,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(cls.workspace,cls.actor))
        def connect():
            db=psycopg.connect(cls.dsn);db.execute('SET ROLE service_role');return db
        cls.store=TrendStore(connect,offline_replay=True);cls.outbox=TrendOutbox(cls.store)
        cls.store.ensure_scope(cls.scope)
        cls.store.grant_entitlement(cls.workspace,cls.scope,['retrieve','derive_metrics','share_across_workspaces'],cls.end)
        cls.rights={name:{'state':'allow','policy_ref':'pipeline-policy-v1','audience_scope':cls.scope,'expires_at':cls.end} for name in contracts.PERMISSIONS}
        cls.policy={'id':'pipeline-policy','version':'policy-v1','provider_id':cls.provider,'operation':'read','scope_key':cls.scope,
            'rights':cls.rights,'reviewed_by':'synthetic-test','review_ref':'synthetic-only','effective_at':cls.start,'expires_at':cls.end,
            'retention_seconds':40*86400,'readiness':'ready','revoked_at':None}
        cls.store.register_contract(cls.provider,'fixture-v1',list(contracts.PERMISSIONS),cls.start,cls.end,{})
        cls.store.register_policy(cls.policy,provider_contract_version='fixture-v1')
        cls.data=fixture();delta=contracts.instant(cls.cutoff)-contracts.instant(cls.data['decision_cutoff'])
        cls.observations=[]
        # A compact real corpus: 60/90/150 current-hour originals; cohort history
        # deliberately absent to prove the pipeline does not fabricate a baseline.
        for source in cls.data['observations'][:300]:
            o=deepcopy(source);o.update(scope_key=cls.scope,provider_id=cls.provider,rights=deepcopy(cls.rights),retention_until=cls.end)
            o['observation_id']=str(uuid.uuid4());o['deletion_key']=o['observation_id']
            for name in ('event_at','received_at','available_at'):o[name]=contracts.iso(contracts.instant(o[name])+delta)
            cls.observations.append(o)
        with cls.store.transaction() as cur:
            for o in cls.observations:cls.store.put_observation(o,cursor=cur)
        cls.pipeline=TrendPipeline(cls.store,clock=lambda:cls.at,max_new_memberships=300)
        cls.event=cls.outbox.enqueue(cls.scope,'synthetic-pipeline-main','trend.ingested',{
            'provider_id':cls.provider,'decision_cutoff':cls.cutoff,'observation_ids':[o['observation_id'] for o in cls.observations],
            'coverage_epoch':'epoch-v1','completeness':'complete_within_scope',
            'coverage_interval':{'start':cls.observations[0]['event_at'][:13]+':00:00Z','end':cls.cutoff},'markers':[]})

    def test_a_atomic_ingest_to_receipt_projection_retry_and_future_cutoff(self):
        with self.store.transaction() as cur:
            claim=self.outbox.claim('pipeline-test','offline-test',lease_seconds=300,cursor=cur)
        original=self.pipeline.consume
        def crash(cur,event):
            original(cur,event)
            raise RuntimeError('synthetic crash after local writes before commit')
        with self.assertRaisesRegex(RuntimeError,'synthetic crash'):self.outbox.consume(claim,crash)
        with self.store.transaction() as cur:
            cur.execute('SELECT count(*) AS count FROM pr_trend_trust_receipts WHERE scope_key=%s',(self.scope,))
            self.assertEqual(row(cur)['count'],0)
        result=self.outbox.consume(claim,original)
        self.assertEqual(result['state'],'done');self.assertTrue(self.outbox.consume(claim,original)['replayed'])
        with self.store.transaction() as cur:
            cur.execute("SELECT * FROM pr_trend_trust_receipts WHERE scope_key=%s ORDER BY receipt_id",(self.scope,))
            saved=rows(cur);self.assertEqual(len(saved),1)
            receipt=saved[0];self.assertEqual(receipt['verification_state'],'verified')
            self.__class__.receipt_id=receipt['receipt_id'];self.__class__.manifest_id=receipt['manifest_id']
            self.__class__.trend_id=receipt['payload']['trend_id'];self.__class__.sealed=deepcopy(receipt['payload'])
            pure=receipt['payload']['pure_receipt']
            self.assertEqual(pure['observed']['qualifying_original_count'],150)
            self.assertEqual(pure['calculated']['velocity']['value'],60);self.assertEqual(pure['calculated']['acceleration']['value'],30)
            self.assertIsNone(pure['calculated']['growth_pct']['value']);self.assertIsNone(pure['inferred']['stage'])
            manifest=decode_manifest(self.store.get_manifest(self.scope,receipt['manifest_id'],cursor=cur))
            self.assertEqual(len(manifest['source_revisions']),300);self.assertEqual(len(manifest['membership_revisions']),300)
            cur.execute("SELECT count(*) AS count FROM pr_trend_projections WHERE scope_key=%s AND kind='membership'",(self.scope,))
            self.assertEqual(row(cur)['count'],300)
            cur.execute("SELECT count(*) AS count FROM pr_trend_projections WHERE scope_key=%s AND kind='metric_snapshot'",(self.scope,))
            self.assertEqual(row(cur)['count'],7)
        projected=self.store.get_projection(self.workspace,self.actor,'trend',self.trend_id)
        self.assertEqual(projected['verification_state'],'verified');self.assertEqual(projected['payload']['calculated']['velocity']['value'],60)
        # Future correction exists durably but cannot change an already sealed receipt.
        future=deepcopy(self.observations[0]);future.update(observation_id=str(uuid.uuid4()),revision_sequence=99,revision_identity='future-r99',
            available_at=contracts.iso(self.now+timedelta(hours=1)))
        future['payload']['text']='future final label';future['payload_digest']=contracts.digest(future['payload'])
        self.store.put_observation(future)
        with self.store.transaction() as cur:
            self.assertEqual(self.pipeline._verify(cur,self.scope,self.receipt_id)['state'],'verified')
            cur.execute('SELECT payload FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(self.scope,self.receipt_id))
            self.assertEqual(row(cur)['payload'],self.sealed)

    def test_b_pending_worker_catches_wire_tampering_and_rechecks_rights(self):
        if not hasattr(self,'receipt_id'):self.skipTest('previous durable acceptance failed')
        from psycopg.types.json import Jsonb
        bad=deepcopy(self.sealed);bad['calculated']['velocity']['value']=999
        with self.store.transaction() as cur:
            cur.execute("UPDATE pr_trend_trust_receipts SET payload=%s,verification_state='pending' WHERE scope_key=%s AND receipt_id=%s",(Jsonb(bad),self.scope,self.receipt_id))
        result=self.pipeline.verify_pending()
        self.assertEqual(result['results'][0]['state'],'mismatch')
        with self.store.transaction() as cur:
            cur.execute("UPDATE pr_trend_trust_receipts SET payload=%s,verification_state='pending' WHERE scope_key=%s AND receipt_id=%s",(Jsonb(self.sealed),self.scope,self.receipt_id))
        self.assertEqual(self.pipeline.verify_pending()['verified'],1)
        # A deployment with a different executable cannot silently run B for A.
        from postriff_phase2.growth.trends import methods
        deployed=[methods.make_method(m['name'],'unsupported-new-version',implementation_digest='f'*64,
                  config=m['config'],algorithm_id=m['algorithm_id']) for m in implementation_methods()]
        with self.store.transaction() as cur,patch('postriff_phase2.growth.trends.pipeline.implementation_methods',return_value=deployed):
            state=self.pipeline._verify(cur,self.scope,self.receipt_id)
            self.assertEqual(state['state'],'method_unavailable')
            self.assertEqual(state['reason'],'recorded_implementation_not_supported')
            cur.execute('SELECT verification_record FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(self.scope,self.receipt_id))
            self.assertEqual(row(cur)['verification_record']['reason'],'recorded_implementation_not_supported')
        with self.store.transaction() as cur:self.assertEqual(self.pipeline._verify(cur,self.scope,self.receipt_id)['state'],'verified')

    def test_c_current_delete_blocks_projection_and_purges_complete_recipe(self):
        if not hasattr(self,'receipt_id'):self.skipTest('previous durable acceptance failed')
        from postriff_phase2.growth.trends import revocation,retention
        revocation.revoke_source(self.store,self.scope,self.provider,self.observations[0]['source_identity'],deletion_sequence=100,purge_deadline=self.end)
        result=self.store.get_projection(self.workspace,self.actor,'trend',self.trend_id)
        self.assertEqual(result['verification_state'],'inputs_deleted');self.assertIsNone(result['payload'])
        for _ in range(8):
            if not retention.sweep(self.store,limit=1000)['purged_nodes']:break
        with self.store.transaction() as cur:
            cur.execute('SELECT recipe,document_digest FROM pr_trend_input_manifests WHERE scope_key=%s AND manifest_id=%s',(self.scope,self.manifest_id))
            self.assertEqual(row(cur),{'recipe':{},'document_digest':None})
            cur.execute("SELECT count(*) AS count FROM pr_trend_manifest_chunks WHERE scope_key=%s AND manifest_id=%s AND payload<>'{}'::jsonb",(self.scope,self.manifest_id))
            self.assertEqual(row(cur)['count'],0)

    def test_d_default_bound_continues_with_database_knowledge_timestamps(self):
        live=TrendStore(self.store.connection_factory)
        scope='shared:pipeline-bounded-'+uuid.uuid4().hex[:10]
        live.ensure_scope(scope)
        live.grant_entitlement(self.workspace,scope,['retrieve','derive_metrics','share_across_workspaces'],self.end)
        rights=deepcopy(self.rights)
        for grant in rights.values():grant['audience_scope']=scope
        policy={**self.policy,'scope_key':scope,'rights':rights}
        live.register_policy(policy,provider_contract_version='fixture-v1')
        sources=[]
        # Default100 limit must split101 actual current-window originals into two transactions.
        with live.transaction() as cur:
            for original in self.observations[-101:]:
                source=deepcopy(original)
                source.update(scope_key=scope,observation_id=str(uuid.uuid4()),rights=deepcopy(rights))
                source['deletion_key']=source['observation_id']
                sources.append(source);live.put_observation(source,cursor=cur)
            cur.execute('SELECT clock_timestamp() AS cutoff');cutoff=row(cur)['cutoff']
            event=TrendOutbox(live).enqueue(scope,'bounded-default','trend.ingested',{
                **self.event['payload'],'decision_cutoff':cutoff,'observation_ids':[o['observation_id'] for o in sources]},cursor=cur)
        pipeline=TrendPipeline(live);outbox=TrendOutbox(live)
        seen=[]
        def consume(cur,event):
            result=pipeline.consume(cur,event);seen.append(result)
        first=outbox.claim('pipeline-test','bounded-worker',lease_seconds=300)
        self.assertEqual(first['event_id'],event['event_id'])
        outbox.consume(first,consume)
        self.assertEqual(seen[-1]['deferred_count'],1)
        with live.transaction() as cur:
            cur.execute('SELECT * FROM pr_trend_trust_receipts WHERE scope_key=%s',(scope,))
            receipt=row(cur);self.assertEqual(receipt['verification_state'],'verified')
            self.assertEqual(receipt['payload']['coverage']['completeness'],'truncated')
            self.assertIsNone(receipt['payload']['calculated']['velocity']['value'])
        continuation=outbox.claim('pipeline-test','bounded-worker',lease_seconds=300)
        self.assertTrue(continuation['event_key'].startswith('pipeline-continuation:'))
        outbox.consume(continuation,consume)
        self.assertEqual(seen[-1]['deferred_count'],0)
        with live.transaction() as cur:
            cur.execute("SELECT * FROM pr_trend_trust_receipts WHERE scope_key=%s ORDER BY decision_cutoff DESC LIMIT 1",(scope,))
            saved=row(cur);pure=saved['payload']['pure_receipt']
            self.assertEqual(saved['verification_state'],'verified')
            self.assertEqual(pure['observed']['qualifying_original_count'],101)
            self.assertEqual(pure['coverage']['completeness'],'complete_within_scope')
            self.assertEqual(pure['correction_reason'],'continued_membership')
            self.assertEqual(pure['replay_mode'],'correction')
            cur.execute("SELECT min(available_at) AS first,max(available_at) AS last,count(*) AS count FROM pr_trend_projections WHERE scope_key=%s AND kind='membership'",(scope,))
            times=row(cur)
            self.assertEqual(times['count'],101)
            self.assertLess(contracts.instant(cutoff),contracts.instant(times['first']))
            self.assertLessEqual(contracts.instant(times['last']),contracts.instant(pure['decision_cutoff']))
            stored=decode_manifest(live.get_manifest(scope,saved['manifest_id'],cursor=cur))
            self.assertTrue(all(contracts.instant(o['available_at'])<=contracts.instant(cutoff) for o in stored['source_revisions']))
            self.assertTrue(all(o['scope_key']==scope for o in stored['source_revisions']))
            self.assertTrue(all(e['scope_key']==scope for e in stored['membership_revisions']))
        # Different delivery, identical sealed decision: no duplicate manifest/receipt.
        duplicate=outbox.enqueue(scope,'bounded-duplicate','trend.ingested',continuation['payload'])
        frozen=TrendPipeline(live,clock=lambda:pure['decision_cutoff'])
        claim=outbox.claim('pipeline-test','bounded-worker',lease_seconds=300)
        self.assertEqual(claim['event_id'],duplicate['event_id'])
        outbox.consume(claim,frozen.consume)
        with live.transaction() as cur:
            cur.execute('SELECT count(*) AS count FROM pr_trend_trust_receipts WHERE scope_key=%s',(scope,))
            self.assertEqual(row(cur)['count'],2)
        # Revocation after the historical cutoff overrides a pending verifier run.
        with live.transaction() as cur:
            cur.execute("UPDATE pr_trend_source_policies SET revoked_at=clock_timestamp() WHERE scope_key=%s",(scope,))
            cur.execute("UPDATE pr_trend_trust_receipts SET verification_state='pending' WHERE scope_key=%s",(scope,))
        states=pipeline.verify_pending()['results']
        self.assertEqual({r['state'] for r in states if r['scope_key']==scope},{'policy_revoked'})
        projected=live.get_projection(self.workspace,self.actor,'trend',saved['payload']['trend_id'])
        self.assertIsNone(projected['payload'])

    def test_e_original_evidence_corrections_and_separate_platform_associations(self):
        from postriff_phase2.growth.trends.service import TrendService
        from postriff_phase2.growth.trends import revocation
        from psycopg.types.json import Jsonb
        live=TrendStore(self.store.connection_factory);pipeline=TrendPipeline(live);outbox=TrendOutbox(live)
        scope='shared:pipeline-evidence-'+uuid.uuid4().hex[:8]
        live.ensure_scope(scope);live.grant_entitlement(self.workspace,scope,['retrieve','derive_metrics','share_across_workspaces'],self.end)
        rights=deepcopy(self.rights)
        for grant in rights.values():grant['audience_scope']=scope
        providers=[self.provider,'pipeline-other-'+uuid.uuid4().hex[:8]]
        live.register_contract(providers[1],'fixture-v1',list(contracts.PERMISSIONS),self.start,self.end,{})
        for provider in providers:live.register_policy({**self.policy,'provider_id':provider,'scope_key':scope,'rights':rights},provider_contract_version='fixture-v1')
        originals=[];result={}
        def process(sources,key,provider):
            with live.transaction() as cur:
                for source in sources:live.put_observation(source,cursor=cur)
                cur.execute('SELECT clock_timestamp() AS cutoff');cutoff=row(cur)['cutoff']
                event=outbox.enqueue(scope,key,'trend.ingested',{**self.event['payload'],'provider_id':provider,
                    'observation_ids':[o['observation_id'] for o in sources],'decision_cutoff':cutoff},cursor=cur)
            claim=outbox.claim('pipeline-test','evidence-worker',lease_seconds=300)
            self.assertEqual(claim['event_id'],event['event_id'])
            def effect(cur,event):result.update(pipeline.consume(cur,event))
            outbox.consume(claim,effect)
            return result['receipts'][0]
        for pi,provider in enumerate(providers):
            sources=[]
            for i,original in enumerate(self.observations[-6:]):
                source=deepcopy(original);source.update(scope_key=scope,provider_id=provider,observation_id=str(uuid.uuid4()),rights=deepcopy(rights))
                source['deletion_key']=source['observation_id']
                source['payload'].update(text='喺香港學習鋼琴分享音樂真係好開心！😀',language='yue',platform='bluesky' if pi==0 else 'mastodon',
                    author_key='provider-author-'+str(i),canonical_url='https://fixture.invalid/original/'+str(i),event_type='music')
                source['payload_digest']=contracts.digest(source['payload']);sources.append(source)
            saved=process(sources,'original-'+str(pi),provider)
            if pi==0:originals=sources;first=deepcopy(saved)
        with live.transaction() as cur:
            cur.execute("SELECT payload FROM pr_trend_projections WHERE scope_key=%s AND kind='topic_association'",(scope,))
            associations=rows(cur);self.assertEqual(len(associations),1)
            edge=associations[0]['payload']
            self.assertEqual(edge['semantic_qualification'],'unqualified');self.assertEqual(edge['mode'],'lexical_only')
            self.assertEqual(edge['platforms'],['bluesky','mastodon']);self.assertEqual(len(set(edge['episode_ids'])),2)
            cur.execute('SELECT payload FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope,first['receipt_id']))
            original_payload=row(cur)['payload'];old_digest=contracts.digest(original_payload)
        service=object.__new__(TrendService);service.values={'RAFII_TREND_INTELLIGENCE':'1','RAFII_TREND_TRUST_RECEIPTS':'1'}
        def wire():
            with live.transaction() as cur:
                trend=live.get_projection(self.workspace,self.actor,'trend',first['trend_id'],cursor=cur)
                return service._trend(live,cur,self.workspace,self.actor,trend,datetime.now(timezone.utc).timestamp())
        rendered=wire()
        self.assertEqual(len(rendered['evidence']),5)
        self.assertTrue(all(e['excerpt']=='喺香港學習鋼琴分享音樂真係好開心！😀' for e in rendered['evidence']))
        self.assertTrue(all(e['url'].startswith('https://fixture.invalid/') for e in rendered['evidence']))
        self.assertEqual([p['platform'] for p in rendered['platform_states']],['bluesky'])
        self.assertIsNone(rendered['inferred']['stage'])
        corrected=deepcopy(originals[0]);corrected.update(observation_id=str(uuid.uuid4()),revision_identity='late-r2',revision_sequence=2,operation='update')
        corrected['payload']['text']+=' 修正版';corrected['payload_digest']=contracts.digest(corrected['payload'])
        updated=process([corrected],'late-edit',providers[0])
        self.assertEqual(updated['episode_id'],first['episode_id'])
        with live.transaction() as cur:
            cur.execute('SELECT payload FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope,updated['receipt_id']))
            replacement=row(cur)['payload'];new=replacement['pure_receipt']
            self.assertEqual(replacement['supersedes_id'],first['receipt_id'])
            self.assertEqual(new['correction_reason'],'late_revision');self.assertEqual(new['replay_mode'],'correction')
            self.assertEqual(new['original_decision_cutoff'],original_payload['pure_receipt']['decision_cutoff'])
            cur.execute('SELECT payload FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope,first['receipt_id']))
            self.assertEqual(contracts.digest(row(cur)['payload']),old_digest)
        denied=deepcopy(rights);denied['display_excerpt']['state']='deny'
        with live.transaction() as cur:cur.execute('UPDATE pr_trend_source_policies SET rights=%s WHERE scope_key=%s AND provider_id=%s',(Jsonb(denied),scope,providers[0]))
        rendered=wire();self.assertTrue(all(e.get('excerpt') is None for e in rendered['evidence']))
        with live.transaction() as cur:cur.execute('UPDATE pr_trend_source_policies SET rights=%s WHERE scope_key=%s AND provider_id=%s',(Jsonb(rights),scope,providers[0]))
        revocation.revoke_source(live,scope,providers[0],originals[0]['source_identity'],deletion_sequence=100,purge_deadline=self.end)
        self.assertIsNone(live.get_projection(self.workspace,self.actor,'trend',first['trend_id'])['payload'])
        # A new permitted-data decision may replace it; prior receipt is never mutated.
        with live.transaction() as cur:
            cur.execute('SELECT clock_timestamp() AS cutoff');cutoff=row(cur)['cutoff']
            event=outbox.enqueue(scope,'deleted-source','trend.ingested',{**self.event['payload'],'provider_id':providers[0],
                'observation_ids':[corrected['observation_id']],'decision_cutoff':cutoff},cursor=cur)
        claim=outbox.claim('pipeline-test','evidence-worker',lease_seconds=300)
        def deletion(cur,event):result.update(pipeline.consume(cur,event))
        outbox.consume(claim,deletion)
        self.assertEqual(len(result['receipts']),1)
        with live.transaction() as cur:
            cur.execute('SELECT payload FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope,result['receipts'][0]['receipt_id']))
            replacement=row(cur)['payload']
            self.assertEqual(replacement['pure_receipt']['correction_reason'],'source_deletion')
            self.assertEqual(replacement['pure_receipt']['observed']['qualifying_original_count'],5)
            self.assertNotIn(corrected['observation_id'],[e['id'] for e in replacement['evidence']])

    def test_f_candidates_bound_recursive_trust_and_preserve_burst_ids(self):
        # Real SQL against a corpus much larger than the batch. EXPLAIN executes
        # the query and proves trust is evaluated outside the bounded CTE.
        class RecordingCursor:
            def __init__(self, cursor):self.cursor=cursor;self.queries=[]
            def execute(self, query, params):
                self.queries.append((query,params));return self.cursor.execute(query,params)
            def __getattr__(self, name):return getattr(self.cursor,name)
        pipeline=TrendPipeline(self.store,max_observations=7)
        expected={o['observation_id'] for o in self.observations[-7:]}
        event=deepcopy(self.event);event['payload']['observation_ids']=sorted(expected)
        with self.store.transaction() as cur:
            recorded=RecordingCursor(cur)
            sources,truncated=pipeline._sources(recorded,event)
            self.assertTrue(truncated)
            self.assertEqual({o['observation_id'] for o in sources},expected)
            members=pipeline._memberships(recorded,self.scope,self.at,sources)
            self.assertEqual({m['observation_id'] for m in members},expected)
            self.assertEqual(len(recorded.queries),3)
            for query,params in recorded.queries:
                cur.execute('EXPLAIN (ANALYZE, VERBOSE, FORMAT JSON) '+query,params)
                plan=cur.fetchone()[0][0]['Plan']
                def nodes(node):
                    yield node
                    for child in node.get('Plans',[]):yield from nodes(child)
                candidates=[n for n in nodes(plan) if n.get('Subplan Name')=='CTE candidates']
                self.assertEqual(len(candidates),1)
                self.assertLessEqual(candidates[0]['Actual Rows'],8)
                self.assertFalse(any('trend_node_valid' in expression for n in nodes(candidates[0])
                                     for expression in n.get('Output',[])))

    def test_b_membership_only_revocation_invalidates_receipt_and_private_advanced(self):
        if not hasattr(self,'receipt_id'):self.skipTest('previous durable acceptance failed')
        from psycopg.types.json import Jsonb
        private='workspace:'+self.workspace;self.store.ensure_scope(private)
        method_digest=contracts.digest({'synthetic_advanced':'membership_dag'})
        self.store.put_method('fixture.membership-advanced','v1',method_digest,{})
        advanced_id=str(uuid.uuid4())
        with self.store.transaction() as cur:
            cur.execute('SELECT * FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(self.scope,self.receipt_id))
            saved=row(cur);payload=saved['payload']
            manifest=self.store.get_manifest(self.scope,self.manifest_id,cursor=cur)
            full=decode_manifest(manifest)
            expected=sorted(uuid_map(self.scope,'membership',m['event_id']) for m in full['membership_revisions'])
            refs=[{'scope_key':self.scope,'node_id':i} for i in expected]
            self.assertEqual(payload['membership_dependency_digest'],contracts.digest(refs))
            self.assertEqual(payload['membership_dependency_count'],300)
            self.assertEqual(len(manifest['inputs']),2)
            self.assertEqual([a['kind'] for a in manifest['recipe']['dependency_anchors']],['source','membership'])
            m=self.store.put_manifest(private,[{'scope_key':self.scope,'node_id':self.receipt_id}],
                decision_cutoff=self.at,available_at=self.at,retention_until=self.end,cursor=cur)
            self.store.put_projection({'scope_key':private,'kind':'genome','object_id':advanced_id,'revision':1,
                'manifest_id':m['manifest_id'],'method_id':'fixture.membership-advanced','method_version':'v1',
                'decision_cutoff':self.at,'available_at':self.at,'retention_until':self.end,
                'payload':{'trust_receipt_id':self.receipt_id,'execution':'synthetic_local'}},cursor=cur)
            self.assertIsNotNone(self.store.get_projection(self.workspace,self.actor,'genome',advanced_id,cursor=cur)['payload'])
            for mode in ('node','method'):
                cur.execute('SAVEPOINT member_invalidation')
                if mode=='node':
                    cur.execute("UPDATE pr_trend_nodes SET validity='revoked' WHERE scope_key=%s AND node_id=%s",(self.scope,expected[0]))
                else:
                    # A separate membership method withdraws independently of the
                    # still-current receipt's own pipeline method.
                    self.store.put_method('fixture.membership-only','v1',method_digest,{},cursor=cur)
                    cur.execute("UPDATE pr_trend_projections SET method_id='fixture.membership-only',method_version='v1' WHERE scope_key=%s AND projection_id=%s",(self.scope,expected[0]))
                    cur.execute("UPDATE pr_trend_method_versions SET qualification='withdrawn' WHERE method_id='fixture.membership-only' AND version='v1'")
                cur.execute('SELECT bool_and(postriff_private.trend_node_valid(scope_key,observation_id)) AS valid FROM pr_trend_observations WHERE scope_key=%s AND observation_id=ANY(%s::uuid[])',
                    (self.scope,[o['observation_id'] for o in self.observations]))
                self.assertTrue(row(cur)['valid'])
                self.assertIsNone(self.store.get_receipt(self.workspace,self.actor,self.receipt_id,cursor=cur)['payload'])
                self.assertIsNone(self.store.get_projection(self.workspace,self.actor,'trend',self.trend_id,cursor=cur)['payload'])
                self.assertIsNone(self.store.get_projection(self.workspace,self.actor,'genome',advanced_id,cursor=cur)['payload'])
                cur.execute('ROLLBACK TO SAVEPOINT member_invalidation')
            # Legacy/current pipeline seals lacking the marker cannot be verified.
            cur.execute('SAVEPOINT missing_binding')
            bad=deepcopy(payload);bad.pop('membership_dependency_digest');bad.pop('membership_dependency_count')
            cur.execute('UPDATE pr_trend_trust_receipts SET payload=%s WHERE scope_key=%s AND receipt_id=%s',(Jsonb(bad),self.scope,self.receipt_id))
            self.assertEqual(self.pipeline._verify(cur,self.scope,self.receipt_id)['state'],'mismatch')
            cur.execute('ROLLBACK TO SAVEPOINT missing_binding')
            # Corrupted SQL edges cannot be excused by an intact pure recipe.
            cur.execute('SAVEPOINT missing_edge')
            anchor=manifest['recipe']['dependency_anchors'][1]['manifest_id']
            cur.execute('DELETE FROM pr_trend_dependencies WHERE scope_key=%s AND node_id=%s AND input_node_id=%s',(self.scope,anchor,expected[0]))
            self.assertEqual(self.pipeline._verify(cur,self.scope,self.receipt_id)['state'],'mismatch')
            cur.execute('ROLLBACK TO SAVEPOINT missing_edge')
            self.assertEqual(self.pipeline._verify(cur,self.scope,self.receipt_id)['state'],'verified')

    def test_g_700_source_root_context_survives_larger_history_and_seals_1400_dependencies(self):
        live=TrendStore(self.store.connection_factory);outbox=TrendOutbox(live)
        scope='shared:pipeline-root-'+uuid.uuid4().hex[:8]
        live.ensure_scope(scope);live.grant_entitlement(self.workspace,scope,['retrieve','derive_metrics','share_across_workspaces'],self.end)
        rights=deepcopy(self.rights)
        for grant in rights.values():grant['audience_scope']=scope
        live.register_policy({**self.policy,'scope_key':scope,'rights':rights},provider_contract_version='fixture-v1')
        def source(n,prior=False):
            o=deepcopy(self.observations[-1]);native=('history-' if prior else 'burst-')+str(n)
            o.update(scope_key=scope,observation_id=str(uuid.uuid4()),source_identity=native,revision_identity='r1:'+native,
                rights=deepcopy(rights));o['deletion_key']=o['observation_id']
            o['payload'].update(native_id=native,author_key='author-'+str(n%100),text='Synthetic music rhythm discussion')
            o['payload_digest']=contracts.digest(o['payload'])
            return o
        with live.transaction() as cur:
            # Cardinality above the700-source context cap reproduces the same
            # selection failure as the separate100k-row operational benchmark.
            for n in range(701):live.put_observation(source(n,True),cursor=cur)
            burst=[source(n) for n in range(700)]
            for o in burst:live.put_observation(o,cursor=cur)
            cur.execute('SELECT clock_timestamp() AS cutoff');cutoff=row(cur)['cutoff']
            event=outbox.enqueue(scope,'root-700','trend.ingested',{**self.event['payload'],'decision_cutoff':cutoff,
                'observation_ids':[o['observation_id'] for o in burst]},cursor=cur)
        pipeline=TrendPipeline(live,max_observations=700,max_episodes=1)
        outcomes=[];receipts_seen=[]
        for page in range(7):
            claim=outbox.claim('pipeline-root-test','root-worker',lease_seconds=300)
            # This consumer has no prior offsets; select the intended fixture event
            # without consuming any other scope's existing test events.
            while claim and claim['scope_key']!=scope:
                outbox.consume(claim,lambda cur,event:None)
                claim=outbox.claim('pipeline-root-test','root-worker',lease_seconds=300)
            self.assertIsNotNone(claim)
            self.assertEqual(claim['payload']['observation_ids'],event['payload']['observation_ids'])
            self.assertEqual(claim['payload']['decision_cutoff'],cutoff)
            if page:self.assertEqual(len(claim['payload']['pending_observation_indices']),700-page*100)
            result={}
            def consume(cur,ev):result.update(pipeline.consume(cur,ev))
            outbox.consume(claim,consume);outcomes.append(result);receipts_seen+=result['receipts']
            self.assertEqual(result['deferred_count'],600-page*100)
            with live.transaction() as cur:
                cur.execute('SELECT payload FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope,result['receipts'][0]['receipt_id']))
                value=row(cur)['payload']
                self.assertEqual(value['pure_receipt']['observed']['qualifying_original_count'],100*(page+1))
        self.assertEqual(len({r['episode_id'] for r in receipts_seen}),1)
        with live.transaction() as cur:
            cur.execute('SELECT * FROM pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope,receipts_seen[-1]['receipt_id']))
            saved=row(cur);self.assertEqual(saved['verification_state'],'verified')
            self.assertEqual(saved['payload']['membership_dependency_count'],700)
            manifest=live.get_manifest(scope,saved['manifest_id'],cursor=cur);full=decode_manifest(manifest)
            self.assertEqual(len(full['source_revisions']),700);self.assertEqual(len(full['membership_revisions']),700)
            self.assertEqual({o['observation_id'] for o in full['source_revisions']},{o['observation_id'] for o in burst})
            self.assertEqual(len(manifest['inputs']),2)
            anchors=[live.get_manifest(scope,a['manifest_id'],cursor=cur) for a in manifest['recipe']['dependency_anchors']]
            self.assertEqual([len(a['inputs']) for a in anchors],[700,700])
            cur.execute('SELECT max(available_at) AS latest FROM pr_trend_nodes WHERE scope_key=%s AND node_id=ANY(%s::uuid[])',
                (scope,[a['manifest_id'] for a in manifest['recipe']['dependency_anchors']]))
            self.assertLessEqual(contracts.instant(row(cur)['latest']),contracts.instant(saved['decision_cutoff']))
            self.assertTrue(all(contracts.instant(o['available_at'])<=contracts.instant(cutoff) for o in full['source_revisions']))
            self.assertEqual(pipeline._verify(cur,scope,saved['receipt_id'])['state'],'verified')
            cur.execute("SELECT payload,octet_length(payload::text) AS size FROM pr_trend_projections WHERE scope_key=%s AND kind='metric_snapshot'",(scope,))
            projections=rows(cur);self.assertTrue(all(p['size']<=65536 for p in projections))
            latest=full['normalized_inputs']['windows'][-1]
            projected=next(p['payload'] for p in projections if p['payload']['snapshot_id']==latest['snapshot_id'])
            self.assertEqual(projected['source_revision_refs_count'],700)
            self.assertEqual(projected['snapshot_document_digest'],contracts.digest(latest))
            self.assertEqual(len(latest['source_revision_refs']),700)
            self.assertNotIn('source_revision_refs',projected)

    def test_h_storage_grants_gate_sql_payload_before_normalization(self):
        from psycopg.types.json import Jsonb
        pipeline=TrendPipeline(self.store,max_observations=7)
        event=deepcopy(self.event);event['payload']['observation_ids']=[o['observation_id'] for o in self.observations[-7:]]
        class Capture:
            def __init__(self,cur):self.cur=cur;self.fetched=[]
            def execute(self,*args):return self.cur.execute(*args)
            def fetchall(self):
                values=self.cur.fetchall();names=[c.name for c in self.cur.description]
                self.fetched.extend(dict(zip(names,r)) for r in values);return values
            def __getattr__(self,name):return getattr(self.cur,name)
        with self.store.transaction() as cur:
            for owner in ('policy','observation'):
                cur.execute('SAVEPOINT raw_storage_denied')
                if owner=='policy':
                    cur.execute("UPDATE pr_trend_source_policies SET rights=rights-'store_raw' WHERE scope_key=%s",(self.scope,))
                else:
                    cur.execute("UPDATE pr_trend_observations SET rights=rights-'store_raw' WHERE scope_key=%s",(self.scope,))
                # Retrieval still passes the frozen SQL040 predicate, so it is
                # not a substitute for either independent storage grant.
                cur.execute('SELECT postriff_private.trend_node_valid(%s,%s) AS valid',(self.scope,event['payload']['observation_ids'][0]))
                self.assertTrue(row(cur)['valid'])
                captured=Capture(cur);sources,truncated=pipeline._sources(captured,event)
                self.assertEqual(sources,[]);self.assertTrue(truncated)
                self.assertTrue(captured.fetched)
                self.assertTrue(all(r['payload'] is None and r['source_identity'] is None for r in captured.fetched))
                # Metadata-only sources retain their independently granted retrieve
                # permission; no raw text is admitted or reconstructed from them.
                metadata=deepcopy(self.observations[-1]);metadata.update(observation_id=str(uuid.uuid4()),
                    source_identity='metadata-'+owner,revision_identity='metadata-r1')
                metadata['deletion_key']=metadata['observation_id']
                metadata['payload'].pop('text',None)
                metadata['payload_digest']=contracts.digest(metadata['payload'])
                metadata['rights'].pop('store_raw',None)
                self.store.put_observation(metadata,cursor=cur)
                local=deepcopy(event);local['payload']['observation_ids']=[metadata['observation_id']]
                found,_=pipeline._sources(cur,local)
                matched=[o for o in found if o['observation_id']==metadata['observation_id']]
                self.assertEqual(len(matched),1);self.assertNotIn('text',matched[0]['payload'])
                # An independently licensed aggregate still uses store_metrics.
                aggregate=deepcopy(self.observations[-1]);aggregate.update(observation_id=str(uuid.uuid4()),
                    source_identity='aggregate-'+owner,revision_identity='aggregate-r1',kind='aggregate_metric')
                aggregate['deletion_key']=aggregate['observation_id']
                aggregate['payload']={'platform':'bluesky','dataset_id':'synthetic-independent','metric_definition':'count-v1',
                    'unit':'posts','population':'declared_fixture','aggregation_semantics':'sum','value':12,
                    'window_start':self.observations[-1]['event_at'],'window_end':self.cutoff}
                aggregate['payload_digest']=contracts.digest(aggregate['payload'])
                self.store.put_observation(aggregate,cursor=cur)
                local=deepcopy(event);local['payload']['observation_ids']=[aggregate['observation_id']]
                found,_=pipeline._sources(cur,local)
                self.assertIn(aggregate['observation_id'],[o['observation_id'] for o in found])
                cur.execute("UPDATE pr_trend_source_policies SET rights=rights-'store_metrics' WHERE scope_key=%s",(self.scope,))
                found,_=pipeline._sources(cur,local)
                self.assertNotIn(aggregate['observation_id'],[o['observation_id'] for o in found])
                cur.execute('ROLLBACK TO SAVEPOINT raw_storage_denied')

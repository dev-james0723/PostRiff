"""Pure adapter contracts with real forecast arithmetic and an in-memory SQL seam.

These are NOT PostgreSQL acceptance or real-data qualification. The synthetic
registry/provenance rows exercise the trusted-record interface only.
"""
import copy
from datetime import timedelta
import unittest
from unittest.mock import patch
import uuid

from postriff_phase2.growth.trends import contracts, forecast, forecast_admission as A
from postriff_phase2.growth.trends.store import TrendStorageError
import test_trend_forecast as forecast_fixtures


def uid(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'forecast-admission-test:'+label))


def shifted(value, **kwargs):
    return contracts.iso(contracts.instant(value)+timedelta(**kwargs))


def source_bindings(store, record):
    from postriff_phase2.growth.trends.pipeline import decode_manifest
    payload=record['payload']
    if 'source_bindings_ref' in payload:
        return decode_manifest(store.manifests[payload['source_bindings_ref']['manifest_id']])['source_bindings']
    return payload['source_bindings']


def seal_document(store, record, key, *, bindings=None):
    from postriff_phase2.growth.trends.pipeline import encode_manifest
    payload=record['payload'];document={'artifact':payload.pop(key)}
    if bindings is not None:
        document['source_bindings']=copy.deepcopy(bindings);payload.pop('source_bindings',None)
    document['manifest_digest']=contracts.digest(document)
    recipe,chunks=encode_manifest(document);inputs=[{'scope_key':store.scope,'node_id':store.observation['source_id']}]
    mid=uid(key+'-document')
    store.manifests[mid]={'recipe':recipe,'document_digest':document['manifest_digest'],'inputs':inputs,
        'chunks':[{'ordinal':i,'digest':contracts.digest(c),'payload':c} for i,c in enumerate(chunks)],
        'digest':contracts.digest({'inputs':inputs,'recipe':recipe,'chunks':[contracts.digest(c) for c in chunks]})}
    payload[key+'_ref']={'manifest_id':mid,'document_digest':document['manifest_digest']}
    if bindings is not None:payload['source_bindings_ref']=copy.deepcopy(payload[key+'_ref'])
    return document


class MemoryCursor:
    description = []

    def __init__(self, store):
        self.store=store; self.result=[]; self.calls=[]

    def execute(self, sql, args=()):
        self.calls.append((sql,args)); s=self.store; self.result=[]
        if 'forecast_admission:clock' in sql:
            self.result=[{'now':s.clocks.pop(0) if s.clocks else s.now}]
        elif 'forecast_admission:method' in sql:
            self.result=[s.methods[tuple(args)]] if tuple(args) in s.methods else []
        elif 'forecast_admission:ancestors' in sql:
            review=s.records['forecast_qualification']['projection_id']
            self.result=[{'root':review,'scope_key':r['scope_key'],'node_id':r['projection_id']}
                         for r in s.records.values() if r['kind']!='forecast' and r['kind'] not in s.missing_review_edges]
        elif 'forecast_admission:source_ancestry' in sql:
            self.result=[{'root':s.records[k]['projection_id'],'scope_key':b['scope_key'],'node_id':b['node_id']}
                for k in ('forecast_candidate','forecast_evaluation') for b in source_bindings(s,s.records[k])
                if k not in s.missing_source_edges]
        elif 'forecast_admission:receipts' in sql:
            self.result=[{'root':s.records[k]['projection_id'],'receipt_id':uid('receipt'),
                'verification_state':s.receipt_state} for k in ('forecast_candidate','forecast_evaluation')]
        elif 'forecast_admission:observation' in sql:
            self.result=[s.observation] if (args[0],args[1])==(s.observation['scope_key'],s.observation['source_id']) else []
        elif 'forecast_admission:entitlement' in sql:
            self.result=[s.entitlement] if s.entitlement is not None else []
        elif 'forecast_admission:artifact_ancestry' in sql:
            self.result=[{'attached':s.artifact_attached}]
        elif 'pg_advisory' not in sql:
            raise AssertionError('unexpected SQL: '+sql)
        self.result=copy.deepcopy(self.result)

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        found,self.result=self.result,[]
        return found


class MemoryStore:
    offline_replay=False

    def __init__(self, case):
        self.wid=case.wid; self.actor=case.actor; self.reviewer=case.reviewer
        self.scope='workspace:'+self.wid; self.now=shifted(case.p['decision_cutoff'],minutes=5)
        self.clocks=[]; self.members={self.actor,self.reviewer}; self.records={};self.methods={}
        self.reads=[]; self.locks=[]; self.writes=[]; self.missing_review_edges=set();self.missing_source_edges=set()
        self.receipt_state='verified';self.scopes=[self.scope];self.on_lock=None
        self.cur=MemoryCursor(self); self.forecasts={};self.manifests={};self.permissions=[];self.artifact_attached=True
        self.entitlement={'operations':['retrieve','derive_metrics','share_across_workspaces'],
                          'expires_at':'2026-10-30T00:00:00Z','revoked_at':None}
        scope=self.scope
        rights={op:{'state':'allow','policy_ref':'test-review','audience_scope':scope,
                    'expires_at':'2026-10-30T00:00:00Z'} for op in contracts.PERMISSIONS}
        self.observation={'source_id':case.sid,'scope_key':scope,'provider_id':'example',
            'source_policy_version':'v1','provider_contract_version':'c1','rights':rights,
            'provenance':{'access_method':'official_public_stream'},'operation':'create','purged_at':None,
            'event_at':'2026-09-23T00:00:00Z','aggregate_end':None,'available_at':'2026-09-23T00:00:00Z',
            'retention_until':'2026-10-30T00:00:00Z','platform':'bluesky','original':True,'storage_permission':'store_metrics','valid':True}
        self.policy={'rights':copy.deepcopy(rights),'operations':list(rights),'provider_contract_version':'c1',
            'available_at':'2026-09-22T00:00:00Z','contract_available_at':'2026-09-22T00:00:00Z',
            'valid_from':'2026-09-22T00:00:00Z','contract_start':'2026-09-22T00:00:00Z',
            'expires_at':'2026-10-30T00:00:00Z','contract_end':'2026-10-30T00:00:00Z','revoked_at':None,
            'contract_operations':list(rights)}
        p=case.p; report=p['report'];prediction=forecast.predict_candidates(p);gate=p['gate']
        plan={k:gate[k] for k in forecast.PREREGISTERED_FIELDS}
        refs=[{'source_id':case.sid,'scope_key':scope,'node_id':case.sid}]
        payloads={
            'candidate':{'prediction':prediction,'source_bindings':refs},
            'evaluation':{'report':report,'source_bindings':refs},
            'preregistration':{'plan':plan,'preregistration_digest':gate['preregistration_digest']},
            'qualification':{'candidate':{'object_id':uid('candidate'),'revision':1},
                'evaluation':{'object_id':uid('evaluation'),'revision':1},
                'preregistration':{'object_id':uid('preregistration'),'revision':1},
                'prediction_digest':prediction['prediction_digest'],
                **{k:gate[k] for k in ('report_digest','dataset_digest','target_digest','method_digest','evaluation_plan_digest','preregistration_digest')}}}
        for role in A.ROLES:
            kind='forecast_'+role;payload=copy.deepcopy(payloads[role]); payload['schema_version']='trend.forecast.'+role+'.v1'
            available=gate['preregistered_at'] if role=='preregistration' else shifted(p['decision_cutoff'],minutes=3 if role=='qualification' else 1)
            if role in ('qualification','preregistration'):
                payload['provenance']={'reviewer_id':self.reviewer,'authority':'test-review-board','reviewed_at':available,
                                       'decision':'approved','evidence_ref':'synthetic-contract-check'}
            self.records[kind]={'kind':kind,'scope_key':scope,'object_id':uid(role),'projection_id':uid('projection-'+role),
                'revision':1,'available_at':available,'expires_at':'2026-10-30T00:00:00Z',
                'validity':'valid','verification_state':'verified','policy':{'derive_metrics':True,'retain_derivatives':True},
                'payload':payload,'method_bundle':{'method_id':'test.'+role,'version':'v1'},'receipt_id':uid('receipt')}
            control={'state':'production','role':role,'runtime_digest':A.runtime_digest(),
                'review_authority':'test-review-board','reviewer_ids':[self.reviewer],
                'evidence_class':'retained_observed_data','allowed_access_methods':['official_public_stream']}
            self.methods[('test.'+role,'v1')]={'method_id':'test.'+role,'version':'v1','artifact_digest':contracts.digest(role),
                'config':{'forecast_admission':control},'qualification':'qualified','revoked_at':None}
        d=A.method_descriptor()
        self.methods[(d['method_id'],d['method_version'])]={'method_id':d['method_id'],'version':d['method_version'],
            'artifact_digest':d['artifact_digest'],'config':d['config'],'qualification':'qualified','revoked_at':None}

    def _actor(self, cur, wid, actor, write=False):
        assert cur is self.cur
        if wid!=self.wid or actor not in self.members: raise TrendStorageError('workspace_access_denied')
        return wid,actor

    def get_projection(self, wid, actor, kind, oid, *, revision=None, as_of=None, cursor=None):
        self._actor(cursor,wid,actor);self.reads.append((kind,oid,revision,cursor))
        r=self.forecasts.get(oid) if kind=='forecast' else self.records.get(kind)
        return copy.deepcopy(r) if r and r['object_id']==oid and (revision is None or revision==r['revision']) else None

    def lock_dependencies(self, wid, actor, bindings, *, cursor):
        self._actor(cursor,wid,actor,write=True);self.locks.append(copy.deepcopy(bindings))
        if self.on_lock:self.on_lock(self)
        for b in bindings:
            if self.records[b['kind']]['revision']!=b['revision']:raise TrendStorageError('projection_revision_conflict')

    def authorized_scopes(self, wid, actor, *, cursor):
        self._actor(cursor,wid,actor);return self.scopes

    def _policy(self, cur, scope, provider, version, permission='retrieve', at=None):
        assert cur is self.cur
        self.permissions.append(permission)
        p=self.policy
        if p['revoked_at'] or permission not in p['contract_operations'] or not contracts.permits(p['rights'],permission,scope,at):
            raise TrendStorageError('source_policy_denied')
        return copy.deepcopy(p)

    def put_manifest(self, scope, inputs, **kwargs):
        assert kwargs['cursor'] is self.cur
        self.writes.append(('manifest',copy.deepcopy(inputs)));mid=uid('manifest-'+str(len(self.manifests)))
        self.manifests[mid]=copy.deepcopy(inputs);return {'manifest_id':mid}

    def put_projection(self, value, *, expected_revision=None,cursor=None):
        assert cursor is self.cur and expected_revision==0
        self.writes.append(('projection',copy.deepcopy(value)))
        r={**copy.deepcopy(value),'projection_id':uid('output'),'expires_at':value['retention_until'],'validity':'valid',
           'policy':{'derive_metrics':True,'retain_derivatives':True},
           'method_bundle':{'method_id':value['method_id'],'version':value['method_version']}}
        self.forecasts[value['object_id']]=r
        return r['projection_id']

    def get_manifest(self, scope, mid, *, cursor):
        assert cursor is self.cur and scope==self.scope
        return copy.deepcopy(self.manifests[mid])


class Admission(unittest.TestCase):
    def setUp(self):
        helper=forecast_fixtures.Forecast();helper.setUp();self.addCleanup(helper.doCleanups)
        self.wid,self.actor,self.reviewer,self.sid=map(uid,('workspace','actor','reviewer','source'))
        p=helper.series();p['scope_key']='workspace:'+self.wid
        for s in p['sources']:s.update(scope_key=p['scope_key'],source_id=self.sid)
        for r in p['history']:r['evidence_refs']=[self.sid]
        self.p=helper.qualification(p)
        self.store=MemoryStore(self)
        self.values={'RAFII_TREND_'+k+'_ENABLED':'1' for k in ('INTELLIGENCE','TRUST_RECEIPTS','RADAR','FORECASTS')}
        self.values['RAFII_TREND_WORKSPACE_ALLOWLIST']=self.wid
        self.adapter=A.ForecastAdmission(self.store,values=self.values)
        self.args={'candidate':{'object_id':uid('candidate'),'revision':1},'evaluation':{'object_id':uid('evaluation'),'revision':1},
                   'review':{'object_id':uid('qualification'),'revision':1},'cursor':self.store.cur}

    def admit(self):return self.adapter.admit(self.wid,self.actor,**self.args)

    def test_actual_forecast_replay_admitted_only_from_locked_durable_subjects(self):
        r=self.admit()
        self.assertEqual(r['state'],'qualified');self.assertEqual(r['payload']['predictions'][0]['method'],forecast.CANDIDATE)
        self.assertEqual(len(r['dependencies']),5)
        self.assertIn({'scope_key':'workspace:'+self.wid,'node_id':self.sid},r['dependencies'])
        self.assertEqual(len(self.store.locks[0]),4)
        self.assertTrue(all(r[3] is self.store.cur for r in self.store.reads))
        self.assertFalse(self.store.writes)
        self.assertTrue({'retrieve','derive_metrics','retain_derivatives','store_metrics'}<=set(self.store.permissions))

    def test_persist_attaches_every_ref_and_idempotently_returns_same_revision(self):
        first=self.adapter.persist(self.wid,self.actor,**self.args)
        second=self.adapter.persist(self.wid,self.actor,**self.args)
        self.assertEqual(first,second);self.assertEqual([w[0] for w in self.store.writes],['manifest','projection'])
        self.assertEqual(len(self.store.writes[0][1]),5)
        self.assertEqual(first['retention_until'],self.store.records['forecast_candidate']['payload']['prediction']['horizon_end'])

    def test_disabled_or_unauthenticated_never_reads_projection(self):
        self.values['RAFII_TREND_FORECASTS_ENABLED']='0'
        with self.assertRaisesRegex(TrendStorageError,'disabled'):self.admit()
        self.assertFalse(self.store.reads)
        self.values['RAFII_TREND_FORECASTS_ENABLED']='1';self.store.members.remove(self.actor)
        with self.assertRaisesRegex(TrendStorageError,'workspace_access_denied'):self.admit()
        self.assertFalse(self.store.reads)

    def test_required_cursor_and_exact_refs_reject_payload_injection(self):
        self.args['cursor']=None
        with self.assertRaisesRegex(TrendStorageError,'authenticated_transaction'):self.admit()
        self.args['cursor']=self.store.cur;self.args['candidate']['fixture']=False
        with self.assertRaisesRegex(TrendStorageError,'exact_revision'):self.admit()
        self.assertFalse(self.store.writes)

    def test_wrong_workspace_current_policy_and_revision_are_not_read_authority(self):
        for change in ('scope','validity','policy','revision'):
            with self.subTest(change=change):
                saved=copy.deepcopy(self.store.records['forecast_candidate']);r=self.store.records['forecast_candidate']
                if change=='scope':r['scope_key']='workspace:'+uid('foreign')
                if change=='validity':r['validity']='revoked'
                if change=='policy':r['policy']['derive_metrics']=False
                if change=='revision':r['revision']=2
                with self.assertRaises(TrendStorageError):self.admit()
                self.store.records['forecast_candidate']=saved

    def test_head_change_during_lock_cannot_reuse_prelock_payload(self):
        self.store.on_lock=lambda s:s.records['forecast_candidate'].update(revision=2)
        with self.assertRaisesRegex(TrendStorageError,'revision_conflict'):self.admit()

    def test_shadow_withdrawn_old_runtime_or_payload_state_never_imply_production(self):
        for change in ('shadow','withdrawn','revoked','runtime','release'):
            with self.subTest(change=change):
                saved=copy.deepcopy(self.store.methods[('test.evaluation','v1')]);m=self.store.methods[('test.evaluation','v1')]
                if change in ('shadow','withdrawn'):m['qualification']=change
                if change=='revoked':m['revoked_at']=self.store.now
                if change=='runtime':m['config']['forecast_admission']['runtime_digest']='0'*64
                if change=='release':m['config']['forecast_admission']['state']='shadow'
                with self.assertRaisesRegex(TrendStorageError,'production_method_required'):self.admit()
                self.store.methods[('test.evaluation','v1')]=saved

    def test_unreviewed_or_deleted_reviewer_cannot_self_attest_fixture_false(self):
        p=self.store.records['forecast_qualification']['payload']['provenance']
        p['reviewer_id']=self.actor
        with self.assertRaisesRegex(TrendStorageError,'review_provenance'):self.admit()
        p['reviewer_id']=self.reviewer;self.store.members.remove(self.reviewer)
        with self.assertRaisesRegex(TrendStorageError,'workspace_access_denied'):self.admit()

    def test_backdated_preregistration_or_review_is_not_durable_provenance(self):
        r=self.store.records['forecast_preregistration'];r['available_at']=self.store.now
        with self.assertRaisesRegex(TrendStorageError,'review_timing'):self.admit()

    def test_missing_review_or_source_dag_edges_and_unverified_receipt_fail_closed(self):
        self.store.missing_review_edges={'forecast_evaluation'}
        with self.assertRaisesRegex(TrendStorageError,'review_dag_missing'):self.admit()
        self.store.missing_review_edges=set();self.store.missing_source_edges={'forecast_candidate'}
        with self.assertRaisesRegex(TrendStorageError,'source_dag_missing'):self.admit()
        self.store.missing_source_edges=set();self.store.receipt_state='mismatch'
        with self.assertRaisesRegex(TrendStorageError,'verified_receipt_required'):self.admit()

    def test_exact_report_dataset_target_method_and_prediction_digests_required(self):
        for key in ('prediction_digest','report_digest','dataset_digest','target_digest','method_digest','evaluation_plan_digest','preregistration_digest'):
            with self.subTest(key=key):
                p=self.store.records['forecast_qualification']['payload'];saved=p[key];p[key]='0'*64
                with self.assertRaisesRegex(TrendStorageError,'review_binding'):self.admit()
                p[key]=saved

    def test_fixture_source_method_and_offline_store_never_admit(self):
        self.store.observation['provenance']['access_method']='fixture'
        with self.assertRaisesRegex(TrendStorageError,'observation_unavailable'):self.admit()
        self.store.offline_replay=True
        with self.assertRaisesRegex(TrendStorageError,'offline_store'):self.admit()

    def test_current_observation_policy_contract_grants_all_rechecked(self):
        for location in ('observation','policy','contract'):
            with self.subTest(location=location):
                o,p=copy.deepcopy(self.store.observation),copy.deepcopy(self.store.policy)
                if location=='observation':self.store.observation['rights']['derive_metrics']['state']='unknown'
                if location=='policy':self.store.policy['rights']['retain_derivatives']['state']='deny'
                if location=='contract':self.store.policy['contract_operations'].remove('store_metrics')
                with self.assertRaises(TrendStorageError):self.admit()
                self.store.observation,self.store.policy=o,p

    def test_late_policy_availability_cannot_replay_old_knowledge_cutoff(self):
        self.store.policy['available_at']=self.store.now
        with self.assertRaisesRegex(TrendStorageError,'replay_or_qualification_failed'):self.admit()

    def test_short_source_grant_and_expiry_during_compute_fail_before_write(self):
        self.store.observation['rights']['derive_metrics']['expires_at']=shifted(self.store.now,minutes=1)
        with self.assertRaisesRegex(TrendStorageError,'source_retention'):self.admit()
        self.store.observation['rights']['derive_metrics']['expires_at']='2026-10-30T00:00:00Z'
        end=self.store.records['forecast_candidate']['payload']['prediction']['horizon_end']
        self.store.clocks=[self.store.now,end]
        with self.assertRaisesRegex(TrendStorageError,'expired_during_replay'):self.admit()
        self.assertFalse(self.store.writes)

    def test_shared_source_needs_explicit_scope_entitlement_and_share_grants(self):
        shared='shared:forecast-test';self.store.scopes.append(shared)
        self.store.observation['scope_key']=shared
        for rights in (self.store.observation['rights'],self.store.policy['rights']):
            for grant in rights.values():grant['audience_scope']=shared
        for k in ('forecast_candidate','forecast_evaluation'):
            self.store.records[k]['payload']['source_bindings'][0]['scope_key']=shared
        self.assertEqual(self.admit()['state'],'qualified')
        self.store.entitlement['operations'].remove('share_across_workspaces')
        with self.assertRaisesRegex(TrendStorageError,'entitlement'):self.admit()

    def test_changed_evaluation_arithmetic_cannot_pass_reviewed_digests(self):
        report=self.store.records['forecast_evaluation']['payload']['report']
        report['losses'][forecast.CANDIDATE][0]['absolute_error']=100
        report['report_digest']=contracts.digest({k:v for k,v in report.items() if k!='report_digest'})
        self.store.records['forecast_qualification']['payload']['report_digest']=report['report_digest']
        with self.assertRaisesRegex(TrendStorageError,'replay_or_qualification_failed'):self.admit()

    def test_service_read_rechecks_production_review_and_replays_cached_values(self):
        saved=self.adapter.persist(self.wid,self.actor,**self.args)
        self.store.forecasts[saved['object_id']]['payload']['predictions'][0]['point']=999999
        actual=self.adapter.read(self.wid,self.actor,saved['object_id'],revision=1,cursor=self.store.cur)
        self.assertNotEqual(actual['payload']['predictions'][0]['point'],999999)
        self.store.methods[('test.qualification','v1')]['qualification']='shadow'
        with self.assertRaisesRegex(TrendStorageError,'production_method_required'):
            self.adapter.read(self.wid,self.actor,saved['object_id'],revision=1,cursor=self.store.cur)

    def test_idempotent_retry_does_not_bypass_current_source_revocation(self):
        self.adapter.persist(self.wid,self.actor,**self.args)
        self.store.policy['revoked_at']=self.store.now
        with self.assertRaisesRegex(TrendStorageError,'source_policy_denied'):
            self.adapter.persist(self.wid,self.actor,**self.args)
        self.assertEqual(len(self.store.writes),2)

    def test_large_report_uses_existing_chunk_codec_and_requires_attached_digest(self):
        from postriff_phase2.growth.trends.pipeline import encode_manifest
        p=self.store.records['forecast_evaluation']['payload']
        document={'artifact':p.pop('report')};document['manifest_digest']=contracts.digest(document)
        recipe,chunks=encode_manifest(document);inputs=[{'scope_key':self.store.scope,'node_id':self.sid}]
        mid=uid('report-document')
        self.store.manifests[mid]={'recipe':recipe,'document_digest':document['manifest_digest'],'inputs':inputs,
            'chunks':[{'ordinal':i,'digest':contracts.digest(c),'payload':c} for i,c in enumerate(chunks)],
            'digest':contracts.digest({'inputs':inputs,'recipe':recipe,'chunks':[contracts.digest(c) for c in chunks]})}
        p['report_ref']={'manifest_id':mid,'document_digest':document['manifest_digest']}
        self.assertEqual(self.admit()['state'],'qualified')
        self.store.artifact_attached=False
        with self.assertRaisesRegex(TrendStorageError,'artifact_dag_missing'):self.admit()
        self.store.artifact_attached=True;p['report_ref']['document_digest']='0'*64
        with self.assertRaisesRegex(TrendStorageError,'artifact_document'):self.admit()

    def test_source_binding_foreign_workspace_omission_and_bounds_reject(self):
        for mutation in ('scope','missing','excess'):
            with self.subTest(mutation=mutation):
                original=copy.deepcopy(self.store.records['forecast_candidate']['payload']['source_bindings'])
                bindings=self.store.records['forecast_candidate']['payload']['source_bindings']
                if mutation=='scope':bindings[0]['scope_key']='workspace:'+uid('another')
                if mutation=='missing':bindings.clear()
                if mutation=='excess':bindings*=997
                with self.assertRaises(TrendStorageError):self.admit()
                self.store.records['forecast_candidate']['payload']['source_bindings']=original

    def test_chunked_prediction_and_report_bindings_replay_without_public_or_stored_hydration(self):
        for kind,key in (('forecast_candidate','prediction'),('forecast_evaluation','report')):
            r=self.store.records[kind];p=r['payload'];original=copy.deepcopy(p[key])
            sealed=seal_document(self.store,r,key,bindings=p['source_bindings'])
            self.assertEqual(sealed['artifact'],original)
        output=self.adapter.persist(self.wid,self.actor,**self.args)
        self.assertEqual(output['payload']['state'],'qualified')
        self.assertNotIn('source_bindings',output['payload'])
        for kind in ('forecast_candidate','forecast_evaluation'):
            self.assertNotIn('source_bindings',self.store.records[kind]['payload'])
        self.assertEqual(self.adapter.read(self.wid,self.actor,output['object_id'],revision=1,cursor=self.store.cur)['payload']['state'],'qualified')

    def test_chunked_bindings_require_exact_explicit_same_manifest_ref(self):
        r=self.store.records['forecast_candidate'];p=r['payload']
        seal_document(self.store,r,'prediction',bindings=p['source_bindings'])
        original=copy.deepcopy(p)
        for mutation in ('missing','null','foreign_manifest','digest','extra_key','inline','no_artifact_ref'):
            with self.subTest(mutation=mutation):
                r['payload']=p=copy.deepcopy(original)
                if mutation=='missing':p.pop('source_bindings_ref')
                if mutation=='null':p['source_bindings_ref']=None
                if mutation=='foreign_manifest':p['source_bindings_ref']['manifest_id']=uid('foreign')
                if mutation=='digest':p['source_bindings_ref']['document_digest']='0'*64
                if mutation=='extra_key':p['source_bindings_ref']['scope_key']=self.store.scope
                if mutation=='inline':p['source_bindings']=[]
                if mutation=='no_artifact_ref':p.pop('prediction_ref')
                with self.assertRaises(TrendStorageError):self.admit()
        self.assertFalse(self.store.writes)

    def test_binding_document_tamper_even_with_rehashed_chunk_fails_full_digest(self):
        from postriff_phase2.growth.trends.pipeline import encode_manifest
        r=self.store.records['forecast_candidate'];p=r['payload']
        document=seal_document(self.store,r,'prediction',bindings=p['source_bindings'])
        saved=self.store.manifests[p['prediction_ref']['manifest_id']]
        document['source_bindings'][0].update(source_id=uid('substituted'),node_id=uid('substituted'))
        recipe,chunks=encode_manifest(document)
        saved['recipe']=recipe
        saved['chunks']=[{'ordinal':i,'digest':contracts.digest(c),'payload':c} for i,c in enumerate(chunks)]
        saved['digest']=contracts.digest({'inputs':saved['inputs'],'recipe':saved['recipe'],'chunks':[c['digest'] for c in saved['chunks']]})
        with self.assertRaisesRegex((TrendStorageError,ValueError),'digest|manifest'):self.admit()

    def test_binding_document_missing_foreign_duplicate_and_malformed_refs_reject(self):
        base=copy.deepcopy(self.store.records['forecast_candidate'])
        for mutation in ('empty','foreign','duplicate','mismatched_id','extra_key','not_list','bad_uuid','too_many'):
            with self.subTest(mutation=mutation):
                r=copy.deepcopy(base);bindings=copy.deepcopy(r['payload']['source_bindings'])
                if mutation=='empty':bindings=[]
                if mutation=='foreign':bindings[0]['scope_key']='workspace:'+uid('foreign')
                if mutation=='duplicate':bindings*=2
                if mutation=='mismatched_id':bindings[0]['node_id']=uid('wrong')
                if mutation=='extra_key':bindings[0]['raw_text']='not allowed'
                if mutation=='not_list':bindings={}
                if mutation=='bad_uuid':bindings[0]['source_id']=True
                if mutation=='too_many':bindings=[{'source_id':uid(str(i)),'scope_key':self.store.scope,'node_id':uid(str(i))} for i in range(1001)]
                seal_document(self.store,r,'prediction',bindings=bindings)
                with self.assertRaises((TrendStorageError,ValueError,TypeError)):
                    self.adapter._hydrate(self.store.cur,r,'prediction')

    def test_one_thousand_chunked_bindings_fit_root_and_hydrate_without_truncation(self):
        r=self.store.records['forecast_candidate'];bindings=[{'source_id':uid(str(i)),'scope_key':self.store.scope,'node_id':uid(str(i))} for i in range(1000)]
        seal_document(self.store,r,'prediction',bindings=bindings)
        self.assertLess(len(contracts.canonical(r['payload']).encode()),65536)
        loaded=self.adapter._load(self.store.cur,self.wid,self.actor,{'kind':'forecast_candidate',**self.args['candidate']},self.store.now)
        self.adapter._hydrate(self.store.cur,loaded,'prediction')
        self.assertEqual(loaded['payload']['source_bindings'],bindings)
        self.assertGreater(len(contracts.canonical(loaded['payload']).encode()),65536)
        with self.assertRaisesRegex(TrendStorageError,'source_bound'):self.admit()
        self.assertFalse(self.store.writes)

    def test_oversized_root_is_rejected_before_manifest_read(self):
        r=self.store.records['forecast_candidate'];p=r['payload']
        seal_document(self.store,r,'prediction',bindings=p['source_bindings'])
        p['padding']='x'*65536
        with patch.object(self.store,'get_manifest',side_effect=AssertionError('must not read manifest')):
            with self.assertRaisesRegex(TrendStorageError,'payload_limit'):self.admit()

    def test_chunked_binding_document_still_requires_current_ancestor(self):
        r=self.store.records['forecast_candidate'];p=r['payload']
        seal_document(self.store,r,'prediction',bindings=p['source_bindings'])
        self.store.artifact_attached=False
        with self.assertRaisesRegex(TrendStorageError,'artifact_dag_missing'):self.admit()

    def test_binding_reference_cannot_claim_a_legacy_document_without_bindings(self):
        r=self.store.records['forecast_candidate'];p=r['payload']
        seal_document(self.store,r,'prediction');p.pop('source_bindings')
        p['source_bindings_ref']=copy.deepcopy(p['prediction_ref'])
        with self.assertRaisesRegex(TrendStorageError,'artifact_document'):self.admit()

    def test_caller_claimed_observed_class_does_not_replace_registry_review(self):
        self.store.records['forecast_evaluation']['payload']['evidence_class']='retained_observed_data'
        self.store.methods[('test.evaluation','v1')]['config']['forecast_admission'].pop('evidence_class')
        with self.assertRaisesRegex(TrendStorageError,'observed_evidence_review_required'):self.admit()

    def test_persisted_forecast_cannot_be_substituted_under_another_object_id(self):
        saved=self.adapter.persist(self.wid,self.actor,**self.args)
        false_id=uid('substitution');self.store.forecasts[false_id]={**saved,'object_id':false_id}
        with self.assertRaisesRegex(TrendStorageError,'stored_binding_mismatch'):
            self.adapter.read(self.wid,self.actor,false_id,revision=1,cursor=self.store.cur)


if __name__=='__main__':unittest.main()

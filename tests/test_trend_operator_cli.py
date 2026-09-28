"""Actual file-only operator subprocesses, sealed algorithms, and measured outcomes."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from test_trend_metrics import fixture, OfflineCase
from postriff_phase2.growth.trends import backtest, contracts, methods, receipts
from postriff_phase2.growth.trends.pipeline import implementation_methods, encode_manifest

ROOT=Path(__file__).resolve().parents[1]


class OperatorCLI(OfflineCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='trend-operator-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.directory=Path(cls.tmp.name)
        cls.data=fixture();cls.cutoff=cls.data['decision_cutoff'];cls.at='2026-09-28T08:00:00Z'
        # These are explicit synthetic grants, never inferred from a real source.
        for item in cls.data['observations']+cls.data['source_policies']:
            item['rights']['retain_derivatives']=deepcopy(item['rights']['store_raw'])
        cls.trust={'schema':'rafii.trend-current-rights.v1','scope_key':'shared:fixture','checked_at':cls.at,
            'source_policies':cls.data['source_policies'],'deleted_observation_ids':[],
            'revoked_policy_versions':[],'withdrawn_methods':[]}
        cls.input=cls.save('input.json',cls.data);cls.rights=cls.save('rights.json',cls.trust)
        cls.replay=cls.directory/'replay.json'
        done=cls.invoke('trend_replay',cls.replay,cls.replay_args(cls.input))
        if done.returncode:raise AssertionError(done.stdout+done.stderr)
        cls.report=json.loads(cls.replay.read_text());cls.pack=cls.report['decisions'][0]['bundle']
        cls.bundle=cls.save('bundle.json',cls.pack)
        # An actual 800-source receipt gives 12 future hourly measurements:
        # 8*80 plus 4*40 originals, compared with the sealed baseline of50.
        observations=[];members=[];windows=[]
        for hour in range(12):
            start=contracts.instant(cls.cutoff)+timedelta(hours=hour)
            spec=deepcopy(cls.data['window_specs'][-1]);spec.update(start=contracts.iso(start),end=contracts.iso(start+timedelta(hours=1)))
            windows.append(spec)
            for n in range(80 if hour<8 else 40):
                source=deepcopy(cls.data['observations'][0]);identity=f'cli-outcome-{hour}-{n}'
                oid=str(uuid.uuid5(uuid.NAMESPACE_URL,identity));event=start+timedelta(seconds=60+n*30)
                source.update(observation_id=oid,source_identity=identity,revision_identity='r1:'+identity,
                    event_at=contracts.iso(event),received_at=contracts.iso(event+timedelta(seconds=1)),
                    available_at=contracts.iso(event+timedelta(seconds=2)))
                source['payload'].update(native_id=identity,author_key=identity)
                source['payload_digest']=contracts.digest(source['payload']);observations.append(source)
                member=deepcopy(cls.data['membership_events'][0]);member.update(event_id='membership-'+oid,
                    observation_id=oid,input_revision_identity=source['revision_identity'],available_at=source['available_at'])
                members.append(member)
        cls.future_kwargs={'observations':observations,'membership_events':members,'window_specs':windows,'baseline_window_specs':[],
            'source_policies':cls.data['source_policies'],'method_artifacts':implementation_methods(),'scope_key':'shared:fixture',
            'trend_id':'topic_fixture','episode_id':'episode_fixture','decision_cutoff':cls.at,'computed_at':cls.at,'execution_state':'synthetic_fixture'}
        cls.future=receipts.create_receipt(**cls.future_kwargs)
        cls.outcomes=cls.save('outcomes.json',{'schema':'rafii.trend-receipt-bundles.v1','bundles':[cls.future]})

    @classmethod
    def save(cls,name,value):
        path=cls.directory/name;path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False));return path

    @classmethod
    def invoke(cls,script,output,extra,*,rights=None,at=None,execution='fixture'):
        return subprocess.run([sys.executable,str(ROOT/'scripts'/(script+'.py')),'--scope','shared:fixture',
            '--at',at or cls.at,'--current-rights',str(rights or cls.rights),'--execution',execution,'--output',str(output),
            *map(str,extra)],capture_output=True,text=True,timeout=90,cwd=ROOT)

    @classmethod
    def replay_args(cls,path):
        return ['--input',path,'--cutoff',cls.cutoff,'--method','current','--method-available-at','2026-08-01T00:00:00Z',
                '--trend-id','topic_fixture','--episode-id','episode_fixture','--group-id','topic_fixture']

    def call(self,script,extra,*,code=0,**kwargs):
        output=self.directory/(uuid.uuid4().hex+'.json')
        done=self.invoke(script,output,extra,**kwargs)
        self.assertEqual(done.returncode,code,done.stdout+done.stderr)
        self.assertNotIn('Traceback',done.stderr)
        status=json.loads(done.stdout)
        self.assertFalse(status['production_verified'])
        return json.loads(output.read_text()) if output.exists() else status

    def shadow(self,*,outcomes=None,baseline=None,candidate=None,code=0,**kwargs):
        return self.call('trend_shadow_report',['--baseline',baseline or self.replay,'--candidate',candidate or self.replay,
            '--outcomes',outcomes or self.outcomes,'--holdout-start',self.cutoff],code=code,**kwargs)

    def test_real_replay_and_receipt_verification_60_90_150(self):
        decision=self.report['decisions'][0];pure=decision['bundle']['receipt']
        self.assertEqual(backtest.seal_decision(decision),decision)
        self.assertEqual(pure['observed']['previous_window_original_counts'],[60,90])
        self.assertEqual(pure['observed']['qualifying_original_count'],150)
        self.assertEqual(pure['calculated']['acceleration']['value'],30)
        self.assertEqual(pure['calculated']['growth_pct']['value'],200)
        self.assertEqual(decision['candidate_stage'],'rising');self.assertIsNone(pure['inferred']['stage'])
        result=self.call('trend_verify_receipt',['--bundle',self.bundle],execution='local')
        self.assertEqual(result['execution_state'],'local_offline');self.assertFalse(result['durable_database_checked'])
        self.assertEqual(result['results'][0]['state'],'verified')
        self.assertEqual(result['provider_calls'],0);self.assertEqual(result['model_calls'],0)
        self.assertFalse(result['wire_projection_verified'])

    def test_appended_future_revision_cannot_change_earlier_seal(self):
        data=deepcopy(self.data);source=deepcopy(data['observations'][0]);source.update(revision_identity='future-r99',revision_sequence=99,
            observation_id=str(uuid.uuid4()),available_at='2026-09-28T01:00:00Z')
        source['payload']['text']='future label must not affect old decision';source['payload_digest']=contracts.digest(source['payload'])
        data['observations'].append(source)
        member=deepcopy(data['membership_events'][0]);member.update(event_id='future-member',revision_sequence=99,
            episode_id='future-episode',available_at=source['available_at'])
        data['membership_events'].append(member)
        report=self.call('trend_replay',self.replay_args(self.save('future-input.json',data)))
        self.assertEqual(report['decisions'],self.report['decisions'])
        args=self.replay_args(self.input);args[args.index('--method-available-at')+1]='2026-09-28T00:00:00Z'
        denied=self.call('trend_replay',args,code=1)
        self.assertEqual(denied['decisions'][0]['state'],'method_unavailable');self.assertNotIn('bundle',denied['decisions'][0])

    def test_current_deletion_revocation_expiry_fail_without_claims(self):
        cases=[]
        deleted=deepcopy(self.trust);deleted['deleted_observation_ids']=[self.data['observations'][0]['observation_id']]
        cases.append((deleted,self.at,'inputs_deleted'))
        revoked=deepcopy(self.trust);revoked['source_policies'][0]['rights']['derive_metrics']['state']='deny'
        cases.append((revoked,self.at,'policy_revoked'))
        missing=deepcopy(self.trust);missing['source_policies']=[];cases.append((missing,self.at,'policy_revoked'))
        derivative=deepcopy(self.trust);derivative['source_policies'][0]['rights'].pop('retain_derivatives')
        cases.append((derivative,self.at,'policy_revoked'))
        expired=deepcopy(self.trust);expired['checked_at']='2026-10-31T00:00:00Z';cases.append((expired,expired['checked_at'],'inputs_expired'))
        for i,(trust,at,state) in enumerate(cases):
            with self.subTest(state=state,i=i):
                report=self.call('trend_verify_receipt',['--bundle',self.bundle],code=1,rights=self.save('deny'+str(i)+'.json',trust),at=at)
                self.assertEqual(report['results'][0]['state'],state)
                self.assertNotIn('projection',report['results'][0]);self.assertNotIn('verification',report['results'][0])
        report=self.call('trend_replay',self.replay_args(self.input),code=1,rights=self.save('replay-denied.json',deleted))
        self.assertEqual(set(report['decisions'][0]),{'state','reason','decision_cutoff'})

    def test_unknown_historical_executor_and_tampered_manifest(self):
        old=deepcopy(self.pack);artifacts=[]
        for artifact in old['manifest']['method_artifacts']:
            artifacts.append(methods.make_method(artifact['name'],'unavailable-old-version',implementation_digest='f'*64,
                config=artifact['config'],algorithm_id=artifact['algorithm_id']))
        # Produce a real immutable old-version receipt, rather than corrupting its seal.
        old=receipts.create_receipt(observations=self.data['observations'],membership_events=self.data['membership_events'],
            window_specs=self.data['window_specs'],baseline_window_specs=self.data['baseline_window_specs'],
            source_policies=self.data['source_policies'],method_artifacts=artifacts,scope_key='shared:fixture',trend_id='topic_fixture',
            episode_id='episode_fixture',decision_cutoff=self.cutoff,computed_at=self.cutoff)
        result=self.call('trend_verify_receipt',['--bundle',self.save('old.json',old)],code=1)
        self.assertEqual(result['results'][0]['state'],'method_unavailable')
        self.assertNotIn('projection',result['results'][0])
        damaged=deepcopy(self.pack);damaged['manifest']['source_revisions'].pop()
        result=self.call('trend_verify_receipt',['--bundle',self.save('damaged.json',damaged)],code=1)
        self.assertEqual(result['results'][0]['state'],'mismatch')

    def test_durable_full_manifest_codec_uses_same_real_verifier(self):
        recipe,chunks=encode_manifest(self.pack['manifest'])
        inputs=[{'scope_key':o['scope_key'],'node_id':o['observation_id']} for o in self.pack['manifest']['source_revisions']]
        durable={'receipt':{'payload':{'pure_receipt':self.pack['receipt'],'pure_receipt_digest':contracts.digest(self.pack['receipt'])}},
            'manifest':{'recipe':recipe,'inputs':inputs,'document_digest':self.pack['manifest']['manifest_digest'],
                'chunks':[{'ordinal':i,'payload':v,'digest':contracts.digest(v)} for i,v in enumerate(chunks)],
                'digest':contracts.digest({'inputs':inputs,'recipe':recipe,'chunks':[contracts.digest(v) for v in chunks]})}}
        result=self.call('trend_verify_receipt',['--bundle',self.save('durable.json',durable)])
        self.assertEqual(result['results'][0]['state'],'verified')
        self.assertFalse(result['durable_database_checked'])

    def test_real_future_windows_wilson_and_unknown_horizon(self):
        result=self.shadow();self.assertEqual(result['promotion'],'not_attempted')
        self.assertTrue(result['comparisons'][0]['same_method_artifacts'])
        side=result['candidate'];self.assertEqual(side['partition'],{'train':0,'purged':0,'holdout':1})
        self.assertEqual(side['outcomes'][0]['qualifying_windows'],8);self.assertEqual(side['outcomes'][0]['label'],'success')
        calibration=side['methods'][0]
        self.assertEqual(calibration['evaluable'],1);self.assertEqual(calibration['success'],1)
        self.assertAlmostEqual(calibration['wilson_95']['lower'],0.20654931437723745)
        self.assertEqual(calibration['calibration_state'],'insufficient_sample');self.assertIsNone(calibration['false_positive_rate'])
        missing=self.save('no-outcomes.json',{'schema':'rafii.trend-receipt-bundles.v1','bundles':[]})
        result=self.shadow(outcomes=missing)
        self.assertEqual(result['candidate']['outcomes'][0]['label'],'not_evaluable')
        self.assertEqual(result['candidate']['methods'][0]['evaluable'],0)
        trust=deepcopy(self.trust);trust['deleted_observation_ids']=[self.future['manifest']['source_revisions'][0]['observation_id']]
        result=self.shadow(rights=self.save('future-deleted.json',trust))
        self.assertEqual(result['unavailable_outcome_bundles'],{'inputs_deleted':1})
        self.assertEqual(result['candidate']['outcomes'][0]['label'],'not_evaluable')

    def test_time_embargo_and_actual_paired_input_binding(self):
        args=self.replay_args(self.input)+['--cutoff','2026-09-27T19:00:00Z']
        replay=self.call('trend_replay',args)
        path=self.save('two-cutoffs.json',replay)
        result=self.shadow(baseline=path,candidate=path)
        self.assertEqual(result['candidate']['partition'],{'train':0,'purged':1,'holdout':1})
        tampered=deepcopy(self.report);tampered['decisions'][0]['pairing_digest']='0'*64
        tampered['decisions'][0]=backtest.seal_decision(tampered['decisions'][0])
        result=self.shadow(candidate=self.save('wrong-pair.json',tampered),code=2)
        self.assertEqual(result['reason'],'pairing_digest_mismatch')
        result=self.call('trend_shadow_report',['--baseline',self.replay,'--candidate',self.replay,'--outcomes',self.outcomes,
            '--holdout-start',self.cutoff,'--embargo-hours','11'],code=2)
        self.assertEqual(result['status'],'error')

    def test_invalid_inputs_are_machine_readable_and_never_overwrite(self):
        for name,body in [('array','[]'),('nan','{"x":NaN}'),('duplicate','{"x":1,"x":2}'),('invalid','{')]:
            path=self.directory/(name+'.json');path.write_text(body)
            result=self.call('trend_verify_receipt',['--bundle',path],code=2)
            self.assertEqual(result['status'],'error')
        result=self.call('trend_verify_receipt',['--bundle',self.bundle],rights=self.directory/'missing.json',code=2)
        self.assertEqual(result['reason'],'input_missing_or_too_large')
        done=self.invoke('trend_verify_receipt',self.bundle,['--bundle',self.bundle])
        self.assertEqual(done.returncode,2);self.assertEqual(json.loads(done.stdout)['reason'],'output_must_not_replace_input')
        self.assertEqual(json.loads(self.bundle.read_text()),self.pack)
        existing=self.save('existing.json',{'unchanged':True})
        done=self.invoke('trend_verify_receipt',existing,['--bundle',self.bundle])
        self.assertEqual(done.returncode,2);self.assertEqual(json.loads(done.stdout)['reason'],'output_already_exists')
        self.assertEqual(json.loads(existing.read_text()),{'unchanged':True})

    def test_cli_network_guard_blocks_loopback_without_connecting(self):
        # Deliberately attempt a socket after loading the executable guard. The
        # hook rejects connect before an OS network call, including loopback DBs.
        code="import runpy,socket; runpy.run_path('scripts/trend_verify_receipt.py',run_name='__main__')"
        done=subprocess.run([sys.executable,'-c',code,'--help'],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(done.returncode,0)
        code="import sys;sys.path.insert(0,'scripts');import trend_verify_receipt as cli;sys.addaudithook(cli.refuse_network);import socket;socket.create_connection(('127.0.0.1',56451))"
        done=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,cwd=ROOT)
        self.assertNotEqual(done.returncode,0);self.assertIn('network_prohibited',done.stderr)


if __name__=='__main__':unittest.main()

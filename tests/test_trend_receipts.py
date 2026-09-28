from copy import deepcopy
import hashlib
from pathlib import Path
from test_trend_metrics import fixture, OfflineCase
from postriff_phase2.growth.trends import receipts as R, methods as M, metrics


def pack():
    f=fixture(); artifacts=[];registry={}
    names={'normalization':'metrics','deduplication':'metrics','clustering':'membership','baseline':'baselines','momentum':'momentum','lifecycle':'lifecycle','confidence':'confidence'}
    for name,algorithm in R.ALGORITHMS.items():
        module_path=Path(R.__file__).with_name(names[name]+'.py')
        artifact=M.make_method(name,'candidate-1',implementation_digest=hashlib.sha256(module_path.read_bytes()).hexdigest(),config={},algorithm_id=algorithm)
        artifacts.append(artifact);registry=M.register_method(registry,artifact)
    kwargs={'observations':f['observations'],'membership_events':f['membership_events'],'window_specs':f['window_specs'],
            'baseline_window_specs':f['baseline_window_specs'],'source_policies':f['source_policies'],'method_artifacts':artifacts,
            'scope_key':'shared:fixture','trend_id':'topic_fixture','episode_id':'episode_fixture',
            'decision_cutoff':f['decision_cutoff'],'computed_at':'2026-09-27T20:01:00Z'}
    return f,kwargs,registry,R.create_receipt(**kwargs)


class Receipts(OfflineCase):
    def test_complete_manifest_recomputes_and_projects(self):
        f,kwargs,registry,output=pack();receipt,manifest=output['receipt'],output['manifest']
        self.assertEqual(len(manifest['source_revisions']),500);self.assertEqual(len(manifest['membership_revisions']),500)
        self.assertEqual(len(manifest['source_chunks']),2);self.assertEqual(len(manifest['baseline_snapshots']),4)
        self.assertEqual(receipt['calculated']['acceleration']['value'],30)
        self.assertEqual(receipt['calculated']['growth_pct']['denominator'],50)
        self.assertEqual(receipt['observed']['previous_window_original_counts'],[60,90])
        self.assertEqual(receipt['observed']['platform'],'bluesky')
        verification=R.verify_receipt(receipt,manifest,registry,at=f['decision_cutoff'],current_policies=f['source_policies'])
        self.assertEqual(verification['state'],'verified')
        current=R.current_receipt_status(manifest,at=f['decision_cutoff'],current_policies=f['source_policies'])
        view=R.project_receipt(receipt,verification,at=f['decision_cutoff'],current_status=current)
        self.assertEqual(view['calculated']['growth_pct']['value'],200); self.assertIsNone(view['inferred']['stage'])
        self.assertNotIn('source_revisions',view);self.assertIsNone(view['interpretation'])

    def test_all_invalidity_states_and_current_revocation(self):
        f,_,registry,out=pack();r,m=out['receipt'],out['manifest'];at=f['decision_cutoff']
        verified=R.verify_receipt(r,m,registry,at=at,current_policies=f['source_policies'])
        self.assertEqual(r['verification']['state'],'pending')
        variants=[({'deleted_observation_ids':[m['source_revisions'][0]['observation_id']]},'inputs_deleted'),
                  ({'revoked_policy_versions':['policy-v1']},'policy_revoked'),
                  ({'at':'2026-10-31T00:00:00Z'},'inputs_expired')]
        for opts,expected in variants:
            args={'at':at,'current_policies':f['source_policies'],**opts}
            state=R.verify_receipt(r,m,registry,**args)
            self.assertEqual(state['state'],expected)
            status=R.current_receipt_status(m,**args)
            view=R.project_receipt(r,verified,at=args['at'],current_status=status)
            self.assertEqual(view['verification_state'],expected);self.assertIsNone(view['calculated']);self.assertIsNone(view['observed'])
        self.assertEqual(R.verify_receipt(r,m,{},at=at,current_policies=f['source_policies'])['state'],'method_unavailable')
        bad=deepcopy(r);bad['observed']['qualifying_original_count']+=1
        self.assertEqual(R.verify_receipt(bad,m,registry,at=at,current_policies=f['source_policies'])['state'],'mismatch')
        policy=deepcopy(f['source_policies']);policy[0]['revoked_at']=at
        self.assertEqual(R.current_receipt_status(m,at=at,current_policies=policy)['state'],'policy_revoked')
        self.assertEqual(R.current_receipt_status(m,at=at)['state'],'policy_revoked')

    def test_full_manifest_not_display_sample_and_float_tolerance(self):
        f,_,registry,out=pack();r,m=out['receipt'],out['manifest'];at=f['decision_cutoff']
        bad=deepcopy(m);bad['source_revisions']=bad['source_revisions'][:2]
        self.assertEqual(R.verify_receipt(r,bad,registry,at=at,current_policies=f['source_policies'])['state'],'mismatch')
        r['calculated']['acceleration']['value']+=1e-7
        self.assertEqual(R.verify_receipt(r,m,registry,at=at,current_policies=f['source_policies'])['reason'],'receipt_seal_integrity')
        r['receipt_id']='receipt_'+metrics.canonical_digest({k:v for k,v in r.items() if k!='receipt_id'})
        self.assertEqual(R.verify_receipt(r,m,registry,at=at,current_policies=f['source_policies'])['state'],'verified')
        r['calculated']['acceleration']['value']+=.1
        r['receipt_id']='receipt_'+metrics.canonical_digest({k:v for k,v in r.items() if k!='receipt_id'})
        self.assertEqual(R.verify_receipt(r,m,registry,at=at,current_policies=f['source_policies'])['state'],'mismatch')

    def test_later_membership_and_source_cannot_change_old_receipt(self):
        f,kwargs,registry,out=pack()
        later=deepcopy(kwargs['observations'][0]);later.update(revision_identity='future',revision_sequence=22,available_at='2026-09-28T00:00:00Z')
        member=deepcopy(kwargs['membership_events'][0]);member.update(event_id='future-member',revision_sequence=501,episode_id='future-episode',available_at=later['available_at'])
        kwargs['observations'].append(later);kwargs['membership_events'].append(member)
        self.assertEqual(R.create_receipt(**kwargs),out)

    def test_method_version_immutable_and_cannot_promote(self):
        f,kwargs,registry,out=pack();a=deepcopy(kwargs['method_artifacts'][0])
        a['config']['new_threshold']=2
        with self.assertRaises(ValueError):M.register_method(registry,a)
        a=M.make_method(a['name'],a['version'],config={'new_threshold':2},implementation_digest=a['implementation_digest'],algorithm_id=a['algorithm_id'])
        with self.assertRaises(ValueError):M.register_method(registry,a)
        a['qualification']='qualified';a['artifact_digest']=metrics.canonical_digest({k:v for k,v in a.items() if k!='artifact_digest'})
        with self.assertRaises(ValueError):M.register_method({},a)

    def test_pending_stale_status_and_interpretation_never_leak(self):
        f,_,registry,out=pack();r,m=out['receipt'],out['manifest'];at=f['decision_cutoff']
        v=R.verify_receipt(r,m,registry,at=at,current_policies=f['source_policies'])
        status=R.current_receipt_status(m,at=at,current_policies=f['source_policies'])
        view=R.project_receipt(r,v,at='2026-09-27T20:01:00Z',current_status=status)
        self.assertEqual(view['verification_state'],'pending');self.assertIsNone(view['calculated'])
        r['interpretation']={'restricted_text':'secret'}
        self.assertIsNone(R.project_receipt(r,v,at=at,current_status=status)['interpretation'])

    def test_correction_seals_lineage_without_rewriting_original_decision(self):
        f,kwargs,registry,out=pack();original=deepcopy(out['receipt']);old_digest=metrics.canonical_digest(original)
        corrected=R.create_receipt(**{**kwargs,'decision_cutoff':'2026-09-27T20:02:00Z','computed_at':'2026-09-27T20:03:00Z'},
            supersedes_receipt_id=original['receipt_id'],correction_reason='late_observation',original_decision_cutoff=original['decision_cutoff'])
        self.assertEqual(metrics.canonical_digest(out['receipt']),old_digest)
        self.assertEqual(corrected['receipt']['replay_mode'],'correction')
        self.assertEqual(corrected['receipt']['original_decision_cutoff'],original['decision_cutoff'])
        self.assertEqual(R.verify_receipt(corrected['receipt'],corrected['manifest'],registry,at='2026-09-27T20:03:00Z',current_policies=f['source_policies'])['state'],'verified')
        with self.assertRaisesRegex(ValueError,'lineage'):
            R.create_receipt(**kwargs,supersedes_receipt_id=original['receipt_id'])

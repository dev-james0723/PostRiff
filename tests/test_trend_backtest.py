from copy import deepcopy
from test_trend_metrics import fixture, OfflineCase
from postriff_phase2.growth.trends import backtest as B, metrics


class Backtest(OfflineCase):
    def test_sealed_cutoff_hides_future_engagement_membership_method_policy(self):
        f=fixture();cutoff=f['decision_cutoff']
        def decide(**ctx):
            return {'feature_digest':metrics.canonical_digest(ctx),'method_version':'frozen-1'}
        args={'observations':f['observations'],'memberships':f['membership_events'],'cutoffs':[cutoff],
              'decide':decide,'method_artifacts':[],'source_policies':f['source_policies']}
        original=B.replay(**args)
        future=deepcopy(f['observations'][0]);future.update(available_at='2026-09-28T00:00:00Z',revision_sequence=999)
        future['payload']['engagement']=999999
        args['observations'].append(future)
        args['memberships'].append({**f['membership_events'][0],'available_at':future['available_at'],'episode_id':'final-membership'})
        args['method_artifacts'].append({'available_at':future['available_at'],'version':'future'})
        args['source_policies'].append({**f['source_policies'][0],'available_at':future['available_at'],'version':'future'})
        self.assertEqual(B.replay(**args),original)
        self.assertEqual(original[0]['decision_digest'],B.seal_decision(original[0])['decision_digest'])

    def test_replay_order_is_knowledge_time_and_source_sequence(self):
        f=fixture();seen=[]
        def decide(**ctx):
            seen.extend(r['available_at'] for r in ctx['observations']);return {'method_version':'v1'}
        B.replay(list(reversed(f['observations'])),[],[f['decision_cutoff']],decide=decide,method_artifacts=[],source_policies=f['source_policies'])
        self.assertEqual(seen,sorted(seen))

    def test_time_embargo_and_transitive_group_purge(self):
        rows=[{'prediction_id':name,'decision_cutoff':time,'group_ids':groups} for name,time,groups in [
            ('safe','2026-09-25T00:00:00Z',['safe']),('same_topic','2026-09-25T01:00:00Z',['topic','bridge']),
            ('transitive','2026-09-25T02:00:00Z',['bridge']),('embargo','2026-09-26T20:00:00Z',['other']),
            ('holdout','2026-09-27T00:00:00Z',['topic'])]]
        out=B.time_embargo_split(rows,holdout_start='2026-09-27T00:00:00Z')
        self.assertEqual([r['prediction_id'] for r in out['train']],['safe']);self.assertEqual(len(out['purged']),3)
        with self.assertRaises(ValueError): B.time_embargo_split(rows,holdout_start='2026-09-27T00:00:00Z',embargo_hours=6)
        with self.assertRaises(ValueError): B.time_embargo_split([{**rows[0],'group_ids':[]}],holdout_start='2026-09-27T00:00:00Z')

    def test_real_receipt_and_lifecycle_replay_not_mock_decisions(self):
        from test_trend_receipts import pack
        from postriff_phase2.growth.trends.receipts import create_receipt
        f,kwargs,registry,expected=pack()
        def decide(**ctx):
            data=create_receipt(**{**kwargs, 'observations':ctx['observations'],
                                   'membership_events':ctx['memberships'], 'source_policies':ctx['source_policies']})
            return {'decision_cutoff':ctx['decision_cutoff'], 'receipt':data['receipt']}
        args={'observations':f['observations'],'memberships':f['membership_events'],'cutoffs':[f['decision_cutoff']],
              'decide':decide,'method_artifacts':[],'source_policies':f['source_policies']}
        result=B.replay(**args)
        self.assertEqual(result[0]['receipt'],expected['receipt'])
        self.assertEqual(result[0]['receipt']['inferred']['candidate_stage'],'rising')
        changed=deepcopy(f['observations'][0]);changed.update(available_at='2026-09-28T00:00:00Z',revision_sequence=100,revision_identity='later')
        args['observations'].append(changed)
        self.assertEqual(result,B.replay(**args))

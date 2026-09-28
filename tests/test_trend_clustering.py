from copy import deepcopy
from test_trend_metrics import fixture, OfflineCase
from postriff_phase2.growth.trends import clustering as C, membership as M, embeddings as E, metrics


class Clustering(OfflineCase):
    def rows(self):
        f=fixture();a,b=deepcopy(f['observations'][:2]);return f,a,b

    def test_original_cantonese_code_switch_punctuation_emoji(self):
        text='喺香港做 AI agent 真係唔簡單呀！😂 #工作'
        features=C.text_features(text,'yue-en')
        self.assertEqual(features['original_text'],text);self.assertIn('香港',features['tokens']);self.assertIn('😂',features['emoji'])
        self.assertTrue(features['code_switch_spans']);self.assertIsNone(features['geography'])
        self.assertEqual(C.text_features('這個學習體驗')['language'],'zh-Hant')
        self.assertEqual(C.text_features('这个学习体验')['language'],'zh-Hans')
        self.assertEqual(C.text_features('佢哋喺度做嘢')['language'],'yue')

    def test_same_entity_different_events_and_recurrence_separated(self):
        f,a,b=self.rows()
        a['payload'].update(text='Alex concert tonight tickets piano',entity_keys=['Alex'],event_type='concert')
        b['payload'].update(text='Alex lawsuit court trial judge',entity_keys=['Alex'],event_type='lawsuit')
        pair=C.compare_pair(a,b,decision_cutoff=f['decision_cutoff'],source_policies=f['source_policies'])
        self.assertEqual(pair['decision'],'different_conversation');self.assertEqual(pair['features']['entity_overlap'],1)
        b['payload']=deepcopy(a['payload']);b['event_at']='2026-08-30T00:00:00Z'
        self.assertEqual(C.compare_pair(a,b,decision_cutoff=f['decision_cutoff'],source_policies=f['source_policies'])['decision'],'different_conversation')

    def test_uncertainty_abstains_and_id_namespaces_separate(self):
        f,a,b=self.rows();a['payload']['text']='alpha beta gamma delta';b['payload']['text']='alpha beta other fourth'
        pair=C.compare_pair(a,b,decision_cutoff=f['decision_cutoff'],source_policies=f['source_policies'])
        self.assertEqual(pair['decision'],'unsure');self.assertEqual(pair['mode'],'lexical_only')
        self.assertEqual(C.apply_semantic_choice(pair,choice='invented',existing_candidate_ids=[b['observation_id']])['semantic_choice'],'unsure')
        ids=C.conversation_ids(entity_keys=['x'],topic_key='x',episode_anchor='x',pattern_text='x',language='yue',scope_key='shared:fixture')
        self.assertEqual(len(set([*ids['entity_ids'],ids['topic_id'],ids['episode_id'],ids['pattern_id']])),4)

    def test_temporal_merge_split_and_optimistic_conflict(self):
        f,a,b=self.rows();events=f['membership_events'][:2];before='2026-09-27T18:00:00Z';after='2026-09-27T19:00:00Z'
        kwargs={'scope_key':'shared:fixture','available_at':after,'method_version':'test','observations':f['observations'],'source_policies':f['source_policies']}
        merged=M.merge_episodes(events,from_episode_id='episode_fixture',to_episode_id='episode_new',expected_revision=2,**kwargs)
        self.assertEqual(M.resolve_memberships(merged,before),sorted(events,key=lambda e:(e['scope_key'],e['observation_id'])))
        self.assertEqual({m['episode_id'] for m in M.resolve_memberships(merged,after)}, {'episode_new'})
        self.assertEqual(M.resolve_episode_alias('episode_fixture',merged,before,scope_key='shared:fixture'),'episode_fixture')
        self.assertEqual(M.resolve_episode_alias('episode_fixture',merged,after,scope_key='shared:fixture'),'episode_new')
        with self.assertRaises(ValueError):M.merge_episodes(merged,from_episode_id='episode_new',to_episode_id='episode_third',expected_revision=2,**kwargs)
        split=M.split_episode(merged,parent_episode_id='episode_new',assignments={a['observation_id']:'child_a',b['observation_id']:'child_b'},expected_revision=5,**kwargs)
        self.assertEqual({m['episode_id'] for m in M.resolve_memberships(split,after)}, {'child_a','child_b'})

    def test_membership_requires_current_rights_and_source_revision(self):
        f,a,b=self.rows();proposal=deepcopy(f['membership_events'][0]);proposal.pop('event_id');proposal['available_at']=f['decision_cutoff']
        f['source_policies'][0]['rights']['derive_metrics']['state']='deny'
        with self.assertRaisesRegex(ValueError,'not_permitted'):M.append_membership_events([], [proposal],expected_revision=0,observations=f['observations'],source_policies=f['source_policies'])
        self.assertEqual(M.resolve_memberships(f['membership_events'],f['decision_cutoff'],observations=f['observations'],source_policies=f['source_policies']),[])

    def test_embedding_is_cohort_rights_and_time_gated(self):
        f,a,b=self.rows();cutoff=f['decision_cutoff']
        record={'embedding_id':'e1','candidate_id':'c1','scope_key':'shared:fixture','available_at':a['available_at'],'retention_until':a['retention_until'],'model_version':'model-v1','rights':a['rights'],'vector':[1.,0.],'provider_id':a['provider_id'],'source_policy_version':a['source_policy_version']}
        q={'state':'qualified','cohorts':['en'],'model_version':'model-v1','available_at':'2026-08-01T00:00:00Z'}
        args={'decision_cutoff':cutoff,'scope_key':'shared:fixture','cohort':'en','qualification':q,'source_policies':f['source_policies']}
        self.assertEqual(E.nearest_neighbors([record],[1.,0.],**args)[0]['similarity'],1)
        self.assertEqual(E.nearest_neighbors([record],[1.,0.],**{**args,'cohort':'yue'}),[])
        record['rights']['store_embeddings']['state']='deny'
        self.assertEqual(E.nearest_neighbors([record],[1.,0.],**args),[])
        with self.assertRaises(ValueError):E.cosine_similarity([float('nan')],[1])

    def test_denied_or_future_pair_has_no_text_features(self):
        f,a,b=self.rows()
        for field,value in [('available_at','2026-09-28T00:00:00Z'),('scope_key','shared:other')]:
            changed={**b,field:value}
            out=C.compare_pair(a,changed,decision_cutoff=f['decision_cutoff'],source_policies=f['source_policies'])
            self.assertEqual(out['decision'],'unsure');self.assertEqual(out['original_features'],[]);self.assertIsNone(out['features'])
        out=C.compare_pair(a,b,decision_cutoff=f['decision_cutoff'],source_policies=[])
        self.assertEqual(out['original_features'],[])

    def test_membership_cannot_backdate_a_new_decision(self):
        f,a,b=self.rows();events=f['membership_events'][:2]
        proposal=deepcopy(events[0]);proposal.pop('event_id')
        with self.assertRaisesRegex(ValueError,'backdate'):
            M.append_membership_events(events,[proposal],expected_revision=2,observations=f['observations'],source_policies=f['source_policies'])

import copy
import unittest
from dataclasses import replace
from unittest.mock import patch
from postriff_phase2.growth import scout as S, scout_outcomes as O, scout_evidence as E, scout_runtime as R
from postriff_phase2.growth.router import AIModelRouter
from postriff_phase2.coworker import flags, listening

NOW = 1800000000
WL = {'id': 'wl1', 'query': 'bakery sourdough proof', 'goal': 'Help local bakers', 'primaryObjective': 'shareability', 'active': True}
STATE = {'brandHub': {'audience': 'local bakers'}, 'phase2': {'channels': [{'id': 'li', 'platform': 'LinkedIn'}, {'id': 'th', 'platform': 'Threads'}, {'id': 'ig', 'platform': 'Instagram'}]}}
def item(n, creator=None, title='Bakery sourdough proof experiment'):
    return {'url': f'https://source{n}.example/post?utm_source=x', 'title': title, 'snippet': f'Independent bakery sourdough proof observation {n}',
            'provenance': {'author': creator or f'creator{n}', 'publishedAt': NOW-3600, 'retrievedAt': NOW, 'platform': 'web', 'evidenceType': 'search_snippet'}}
class Judge:
    def __init__(self, share='utility', missing=None): self.calls=[]; self.share=share; self.missing=missing
    def judge(self, gate, state, workspace_id):
        self.calls.append((gate,workspace_id))
        answers={k:True for k in ('meaningful','sufficient','audience_fit','goal_fit','original_angle','standalone','native_fit')}
        answers['forwarding_utility']=self.share
        if self.missing: answers.pop(self.missing,None)
        return {'status':'ok','answers':answers}

def ready(judge=None): return S.prepare(copy.deepcopy(STATE),copy.deepcopy(WL),[item(1),item(2)],'w1',NOW,judge=judge or Judge())

class Scout(unittest.TestCase):
    def tearDown(self): flags.attach(None)
    def test_normalize_dedupe_scope_and_age(self):
        a=S.normalize(item(1),'w1',NOW)
        self.assertNotIn('utm_',a['url']); self.assertGreater(a['ageDays'],0)
        self.assertNotEqual(a['id'],S.normalize(item(1),'w2',NOW)['id'])
        self.assertIsNone(S.normalize({'url':'javascript:alert(1)'},'w1',NOW))
        i=item(2); i['provenance'].pop('publishedAt'); self.assertIsNone(S.normalize(i,'w1',NOW)['ageDays'])
        self.assertEqual(len(S.prepare(STATE,WL,[item(1),item(1)],'w1',NOW)['signals']),1)
    def test_cluster_independence_not_urls(self):
        p=S.prepare(STATE,WL,[item(1,'same'),item(2,'same')],'w1',NOW)
        self.assertEqual(p['trends'][0]['stage'],'insufficient_evidence')
        self.assertEqual(ready()['trends'][0]['independentCreators'],2)
    def test_judgment_abstention_never_yes(self):
        p=S.prepare(STATE,WL,[item(1),item(2)],'w1',NOW,judge=S.ScoutJudge(AIModelRouter()))
        self.assertEqual(p['opportunities'][0]['actionType'],'watch')
        self.assertEqual(ready(Judge(missing='original_angle'))['opportunities'][0]['actionType'],'watch')
    def test_ready_objective_and_platform_native(self):
        op=ready()['opportunities'][0]
        self.assertEqual(op['actionType'],'act_now'); self.assertEqual(op['primaryObjective'],'shareability')
        self.assertEqual(len({p['format'] for p in op['executionPlans']}),3)
        self.assertEqual(len({p['hookStrategy'] for p in op['executionPlans']}),3)
        self.assertTrue(all(not p['assetReuseAllowed'] for p in op['executionPlans']))
    def test_no_forwarding_reason_abstains(self):
        for value in ('none','unsure'):
            self.assertEqual(ready(Judge(value))['opportunities'][0]['actionType'],'watch')
    def test_likes_do_not_affect_ranking(self):
        a=item(1); a['likes']=900000000
        self.assertEqual(S.prepare(STATE,WL,[a,item(2)],'w1',NOW)['opportunities'],S.prepare(STATE,WL,[item(1),item(2)],'w1',NOW)['opportunities'])
    def test_unknown_goal_no_filler(self):
        self.assertEqual(S.prepare(STATE,{**WL,'primaryObjective':None},[item(1)],'w1',NOW)['opportunities'],[])
        self.assertEqual(S.prepare(STATE,WL,[{**item(1,title='Unrelated bicycles'), 'snippet':'Only bicycle wheels'}],'w1',NOW)['opportunities'],[])
    def test_lifecycle_expiry_and_repetition(self):
        ss=[S.normalize(item(i),'w1',NOW) for i in range(4)]
        for s in ss: s['contentHash']='identical'
        self.assertEqual(S.cluster(ss,'wl1','w1',NOW)[0]['stage'],'saturated')
        for s in ss: s['ageDays']=10
        self.assertEqual(S.cluster(ss,'wl1','w1',NOW)[0]['stage'],'expired')
    def test_store_bounded_idempotent(self):
        state=copy.deepcopy(STATE); wl=copy.deepcopy(WL); p=ready()
        S.store(state,wl,p,NOW); state['coworker']['listening']['opportunities'][0]['status']='dismissed'
        S.store(state,wl,ready(),NOW)
        self.assertEqual(len(state['coworker']['listening']['opportunities']),1)
        self.assertEqual(state['coworker']['listening']['opportunities'][0]['status'],'dismissed')
    def test_flags_off_legacy_watchlist_and_view(self):
        flags.attach({}); state={}; wl=listening.save_watchlist(state,{'query':'bakery proof'},'a',NOW)
        self.assertNotIn('primaryObjective',wl); self.assertNotIn('flipper',listening.view(state,NOW))
    def test_flags_on_require_single_objective(self):
        flags.attach({'RAFII_ACTIVE_SCOUT_ENABLED':'1'})
        with self.assertRaises(Exception): listening.save_watchlist({}, {'query':'bakery proof','primaryObjective':['reach','authority']},'a',NOW)
    @patch('postriff_phase2.growth.scout_runtime.research.allowed',return_value=True)
    def test_claim_fences_budget_consent_changes(self,_):
        state=copy.deepcopy(STATE); listening.root(state)['watchlists']=[copy.deepcopy(WL)]
        self.assertIsNotNone(R.reserve(state,NOW,'one')); self.assertIsNone(R.reserve(state,NOW,'two'))
        self.assertIsNone(R.complete(state,'two',ready(),NOW+1))
        state['brandHub']['audience']='different'
        self.assertIsNone(R.complete(state,'one',ready(),NOW+1))
        self.assertEqual(state['coworker']['listening']['scoutBudget']['retrieval'],1)
    @patch('postriff_phase2.growth.scout_runtime.research.allowed',return_value=True)
    def test_failed_run_does_not_erase_evidence(self,_):
        state=copy.deepcopy(STATE); root=listening.root(state); root['watchlists']=[copy.deepcopy(WL)]
        S.store(state,root['watchlists'][0],ready(),NOW-2*86400)
        R.reserve(state,NOW,'one')
        R.complete(state,'one',{'signals':[],'trends':[],'opportunities':[],'status':'unavailable'},NOW+1)
        self.assertTrue(root['trends']); self.assertTrue(root['opportunities'])

RIGHTS={'access':True,'analyze':True,'storeEvidence':True,'retainUntil':NOW+86400}
def pack(**kwargs):
    base=E.EvidencePack('s','hash','fixture','1',NOW,30,'none',(),(),(),(),(),'sparse',{'provider':'fixture'},RIGHTS)
    return replace(base,**kwargs)
class Adapter:
    def __init__(self): self.calls=0
    def capabilities(self): return {'id':'fixture','version':'1','enforcesDeadline':True,'stages':['frames','multimodal']}
    def supports(self,s): return True
    def analyze(self,r):
        self.calls+=1
        return pack(source_id=r['source']['id'],content_hash=r['source']['contentHash']),{'requests':1,'costSource':'unknown'}
class Media(unittest.TestCase):
    def test_caption_only_no_watched_state(self): self.assertFalse(pack(source_text='great demo').summary()['videoObserved'])
    def test_no_transcript_no_spoken(self):
        with self.assertRaises(ValueError): pack(spoken_highlights=({'refs':['x']},)).summary()
    def test_transcript_only_no_visual(self):
        with self.assertRaises(ValueError): pack(transcript_source='whisper',transcript=({'id':'t','time':1},),visual_highlights=({'refs':['x']},)).summary()
    def test_frames_only_and_sparse_limitation(self):
        summary=pack(frames=({'id':'f','time':1},)).summary()
        self.assertTrue(summary['videoObserved']); self.assertEqual(summary['spokenHighlights'],[])
        self.assertTrue(any('Sampled' in x for x in summary['limitations']))
        self.assertEqual(summary['reuse'],'pattern_learning_only')
    def test_moment_evidence_time_and_abstain(self):
        m=E.MomentCandidate(1,5,'Demo','visual','Visible proof',('demo',),visual_refs=('f',),confidence='high')
        self.assertEqual(len(pack(frames=({'id':'f','time':1},),moments=(m,)).summary()['moments']),1)
        self.assertEqual(pack(frames=({'id':'f','time':1},),moments=(replace(m,confidence='low'),)).summary()['moments'],[])
        for bad in (replace(m,end=31),replace(m,start=float('nan')),replace(m,evidence_type='mixed')):
            with self.assertRaises(ValueError): pack(frames=({'id':'f','time':1},),moments=(bad,)).summary()
    def test_gate_cache_workspace_budget_rights(self):
        adapter=Adapter(); cache=[]; ledger={}
        source={'id':'s','contentHash':'hash','ageDays':1,'duration':30,'rights':RIGHTS}
        def run(s=source,w='w1'):
            return E.enrich(s,workspace_id=w,adapter=adapter,ledger=ledger,cache=cache,now=NOW,deadline=10,relevant=True,useful=True,enabled=True,clock=lambda:0)
        self.assertEqual(run()['status'],'ok'); self.assertTrue(run()['cached']); self.assertEqual(adapter.calls,1)
        self.assertEqual(run(w='w2')['status'],'ok'); self.assertEqual(adapter.calls,2)
        self.assertEqual(run({**source,'id':'b','contentHash':'new'})['reason'],'budget_exhausted')
        self.assertEqual(run({**source,'rights':{}})['reason'],'rights_unknown')
    def test_unavailable_route_keeps_text(self):
        r=E.enrich({},workspace_id='w',adapter=None,ledger={},cache=[],now=NOW,deadline=1,relevant=True,useful=True)
        self.assertEqual(r['reason'],'adapter_unavailable'); self.assertTrue(ready()['opportunities'])

def observation(n,value=10,objective='follower_conversion',window='24h',**changes):
    row={'id':str(n),'account':'a','provider':'threads','language':'en','format':'text','window':window,'objective':objective,'definition':'v1','publishedAt':NOW-100000+n*1000,
         'metrics':{k:{'value':v,'coverage':'available','receipt':f'r{n}{k}','observedAt':NOW} for k,v in {'likes':100000,'profile_visits':100,'follows':value,'views':1000,'shares':value}.items()}}
    row.update(changes); return row
class Outcomes(unittest.TestCase):
    def test_normalized_comparable_observed_over_model(self):
        history=[observation(i) for i in range(5)]
        r=O.evaluate(observation(9,30,modelScore=0),history)
        self.assertEqual(r['state'],'double_down_candidate'); self.assertAlmostEqual(r['lift'],3); self.assertFalse(r['durableStrategy']); self.assertFalse(r['causal'])
        self.assertEqual(O.evaluate(observation(9,1,modelScore=100),history)['state'],'underperformed')
    def test_missing_profile_follows_likes_only_unavailable(self):
        for missing in ('profile_visits','follows'):
            row=observation(9); row['metrics'].pop(missing)
            self.assertEqual(O.evaluate(row,[])['state'],'measurement_unavailable')
    def test_one_hour_never_durable(self): self.assertEqual(O.evaluate(observation(9,30,window='1h'),[])['state'],'observing')
    def test_mixed_cohorts_duplicates_and_zero(self):
        history=[observation(i,account='other') for i in range(5)]
        self.assertEqual(O.evaluate(observation(9),history)['state'],'needs_more_data')
        self.assertEqual(O.evaluate(observation(9),[observation(1)]*10)['samples'],1)
        self.assertEqual(O.evaluate(observation(9),[observation(i,0) for i in range(5)])['state'],'insufficient_data')
    def test_invalid_denominator_and_nan(self):
        r=observation(9); r['metrics']['profile_visits']['value']=0; self.assertIsNone(O.objective_measure(r)[0])
        r['metrics']['follows']['value']=float('nan'); self.assertIsNone(O.value(r,'follows'))
    def test_business_return_and_retention_never_inferred(self): self.assertEqual(O.evaluate(observation(9),[])['businessReturn'],'unmeasured')



class Hardening(unittest.TestCase):
    def test_preview_blocks_new_egress(self):
        from postriff_phase2.coworker.flags import EGRESS_FLAGS
        self.assertIn('RAFII_ACTIVE_SCOUT_ENABLED',EGRESS_FLAGS)
        self.assertIn('RAFII_MULTIMODAL_ENRICHMENT_ENABLED',EGRESS_FLAGS)
    def test_media_retention_removes_cached_and_embedded_evidence(self):
        state={'coworker':{'listening':{'mediaCache':[{'expiresAt':NOW-1}], 'opportunities':[{'evidence':[{'mediaEvidence':{'rights':{'retainUntil':NOW-1}}}], 'executionPlans':[{'keyMomentRefs':[{'retainUntil':NOW-1}]}]}]}}}
        S.prune_media(state,NOW);root=state['coworker']['listening']
        self.assertEqual(root['mediaCache'],[]);self.assertNotIn('mediaEvidence',root['opportunities'][0]['evidence'][0])
        self.assertEqual(root['opportunities'][0]['executionPlans'][0]['keyMomentRefs'],[])
    def test_lineage_retraction_and_tamper(self):
        state={'sources':[{'id':'s','active':True,'text':'Plan','origin':{'kind':'scout_opportunity','executionPlan':{'id':'p'}}}]}
        bindings=S.lineage(state,['s']);S.validate_lineage(state,bindings)
        state['sources'][0]['active']=False
        with self.assertRaises(Exception):S.validate_lineage(state,bindings)
    def test_supplied_watch_adapter_never_acquires_media(self):
        p=pack(frames=({'id':'f','time':1},));a=E.SuppliedWatchAdapter({'hash':p})
        self.assertTrue(a.supports({'mediaType':'video','contentHash':'hash'}))
        import time
        returned,receipt=a.analyze({'source':{'contentHash':'hash'},'deadline':time.monotonic()+1})
        self.assertEqual(receipt['providerCalls'],0);self.assertTrue(returned.summary()['videoObserved'])
    def test_timestamped_native_and_whisper_transcripts(self):
        for source in ('native_captions','whisper'):
            p=pack(transcript_source=source,transcript=({'id':'t','time':1,'text':'Original explanation'},),spoken_highlights=({'refs':['t'],'text':'Explanation'},))
            summary=p.summary();self.assertEqual(summary['visualHighlights'],[]);self.assertEqual(summary['transcriptSource'],source)
    def test_source_changed_hash_refreshes(self):
        state=copy.deepcopy(STATE);w=copy.deepcopy(WL);S.store(state,w,ready(),NOW)
        changed=item(1);changed['snippet']='New bakery sourdough proof evidence'
        p=S.prepare(state,w,[changed],'w1',NOW+1)
        self.assertTrue(any(s['text']==changed['snippet'] for s in p['signals']))

class LeaseLimits(unittest.TestCase):
    @patch('postriff_phase2.growth.scout_runtime.research.allowed',return_value=True)
    def test_expired_completion_and_daily_budget(self,_):
        flags.attach({})
        state=copy.deepcopy(STATE);root=listening.root(state);root['watchlists']=[copy.deepcopy(WL)]
        self.assertIsNotNone(R.reserve(state,NOW,'one'))
        self.assertIsNone(R.complete(state,'one',ready(),NOW+91))
        for n in range(1,4):self.assertIsNotNone(R.reserve(state,NOW+n*100,f'token{n}'))
        self.assertIsNone(R.reserve(state,NOW+500,'exhausted'))
        self.assertEqual(root['scoutBudget']['judgments'],32)
        flags.attach(None)
    def test_media_adapter_cannot_smuggle_strong_synthesis(self):
        adapter=Adapter();adapter.capabilities=lambda:{'id':'bad','enforcesDeadline':True,'stages':['synthesis']}
        r=E.enrich({'id':'s','contentHash':'hash','ageDays':1,'duration':30,'rights':RIGHTS},workspace_id='w',adapter=adapter,ledger={},cache=[],now=NOW,deadline=10,relevant=True,useful=True,enabled=True,clock=lambda:0)
        self.assertEqual(r['reason'],'invalid_adapter_budget');self.assertEqual(adapter.calls,0)

class SourceEvidence(unittest.TestCase):
    def test_media_identity_changes_even_when_caption_does_not(self):
        i=item(1);i['provenance']['contentHash']='video-a'
        state=copy.deepcopy(STATE);w=copy.deepcopy(WL)
        S.store(state,w,S.prepare(state,w,[i],'w1',NOW),NOW)
        i['provenance']['contentHash']='video-b'
        p=S.prepare(state,w,[i],'w1',NOW+1)
        self.assertEqual(len(p['signals']),1)
        self.assertEqual(p['signals'][0]['contentHash'],'video-b')
    def test_new_official_reading_refreshes_unchanged_text(self):
        i=item(1);i['provenance'].update(kind='official_api',provider='threads')
        i['observedOutcome']=observation(9,30);i['creatorHistory']=[observation(n) for n in range(5)]
        state=copy.deepcopy(STATE);w=copy.deepcopy(WL)
        S.store(state,w,S.prepare(state,w,[i],'w1',NOW),NOW)
        i['observedOutcome']=observation(9,5)
        p=S.prepare(state,w,[i],'w1',NOW+1)
        self.assertEqual(len(p['signals']),1)
        self.assertEqual(p['signals'][0]['observedOutcome']['state'],'underperformed')
        self.assertAlmostEqual(p['signals'][0]['observedOutcome']['lift'],.5)
    def test_official_normalization_keeps_comparable_account_basis(self):
        i=item(1);i['provenance'].update(kind='official_api',provider='threads')
        i['observedOutcome']=observation(9,30);i['creatorHistory']=[observation(n) for n in range(5)]
        normalized=S.normalize(i,'w1',NOW)['observedOutcome']
        self.assertAlmostEqual(normalized['lift'],3);self.assertEqual(normalized['samples'],5)
        i['provenance']['kind']='web_search'
        self.assertIsNone(S.normalize(i,'w1',NOW)['observedOutcome'])
    def test_accepted_preferences_remain_account_and_objective_scoped(self):
        state=copy.deepcopy(STATE)
        state['_scoutPlanningPreferences']=[{'id':'h','statement':'A reviewed association','cohort':{'objective':'shareability','account':'li','language':'en'},'expiresAt':NOW+1}]
        result=S.prepare(state,WL,[item(1),item(2)],'w1',NOW,judge=Judge())
        plans=result['opportunities'][0]['executionPlans']
        self.assertEqual(len(plans[0]['planningPreferences']),1)
        self.assertEqual(plans[1]['planningPreferences'],[])

if __name__=='__main__':unittest.main()

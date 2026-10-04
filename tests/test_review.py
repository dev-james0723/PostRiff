"""Review projection semantics; SYNTHETIC stored observations, no provider calls."""
import copy
import importlib.util
import unittest
from datetime import datetime, timezone
from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc).timestamp()


def fixture():
    jobs, rows = [], []
    for i in range(6):
        at = NOW - (2 + i) * 86400
        job = {'id': str(i), 'state': 'verified', 'providerReference': 'post-' + str(i), 'verification': {'at': at},
               'manifest': {'channelId': 'own', 'platform': 'Instagram', 'contentType': {'id': 'text', 'formatId': 'text'},
                            'payload': {'language': 'en', 'text': 'Synthetic original ' + str(i)}}}
        jobs.append(job)
        for name, value in (('reach', i * 10), ('likes', i)):
            rows.append({'observationId': name + str(i), 'jobId': str(i), 'connectionId': 'own', 'provider': 'instagram',
                         'nativePostId': job['providerReference'], 'nativeName': name, 'definitionVersion': insights.DEFINITION_VERSION,
                         'unit': 'count', 'value': value, 'availability': 'available', 'observedAt': at + 86400,
                         'ingestedAt': at + 86401, 'readOffset': '24h', 'sourceRef': 'https://graph.instagram.com/v25.0/post/insights',
                         'collectionState': 'measured'})
    state = {'phase2': {'channels': [{'id': 'own', 'platform': 'Instagram'}], 'jobs': jobs}}
    scope = {'channelIds': ['own'], 'publicationPeriod': {'start': '2026-09-20T00:00:00Z', 'end': '2026-10-04T00:00:00Z', 'timezone': 'America/Indiana/Indianapolis'},
             'horizon': '24h', 'language': 'en', 'formatIds': ['text'], 'nativeMetric': [{'provider': 'instagram', 'nativeName': 'reach', 'definitionVersion': insights.DEFINITION_VERSION, 'unit': 'count'}],
             'comparison': {'kind': 'none'}, 'aggregation': 'median'}
    return state, rows, scope


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.find_spec('postriff_phase2.coworker.review')
        cls.review = __import__('postriff_phase2.coworker.review', fromlist=['review']) if spec else None

    def setUp(self):
        self.assertIsNotNone(self.review, 'The strict review projection adapter is required')
        self.state, self.rows, self.scope = fixture()

    def context(self):
        return self.review.resolve_review_context('workspace', self.scope, self.state, NOW, rights_epoch='epoch')

    def projection(self):
        return self.review.project_review(self.state, self.context(), self.rows, {'own'}, NOW)

    def test_route_workspace_cannot_be_overridden(self):
        self.scope['workspaceId'] = 'foreign'
        with self.assertRaises(AlphaError): self.context()
        self.scope.pop('workspaceId'); self.scope['channelIds'] = ['foreign']
        with self.assertRaises(AlphaError): self.context()

    def test_dates_require_explicit_timezone_and_half_open_period(self):
        self.scope['publicationPeriod']['timezone'] = 'fake/zone'
        with self.assertRaises(AlphaError): self.context()

    def test_scope_rejects_ambiguous_dates_and_future_classification(self):
        self.scope['relativeDateRule'] = {'kind':'this_week','timezone':'UTC'}
        with self.assertRaises(AlphaError): self.context()
        self.scope.pop('relativeDateRule')
        self.state['coworker'] = {'review':{'tags':{'theme':{'kind':'theme'}},'classificationVersion':2}}
        self.scope['tagSelection'] = [{'tagId':'theme','kind':'theme','classificationVersion':3}]
        with self.assertRaises(AlphaError): self.context()

    def test_metric_time_keeps_subsecond_precision(self):
        self.rows[0]['observedAt'] += 0.125
        evidence = self.projection()['nativeResults'][0]
        self.assertEqual(self.review.stamp(evidence['observedAt']), self.rows[0]['observedAt'])
        self.scope['publicationPeriod']['timezone'] = 'UTC'
        self.scope['publicationPeriod']['end'] = self.scope['publicationPeriod']['start']
        with self.assertRaises(AlphaError): self.context()

    def test_sql_microsecond_precision_does_not_make_exact_due_time_early(self):
        at=1791028800.8240361
        self.state['phase2']['jobs'][0]['verification']['at']=at-86400
        self.rows[0]['observedAt']=float('1791028800.824036')
        self.rows[0]['ingestedAt']=at+1
        self.assertTrue(self.projection()['nativeResults'][0]['eligible'])

    def test_takeaway_cannot_propose_hypothesis_with_other_scope_or_low_arms(self):
        p=self.projection()
        h={'id':'h','cohort':{'connectionId':'own','provider':'instagram','language':'en','contentTypeId':'text','definitionVersion':insights.DEFINITION_VERSION},'metric':'reach','dimension':'length','sample_a':5,'sample_b':5,'evidence_ids':['0'],'counter_evidence_ids':[],'expiresAt':NOW+100}
        self.assertFalse(self.review.review_hypothesis_eligible(self.state,p,h,NOW))
        h['cohort']['connectionId']='other'
        self.assertFalse(self.review.review_hypothesis_eligible(self.state,p,h,NOW))

    def test_relative_view_resolves_dst_local_week_without_moving_snapshot(self):
        a = self.review.resolve_relative_period({'kind': 'this_week', 'timezone': 'America/New_York'}, datetime(2026, 11, 1, 17, tzinfo=timezone.utc).timestamp())
        self.assertEqual(a['start'], '2026-10-26T04:00:00Z')
        self.assertEqual(a['end'], '2026-11-02T05:00:00Z')
        b = self.review.resolve_relative_period({'kind': 'this_week', 'timezone': 'America/New_York'}, NOW)
        self.assertNotEqual(a, b)

    def test_relative_saved_view_moves_previous_period_together(self):
        definition={'channelIds':['own'],'relativeDateRule':{'kind':'this_week','timezone':'UTC'},'comparison':{'kind':'previous_period','publicationPeriod':{'start':'2026-09-21T00:00:00Z','end':'2026-09-28T00:00:00Z','timezone':'UTC'}}}
        saved=self.review.save_review_view(self.state,'workspace',{'name':'Weekly','filterDefinition':definition,'expectedRevision':0,'idempotencyKey':'relative-baseline'},'owner',NOW)
        reopened=self.review.resolve_review_context('workspace',saved['filterDefinition'],self.state,NOW+7*86400)
        self.assertEqual(reopened['comparison']['publicationPeriod']['start'],'2026-09-28T00:00:00Z')
        self.assertEqual(reopened['comparison']['publicationPeriod']['end'],'2026-10-05T00:00:00Z')

    def test_scope_filter_precedes_retention_bound(self):
        self.state['phase2']['channels'].append({'id':'other','platform':'Instagram'})
        for i in range(300):
            job=copy.deepcopy(self.state['phase2']['jobs'][0]);job['id']='other'+str(i);job['providerReference']='other-post'+str(i)
            job['manifest']['channelId']='other';job['verification']['at']=NOW-3600-i
            self.state['phase2']['jobs'].append(job)
        p=self.projection()
        self.assertEqual(p['coverage']['eligible'],6)
        self.assertFalse(p['coverage']['truncated'])

    def test_relative_baseline_preserves_civil_week_and_month(self):
        scope={'channelIds':['own'],'relativeDateRule':{'kind':'this_week','timezone':'America/New_York'},'comparison':{'kind':'previous_period','relativeToPublicationPeriod':True}}
        now=datetime(2026,11,8,17,tzinfo=timezone.utc).timestamp()
        context=self.review.resolve_review_context('workspace',scope,self.state,now)
        self.assertEqual(context['comparison']['publicationPeriod'],{'start':'2026-10-26T04:00:00Z','end':'2026-11-02T05:00:00Z','timezone':'America/New_York'})
        scope['relativeDateRule']={'kind':'this_month','timezone':'UTC'}
        context=self.review.resolve_review_context('workspace',scope,self.state,NOW)
        self.assertEqual(context['comparison']['publicationPeriod'],{'start':'2026-09-01T00:00:00Z','end':'2026-10-01T00:00:00Z','timezone':'UTC'})
        fixed={**scope,'relativeDateRule':None,'publicationPeriod':context['publicationPeriod'],'comparison':context['comparison']}
        self.assertEqual(self.review.resolve_review_context('workspace',fixed,self.state,NOW+40*86400)['comparison'],context['comparison'])

    def test_zero_and_null_and_invalid_values_are_separate(self):
        for i, value in enumerate((None, True, -1, float('nan'), float('inf'))):
            self.rows[2 + i * 2]['value'] = value
        evidence = self.projection()['nativeResults']
        self.assertEqual(evidence[0]['value'], 0)
        self.assertEqual(evidence[0]['valueState'], 'measured')
        self.assertTrue(all(e['value'] is None and e['reason'] for e in evidence[1:]))

    def test_strict_offset_definition_cutoff_and_identity(self):
        for key, value, reason in [('readOffset',None,'unknown_read_offset'),('readOffset','7d','wrong_horizon'),
                                    ('definitionVersion','old','definition_mismatch'),('observedAt',NOW+1,'after_cutoff'),
                                    ('nativePostId','foreign','publication_mismatch')]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.rows);self.rows[0][key]=value
                p=self.projection();self.assertIn(reason,p['coverage']['excludedByReason']);self.rows=original

    def test_duplicate_readings_count_one_publication_and_latest_failure_is_stale(self):
        self.rows.append({**self.rows[0], 'observationId': 'duplicate', 'observedAt':self.rows[0]['observedAt']+10})
        self.assertEqual(self.projection()['groups'][0]['sampleSize'],6)
        self.rows.append({**self.rows[0], 'observationId':'failed', 'value':None, 'availability':'unavailable', 'observedAt':self.rows[0]['observedAt']+20})
        p=self.projection();self.assertEqual(p['groups'][0]['sampleSize'],5)
        e=next(e for e in p['nativeResults'] if e['publicationBinding']['jobId']=='0')
        self.assertEqual(e['freshnessState'],'stale');self.assertEqual(e['value'],0)

    def test_revoked_rights_remove_value_and_source(self):
        p=self.review.project_review(self.state,self.context(),self.rows,set(),NOW)
        self.assertTrue(all(e['value'] is None and e['sourceRef'] is None for e in p['nativeResults']))
        self.assertEqual(p['groups'],[])

    def test_basis_uses_exact_readings_and_scope_digest(self):
        p=self.projection();self.rows[1]['observedAt']+=10
        self.assertEqual(p['basisDigest'],self.projection()['basisDigest'])
        self.rows[0]['ingestedAt']+=1
        self.assertNotEqual(p['basisDigest'],self.projection()['basisDigest'])
        digest=self.context()['contextDigest'];self.scope['language']='zh-Hant'
        self.assertNotEqual(digest,self.context()['contextDigest'])

    def test_zero_baseline_has_no_relative_infinity(self):
        self.scope['publicationPeriod']={'start':'2026-09-30T00:00:00Z','end':'2026-10-04T00:00:00Z','timezone':'UTC'}
        self.scope['comparison']={'kind':'previous_period','publicationPeriod':{'start':'2026-09-24T00:00:00Z','end':'2026-09-30T00:00:00Z','timezone':'UTC'}}
        for r in self.rows[6:]:r['value']=0
        c=self.projection()['comparisons'][0]
        self.assertIsNone(c['relativeChange']);self.assertEqual(c['reason'],'zero_baseline')

    def test_mixed_readings_cannot_make_a_ratio(self):
        self.assertEqual(self.review.matched_ratio(self.rows[1],self.rows[0])['value'],None)
        self.assertEqual(self.review.matched_ratio(self.rows[1],self.rows[0])['reason'],'zero_denominator')
        self.rows[0]['value']=10;self.rows[1]['observedAt']+=1
        self.assertEqual(self.review.matched_ratio(self.rows[1],self.rows[0])['reason'],'incompatible_readings')

    def test_saved_view_relative_rule_replay_and_revision_conflict(self):
        self.assertTrue(hasattr(self.review,'save_review_view'),'Saved Views must use the existing aggregate')
        body={'name':'Weekly original content','filterDefinition':{**self.scope,'publicationPeriod':None,'relativeDateRule':{'kind':'this_week','timezone':'UTC'}},'expectedRevision':0,'idempotencyKey':'view-key-001'}
        view=self.review.save_review_view(self.state,'workspace',body,'owner',NOW)
        self.assertEqual(view['revision'],1)
        self.assertEqual(view,self.review.save_review_view(self.state,'workspace',body,'owner',NOW+1))
        with self.assertRaises(AlphaError):self.review.save_review_view(self.state,'workspace',{**body,'name':'Different'},'owner',NOW)
        with self.assertRaises(AlphaError):self.review.save_review_view(self.state,'workspace',{**body,'id':view['id'],'idempotencyKey':'view-key-002','expectedRevision':0},'owner',NOW)

    def test_classification_versions_do_not_rewrite_old_membership(self):
        self.assertTrue(hasattr(self.review,'classify_content'),'Human classification is versioned')
        body={'jobId':'0','manifestDigest':self.projection()['nativeResults'][0]['publicationBinding']['manifestDigest'],
              'tags':[{'tagId':'theme-practice','kind':'theme','label':'Practice'}],'confirmed':True,'source':'human','expectedRevision':0,'idempotencyKey':'class-key-01'}
        one=self.review.classify_content(self.state,'workspace',body,'owner',NOW)
        self.assertEqual(one['version'],1)
        second={**body,'tags':[],'expectedRevision':1,'idempotencyKey':'class-key-02'}
        self.review.classify_content(self.state,'workspace',second,'owner',NOW)
        self.assertEqual(self.review._classification(self.state,'0',1)['tags'],['theme-practice'])
        self.assertEqual(self.review._classification(self.state,'0',2)['tags'],[])

    def test_ai_classification_is_a_suggestion_until_human_confirmation(self):
        self.assertTrue(hasattr(self.review,'classify_content'))
        body={'jobId':'0','manifestDigest':self.projection()['nativeResults'][0]['publicationBinding']['manifestDigest'],
              'tags':[{'tagId':'theme-practice','kind':'theme','label':'Practice'}],'confirmed':False,'source':'ai_suggestion','expectedRevision':0,'idempotencyKey':'class-ai-001'}
        suggestion=self.review.classify_content(self.state,'workspace',body,'owner',NOW)
        self.assertEqual(suggestion['status'],'suggested')
        self.assertEqual(self.review._classification(self.state,'0',999)['tags'],[])

    def test_bounded_takeaways_keep_support_counter_and_no_empty_claims(self):
        self.assertTrue(hasattr(self.review,'review_takeaways'))
        p=self.projection();items=self.review.review_takeaways(p,self.state,NOW)
        self.assertLessEqual(len(items),3);self.assertTrue(items)
        self.assertTrue(all(i['supportBindings'] and i['contextDigest']==p['contextDigest'] and i['causal'] is False for i in items))
        p['groups']=[];self.assertEqual(self.review.review_takeaways(p,self.state,NOW),[])

    def test_snapshot_is_immutable_and_notes_make_a_new_version(self):
        self.assertTrue(hasattr(self.review,'build_review_snapshot'))
        p=self.projection();original=copy.deepcopy(p)
        a=self.review.build_review_snapshot(p,self.state,['繁體中文註記'],'owner','a'*40,NOW)
        b=self.review.build_review_snapshot(p,self.state,['New note'],'owner','a'*40,NOW+1,previous=a)
        self.assertEqual(a['version'],1);self.assertEqual(b['version'],2)
        self.assertEqual(a['humanNotes'],['繁體中文註記']);self.assertNotEqual(a['payloadDigest'],b['payloadDigest'])
        self.assertEqual(p,original)
        self.assertEqual(a['resolvedContext']['publicationPeriod'],p['resolvedContext']['publicationPeriod'])
        self.assertEqual(a['timeBack']['state'],'unavailable')

    def test_exports_use_same_snapshot_and_csv_is_safe(self):
        self.assertTrue(hasattr(self.review,'format_snapshot'))
        import csv,io
        p=self.projection();s=self.review.build_review_snapshot(p,self.state,['=malicious','繁體註記,含逗號'],'owner','a'*40,NOW)
        outputs={f:self.review.format_snapshot(s,f) for f in ('markdown','csv','pdf')}
        for f,content in outputs.items():
            self.assertIn(s['snapshotId'],content['content']);self.assertIn('繁體註記',content['content'])
            self.assertEqual(content['payloadDigest'],s['payloadDigest'])
        rows=list(csv.DictReader(io.StringIO(outputs['csv']['content'])))
        self.assertEqual(rows[0]['value'],'0.0');self.assertEqual(rows[0]['valueState'],'measured')
        self.assertTrue(rows[0]['humanNotes'].startswith("'="))
        self.assertIn('observationId',rows[0]);self.assertIn('sourceRef',rows[0])

    def test_reuse_deduplicates_and_has_no_history_import_effect(self):
        self.assertTrue(hasattr(self.review,'reuse_candidates'))
        self.state['phase2']['jobs'].append(copy.deepcopy(self.state['phase2']['jobs'][0]))
        before=copy.deepcopy(self.state);r=self.review.reuse_candidates(self.state,self.projection(),NOW)
        self.assertEqual(len(r),6);self.assertEqual(self.state,before)
        self.assertTrue(all(c['state']=='content_only' and c['revision'] is not None for c in r))
        self.state['phase2']['channels'][0]['revoked']=True
        self.assertEqual(self.review.reuse_candidates(self.state,self.projection(),NOW),[])

    def test_unreviewed_personalization_withholds_accuracy_and_best_claims(self):
        self.assertTrue(hasattr(self.review,'personalization_status'))
        result=self.review.personalization_status(self.state,self.projection(),NOW)
        self.assertEqual(result['status'],'method_unavailable');self.assertIsNone(result['accuracy'])


if __name__=='__main__':unittest.main()

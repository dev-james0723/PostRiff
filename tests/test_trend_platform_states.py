"""G18 read composition: bounded offline checks and opt-in disposable PostgreSQL."""
import copy
import json
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from postriff_phase2.growth.trends import contracts, platform_states as P
from postriff_phase2.growth.trends.store import TrendStorageError


def uid(n): return str(uuid.UUID(int=n))
WID, ACTOR, TID, OTHER, RID, OTHER_RID, EDGE = [uid(n) for n in range(1,8)]
SCOPE = 'shared:g18-fixture'
NOW = '2026-09-27T12:00:00Z'
EARLIER = '2026-09-27T11:00:00Z'
END = '2026-09-27T14:00:00Z'


class ReadStore:
    def __init__(self):
        self.records={}; self.manifests={}; self.metadata={}; self.calls=[]; self.queries=[]
        self.method=('shadow',None); self.candidates=[(EDGE,)]; self.result=[]
        for n,(tid,rid,platform,cutoff) in enumerate(((TID,RID,'bluesky','2026-09-27T10:00:00Z'),(OTHER,OTHER_RID,'youtube',EARLIER))):
            payload={'trend_id':tid,'episode_id':uid(20+n),'platform_states':[{'platform':platform,
                'coverage':{'availability':'available','scope':SCOPE,'completeness':'partial' if n else 'complete_within_scope'},
                'inferred':{'stage':'rising' if n else 'emerging'},'cohort_qualified':True,'method_state':'production'}]}
            row={'scope_key':SCOPE,'object_id':rid,'receipt_id':rid,'projection_id':uid(30+n),'kind':'receipt',
                'revision':1,'available_at':cutoff,'expires_at':END if n else '2026-09-27T13:00:00Z',
                'validity':'valid','verification_state':'verified','policy':{'derive_metrics':True,'retain_derivatives':True},
                'method_bundle':{'method_id':'fixture','version':'1'},'payload':payload}
            self.records['receipt',rid]=row
            self.metadata[row['projection_id']]=(uid(40+n),cutoff)
            self.manifests[uid(40+n)]={'inputs':[{'scope_key':SCOPE,'node_id':uid(50+n)}]}
        primary=copy.deepcopy(self.records['receipt',RID]); primary.update(kind='trend',object_id=TID,projection_id=uid(60))
        self.records['trend',TID]=primary
        recipe={'edge_type':'lexical_topic_association','mode':'lexical_only','semantic_qualification':'unqualified',
            'topic_ids':[TID,OTHER],'episode_ids':[uid(20),uid(21)],'receipt_ids':[RID,OTHER_RID],
            'evidence_refs':[uid(50),uid(51)],'platforms':['bluesky','youtube'],'available_at':EARLIER}
        edge=copy.deepcopy(primary); edge.update(kind='topic_association',object_id=EDGE,projection_id=uid(70),receipt_id=None,
            verification_state='pending',payload=recipe,available_at=EARLIER)
        self.records['topic_association',EDGE]=edge
        self.metadata[uid(70)]=(uid(80),EARLIER)
        self.manifests[uid(80)]={'recipe':copy.deepcopy(recipe),'chunks':[],
            'inputs':[{'scope_key':SCOPE,'node_id':rid} for rid in (RID,OTHER_RID)]}

    @contextmanager
    def transaction(self,cursor=None): yield cursor or self
    def authorized_scopes(self,wid,actor,*,cursor):
        if (wid,actor)!=(WID,ACTOR): raise TrendStorageError('membership_denied')
        return [SCOPE]
    def get_projection(self,wid,actor,kind,oid,*,as_of,cursor):
        self.authorized_scopes(wid,actor,cursor=cursor);self.calls.append((kind,oid,as_of))
        r=self.records.get((kind,oid))
        return copy.deepcopy(r) if r and contracts.instant(r['available_at'])<=contracts.instant(as_of) else None
    def get_receipt(self,wid,actor,rid,**kw): return self.get_projection(wid,actor,'receipt',rid,**kw)
    def get_manifest(self,scope,mid,*,cursor):
        if scope!=SCOPE: raise AssertionError('scope leak')
        return copy.deepcopy(self.manifests[mid])
    def execute(self,sql,args=()):
        self.queries.append((sql,args)); q=' '.join(sql.split())
        if 'pg_advisory_xact_lock_shared' in q: self.result=[]
        elif q.startswith('SELECT manifest_id::text,decision_cutoff'): self.result=[self.metadata[args[1]]]
        elif q.startswith('SELECT qualification,revoked_at'): self.result=[self.method]
        elif q.startswith('SELECT p.object_id::text'):
            self.assert_candidate_query(q,args)
            self.result=copy.deepcopy(self.candidates[:args[-1]])
        else: raise AssertionError('unexpected SQL: '+q)
    def assert_candidate_query(self,q,args):
        assert "kind='topic_association'" in q and "payload->'topic_ids' @>" in q
        assert args[0]==[SCOPE] and json.loads(args[1])==[TID] and args[2]==args[3]
    def fetchone(self): return self.result.pop(0) if self.result else None
    def fetchall(self): r,self.result=self.result,[]; return r


class PlatformStatesTests(unittest.TestCase):
    def setUp(self):
        self.store=ReadStore()
        for target in ('socket.socket','socket.create_connection','urllib.request.urlopen'):
            p=patch(target,side_effect=AssertionError('no egress'));p.start();self.addCleanup(p.stop)
        p=patch.object(P,'utcnow',return_value=NOW);p.start();self.addCleanup(p.stop)
    def read(self,**kw): return P.related_platform_states(self.store,workspace_id=WID,actor_id=ACTOR,trend_id=TID,**kw)
    def test_independent_exact_receipts_common_read_cutoff_and_earliest_expiry(self):
        before=copy.deepcopy(self.store.records); result=self.read()
        self.assertEqual([r['platform'] for r in result['platform_states']],['bluesky','youtube'])
        self.assertEqual([r['trust_receipt_id'] for r in result['snapshots']],[RID,OTHER_RID])
        self.assertNotEqual(result['snapshots'][0]['decision_cutoff'],result['snapshots'][1]['decision_cutoff'])
        self.assertEqual(result['expires_at'],'2026-09-27T13:00:00Z')
        self.assertEqual(len({call[2] for call in self.store.calls}),1)
        self.assertNotIn(('trend',OTHER),[(k,i) for k,i,_ in self.store.calls])
        self.assertEqual(before,self.store.records)
        self.assertNotIn('stage',result)
        self.assertEqual(result['platform_states'][1]['coverage']['completeness'],'partial')
    def test_stored_qualification_booleans_and_method_alone_cannot_qualify_stages(self):
        self.store.method=('qualified',None)
        result=self.read()
        self.assertTrue(all(r['inferred']['stage'] is None for r in result['platform_states']))
        self.assertTrue(all(r['cohort_qualified'] is False for r in result['snapshots']))
        self.assertTrue(all(r['method_state']=='production' for r in result['snapshots']))
    def test_source_loss_invalidates_related_receipt_even_at_historical_asof(self):
        for change in ({'validity':'revoked'},{'verification_state':'pending'},{'policy':{'derive_metrics':False,'retain_derivatives':True}},
                       {'expires_at':'2026-09-27T11:59:59Z'}):
            with self.subTest(change=change):
                self.store=ReadStore();self.store.records['receipt',OTHER_RID].update(change)
                self.assertEqual(len(self.read(as_of='2026-09-27T11:30:00Z')['platform_states']),1)
    def test_primary_loss_denies_instead_of_leaking_relationship(self):
        self.store.records['receipt',RID]['validity']='deleted'
        with self.assertRaises(TrendStorageError): self.read()
    def test_unauthorized_tenant_denies(self):
        with self.assertRaises(TrendStorageError):
            P.related_platform_states(self.store,workspace_id=OTHER,actor_id=ACTOR,trend_id=TID)
    def test_manifest_receipt_nodes_and_plain_recipe_are_exact(self):
        for field,value in (('inputs',[{'scope_key':SCOPE,'node_id':uid(30)}]),('recipe',{}),('chunks',[{}])):
            with self.subTest(field=field):
                self.store=ReadStore();self.store.manifests[uid(80)][field]=value
                self.assertEqual(len(self.read()['platform_states']),1)
    def test_future_cutoff_and_future_related_receipt_are_excluded(self):
        with self.assertRaisesRegex(ValueError,'future'): self.read(as_of=END)
        self.store.records['receipt',OTHER_RID]['available_at']=END
        self.assertEqual(len(self.read()['platform_states']),1)
    def test_mismatched_topic_episode_platform_and_evidence_abstain(self):
        for key,value in (('trend_id',uid(99)),('episode_id',uid(99))):
            with self.subTest(key=key):
                self.store=ReadStore();self.store.records['receipt',OTHER_RID]['payload'][key]=value
                self.assertEqual(len(self.read()['platform_states']),1)
        self.store=ReadStore();self.store.manifests[uid(41)]['inputs']=[]
        self.assertEqual(len(self.read()['platform_states']),1)
    def anchored_related(self):
        original=self.store.manifests[uid(41)]['inputs']
        descriptors=[]
        for kind,mid,inputs in (('source',uid(91),original),('membership',uid(92),[{'scope_key':SCOPE,'node_id':uid(93)}])):
            recipe={'schema':'rafii.trend-dependency-anchor.v1','kind':kind,'input_digest':contracts.digest(inputs)}
            descriptors.append({'manifest_id':mid,**recipe})
            self.store.manifests[mid]={'inputs':copy.deepcopy(inputs),'recipe':recipe,'document_digest':recipe['input_digest'],
                'decision_cutoff':'2026-09-27T10:30:00Z','chunks':[]}
        self.store.manifests[uid(41)]={'recipe':{'dependency_anchors':descriptors},
            'inputs':[{'scope_key':SCOPE,'node_id':a['manifest_id']} for a in descriptors]}

    def test_bounded_receipt_source_membership_anchors_preserve_exact_lineage(self):
        self.anchored_related()
        self.assertEqual(len(self.read()['platform_states']),2)
        for mutation in ('digest','root','cutoff','missing','oversized'):
            with self.subTest(mutation=mutation):
                self.store=ReadStore();self.anchored_related()
                if mutation=='digest':self.store.manifests[uid(91)]['document_digest']='0'*64
                if mutation=='root':self.store.manifests[uid(41)]['inputs'][0]['node_id']=uid(999)
                if mutation=='cutoff':self.store.manifests[uid(91)]['decision_cutoff']=END
                if mutation=='missing':del self.store.manifests[uid(91)]
                if mutation=='oversized':self.store.manifests[uid(91)]['inputs']*=1001
                self.assertEqual(len(self.read()['platform_states']),1)

    def test_current_method_withdrawal_and_stale_primary_binding_abstain(self):
        self.store.method=('withdrawn',None)
        with self.assertRaises(TrendStorageError): self.read()
        self.store=ReadStore();self.store.records['topic_association',EDGE]['payload']['receipt_ids']=[OTHER_RID,uid(90)]
        self.assertEqual(len(self.read()['platform_states']),1)
    def test_bounded_page_is_reported_and_performs_only_selects(self):
        self.store.candidates=[(EDGE,)]*3
        result=self.read(limit=2);self.assertTrue(result['truncated'])
        self.assertEqual(len(result['platform_states']),2)
        self.assertTrue(all(q.lstrip().startswith('SELECT ') for q,_ in self.store.queries))
        for invalid in (0,21,True):
            with self.assertRaises(ValueError): self.read(limit=invalid)


# Reuse only fixture setup; do not inherit/re-run its notification test methods.
import test_trend_notifications as notification_fixture

class PlatformStatesPostgres(unittest.TestCase):
    setUpClass=classmethod(notification_fixture.NotificationPostgres.setUpClass.__func__)
    setUp=notification_fixture.NotificationPostgres.setUp
    ingest=notification_fixture.NotificationPostgres.ingest
    put_opportunity=notification_fixture.NotificationPostgres.put_opportunity

    def related_source(self):
        from postriff_phase2.growth.trends.store import utcnow
        with self.connect() as db:
            source=db.execute('SELECT payload,rights,event_at FROM pr_trend_observations WHERE observation_id=%s',(self.sources[0],)).fetchone()
        self.related_provider='g18-secondary-'+uuid.uuid4().hex[:10]
        self.store.register_contract(self.related_provider,'1',list(contracts.PERMISSIONS),opportunities.iso(self.at-3600),self.end)
        self.store.register_policy({'scope_key':self.scope,'provider_id':self.related_provider,'version':'1','rights':source[1],
            'effective_at':opportunities.iso(self.at-3600),'expires_at':self.end,'retention_seconds':7200,'readiness':'ready'},provider_contract_version='1')
        payload={**source[0],'platform':'youtube','native_id':'related-native','author_key':'related-author'}
        identity=str(uuid.uuid4())
        self.store.put_observation({'schema_version':contracts.SCHEMA_VERSION,'observation_id':identity,'scope_key':self.scope,
            'provider_id':self.related_provider,'provider_contract_version':'1','source_policy_version':'1','source_identity':'g18-related-source',
            'revision_identity':'r1','revision_sequence':1,'kind':'raw_post','operation':'create','event_at':contracts.iso(source[2]),
            'received_at':utcnow(),'available_at':utcnow(),'time_basis':'provider_event','coverage_epoch':'notification-fixture',
            'provenance':{'access_method':'synthetic'},'retention_until':self.end,'rights':source[1],
            'deletion_key':'g18-related-source','payload':payload,'payload_digest':contracts.digest(payload)})
        primary_provider,self.provider=self.provider,self.related_provider
        self.sources=[identity]
        second=self.ingest('partial')
        self.provider=primary_provider
        return second

    def read(self,**kw):
        return P.related_platform_states(self.store,workspace_id=self.wid,actor_id=self.actor,trend_id=self.tid,**kw)

    def test_real_pipeline_receipt_dag_compose_then_source_loss_and_tenant_isolation(self):
        from postriff_phase2.growth.trends.store import utcnow
        from postriff_phase2.growth.trends.revocation import revoke_source
        second=self.related_source();cutoff=utcnow();result=self.read(as_of=cutoff)
        self.assertEqual([r['platform'] for r in result['platform_states']],['bluesky','youtube'])
        self.assertEqual(result['snapshots'][1]['trust_receipt_id'],second['receipt_id'])
        self.assertNotEqual(result['snapshots'][0]['decision_cutoff'],result['snapshots'][1]['decision_cutoff'])
        self.assertTrue(all(r['inferred']['stage'] is None for r in result['platform_states']))
        self.assertTrue(all(r['verification_state']=='verified' for r in result['snapshots']))
        self.assertEqual(len(self.read(as_of=self.trend['available_at'])['platform_states']),1)
        with self.assertRaises(TrendStorageError):
            P.related_platform_states(self.store,workspace_id=self.foreign_wid,actor_id=self.foreign_actor,trend_id=self.tid)
        revoke_source(self.store,self.scope,self.related_provider,'g18-related-source')
        self.assertEqual(len(self.read(as_of=cutoff)['platform_states']),1)

    def test_real_plain_manifest_mismatch_omits_link(self):
        self.related_source();self.assertEqual(len(self.read()['platform_states']),2)
        with self.connect() as db:
            db.execute("UPDATE pr_trend_projections SET payload=jsonb_set(payload,'{semantic_qualification}','\"qualified\"') WHERE scope_key=%s AND kind='topic_association'",(self.scope,))
        self.assertEqual(len(self.read()['platform_states']),1)

from postriff_phase2.growth.trends import opportunities

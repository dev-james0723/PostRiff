"""Runtime privacy integration: offline contracts and isolated real SQL only."""
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from postriff_phase2.growth.trends import analytics_runtime, frontier_runtime as runtime, revocation
from postriff_phase2.growth.trends.contracts import ContractError
from test_trend_frontier import FrontierSQL


class FrontierRuntimeOffline(unittest.TestCase):
    def test_bounds_and_invalid_cursor_fail_closed(self):
        store=Mock()
        for bound in (True,0,101,1.5):
            with self.subTest(bound=bound), self.assertRaises(ContractError): runtime.maintenance(store,limit=bound)
        store.transaction.assert_not_called()
        for cursor in (None,[],{'after':['not','key']},{'after':'private query text'},
                       {'after':None,'permission':'allow'},{'after':'shared:scope|frontier-request:wrong'}):
            with self.subTest(cursor=cursor), self.assertRaises(ContractError): runtime._after(cursor)
        self.assertIsNone(runtime._after({}))
        self.assertIsNone(runtime._after({'after':None}))

    def test_helper_receives_same_transaction_and_current_cursor(self):
        store=Mock();cur=Mock();cur.description=[]
        @contextmanager
        def transaction(cursor=None): yield cursor or cur
        store.transaction=transaction
        key='shared:synthetic|frontier-request:'+'a'*64
        cur.fetchone.side_effect=[{'locked':True},{'reads_ready':True},{'present':True},
                                  {'cursor_value':{'after':key},'generation':7}]
        with patch.object(runtime.DiscoveryFrontier,'maintenance',return_value={'status':'ok','cancelled':2,'next_key':None}) as helper:
            result=runtime.maintenance(store,limit=3)
        helper.assert_called_once_with(limit=3,after=key,cursor=cur)
        self.assertEqual(result['cursor_generation'],8)
        store.ensure_scope.assert_called_once_with(runtime.SCOPE,cursor=cur)
        update=cur.execute.call_args.args
        self.assertIn('generation=generation+1',update[0])
        self.assertEqual(json.loads(update[1][0]),{'after':None})

    def test_lock_restore_and_idle_do_not_create_scope_or_call_helper(self):
        for values,status in (([{'locked':False}],'busy'),
                              ([{'locked':True},{'reads_ready':False}],'restore_deferred'),
                              ([{'locked':True},None],'restore_deferred'),
                              ([{'locked':True},{'reads_ready':True},{'present':False}],'idle')):
            store=Mock();cur=Mock();cur.description=[];cur.fetchone.side_effect=values
            @contextmanager
            def transaction(): yield cur
            store.transaction=transaction
            with patch.object(runtime.DiscoveryFrontier,'maintenance') as helper:
                self.assertEqual(runtime.maintenance(store)['status'],status)
                helper.assert_not_called()
            store.ensure_scope.assert_not_called()
            self.assertFalse(any('INSERT' in c.args[0] or 'UPDATE' in c.args[0] for c in cur.execute.call_args_list))


@unittest.skipUnless(os.environ.get('TREND_SERVICE_TEST_DSN'),'explicit isolated SQL fixture required')
class FrontierRuntimeSQL(unittest.TestCase):
    def setUp(self):
        self.f=FrontierSQL();self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def event(self):
        return self.f.admitted(self.f.produce([self.f.proposal()]))

    def cursor(self):
        return self.f.fetch('SELECT cursor_value,generation FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',
                            (runtime.SCOPE,runtime.PROVIDER,runtime.PARTITION))

    def seed_cursor(self, after=None, generation=37):
        self.f.store.ensure_scope(runtime.SCOPE)
        after=after or self.f.scope+'|frontier-allocation:'+'0'*64
        with self.f.connect() as db:
            db.execute('''INSERT INTO pr_trend_provider_cursors(scope_key,provider_id,partition_key,cursor_value,generation)
                VALUES(%s,%s,%s,%s::jsonb,%s) ON CONFLICT(scope_key,provider_id,partition_key)
                DO UPDATE SET cursor_value=excluded.cursor_value,generation=excluded.generation''',
                (runtime.SCOPE,runtime.PROVIDER,runtime.PARTITION,json.dumps({'after':after}),generation))
        return after

    def test_untouched_frontier_does_not_write_scope_cursor_or_legal_authority(self):
        # Rollback-only view makes this check independent of prior tests' rows.
        with self.f.connect() as db, db.transaction(force_rollback=True), db.cursor() as cur:
            cur.execute("UPDATE pr_trend_outbox SET payload='{}' WHERE event_type=%s",(runtime.EVENT,))
            tables=('pr_trend_scopes','pr_trend_provider_cursors','pr_trend_provider_contracts','pr_trend_source_policies','pr_trend_entitlements')
            def footprint():
                result=[]
                for name in tables:
                    cur.execute('SELECT count(*) FROM '+name);result.append(cur.fetchone()[0])
                return result
            before=footprint()
            @contextmanager
            def transaction(cursor=None): yield cursor or cur
            with patch.object(self.f.store,'transaction',transaction):
                self.assertEqual(runtime.maintenance(self.f.store)['status'],'idle')
            self.assertEqual(footprint(),before)

    def test_atomic_cleanup_and_cursor_rollback_on_helper_failure(self):
        d=self.event();after=self.seed_cursor()
        revocation.revoke_author(self.f.store,self.f.provider,'author-0')
        original=runtime.DiscoveryFrontier.maintenance
        def fail_after_cleanup(instance,**kwargs):
            result=original(instance,**kwargs)
            self.assertGreaterEqual(result['cancelled'],1)
            raise RuntimeError('synthetic failure before cursor commit')
        with patch.object(runtime.DiscoveryFrontier,'maintenance',fail_after_cleanup):
            with self.assertRaisesRegex(RuntimeError,'synthetic failure'): runtime.maintenance(self.f.store,limit=25)
        self.assertEqual(self.cursor(),({'after':after},37))
        self.assertEqual(self.f.job(d['job_id'])['state'],'queued')
        self.assertTrue(self.f.job(d['job_id'])['payload'])
        runtime.maintenance(self.f.store,limit=25)
        self.assertEqual(self.f.job(d['job_id'])['payload'],{})
        self.assertEqual(self.cursor()[1],38)

    def test_cursor_corruption_rolls_back_without_skipping_privacy_records(self):
        d=self.event();self.seed_cursor()
        with self.f.connect() as db:
            db.execute("UPDATE pr_trend_provider_cursors SET cursor_value='{\"after\":\"untrusted query\"}' WHERE scope_key=%s AND provider_id=%s AND partition_key=%s",(runtime.SCOPE,runtime.PROVIDER,runtime.PARTITION))
        with self.assertRaises(ContractError): runtime.maintenance(self.f.store)
        self.assertEqual(self.cursor()[1],37)
        self.assertEqual(self.f.job(d['job_id'])['state'],'queued')

    def test_advisory_contention_does_not_advance_or_cancel(self):
        d=self.event();after=self.seed_cursor()
        with self.f.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(runtime.LOCK,))
            self.assertEqual(runtime.maintenance(self.f.store)['status'],'busy')
        self.assertEqual(self.cursor(),({'after':after},37))
        self.assertEqual(self.f.job(d['job_id'])['state'],'queued')

    def test_restore_guard_preserves_existing_cursor_and_pending_query(self):
        d=self.event();after=self.seed_cursor()
        revocation.begin_restore(self.f.store)
        try:
            self.assertEqual(runtime.maintenance(self.f.store)['status'],'restore_deferred')
            self.assertEqual(self.cursor(),({'after':after},37))
            self.assertEqual(self.f.job(d['job_id'])['state'],'queued')
        finally:
            with self.f.connect() as db: db.execute('UPDATE pr_trend_runtime_guard SET reads_ready=true WHERE singleton')

    def test_valid_events_do_not_starve_deleted_query_and_parent_purges_after_cleanup(self):
        d=self.event();self.seed_cursor()
        identity=self.f.fetch('SELECT source_identity FROM pr_trend_observations WHERE scope_key=%s AND observation_id=%s',
                             (self.f.scope,self.f.sources[0]))[0]
        revocation.revoke_source(self.f.store,self.f.scope,self.f.provider,identity)
        first=runtime.maintenance(self.f.store,limit=1)
        self.assertEqual(first['cancelled'],0)  # Valid allocation is the first key.
        self.assertIsNotNone(first['next_key'])
        for _ in range(10):
            result=runtime.maintenance(self.f.store,limit=1)
            # This is the exact parent composition, including actual canonical SQL.
            analytics_runtime.maintain(self.f.store,limit=25)
            payload=self.f.fetch('SELECT payload FROM pr_trend_outbox WHERE scope_key=%s AND event_key=%s',
                                 (self.f.scope,'frontier-request:'+d['request_id']))[0]
            if self.f.job(d['job_id'])['payload']=={} and payload=={}: break
        self.assertEqual(self.f.job(d['job_id'])['payload'],{})
        self.assertEqual(payload,{})
        self.assertGreater(self.cursor()[1],38)

    def test_exhausted_scan_wraps_durably_then_visits_earlier_keys(self):
        self.event()
        self.seed_cursor('shared:zzzzzz|frontier-request:'+'f'*64)
        # Workspace scope keys sort after shared keys, so use the maximum UUID.
        self.seed_cursor('workspace:ffffffff-ffff-ffff-ffff-ffffffffffff|frontier-request:'+'f'*64)
        result=runtime.maintenance(self.f.store,limit=1)
        self.assertIsNone(result['next_key'])
        self.assertEqual(self.cursor(),({'after':None},38))
        result=runtime.maintenance(self.f.store,limit=1)
        self.assertIsNotNone(result['next_key'])
        self.assertEqual(self.cursor()[1],39)

    def test_flags_and_health_pause_are_not_rights_revocation(self):
        d=self.event();self.seed_cursor()
        with self.f.connect() as db:
            db.execute("INSERT INTO pr_trend_source_health(scope_key,provider_id,status,observed_at,next_allowed_at,notes_code) VALUES(%s,%s,'unavailable',%s,%s,'synthetic_pause')",(self.f.scope,self.f.provider,self.f.at,self.f.end))
        with patch.dict(os.environ,{'RAFII_TREND_INTELLIGENCE_ENABLED':'0','RAFII_TREND_RADAR_ENABLED':'0'},clear=True):
            result=runtime.maintenance(self.f.store,limit=25)
        self.assertEqual(self.f.job(d['job_id'])['state'],'queued')
        self.assertTrue(self.f.job(d['job_id'])['payload'])
        self.assertEqual(result['status'],'ok')

    def test_unknown_permission_and_contract_revocation_cleanup_without_new_grants(self):
        d=self.event();self.seed_cursor()
        before=[self.f.fetch('SELECT count(*) FROM '+table)[0] for table in
                ('pr_trend_provider_contracts','pr_trend_source_policies','pr_trend_entitlements')]
        with self.f.connect() as db:
            db.execute("UPDATE pr_trend_source_policies SET rights=jsonb_set(rights,'{retain_derivatives,state}','\"unknown\"') WHERE scope_key=%s AND provider_id=%s",(self.f.scope,self.f.provider))
            db.execute('UPDATE pr_trend_provider_contracts SET revoked_at=clock_timestamp() WHERE provider_id=%s',(self.f.provider,))
        runtime.maintenance(self.f.store,limit=25)
        self.assertEqual(self.f.job(d['job_id'])['payload'],{})
        after=[self.f.fetch('SELECT count(*) FROM '+table)[0] for table in
               ('pr_trend_provider_contracts','pr_trend_source_policies','pr_trend_entitlements')]
        self.assertEqual(before,after)

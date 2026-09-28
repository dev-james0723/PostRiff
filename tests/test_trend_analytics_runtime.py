import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from postriff_phase2.growth.trends import analytics_runtime as runtime
from test_trend_service import WID,ACTOR,RID


class RuntimeTests(unittest.TestCase):
    def test_off_never_reads_policy_and_ambiguous_authority_never_records(self):
        cur=Mock();store=Mock()
        self.assertEqual(runtime.record(store,cur,WID,ACTOR,RID,values={})['status'],'disabled')
        cur.execute.assert_not_called()
        values={'RAFII_TREND_ANALYTICS_RETENTION_ENABLED':'1','RAFII_TREND_INTELLIGENCE_ENABLED':'1','RAFII_TREND_WORKSPACE_ALLOWLIST':WID}
        cur.fetchall.return_value=[('one','1'),('two','2')]
        with patch.object(runtime.analytics_retention,'retain_exposure') as record:
            self.assertEqual(runtime.record(store,cur,WID,ACTOR,RID,values=values)['status'],'unavailable')
            record.assert_not_called()
            cur.fetchall.return_value=[('reviewed','v2')]
            runtime.record(store,cur,WID,ACTOR,RID,values=values)
            record.assert_called_once_with(store,cur,WID,ACTOR,RID,authority={'provider_id':'reviewed','policy_version':'v2'},enabled=True)

    def test_cleanup_persists_full_keyset_then_wraps_even_without_recording_flags(self):
        cur=Mock();store=Mock()
        @contextmanager
        def transaction(): yield cur
        store.transaction=transaction
        key=['2026-09-29T00:00:00Z','workspace:'+WID,RID]
        for saved,next_key in (({},key),({'after':key},None)):
            cur.fetchone.side_effect=[(True,),(True,),(saved,)]
            with patch.object(runtime.analytics_retention,'sweep',return_value={'next_key':next_key}) as sweep:
                runtime.maintain(store,limit=5)
                sweep.assert_called_once_with(store,limit=5,after=saved.get('after'),cursor=cur)
                update=cur.execute.call_args.args
                self.assertIn('generation=generation+1',update[0])
                import json
                self.assertEqual(json.loads(update[1][0]),{'after':next_key})

    def test_restore_guard_defers_cursor_and_no_rows_runs_canonical_sweep(self):
        cur=Mock();store=Mock()
        @contextmanager
        def transaction(): yield cur
        store.transaction=transaction
        cur.fetchone.side_effect=[(True,),(True,),({},)]
        with patch.object(runtime.analytics_retention,'sweep',return_value={'deferred':'restore_in_progress'}):
            self.assertEqual(runtime.maintain(store)['deferred'],'restore_in_progress')
        self.assertFalse(any('UPDATE public.pr_trend_provider_cursors' in c.args[0] for c in cur.execute.call_args_list))
        cur.fetchone.side_effect=[(True,),(False,)]
        with patch.object(runtime.retention,'sweep',return_value={'deleted':0}) as sweep:
            self.assertEqual(runtime.maintain(store)['checked'],0)
            sweep.assert_called_once_with(store,limit=100,cursor=cur)


@unittest.skipUnless(os.environ.get('TREND_SERVICE_TEST_DSN'),'explicit disposable PostgreSQL required')
class RuntimeSQL(unittest.TestCase):
    def test_record_authority_and_durable_cleanup_against_real_sql(self):
        from test_trend_analytics_retention import AnalyticsRetentionSQL
        fixture=AnalyticsRetentionSQL();fixture.setUp()
        try:
            authority=fixture.authority()
            values={'RAFII_TREND_ANALYTICS_RETENTION_ENABLED':'1','RAFII_TREND_INTELLIGENCE_ENABLED':'1',
                    'RAFII_TREND_WORKSPACE_ALLOWLIST':fixture.wid}
            with fixture.connect() as db,db.cursor() as cur:
                result=runtime.record(fixture.store,cur,fixture.wid,fixture.actor,fixture.eid,values=values)
            self.assertEqual(result['status'],'available')
            with fixture.connect() as db:
                db.execute('UPDATE pr_trend_source_policies SET revoked_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s AND version=%s',
                    (fixture.scope,fixture.raw[1],fixture.raw[3]))
            suppressed=0
            for _ in range(100):
                one=runtime.maintain(fixture.store,limit=1)
                suppressed+=one.get('suppressed',0)
                with fixture.connect() as db:
                    remaining=db.execute('SELECT payload FROM pr_trend_projections WHERE scope_key=%s AND object_id=%s',
                        (fixture.scope,result['object_id'])).fetchone()[0]
                if remaining=={}:break
            self.assertGreaterEqual(suppressed,1)
            self.assertEqual(remaining,{})
            with fixture.connect() as db:
                saved=db.execute('SELECT cursor_value FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',
                    (runtime.SCOPE,runtime.PROVIDER,runtime.PARTITION)).fetchone()
            self.assertIn('after',saved[0])
            self.assertEqual(fixture.read(result['object_id'])['status'],'unavailable')
        finally:
            # This fixture owns no process/cluster and its DB is disposable.
            pass

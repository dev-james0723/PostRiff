import tempfile
import unittest
from pathlib import Path
from agent_team.collector import collect_once,from_observation,coverage_event,coverage_from_journal
from agent_team.events import Journal
from agent_team.observers import SourceObservation,ObservationBatch


class CollectorTests(unittest.TestCase):
    scan_at='2026-10-05T15:02:00Z'
    start_at='2026-10-05T14:32:00Z'

    def item(self):
        return SourceObservation('typeless','private record','a'*64,'history_record','2026-10-05T15:00:00Z','2026-10-05T15:01:00Z','2026-10-05T15:02:00Z',{}, {'audio_path':'/private/secret.wav'}, {'text_length':20,'text_hash':'b'*64},'secret private transcript')

    def test_projection_does_not_upload_private_content(self):
        e=from_observation(self.item());raw=str(e.cloud())
        self.assertNotIn('secret',raw);self.assertNotIn('private record',raw)
        self.assertEqual(e.payload['textLength'],20)

    def test_repeated_scan_is_idempotent_and_never_claims_daily_coverage(self):
        item=self.item()
        class Adapter:
            def poll(self,**kwargs):return ObservationBatch('ok',(item,),{'updated_at':'2026-10-05T15:01:00Z','source_id':'private record'},(),1,True)
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'journal.db')
            for _ in range(2):result=collect_once(j,'2026-10-05T15:02:00Z',typeless_observer=Adapter())
            self.assertEqual(sum(x['source']=='typeless' for x in j.all()),1)
            self.assertFalse(result['sources']['typeless']['dailyCoverageComplete']);j.close()

    def test_failed_scan_keeps_receipt_time_but_has_unknown_source_freshness(self):
        for status in ('unavailable','error','not_connected'):
            with self.subTest(status=status):
                # A failure must not become complete through the batch default.
                batch=ObservationBatch(status,gaps=('source_query_failed',))
                event=coverage_event('typeless',batch,self.scan_at,self.start_at,self.scan_at)
                self.assertNotIn('sourceFreshAt',event.payload)
                self.assertIn('source_freshness_unknown',event.payload['gaps'])
                coverage=coverage_from_journal([event.cloud()])['typeless']
                self.assertEqual(coverage['status'],status)
                self.assertIsNone(coverage['freshAt'])
                self.assertEqual(coverage['scannedAt'],self.scan_at)
                self.assertFalse(coverage['complete'])

    def test_successful_empty_scan_watermark_is_not_daily_or_activity_coverage(self):
        batch=ObservationBatch('ok')
        event=coverage_event('luci',batch,self.scan_at,self.start_at,self.scan_at)
        coverage=coverage_from_journal([event.cloud()])['luci']
        self.assertEqual(coverage['freshAt'],self.scan_at)
        self.assertEqual(coverage['scannedAt'],self.scan_at)
        self.assertEqual(event.payload['count'],0)
        self.assertFalse(coverage['complete'])
        self.assertIn('bounded_scan_only',coverage['gaps'])
        legacy=event.cloud();legacy['payload']['scanComplete']=True
        self.assertFalse(coverage_from_journal([legacy])['luci']['complete'])

    def test_unfinished_or_gapped_scan_does_not_claim_query_watermark(self):
        for batch in (ObservationBatch('partial',complete=False),
                      ObservationBatch('partial',gaps=('record_app_version_unknown',)),
                      ObservationBatch('ok',complete=False),
                      ObservationBatch('ok',gaps=('record_app_version_unknown',))):
            with self.subTest(batch=batch):
                event=coverage_event('typeless',batch,self.scan_at,self.start_at,self.scan_at)
                self.assertNotIn('sourceFreshAt',event.payload)
                self.assertIsNone(coverage_from_journal([event.cloud()])['typeless']['freshAt'])

    def test_legacy_failed_watermark_is_ignored_and_missing_watermark_is_safe(self):
        event=coverage_event('typeless',ObservationBatch('ok'),self.scan_at,self.start_at,self.scan_at).cloud()
        event['payload'].update(sourceStatus='unavailable',scanComplete=True,gaps=[])
        coverage=coverage_from_journal([event])['typeless']
        self.assertIsNone(coverage['freshAt'])
        self.assertFalse(coverage['complete'])
        del event['payload']['sourceFreshAt']
        self.assertIsNone(coverage_from_journal([event])['typeless']['freshAt'])
        event['payload']['sourceStatus']='ok'
        self.assertIsNone(coverage_from_journal([event])['typeless']['freshAt'])

    def test_failed_later_page_preserves_status_prior_rows_and_cursor(self):
        item=self.item()
        cursor={'updated_at':'2026-10-05T15:01:00Z','source_id':'private record'}
        for status in ('unavailable','error'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
                class Adapter:
                    calls=0
                    def poll(self,**kwargs):
                        self.calls+=1
                        if self.calls==1:
                            return ObservationBatch('partial',(item,),cursor,('page_remaining',),1,False)
                        return ObservationBatch(status,cursor=cursor,gaps=('source_query_failed',))
                adapter=Adapter();j=Journal(Path(d)/'journal.db')
                try:
                    result=collect_once(j,self.scan_at,typeless_observer=adapter)
                    source=result['sources']['typeless']
                    self.assertEqual(adapter.calls,2)
                    self.assertEqual(source['status'],status)
                    self.assertEqual(source['observations'],1)
                    self.assertFalse(source['boundedScanComplete'])
                    self.assertFalse(source['dailyCoverageComplete'])
                    self.assertEqual(j.cursor('typeless'),cursor)
                    coverage=coverage_from_journal(j.all())['typeless']
                    self.assertIsNone(coverage['freshAt'])
                    self.assertEqual(coverage['scannedAt'],result['observedAt'])
                finally:j.close()

    def test_missing_activity_timestamp_does_not_use_receipt_as_freshness(self):
        item=SourceObservation('luci','record','a'*64,'capture',None,None,self.scan_at)
        event=from_observation(item)
        self.assertNotIn('sourceFreshAt',event.payload)
        self.assertEqual(event.happened_at,self.scan_at)
        event.cloud()

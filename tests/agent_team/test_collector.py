import tempfile
import unittest
from pathlib import Path
from agent_team.collector import collect_once,from_observation
from agent_team.events import Journal
from agent_team.observers import SourceObservation,ObservationBatch


class CollectorTests(unittest.TestCase):
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

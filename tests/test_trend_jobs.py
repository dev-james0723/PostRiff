"""Offline job admission contracts; no provider, network or database access."""
import unittest
import uuid
from postriff_phase2.growth.trends.jobs import micro_usd, partition_key, validate_job_controls
from postriff_phase2.growth.trends.outbox import ingestion_payload
from postriff_phase2.growth.trends.store import TrendStorageError, bounded_json, aggregate_payload


class TrendJobContracts(unittest.TestCase):
    def test_microdollars_reject_float_bool_negative_overflow(self):
        for amount in (True,False,1.1,-1,2**63,'10',None):
            with self.subTest(amount=amount), self.assertRaises(TrendStorageError):
                micro_usd(amount)
        self.assertEqual(micro_usd(0),0)
        self.assertEqual(micro_usd(2**63-1),2**63-1)

    def test_cursor_partition_binds_instance_protocol_and_query(self):
        values={'instance_id':'social.example','protocol_version':'v2','filter_digest':'abc'}
        first=partition_key(**values)
        for key in values:
            self.assertNotEqual(first,partition_key(**{**values,key:values[key]+'-changed'}))
        self.assertEqual(first,partition_key(**values))
        with self.assertRaises(TrendStorageError):
            partition_key(instance_id='',protocol_version='v2',filter_digest='abc')

    def test_payload_rejects_nonfinite_and_oversized_provider_data(self):
        for value in ({'x':float('nan')},{'x':float('inf')},{'x':'x'*70000}):
            with self.assertRaises(ValueError):
                bounded_json(value)

    def test_aggregate_display_boundary_rejects_nested_excerpt_and_link(self):
        source={'metrics':{'mention_rate':{'value':2,'unit':'posts/hour','text':'private source'},'private source':3},
                'coverage':{'availability':'available','notes':'private excerpt','url':'https://private.invalid'},
                'observed':{'qualifying_original_count':2,'known_creator_count':'private creator'}}
        self.assertEqual(aggregate_payload(source),{'metrics':{'mention_rate':{'value':2,'unit':'posts/hour'}},
            'coverage':{'availability':'available'},'observed':{'qualifying_original_count':2}})

    def test_job_controls_cannot_be_a_second_raw_source_store(self):
        for value in ({'observations':[]},{'filter':{'did':'did:fixture:account'}},{'text':'raw source'}):
            with self.assertRaises(TrendStorageError):
                validate_job_controls(value)
        validate_job_controls({'operation':'sample','max_items':10,'observation_ids':['opaque-ref']})

    def test_ingestion_markers_keep_counts_without_account_identity(self):
        result=ingestion_payload({'markers':[{'kind':'account','did':'did:fixture:account','active':False},
            {'kind':'sync','did':'did:fixture:account','text':'raw'}],'text':'raw','author_key':'did:fixture:account'})
        self.assertEqual(result,{'marker_counts':{'account':1,'sync':1}})

    def test_continuation_indices_preserve_bounded_root_context(self):
        ids=[str(uuid.uuid4()) for _ in range(1000)]
        payload={'observation_ids':ids,'pending_observation_indices':list(range(100,1000))}
        self.assertEqual(ingestion_payload(payload),payload)
        bounded_json(ingestion_payload(payload))
        self.assertEqual(ingestion_payload({'observation_ids':[],'pending_observation_indices':[]}),
            {'observation_ids':[],'pending_observation_indices':[]})

    def test_continuation_indices_reject_ambiguous_or_unbounded_controls(self):
        ids=[str(uuid.uuid4()),str(uuid.uuid4())]
        for pending in ([True],[1.0],['1'],[-1],[2],[0,0],[0,1,0],None,{},(0,),[[]]):
            with self.subTest(pending=pending), self.assertRaises(TrendStorageError):
                ingestion_payload({'observation_ids':ids,'pending_observation_indices':pending})
        with self.assertRaises(TrendStorageError):
            ingestion_payload({'pending_observation_indices':[]})


if __name__=='__main__':
    unittest.main()

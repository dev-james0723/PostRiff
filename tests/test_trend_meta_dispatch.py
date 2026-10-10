"""Discovery request routing and cursor isolation without provider traffic."""
import io
import json
import sys
from contextlib import contextmanager
from datetime import timedelta
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_phase2.growth import trends
from postriff_phase2.growth.trends import http, worker, retention, store
from postriff_phase2.growth.trends.jobs import partition_key
from postriff_phase2.growth.trends.contracts import digest, instant, iso
from test_trend_meta_public import policy
from test_trend_contracts import WORKSPACE


class MetaDispatch(unittest.TestCase):
    def test_retention_takes_trust_before_restore_or_node_locks(self):
        cur=Mock(description=[])
        cur.fetchone.return_value={'reads_ready':False}
        @contextmanager
        def transaction(cursor=None): yield cur
        retention.sweep(SimpleNamespace(transaction=transaction))
        self.assertIn('trend-trust-mutation',cur.execute.call_args_list[0].args[0])

    def test_same_native_meta_revision_can_be_recognized_across_fetch_times(self):
        from postriff_phase2.growth.trends.providers import meta_public as meta
        import test_trend_contracts as F
        def normalize(at,text='unchanged public caption'):
            return meta._normalize({'id':'123','text':text,'timestamp':F.BEFORE},
                platform='threads',policy=policy('threads'),at=at,available_at=at,epoch='test',
                source_key='id',content_key='text',time_key='timestamp',url_key='permalink')
        first=normalize(F.NOW)
        second=normalize(iso(instant(F.NOW)+timedelta(seconds=1)))
        self.assertEqual(first['observation_id'],second['observation_id'])
        self.assertNotEqual(first['revision_sequence'],second['revision_sequence'])
        self.assertTrue(store.same_meta_sample_revision(second,first,'keyword_search'))
        self.assertFalse(store.same_meta_sample_revision(second,first,'owned_insights'))
        self.assertFalse(store.same_meta_sample_revision({**second,'revision_sequence':2},first,'keyword_search'))
        self.assertFalse(store.same_meta_sample_revision(normalize(F.NOW,'edited text'),first,'keyword_search'))

    def test_new_reviewed_policy_creates_fresh_acquisition_without_rebinding_revoked_evidence(self):
        from postriff_phase2.growth.trends.providers import meta_public as meta
        import test_trend_contracts as F
        def normalize(p):
            return meta._normalize({'id':'123','text':'same post','timestamp':F.BEFORE},
                platform='threads',policy=p,at=F.NOW,available_at=F.NOW,epoch='test',
                source_key='id',content_key='text',time_key='timestamp',url_key='permalink')
        first=normalize(policy('threads'))
        renewed=normalize(replace(policy('threads'),version='renewed-policy-v2'))
        self.assertEqual(first['source_identity'],renewed['source_identity'])
        self.assertEqual(first['payload_digest'],renewed['payload_digest'])
        self.assertNotEqual(first['observation_id'],renewed['observation_id'])
        self.assertEqual(first['provenance']['content_revision_digest'],renewed['provenance']['content_revision_digest'])

    def test_request_cursors_are_isolated_from_other_queries_and_scheduled_defaults(self):
        cap=SimpleNamespace(endpoint='graph.threads.net/keyword_search', version='fixture-v1')
        p=policy('threads')
        first={'operation':p.operation,'coverage_epoch':'request:one',
               'discovery_request_id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}
        second={**first,'discovery_request_id':'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'}
        one=worker.cursor_partition(cap,p,first)
        self.assertNotEqual(one,worker.cursor_partition(cap,p,second))
        self.assertNotEqual(one,worker.cursor_partition(cap,p,{**first,'coverage_epoch':'request:changed'}))
        old=partition_key(instance_id=cap.endpoint,protocol_version=cap.version,
            filter_digest=digest({'operation':p.operation,'scope':p.scope_key,'filter':{}}))
        self.assertEqual(worker.cursor_partition(cap,p,{}),old)
        self.assertNotEqual(one,old)

    def test_discovery_routes_are_explicit_private_and_never_fall_into_revoke(self):
        module=SimpleNamespace(submit=Mock(return_value={'data':{'status':'queued'}}),
            read=Mock(return_value={'data':{'requests':[],'options':[]}}))
        app=SimpleNamespace(_body=lambda e:json.loads(e['wsgi.input'].read()),
            _json=lambda start,status,value:(start(str(status),[('Cache-Control','public')]),value)[1])
        service=object()
        def request(method,tail,query=''):
            seen=[]
            data=http.handle(app,{'QUERY_STRING':query,'wsgi.input':io.BytesIO(b'{"provider":"threads"}')},
                lambda s,h:seen.append((int(s),dict(h))),service,WORKSPACE,'session',method,tail)
            self.assertEqual(seen[0][1]['Cache-Control'],'private, no-store')
            return seen[0][0],data
        path=['public-sources','discovery-requests']
        with patch.dict(sys.modules,{'postriff_phase2.growth.trends.meta_discovery':module}), \
                patch.object(trends,'meta_discovery',module,create=True):
            self.assertEqual(request('GET',path)[0],200)
            module.read.assert_called_once_with(service,WORKSPACE,'session')
            self.assertEqual(request('POST',path)[0],202)
            module.submit.assert_called_once_with(service,WORKSPACE,'session',{'provider':'threads'})
            self.assertEqual(request('POST',path,'override=true')[0],400)
            self.assertEqual(module.submit.call_count,1)
            self.assertEqual(request('DELETE',path)[0],404)
            self.assertEqual(request('PATCH',path)[0],404)

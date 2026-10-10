"""Public-source UI must never promote owned or synthetic evidence to LIVE."""
import unittest
from datetime import timedelta
import test_trend_contracts as F
from postriff_phase2.growth.trends.contracts import iso,instant
from postriff_phase2.growth.trends.meta_sources import source_status

class MetaStatus(unittest.TestCase):
    def test_only_current_genuine_third_party_evidence_is_live(self):
        base=dict(active=True,latest_successful_read=F.NOW, evidence_kind='provider_response',third_party=True)
        self.assertEqual(source_status(base,at=F.NOW),'LIVE')
        for patch in ({'active':False},{'evidence_kind':'synthetic'},{'third_party':False},
                      {'latest_successful_read':None},{'latest_successful_read':F.BEFORE},
                      {'next_allowed_at':F.AFTER}):
            with self.subTest(patch=patch):self.assertNotEqual(source_status({**base,**patch},at=F.NOW),'LIVE')
        self.assertEqual(source_status(None,at=F.NOW),'APP_REVIEW_REQUIRED')
        self.assertEqual(source_status({**base,'revoked_at':F.NOW},at=F.NOW),'REVOKED')
        self.assertEqual(source_status({**base,'latest_successful_read':iso(instant(F.NOW)+timedelta(seconds=1))},at=F.NOW),'UNVERIFIED')

class MetaHttp(unittest.TestCase):
    def test_public_routes_require_interactive_auth_and_connection_permission(self):
        from test_trend_http import TrendHTTPTests
        harness=TrendHTTPTests('test_static_paths_never_interpreted_as_trend_ids');harness.setUp()
        self.assertEqual(harness.request(['public-sources'],token='')[0],401)
        self.assertEqual(harness.request(['public-sources'],token='prt_api')[0],403)
        harness.repo.role='viewer'
        self.assertEqual(harness.request(['public-sources','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],method='DELETE')[0],403)
        self.assertEqual(harness.request(['public-sources','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],method='POST')[0],404)

class MetaWire(unittest.TestCase):
    def test_database_datetimes_are_serialized_without_double_iso_conversion(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from postriff_phase2.growth.trends import meta_sources
        class Cursor:
            description=[]
            sql=[]
            def execute(self,sql,args=None):self.sql.append(sql)
            def fetchone(self):return {'installed':True}
            def fetchall(self):return [dict(authorization_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                provider_id='threads',operation='keyword_search',active=True,revoked_at=None,
                latest_successful_read=instant(F.NOW),expires_at=instant(F.AFTER),
                evidence_kind='provider_response',third_party=True)]
        cur=Cursor()
        @contextmanager
        def transaction(*_args):yield None,cur,None,None,None,None
        service=SimpleNamespace(transaction=transaction,values={})
        with patch.object(meta_sources,'utcnow',return_value=F.NOW):
            response=meta_sources.read(service,F.WORKSPACE,'session')
        item=next(v for v in response['data'] if v['provider']=='threads')
        self.assertEqual(item['latest_successful_read'],F.NOW)
        self.assertEqual(item['status'],'PAUSED')
        self.assertIn('DISTINCT ON(a.provider_id,a.operation)',cur.sql[1])
        self.assertIn("a.review->>'verified_at' DESC",cur.sql[1])

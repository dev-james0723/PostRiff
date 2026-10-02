"""Latent existing API acquisitions also require v2 funding before broker IO."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker.service import CoworkerService
from test_growth_unqualified_v2 import Cursor, Database
from postriff_phase2 import automation_runs
from postriff_phase2.research import ExaSearch


class Acquisition(unittest.TestCase):
    def service(self,mode):
        cur=Cursor(mode)
        @contextmanager
        def transaction(*args): yield cur,(1,{}),'actor'
        service=CoworkerService.__new__(CoworkerService)
        service.hosted=SimpleNamespace(repository=SimpleNamespace(transaction=transaction), ideas=SimpleNamespace(_member=lambda row:None))
        service._require=lambda flag:None; service._require_edit=lambda *args:None
        service._state=lambda *args:{}; service.clock=lambda:1_000_000
        service._broker=Mock(return_value=SimpleNamespace(search_items=Mock(return_value={'status':'ok','items':[],'provider':'synthetic','errors':[]})))
        return service

    def refusal(self,call):
        with self.assertRaises(AlphaError) as caught: call()
        self.assertEqual((caught.exception.status,caught.exception.code),(503,'growth_credit_bridge_unavailable'))

    @patch('postriff_phase2.permissions.require')
    def test_direct_research_refuses_before_source_selection(self,_):
        for mode in ('free','managed'):
            with self.subTest(mode=mode):
                service=self.service(mode)
                self.refusal(lambda:service.research_search('workspace','session','piano practice'))
                service._broker.assert_not_called()

    @patch('postriff_phase2.coworker.service.flags.enabled',return_value=True)
    @patch('postriff_phase2.coworker.service.source_intake.normalize',side_effect=AlphaError('Synthetic provider refusal.',402))
    @patch('postriff_phase2.permissions.require')
    def test_url_campaign_refuses_before_remote_normalization(self,_,normalize,__):
        for mode in ('free','managed'):
            with self.subTest(mode=mode):
                normalize.reset_mock(); service=self.service(mode)
                self.refusal(lambda:service.source_campaign('workspace','session',{'format':'url','url':'https://fixture.invalid/post'}))
                normalize.assert_not_called(); service._broker.assert_not_called()

    @patch('postriff_phase2.automation_runs.web_research.allowed',return_value=True)
    @patch('postriff_phase2.automation_runs._skill')
    @patch('postriff_phase2.automation_runs.campaigns._history')
    @patch('postriff_phase2.automation_research.find',return_value={'decision':'nothing_worth','reason':'synthetic empty'})
    def test_automation_research_refuses_before_search(self,find,*_):
        for mode in ('free','managed'):
            with self.subTest(mode=mode):
                find.reset_mock(); cur=Cursor(mode)
                host=SimpleNamespace(automation_research=SimpleNamespace(search=Mock(),read=Mock()))
                worker=SimpleNamespace(service=host,clock=lambda:1_000_000)
                claim={'workspaceId':'workspace','actor':'actor','binding':{},'task':{'workflow':{'research':{'onNothing':'draft'}}},'occurrence':{'id':'occ'}}
                repository=SimpleNamespace(get=lambda *args:{'state':{}})
                def update(service,wid,occ,actor,change,binding):
                    change({}, {}, {}, cur)
                    return {}
                with patch('postriff_phase2.automation_runs._update_run',side_effect=update):
                    self.refusal(lambda:automation_runs.research_step(worker,claim,repository,'synthetic-capability'))
                find.assert_not_called()

    @patch('postriff_phase2.automation_runs.web_research.allowed',return_value=True)
    @patch('postriff_phase2.automation_runs._skill')
    @patch('postriff_phase2.automation_runs.campaigns._history')
    def test_legacy_automation_keeps_shared_transport_guard_scoped(self,*_):
        cur=Cursor('legacy'); prior=Mock(); search=ExaSearch(before_call=prior)
        host=SimpleNamespace(automation_research=SimpleNamespace(search=search,read=Mock()),
                             connection_factory=lambda:Database(cur))
        worker=SimpleNamespace(service=host,clock=lambda:1_000_000)
        claim={'workspaceId':'workspace','actor':'actor','binding':{},'task':{'workflow':{'research':{'onNothing':'draft'}}},'occurrence':{'id':'occ'}}
        repository=SimpleNamespace(get=lambda *args:{'state':{}})
        def update(service,wid,occ,actor,change,binding):
            change({}, {}, {}, cur)
            return {}
        def find(spec,*,search:object,**kwargs):
            self.assertIs(host.automation_research.search.before_call,prior,
                          'One workspace must never replace the shared backend guard.')
            search('piano practice',2)
            return {'decision':'nothing_worth','reason':'synthetic empty'}
        with patch('postriff_phase2.automation_runs._update_run',side_effect=update), \
             patch('postriff_phase2.automation_research.find',side_effect=find), \
             patch('postriff_phase2.research._http',return_value=(200,{},'{"result":{}}')) as http:
            record,stop=automation_runs.research_step(worker,claim,repository,'synthetic-capability')
        self.assertIsNone(stop); self.assertEqual(record['decision'],'nothing_worth')
        self.assertEqual(http.call_count,2); self.assertEqual(prior.call_count,2)
        self.assertIs(host.automation_research.search.before_call,prior)


if __name__=='__main__': unittest.main()

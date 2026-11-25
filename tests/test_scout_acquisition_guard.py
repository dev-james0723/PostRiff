"""Exercise the actual broker and per-RPC acquisition boundary without network IO."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.research import ExaSearch
from postriff_phase2.coworker.research_broker import ResearchBroker


def refusal(): return AlphaError('Funding changed.', 503, code='growth_credit_bridge_unavailable')


def provider(name, result=None, error=None):
    return SimpleNamespace(id=name, capabilities=lambda: {'operations': ['search']},
                           readiness=lambda state: {'state': 'ready'}, search=Mock(return_value=result or [], side_effect=error))


class Guard(unittest.TestCase):
    def test_broker_refuses_before_first_source(self):
        p=provider('first'); broker=ResearchBroker([p]); broker.before_call=Mock(side_effect=refusal())
        with self.assertRaises(AlphaError): broker.search_items('synthetic')
        p.search.assert_not_called()

    def test_plan_transition_blocks_next_fallback(self):
        first=provider('first',error=OSError('synthetic refusal')); second=provider('second')
        broker=ResearchBroker([first,second]); broker.before_call=Mock(side_effect=[None,refusal()])
        with self.assertRaises(AlphaError): broker.search_items('synthetic')
        self.assertEqual(first.search.call_count,1); second.search.assert_not_called()

    @patch('postriff_phase2.research._http')
    def test_each_exa_rpc_guards_immediately_before_http(self,http):
        exa=ExaSearch(); exa.before_call=Mock(side_effect=refusal())
        with self.assertRaises(AlphaError): exa._post({},b'synthetic')
        http.assert_not_called(); exa.before_call.assert_called_once_with()


if __name__=='__main__': unittest.main()

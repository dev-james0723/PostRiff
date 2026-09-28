import unittest
from unittest.mock import patch
from postriff_phase2.growth.trends import learning,learning_options
from test_trend_service import make_service,WID,OID,ACTOR,NOW,RID
from test_trend_opportunities import PAYLOAD


class ChoiceOptions(unittest.TestCase):
    def setUp(self):
        self.svc,self.repo,self.store=make_service()
        self.svc.accept(WID,'session',OID,PAYLOAD)
        self.metrics=patch.dict(learning_options.INSIGHT_METRICS,{'bluesky':('views','likes')})
        self.metrics.start();self.addCleanup(self.metrics.stop)

    def options(self):
        return learning_options.choices(self.store,self.repo,WID,ACTOR,self.repo.state,NOW)

    def test_server_catalog_is_current_and_returns_unpublished_selection(self):
        options=self.options();self.assertEqual(len(options),1)
        choice=options[0]
        self.assertEqual(choice['provider'],'bluesky')
        self.assertEqual(choice['metrics'],['views','likes'])
        self.assertEqual(choice['definition_version'],learning_options.DEFINITION_VERSION)
        self.assertIsNone(choice['saved_choice'])
        self.assertNotIn('follower_conversion', choice['objectives'])
        payload={k:choice[k] for k in ('selection_digest','channel_id','provider','definition_version')}
        payload.update(metric='views',window='24h',objective='reach')
        learning_options.require_choice(options,payload)
        saved=learning.record_metric_choice(self.repo.state,ACTOR,payload,NOW)
        self.assertEqual(self.options()[0]['saved_choice'],saved)
        for change in ({'definition_version':'future'},{'metric':'made_up'},{'provider':'foreign'},{'selection_digest':'other'}):
            with self.assertRaises(ValueError):learning_options.require_choice(options,{**payload,**change})

    def test_revoked_or_stale_accepted_selection_has_no_choice(self):
        self.store.rows['receipt',RID]['validity']='revoked'
        self.assertEqual(self.options(),[])
        self.store.rows['receipt',RID]['validity']='valid'
        self.repo.state['sources'][0]['active']=False
        self.assertEqual(self.options(),[])

"""Real site-agent billing facts follow ledger billingMode, not legacy zero batch counters."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from postriff_phase2.site_agent import tools,compose,contracts,classifier,procedures
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_site_agent import page

class ResidualCustomerCopyTests(unittest.TestCase):
    def read(self,mode,credits=None):
        view={"billingMode":mode,"credits":credits,"entitlement":{"planTermsId":"creator-v1","writingBatchesRemaining":0,"mediaCreditsRemaining":0},"subscription":{"label":"Creator","status":"active"},"budget":{}}
        statements=[]
        ctx=SimpleNamespace(cur=SimpleNamespace(execute=lambda *args:statements.append(args[0])),workspace_id="owned",principal="member",membership=SimpleNamespace(allows=lambda role:False),now=1,service=SimpleNamespace(ledger=SimpleNamespace(usage_view=lambda *args:view),billing=SimpleNamespace(lifecycle=lambda *args:{"canPublish":True})))
        result=tools.entitlements_summary(ctx)
        self.assertEqual(statements,["SAVEPOINT site_agent_usage","ROLLBACK TO SAVEPOINT site_agent_usage"])
        return result
    def answer(self,result):
        p=page("/app/account/billing");reading=classifier.classify("How many credits are available?",p);plan=procedures.select(reading,p,"How many credits are available?")
        return compose.compose(reading,p,plan,{"entitlements.summary":result},language="en",trace_id="local",retrieved_at="2026-10-03T00:00:00Z")
    def test_managed_balances_and_held_cost_are_not_legacy_zero_batches(self):
        r=self.read("managed_credits",{"availableMilliCredits":3494000,"heldMilliCredits":6000,"usedMilliCredits":0,"lots":[{"grantId":"private"}],"policy":"internal"})
        self.assertEqual(r["data"].get("billingMode"),"managed_credits")
        self.assertEqual(r["data"].get("credits"),{"availableMilliCredits":3494000,"heldMilliCredits":6000,"usedMilliCredits":0})
        text=self.answer(r)["text"]+str(compose.facts({"entitlements.summary":r}))
        self.assertIn("3494",text);self.assertIn("6",text)
        self.assertNotRegex(text.lower(),r"writing batch|media credit")
    def test_free_and_unknown_balances_are_not_claimed_as_legacy_allowance(self):
        for mode in ["free_preview","managed_credits",None]:
            with self.subTest(mode=mode):
                r=self.read(mode);text=self.answer(r)["text"]+str(compose.facts({"entitlements.summary":r}))
                self.assertNotRegex(text.lower(),r"writing batch|media credit")
                self.assertNotIn("0 credits available",text.lower())
    def test_legacy_still_uses_its_legacy_counters(self):
        r=self.read("legacy_allowances");text=self.answer(r)["text"]+str(compose.facts({"entitlements.summary":r}))
        self.assertIn("Writing batches",text);self.assertIn("Media credits",text)

if __name__=="__main__":unittest.main()

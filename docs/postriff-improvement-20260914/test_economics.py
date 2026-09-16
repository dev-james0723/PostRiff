import copy,json,unittest
from pathlib import Path
import economics as e
class EconomicsChecks(unittest.TestCase):
 def setUp(self): self.p=json.loads((Path(__file__).parent/'economics-inputs.json').read_text())['scenarios']['base']
 def test_report_base_and_bullish_conflict(self):
  rows=e.baseline();base=next(x for x in rows if x['scenario']=='base' and x['month']==36);bull=rows[-1]
  self.assertAlmostEqual(base['reconstructed_paid'],186.02247649604388)
  self.assertEqual(base['report_contribution']-base['report_fixed_cost'],-974)
  self.assertEqual(bull['price_mix_ARPU'],39);self.assertGreater(bull['MRR_difference'],7000)
 def test_zero_conversions_do_not_zero_CAC(self):
  for c in self.p['channels']:c['paid_rate']=0
  r=e.simulate(self.p,3)
  self.assertTrue(all(x['full_CAC'] is None for x in r['funnel']))
  self.assertEqual(r['monthly'][-1]['ending_paid'],0)
  self.assertLess(r['monthly'][-1]['ending_cash'],self.p['opening_cash'])
 def test_delays_stock_cash_and_service_separate(self):
  r=e.simulate(self.p,3)
  self.assertEqual(r['monthly'][0]['new_paid'],0)
  self.assertAlmostEqual(r['monthly'][1]['new_paid'],6.855)
  self.assertEqual(r['monthly'][1]['receipts_after_fees'],0)
  self.assertGreater(r['monthly'][2]['receipts_after_fees'],0)
  self.p['onboarding_take_rate']=1;r2=e.simulate(self.p,3)
  self.assertEqual(r2['monthly'][1]['MRR'],r['monthly'][1]['MRR'])
  self.assertGreater(r2['monthly'][1]['service_revenue'],0)
 def test_support_paid_once_and_fixed_hours_not_support(self):
  a=e.simulate(self.p,3);self.p['support_paid_fraction']=1;b=e.simulate(self.p,3)
  self.assertAlmostEqual(a['monthly'][-1]['full_economic_result'],b['monthly'][-1]['full_economic_result'])
  self.assertGreater(a['monthly'][-1]['ending_cash'],b['monthly'][-1]['ending_cash'])
 def test_matrix_migration_conserves_customers(self):
  a=e.simulate(self.p,3);self.p['migration']=[[1,0,0],[.1,.8,.1],[0,0,1]];b=e.simulate(self.p,3)
  self.assertAlmostEqual(a['monthly'][-1]['ending_paid'],b['monthly'][-1]['ending_paid'])
  self.assertGreater(b['monthly'][-1]['business'],0)
 def test_annual_cash_and_revenue_are_not_equal(self):
  self.p['annual_share']=.2;self.p['collection_delay_months']=0;r=e.simulate(self.p,14)
  self.assertGreater(r['monthly'][1]['receipts_after_fees'],r['monthly'][1]['MRR'])
 def test_full_CAC_includes_trial_and_sales_time(self):
  r=e.simulate(self.p,1)['funnel'][0]
  self.assertAlmostEqual(r['full_CAC'],(20+16*30+20*.8+20*10/60*30)/4.8)
if __name__=='__main__':unittest.main()

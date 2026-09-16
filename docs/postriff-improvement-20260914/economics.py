#!/usr/bin/env python3
"""USD scenario calculator. No network, billing or customer records. Python stdlib only."""
import argparse, copy, csv, json, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PLANS = ['studio', 'assist', 'business']

def write_csv(path, rows):
    if not rows: return
    with path.open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def validate(p):
    assert len(p['plans'])==3 and abs(sum(p['new_plan_mix'])-1)<1e-9
    assert len(p['migration'])==3
    for row in p['migration']:
        assert len(row)==3 and all(0<=v<=1 for v in row) and abs(sum(row)-1)<1e-9
    for k in ['churn','reactivation','discount','refund_rate','annual_share','annual_discount','support_paid_fraction']:
        assert 0<=p[k]<=1,k
    assert p['conversion_delay_months']>=0 and p['collection_delay_months']>=0
    assert p['annual_share']==0 or p['migration']==[[1,0,0],[0,1,0],[0,0,1]], 'Annual migration/proration not modeled; use monthly billing for migration tests.'
    for c in p['channels']:
        assert c['qualified_cap']>=0 and c['qualified_month1']>=0
        for k in ['trial_rate','activation_rate','paid_rate']: assert 0<=c[k]<=1,k

def plan_unit(p, i):
    plan=p['plans'][i]; price=plan['price']*(1-p['discount'])*(1-p['annual_share']*p['annual_discount'])
    ai=plan['batches']*plan['attempt_cost']*plan['attempts_per_success']*p['ai_multiplier']
    direct=ai+sum(plan[k] for k in ['parse','embedding','storage','media'])
    support=plan['support_minutes']*p['support_multiplier']/60
    fee=price*p['payment_pct']+p['payment_fixed']*(1-p['annual_share']+p['annual_share']/12)
    cash=price*(1-p['refund_rate'])-fee-direct-support*p['hourly_rate']*p['support_paid_fraction']
    economic=cash-support*p['hourly_rate']*(1-p['support_paid_fraction'])
    return dict(plan=PLANS[i],price=plan['price'],net_monthly_revenue=price*(1-p['refund_rate']),direct_cost=direct,
                support_hours=support,fee=fee,cash_contribution=cash,economic_contribution=economic)

def simulate(p, months=36):
    validate(p); cohorts=[]; funnel=[]; monthly=[]; detail=[]; invoices={}; acq_cost={}; cash=p['opening_cash']
    units=[plan_unit(p,i) for i in range(3)]
    for m in range(1,months+1):
        opening=sum(sum(c['active']) for c in cohorts); churned=returned=0
        for c in cohorts:
            lost=[x*p['churn'] for x in c['active']]; win=[x*p['reactivation'] for x in c['lapsed']]
            churned+=sum(lost); returned+=sum(win)
            # Existing lapsed pool only. Newly churned accounts cannot reactivate in the same month.
            a=[c['active'][i]-lost[i]+win[i] for i in range(3)]
            c['lapsed']=[c['lapsed'][i]+lost[i]-win[i] for i in range(3)]
            c['active']=[sum(a[i]*p['migration'][i][j] for i in range(3)) for j in range(3)]
        trial_total=acq_cash=acq_hours=0
        for channel in p['channels']:
            q=min(channel['qualified_cap'],channel['qualified_month1']*(1+channel['growth'])**(m-1))
            if channel['id']==p.get('disabled_channel') and m>=p.get('disable_month',13): q=0
            trials=q*channel['trial_rate']; active=trials*channel['activation_rate']; expected=active*channel['paid_rate']
            spend=channel['cash_month']; hours=channel['hours_month']
            # Costs continue during an outage until the experiment is explicitly stopped.
            trial_total+=trials; acq_cash+=spend; acq_hours+=hours
            acq_cost[(m,channel['id'])]=(spend,hours*p['hourly_rate'])
            funnel.append(dict(month=m,channel=channel['id'],qualified=q,trials=trials,activated=active,
                               expected_new_paid=expected,payment_cohort_month=m+p['conversion_delay_months'],
                               cash_acquisition=spend,economic_acquisition=spend+hours*p['hourly_rate'],
                               cash_CAC=(spend+trials*p['trial_cash']*p['ai_multiplier']+trials*p['trial_support_minutes']/60*p['support_multiplier']*p['hourly_rate']*p['support_paid_fraction'])/expected if expected else None,
                               full_CAC=(spend+hours*p['hourly_rate']+trials*p['trial_cash']*p['ai_multiplier']+trials*p['trial_support_minutes']/60*p['support_multiplier']*p['hourly_rate'])/expected if expected else None))
        new=0
        for f in [x for x in funnel if x['payment_cohort_month']==m]:
            count=f['expected_new_paid'];new+=count
            cohorts.append(dict(join_month=m,origin_month=f['month'],channel=f['channel'],
                                active=[count*x for x in p['new_plan_mix']],lapsed=[0,0,0]))
        counts=[sum(c['active'][i] for c in cohorts) for i in range(3)]
        assert abs(sum(counts)-(opening+new+returned-churned))<1e-7
        gross_mrr=sum(counts[i]*p['plans'][i]['price']*(1-p['discount'])*(1-p['annual_share']*p['annual_discount']) for i in range(3))
        paid_direct=sum(counts[i]*units[i]['direct_cost'] for i in range(3))
        support_hours=sum(counts[i]*units[i]['support_hours'] for i in range(3))
        support_cash=support_hours*p['hourly_rate']*p['support_paid_fraction']
        contribution_cash=sum(counts[i]*units[i]['cash_contribution'] for i in range(3))
        contribution_economic=sum(counts[i]*units[i]['economic_contribution'] for i in range(3))
        trial_cash=trial_total*p['trial_cash']*p['ai_multiplier']
        trial_hours=trial_total*p['trial_support_minutes']/60*p['support_multiplier']
        onboard=new*p['onboarding_take_rate'];service_gross=onboard*p['onboarding_price']
        service_revenue=service_gross*(1-p['refund_rate'])
        service_fees=service_gross*p['payment_pct']+onboard*p['payment_fixed']
        service_cash=onboard*p['onboarding_cash_cost']; service_hours=onboard*p['onboarding_hours']
        # Billing and recognized recurring revenue are distinct. Annual invoices renew on cohort anniversaries.
        recurring_invoice=0;transactions=0
        for c in cohorts:
            for i,n in enumerate(c['active']):
                price=p['plans'][i]['price']*(1-p['discount'])
                recurring_invoice+=n*(1-p['annual_share'])*price;transactions+=n*(1-p['annual_share'])
                if (m-c['join_month'])%12==0:
                    recurring_invoice+=n*p['annual_share']*12*price*(1-p['annual_discount']);transactions+=n*p['annual_share']
                detail.append(dict(month=m,join_month=c['join_month'],origin_month=c['origin_month'],channel=c['channel'],plan=PLANS[i],active=n,lapsed=c['lapsed'][i]))
        invoice_net=(recurring_invoice+service_gross)*(1-p['refund_rate'])
        fees=(recurring_invoice+service_gross)*p['payment_pct']+(transactions+onboard)*p['payment_fixed']
        due=m+p['collection_delay_months'];invoices[due]=invoices.get(due,0)+invoice_net-fees
        receipts=invoices.get(m,0)
        fixed=p['fixed_infra']+p['fixed_other']+p['engineering_cash']+p['operations_cash']
        cash_out=paid_direct+support_cash+trial_cash+acq_cash+fixed+service_cash+trial_hours*p['hourly_rate']*p['support_paid_fraction']+p.get('founder_draw',0)
        cash+=receipts-cash_out
        cash_operating=contribution_cash-trial_cash-trial_hours*p['hourly_rate']*p['support_paid_fraction']-acq_cash-fixed+service_revenue-service_fees-service_cash
        economic=cash_operating-(support_hours+trial_hours)*p['hourly_rate']*(1-p['support_paid_fraction'])-(acq_hours+p['founder_product_hours']+service_hours)*p['hourly_rate']
        hours=(support_hours+trial_hours)*(1-p['support_paid_fraction'])+acq_hours+p['founder_product_hours']+service_hours
        monthly.append(dict(month=m,opening_paid=opening,new_paid=new,reactivated=returned,churned=churned,ending_paid=sum(counts),
                            studio=counts[0],assist=counts[1],business=counts[2],MRR=gross_mrr,ARR_run_rate=gross_mrr*12,
                            paid_cash_contribution=contribution_cash,paid_economic_contribution=contribution_economic,
                            service_revenue=service_revenue,service_economic_cost=service_cash+service_fees+service_hours*p['hourly_rate'],
                            trial_cash=trial_cash,trial_support_hours=trial_hours,acquisition_cash=acq_cash,acquisition_hours=acq_hours,
                            fixed_cash=fixed,cash_operating_result=cash_operating,full_economic_result=economic,
                            receipts_after_fees=receipts,cash_out=cash_out,ending_cash=cash,founder_hours=hours,
                            capacity_exceeded=hours>p['founder_capacity_hours']))
    return dict(monthly=monthly,funnel=funnel,cohorts=detail,units=units,
                first_negative_cash_month=next((x['month'] for x in monthly if x['ending_cash']<0),None),
                first_capacity_exceeded=next((x['month'] for x in monthly if x['capacity_exceeded']),None))

def baseline():
    # Report values preserved verbatim at displayed precision; never fitted to reconstructed values.
    published={
      'bearish':[(12,1.6,39,469,13),(24,2.1,53,630,17),(36,2.5,61,732,20)],
      'base':[(12,43.2,1296,15551,935),(24,98.1,2944,35329,2124),(36,186.0,5581,66968,4026)],
      'bullish':[(12,431.2,15955,191455,11320),(24,1385.0,51246,614956,36360),(36,3695.3,136728,1640732,97010)]}
    seeds={'bearish':(500,.01,.03,.30,.05,.12,[.75,.23,.02]),'base':(1000,.05,.06,.50,.12,.06,[.55,.40,.05]),'bullish':(2000,.08,.10,.65,.20,.03,[.40,.40,.20])}
    rows=[]
    for name,seed in seeds.items():
        q,g,t,a,p,ch,mix=seed;n=0;arpu=sum(v*price for v,price in zip(mix,[19,39,79]))
        for m in range(1,37):
            visitors=q*(1+g)**(m-1);n=n*(1-ch)+visitors*t*a*p
            if m in (12,24,36):
                original=next(x for x in published[name] if x[0]==m)
                rows.append(dict(scenario=name,month=m,report_paid=original[1],report_MRR=original[2],report_ARR=original[3],
                                 report_contribution=original[4],report_fixed_cost=5000,report_partial_result=original[4]-5000,
                                 reconstructed_qualified=visitors,reconstructed_paid=n,price_mix_ARPU=arpu,
                                 reconstructed_MRR=n*arpu,MRR_difference=n*arpu-original[2],
                                 report_implied_ARPU=original[2]/original[1],original_seed='source_unavailable',
                                 note='Report pp3-4/18-20; displayed precision only. Bullish mix conflict retained. Per-plan contribution seed unavailable.'))
    return rows

def run(out,inputs):
    out.mkdir(parents=True,exist_ok=True);config=json.loads(inputs.read_text());summaries=[]
    write_csv(out/'report-baseline.csv',baseline())
    for name,p in config['scenarios'].items():
        result=simulate(p)
        for key in ['monthly','funnel','cohorts','units']:write_csv(out/f'{name}-{key}.csv',result[key])
        for m in [12,24,36]:summaries.append(dict(scenario=name,**result['monthly'][m-1],first_negative_cash_month=result['first_negative_cash_month'],first_capacity_exceeded=result['first_capacity_exceeded']))
    write_csv(out/'scenario-summary.csv',summaries)
    p=config['scenarios']['base']; base=simulate(p); stresses=[]
    mutations={'ai_x2':{'ai_multiplier':2},'support_x2':{'support_multiplier':2},'churn_x1_5':{'churn':p['churn']*1.5},
               'primary_channel_off':{'disabled_channel':'founder','disable_month':13},'collection_delay_3_months':{'collection_delay_months':3},
               'conversion_delay_3_months':{'conversion_delay_months':3},'founder_cash_draw_2000':{'founder_draw':2000},'annual_20pct':{'annual_share':.2}}
    for name,mutation in mutations.items():
        q=copy.deepcopy(p);q.update(mutation);mutations[name]=q
    q=copy.deepcopy(p)
    for c in q['channels']:c['paid_rate']/=2
    mutations['paid_conversion_half']=q
    for name,q in mutations.items():
        r=simulate(q)
        for m in [12,24,36]:stresses.append(dict(stress=name,**r['monthly'][m-1],first_negative_cash_month=r['first_negative_cash_month'],first_capacity_exceeded=r['first_capacity_exceeded']))
    write_csv(out/'stress-tests.csv',stresses)
    # Comparable one-at-a-time +20% shocks, ranked by month-36 full-cost operating result.
    sensitivity=[]
    for variable in ['ai_multiplier','support_multiplier','churn','fixed_infra','founder_product_hours','hourly_rate','paid_rate','qualified_volume']:
        q=copy.deepcopy(p)
        if variable in ('paid_rate','qualified_volume'):
            for c in q['channels']:
                if variable=='paid_rate':c['paid_rate']=min(1,c['paid_rate']*1.2)
                else:c['qualified_month1']*=1.2;c['qualified_cap']*=1.2
        else:q[variable]*=1.2
        r=simulate(q)['monthly'][-1]
        delta=r['full_economic_result']-base['monthly'][-1]['full_economic_result']
        sensitivity.append(dict(variable=variable,shock='+20%',delta_month36_full_result=delta,absolute_delta=abs(delta)))
    sensitivity.sort(key=lambda x:x['absolute_delta'],reverse=True);write_csv(out/'sensitivity.csv',sensitivity)
    (out/'validation.json').write_text(json.dumps({'status':'pass','execution':'scenario_calculation_not_forecast','months':36,'scenarios':3,'stress_scenarios':len(mutations),'top3':sensitivity[:3],
      'checks':['cohort stock-flow conservation every month','plan mix/migration sums','zero conversions produce undefined CAC','cash receipts separated from recognized recurring revenue'],
      'limitations':['Annual billing is a sensitivity-only approximation: expected churn/refunds, no contract-level proration or deferred-revenue balance sheet.','All business inputs are assumptions or unknown, not observed growth.','Capacity-exceeding and negative-cash rows are infeasible unless funding or staffing changes.']},indent=2))
    print(json.dumps({'summary':str(out/'scenario-summary.csv'),'top3':[x['variable'] for x in sensitivity[:3]]},indent=2))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--inputs',type=Path,default=ROOT/'economics-inputs.json');a.add_argument('--out',type=Path,default=ROOT/'model');args=a.parse_args();run(args.out,args.inputs)

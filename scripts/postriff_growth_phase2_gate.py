"""Evaluate a supplied research export locally; never enroll users or claim fixtures prove lift.

Input JSON: execution ('observed' or 'synthetic'), experimentId, elapsedDays,
accounts [{accountId,arm,percentiles}], posts and predictions (native export),
suggestions [{id, written: bool}]. Keep exports outside the checkout. No network.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_phase2.growth import creator_calibration as cal


def evaluate(data):
    synthetic=data.get('execution')!='observed'
    accounts=data.get('accounts',[]);experiment=data.get('experimentId')
    if accounts and (not experiment or any(r.get('arm')!=cal.assignment(experiment,r.get('accountId','')) for r in accounts)):
        raise ValueError('Account arms must match the preregistered deterministic assignment')
    lift=cal.experiment_report(accounts,data.get('elapsedDays',0),synthetic=synthetic)
    calibration=cal.propose(data.get('posts',[]),data.get('predictions',{}))
    dimensions=max((len(c['dimensions']) for c in calibration['candidates']),default=0)
    suggestions=data.get('suggestions',[])
    if any(not isinstance(s.get('id'),str) or type(s.get('written')) is not bool for s in suggestions):raise ValueError('Invalid suggestion records')
    if len({s['id'] for s in suggestions})!=len(suggestions):raise ValueError('One row per distinct suggestion')
    rate=sum(s['written'] for s in suggestions)/len(suggestions) if suggestions else None
    checks={'threeDimensionsRhoAtLeastPointTwo':not synthetic and dimensions>=3,
            'fourWeekAccountExperimentFivePercentiles':lift['targetMet'],
            'audienceSuggestionToContentTwentyPercent':not synthetic and rate is not None and rate>=.2}
    return {'execution':data.get('execution','missing'),'status':'targets_observed_requires_review' if all(checks.values()) else 'not_met',
            'checks':checks,'calibration':{'passingDimensionsInOneCohort':dimensions,'minimumPosts':50},
            'experiment':lift,'audience':{'suggestions':len(suggestions),'written':sum(s['written'] for s in suggestions),'rate':rate},
            'notice':'This validates supplied evidence only. Review provenance, enrollment, missingness and uncertainty before any release decision.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path);args=parser.parse_args()
    try:print(json.dumps(evaluate(json.loads(args.input.read_text())),indent=2))
    except (ValueError,TypeError,KeyError) as e:parser.exit(2,str(e)+'\n')

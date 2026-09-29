#!/usr/bin/env python3
"""Validate the DESIGN ARTIFACT only. Never connects to Rafii or a provider.
Requires PyYAML and jsonschema. Product acceptance cases remain NOT RUN.
"""
from pathlib import Path
import copy, datetime, json, re, sys
import yaml
from jsonschema import Draft202012Validator, FormatChecker
ROOT=Path(__file__).resolve().parent
checks=[]
def check(name,fn):
 try:
  fn();checks.append({'name':name,'status':'pass'})
 except Exception as exc:
  checks.append({'name':name,'status':'fail','error':str(exc)})
def require(value,msg):
 if not value:raise AssertionError(msg)
def load(p):return json.loads((ROOT/p).read_text())
for p in sorted(ROOT.rglob('*.json')):
 if p.name not in ['validation-report.json','manifest-sha256.json']:
  check('parse:'+str(p.relative_to(ROOT)),lambda p=p:json.loads(p.read_text()))
schemas={p.name.split('.schema.json')[0]:json.loads(p.read_text()) for p in (ROOT/'contracts').glob('*.schema.json')}
for name,schema in schemas.items():check('schema:'+name,lambda s=schema:Draft202012Validator.check_schema(s))
for p in sorted((ROOT/'examples').glob('*.json')):
 name=p.stem
 check('example:'+name,lambda p=p,n=name:Draft202012Validator(schemas[n],format_checker=FormatChecker()).validate(json.loads(p.read_text())))
metrics=load('catalogs/metrics.json');charts=load('catalogs/dashboards.json');sources=load('research/sources.json');tests=load('catalogs/acceptance-cases.json')
ids={m['id'] for m in metrics};sourceids={s['id'] for s in sources}
check('metric IDs unique',lambda:require(len(ids)==len(metrics),'Duplicate metric IDs'))
check('chart IDs unique',lambda:require(len({c['id'] for c in charts})==len(charts),'Duplicate chart IDs'))
check('every chart metric exists',lambda:require(all(set(c['metric_ids'])<=ids for c in charts),'Unknown metric reference'))
check('MRR bridge includes reactivation',lambda:require('mrr_reactivation' in next(c for c in charts if c['id']=='mrr-bridge')['metric_ids'],'MRR bridge gap'))
check('sources unique',lambda:require(len(sourceids)==len(sources),'Duplicate source IDs'))
check('all detector rules disabled',lambda:require(all(not d['enabled'] and not d['automatic_external_action'] for d in load('catalogs/detectors.json')),'Activated detector found'))
check('all product cases remain not-run',lambda:require(all(t['status']=='not_run_design_case' for t in tests),'False product test result'))
check('all synthetic execution fixtures labeled',lambda:require(all(load('examples/'+n+'.json')['fixture'] is True for n in ['event-envelope','recommendation','engineering-check','engineering-receipt']),'Fixture mislabeled'))
def must_reject(name,value):
 errors=list(Draft202012Validator(schemas[name],format_checker=FormatChecker()).iter_errors(value))
 require(bool(errors),'Unsafe fixture unexpectedly accepted')
q=load('examples/metric-query.json');bad=copy.deepcopy(q);bad['sql']='SELECT * FROM private_data'
check('reject raw SQL property',lambda:must_reject('metric-query',bad))
badmetric=copy.deepcopy(q);badmetric['metricIds']=['raw_private_messages']
check('reject unknown private-content metric',lambda:must_reject('metric-query',badmetric))
bigq=copy.deepcopy(q);bigq['limit']=10000000
check('reject unbounded query output',lambda:must_reject('metric-query',bigq))
j=load('examples/engineering-check.json');badsha=copy.deepcopy(j);badsha['candidateSha']='consumer-saas'
check('reject mutable branch as check SHA',lambda:must_reject('engineering-check',badsha))
cmd=copy.deepcopy(j);cmd['command']='arbitrary shell'
check('reject arbitrary runner command',lambda:must_reject('engineering-check',cmd))
prod=copy.deepcopy(j);prod['environment']='production'
check('reject production environment for disposable check',lambda:must_reject('engineering-check',prod))
def query_semantics(value):
 start=datetime.datetime.fromisoformat(value['interval']['start'].replace('Z','+00:00'))
 end=datetime.datetime.fromisoformat(value['interval']['end'].replace('Z','+00:00'))
 require(0<(end-start).total_seconds()<=366*86400,'Invalid or excessive interval')
 from zoneinfo import ZoneInfo
 ZoneInfo(value['interval']['timeZone'])
 for mid in value['metricIds']:
  m=next(m for m in metrics if m['id']==mid)
  require(set(value['groupBy'])<=set(m['allowed_dimensions']),'Unsupported per-metric grouping')
def semantic_reject(fn):
 try:fn()
 except (ValueError,AssertionError,KeyError):return
 raise AssertionError('Invalid semantics accepted')
check('fixture query semantic consistency',lambda:query_semantics(q))
invalid_group=copy.deepcopy(q);invalid_group['groupBy']=['currency']
check('reject invalid per-metric dimension',lambda:semantic_reject(lambda:query_semantics(invalid_group)))
invalid_window=copy.deepcopy(q);invalid_window['interval']['end']=invalid_window['interval']['start']
check('reject empty interval',lambda:semantic_reject(lambda:query_semantics(invalid_window)))
def receipt_semantics(r):
 if r['state']=='passed': require(all(not c['required'] or c['status']=='pass' for c in r['checks']),'Required check incomplete but state passed')
r=load('examples/engineering-receipt.json');fake=copy.deepcopy(r);fake['state']='passed'
check('partial receipt remains honest',lambda:receipt_semantics(r))
check('reject false all-passed receipt',lambda:semantic_reject(lambda:receipt_semantics(fake)))
api=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text())
check('OpenAPI version',lambda:require(api['openapi']=='3.1.0','Incorrect spec version'))
def api_refs(x):
 if isinstance(x,dict):
  if '$ref' in x:
   ref=x['$ref'];require(ref.startswith('#/'),'Unexpected external ref')
   cur=api
   for k in ref[2:].split('/'):cur=cur[k]
  for v in x.values():api_refs(v)
 elif isinstance(x,list):
  for v in x:api_refs(v)
check('OpenAPI refs resolve',lambda:api_refs(api))
check('OpenAPI default founder auth',lambda:require(api['security']==[{'FounderSession':[]}],'Missing founder auth'))
check('no execute-anything route',lambda:require(all(not re.search(r'/(shell|sql|run-command)',p) for p in api['paths']),'Unsafe route'))
text=(ROOT/'rafii-control-v2-spec.md').read_text()
check('main sections 0 to 23 present',lambda:require(all(re.search(r'^## '+str(i)+r'\.',text,re.M) for i in range(24)),'Missing main section'))
check('four detailed appendices present',lambda:require(all('# Appendix '+a+'.' in text for a in 'ABCD'),'Missing appendix'))
check('design-only boundary present',lambda:require('Not implemented or activated' in text and 'No codebase scan or production test was run' in text,'Missing scope limits'))
check('no TODO or TBD placeholders',lambda:require(not re.search(r'\b(?:TODO|TBD)\b',text),'Unresolved placeholder'))
check('no leaked tool citation markup',lambda:require('' not in text,'Tool citation token found'))
check('basic secret-shape scan',lambda:require(not re.search(r'(?:sk_live_|sk_test_|whsec_)[A-Za-z0-9]{12,}|eyJ[A-Za-z0-9_-]{25,}\.',text),'Secret-shaped string found'))
check('integration source refs exist',lambda:require(all(set(i['source_refs'].split(','))<=sourceids for i in load('catalogs/integrations.json')),'Unknown integration source'))
report={'scope':'Artifact/contract consistency validation only. No Rafii product test, production scan, vendor integration or engineering execution was performed.','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'counts':{'metrics':len(metrics),'visualizations':len(charts),'detectors':len(load('catalogs/detectors.json')),'acceptance_cases_designed_not_run':len(tests),'json_schemas':len(schemas),'openapi_paths':len(api['paths'])},'checks':checks,'passed':sum(c['status']=='pass' for c in checks),'failed':sum(c['status']=='fail' for c in checks)}
(ROOT/'validation-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['scope','counts','passed','failed']},indent=2))
for c in checks:
 if c['status']=='fail':print(c)
sys.exit(bool(report['failed']))

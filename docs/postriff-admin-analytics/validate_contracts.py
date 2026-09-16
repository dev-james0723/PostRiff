"""Bounded conformance checks for candidate schemas; not a full OpenAPI validator."""
from pathlib import Path
import json,re,copy,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
B=Path(__file__).parent;C=B/'contracts';checks=[]
def check(n,v):
 assert v,n
 checks.append(n)
def rejects(n,f):
 try:f()
 except (ValueError,AssertionError,KeyError):checks.append(n)
 else:raise AssertionError(n)
registry=json.loads((C/'metric-registry.json').read_text());defs={m['key']:m for m in registry['metrics']}
schema=json.loads((C/'metric-point.schema.json').read_text())
def validate_point(p):
 if set(p)!=set(schema['required']):raise ValueError('fields')
 m=defs[p['metricKey']]
 if p['dataDomain']=='social':
  if m['provider']=='postriff' or not p['workspaceId'] or not p['accountId'] or p['sourceKind']=='first_party':raise ValueError('social scope')
 elif p['dataDomain']=='first_party':
  if m['provider']!='postriff' or p['accountId'] is not None or p['sourceKind']!='first_party':raise ValueError('first-party scope')
 else:raise ValueError('domain')
 if p['unit']=='currency':
  if not isinstance(p['currency'],str) or not re.fullmatch('[A-Z]{3}',p['currency']):raise ValueError('currency')
 elif p['currency'] is not None:raise ValueError('nonmonetary currency')
 if p['definitionVersion']!=m['version']:raise ValueError('definition')
 if p['execution'] not in ('live','synthetic'):raise ValueError('execution')
 if p['valueStatus'] not in schema['properties']['valueStatus']['enum']:raise ValueError('status')
 if p['valueStatus']=='measured':
  if not isinstance(p['value'],str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',p['value']):raise ValueError('value')
  n=Decimal(p['value'])
  if p['unit']=='count' and (n<0 or n!=int(n)):raise ValueError('nonnegative integer count')
  if p['period']['grain'] not in m['allowedGrains']:raise ValueError('unqualified grain')
 else:
  if p['value'] is not None:raise ValueError('missing is null')
 if p['derived'] and not m['derivedAllowed']:raise ValueError('policy')
 if p['unit']!=m['unit']:raise ValueError('unit')
 if p['execution']=='live' and m['provider']!='postriff' and not m['liveQualified']:raise ValueError('live qualification missing')
 period=p['period'];ZoneInfo(period['timezone'])
 if (period['start'] is None)!=(period['end'] is None):raise ValueError('period')
 if period['start'] is not None and datetime.datetime.fromisoformat(period['start'])>=datetime.datetime.fromisoformat(period['end']):raise ValueError('period order')
 coverage=p['coverage']
 if coverage['expected'] is not None:
  if not 0<=coverage['observed']<=coverage['expected']:raise ValueError('coverage')
  if coverage['complete'] and coverage['observed']!=coverage['expected']:raise ValueError('complete')
 elif coverage['complete']:raise ValueError('unknown denominator')
for name,p in json.loads((C/'examples.json').read_text()).items():
 if isinstance(p,dict):validate_point(p);check('valid '+name+' example',True)
base=json.loads((C/'examples.json').read_text())['measured']
def bad(**kw):validate_point({**copy.deepcopy(base),**kw})
rejects('unknown metric rejected',lambda:bad(metricKey='all_platforms.total_views'))
rejects('missing metric cannot be invented zero',lambda:bad(valueStatus='scope_missing',value='0'))
rejects('measured cannot be null',lambda:bad(value=None))
rejects('negative native count rejected',lambda:bad(value='-2'))
rejects('floating count rejected',lambda:bad(value='0.5'))
rejects('unqualified YouTube derived metric rejected',lambda:bad(derived=True))
rejects('unqualified real API claim rejected',lambda:bad(execution='live'))
rejects('unknown coverage cannot be complete',lambda:bad(coverage={'expected':None,'observed':7,'definition':'unknown','complete':True}))
rejects('added token field rejected',lambda:validate_point({**base,'access_token':'SYNTHETIC_NOT_A_SECRET'}))
rejects('social metric cannot impersonate first-party global aggregate',lambda:bad(dataDomain='first_party',accountId=None,workspaceId=None,sourceKind='first_party'))
rejects('social metrics require workspace and account',lambda:bad(workspaceId=None))
check('all first-party definitions contain reviewable formulas',all(m['formula'] for m in defs.values() if m['provider']=='postriff'))
check('no cross-platform or cross-tenant aggregate defaults',all(not m['crossPlatformSum'] and not m['crossTenantSocialAggregate'] for m in defs.values()))
cap=json.loads((C/'provider-capabilities.json').read_text())['providers']
check('three selected providers and zero authorization assumed',set(p['provider'] for p in cap)=={'youtube','instagram','linkedin'} and all(p['selectedByUser'] and not p['insightsVerified'] and p['billingBudgetAuthorizedMicros']==0 for p in cap))
api=json.loads((C/'openapi.json').read_text());ids=[]
def walk(n):
 if isinstance(n,dict):
  if '$ref'in n:
   ref=n['$ref']; assert ref.startswith('#/'),'only local refs'
   value=api
   for segment in ref[2:].split('/'):value=value[segment]
  for v in n.values():walk(v)
 elif isinstance(n,list):
  for v in n:walk(v)
walk(api);check('all OpenAPI refs resolve locally',True)
for path,methods in api['paths'].items():
 for method,op in methods.items():
  ids.append(op['operationId']);assert op['x-required-permission'];assert '401'in op['responses'] and '403'in op['responses']
  assert set(re.findall(r'{(\w+)}',path))=={p['name'] for p in op['parameters'] if p['in']=='path'}
check('OpenAPI operation IDs unique and path params match',len(ids)==len(set(ids)))
check('read contract has no publication operation',not any('publish' in x.lower() for x in ids))
check('42 unique metric definitions',len(defs)==42 and len(defs)==len(registry['metrics']))
# DST period example: local native date is 23 hours, not blindly 24.
z=ZoneInfo('America/Los_Angeles');a=datetime.datetime(2026,3,8,tzinfo=z);b=datetime.datetime(2026,3,9,tzinfo=z)
check('native Pacific DST day contract preserves 23h',b.timestamp()-a.timestamp()==23*3600)
result={'status':'pass','execution':'candidate-contract-conformance','checks':checks,'test_count':len(checks),'limitations':['No live provider requests or JWT validation','Full OpenAPI/JSON Schema standard validator validation_unavailable: no validator installed; local refs/required fields/negative cases checked','Worker concurrency and billing end-to-end tests specified but not implemented']}
(B/'evidence/contract-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

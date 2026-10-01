"""Versioned catalog, bounded metric DSL, safe read DTOs and isolated founder intelligence.

The supplied metric policies are proposed, not activated. Missing/uncalibrated sources
remain unavailable until a separately reviewed policy and adapter qualify them.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from jsonschema import Draft202012Validator, FormatChecker
from postriff_phase2.agent_runtime_v2.contracts import ToolSpec, READ, CREATE_DRAFT, empty_result, new_trace_id
from .auth import CAPABILITIES, ControlError
from .investigations import effective_quality, evaluate_checks, plan_intent, ADAPTER_VERSION

# The runtime pack ships inside the package; the tech-pack docs copy remains the fallback for older checkouts.
PACK_CANDIDATES = (Path(__file__).resolve().parent / 'pack',
                   Path(__file__).resolve().parents[2] / 'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2')
PACK = next((candidate for candidate in PACK_CANDIDATES if (candidate / 'catalogs/metrics.json').is_file()), PACK_CANDIDATES[0])
ACTIVATED = 'activated_v1'
MODES = ('live', 'demo')
FOUNDER_TOOLS = (
    ToolSpec('founder.metrics.query', READ, 'metrics.query', 'Named metrics with receipts and quality states', tenant='founder', audit='metrics.query'),
    ToolSpec('founder.customers.metadata', READ, 'customers.read', 'Safe account metadata; no customer messages or private content', tenant='founder', audit='customers.read'),
    ToolSpec('founder.workspaces.metadata', READ, 'workspaces.read', 'Membership and subscription metadata', tenant='founder', audit='workspaces.read'),
    ToolSpec('founder.engineering.evidence', READ, 'engineering.read', 'Attested exact-SHA evidence; no dispatch or code writes', tenant='founder', audit='engineering.read'),
    ToolSpec('founder.recommendation.prepare', CREATE_DRAFT, 'copilot.use', 'Evidence-bound proposal requiring separate human approval', tenant='founder', approval=True),
)


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
def iso_now(): return datetime.now(timezone.utc).isoformat()
def identifier(value):
    try: return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError): raise ControlError('VALIDATION_FAILED', 400)


class Catalog:
    def __init__(self, path=PACK):
        path = Path(path)
        self.metrics = {}
        # metrics.json holds the tech pack's proposed entries plus the P0 activations; each later founder slice appends its own
        # activated_v1 entries in catalogs/metrics.d/<slice>.json (sorted, after metrics.json) so slices never edit one file.
        rows = json.loads((path / 'catalogs/metrics.json').read_text())
        for extension in sorted((path / 'catalogs/metrics.d').glob('*.json')):
            extra = json.loads(extension.read_text())
            if not isinstance(extra, list) or any(not isinstance(row, dict) or row.get('status') != ACTIVATED for row in extra):
                raise ValueError('metrics.d entries must be activated_v1 rows: ' + extension.name)
            rows.extend(extra)
        for row in rows:
            # An activated_v1 entry appended to the catalog governs its id; the proposed text stays untouched.
            current = self.metrics.get(row['id'])
            if current is not None and current.get('status') == ACTIVATED and row.get('status') == ACTIVATED: raise ValueError('duplicate activated metric ' + row['id'])
            if current is None or current.get('status') != ACTIVATED: self.metrics[row['id']] = row
        self.dashboards = json.loads((path / 'catalogs/dashboards.json').read_text())
        self.detectors = json.loads((path / 'catalogs/detectors.json').read_text())
        self.integrations = json.loads((path / 'catalogs/integrations.json').read_text())
        schemas = {name: json.loads((path / f'contracts/{name}.schema.json').read_text()) for name in ('metric-query', 'copilot-turn', 'recommendation', 'event-envelope', 'chart-spec')}
        self._extend_query_schema(schemas['metric-query'])
        self.schemas = {name: Draft202012Validator(schema, format_checker=FormatChecker()) for name, schema in schemas.items()}

    def _extend_query_schema(self, schema):
        """The structural schema admits exactly the catalog's ids and dimensions; the two cannot drift."""
        properties = schema['properties']
        properties['metricIds']['items']['enum'] = sorted(self.metrics)
        dimensions = set(properties['groupBy']['items']['enum'])
        for metric in self.metrics.values(): dimensions.update(metric['allowed_dimensions'])
        properties['groupBy']['items']['enum'] = sorted(dimensions)
        properties['filters']['items']['properties']['dimension']['enum'] = sorted(dimensions)

    def activated(self, metric_id): return self.metrics.get(metric_id, {}).get('status') == ACTIVATED

    def validate(self, name, value):
        if not self.schemas[name].is_valid(value): raise ControlError('VALIDATION_FAILED', 400)

    def validate_query(self, query):
        self.validate('metric-query', query)
        try:
            start = datetime.fromisoformat(query['interval']['start'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(query['interval']['end'].replace('Z', '+00:00'))
            ZoneInfo(query['interval']['timeZone'])
        except (ValueError, ZoneInfoNotFoundError): raise ControlError('VALIDATION_FAILED', 400)
        if not start.tzinfo or not end.tzinfo or not timedelta(0) < end-start <= timedelta(days=366): raise ControlError('BUDGET_EXCEEDED', 400)
        dimensions = set(query['groupBy']) | {item['dimension'] for item in query['filters']}
        selected = [self.metrics[name] for name in query['metricIds']]
        if any(not dimensions <= set(metric['allowed_dimensions']) for metric in selected): raise ControlError('VALIDATION_FAILED', 400)
        if len({metric['grain'] for metric in selected}) > 1: raise ControlError('VALIDATION_FAILED', 400)
        if any(metric['currency_policy'] == 'native_currency_separate' for metric in selected) and 'currency' not in query['groupBy']:
            raise ControlError('VALIDATION_FAILED', 400)
        if any(item['operator'] == 'eq' and len(item['values']) != 1 for item in query['filters']): raise ControlError('VALIDATION_FAILED', 400)
        return selected


def engineering_state(rows, sha, required_count=0):
    """No branch-name, empty, skipped, stale or untrusted green. This never implies merge/deploy/fix."""
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha) or required_count <= 0: return 'suspected'
    checks = [row for row in rows if row.get('kind') == 'check' and row.get('required')]
    if len(checks) != required_count: return 'suspected'
    if all(row.get('exact_sha') == sha and row.get('attested') is True and row.get('conclusion') == 'success' for row in checks):
        return 'checks_passed'
    return 'suspected'


class QueryService:
    def __init__(self, store, catalog=None, *, synthetic=False, clock=None, delivery=None):
        self.store, self.catalog, self.synthetic = store, catalog or Catalog(), synthetic
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.delivery = delivery or {"state":"unverified", "localCandidate":None,"remotePRHead":None,"targetBranch":None,"ciSHA":None,"hostedControlDeployment":None}

    @staticmethod
    def require(principal, capability):
        if principal.get('session', {}).get('environment') not in ('local','staging','production') or capability not in CAPABILITIES or capability not in principal.get('operator', {}).get('capabilities', []):
            raise ControlError('SCOPE_DENIED')

    def demo_data(self, principal):
        """The founder's own persisted Demo dataset (RLS-isolated); never a Live fallback."""
        from .workspace import WorkspaceService
        return WorkspaceService(self.store).demo(principal)

    def metric_query(self, query, principal, request_id, snapshot_id=None, mode='live', demo_data=None):
        self.require(principal, 'metrics.query')
        if mode not in MODES: raise ControlError('VALIDATION_FAILED', 400)
        metrics = self.catalog.validate_query(query)
        if 'check_failures' in query['metricIds']:self.require(principal,'engineering.read')
        if self.synthetic and (principal['session']['environment'] != 'local' or self.store.environment != 'local'): raise ControlError('SCOPE_DENIED')
        if self.synthetic and query['metricIds']==['check_failures'] and query['comparison'] != 'none': raise ControlError('VALIDATION_FAILED',400)
        activated = [metric for metric in metrics if metric.get('status') == ACTIVATED]
        # Activated and proposed definitions never share one receipt; a Demo query of proposed ids is still proposed.
        if activated and len(activated) != len(metrics): raise ControlError('VALIDATION_FAILED', 400)
        if snapshot_id is not None and (activated or mode != 'live'): raise ControlError('VALIDATION_FAILED', 400)
        receipt_id, as_of = str(uuid.uuid4()), self.clock().isoformat()
        rows = [dict(metricId=metric['id'], definitionVersion=metric['version'], unit=metric['unit'], grain=metric['grain'],
                     value=None, sampleCount=None, dataState='unavailable', sourceWatermark=None, reason='definition_not_activated',
                     defaultExclusions=metric['default_exclusions'], queryTemplateRef=metric['query_template_ref']) for metric in metrics][:query['limit']]
        execution = 'policy_unavailable'
        if activated:
            if mode == 'demo':
                from . import demo_metrics
                data = demo_data if demo_data is not None else self.demo_data(principal)
                rows, coverage, source_versions = demo_metrics.compute(data, query, metrics)
                execution = 'demo_dataset'
            else:
                from . import live_metrics
                rows, coverage, source_versions = live_metrics.compute(self, query, metrics)
                execution = 'admitted_operational'
            if len(rows) > query['limit']: raise ControlError('BUDGET_EXCEEDED', 400)
            watermarks = {row['source_id']: row['watermark'] for row in self.store.read('sources')}
            states = {row['dataState'] for row in rows}
            # Zero grouped rows from an instrumented source is a measured empty period, never a missing source.
            state = next(iter(states)) if len(states) == 1 else 'partial' if states else 'measured'
            self.store.receipt(dict(id=receipt_id, operator=principal['operator']['user_id'], requestId=identifier(request_id),
                                    queryDigest=hashlib.sha256(canonical(query).encode()).hexdigest(), metricVersions={m['id']:m['version'] for m in metrics},
                                    dataState=state, sourceWatermarks=watermarks, rowCount=len(rows), rows=rows, executionState=execution, normalizedQuery=json.loads(canonical(query)), calculatedAt=as_of, coverage=coverage, sourceVersions=source_versions))
            warning = ('Demo dataset: fictional records computed with the activated v1 definitions; never a Live fallback.' if mode == 'demo'
                       else 'Activated v1 definitions over restricted projections. Coverage and data states qualify every value; missing data is not zero.')
            return dict(requestId=request_id, queryReceiptId=receipt_id, asOf=as_of, dataState=state, mode=mode, rows=rows, executionState=execution, normalizedQuery=json.loads(canonical(query)), coverage=coverage, sourceVersions=source_versions, warnings=[warning])
        if self.synthetic and query['metricIds'] == ['check_failures']:
            projected = self.store.query_check_rollups(query,metrics[0]['version'])
            rows = []
            for projection in projected:
                watermark = datetime.fromisoformat(projection['source_watermark'])
                state = 'partial' if projection['states'] != ['measured'] else 'stale' if datetime.now(timezone.utc)-watermark > timedelta(minutes=15) else 'measured'
                rows.append(dict(metricId='check_failures',definitionVersion=metrics[0]['version'],unit=metrics[0]['unit'],grain=metrics[0]['grain'],
                    value=int(projection['value']) if projection['value'] is not None and state!='partial' else None,
                    dimensions=projection['dimensions'],sampleCount=projection['sample_count'],dataState=state,sourceWatermark=projection['source_watermark'],
                    reason='synthetic_coverage_incomplete' if state=='partial' else 'synthetic_source_stale' if state=='stale' else 'synthetic_source_receipts',
                    sourceReceiptIds=projection['source_receipt_ids'],fixture=True,defaultExclusions=metrics[0]['default_exclusions'],queryTemplateRef=metrics[0]['query_template_ref']))
            execution = 'local_synthetic'
            if not rows:
                rows=[dict(metricId='check_failures',definitionVersion=metrics[0]['version'],unit=metrics[0]['unit'],grain=metrics[0]['grain'],value=None,dimensions={},sampleCount=None,dataState='unavailable',sourceWatermark=None,reason='no_source_coverage',sourceReceiptIds=[],fixture=True)]
        if snapshot_id is not None:
            rows, execution, snapshot_coverage, source_versions = self.snapshot_rows(snapshot_id,query,principal)
        else:
            snapshot_coverage = None
            source_versions = {'adapter': 'local-check-rollup/1' if execution=='local_synthetic' else 'not_admitted'}
        coverage = snapshot_coverage or dict(complete=execution=='local_synthetic' and all(row['dataState']=='measured' for row in rows), returnedRows=len(rows), populationTotal=None, inputLimit=1000, reason='bounded_fixture' if execution=='local_synthetic' else 'definition_not_activated')
        watermarks = {row['source_id']: row['watermark'] for row in self.store.read('sources')}
        watermarks.update({ref:row['sourceWatermark'] for row in rows for ref in row.get('sourceReceiptIds',[])})
        states={row['dataState'] for row in rows}
        state = next(iter(states)) if len(states)==1 else 'partial'
        self.store.receipt(dict(id=receipt_id, operator=principal['operator']['user_id'], requestId=identifier(request_id),
                                queryDigest=hashlib.sha256(canonical(query).encode()).hexdigest(), metricVersions={m['id']:m['version'] for m in metrics},
                                dataState=state, sourceWatermarks=watermarks, rowCount=len(rows), rows=rows, executionState=execution, normalizedQuery=json.loads(canonical(query)), calculatedAt=as_of, coverage=coverage, sourceVersions=source_versions))
        return dict(requestId=request_id, queryReceiptId=receipt_id, asOf=as_of, dataState=state, rows=rows, executionState=execution, normalizedQuery=json.loads(canonical(query)), coverage=coverage, sourceVersions=source_versions,
                    warnings=['Synthetic local source receipts; excluded from operational business metrics. Proposed policies remain inactive. Missing data is not zero.' if execution=='local_synthetic' else 'Versioned business policy and source qualification are required. Missing data is not zero.'])

    def source_health(self):
        rows = {row['source_id']: row for row in self.store.read('sources')}
        snapshots = self.snapshots()
        operational = next((row for row in snapshots if row['provenance']=='admitted_operational'),None)
        if operational:
            capture=operational['payload']
            rows['github']=dict(source_id='github',state='measured',watermark=capture['observedAt'],checked_at=capture['observedAt'],qualified=True,coverage_complete=capture['coverage']['complete'],provenance=capture['provenance'],source_version=capture['adapterVersion'])
        ids=[source['id'] for source in self.catalog.integrations if source['id'] not in ('react_flow','echarts')]
        return [effective_quality(rows.get(source,dict(source_id=source,state='unavailable')),self.clock()) for source in ids]

    def snapshots(self):
        return self.store.check_snapshots() if hasattr(self.store,'check_snapshots') else []

    def snapshot_rows(self, snapshot_id, query, principal):
        self.require(principal,'engineering.read')
        capture=self.store.check_snapshot(identifier(snapshot_id))
        if not capture: raise ControlError('SOURCE_UNAVAILABLE',404)
        if query['metricIds']!=['check_failures'] or query['comparison']!='none' or query['groupBy']!=['suite','failure_class']: raise ControlError('VALIDATION_FAILED',400)
        if capture['provenance']=='synthetic' and (not self.synthetic or principal['session']['environment']!='local'): raise ControlError('SCOPE_DENIED')
        observed=datetime.fromisoformat(capture['observedAt'])
        if not datetime.fromisoformat(query['interval']['start'].replace('Z','+00:00')) <= observed < datetime.fromisoformat(query['interval']['end'].replace('Z','+00:00')):
            checks=[]
        else: checks=evaluate_checks(capture['workflowRuns'],capture['requiredManifest'],capture['coverage']['complete'])['checks']
        synthetic=capture['provenance']=='synthetic'
        quality=effective_quality(dict(source_id='github',state='measured',watermark=capture['observedAt'],checked_at=capture['observedAt'],qualified=capture['provenance']=='admitted_operational',coverage_complete=capture['coverage']['complete'],provenance=capture['provenance'],source_version=capture['adapterVersion']),self.clock())
        rows=[]
        for check in checks:
            dims=dict(suite=check['name'],failure_class='infrastructure' if check['outcome']=='infrastructure_failure' else 'check')
            if any(dims.get(f['dimension']) not in f['values'] for f in query['filters']):continue
            eligible=check['outcome'] in ('success','failure')
            state=('unavailable' if observed>self.clock() else 'partial' if not eligible or not capture['coverage']['complete'] else 'stale' if self.clock()-observed>timedelta(minutes=15) else 'measured') if synthetic else (quality['state'] if eligible else 'unavailable' if check['outcome']=='infrastructure_failure' else 'partial')
            rows.append(dict(metricId='check_failures',definitionVersion=1,unit='count',grain='engineering_job',value=int(check['outcome']=='failure') if eligible and state in ('measured','stale') else None,sampleCount=1 if eligible else None,dataState=state,dimensions={key:dims[key] for key in query['groupBy']},sourceWatermark=capture['observedAt'],sourceReceiptIds=[snapshot_id],fixture=synthetic,reason=check['outcome'],outcome=check['outcome'],exactSha=capture['exactSha']))
        if not rows:
            rows=[dict(metricId='check_failures',definitionVersion=1,unit='count',grain='engineering_job',value=None,sampleCount=None,dataState='unavailable',dimensions={},sourceWatermark=capture['observedAt'],sourceReceiptIds=[snapshot_id],fixture=synthetic,reason='no_eligible_matching_check')]
        if len(rows)>query['limit']:raise ControlError('BUDGET_EXCEEDED',400)
        evaluation=evaluate_checks(capture['workflowRuns'],capture['requiredManifest'],capture['coverage']['complete'])
        coverage=dict(complete=capture['coverage']['complete'],scope='exact_sha_required_workflow_manifest',required=len(evaluation['checks']),observed=evaluation['observedRequiredCount'],returnedRows=len(rows),populationTotal=None,provenance=capture['provenance'],qualification=evaluation['qualification'],releaseAccepted=False)
        versions=dict(ageSeconds=quality['age_seconds'],adapter=capture['adapterVersion'],manifestVersion=capture['requiredManifest']['version'],exactSha=capture['exactSha'],snapshotId=snapshot_id,sourceRequestId=capture['requestId'],resourceUrl=capture['resourceUrl'],providerBodyDigest=capture['providerBodyDigest'],observedAt=capture['observedAt'],requiredManifest=capture['requiredManifest'])
        return rows,'local_synthetic' if synthetic else capture['provenance'],coverage,versions

    def dispatch(self, path, body, principal, request_id, mode=None):
        if path == '/metrics/query':
            # Data mode travels beside the query (body.mode or the caller's ?mode=); the schema never sees it.
            selected = body.get('mode', mode) if isinstance(body, dict) else mode
            query = {key: value for key, value in body.items() if key != 'mode'} if isinstance(body, dict) else body
            return self.metric_query(query, principal, request_id, mode=selected or 'live')
        if path == '/engineering/checks/query':
            if set(body)!= {'snapshotId','query'}:raise ControlError('VALIDATION_FAILED',400)
            return self.metric_query(body['query'],principal,request_id,body['snapshotId'])
        if path == '/engineering/checks':
            self.require(principal,'engineering.read')
            snapshots=[dict(id=row['id'],exactSha=row['exact_sha'],provenance=row['provenance'],observedAt=row['observed_at'],qualification=evaluate_checks(row['payload']['workflowRuns'],row['payload']['requiredManifest'],row['payload']['coverage']['complete']),coverage=row['payload']['coverage']) for row in self.snapshots()]
            return dict(snapshots=snapshots,delivery=self.delivery,_dataState='partial',readOnly=True)
        if path == '/copilot/turns': return self.copilot_turn(body, principal)
        if path == '/sources/health':
            self.require(principal,'control.read')
            return dict(sources=self.source_health(),_dataState='partial')
        if path == '/overview':
            self.require(principal,'control.read')
            sources=self.source_health()
            return dict(evidenceReadiness={'qualifiedSources':sum(row['state']=='measured' for row in sources),'sourcesConsidered':len(sources),'businessHealth':'unavailable','reason':'Business telemetry is not qualified. Inspect exact-SHA check evidence and source readiness.'},sources=sources,delivery=self.delivery,investigationPath='/control/engineering',readOnly=True,_dataState='partial')
        if path == '/dashboards':
            self.require(principal, 'control.read')
            return dict(dashboards=self.catalog.dashboards, definitions=list(self.catalog.metrics.values()), detectors=self.catalog.detectors, _dataState='unavailable')
        if path == '/users':
            self.require(principal, 'customers.read')
            rows=self.store.read('users')
            return dict(users=rows, limit=200, scope='safe_metadata', coverage={'complete':False,'populationTotal':None,'returnedRows':len(rows)},_dataState='partial')
        if path.startswith('/users/'):
            self.require(principal, 'customers.read')
            user_id = identifier(path.removeprefix('/users/'))
            rows = self.store.read('user', user_id)
            if not rows: raise ControlError('SOURCE_UNAVAILABLE', 404)
            return dict(user=rows[0], memberships=self.store.read('user_memberships', user_id), privateContent={'dataState':'suppressed', 'reason':'scoped_support_grant_required'}, financialActionsEnabled=False)
        if path == '/workspaces':
            self.require(principal, 'workspaces.read')
            return dict(workspaces=self.store.read('workspaces'), limit=200, scope='safe_metadata',coverage={'complete':False,'populationTotal':None},_dataState='partial')
        if path == '/engineering':
            self.require(principal, 'engineering.read')
            rows=self.store.read('engineering')
            for row in rows:
                if row['state'] in ('checks_passed','merged','deployed','production_verified'):
                    row['observed_stage']=row['state']
                    row['state']='suspected'
                    row['qualification']='trusted_required_check_manifest_not_qualified' if row['kind']=='check' else 'trusted_stage_evidence_not_qualified'
            return dict(evidence=rows, stages=['suspected','reproduced','candidate_fix','checks_passed','merged','deployed','production_verified'], checksDispatchEnabled=False, patchEnabled=False, _dataState='partial')
        if path.startswith('/metrics/receipts/'):
            self.require(principal, 'metrics.query')
            receipt=self.authorized_receipt(path.removeprefix('/metrics/receipts/'),principal)
            return dict(receipt=receipt, _dataState=receipt['data_state'])
        if path == '/recommendations':
            self.require(principal, 'control.read')
            # Even trusted storage must obey the authoritative contract before rendering.
            rows = self.store.read('recommendations')
            for row in rows: self.catalog.validate('recommendation', row['proposal'])
            return dict(recommendations=rows, approvalExecutionEnabled=False)
        if path.startswith('/copilot/runs/'):
            self.require(principal, 'copilot.use')
            run = self.store.run(identifier(path.removeprefix('/copilot/runs/')), principal['operator']['user_id'])
            if not run: raise ControlError('SOURCE_UNAVAILABLE', 404)
            for ref in run.get('queryReceiptIds',[]):self.authorized_receipt(ref,principal)
            return dict(run=run, _dataState='partial')
        if path == '/audit':
            self.require(principal, 'audit.read')
            return dict(events=self.store.audit_read(), limit=200)
        raise ControlError('SCOPE_DENIED', 404)

    def authorized_receipt(self, reference, principal):
        self.require(principal,'metrics.query')
        rows=self.store.read('receipt',identifier(reference))
        if not rows:raise ControlError('SCOPE_DENIED')
        receipt=rows[0]
        owner=receipt.get('operator_id')
        if owner and owner != principal['operator']['user_id']:raise ControlError('SCOPE_DENIED')
        metrics=set(receipt.get('normalized_query',{}).get('metricIds',[]))|set(receipt.get('metric_versions',{}))|{row.get('metricId') for row in receipt.get('result_rows',[])}
        if 'check_failures' in metrics or receipt.get('source_versions',{}).get('adapter')=='github-workflow/1':
            self.require(principal,'engineering.read')
        if datetime.fromisoformat(receipt['expires_at']) <= self.clock():raise ControlError('STALE_PREVIEW',409)
        if receipt['execution_state']=='local_synthetic' and (not self.synthetic or principal['session']['environment']!='local'):raise ControlError('SCOPE_DENIED')
        return receipt

    def copilot_turn(self, request, principal):
        self.require(principal, 'copilot.use')
        self.require(principal, 'metrics.query')
        self.catalog.validate('copilot-turn', request)
        for evidence in request['contextEvidenceIds']:
            self.authorized_receipt(evidence,principal)
        # A deterministic intelligence mode has no paid model call, autonomous schedule or effect executor.
        # Customer/user prose is not interpolated into tools, SQL, log payloads or persisted conversations.
        run_id, cached = self.store.reserve_run(request, principal, hashlib.sha256(canonical(request).encode()).hexdigest())
        if cached is not None:
            for ref in cached.get('queryReceiptIds',[]):self.authorized_receipt(ref,principal)
            return {**cached, 'runId':run_id}
        try:
            return self._copilot_read(request, principal, run_id)
        except BaseException:
            self.store.save_run(dict(runId=run_id, state='blocked', code='SOURCE_UNAVAILABLE',
                                     answerText='Read investigation unavailable. No action was performed.',
                                     queryReceiptIds=[], changedEntities=[]), principal, request['conversationId'])
            raise

    def _copilot_read(self, request, principal, run_id):
        # Intent chooses only a named read template. It cannot add fields, instructions, recipients or actions.
        if request['contextEvidenceIds']:
            allowed={'explain this evidence','explain this receipt','explain selected receipt','explain these check failures','explain check failures using this receipt'}
            if request['message'].strip().casefold() not in allowed:
                return self.unsupported_run(request,principal,run_id)
            receipts=[self.authorized_receipt(ref,principal) for ref in request['contextEvidenceIds']]
            evidence_rows=[row for receipt in receipts for row in receipt['result_rows']]
            receipt_ids=request['contextEvidenceIds']
        else:
            query=plan_intent(request['message'],self.clock())
            if query is None or query['comparison']!='none':
                return self.unsupported_run(request,principal,run_id,query)
            receipt=self.metric_query(query,principal,request['requestId'])
            evidence_rows=receipt['rows'];receipt_ids=[receipt['queryReceiptId']]
        descriptions=[f"{row.get('dimensions',{}).get('suite',row['metricId'].replace('_',' '))}: {row['value'] if row['value'] is not None else 'unavailable'} failures, {row['dataState']}, outcome {row.get('outcome',row.get('reason','unavailable')).replace('_',' ')}." for row in evidence_rows]
        synthetic=any(row.get('fixture') for row in evidence_rows)
        answer=('Synthetic local evidence snapshot; proposed policies remain inactive. ' if synthetic else 'Read-only query evidence. ')+ ' '.join(descriptions)+ ' Quality states describe the receipt snapshot. Stale, partial and unavailable rows cannot support a current operational conclusion. No action was performed.'
        run = empty_result(new_trace_id(), request['modality'])
        run.update(runId=run_id, namespace='founder', mode='deterministic_read_only',
                   answerText=answer, evidenceRows=evidence_rows,
                   speakableSummary='Synthetic local evidence.' if synthetic else 'Read-only evidence; review quality states before conclusions.', state='completed',
                   queryReceiptIds=receipt_ids, recommendations=[], tools=[tool.public() for tool in FOUNDER_TOOLS if tool.permission in principal['operator']['capabilities']],
                   usage={'providerCalls':0,'costState':'not_applicable'}, warnings=[{'code':'MODEL_DISABLED','message':'Model generation and scheduled investigations are disabled pending explicit budget and access approval.'}])
        if self.store.save_run(run, principal, request['conversationId']) is False:raise ControlError('SOURCE_UNAVAILABLE',503)
        return run

    def unsupported_run(self, request, principal, run_id, query=None):
        run=empty_result(new_trace_id(),request['modality'])
        run.update(runId=run_id,namespace='founder',mode='deterministic_read_only',state='blocked',answerText='Unsupported question or comparison. This milestone can explain an explicitly selected receipt and bounded check queries. Qualified spend, activation, deployment, agent and causal-comparison evidence is unavailable. No action was performed.',queryReceiptIds=[],requestedQuery=query,changedEntities=[],usage={'providerCalls':0,'costState':'not_applicable'})
        if self.store.save_run(run,principal,request['conversationId']) is False:raise ControlError('SOURCE_UNAVAILABLE',503)
        return run

    def validate_recommendation(self, proposal, principal):
        self.require(principal, 'copilot.use')
        self.catalog.validate('recommendation', proposal)
        if proposal['environment'] != principal['session']['environment']: raise ControlError('SCOPE_DENIED')
        if datetime.fromisoformat(proposal['expiresAt'].replace('Z','+00:00')) <= datetime.now(timezone.utc): raise ControlError('STALE_PREVIEW', 409)
        for fact in proposal['facts']:
            for ref in fact['evidenceRefs']:
                if not self.store.read('receipt', identifier(ref)): raise ControlError('SCOPE_DENIED')
        return proposal  # No execute method exists in this read/proposal service.

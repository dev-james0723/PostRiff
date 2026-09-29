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

PACK = Path(__file__).resolve().parents[2] / 'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2'
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
        self.metrics = {row['id']: row for row in json.loads((path / 'catalogs/metrics.json').read_text())}
        self.dashboards = json.loads((path / 'catalogs/dashboards.json').read_text())
        self.detectors = json.loads((path / 'catalogs/detectors.json').read_text())
        self.integrations = json.loads((path / 'catalogs/integrations.json').read_text())
        self.schemas = {name: Draft202012Validator(json.loads((path / f'contracts/{name}.schema.json').read_text()), format_checker=FormatChecker())
                        for name in ('metric-query', 'copilot-turn', 'recommendation', 'event-envelope', 'chart-spec')}

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
    def __init__(self, store, catalog=None):
        self.store, self.catalog = store, catalog or Catalog()

    @staticmethod
    def require(principal, capability):
        if principal.get('session', {}).get('environment') not in ('local','staging','production') or capability not in CAPABILITIES or capability not in principal.get('operator', {}).get('capabilities', []):
            raise ControlError('SCOPE_DENIED')

    def metric_query(self, query, principal, request_id):
        self.require(principal, 'metrics.query')
        metrics = self.catalog.validate_query(query)
        receipt_id, as_of = str(uuid.uuid4()), iso_now()
        rows = [dict(metricId=metric['id'], definitionVersion=metric['version'], unit=metric['unit'], grain=metric['grain'],
                     value=None, sampleCount=None, dataState='unavailable', sourceWatermark=None, reason='definition_not_activated',
                     defaultExclusions=metric['default_exclusions'], queryTemplateRef=metric['query_template_ref']) for metric in metrics][:query['limit']]
        watermarks = {row['source_id']: row['watermark'] for row in self.store.read('sources')}
        self.store.receipt(dict(id=receipt_id, operator=principal['operator']['user_id'], requestId=identifier(request_id),
                                queryDigest=hashlib.sha256(canonical(query).encode()).hexdigest(), metricVersions={m['id']:m['version'] for m in metrics},
                                dataState='unavailable', sourceWatermarks=watermarks, rowCount=len(rows)))
        return dict(requestId=request_id, queryReceiptId=receipt_id, asOf=as_of, dataState='unavailable', rows=rows,
                    warnings=['Versioned business policy and source qualification are required. Missing data is not zero.'])

    def source_health(self):
        rows = {row['source_id']: row for row in self.store.read('sources')}
        return [rows.get(source['id'], dict(source_id=source['id'], state='unavailable', watermark=None, checked_at=None, reason_code='not_configured')) for source in self.catalog.integrations]

    def dispatch(self, path, body, principal, request_id):
        if path == '/metrics/query': return self.metric_query(body, principal, request_id)
        if path == '/copilot/turns': return self.copilot_turn(body, principal)
        if path == '/overview':
            self.require(principal, 'control.read')
            metrics = [self.catalog.metrics[name] for name in self.catalog.dashboards[0]['metric_ids']]
            return dict(metrics=[dict(id=m['id'], title=m['title'], value=None, unit=m['unit'], grain=m['grain'], definitionVersion=m['version'], dataState='unavailable', sourceWatermark=None, sampleCount=None, reason='definition_not_activated') for m in metrics],
                        sources=self.source_health(), _dataState='unavailable', readOnly=True)
        if path == '/sources/health':
            self.require(principal, 'control.read')
            return dict(sources=self.source_health(), _dataState='partial')
        if path == '/dashboards':
            self.require(principal, 'control.read')
            return dict(dashboards=self.catalog.dashboards, definitions=list(self.catalog.metrics.values()), detectors=self.catalog.detectors, _dataState='unavailable')
        if path == '/users':
            self.require(principal, 'customers.read')
            return dict(users=self.store.read('users'), limit=200, scope='safe_metadata', _dataState='measured')
        if path.startswith('/users/'):
            self.require(principal, 'customers.read')
            user_id = identifier(path.removeprefix('/users/'))
            rows = self.store.read('user', user_id)
            if not rows: raise ControlError('SOURCE_UNAVAILABLE', 404)
            return dict(user=rows[0], memberships=self.store.read('user_memberships', user_id), privateContent={'dataState':'suppressed', 'reason':'scoped_support_grant_required'}, financialActionsEnabled=False)
        if path == '/workspaces':
            self.require(principal, 'workspaces.read')
            return dict(workspaces=self.store.read('workspaces'), limit=200, scope='safe_metadata')
        if path == '/engineering':
            self.require(principal, 'engineering.read')
            rows=self.store.read('engineering')
            for row in rows:
                if row['kind']=='check' and row['state'] in ('checks_passed','merged','deployed','production_verified'):
                    row['observed_stage']=row['state']
                    row['state']='suspected'
                    row['qualification']='trusted_required_check_manifest_not_qualified'
            return dict(evidence=rows, stages=['suspected','reproduced','candidate_fix','checks_passed','merged','deployed','production_verified'], checksDispatchEnabled=False, patchEnabled=False, _dataState='partial')
        if path.startswith('/metrics/receipts/'):
            self.require(principal, 'metrics.query')
            rows = self.store.read('receipt', identifier(path.removeprefix('/metrics/receipts/')))
            if not rows: raise ControlError('SOURCE_UNAVAILABLE', 404)
            return dict(receipt=rows[0], _dataState=rows[0]['data_state'])
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
            return dict(run=run, _dataState='partial')
        if path == '/audit':
            self.require(principal, 'audit.read')
            return dict(events=self.store.audit_read(), limit=200)
        raise ControlError('SCOPE_DENIED', 404)

    def copilot_turn(self, request, principal):
        self.require(principal, 'copilot.use')
        self.require(principal, 'metrics.query')
        self.catalog.validate('copilot-turn', request)
        for evidence in request['contextEvidenceIds']:
            if not self.store.read('receipt', identifier(evidence)): raise ControlError('SCOPE_DENIED')
        # A deterministic intelligence mode has no paid model call, autonomous schedule or effect executor.
        # Customer/user prose is not interpolated into tools, SQL, log payloads or persisted conversations.
        run_id, cached = self.store.reserve_run(request, principal, hashlib.sha256(canonical(request).encode()).hexdigest())
        if cached is not None: return {**cached, 'runId':run_id}
        try:
            return self._copilot_read(request, principal, run_id)
        except Exception:
            self.store.save_run(dict(runId=run_id, state='blocked', code='SOURCE_UNAVAILABLE',
                                     answerText='Read investigation unavailable. No action was performed.',
                                     queryReceiptIds=[], changedEntities=[]), principal, request['conversationId'])
            raise

    def _copilot_read(self, request, principal, run_id):
        # Intent chooses only a named read template. It cannot add fields, instructions, recipients or actions.
        words=request['message'].casefold()
        metric_id='mrr' if any(word in words for word in ('mrr','revenue','recurring')) else 'refunds' if 'refund' in words else 'activation_rate'
        metric=self.catalog.metrics[metric_id]
        query = dict(metricIds=[metric_id], interval=dict(start=(datetime.now(timezone.utc)-timedelta(days=28)).isoformat(), end=iso_now(), timeZone='UTC'), groupBy=['currency'] if metric['currency_policy']=='native_currency_separate' else [], filters=[], comparison='none', limit=100)
        receipt = self.metric_query(query, principal, request['requestId'])
        run = empty_result(new_trace_id(), request['modality'])
        run.update(runId=run_id, namespace='founder', mode='deterministic_read_only',
                   answerText=f"{metric['title']} is unavailable: its versioned policy and source coverage have not been qualified. This deterministic mode selected a named read template; it performs no requested action. Review the definition and source-health evidence before drawing a business conclusion.",
                   speakableSummary=f"{metric['title']} data is unavailable. Its policy and source coverage need qualification.",
                   queryReceiptIds=[receipt['queryReceiptId']], recommendations=[], tools=[tool.public() for tool in FOUNDER_TOOLS if tool.permission in principal['operator']['capabilities']],
                   usage={'providerCalls':0,'costState':'not_applicable'}, warnings=[{'code':'MODEL_DISABLED','message':'Model generation and scheduled investigations are disabled pending explicit budget and access approval.'}])
        self.store.save_run(run, principal, request['conversationId'])
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

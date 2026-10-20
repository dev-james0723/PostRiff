"""Workspace-authorized X management, exact approvals and durable official API dispatch."""
import json
import os
import re

from postriff_alpha.domain import AlphaError
from .permissions import Membership, require
from . import x_direct_journal as journal
from .x_direct_executor import IMPLEMENTED_OPERATIONS, READ_OPERATIONS, POST_OPERATIONS, execute, reconcile_post, plain
from .x_release import acceptance_allowed, connection_allowed, management_allowed, publishing_allowed

REQUEST_EVIDENCE_FIELDS = frozenset(('normalizedFingerprint','estimatedCostMicros',
    'estimatedMaxCostMicros','maximumApiRequests','approvedMedia'))
PUBLISH_OPERATIONS = POST_OPERATIONS | frozenset(('posts.thread',))
SENSITIVE_OPERATIONS = frozenset(('posts.delete','blocks.create','blocks.delete','dm.delete','lists.delete'))


def requirement(operation):
    if operation == 'posts.hide_reply':
        return 'moderate'
    if operation in ('posts.reply','dm.send','dm.conversation.send','dm.group.create'):
        return 'reply'
    return 'approve'


def view(item):
    return {'id': item['id'], 'connectionId': item['connection_id'], 'accountId': item['provider_account_id'],
            'operation': item['operation_id'], 'request': item['request'], 'digest': item['digest'],
            'state': item['state'], 'createdAt': item['created_at'], 'expiresAt': item['preview_expires_at'],
            'approvedAt': item['approved_at'], 'scheduledAt': item['next_at'],
            'cancelRequested': item['cancel_requested'], 'attempts': item['attempts'], 'checks': item['checks'],
            'receipts': item['receipts'], 'reasonCode': item['reason_code'], 'reason': item['reason'],
            'evidenceClass': 'provider_response' if item['receipts'] else 'Rafii operation record'}


class XDirectService:
    def __init__(self, service, cost=None):
        self.service, self.repository, self.oauth, self.clock = service, service.repository, service.oauth, service.clock
        self.provider = self.oauth.providers.get('x')
        self.cost = cost
        if self.provider is not None and cost is None:
            from .x_direct_cost import XCostController, XCostPolicy
            import hashlib
            self.cost = XCostController(self.repository.connection_factory,
                XCostPolicy.from_environment(os.environ),
                app_key=hashlib.sha256(self.provider.client_id.encode()).hexdigest(), clock=self.clock)
        self.oauth.x_direct = self
        if self.provider is not None:
            self.provider.cost_admission_ready = bool(self.cost and self.cost.ready)
            self.provider.cost_capability_ready = self.capability_ready
            self.provider.implemented_capabilities = frozenset(('identity','publish','schedule','reply','analytics','moderate'))

    def request_context(self, workspace, connection, operation):
        if self.cost is None:
            raise AlphaError('Unavailable — X API cost admission is not configured.', 503,
                             code='x_cost_admission_required')
        return self.cost.context(workspace, connection, operation)

    def _credential(self, cur, workspace, connection):
        if not isinstance(connection, str) or not re.fullmatch(r'[0-9a-f]{32}', connection):
            raise AlphaError('X connection unavailable.', 404)
        cur.execute("""SELECT provider_account_id,access_ciphertext,key_id,scopes
            FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s
            AND provider='x' AND revoked_at IS NULL""", (workspace, connection))
        stored = cur.fetchone()
        if not stored or self.provider is None:
            raise AlphaError('X connection unavailable.', 404)
        account, ciphertext, key_id, scopes = stored
        access = self.oauth.vault.decrypt(ciphertext, key_id)
        generation = self.provider.authorization_generation(access)
        from .x_resource_evidence import entitlements
        access = entitlements(cur,workspace,connection,generation,self.clock())
        return {'account':str(account),'generation':generation,'scopes':list(scopes or []),'resourceAccess':access}

    def _normalize(self, workspace, connection, credential, body, cur=None, *, readback_media=None):
        from .x_direct_contract import normalize_operation, ContractValidationError
        allowed = {'operation','path','body','query','maxBillableResources','requestKey','scheduleAt'}
        if not isinstance(body, dict) or not set(body) <= allowed:
            raise AlphaError('Use a structured X operation.', 400, code='x_operation_input')
        media_upload = body.get('operation') == 'media.upload'
        if media_upload and (not getattr(self.service, 'assets', None) or not self.cost):
            raise AlphaError('Unavailable — verified private media storage or upload pricing is not configured.', 503,
                             code='x_media_workflow_unavailable')
        if cur is None and (media_upload or (isinstance(body.get('body'), dict) and body['body'].get('media'))):
            with self.repository.connection_factory() as db, db.cursor() as nested:
                return self._normalize(workspace, connection, credential, body, nested, readback_media=readback_media)
        if media_upload:
            from .x_direct_media import plan_input
            return plan_input(cur, workspace, connection, credential, body, self.cost.policy.unit_prices)
        try:
            request = normalize_operation(body.get('operation'), workspace_id=workspace, account_id=connection,
                actor_user_id=credential['account'], path_params=body.get('path'), body=body.get('body'),
                query=body.get('query'), max_billable_resources=body.get('maxBillableResources', 1))
            if request.operation_id in POST_OPERATIONS and request.body.get('media'):
                from .x_direct_media import verified_attachments
                ids = request.body['media']['media_ids']
                proofs = (readback_media if readback_media is not None else
                          verified_attachments(cur, workspace, connection, credential, ids, self.clock()))
                if not isinstance(proofs, dict) or set(proofs) != set(ids):
                    raise AlphaError('Exact uploaded-media ownership evidence is required.', 409, code='x_media_ownership_required')
                scheduled = body.get('scheduleAt')
                if readback_media is None and scheduled is not None:
                    import math
                    if (type(scheduled) not in (int, float) or not math.isfinite(scheduled)
                            or any(scheduled + 60 >= proof['expiresAt'] for proof in proofs.values())):
                        raise AlphaError('Upload later or schedule before the X media expires.', 409, code='x_media_schedule_expired')
                credential['mediaAccess'] = proofs
                credential['resourceAccess'] = credential.get('resourceAccess', frozenset()) | frozenset('uploaded_media:' + rid for rid in ids)
            return request
        except ContractValidationError as error:
            raise AlphaError(error.reason, 400, code=error.reason_code) from error

    def _context(self, workspace, connection, credential, request=None, *, approved=False):
        from .x_direct_contract import DirectContext, CostAdmission
        from .x_access_evidence import current_access
        access = current_access(self.provider, self.clock())
        admission = None
        if request is not None and request.estimated_cost_micros is not None and self.cost is not None and self.cost.eligible_request(request, workspace_id=workspace):
            admission = CostAdmission(workspace_id=workspace, account_id=connection,
                operation_id=request.operation_id, request_fingerprint=request.fingerprint,
                admitted_micros=request.estimated_cost_micros)
        implementations = (IMPLEMENTED_OPERATIONS | frozenset(('posts.thread',))) if management_allowed(self.provider, workspace) else frozenset()
        if self._media_configured() and management_allowed(self.provider, workspace):
            implementations |= frozenset(('media.upload',))
        if not publishing_allowed(self.provider, workspace):
            implementations = implementations - PUBLISH_OPERATIONS
        return DirectContext(workspace_id=workspace, account_id=connection, actor_user_id=credential['account'],
            granted_scopes=frozenset(credential['scopes']), implemented_operations=implementations,
            verified_entitlements=access['entitlements'] | credential.get('resourceAccess',frozenset()),
            app_public_access_verified=access['publicCustomerVerified'],
            app_acceptance_lane_authorized=acceptance_allowed(self.provider, workspace),
            approved_request_fingerprint=request.fingerprint if request is not None and approved else None,
            approval_direct_user_initiated=approved, cost_admission=admission)

    def _media_configured(self):
        from .x_direct_cost import MEDIA_PRICE_KEYS
        return bool(getattr(self.service, 'assets', None) and self.cost and self.cost.ready
                    and MEDIA_PRICE_KEYS <= self.cost.policy.allowed_price_keys
                    and MEDIA_PRICE_KEYS <= self.cost.policy.unit_prices.keys())

    def _decision(self, workspace, connection, credential, body, request, *, approved, preview=False):
        from .x_direct_contract import evaluate_direct_operation, execution_authority, DirectDecision, CAPABILITIES
        if request.operation_id == 'media.upload':
            context = self._context(workspace, connection, credential, request, approved=approved)
            denied = execution_authority(request, context)
            if denied and not (preview and denied.reason_code == 'x_approval_required'):
                raise AlphaError(denied.reason, 409, code=denied.reason_code)
            if context.cost_admission is None:
                raise AlphaError('Unavailable — the complete media workflow exceeds its current evidenced cost allowance.',
                                 409, code='x_cost_admission_required')
            return DirectDecision('direct', 'x_media_plan_ready',
                'Exact upload plan only; no external bytes sent before interactive approval.',
                CAPABILITIES['media.upload'], request, True)
        decision = evaluate_direct_operation(request.operation_id,
            self._context(workspace, connection, credential, request, approved=approved),
            path_params=body.get('path'), body=body.get('body'), query=body.get('query'),
            max_billable_resources=body.get('maxBillableResources', 1))
        if decision.status != 'direct' and not (preview and decision.reason_code == 'x_approval_required'):
            raise AlphaError(decision.reason, 409, code=decision.reason_code)
        return decision

    def overview(self, workspace, token, connection):
        from .hosted import _membership
        from .x_direct_contract import list_capabilities, CONTRACT_VERSION
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), 'read')
            credential = self._credential(cur, workspace, connection)
            catalogue = list_capabilities(self._context(workspace, connection, credential))
            ready = journal.schema_ready(cur)
            operations = []
            if ready:
                cur.execute('SELECT ' + journal.SELECT + """ FROM public.pr_x_direct_operations
                    WHERE workspace_id=%s AND connection_id=%s ORDER BY created_at DESC LIMIT 50""",
                    (workspace, connection))
                stored_operations = [journal.row_value(value) for value in cur.fetchall()]
                operations = [view(item) for item in stored_operations]
            else:
                stored_operations = []
            from .x_direct_media import _asset, verified_attachments
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
            source_row = cur.fetchone()
            source_state = json.loads(source_row[0]) if source_row and isinstance(source_row[0], str) else source_row[0] if source_row else {}
            media_assets = []
            for asset in reversed((source_state.get('phase2') or {}).get('assets', [])):
                if len(media_assets) >= 200:
                    break
                try:
                    safe = _asset(asset)
                    media_assets.append({key: safe[key] for key in ('id', 'mime', 'bytes')})
                except (AlphaError, TypeError, AttributeError):
                    continue
            uploaded_media = []
            for item in stored_operations:
                if item['operation_id'] != 'media.upload' or item['state'] != 'verified':
                    continue
                rid = (item['progress'].get('media') or {}).get('id')
                try:
                    proofs = verified_attachments(cur, workspace, connection, credential, [rid], self.clock())
                    uploaded_media.append({'id': rid, **proofs[rid]})
                except AlphaError:
                    continue
        return {'connectionId': connection, 'accountId': credential['account'], 'contractVersion': CONTRACT_VERSION,
                'capabilities': [{**plain(entry), 'capability': {**plain(entry.capability),
                    'input_path_params': list(entry.capability.input_path_params),
                    'path_params': list(entry.capability.path_params), 'mutates': entry.capability.mutates}}
                    for entry in catalogue], 'operations': operations, 'journalReady': ready,
                'mediaAssets': media_assets, 'uploadedMedia': uploaded_media,
                'costReady': bool(self.cost and self.cost.ready),
                'publicAcceptance': 'not_proven_by_configuration', 'directOnly': True}

    def preview_in_transaction(self, cur, workspace, actor, connection, body):
        credential = self._credential(cur, workspace, connection)
        request = self._normalize(workspace, connection, credential, body, cur)
        if request.operation_id in READ_OPERATIONS:
            raise AlphaError('Choose a management action for approval, or explicitly request a read.', 400)
        # This eligibility check evaluates the exact proposed request. It is not an approval or a provider call.
        self._decision(workspace, connection, credential, body, request, approved=False, preview=True)
        if body.get('scheduleAt') is not None and request.operation_id not in PUBLISH_OPERATIONS:
            raise AlphaError('Only explicitly approved posts can be scheduled here. Interactions require a direct user action.', 409,
                             code='x_interaction_scheduling_unavailable')
        payload = {key: plain(value) for key, value in body.items() if key != 'requestKey'}
        payload['body'] = plain(body.get('body', {})) if request.operation_id == 'media.upload' else plain(request.body)
        if credential.get('mediaAccess'):
            payload['approvedMedia'] = plain(credential['mediaAccess'])
        payload['query'] = plain(request.query)
        payload['maxBillableResources'] = request.max_billable_resources
        payload['normalizedFingerprint'] = request.fingerprint
        payload['estimatedCostMicros'] = request.estimated_cost_micros
        from .x_direct_cost import operation_budget
        budget = operation_budget(request, self.cost.policy.unit_prices)
        payload.update({key:budget[key] for key in ('estimatedMaxCostMicros','maximumApiRequests')})
        item = journal.create(cur, workspace=workspace, connection=connection, account=credential['account'],
            generation=credential['generation'], actor=actor, operation_id=request.operation_id,
            request_key=body.get('requestKey'), request=payload, now=self.clock())
        from .hosted import audit
        audit(cur, workspace, actor, 'x.operation_proposed', item['id'],
              {'operation': request.operation_id, 'digest': item['digest'], 'execution': 'none'})
        return view(item)

    def preview(self, workspace, token, connection, body):
        from .hosted import _membership
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), 'edit')
            return self.preview_in_transaction(cur, workspace, actor, connection, body)

    def approve(self, workspace, token, connection, operation, body):
        if not isinstance(body, dict) or set(body) != {'digest', 'confirmed'}:
            raise AlphaError('Approve the exact X operation shown in Rafii.', 400, code='x_exact_approval_required')
        from .hosted import _membership, audit
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError('An interactive customer approval is required for X actions.', 403,
                             code='x_interactive_approval_required')
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            item = journal.read(cur, workspace, operation, lock=True)
            if item['connection_id'] != connection:
                raise AlphaError('X operation unavailable.', 404)
            require(_membership(row), requirement(item['operation_id']))
            self.repository.assert_fresh(token, actor)
            credential = self._credential(cur, workspace, connection)
            if credential['generation'] != item['authorization_generation']:
                raise AlphaError('X authorization changed. Prepare a new approval.', 409, code='x_authorization_changed')
            saved = {key: value for key, value in item['request'].items()
                     if key not in REQUEST_EVIDENCE_FIELDS}
            request = self._normalize(workspace, connection, credential, saved, cur)
            if request.fingerprint != item['request']['normalizedFingerprint']:
                raise AlphaError('The X API contract changed. Prepare a new approval.', 409, code='x_contract_changed')
            if credential.get('mediaAccess', {}) != item['request'].get('approvedMedia', {}):
                raise AlphaError('The approved X media changed. Prepare a new review.', 409, code='x_media_ownership_required')
            self._decision(workspace, connection, credential, saved, request, approved=True)
            item = journal.approve(cur, workspace, operation, actor, body.get('digest'),
                                   body.get('confirmed'), self.clock())
            audit(cur, workspace, actor, 'x.operation_approved', operation,
                  {'operation': item['operation_id'], 'digest': item['digest'], 'accountId': credential['account']})
        # Worker dispatch owns external execution after this approval commits.
        return view(item)

    def cancel(self, workspace, token, connection, operation):
        from .hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            item = journal.read(cur, workspace, operation, lock=True)
            if item['connection_id'] != connection:
                raise AlphaError('X operation unavailable.', 404)
            require(_membership(row), requirement(item['operation_id']))
            item = journal.cancel(cur, workspace, operation, self.clock())
            audit(cur, workspace, actor, 'x.operation_canceled', operation)
            return view(item)

    def read(self, workspace, token, connection, body):
        from .hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), 'read')
            credential = self._credential(cur, workspace, connection)
            request = self._normalize(workspace, connection, credential, body, cur)
            if request.operation_id not in READ_OPERATIONS:
                raise AlphaError('This action requires an exact approval.', 409, code='x_exact_approval_required')
            self._decision(workspace, connection, credential, body, request, approved=False)
            audit(cur, workspace, actor, 'x.read_requested', connection,
                  {'operation': request.operation_id, 'requestFingerprint': request.fingerprint})
        grant = {**self.oauth.token_for_worker(workspace, connection), 'workspaceId': workspace, 'connectionId': connection}
        if grant.get('authorizationGeneration') != credential['generation']:
            raise AlphaError('X authorization changed. Reload this account.', 409, code='x_authorization_changed')
        with self.request_context(workspace, connection, request.operation_id):
            result = execute(request, self.provider, grant, now=self.clock())
        # Recheck membership after I/O before returning private provider data.
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), 'read')
            current = self._credential(cur, workspace, connection)
            if current['generation'] != credential['generation']:
                raise AlphaError('X authorization changed while reading.', 409, code='x_authorization_changed')
            from .x_resource_evidence import record_read
            record_read(cur,workspace,connection,current,request,result,self.clock())
        return result

    def capability_ready(self,workspace,name):
        from .x_access_evidence import current_access
        from .x_direct_cost import PRICES
        access=current_access(self.provider,self.clock())
        key={'publish':'post_write','schedule':'post_write','reply':'post_write',
             'analytics':'post_read','moderate':'content_manage'}.get(name)
        if (not key or not self.cost or 'x_api_v2' not in access['entitlements']
                or not (access['publicCustomerVerified'] or acceptance_allowed(self.provider,workspace))):
            return False
        if name=='reply' and 'enterprise' not in access['entitlements']:
            return False
        keys={key,'post_read'} if name in ('publish','schedule','reply') else {key}
        writes = 0 if name=='analytics' else 3
        amount=(writes or 1)*PRICES[key]+(3*PRICES['post_read'] if len(keys)>1 else 0)
        return keys<=self.cost.policy.allowed_price_keys and self.cost.eligible(amount,workspace,
            request_count=6 if len(keys)>1 else (writes or 1))

    def _authority(self, cur, workspace, item):
        from . import security_holds
        from .billing import require_publishing
        try:
            if not item.get('approved_by'):
                return False
            security_holds.assert_clear(cur, item['approved_by'], authorized_at=item.get('approved_at'))
            require_publishing(cur, workspace, self.clock())
            cur.execute("""SELECT m.role,m.can_publish,m.can_reply,m.can_moderate
                FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
                WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active'
                  AND p.deleted_at IS NULL FOR SHARE OF m,p""", (workspace, item['approved_by']))
            member = cur.fetchone()
            return bool(member and Membership.from_row(member[0], can_publish=member[1],
                can_reply=member[2], can_moderate=member[3]).allows(requirement(item['operation_id'])))
        except AlphaError:
            return False


    def _prepare_thread(self,cur,workspace,claimed,credential):
        from . import x_direct_thread as thread
        body={k:v for k,v in claimed['request'].items() if k not in REQUEST_EVIDENCE_FIELDS}
        plan=self._normalize(workspace,claimed['connection_id'],credential,body,cur)
        progress=claimed['progress'].get('thread') or thread.initial_progress(plan)
        if claimed['cancel_requested']:
            progress=thread.cancel_thread(plan,progress)
        if claimed['progress']['phase']=='write':
            _,progress=thread.begin_step(plan,progress)
        else:
            child=thread.current_step(plan,progress)
            progress=thread.begin_readback(plan,progress,child)
        return journal.update(cur,workspace,claimed['id'],progress={**claimed['progress'],'thread':progress})

    def _thread_result(self,request,claimed,result):
        from . import x_direct_thread as thread
        progress=claimed['progress']['thread']
        child=thread.current_step(request,progress)
        if claimed['cancel_requested']:
            progress=thread.cancel_thread(request,progress)
        phase=claimed['progress']['phase']
        if phase=='write' and result['state']=='accepted':
            progress=thread.accept_step(request,progress,child,result['receipt']['resourceId'])
        elif phase=='reconcile' and result['state']=='verified':
            progress=thread.advance_step(request,progress,child,{'state':'verified','verification':'provider_lookup',
                'requestFingerprint':child.fingerprint,'reference':result['receipt']['resourceId']})
            result={**result,'state':{'complete':'verified','cancelled':'canceled'}.get(progress['state'],'queued'),
                'resetCounters':True,'nextAt':self.clock(),
                'reason':'The confirmed thread step is saved; remaining approved steps follow the durable queue.'}
        elif phase=='reconcile' and result['state']=='accepted':
            progress=thread.inconclusive_readback(request,progress,child)
            if progress['state'] in ('uncertain','cancelled_uncertain'):
                result={**result,'state':'uncertain','reasonCode':'x_thread_readback_exhausted',
                    'reason':'The bounded thread readback allowance is exhausted. No post will be repeated.'}
        else:
            progress=thread.uncertain_step(request,progress,child)
            if result['state']=='queued':
                result={**result,'state':'held','reason':'X rate-limited this thread step. Existing receipts are retained; a fresh review is required.'}
        return {**result,'progress':{**claimed['progress'],'thread':progress}}

    def _finish_result(self,cur,claimed,result):
        completed=journal.finish(cur,claimed,state=result['state'],now=self.clock(),
            receipt=result.get('receipt'),reason_code=result.get('reasonCode'),reason=result.get('reason'),
            next_at=result.get('nextAt'),progress=result.get('progress'),reset_counters=result.get('resetCounters',False))
        if completed:
            from .hosted import audit
            audit(cur,claimed['workspace_id'],claimed['approved_by'],'x.operation_result',claimed['id'],
                {'state':completed['state'],'operation':claimed['operation_id'],
                 'receiptCount':len(completed['receipts']),'reasonCode':completed['reason_code']})
        return completed

    def dispatch_one(self):
        if self.provider is None or self.cost is None or not self.cost.ready:
            return {'enabled': False, 'selected': False, 'reasonCode': 'x_cost_admission_required'}
        with self.repository.connection_factory() as db, db.cursor() as cur:
            if not journal.schema_ready(cur):
                return {'enabled': False, 'selected': False, 'reasonCode': 'x_direct_schema_required'}
            cur.execute("""SELECT w.id::text FROM public.pr_workspaces w
                WHERE NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'
                  AND EXISTS(SELECT 1 FROM public.pr_x_direct_operations o WHERE o.workspace_id=w.id
                    AND o.state IN ('queued','accepted','dispatching') AND o.next_at<=now()
                    AND (o.lease_until IS NULL OR o.lease_until<=now()))
                ORDER BY w.id LIMIT 1 FOR UPDATE OF w SKIP LOCKED""")
            selected = cur.fetchone()
            if not selected:
                return {'enabled': True, 'selected': False}
            workspace = selected[0]
            cur.execute("""SELECT id::text FROM public.pr_x_direct_operations
                WHERE workspace_id=%s AND state IN ('queued','accepted','dispatching') AND next_at<=now()
                  AND (lease_until IS NULL OR lease_until<=now())
                ORDER BY next_at,created_at LIMIT 1 FOR UPDATE SKIP LOCKED""", (workspace,))
            selected = cur.fetchone()
            if not selected:
                return {'enabled': True, 'selected': False}
            operation = selected[0]
            item = journal.read(cur, workspace, operation, lock=True)
            try:
                credential = self._credential(cur, workspace, item['connection_id'])
                allowed = management_allowed(self.provider, workspace)
                if item['operation_id'] in PUBLISH_OPERATIONS:
                    allowed = allowed and publishing_allowed(self.provider, workspace)
                claimed = journal.claim(cur, workspace, operation,
                    generation=credential['generation'], account=credential['account'],
                    authority=allowed and self._authority(cur, workspace, item), now=self.clock())
                if claimed and claimed['operation_id']=='posts.thread':
                    claimed=self._prepare_thread(cur,workspace,claimed,credential)
            except AlphaError as error:
                journal.update(cur, workspace, operation, state='held', reason_code=error.code or 'x_connection_unavailable',
                               reason='X authorization is unavailable; no request was dispatched.')
                return {'enabled': True, 'selected': True, 'state': 'held'}
        if not claimed:
            return {'enabled': True, 'selected': True}
        result = None
        request = None
        completed = None
        try:
            connection=claimed['connection_id']
            grant={**self.oauth.token_for_worker(workspace,connection),'workspaceId':workspace,'connectionId':connection}
            with self.repository.connection_factory() as db,db.cursor() as cur:
                # Lock order matches connection changes and cancellation: workspace,
                # credential, membership, operation. Hold through ONE bounded HTTP call.
                cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE",(workspace,))
                row=cur.fetchone()
                state=json.loads(row[0]) if row and isinstance(row[0],str) else row[0] if row else {}
                cur.execute("""SELECT connection_id FROM public.pr_encrypted_credentials
                    WHERE workspace_id=%s AND connection_id=%s AND provider='x' AND revoked_at IS NULL FOR SHARE""",
                    (workspace,connection))
                current=self._credential(cur,workspace,connection) if cur.fetchone() else None
                if (not row or state.get('accountDeletion') or state.get('accountBlock') or not current
                        or current['generation']!=claimed['authorization_generation']
                        or grant.get('authorizationGeneration')!=claimed['authorization_generation']
                        or not self._authority(cur,workspace,claimed)):
                    raise AlphaError('X authorization changed before execution.',409,code='x_authorization_changed')
                claimed=journal.assert_dispatch_fence(cur,claimed,self.clock())
                saved={k:v for k,v in claimed['request'].items() if k not in REQUEST_EVIDENCE_FIELDS}
                readback_media = claimed['request'].get('approvedMedia', {}) if claimed['progress']['phase'] == 'reconcile' else None
                request=self._normalize(workspace,connection,current,saved,cur,readback_media=readback_media)
                if current.get('mediaAccess', {}) != claimed['request'].get('approvedMedia', {}):
                    raise AlphaError('The reviewed X attachment evidence changed.', 409, code='x_media_ownership_required')
                grant['verifiedMedia'] = current.get('mediaAccess', {})
                if request.fingerprint!=claimed['request']['normalizedFingerprint']:
                    raise AlphaError('The approved X contract changed.',409,code='x_contract_changed')
                from .x_direct_cost import operation_budget
                budget = operation_budget(request, self.cost.policy.unit_prices)
                if (request.estimated_cost_micros!=claimed['request'].get('estimatedCostMicros')
                        or any(budget[key]!=claimed['request'].get(key) for key in ('estimatedMaxCostMicros','maximumApiRequests'))):
                    raise AlphaError('X pricing changed. Review this action again.',409,code='x_price_changed')
                if not management_allowed(self.provider,workspace):
                    raise AlphaError('X Direct execution is paused.',409,code='x_execution_paused')
                if claimed['progress']['phase']=='write':
                    from .x_direct_contract import execution_authority
                    denied=execution_authority(request,self._context(workspace,connection,current,request,approved=True))
                    if denied is not None:
                        raise AlphaError(denied.reason,409,code=denied.reason_code)
                sent=request
                if request.operation_id=='posts.thread':
                    from .x_direct_thread import current_step
                    sent=current_step(request,claimed['progress']['thread'])
                thread_context=(request,claimed['progress']['thread']) if request.operation_id=='posts.thread' else None
                with self.request_context(workspace,connection,sent.operation_id):
                    if request.operation_id == 'media.upload':
                        from .x_direct_media import advance_media
                        def before_media_send():
                            journal.assert_dispatch_fence(cur, claimed, self.clock())
                        result = advance_media(request, self.provider, grant, claimed['progress'],
                            self.service.assets.storage, now=self.clock(), before_send=before_media_send)
                    elif claimed['progress']['phase']=='reconcile':
                        result=reconcile_post(sent,self.provider,grant,journal.receipt_for(claimed),now=self.clock(),thread_context=thread_context)
                    else:
                        result=execute(sent,self.provider,grant,now=self.clock(),thread_context=thread_context)
                if request.operation_id=='posts.thread':
                    result=self._thread_result(request,claimed,result)
                completed=self._finish_result(cur,claimed,result)
            return {'enabled':True,'selected':True,'operationId':operation,
                    'state':completed['state'] if completed else 'uncertain'}
        except AlphaError as error:
            if result is not None:
                result={**result,'state':'uncertain','reasonCode':'x_result_persistence_failed',
                    'reason':'X returned a result that could not be finalized. Saved evidence is retained; no write is repeated.'}
            else:
                result={'state':'canceled' if error.code=='x_cancel_requested' else 'held',
                    'reasonCode':error.code or 'x_execution_unavailable','reason':str(error)}
        except Exception:
            # Preserve any actual response already received even if a commit failed.
            result={**(result or {}),'state':'uncertain','reasonCode':'x_dispatch_result_unknown',
                'reason':'The provider result could not be committed. No automatic write retry is allowed.'}
        with self.repository.connection_factory() as db,db.cursor() as cur:
            completed=self._finish_result(cur,claimed,result)
        return {'enabled':True,'selected':True,'operationId':operation,
                'state':completed['state'] if completed else 'uncertain'}


def handle_http(app, environ, start_response, service, token, method, parts):
    engine = getattr(service, 'x_direct', None)
    if engine is None:
        raise AlphaError('Unavailable — X Direct management is not configured.', 503, code='x_direct_unavailable')
    workspace, connection = parts[2], parts[4]
    tail = parts[5:]
    if not tail and method == 'GET':
        return app._json(start_response, 200, engine.overview(workspace, token, connection))
    if tail == ['preview'] and method == 'POST':
        return app._json(start_response, 201, engine.preview(workspace, token, connection, app._body(environ)))
    if tail == ['read'] and method == 'POST':
        return app._json(start_response, 200, engine.read(workspace, token, connection, app._body(environ)))
    if len(tail) == 3 and tail[0] == 'operations' and method == 'POST':
        body = app._body(environ)
        if tail[2] == 'approve':
            return app._json(start_response, 202, engine.approve(workspace, token, connection, tail[1], body))
        if tail[2] == 'cancel':
            return app._json(start_response, 200, engine.cancel(workspace, token, connection, tail[1]))
    raise AlphaError('This X management route is unavailable.', 404)

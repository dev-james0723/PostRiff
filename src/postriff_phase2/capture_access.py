"""Narrow authenticated access to opt-in writer audit capture; default off."""
import base64
import re
import uuid
from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
from postriff_alpha.domain import AlphaError
from .permissions import require
from . import request_capture


def _identifier(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise AlphaError('A valid private audit identifier is required.', 400) from error


def _nonce(body):
    value = body.get('serverNonce') if isinstance(body, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', value):
        raise AlphaError('A valid single-run audit consent nonce is required.', 400)
    return value


def _managed_writer(runtime):
    from .model_runtime import ServerModelRuntime, model_transport, DEFAULT_ENDPOINT
    if (not isinstance(runtime, ServerModelRuntime) or runtime.asynchronous
            or runtime.transport is not model_transport or runtime.endpoint != DEFAULT_ENDPOINT):
        raise AlphaError('This audit requires the managed Gateway HTTPS writer.', 409)


def from_environment(ideas, values):
    if values.get('RAFII_REQUEST_CAPTURE_ENABLED') != '1':
        return None
    def key(name):
        try:
            return base64.b64decode(values.get(name, ''), validate=True)
        except ValueError as error:
            raise ValueError('Invalid private audit key configuration.') from error
    service = request_capture.CaptureService(
        request_capture.PostgresCaptureRepository(ideas.repository.connection_factory),
        key('RAFII_CAPTURE_ENCRYPTION_KEY'), key('RAFII_CAPTURE_SIGNING_KEY'),
        values.get('RAFII_CAPTURE_KEY_ID', ''), values.get('VERCEL_GIT_COMMIT_SHA') or values.get('RAFII_CAPTURE_SOURCE_SHA', ''),
        values.get('RAFII_CAPTURE_WORKSPACE_ID', ''))
    return CaptureAccess(ideas, service)


def purge_expired(repository):
    """Keep expiry cleanup alive after the capture feature is disabled or rolled back."""
    with repository.connection_factory() as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regprocedure('audit_private.capture_operation(text,jsonb)')")
            if cur.fetchone()[0] is None:
                return 'not_installed'
            request_capture.PostgresCaptureRepository(repository.connection_factory).call('purge', {}, cursor=cur)
    return 'ok'


class CaptureAccess:
    def __init__(self, ideas, service):
        self.ideas, self.service = ideas, service

    def actor(self, workspace_id, token):
        from .api_tokens import is_api_token
        if is_api_token(token) or workspace_id != self.service.allowlisted_workspace:
            raise AlphaError('Private audit capture is unavailable.', 403)
        with self.ideas.repository.transaction(token, workspace_id) as (cur, row, actor):
            require(self.ideas._member(row), 'owner')
            from .developer_usage import ai_usage_exempt
            if ai_usage_exempt(actor):
                raise AlphaError('Private audit requires an ordinary account.', 403)
            cur.execute("SELECT 1 FROM rafii_control.platform_operators WHERE user_id=%s AND status='active' LIMIT 1", (actor,))
            if cur.fetchone():
                raise AlphaError('Private audit requires a non-operator account.', 403)
        return actor

    def status(self, workspace_id, token):
        actor = self.actor(workspace_id, token)
        return {'enabled': True, 'actorId': actor, 'workspaceId': workspace_id,
                'consentVersion': request_capture.CONSENT_VERSION, 'ttlSeconds': 3600,
                'publicKey': base64.b64encode(self.service.public_key).decode(),
                'keyId': self.service.key_id, 'sourceSha': self.service.deployment_sha,
                'retention': 'Encrypted request and response retained for at most one hour; only you can read them. Revocation stops access. Encrypted backups follow the database backup retention policy.'}

    def credits(self, workspace_id, token, model=None):
        self.actor(workspace_id, token)
        runtime, _, _ = self.ideas.resolve_writer(self.ideas._state_reader(workspace_id, token), model)
        from .model_runtime import model_transport
        _managed_writer(runtime)
        response = model_transport('GET', 'https://ai-gateway.vercel.sh/v1/credits',
                                   headers={'Authorization': 'Bearer ' + runtime.api_key})
        data = response.get('body') or {}
        if response.get('status') != 200 or not isinstance(data, dict):
            raise AlphaError('The mounted writer credit balance could not be verified.', 503)
        try:
            balance = Decimal(str(data['balance']))
            if not balance.is_finite() or balance < 0:
                raise InvalidOperation
        except (KeyError, InvalidOperation, ValueError) as error:
            raise AlphaError('The mounted writer returned no usable credit balance.', 503) from error
        return {'balanceUsd': str(balance), 'totalUsedUsd': str(data.get('total_used', 'unknown')),
                'source': 'GET /v1/credits using the same mounted key as the selected writer', 'modelCalls': 0}

    def create(self, workspace_id, token, body):
        actor = self.actor(workspace_id, token)
        runtime, _, _ = self.ideas.resolve_writer(self.ideas._state_reader(workspace_id, token), body.get('model'))
        _managed_writer(runtime)
        if body.get('consentVersion') != request_capture.CONSENT_VERSION:
            raise AlphaError('Confirm the current audit retention notice.', 400)
        try:
            return self.service.create_grant(workspace_id=workspace_id, actor_id=actor, route=runtime.endpoint,
                reader_ids=[actor], confirmed=body.get('confirmed'), consent_version=body['consentVersion'], ttl_seconds=3600)
        except request_capture.AuditCaptureBlocked as error:
            raise AlphaError(str(error), 403, code='audit_capture_blocked') from error

    def read(self, workspace_id, token, capture_id, body):
        actor = self.actor(workspace_id, token)
        capture_id, nonce = _identifier(capture_id), _nonce(body)
        try:
            return self.service.read_capture(capture_id=capture_id, workspace_id=workspace_id,
                                            reader_id=actor, grant_nonce=nonce)
        except request_capture.AuditCaptureBlocked as error:
            raise AlphaError(str(error), 403, code='audit_capture_blocked') from error

    def list(self, workspace_id, token, grant_id, body):
        actor = self.actor(workspace_id, token)
        grant_id, nonce = _identifier(grant_id), _nonce(body)
        try:
            return self.service.list_captures(grant_id=grant_id, workspace_id=workspace_id,
                                             reader_id=actor, grant_nonce=nonce)
        except request_capture.AuditCaptureBlocked as error:
            raise AlphaError(str(error), 403, code='audit_capture_blocked') from error

    def privacy_changed(self, cur, workspace_id, before, after, actor):
        if workspace_id != self.service.allowlisted_workspace:
            return
        old = {s['id']: s for s in before.get('sources', [])}
        new = {s['id']: s for s in after.get('sources', [])}
        privacy_keys = ('active', 'sourcePolicy', 'cloudConsent', 'consent', 'grants', 'deleted',
                        'egressConsent', 'useApprovals', 'useGrants', 'purposeGrants', 'routeGrants', 'grantRevision', 'selected')
        revoked_source = any(sid not in new or any(old[sid].get(k) != new[sid].get(k) for k in privacy_keys) for sid in old)
        privacy_change = any(before.get(k) != after.get(k) for k in ('memoryEgress', 'accountDeletion', 'accountBlock'))
        old_learning, new_learning = before.get('learning') or {}, after.get('learning') or {}
        reset = old_learning.get('resetAt') != new_learning.get('resetAt') and bool(new_learning.get('resetAt'))
        if revoked_source or privacy_change or reset:
            self.service.revoke_workspace(cur, workspace_id=workspace_id, actor_id=actor)

    def revoke(self, workspace_id, token, grant_id, body):
        actor = self.actor(workspace_id, token)
        grant_id, nonce = _identifier(grant_id), _nonce(body)
        try:
            self.service.revoke_grant(grant_id=grant_id, workspace_id=workspace_id, actor_id=actor,
                                      server_nonce=nonce)
        except request_capture.AuditCaptureBlocked as error:
            raise AlphaError(str(error), 403, code='audit_capture_blocked') from error
        return {'revoked': True}


def requested(payload):
    return 'auditCapture' in payload


def validate_payload(ideas, workspace_id, token, payload, runtime, text):
    """Refuse unsupported side calls, rather than silently omit them from an audit."""
    if not requested(payload):
        return
    from . import request_model, workflow_parse, automation_edit
    access = getattr(ideas, 'capture', None)
    if access is None:
        raise AlphaError('Private audit capture is not enabled.', 409, code='audit_capture_blocked')
    access.actor(workspace_id, token)
    grant = payload['auditCapture']
    if not isinstance(grant, dict):
        raise AlphaError('A single-run audit consent grant is required.', 400)
    _identifier(grant.get('grantId'))
    _nonce(grant)
    key = payload.get('idempotencyKey')
    if not isinstance(key, str) or not key.strip() or len(key) > 100 or payload.get('research') is not False:
        raise AlphaError('Audit capture requires an idempotency key and research turned off.', 400)
    _managed_writer(runtime)
    if payload.get('imageGeneration') or payload.get('attachments'):
        raise AlphaError('Audit capture supports the synchronous text writer only.', 409)
    if any(r.get('kind') == 'connector_item' for r in payload.get('references', []) if isinstance(r, dict)):
        raise AlphaError('Connector side calls are not covered by writer capture.', 409)
    state = ideas.repository.get(workspace_id, token)['state']
    names = [a['name'] for a in automation_edit.summaries(state)]
    if request_model.wants_reading(text) or workflow_parse.names_automation(text, names):
        raise AlphaError('This request needs an additional model route not covered by writer capture.', 409)


def bind(ideas, cur, workspace_id, actor, run_id, key, payload, runtime, reservation):
    if not requested(payload):
        return None
    access = ideas.capture
    grant = payload['auditCapture']
    try:
        access.service.bind_grant(cur, grant_id=grant['grantId'], server_nonce=grant['serverNonce'],
            workspace_id=workspace_id, actor_id=actor, run_id=run_id, idempotency_key=key)
    except request_capture.AuditCaptureBlocked as error:
        raise AlphaError(str(error), 403, code='audit_capture_blocked') from error
    return request_capture.CaptureScope(workspace_id, actor, run_id, grant['grantId'], grant['serverNonce'],
                                        runtime.endpoint, reservation_id=reservation['reservationId'])


def scope(ideas, bound):
    return request_capture.capture_scope(ideas.capture.service, bound) if bound else nullcontext()

"""Recoverable Founder Ops provisioning with existing restricted roles.

Commit 1 reserves one owner/environment ID and its internal classification.
Commit 2 creates that exact tenant, membership and state atomically. Resolution
verifies the active owner via bounded projections before using a reserved ID.
"""
from __future__ import annotations
import json
import logging
import os
import re
import time
import uuid
from .auth import ControlError
from .http import register_route

ENV = 'RAFII_FOUNDER_OPS_WORKSPACE_ID'
OPS_NAME = 'Rafii Ops (founder)'
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
LOG = logging.getLogger(__name__)


class OpsPolicyDisabled(ControlError):
    def __init__(self, blocker):
        super().__init__('POLICY_DISABLED', 409)
        self.blocker = blocker


def _uuid(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value.strip().lower()):
        return None
    return str(uuid.UUID(value.strip()))


def _unavailable(error):
    LOG.warning(json.dumps({'event': 'founder_ops.source_unavailable', 'exceptionType': type(error).__name__}))
    raise ControlError('SOURCE_UNAVAILABLE', 503) from None


def stored(store, operator_id):
    """Read the durable identity. Absence and database unavailability differ."""
    if store is None or not operator_id:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    try:
        with store.transaction() as con:
            row = con.execute('SELECT ops_workspace_id::text AS ops FROM rafii_control.founder_settings WHERE operator_id=%s AND environment=%s',
                              (operator_id, store.environment)).fetchone()
    except Exception as error:
        _unavailable(error)
    if row and row.get('ops') and not _uuid(row['ops']):
        raise OpsPolicyDisabled('ops_workspace_invalid')
    return _uuid(row['ops']) if row and row.get('ops') else None


def candidate(values, store, operator_id):
    raw = (values if values is not None else os.environ).get(ENV)
    if raw:
        workspace = _uuid(raw)
        if not workspace:
            raise OpsPolicyDisabled('ops_workspace_invalid')
        return workspace, 'environment'
    found = stored(store, operator_id)
    return (found, 'settings') if found else (None, None)


def ready(store, operator_id, workspace):
    """Fixed read-only metadata, environment-scoped. No raw tenant state."""
    if store is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    try:
        with store.transaction(read=True) as con:
            row = con.execute('SELECT w.id::text AS id,m.role,m.status,u.deleted,c.kind,c.environment '
                              'FROM rafii_control.safe_workspaces w '
                              'JOIN rafii_control.safe_memberships m ON m.workspace_id=w.id AND m.user_id=%s '
                              'JOIN rafii_control.safe_users u ON u.user_id=m.user_id '
                              'LEFT JOIN rafii_control.workspace_classifications c ON c.workspace_id=w.id '
                              'WHERE w.id=%s', (operator_id, workspace)).fetchone()
    except Exception as error:
        _unavailable(error)
    if not row:
        return False
    if row['role'] != 'owner' or row['status'] != 'active' or row['deleted'] or row['kind'] != 'internal' or row['environment'] != store.environment:
        raise OpsPolicyDisabled('ops_workspace_invalid')
    return True


def resolve(values=None, store=None, operator_id=None):
    workspace, source = candidate(values, store, operator_id)
    return (workspace, source) if workspace and ready(store, operator_id, workspace) else (None, None)


def _store(app):
    return getattr(getattr(app, 'queries', None), 'store', None)


def _operator(principal):
    return principal['operator']['user_id']


def get_ops(app, principal, request):
    store, operator = _store(app), _operator(principal)
    workspace, source = candidate(getattr(app, 'flags', None) or {}, store, operator)
    usable = bool(workspace and ready(store, operator, workspace))
    return {'workspaceId': workspace if usable else None, 'source': source,
            'name': OPS_NAME if source == 'settings' else None,
            'provisioningState': 'ready' if usable else ('reserved' if workspace else 'not_configured'),
            'canCreate': not usable and source != 'environment' and getattr(app, 'runtime', None) is not None}


def _consumer_factory(service):
    factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
    if factory is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return factory


def _reserve(store, operator):
    """Serialize allocation; classification commits before the tenant exists."""
    try:
        with store.transaction() as con:
            con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('founder_ops:' + store.environment + ':' + operator,))
            row = con.execute('SELECT ops_workspace_id::text AS ops FROM rafii_control.founder_settings WHERE operator_id=%s AND environment=%s',
                              (operator, store.environment)).fetchone()
            workspace = _uuid(row['ops']) if row and row.get('ops') else str(uuid.uuid4())
            con.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,set_by,environment) VALUES(%s,'internal','founder ops workspace',%s,%s) ON CONFLICT (workspace_id) DO NOTHING",
                        (workspace, operator, store.environment))
            classification = con.execute('SELECT kind,environment FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,)).fetchone()
            if not classification or classification['kind'] != 'internal' or classification['environment'] != store.environment:
                raise OpsPolicyDisabled('ops_workspace_invalid')
            con.execute('INSERT INTO rafii_control.founder_settings(operator_id,environment,ops_workspace_id,updated_at) VALUES(%s,%s,%s,now()) '
                        'ON CONFLICT (operator_id,environment) DO UPDATE SET ops_workspace_id=coalesce(founder_settings.ops_workspace_id,excluded.ops_workspace_id)',
                        (operator, store.environment, workspace))
        return workspace
    except ControlError:
        raise
    except Exception as error:
        _unavailable(error)


def create_ops(app, principal, request):
    if request.get('mode') != 'live':
        raise ControlError('VALIDATION_FAILED', 400)
    operator, store = _operator(principal), _store(app)
    if store is None or getattr(app, 'runtime', None) is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    workspace, source = candidate(getattr(app, 'flags', None) or {}, store, operator)
    if source == 'environment':
        if not ready(store, operator, workspace):
            raise OpsPolicyDisabled('ops_workspace_not_ready')
        return {'workspaceId': workspace, 'source': source, 'created': False}
    workspace = _reserve(store, operator)
    service = app.consumer()
    from postriff_phase2.auth import initial_phase2_state
    from postriff_phase2.hosted import audit
    try:
        with _consumer_factory(service)() as db:
            with db.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('founder_ops:' + store.environment + ':' + operator,))
                cur.execute('SELECT 1 FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL', (operator,))
                if cur.fetchone() is None:
                    raise ControlError('VALIDATION_FAILED', 409)
                cur.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s) ON CONFLICT(id) DO NOTHING RETURNING id::text', (workspace,))
                created = cur.fetchone() is not None
                if created:
                    cur.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections) VALUES(%s,%s,'owner','active',true,true,true,true)", (workspace, operator))
                    state = initial_phase2_state(workspace, operator, OPS_NAME, 'studio', time.time(), execution='hosted-candidate')
                    state['workspace']['name'] = OPS_NAME
                    from postriff_phase2.founder_policy import defaults
                    state['founderOps'] = {'operatorId': operator, 'environment': store.environment, 'version': 1, 'policy': defaults()}
                    state['phase2'].pop('trial', None)
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))
                    audit(cur, workspace, operator, 'workspace.created', '', {'kind': 'founder_ops'})
                cur.execute('SELECT role,status,can_publish,can_reply,can_moderate,can_manage_connections FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s', (workspace, operator))
                member = cur.fetchone()
                if member is None or tuple(member)[:2] != ('owner', 'active'):
                    raise OpsPolicyDisabled('ops_workspace_invalid')
                cur.execute('SELECT EXISTS(SELECT 1 FROM public.pr_trials WHERE workspace_id=%s) OR EXISTS(SELECT 1 FROM public.pr_subscriptions WHERE workspace_id=%s)', (workspace, workspace))
                if cur.fetchone()[0]:
                    raise OpsPolicyDisabled('ops_workspace_has_customer_billing')
            db.commit()
    except ControlError:
        raise
    except Exception as error:
        _unavailable(error)
    if not ready(store, operator, workspace):
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return {'workspaceId': workspace, 'source': 'settings', 'created': created, 'name': OPS_NAME}


register_route('GET', r'/ops-workspace', 'control.read', 'founder_ops', 'get_ops', demo_ok=True)
register_route('POST', r'/ops-workspace', 'control.settings', 'founder_ops', 'create_ops', budget='founder.action')

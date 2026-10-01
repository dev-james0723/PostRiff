"""Founder ops workspace (PRD §4.5, CONTRACTS §8.H): the internal workspace Founder Rafii's conversations, runs, ledger rows
and founder calls live in, so none of them appear in a customer workspace or a customer KPI.

Boundaries. Resolution is `RAFII_FOUNDER_OPS_WORKSPACE_ID` when the deployment sets it, else this founder's row in
`rafii_control.founder_settings` (070), read through the restricted session role. Creation (POST /ops-workspace,
control.settings, so a fresh second factor) runs once per founder and environment through the embedded consumer runtime's
own connection: one workspace, one active owner membership (no publishing or connection rights), the standard initial state
named "Rafii Ops (founder)", a content-free `workspace.created` audit row, then the internal classification and the setting.
It never creates a trial, a subscription or a connection, and a second call returns the existing workspace.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from .auth import ControlError
from .http import register_route

ENV = 'RAFII_FOUNDER_OPS_WORKSPACE_ID'
OPS_NAME = 'Rafii Ops (founder)'
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _uuid(value):
    if not isinstance(value, str) or not _UUID.match(value.strip().lower()):
        return None
    return str(uuid.UUID(value.strip()))


def stored(store, operator_id):
    """This founder's stored ops workspace in the store's environment, or None (also when 070 is not installed)."""
    if store is None or not operator_id:
        return None
    try:
        with store.transaction() as con:
            row = con.execute('SELECT ops_workspace_id::text AS ops FROM rafii_control.founder_settings WHERE operator_id=%s AND environment=%s',
                              (operator_id, store.environment)).fetchone()
    except Exception:  # noqa: BLE001 - a missing table or an unreachable store means "not configured", never a 503 here
        return None
    return _uuid(row['ops']) if row and row.get('ops') else None


def resolve(values=None, store=None, operator_id=None):
    """(workspace id, source): the deployment variable first, then the founder's stored setting; (None, None) when neither."""
    env = _uuid((values if values is not None else os.environ).get(ENV) or '')
    if env:
        return env, 'environment'
    found = stored(store, operator_id)
    return (found, 'settings') if found else (None, None)


def _store(app):
    return getattr(getattr(app, 'queries', None), 'store', None)


def _operator(principal):
    return principal['operator']['user_id']


def get_ops(app, principal, request):
    """GET /ops-workspace (control.read): where Founder Rafii runs, and whether it can be created here."""
    workspace, source = resolve(getattr(app, 'flags', None) or {}, _store(app), _operator(principal))
    return {'workspaceId': workspace, 'source': source, 'name': OPS_NAME if source == 'settings' else None,
            'canCreate': workspace is None and getattr(app, 'runtime', None) is not None}


def _consumer_factory(service):
    factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
    if factory is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return factory


def create_ops(app, principal, request):
    """POST /ops-workspace (control.settings + step-up): create the founder's internal workspace once, classify it internal and
    remember it. Idempotent: an existing one (variable or setting) is returned unchanged."""
    if request.get('mode') != 'live':
        raise ControlError('VALIDATION_FAILED', 400)
    operator, store = _operator(principal), _store(app)
    workspace, source = resolve(getattr(app, 'flags', None) or {}, store, operator)
    if workspace:
        return {'workspaceId': workspace, 'source': source, 'created': False}
    if store is None or getattr(app, 'runtime', None) is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    service = app.consumer()
    from postriff_phase2.auth import initial_phase2_state
    from postriff_phase2.hosted import audit
    with _consumer_factory(service)() as db:
        with db.cursor() as cur:
            cur.execute('SELECT 1 FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL', (operator,))
            if cur.fetchone() is None:
                raise ControlError('VALIDATION_FAILED', 409)
            cur.execute('INSERT INTO public.pr_workspaces DEFAULT VALUES RETURNING id::text')
            workspace = cur.fetchone()[0]
            cur.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections) "
                        "VALUES(%s,%s,'owner','active',false,false,false,false)", (workspace, operator))
            state = initial_phase2_state(workspace, operator, OPS_NAME, 'studio', time.time(), execution='hosted-candidate')
            state.setdefault('workspace', {})
            if isinstance(state['workspace'], dict):
                state['workspace']['name'] = OPS_NAME
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))
            audit(cur, workspace, operator, 'workspace.created', '', {'kind': 'founder_ops'})
        db.commit()
    with store.transaction() as con:
        con.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,set_by,environment) VALUES(%s,'internal','founder ops workspace',%s,%s) "
                    "ON CONFLICT (workspace_id) DO UPDATE SET kind='internal',reason=excluded.reason,set_by=excluded.set_by",
                    (workspace, operator, store.environment))
        con.execute('INSERT INTO rafii_control.founder_settings(operator_id,environment,ops_workspace_id,updated_at) VALUES(%s,%s,%s,now()) '
                    'ON CONFLICT (operator_id,environment) DO UPDATE SET ops_workspace_id=excluded.ops_workspace_id,updated_at=now()',
                    (operator, store.environment, workspace))
    return {'workspaceId': workspace, 'source': 'settings', 'created': True, 'name': OPS_NAME}


register_route('GET', r'/ops-workspace', 'control.read', 'founder_ops', 'get_ops', demo_ok=True)
register_route('POST', r'/ops-workspace', 'control.settings', 'founder_ops', 'create_ops', budget='founder.action')

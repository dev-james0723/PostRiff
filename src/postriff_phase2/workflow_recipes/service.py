"""Creator-scoped recipe configuration and explicit, immutable CF2 policy enrollment."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace

from postriff_alpha.domain import AlphaError
from ..permissions import require
from ..agent_runtime_v2 import agent_permissions, authz, capability_registry
from ..agent_runtime_v2.task_engine import flags
from . import catalog


def enabled(workspace_id, config=None):
    return (os.environ.get('RAFII_WORKFLOW_RECIPES_ENABLED') == '1'
            and workspace_id in {x.strip() for x in os.environ.get('RAFII_WORKFLOW_RECIPES_WORKSPACES', '').split(',')}
            and flags.enabled_for(workspace_id, config) and authz.mode_for(config, workspace_id) == 'enforce')


def schema_available(cur):
    cur.execute("SELECT to_regclass('public.pr_workflow_recipes'),to_regclass('public.pr_workflow_recipe_runs'),to_regclass('public.pr_agent_autopilot_policies')")
    return all(cur.fetchone())


def ready(cur):
    if not schema_available(cur):
        raise AlphaError('Workflow recipes are not available yet.', 503, code='workflow_recipes_unavailable')


def context(service, cur, w, principal):
    from ..hosted import MEMBER_COLUMNS
    cur.execute(f"SELECT w.revision,w.state,{MEMBER_COLUMNS} FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w FOR SHARE OF m,p", (w, principal))
    row = cur.fetchone()
    if not row:
        raise AlphaError('Workspace unavailable.', 403)
    member = service.ideas._member(row)
    require(member, 'edit')
    state = service.ideas._state(row)
    if state.get('accountDeletion') or state.get('accountBlock') or (state.get('workspace') or {}).get('sample'):
        raise AlphaError('Workflow recipes are unavailable in this workspace.', 403)
    return row, member, state


def scope(cur, w, config, state):
    if config['templateId'] == 'weekly_performance':
        channel = next((c for c in (state.get('phase2') or {}).get('channels', []) if c.get('id') == config['connectionId'] and not c.get('revoked')), None)
        if not channel:
            raise AlphaError('The selected account is unavailable.', 409, code='recipe_scope_changed')
    elif config.get('collectionId'):
        cur.execute('SELECT 1 FROM public.pr_library_collections WHERE workspace_id=%s AND id=%s FOR SHARE', (w, config['collectionId']))
        if not cur.fetchone():
            raise AlphaError('The selected collection is unavailable.', 409, code='recipe_scope_changed')


def load(cur, w, principal, recipe_id, *, lock=True):
    recipe_id = catalog.ident(recipe_id, 'recipe')
    cur.execute("SELECT replace(id::text,'-',''),version,status,config,policy_id::text,extract(epoch from event_cursor),consecutive_failures,extract(epoch from next_attempt_at) FROM public.pr_workflow_recipes WHERE workspace_id=%s AND created_by=%s AND id=%s" + (' FOR UPDATE' if lock else ''), (w, principal, recipe_id))
    row = cur.fetchone()
    if not row:
        raise AlphaError('Recipe unavailable.', 404)
    keys = ('id', 'version', 'status', 'config', 'policyId', 'eventCursor', 'consecutiveFailures', 'nextAttemptAt')
    out = dict(zip(keys, row))
    for key in ('eventCursor', 'nextAttemptAt'):
        out[key] = float(out[key]) if out[key] is not None else None
    return out


def policy_constraints(recipe):
    c = recipe['config']
    return {'recipeId': recipe['id'], 'recipeVersion': recipe['version'], 'templateId': c['templateId'],
            'templateVersion': c['templateVersion'], 'templateDigest': catalog.digest(catalog.TEMPLATES.get(c['templateId'])), 'inputsDigest': catalog.digest(c), 'notificationPolicy': c['notificationPolicy'],
            'timeZone': c['timeZone'], 'connectionIds': [c['connectionId']] if c.get('connectionId') else [],
            'collectionId': c.get('collectionId'), 'window': {'expiresAt': c['expiresAt']}}


def _audit(cur, w, actor, kind, ident, meta=None):
    from ..hosted import audit
    audit(cur, w, actor, 'recipe.' + kind, ident, meta or {})


def consent_receipt(cur, w, principal, grants, recipe, key, proof, now, *, revoke=False):
    material = {'recipeId': recipe['id'], 'version': recipe['version'], 'config': recipe['config'], 'revoke': revoke}
    fingerprint = catalog.digest(material)
    cur.execute('SELECT id::text,request_fingerprint FROM public.pr_agent_consent_receipts WHERE workspace_id=%s AND actor=%s AND idempotency_key=%s', (w, principal, key))
    existing = cur.fetchone()
    if existing:
        if existing[1] != fingerprint:
            raise AlphaError('This request key was used for different settings.', 409)
        return existing[0]
    cur.execute("INSERT INTO public.pr_agent_consent_receipts(workspace_id,user_id,actor,kind,source,epoch_before,epoch_after,preset_before,preset_after,scopes_before,scopes_after,widened,consent_version,copy_digest,catalogue_digest,step_up,idempotency_key,request_fingerprint,created_at) VALUES(%s,%s,%s,%s,'settings',%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s,%s,to_timestamp(%s)) RETURNING id::text",
                (w, principal, principal, 'autopilot_revoked' if revoke else 'autopilot_enabled', grants.user_epoch, grants.user_epoch,
                 grants.preset, grants.preset, json.dumps({'autopilotPolicyId': recipe.get('policyId')}), json.dumps(material), not revoke,
                 agent_permissions.CONSENT_VERSION, agent_permissions.COPY_DIGEST, authz.catalogue_digest(), json.dumps(proof), key, fingerprint, now))
    return cur.fetchone()[0]


class Recipes:
    def __init__(self, service, config=None):
        self.service, self.config = service, config
        self.clock = service.repository.clock

    def _require(self, cur, w):
        if not enabled(w, self.config):
            raise AlphaError('Workflow recipes are not available yet.', 404, code='workflow_recipes_unavailable')
        ready(cur)

    def list(self, w, token):
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            _, _member, state = context(self.service, cur, w, principal)
            # An authorized rollout probe is not a failed operation. Keep writes/reports on _require.
            if not enabled(w, self.config) or not schema_available(cur):
                return {'available': False}
            grants = agent_permissions.load(cur, w, principal, now=self.clock())
            cur.execute("SELECT replace(id::text,'-','') FROM public.pr_workflow_recipes WHERE workspace_id=%s AND created_by=%s ORDER BY updated_at DESC LIMIT 20", (w, principal))
            recipes = [load(cur, w, principal, i, lock=False) for (i,) in cur.fetchall()]
            cur.execute('SELECT id::text FROM public.pr_agent_autopilot_policies WHERE workspace_id=%s AND user_id=%s AND created_epoch=%s', (w, principal, grants.user_epoch))
            current_ids = {row[0] for row in cur.fetchall()}
            policies = {p.id: p for p in grants.autopilot if p.id in current_ids}
            for recipe in recipes:
                policy = policies.get(recipe['policyId'])
                recipe['policyCurrent'] = bool(policy and recipe['status'] == 'active' and policy.constraints == policy_constraints(recipe))
                recipe['usedOperations'] = int((policy.usage or {}).get('actionsTotal', 0)) if policy else None
            cur.execute("SELECT replace(id::text,'-',''),name FROM public.pr_library_collections WHERE workspace_id=%s ORDER BY name LIMIT 100", (w,))
            collections = [{'id': i, 'name': name} for i, name in cur.fetchall()]
            cur.execute("SELECT replace(r.id::text,'-',''),replace(r.recipe_id::text,'-',''),r.task_id::text,t.state,t.reason_code,(r.report IS NOT NULL),extract(epoch from r.created_at) FROM public.pr_workflow_recipe_runs r JOIN public.pr_agent_tasks t ON t.id=r.task_id WHERE r.workspace_id=%s AND r.created_by=%s ORDER BY r.created_at DESC,r.id DESC LIMIT 10", (w, principal))
            runs = [{'id': i, 'recipeId': recipe, 'taskId': task, 'state': status, 'reasonCode': reason, 'hasReport': report, 'createdAt': float(at)} for i, recipe, task, status, reason, report, at in cur.fetchall()]
            return {'available': True, 'permissionToken': grants.token(), 'explicitPermissions': grants.source == 'explicit',
                    'templates': list(catalog.TEMPLATES.values()), 'recipes': recipes, 'runs': runs, 'collections': collections,
                    'connections': [{'id': c['id'], 'name': c.get('account') or c.get('platform') or c['id']} for c in (state.get('phase2') or {}).get('channels', []) if c.get('id') and not c.get('revoked')]}

    def save(self, w, token, body, recipe_id=None):
        authz.human_only(token)
        if not isinstance(body, dict) or set(body) != {'settings', 'expectedVersion'}:
            raise AlphaError('Review the listed recipe settings.', 400)
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._require(cur, w)
            _, _, state = context(self.service, cur, w, principal)
            config = catalog.validate(body['settings'], self.clock())
            scope(cur, w, config, state)
            if recipe_id:
                catalog.integer(body['expectedVersion'], 1, 2147483647, 'Recipe version')
                old = load(cur, w, principal, recipe_id)
                if old['version'] != body['expectedVersion']:
                    raise AlphaError('This recipe changed. Reload it.', 409)
                self._stop(cur, w, principal, old, 'paused', 'settings_changed')
                cur.execute("UPDATE public.pr_workflow_recipes SET status='draft',config=%s::jsonb,policy_id=NULL,updated_at=now() WHERE id=%s", (json.dumps(config), old['id']))
                ident = old['id']
            else:
                if body['expectedVersion'] is not None:
                    raise AlphaError('A new recipe has no previous version.', 400)
                cur.execute("SELECT count(*) FROM public.pr_workflow_recipes WHERE workspace_id=%s AND created_by=%s AND status<>'revoked'", (w, principal))
                if cur.fetchone()[0] >= catalog.MAX_RECIPES:
                    raise AlphaError('Keep at most 5 personal recipes active or in draft.', 409)
                ident = uuid.uuid4().hex
                cur.execute('INSERT INTO public.pr_workflow_recipes(id,workspace_id,created_by,config,event_cursor) VALUES(%s,%s,%s,%s::jsonb,to_timestamp(%s))', (ident, w, principal, json.dumps(config), self.clock()))
            _audit(cur, w, principal, 'saved', ident)
            return load(cur, w, principal, ident)

    def enable(self, w, token, recipe_id, body):
        authz.human_only(token)
        if not isinstance(body, dict) or set(body) != {'expectedVersion', 'permissionToken', 'confirmed', 'requestKey'} or body['confirmed'] is not True:
            raise AlphaError('Inspect and explicitly authorize this recipe policy.', 400)
        catalog.integer(body['expectedVersion'], 1, 2147483647, 'Recipe version')
        key = body['requestKey']
        if not isinstance(key, str) or not 16 <= len(key) <= 100:
            raise AlphaError('Use a valid request key.', 400)
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._require(cur, w)
            _, member, state = context(self.service, cur, w, principal)
            recipe = load(cur, w, principal, recipe_id)
            grants = agent_permissions.load(cur, w, principal, now=self.clock())
            if recipe['version'] != body['expectedVersion'] or grants.token() != body['permissionToken']:
                raise AlphaError('Recipe or permissions changed. Reload and review again.', 409)
            if grants.source != 'explicit' or grants.ended:
                raise AlphaError('Choose explicit Rafii permissions before enabling a recipe.', 403)
            if recipe['status'] == 'active':
                return recipe
            if recipe['status'] == 'revoked' or recipe['config']['expiresAt'] <= self.clock() + 60:
                raise AlphaError('Update and review this recipe before enabling it.', 409)
            scope(cur, w, recipe['config'], state)
            proof = authz.require_step_up(self.service.repository, token, principal, now=self.clock(), reason='workflow_recipe')
            template = catalog.TEMPLATES[recipe['config']['templateId']]
            cap = capability_registry.get(template['capabilityId'])
            if cap is None or cap.risk != 'R0' or cap.cost != 'free' or not cap.background_eligible:
                raise AlphaError('This recipe requires a native action approval and cannot run automatically.', 403)
            policy_id = str(uuid.uuid4())
            limits = {k: recipe['config'][k] for k in ('actionsPerDay', 'actionsTotal', 'usdMicroPerDay')}
            constraints = policy_constraints(recipe)
            policy = agent_permissions.AutopilotPolicy(policy_id, frozenset([cap.capability_id]), constraints, limits, {}, float(recipe['config']['expiresAt']))
            decision = authz.decide(authz._registry_capability(cap), surface=authz.Surface('task_engine', cap.name, 'none'), member=member,
                                   grants=replace(grants, autopilot=(policy,)), state=state, actor=authz.Actor('autopilot', principal), target={'connectionId': recipe['config'].get('connectionId')}, now=self.clock())
            if decision.outcome != 'allow':
                raise AlphaError('Current permissions do not allow these scoped automatic reads.', 403, code='recipe_permission_required')
            receipt = consent_receipt(cur, w, principal, grants, recipe, 'recipe-enable:' + key, proof, self.clock())
            cur.execute('INSERT INTO public.pr_agent_autopilot_policies(id,workspace_id,user_id,capability_ids,constraints,limits,created_epoch,receipt_id,step_up_at,starts_at,expires_at) VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,to_timestamp(%s),to_timestamp(%s),to_timestamp(%s))',
                        (policy_id, w, principal, [cap.capability_id], json.dumps(constraints), json.dumps(limits), grants.user_epoch, receipt, proof['at'], self.clock(), recipe['config']['expiresAt']))
            cur.execute("UPDATE public.pr_workflow_recipes SET status='active',policy_id=%s,updated_at=now(),consecutive_failures=0,next_attempt_at=NULL,event_cursor=now() WHERE id=%s", (policy_id, recipe['id']))
            _audit(cur, w, principal, 'enabled', recipe['id'], {'policyId': policy_id, 'version': recipe['version']})
            return load(cur, w, principal, recipe['id'])

    def _stop(self, cur, w, principal, recipe, status, reason):
        if recipe.get('policyId'):
            cur.execute("UPDATE public.pr_agent_autopilot_policies SET revoked_at=coalesce(revoked_at,now()),revoke_reason=coalesce(revoke_reason,'revoked') WHERE id=%s AND workspace_id=%s AND user_id=%s", (recipe['policyId'], w, principal))
        cur.execute("UPDATE public.pr_workflow_recipes SET status=%s,version=version+1,updated_at=now() WHERE id=%s", (status, recipe['id']))
        # Stop admission and in-flight future steps; historical reports/receipts remain inspectable.
        cur.execute("UPDATE public.pr_agent_tasks SET cancel_requested_at=coalesce(cancel_requested_at,now()),cancel_requested_by=%s,reason_code='permission_revoked',updated_at=now() WHERE workspace_id=%s AND created_by=%s AND autopilot_policy_id=%s AND state IN ('queued','running','awaiting_approval','blocked')", (principal, w, principal, recipe.get('policyId')))
        _audit(cur, w, principal, status, recipe['id'], {'reason': reason})

    def stop(self, w, token, recipe_id, body):
        authz.human_only(token)
        if not isinstance(body, dict) or set(body) != {'expectedVersion', 'status'} or body['status'] not in ('paused', 'revoked'):
            raise AlphaError('Choose pause or revoke.', 400)
        catalog.integer(body['expectedVersion'], 1, 2147483647, 'Recipe version')
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._require(cur, w)
            context(self.service, cur, w, principal)
            recipe = load(cur, w, principal, recipe_id)
            if recipe['version'] != body['expectedVersion']:
                raise AlphaError('This recipe changed. Reload it.', 409)
            grants = agent_permissions.load(cur, w, principal, now=self.clock())
            consent_receipt(cur, w, principal, grants, recipe, f"recipe-stop:{recipe['id']}:{recipe['version']}:{body['status']}", {}, self.clock(), revoke=True)
            self._stop(cur, w, principal, recipe, body['status'], 'user_choice')
            return load(cur, w, principal, recipe_id)

    def run(self, runtime, w, token, recipe_id, body):
        authz.human_only(token)
        if not isinstance(body, dict) or set(body) != {'expectedVersion', 'requestKey'}:
            raise AlphaError('Send the reviewed recipe version and request key.', 400)
        catalog.integer(body['expectedVersion'], 1, 2147483647, 'Recipe version')
        key = body['requestKey']
        if not isinstance(key, str) or not 16 <= len(key) <= 80 or any(c.isspace() for c in key):
            raise AlphaError('Use a valid run request key.', 400)
        from .runner import admit
        from ..agent_runtime_v2.task_engine import executor
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._require(cur, w)
            recipe = load(cur, w, principal, recipe_id)
            if recipe['version'] != body['expectedVersion']:
                raise AlphaError('This recipe changed. Reload it.', 409)
            task = admit(cur, self, w, principal, recipe, self.clock(), manual_key=key)
        if task:
            executor.drive_inline(runtime, w, token, principal, task['taskId'], actor_kind='autopilot', seconds=90, max_steps=1)
        return self.list(w, token)

    def report(self, w, token, run_id):
        run_id = catalog.ident(run_id, 'report')
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._require(cur, w)
            _, member, state = context(self.service, cur, w, principal)
            cur.execute('SELECT report,task_id::text,inputs FROM public.pr_workflow_recipe_runs WHERE id=%s AND workspace_id=%s AND created_by=%s', (run_id, w, principal))
            run = cur.fetchone()
            if not run:
                raise AlphaError('Report unavailable.', 404)
            scope(cur, w, run[2], state)
            grants = agent_permissions.load(cur, w, principal, now=self.clock())
            template = catalog.TEMPLATES.get(run[2].get('templateId'))
            cap = capability_registry.get(template['capabilityId']) if template else None
            if cap is None:
                raise AlphaError('The report source is no longer available.', 403, code='agent_permission_revoked')
            decision = authz.decide(authz._registry_capability(cap), surface=authz.Surface('task_engine', cap.name, 'none'), member=member, grants=grants,
                                   state=state, actor=authz.Actor('human_ui', principal), target=run[2], now=self.clock())
            if decision.outcome != 'allow':
                raise AlphaError('Current source permissions do not allow this stored report.', 403, code='agent_permission_revoked')
            return {'id': run_id, 'taskId': run[1], 'inputs': run[2], 'report': run[0]}

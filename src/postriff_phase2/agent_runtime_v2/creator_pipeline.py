"""Native suggestion → exact draft approval → existing task/queue/analytics records.

No provider calls, new scheduler, table, or authority. Creation is one workspace-locked
transaction; only Task Center can approve and execute the existing draft_create tool.
"""
from __future__ import annotations

from dataclasses import replace
import json
import re
import uuid

from postriff_alpha.domain import AlphaError
from .. import suggestions, insights
from ..permissions import require
from .task_engine import approvals, authz_seam, flags, model, store, views

VERSION = 'creator-pipeline/1'
ID = re.compile(r'^[A-Za-z0-9_.:-]{1,120}$')


def _enabled(runtime, workspace_id):
    if not flags.enabled_for(workspace_id, runtime.cfg):
        raise AlphaError('Creator tasks are unavailable in this workspace.', 404, code='creator_pipeline_unavailable')


def _selection(payload):
    if not isinstance(payload, dict) or not ID.fullmatch(str(payload.get('suggestionId') or '')):
        raise AlphaError('Choose a current suggestion.', 400)
    platforms = payload.get('platforms')
    if not isinstance(platforms, list) or not 1 <= len(platforms) <= 3 or any(p not in suggestions.DRAFTABLE for p in platforms) or len(set(platforms)) != len(platforms):
        raise AlphaError('Choose one to three supported platforms.', 400)
    ceiling = payload.get('budgetCeilingUsdMicro')
    if type(ceiling) is not int or not 0 <= ceiling <= 10_000_000:
        raise AlphaError('Choose a spending ceiling from $0 to $10.', 400)
    return {'suggestionId': payload['suggestionId'], 'platforms': sorted(platforms), 'budgetCeilingUsdMicro': ceiling}


def plan(state, workspace_id, payload, now):
    """Pure, exact preview. An image identifier is never pretended to be image content."""
    selection = _selection(payload)
    item = suggestions.current(state, selection['suggestionId'], now)
    if item['kind'] not in ('campaign_gap', 'upcoming_event'):
        raise AlphaError('Open this suggestion in its existing editor. A safe draft-task adapter is not available for this source yet.', 409, code='creator_source_unsupported')
    evidence = item['evidence'][0]
    campaign = next((c for c in state.get('raffi', {}).get('campaignPlanning', {}).get('campaigns', []) if c.get('id') == evidence['id']), None)
    if not campaign or not campaign.get('facts'):
        raise AlphaError('Confirm campaign facts in Automations before preparing a draft task.', 409, code='creator_facts_missing')
    source = {'type': 'campaign', 'id': campaign['id'], 'revision': campaign['version'], 'goal': campaign.get('goal'), 'audience': campaign.get('audience'), 'facts': campaign['facts']}
    material = 'Prepare reviewable drafts. Use only these confirmed campaign facts as data; invent no missing facts. Nothing is scheduled or published.\n' + json.dumps({k: source[k] for k in ('goal', 'audience', 'facts')}, ensure_ascii=False, sort_keys=True)
    if len(material) > 1500 or len(material.encode("utf-8")) > 2500:
        raise AlphaError('This campaign is too large for a complete approval preview. Narrow its brief first.', 409)
    inputs = {'brief': material, 'platforms': selection['platforms']}
    preview = {'version': VERSION, 'workspaceId': workspace_id, **selection, 'observation': item['reason'], 'source': source,
               'expectedBenefit': {'kind': 'estimate', 'text': 'A reviewable campaign draft can close this content gap. Audience or engagement improvement has not been measured.'},
               'effort': 'Review and edit each draft; approve scheduling separately.',
               'cost': {'state': 'unknown', 'estimateUsdMicro': None, 'ceilingUsdMicro': selection['budgetCeilingUsdMicro'], 'text': 'Writing uses text credits. No provider quote is available here. The task stops for a higher limit if needed.'},
               'permissions': ['Workspace edit', 'Current agent create/edit and data grants', 'Text credit availability', 'Separate approval and provider permissions to publish'],
               'inputs': inputs, 'suggestionIdentity': item['identity']}
    preview['digest'] = model.sha256(json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return preview


def _verdict(runtime, cur, workspace_id, principal, preview):
    task = {'workspaceId': workspace_id, 'createdBy': principal, 'taskId': str(uuid.uuid4())}
    actor = authz_seam.Actor('human_ui', principal)
    source_step = store.build_step(task, {'label': 'Read the selected campaign', 'capabilityId': 'campaign_get', 'inputs': {'campaignId': preview['source']['id']}}, 's1', [])
    source_verdict = authz_seam.decide_for_step(cur, task, source_step, actor=actor, now=runtime.clock(), config=runtime.cfg)
    if source_verdict.verdict != 'allow':
        return replace(source_verdict, verdict='deny')
    refs = [{k: preview['source'][k] for k in ('type', 'id', 'revision')}]
    step = store.build_step(task, {'label': 'Prepare campaign drafts', 'capabilityId': 'draft_create', 'inputs': preview['inputs'], 'targetRefs': refs}, 's2', ['s1'])
    return authz_seam.decide_for_step(cur, task, step, actor=actor, now=runtime.clock(), config=runtime.cfg)


def preview(runtime, workspace_id, token, payload):
    with runtime.service.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(runtime.service.ideas._member(row), 'edit')
        _enabled(runtime, workspace_id)
        result = plan(runtime.service.ideas._state(row), workspace_id, payload, runtime.clock())
        verdict = _verdict(runtime, cur, workspace_id, principal, result)
        return {**result, 'canCreate': verdict.verdict != 'deny', 'permissionReason': verdict.authz_reason}


def create(runtime, workspace_id, token, payload):
    selection = _selection(payload)
    key, digest = payload.get('idempotencyKey'), payload.get('digest')
    if not isinstance(key, str) or not 16 <= len(key) <= 100 or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise AlphaError('Send the preview digest and original request key.', 400)
    request = {**selection, 'digest': digest, 'kind': VERSION}
    service = runtime.service
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(service.ideas._member(row), 'edit')
        _enabled(runtime, workspace_id)
        # Reconcile an uncertain request before rereading a now-changed suggestion.
        found = store.existing_request(cur, workspace_id, key, principal, model.request_digest(principal, request))
        if found is not None:
            return {'taskId': found['taskId'], 'href': '/app/tasks?task=' + found['taskId'], 'replayed': True}
        state = service.ideas._state(row)
        reviewed = plan(state, workspace_id, selection, runtime.clock())
        if reviewed['digest'] != digest:
            raise AlphaError('The suggestion or campaign changed. Review the new preview.', 409, code='creator_preview_stale')
        verdict = _verdict(runtime, cur, workspace_id, principal, reviewed)
        if verdict.verdict == 'deny':
            raise AlphaError('Current agent permission does not allow this action: ' + verdict.authz_reason, 403, code='creator_permission_denied')
        dedupe = model.sha256(json.dumps([VERSION, reviewed['suggestionIdentity'], selection['platforms']], sort_keys=True))
        cur.execute("SELECT id::text FROM public.pr_agent_tasks WHERE workspace_id=%s AND created_by=%s AND dedupe_key=%s AND state IN ('queued','running','awaiting_approval','blocked')", (workspace_id, principal, dedupe))
        active = cur.fetchone()
        if active:
            raise AlphaError('This action already has an open task. Inspect its entry in Creator Pipeline.', 409, code='creator_task_exists')
        title = 'Prepare campaign drafts: ' + str(reviewed['source'].get('goal') or 'Campaign')[:90]
        cur.execute('INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text', (workspace_id, principal, title))
        conversation = cur.fetchone()[0]
        ref = {k: reviewed['source'][k] for k in ('type', 'id', 'revision')}
        task, _ = store.create_task(cur, service.ideas, workspace_id=workspace_id, conversation_id=conversation, created_by=principal,
            origin='opportunity', title=title, request_key=key, payload=request, dedupe_key=dedupe, trace_id='trace_' + uuid.uuid4().hex,
            authz_token=verdict.token, budget_ceiling_usd_micro=selection['budgetCeilingUsdMicro'], steps=[
                {'key': 's1', 'kind': 'approval', 'label': 'Review exact draft request and spending ceiling', 'approves': 's2'},
                {'key': 's2', 'kind': 'tool', 'label': 'Write reviewable campaign drafts', 'capabilityId': 'draft_create', 'inputs': reviewed['inputs'], 'targetRefs': [ref], 'dependsOn': ['s1']}])
        steps = store.load_steps(cur, workspace_id, task['taskId'])
        # Ask for the exact tool action; a later separate spend approval raises a $0 ceiling.
        action_verdict = replace(verdict, approval_kind='agent_action') if verdict.approval_kind == 'spend' else verdict
        approval_id = approvals.request_approval(cur, service.ideas, task, steps[0], action_verdict, gated=steps[1])
        summary = {'what': 'Prepare reviewable drafts; no scheduling or publication', 'source': reviewed['source'], 'inputs': reviewed['inputs'],
                   'expectedBenefit': reviewed['expectedBenefit'], 'budgetCeilingUsdMicro': selection['budgetCeilingUsdMicro'], 'price': 'Unknown; current credit and task limits still apply.'}
        cur.execute('UPDATE public.pr_agent_approvals SET summary=%s::jsonb WHERE id=%s', (json.dumps(summary), approval_id))
        metadata = {'version': VERSION, 'recordedAt': runtime.clock(), 'suggestionId': selection['suggestionId'], 'source': ref, 'observation': reviewed['observation'],
                    'expectedBenefit': reviewed['expectedBenefit'], 'platforms': selection['platforms'], 'previewDigest': digest,
                    'experiment': {'kind': 'content_gap', 'hypothesis': 'Preparing and reviewing this campaign draft may make the planned content available. Engagement impact requires comparable observed outcomes.', 'status': 'unmeasured'}}
        cur.execute("UPDATE public.pr_agent_runs SET usage=coalesce(usage,'{}'::jsonb)||jsonb_build_object('creatorPipeline',%s::jsonb) WHERE id=%s AND workspace_id=%s", (json.dumps(metadata), task['taskId'], workspace_id))
        store.refresh(cur, service.ideas, task)
        return {'taskId': task['taskId'], 'href': '/app/tasks?task=' + task['taskId'], 'replayed': False}


def result(state, steps):
    """Join actual output ids to live drafts/jobs. Queue acceptance is never publication."""
    draft_ids = {o.get('id') for step in steps for o in [*step.get('outputs', []), *step.get('entities', [])] if isinstance(o, dict) and o.get('type') == 'draft'}
    drafts = [{'id': v['id'], 'platform': v.get('platform'), 'revision': v.get('revision'), 'href': '/app/queue?view=drafts&draft=' + v['id']}
              for v in state.get('variants', []) if v.get('id') in draft_ids]
    jobs = []
    for job in state.get('phase2', {}).get('jobs', []):
        manifest = job.get('manifest') or {}
        if manifest.get('variantId') not in draft_ids:
            continue
        verification = job.get('verification') or {}
        verified = job.get('state') == 'verified' and bool(verification.get('at')) and bool(job.get('providerConfirmed')) and bool(job.get('providerReference'))
        if manifest.get('platform') == 'YouTube':
            verified = verified and (job.get('progress') or {}).get('stage') == 'published'
        jobs.append({'id': job['id'], 'state': job.get('state'), 'platform': manifest.get('platform'), 'verified': verified,
                     'verifiedAt': verification.get('at') if verified else None, 'providerReference': job.get('providerReference') if verified else None,
                     'href': '/app/queue?job=' + job['id']})
    return {'drafts': drafts[:40], 'jobs': jobs[:40], 'resultsTruncated': len(drafts) > 40 or len(jobs) > 40,
            'publication': 'verified' if jobs and len(jobs) <= 40 and all(j['verified'] for j in jobs) else 'not_verified'}


def listing(runtime, workspace_id, token):
    service = runtime.service
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(service.ideas._member(row), 'edit')
        _enabled(runtime, workspace_id)
        state = service.ideas._state(row)
        cur.execute("SELECT t.id::text,r.usage->'creatorPipeline' FROM public.pr_agent_tasks t JOIN public.pr_agent_runs r ON r.id=t.id AND r.workspace_id=t.workspace_id WHERE t.workspace_id=%s AND t.created_by=%s AND r.usage->'creatorPipeline'->>'version'=%s ORDER BY t.created_at DESC LIMIT 21", (workspace_id, principal, VERSION))
        rows = cur.fetchall()
        entries = []
        for task_id, metadata in rows[:20]:
            task = store.load_task(cur, workspace_id, task_id)
            steps = store.load_steps(cur, workspace_id, task_id)
            outcome = result(state, steps)
            entries.append({'taskId': task_id, 'title': task['title'], 'state': task['state'], 'href': '/app/tasks?task=' + task_id,
                            **metadata, **outcome, 'analyticsHref': '/app/analytics', 'measurement': {'status': 'unavailable', 'reason': 'No native metric reading is linked yet.'}})
        # Existing same-workspace metric reader; expose only readings of linked verified jobs.
        verified_ids = {j['id'] for entry in entries for j in entry['jobs'] if j['verified']}
        if verified_ids:
            readings = insights.summary(cur, workspace_id, [j for j in state.get('phase2', {}).get('jobs', []) if j.get('id') in verified_ids], runtime.clock())
            posts = readings.get('posts', [])
            for entry in entries:
                ids = {j['id'] for j in entry['jobs'] if j['verified']}
                measured = [p for p in posts if p.get('jobId') in ids and p.get('contentOrigin') == 'postriff_published']
                if measured:
                    entry['measurement'] = {'status': 'observed', 'posts': measured[:40], 'truncated': len(measured) > 40, 'reason': 'Native observations, not proof of causal benefit. Compare like periods and definitions in Analytics.'}
        return {'workspaceId': workspace_id, 'items': entries, 'hasMore': len(rows) > 20}

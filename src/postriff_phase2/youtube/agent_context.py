"""Provenance and deletion of native YouTube data consumed by one agent turn.

Only the server's analytics tool creates these sources. User prose, Library
content and ordinary conversations are never classified by keyword matching.
Answers remain visible for at most 30 days, but are never eligible as later AI
history. A disconnected/replaced grant cannot persist a late model answer.
"""
from __future__ import annotations

import copy
import json
import time

from postriff_alpha.domain import AlphaError

from ..contracts import digest

KEY = 'youtubeProviderContext'
REMOVED = 'youtubeProviderContextRemoved'
RETENTION_SECONDS = 30 * 86400
NOTICE = 'YouTube analytics context was removed. Ask again after connecting the channel to read its current analytics.'


def source(workspace, connection, channel, generation, now):
    if not all(isinstance(value, str) and value for value in (workspace, connection, channel, generation)):
        raise AlphaError('Reconnect this YouTube channel before sharing analytics with Rafii.', 409, code='youtube_revoked_oauth')
    return {'provider': 'youtube', 'workspaceId': workspace, 'connectionId': connection, 'channelId': channel,
            'authorizationGeneration': generation, 'ingestedAt': now, 'expiresAt': now + RETENTION_SECONDS}


def sources(value):
    """Read machine provenance only, including deterministically attributed legacy facts."""
    if not isinstance(value, dict):
        return []
    result = value.get('agent') if isinstance(value.get('agent'), dict) else value
    tagged = result.get(KEY)
    out = [item for item in tagged if isinstance(item, dict) and item.get('provider') == 'youtube'] if isinstance(tagged, list) else []
    facts = result.get('facts')
    for fact in facts if isinstance(facts, list) else []:
        if not isinstance(fact, dict) or fact.get('kind') != 'youtube_native_analytics':
            continue
        evidence = fact.get('evidence') or {}
        if isinstance(evidence, dict) and all(isinstance(evidence.get(key), str) and evidence[key] for key in ('connectionId', 'channelId')):
            legacy = {'provider': 'youtube', 'connectionId': evidence['connectionId'], 'channelId': evidence['channelId']}
            if not any(item.get('connectionId') == legacy['connectionId'] and item.get('channelId') == legacy['channelId'] for item in out):
                out.append(legacy)
    return out


def history_eligible(role, body):
    # A human's words remain theirs, even if they quote analytics. Provenance is
    # assigned only to actual tool-consuming assistant turns.
    agent = body.get('agent') if isinstance(body, dict) and isinstance(body.get('agent'), dict) else {}
    return role != 'assistant' or not (sources(body) or agent.get(REMOVED) or (isinstance(body, dict) and body.get(REMOVED)))


def assert_current(creator, workspace, provenance, *, cursor=None, locked=False, now=None):
    now = time.time() if now is None else now
    if provenance and not callable(getattr(getattr(creator, 'journal', None), 'assert_authorized', None)):
        raise AlphaError('YouTube analytics authorization cannot be verified. Try again later.', 503, code='youtube_context_unavailable')
    for item in provenance:
        if (item.get('workspaceId') != workspace or type(item.get('expiresAt')) not in (int, float)
                or item['expiresAt'] <= now):
            raise AlphaError('This YouTube analytics context is no longer authorized.', 409, code='youtube_revoked_oauth')
        creator.journal.assert_authorized(workspace, item.get('connectionId'), item.get('authorizationGeneration'),
                                          cursor=cursor, locked=locked)


def redact_result(result):
    """Freeform assistant output is inseparable; keep content-free billing/effect receipts."""
    from ..agent_runtime_v2.contracts import empty_result
    out = empty_result(result.get('traceId'), result.get('modality', 'text'))
    for key in ('usage', 'routes', 'changedEntities', 'generatedAssets', 'pendingApprovals'):
        if key in result:
            out[key] = copy.deepcopy(result[key])
    out.update(answerText=NOTICE, speakableSummary=NOTICE, composedBy='deterministic', **{REMOVED: True})
    return out


def redact_message(body):
    from ..site_agent import contracts
    agent = redact_result(body.get('agent') or {})
    site = body.get('siteAgent') or {}
    return {'text': NOTICE, 'runId': body.get('runId'), REMOVED: True, 'agent': agent,
            'siteAgent': {'version': site.get('version'), 'runId': body.get('runId'), 'intent': 'agent', 'status': site.get('status'),
                          'blocks': [contracts.text(NOTICE)], 'proposals': copy.deepcopy(site.get('proposals') or []),
                          'refs': [], 'followUps': []}}


def redact_artifact(artifact):
    out = copy.deepcopy(artifact)
    if isinstance(out.get('result'), dict):
        out['result'] = redact_result(out['result'])
    out.pop('pendingRun', None)
    if isinstance(out.get('trace'), dict):
        # Trace extensions are not guaranteed to be content-free. Retain only
        # the correlation identifier and runtime, never arbitrary extension data.
        out['trace'] = {key: out['trace'][key] for key in ('traceId', 'runtime') if key in out['trace']}
    out[REMOVED] = True
    return out


def _legacy_match(expr):
    # Type-check old arrays; a malformed historical value must not abort an
    # otherwise valid disconnect. No scan of user/freeform strings is allowed.
    facts = f"CASE WHEN jsonb_typeof({expr}->'facts')='array' THEN {expr}->'facts' ELSE '[]'::jsonb END"
    return f"EXISTS (SELECT 1 FROM jsonb_array_elements({facts}) f WHERE f->>'kind'='youtube_native_analytics' AND f->'evidence'->>'connectionId'=%s AND f->'evidence'->>'channelId'=%s)"


def _legacy_expired(expr):
    facts = f"CASE WHEN jsonb_typeof({expr}->'facts')='array' THEN {expr}->'facts' ELSE '[]'::jsonb END"
    return ("created_at<=to_timestamp(%s)-interval '30 days' AND EXISTS (SELECT 1 FROM jsonb_array_elements(" + facts +
            ") f WHERE f->>'kind'='youtube_native_analytics' AND jsonb_typeof(f->'evidence'->'connectionId')='string' "
            "AND jsonb_typeof(f->'evidence'->'channelId')='string')")


def _scrub(cur, workspace, message_predicate, message_params, run_predicate, run_params):
    """Caller owns the workspace lock, matching all agent and disconnect writers."""
    run_ids = set()
    cur.execute("SELECT id::text,run_id::text,body FROM public.pr_messages WHERE workspace_id=%s AND role='assistant' AND (" + message_predicate + ')',
                (workspace, *message_params))
    for message_id, run_id, body in cur.fetchall():
        cur.execute('UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s AND workspace_id=%s AND role=\'assistant\'',
                    (json.dumps(redact_message(body), ensure_ascii=False), message_id, workspace))
        if run_id:
            run_ids.add(run_id)
    if run_ids:
        run_predicate += ' OR id::text=ANY(%s)'
        run_params = (*run_params, sorted(run_ids))
    cur.execute('SELECT id::text,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND (' + run_predicate + ')', (workspace, *run_params))
    for run_id, artifact in cur.fetchall():
        redacted = redact_artifact(artifact or {})
        cur.execute('UPDATE public.pr_agent_runs SET artifact=%s::jsonb,artifact_hash=%s,updated_at=now() WHERE id::text=%s AND workspace_id=%s',
                    (json.dumps(redacted, ensure_ascii=False), digest(redacted), run_id, workspace))
        run_ids.add(run_id)
    for run_id in sorted(run_ids):
        # These events copy assistant text and blocks. Keep type/sequence/clock
        # for replay, but never retain provider-derived contents in the body.
        cur.execute("UPDATE public.pr_agent_events SET body=%s::jsonb WHERE workspace_id=%s AND run_id::text=%s AND kind IN ('artifact.created','message.delta','message.completed')",
                    (json.dumps({REMOVED: True}), workspace, run_id))


def purge_connection(cur, workspace, connection):
    cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube'", (workspace, connection))
    row = cur.fetchone()
    channel = row[0] if row else None
    tag = json.dumps([{'provider': 'youtube', 'workspaceId': workspace, 'connectionId': connection}])
    message = "body->'agent'->%s @> %s::jsonb"
    run = "artifact->'result'->%s @> %s::jsonb OR artifact->'pendingRun'->%s @> %s::jsonb"
    message_params, run_params = (KEY, tag), (KEY, tag, KEY, tag)
    if channel:
        message += ' OR ' + _legacy_match("(body->'agent')")
        run += ' OR ' + _legacy_match("(artifact->'result')")
        message_params += (connection, channel)
        run_params += (connection, channel)
    _scrub(cur, workspace, message, message_params, run, run_params)


def purge_expired(cur, now=None):
    now = time.time() if now is None else now
    predicate = "jsonb_path_exists(coalesce(%s, '[]'::jsonb), '$[*] ? (@.provider == \"youtube\" && @.expiresAt <= $clock)', jsonb_build_object('clock', %%s))"
    message = predicate % "body->'agent'->'youtubeProviderContext'"
    run = (predicate % "artifact->'result'->'youtubeProviderContext'" + ' OR ' +
           predicate % "artifact->'pendingRun'->'youtubeProviderContext'")
    # Legacy native facts have no trustworthy ingestion marker; their row clock
    # bounds retention, but only explicitly native facts are selected.
    legacy_message = _legacy_expired("(body->'agent')")
    legacy_run = _legacy_expired("(artifact->'result')")
    message += ' OR (' + legacy_message + ')'
    run += ' OR (' + legacy_run + ')'
    cur.execute('SELECT DISTINCT workspace_id::text FROM (SELECT workspace_id FROM public.pr_messages WHERE role=\'assistant\' AND (' + message +
                ') UNION SELECT workspace_id FROM public.pr_agent_runs WHERE (' + run + ')) expired LIMIT 100', (now, now, now, now, now))
    workspaces = [row[0] for row in cur.fetchall()]
    for workspace in sorted(workspaces):
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE SKIP LOCKED', (workspace,))
        if cur.fetchone():
            _scrub(cur, workspace, message, (now, now), run, (now, now, now))

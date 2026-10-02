"""Founder voice: a GPT-Live session for the founder panel (Founder Admin P1-5, CONTRACTS §8.E; PRD §6.5).

Boundaries.

* No credential in the browser. The founder panel posts its WebRTC SDP offer to POST /agent/voice/sessions; the Control
  boundary has already checked the founder (copilot.use, AAL2, CSRF, budget `founder.voice`); this module then requires
  RAFII_FOUNDER_VOICE_ENABLED and the founder ops workspace (409 POLICY_DISABLED with the blocker
  `founder_voice_disabled` / `ops_workspace_not_configured` otherwise, before any database or provider is touched) and
  creates the Live session with the server-held key exactly as the customer Voice Mode does (agent_runtime_v2.live).
* Voice never gets more than text. The Live session carries no tools of its own: delegation is `client`, so every
  `session.delegation.created` comes back to POST /agent/voice/sessions/{id}/delegations, which runs `founder_agent.turn`
  with modality 'voice' in the session's own founder conversation and data mode — the founder tools only, through the same
  gate as a typed question (tenant, permission, voice ≤ text), with the same receipts, drafts that wait for confirmation
  in the panel, refusals and `founder.agent.turn` audit. The Live instructions forbid stating any value the backend did
  not return in the call.
* Same tenant model as a founder text turn: the session is a `pr_agent_runs` row in the ops workspace keyed
  `voice:founder:<mode>:<environment>:...`, in a `[founder:<mode>:<environment>]` conversation (Demo and Live never share
  a thread), owned by the founder (only the founder who started it can delegate, write its transcript or end it). Its
  cost is reserved up front on the ops workspace ledger with meta costCenter='founder_ops' and settled on end from the
  server's clock (a session nobody ended is reaped after the cap, never free and never held forever).
* Routes (registered at import, capability copilot.use): GET /agent/voice/status, POST /agent/voice/sessions (budget
  founder.voice), POST /agent/voice/sessions/{id}/delegations (budget founder.agent.turn, like a typed turn),
  POST /agent/voice/sessions/{id}/transcript and POST /agent/voice/sessions/{id}/end. Ending and transcripts stay possible
  after the flag is turned off, so a session in flight can always be closed and settled.
"""
from __future__ import annotations

import json
import os
import re

from . import http
from .auth import ControlError

FLAG = 'RAFII_FOUNDER_VOICE_ENABLED'
SESSION_ID = '([0-9a-fA-F-]{36})'
_UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z')
_DELEGATION = re.compile(r'[A-Za-z0-9_.:-]{1,64}\Z')
MAX_DELEGATIONS_KEPT = 50
START_KEYS = frozenset(('sdp', 'mode', 'conversationId', 'locale', 'voice', 'pageContext'))
DELEGATION_KEYS = frozenset(('delegationId', 'message', 'timeZone', 'locale', 'pageContext'))

FOUNDER_LIVE_PROMPT = """You are Rafii, speaking with the founder of Rafii in the founder console (Founder mode). Speak calmly and briefly:
one to three sentences unless the founder asks for more. {language}

Backchannel policy: Use few, short backchannels. Do not compete with the founder or with an answer you are giving.

Interruption policy: Stop speaking when the founder interrupts. Listen. A correction replaces what you were doing.

{mode}

Delegation policy:
The backend is the founder console's Rafii. It reads the business through founder tools only: metrics with receipts (revenue, cash,
customers, AI cost, publishing, reliability, support), incidents and their timelines, data source health, what the founder's screen
shows, drafts for the founder to read (never sent), and reminders or reports prepared for the founder to confirm in the panel.
Delegate to the backend when:
- The founder asks about any number, customer, workspace, subscription, incident, chart, cost, report, reminder, draft or page.
- The founder answers yes or no to something the backend proposed (the backend decides which proposal a "yes" applies to).
- The founder asks to cancel or change work already requested.
Do not delegate to the backend when:
- You can answer from a still-current backend result in this call.
- You need a brief clarification to understand the request.

Truth:
- Never state a number, customer, workspace, incident, date or state that the backend did not return in this call, and never add up,
  subtract, average, convert or compare numbers yourself. Missing data is not zero: say what is missing.
- Before an answer that depends on the backend, delegate first. While you wait, say briefly that you are checking; never guess.
- Never say that something was sent, saved, scheduled, acknowledged, refunded, blocked, deleted or changed unless the backend's result
  said so. Drafts, reminders and reports wait for the founder's confirmation in the panel.
- From voice you cannot send email, push or texts, place calls, refund, ban, delete data, deploy or run commands; say where in the
  console the founder can do it, if anywhere.
- Never read out ids, receipt ids, links or secrets."""
MODE_LINES = {
    'demo': 'Data mode: Demo. Everything comes from a fictional dataset for rehearsing the console; say "Demo" whenever you report a value '
            'and never present it as the business.',
    'live': 'Data mode: Live, the real business data of the {environment} environment. Never fall back to Demo.',
}


def _truthy(value):
    return str(value if value is not None else '').strip().lower() in ('1', 'true', 'yes', 'on')


def _founder_agent():
    """founder_agent, imported on use: it pulls the agent runtime, which a Control-only process may not carry."""
    from . import founder_agent
    return founder_agent


def founder_live_prompt(locale, mode, environment, style=None):
    """The Live session's instructions: fixed text, the language line, the data-mode sentence, then the delivery the
    founder chose (fixed sentences picked by their style's enum values; never their own words)."""
    from postriff_phase2.agent_runtime_v2 import live, style as agent_style
    prompt = FOUNDER_LIVE_PROMPT.format(language=live.LANGUAGE_LINES.get(locale or 'auto', live.LANGUAGE_LINES['auto']),
                                        mode=MODE_LINES['demo' if mode == 'demo' else 'live'].format(environment=str(environment)))
    return prompt if style is None else prompt + '\n\n' + agent_style.voice_block(style)


def session_config(model, locale, voice, mode, environment, style=None, history=''):
    """The browser Live session: founder instructions, client delegation, `store: false`, the restricted data channel, and
    no tools of its own."""
    from postriff_phase2.agent_runtime_v2 import live
    session = {'model': model, 'instructions': founder_live_prompt(locale, mode, environment, style), 'audio': {'output': {'voice': voice}},
               'delegation': {'type': 'client'}, 'store': False,
               'client': {'data_channel': {'allowed_client_events': list(live.ALLOWED_CLIENT_EVENTS), 'allowed_server_events': list(live.ALLOWED_SERVER_EVENTS)}}}
    if history:
        session['input'] = [{'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': history}]}]
    return session


_CLASSES = {}


def voice_sessions_class():
    """FounderVoiceSessions, built on first use over agent_runtime_v2.live.VoiceSessions (imported lazily, like the agent)."""
    if 'founder' in _CLASSES:
        return _CLASSES['founder']
    from postriff_alpha.domain import AlphaError, uid
    from postriff_phase2.agent_runtime import safe_event
    from postriff_phase2.agent_runtime_v2 import live, style as agent_style
    from postriff_phase2.agent_runtime_v2.greeting import opening
    from postriff_phase2.contracts import digest
    from postriff_phase2.permissions import require

    class FounderVoiceSessions(live.VoiceSessions):
        """The customer Voice Mode broker with the founder's namespace, conversation, prompt and cost centre. Transcript,
        end, reaping and settlement are the base class's own; every session read is confined to this namespace."""

        def __init__(self, runtime, *, mode, environment, transport=None):
            super().__init__(runtime, transport=transport)
            founder_agent = _founder_agent()
            self.mode, self.environment = mode, environment
            self.namespace = founder_agent.conversation_namespace(mode, environment)
            self.key_prefix = f'voice:{self.namespace}:'

        def _cap_minutes(self):
            # Whole-minute broker limits never exceed the stored seconds cap.
            return max(1, getattr(self, '_founder_cap_seconds', 600) // 60)

        def start(self, workspace_id, token, payload, *, request_id=None) -> dict:
            founder_agent = _founder_agent()
            sdp = payload.get('sdp') if isinstance(payload, dict) else None
            if not isinstance(sdp, str) or not sdp.startswith('v=0') or len(sdp.encode()) > live.MAX_SDP_BYTES:
                raise AlphaError("Send the browser's WebRTC offer.", 400, code='sdp_invalid')
            if not self.cfg.enabled('RAFII_AGENT_V2_ENABLED'):
                raise AlphaError("Rafii's agent runtime is not enabled on this deployment.", 409, code='runtime_off')
            route = self.cfg.route('voice_front_end', reason='founder voice session')
            if not route.available:
                raise AlphaError('No GPT-Live route is configured here.', 409, code='runtime_off')
            repo, ideas = self.service.repository, self.service.ideas
            with repo.transaction(token, workspace_id) as (cur, row, principal):
                require(ideas._member(row), 'edit')
                from postriff_phase2.billing import ops_metadata
                from postriff_phase2.founder_policy import policy_from_marker
                marker = ops_metadata(cur, workspace_id)
                if not marker or marker['operatorId'] != str(principal):
                    raise AlphaError('Founder voice requires the verified internal owner.', 403)
                policy = policy_from_marker(marker)
                self._founder_cap_seconds = policy['maxCallSeconds']
                style = agent_style.load(cur, principal)
                locale, voice = live.locale_and_voice(payload, style)
                opening_greeting = opening(cur, principal, locale)
                conversation_id = payload.get('conversationId')
                if conversation_id:
                    cur.execute('SELECT title FROM public.pr_conversations WHERE id::text=%s AND workspace_id=%s', (conversation_id, workspace_id))
                    found = cur.fetchone()
                    if not found or founder_agent.namespace_of_title(found[0]) != self.namespace:
                        raise AlphaError('Conversation unavailable.', 404)
                else:
                    cur.execute('INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text',
                                (workspace_id, principal, founder_agent.conversation_title(self.namespace, 'Voice conversation')))
                    conversation_id = cur.fetchone()[0]
                self._reap(cur, workspace_id, principal)
                cur.execute("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s AND actor=%s AND idempotency_key LIKE 'voice:%%' AND status='running' "
                            "AND created_at>now()-make_interval(mins=>%s)", (workspace_id, principal, self._cap_minutes()))
                if cur.fetchone()[0] >= policy['concurrentCalls']:
                    raise AlphaError('Voice is already on in another tab. End it there first.', 429, code='voice_busy')
                history = self._history(cur, workspace_id, conversation_id)
                estimate = self.cfg.live_usd_micro_per_minute * self._cap_minutes()
                key = self.key_prefix + uid()
                cur.execute('INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) '
                            "VALUES(%s,%s,%s,'running',%s,'quick',%s,%s,%s,%s::jsonb) RETURNING id::text",
                            (conversation_id, workspace_id, principal, route.model, digest({'voice': key}), digest({'live': 1, 'founder': 1}), key,
                             json.dumps({'voice': {'state': 'connecting', 'locale': locale, 'voice': voice, 'startedAt': self._now(), 'transcript': [], 'delegations': [],
                                                   'capSeconds': self._founder_cap_seconds, 'founder': {'mode': self.mode, 'environment': self.environment, 'namespace': self.namespace}}})))
                voice_session_id = cur.fetchone()[0]
                # Founder voice is founder operations spend on the ops workspace's own ledger, never a customer's credits.
                reservation = self.service.ledger.reserve(cur, workspace_id, principal, 'tool', estimate, f'voice:{voice_session_id}', charge_batch=False,
                                                          provider='openai', model=route.model, run_id=voice_session_id,
                                                          meta={'via': 'rafii_founder_voice', 'unit': 'session', 'capMinutes': self._cap_minutes(), 'costCenter': 'founder_ops'})
                artifact = self._artifact(cur, workspace_id, voice_session_id)
                artifact['voice']['reservationId'] = reservation['reservationId']
                self._save(cur, workspace_id, voice_session_id, artifact)
            try:
                session = session_config(route.model, locale, voice, self.mode, self.environment, style, history)
            except Exception as error:  # noqa: BLE001 - the reservation is already committed
                self._start_failed(workspace_id, token, voice_session_id, reservation, 'live_error', {'phase': 'live_config'}, request_id)
                raise AlphaError("The voice service didn't start a session. You can keep typing.", 502, code='live_error') from error
            try:
                response = self.transport('POST', live.LIVE_ENDPOINT, headers={'Authorization': f"Bearer {self.cfg.credential('openai')}"},
                                          body={'session': session, 'transport': {'type': 'webrtc', 'sdp': sdp}})
            except AlphaError as error:
                raw = getattr(error, 'live_diagnostic', None)
                raw = raw if isinstance(raw, dict) else {}
                details = live.creation_diagnostic(status=raw.get('upstreamStatus'), provider_request_id=raw.get('providerRequestId'))
                self._start_failed(workspace_id, token, voice_session_id, reservation, error.code if error.code in live.START_FAILURE_CODES else 'live_error',
                                   details, request_id)
                raise
            except Exception as error:  # noqa: BLE001 - a failed transport must not leave its reserved session running
                self._start_failed(workspace_id, token, voice_session_id, reservation, 'live_error', live.creation_diagnostic(), request_id)
                raise AlphaError("The voice service didn't start a session. You can keep typing.", 502, code='live_error') from error
            response = response if isinstance(response, dict) else {}
            status, body = response.get('status'), response.get('body')
            status = status if type(status) is int else None
            details = live.creation_diagnostic(body, status=status, provider_request_id=response.get('providerRequestId'))
            body = body if isinstance(body, dict) else {}
            transport, provider_session = body.get('transport'), body.get('session')
            answer = transport.get('sdp') if isinstance(transport, dict) else None
            live_id = provider_session.get('id') if isinstance(provider_session, dict) else None
            if status != 201 or not isinstance(answer, str) or not answer.strip() or not isinstance(live_id, str) or not live_id.strip():
                code = {401: 'live_auth', 403: 'live_forbidden'}.get(status, 'live_rejected')
                if status == 429 and details.get('errorCode') in live.ACCOUNT_LIMIT_CODES:
                    code = 'live_quota'
                elif status == 429 and details.get('errorCode') in live.TRANSIENT_LIMIT_CODES:
                    code = 'live_busy'
                self._start_failed(workspace_id, token, voice_session_id, reservation, code, details, request_id)
                raise AlphaError("The voice service didn't start a session. You can keep typing.", 502, code=code)
            try:
                with repo.transaction(token, workspace_id) as (cur, _row, _principal):
                    artifact = self._artifact(cur, workspace_id, voice_session_id)
                    artifact['voice'].update({'state': 'live', 'liveSessionId': live_id, 'reservationId': reservation['reservationId'], 'connectedAt': self._now()})
                    self._save(cur, workspace_id, voice_session_id, artifact)
                    ideas._insert_event(cur, workspace_id, voice_session_id, safe_event('run.started', agent='voice', model=route.model, modality='voice', locale=locale))
            except Exception as error:  # noqa: BLE001 - provider admission may already have billed
                self._start_failed(workspace_id, token, voice_session_id, reservation, 'live_error', {**details, 'phase': 'live_persist'}, request_id)
                raise AlphaError("The voice service didn't start a session. You can keep typing.", 502, code='live_error') from error
            return {'voiceSessionId': voice_session_id, 'liveSessionId': live_id, 'conversationId': conversation_id, 'sdp': answer, 'dataChannel': live.DATA_CHANNEL,
                    'model': route.model, 'locale': locale, 'voice': voice, 'openingGreeting': opening_greeting, 'capMinutes': self._cap_minutes(),
                    'allowedClientEvents': list(live.ALLOWED_CLIENT_EVENTS)}

        def _artifact(self, cur, workspace_id, voice_session_id, *, owner_check=False, principal=None) -> dict:
            """The session row of THIS namespace only: a customer voice session, another data mode or another environment
            is the same 404 as a missing one; with owner_check, so is another member's session."""
            cur.execute('SELECT artifact,idempotency_key,actor::text FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE',
                        (voice_session_id, workspace_id))
            row = cur.fetchone()
            if not row or not str(row[1]).startswith(self.key_prefix):
                raise AlphaError('Voice session unavailable.', 404)
            if owner_check and row[2] != principal:
                raise AlphaError('Voice session unavailable.', 404)
            artifact = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            artifact.setdefault('voice', {})
            seconds = artifact['voice'].get('capSeconds', 600)
            if type(seconds) is int and 60 <= seconds <= 3600:
                self._founder_cap_seconds = seconds
            return artifact

        def _reap(self, cur, workspace_id, principal):
            # A bookkeeping timeout is not provider billing evidence. Preserve
            # the hold until actual provider usage is reconciled.
            cur.execute("SELECT id::text,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND actor=%s "
                        "AND idempotency_key LIKE %s AND status='running' "
                        "AND created_at<=now()-make_interval(secs=>coalesce((artifact->'voice'->>'capSeconds')::int,600)+300) FOR UPDATE SKIP LOCKED",
                        (workspace_id, principal, self.key_prefix + '%'))
            for run_id, artifact in cur.fetchall():
                voice = (artifact or {}).setdefault('voice', {})
                if voice.get('reservationId'):
                    self.service.ledger.settle(cur, workspace_id, voice['reservationId'], 'unknown', None)
                live.record_session(cur, self.cfg, workspace_id, principal, run_id, voice, status='unknown', seconds=None, cost=None)
                voice.update(state='ended', reason='not_ended_by_client', endedAt=self._now(), usageSeconds=None,
                             costUsdMicro=None, billingBasis='unknown until provider usage is reconciled')
                self._save(cur, workspace_id, run_id, artifact, status='completed')
                self.service.ideas._insert_event(cur, workspace_id, run_id, safe_event('run.completed', usage={'provenance': 'voice', 'costState': 'unknown'}))

        def _close(self, workspace_id, token, voice_session_id, reservation, *, state, reason, seconds, failure_diagnostic=None):
            if state != 'ended':
                return super()._close(workspace_id, token, voice_session_id, reservation, state=state, reason=reason,
                                      seconds=seconds, failure_diagnostic=failure_diagnostic)
            with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(self.service.ideas._member(row), 'read')
                artifact = self._artifact(cur, workspace_id, voice_session_id, owner_check=True, principal=principal)
                voice = artifact['voice']
                if voice.get('state') in ('ended', 'failed'):
                    return {'voiceSessionId': voice_session_id, 'state': voice['state'], 'note': 'Already ended.'}
                started = voice.get('connectedAt') or voice.get('startedAt') or self._now()
                observed = min(max(0.0, self._now() - started), self._cap_minutes() * 60)
                if reservation and reservation.get('reservationId'):
                    self.service.ledger.settle(cur, workspace_id, reservation['reservationId'], 'unknown', None)
                live.record_session(cur, self.cfg, workspace_id, principal, voice_session_id, voice, status='ok', seconds=None, cost=None)
                voice.update(state=state, endedAt=self._now(), reason=reason, usageSeconds=None, costUsdMicro=None,
                             observedDurationSeconds=observed, clientReportedSeconds=seconds, billingBasis='unknown until provider usage is reconciled')
                self._save(cur, workspace_id, voice_session_id, artifact, status='completed')
                self.service.ideas._insert_event(cur, workspace_id, voice_session_id, safe_event('run.completed', usage={'provenance': 'voice', 'costState': 'unknown'}))
            return {'voiceSessionId': voice_session_id, 'state': state, 'reason': reason, 'usageSeconds': None, 'costState': 'unknown'}

        def bound(self, workspace_id, token, voice_session_id) -> str:
            """The conversation a delegation runs in: the caller's own live session of this namespace, else a refusal."""
            with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(self.service.ideas._member(row), 'edit')
                artifact = self._artifact(cur, workspace_id, voice_session_id, owner_check=True, principal=principal)
                cur.execute('SELECT conversation_id::text,status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s', (voice_session_id, workspace_id))
                found = cur.fetchone()
            if not found or found[1] != 'running' or artifact['voice'].get('state') not in ('connecting', 'live'):
                raise AlphaError('This voice session has ended. Start voice again.', 409, code='voice_session_ended')
            return found[0]

        def note_delegation(self, workspace_id, token, voice_session_id, delegation_id, run_id) -> None:
            """Keep which founder turn answered which delegation on the session row (bounded; ids only)."""
            with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
                artifact = self._artifact(cur, workspace_id, voice_session_id, owner_check=True, principal=principal)
                kept = artifact['voice'].setdefault('delegations', [])
                if not any(isinstance(item, dict) and item.get('id') == delegation_id for item in kept):
                    kept.append({'id': delegation_id, 'runId': run_id, 'at': self._now()})
                del kept[:-MAX_DELEGATIONS_KEPT]
                self._save(cur, workspace_id, voice_session_id, artifact)

    _CLASSES['founder'] = FounderVoiceSessions
    return FounderVoiceSessions


# --- gates ----------------------------------------------------------------------------------------------------------------------
def ops_workspace(flags, control=None, principal=None):
    """The founder ops workspace exactly as a founder text turn resolves it (founder_agent): RAFII_FOUNDER_OPS_WORKSPACE_ID,
    else this founder's stored setting (founder_ops, created from Settings); 409 POLICY_DISABLED
    (ops_workspace_not_configured) when neither exists."""
    founder_agent = _founder_agent()
    resolve = getattr(founder_agent, '_resolve_ops', None)
    if resolve is None or not isinstance(principal, dict):
        return founder_agent.ops_workspace_id(flags or {})
    return resolve(flags if flags is not None else {}, control, principal)


def require_enabled(flags, control=None, principal=None):
    """409 POLICY_DISABLED, before anything is read, when the founder voice flag is off or the ops workspace is not set."""
    founder_agent = _founder_agent()
    if not _truthy((flags or {}).get(FLAG)):
        raise founder_agent.PolicyDisabled('founder_voice_disabled')
    ops_workspace(flags, control, principal)


def _flags(values):
    return values if values is not None else os.environ


def _sessions(service, principal, mode, *, control, flags, request_id, base=None, context=None, transport=None):
    """(FounderVoiceSessions, ops workspace id, capability) for one request, through founder_agent's own scoped runtime."""
    founder_agent = _founder_agent()
    principal = founder_agent.require_founder(principal)
    if mode not in founder_agent.MODES:
        raise ControlError('VALIDATION_FAILED', 400)
    ops = ops_workspace(flags, control, principal)
    founder = founder_agent.founder_scope_for(principal, mode, control, context or {}, founder_agent.request_identifier(request_id))
    runtime, capability = founder_agent.founder_runtime(service, ops, principal['operator']['user_id'], founder, base=base)
    sessions = voice_sessions_class()(runtime, mode=mode, environment=principal['session']['environment'],
                                      transport=transport or getattr(runtime, 'live_transport', None))
    return sessions, ops, capability


def _runtime_blocker(sessions):
    """The fixed blocker when the agent runtime or the GPT-Live route cannot serve a founder voice session, else None."""
    if not sessions.cfg.enabled('RAFII_AGENT_V2_ENABLED') and getattr(sessions.runtime, 'model_factory', None) is None:
        return 'agent_runtime_off'
    if not sessions.cfg.route('voice_front_end', reason='founder voice status').available:
        return 'voice_route_unavailable'
    return None


def _envelope(sessions, out):
    return {**out, 'mode': sessions.mode, 'environment': sessions.environment, 'namespace': sessions.namespace, '_dataState': 'not_applicable'}


# --- operations (the HTTP handlers below are thin wrappers; tests call these with a scripted runtime) -----------------------------
def status(service, principal, *, mode='live', control=None, values=None, base=None, request_id=None):
    """Whether founder voice can start here, with every blocker (fixed codes), without creating anything."""
    founder_agent = _founder_agent()
    founder_agent.require_founder(principal)
    flags, blockers, model = _flags(values), [], None
    if not _truthy(flags.get(FLAG)):
        blockers.append('founder_voice_disabled')
    try:
        ops_workspace(flags, control, principal)
    except founder_agent.PolicyDisabled:
        blockers.append('ops_workspace_not_configured')
    if service is None:
        blockers.append('consumer_runtime_unavailable')
    elif 'ops_workspace_not_configured' not in blockers:
        sessions, _ops, _capability = _sessions(service, principal, mode, control=control, flags=flags, request_id=request_id, base=base)
        try:
            from postriff_phase2.billing import ops_metadata
            from postriff_phase2.founder_policy import policy_from_marker
            with sessions.service.repository.transaction(_capability, _ops) as (cur, _row, actor):
                marker = ops_metadata(cur, _ops)
                if not marker or marker['operatorId'] != str(actor):
                    raise ValueError('unverified internal owner')
                sessions._founder_cap_seconds = policy_from_marker(marker)['maxCallSeconds']
        except Exception:
            blockers.append('founder_voice_policy_unavailable')
        blocker = _runtime_blocker(sessions)
        if blocker:
            blockers.append(blocker)
        model = sessions.cfg.route('voice_front_end', reason='founder voice status').model
    return {'available': not blockers, 'blockers': blockers, 'mode': mode, 'capMinutes': sessions._cap_minutes() if service is not None and 'ops_workspace_not_configured' not in blockers else 10, 'model': model, 'delegation': 'client',
            '_dataState': 'not_applicable'}


def validate_start(body, mode):
    founder_agent = _founder_agent()
    if not isinstance(body, dict) or 'sdp' not in body or set(body) - START_KEYS or body.get('mode', mode) != mode:
        raise ControlError('VALIDATION_FAILED', 400)
    conversation = body.get('conversationId')
    if conversation is not None and (not isinstance(conversation, str) or not _UUID.match(conversation)):
        raise ControlError('VALIDATION_FAILED', 400)
    for name in ('locale', 'voice'):
        if body.get(name) is not None and (not isinstance(body[name], str) or not 1 <= len(body[name]) <= 20):
            raise ControlError('VALIDATION_FAILED', 400)
    return {'sdp': body['sdp'], 'conversationId': conversation.lower() if conversation else None, 'locale': body.get('locale'), 'voice': body.get('voice'),
            'pageContext': founder_agent.founder_context(body.get('pageContext'))}


def start(service, principal, body, request_id, *, mode, control=None, values=None, base=None, transport=None):
    """POST /agent/voice/sessions: the founder panel's GPT-Live session (SDP answer, ids, delegation path)."""
    founder_agent = _founder_agent()
    from postriff_alpha.domain import AlphaError
    founder_agent.require_founder(principal)
    flags = _flags(values)
    require_enabled(flags, control, principal)
    payload = validate_start(body, mode)
    sessions, ops, capability = _sessions(service, principal, mode, control=control, flags=flags, request_id=request_id, base=base,
                                          context=payload['pageContext'], transport=transport)
    blocker = _runtime_blocker(sessions)
    if blocker:
        raise founder_agent.PolicyDisabled(blocker)
    try:
        out = sessions.start(ops, capability, payload, request_id=request_id)
    except AlphaError as error:
        raise founder_agent.control_error(error) from None
    base_path = f"/api/control/v2/agent/voice/sessions/{out['voiceSessionId']}"
    return _envelope(sessions, {**out, 'delegation': {'type': 'client', 'path': base_path + '/delegations', 'modality': 'voice'},
                                'transcriptPath': base_path + '/transcript', 'endPath': base_path + '/end'})


def delegate(service, principal, voice_session_id, body, request_id, *, mode, control=None, values=None, base=None, model_factory=None):
    """POST /agent/voice/sessions/{id}/delegations: one `session.delegation.created` answered by `founder_agent.turn` with
    modality 'voice' in the session's own conversation and data mode (founder tools only; voice ≤ text). One founder turn
    per delegation id: a repeated event or a retried request replays the same turn."""
    founder_agent = _founder_agent()
    from postriff_alpha.domain import AlphaError
    from postriff_phase2.agent_runtime_v2 import live
    founder_agent.require_founder(principal)
    flags = _flags(values)
    require_enabled(flags, control, principal)
    if not isinstance(voice_session_id, str) or not _UUID.match(voice_session_id):
        raise ControlError('VALIDATION_FAILED', 400)
    if not isinstance(body, dict) or not {'delegationId', 'message'} <= set(body) or set(body) - DELEGATION_KEYS:
        raise ControlError('VALIDATION_FAILED', 400)
    delegation = body['delegationId']
    if not isinstance(delegation, str) or not _DELEGATION.match(delegation):
        raise ControlError('VALIDATION_FAILED', 400)
    voice_session_id = voice_session_id.lower()
    sessions, ops, capability = _sessions(service, principal, mode, control=control, flags=flags, request_id=request_id, base=base)
    try:
        conversation_id = sessions.bound(ops, capability, voice_session_id)
    except AlphaError as error:
        raise founder_agent.control_error(error) from None
    turn = {'message': body['message'], 'mode': mode, 'conversationId': conversation_id, 'modality': 'voice',
            'idempotencyKey': f'voice:{voice_session_id}:{delegation}', **{name: body[name] for name in ('timeZone', 'locale', 'pageContext') if body.get(name) is not None}}
    out = founder_agent.turn(service, principal, turn, request_id, control=control, values=flags, base=base, model_factory=model_factory)
    try:
        sessions.note_delegation(ops, capability, voice_session_id, delegation, out.get('runId'))
    except Exception:  # noqa: BLE001 - bookkeeping never changes the answer the founder already has
        pass
    return {**out, 'voiceSessionId': voice_session_id, 'delegationId': delegation, 'speakable': live.speakable_result(out)}


def transcript(service, principal, voice_session_id, body, request_id, *, mode, control=None, values=None, base=None):
    """POST /agent/voice/sessions/{id}/transcript: text of what was said (no audio), on the caller's own session."""
    founder_agent = _founder_agent()
    from postriff_alpha.domain import AlphaError
    if not isinstance(voice_session_id, str) or not _UUID.match(voice_session_id) or not isinstance(body, dict) or set(body) - {'turns'}:
        raise ControlError('VALIDATION_FAILED', 400)
    sessions, ops, capability = _sessions(service, principal, mode, control=control, flags=_flags(values), request_id=request_id, base=base)
    try:
        return _envelope(sessions, sessions.transcript(ops, capability, voice_session_id.lower(), body))
    except AlphaError as error:
        raise founder_agent.control_error(error) from None


def end(service, principal, voice_session_id, body, request_id, *, mode, control=None, values=None, base=None):
    """POST /agent/voice/sessions/{id}/end: end and settle the caller's own session (server clock; costCenter founder_ops)."""
    founder_agent = _founder_agent()
    from postriff_alpha.domain import AlphaError
    if not isinstance(voice_session_id, str) or not _UUID.match(voice_session_id) or not isinstance(body, dict) or set(body) - {'usageSeconds', 'reason'}:
        raise ControlError('VALIDATION_FAILED', 400)
    sessions, ops, capability = _sessions(service, principal, mode, control=control, flags=_flags(values), request_id=request_id, base=base)
    try:
        return _envelope(sessions, sessions.end(ops, capability, voice_session_id.lower(), body))
    except AlphaError as error:
        raise founder_agent.control_error(error) from None


# --- HTTP handlers (fn(app, principal, request); CONTRACTS §8.0) --------------------------------------------------------------------
def _consumer(app):
    """The consumer runtime for the status read, or None (separate mount, or a runtime that does not build here)."""
    try:
        return app.consumer()
    except Exception:  # noqa: BLE001 - status names the blocker instead of failing
        return None


def http_status(app, principal, request):
    return status(_consumer(app), principal, mode=request['mode'], control=app, values=app.flags, request_id=request['requestId'])


def http_start(app, principal, request):
    _founder_agent().require_founder(principal)
    require_enabled(app.flags, app, principal)   # the policy answer comes before "no consumer runtime here"
    return start(app.consumer(), principal, request['body'], request['requestId'], mode=request['mode'], control=app, values=app.flags)


def http_delegate(app, principal, request):
    _founder_agent().require_founder(principal)
    require_enabled(app.flags, app, principal)
    return delegate(app.consumer(), principal, request['match'][0], request['body'], request['requestId'], mode=request['mode'], control=app, values=app.flags)


def http_transcript(app, principal, request):
    return transcript(app.consumer(), principal, request['match'][0], request['body'], request['requestId'], mode=request['mode'], control=app, values=app.flags)


def http_end(app, principal, request):
    return end(app.consumer(), principal, request['match'][0], request['body'], request['requestId'], mode=request['mode'], control=app, values=app.flags)


ROUTES = (('GET', r'/agent/voice/status', 'http_status', {}),
          ('POST', r'/agent/voice/sessions', 'http_start', {'budget': 'founder.voice', 'demo_ok': True}),
          ('POST', rf'/agent/voice/sessions/{SESSION_ID}/delegations', 'http_delegate', {'budget': 'founder.agent.turn', 'demo_ok': True}),
          ('POST', rf'/agent/voice/sessions/{SESSION_ID}/transcript', 'http_transcript', {'budget': 'founder.agent.turn', 'demo_ok': True}),
          ('POST', rf'/agent/voice/sessions/{SESSION_ID}/end', 'http_end', {'budget': 'founder.agent.turn', 'demo_ok': True}))


def register():
    """Register the voice routes once per process (copilot.use; a re-import never duplicates them)."""
    for method, pattern, function, options in ROUTES:
        if not any(existing[0] == method and existing[1].pattern == pattern for existing in http.EXTENSION_ROUTES):
            http.register_route(method, pattern, 'copilot.use', 'founder_voice', function, **options)


register()

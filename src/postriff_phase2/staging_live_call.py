"""One explicitly requested, fixed-destination staging voice test. No mission or retry."""
import uuid

from postriff_alpha.domain import AlphaError

REASON_PREFIX = 'james_live_test:'


def test_identity(value):
    try:
        result = str(uuid.UUID(value))
        if result != value:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise AlphaError('Invalid voice test identity.', 400) from None


def is_voice_test_call(call):
    reason = call.get('reason_key') or ''
    if call.get('destination_ref') != 'james_env' or not reason.startswith(REASON_PREFIX):
        return False
    try:
        test_identity(reason[len(REASON_PREFIX):])
        return True
    except AlphaError:
        return False


def _gate(service, values):
    from .agent_team_acceptance import require_acceptance
    require_acceptance(values, phone=True)
    daily = service.james_daily_call
    daily._require_base()
    if daily.phone.provider.real is not True:
        raise AlphaError('A real phone provider is required.', 409)
    return daily


def _prior(service, daily, identity):
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT id::text FROM public.pr_phone_calls WHERE user_id=%s AND workspace_id=%s "
                    "AND idempotency_key=%s AND reason_key=%s AND destination_ref='james_env'",
                    (daily.cfg.user_id, daily.cfg.workspace_id, REASON_PREFIX + identity, REASON_PREFIX + identity))
        row = cur.fetchone()
    return row[0] if row else None


def preview(service, values):
    from .credit_meter import millicredits
    daily = _gate(service, values)
    seconds = min(120, daily.cfg.max_seconds, daily.phone.config.cap_seconds)
    if daily.cfg.quiet(service.clock()):
        raise AlphaError('Voice test is inside quiet hours.', 409, code='quiet_hours')
    book = service.ledger.credits
    if book is None:
        raise AlphaError('The staging credit ledger is paused; no call was requested.', 503)
    with service.connection_factory() as db, db.cursor() as cur:
        estimate = daily._estimate(seconds)
        daily._budget_check(cur, service.clock(), extra=estimate)
        if not book.policy(cur, daily.cfg.workspace_id):
            raise AlphaError('The staging voice test requires active credit terms.', 409)
        wallet = book.view(cur, daily.cfg.workspace_id)
        if wallet['debtMilliCredits'] or wallet['availableMilliCredits'] < millicredits(estimate):
            raise AlphaError('Existing credits cannot cover this bounded voice test. No call was requested.', 402)
    return {'executionMode': 'staging_voice_test', 'provider': daily.phone.provider.name,
            'model': 'gpt-live-1', 'maxSeconds': seconds, 'destinationConfigured': True,
            'dailyCapUsdMicro': daily.cfg.daily_cap, 'monthlyCapUsdMicro': daily.cfg.monthly_cap,
            'automaticRetry': False, 'nativeAgentRequired': False, 'creditLedgerReady': True}


def start(service, values, request):
    # Reject caller-selected principals, destinations, prompts and durations before any egress.
    if not isinstance(request, dict) or set(request) != {'testId'}:
        raise AlphaError('Send only the voice test identity.', 400)
    identity = test_identity(request['testId'])
    daily = _gate(service, values)
    prior = _prior(service, daily, identity)
    if prior:
        return status(service, values, identity)
    plan = preview(service, values)
    from .phone.runtime import principal_phone
    scoped, capability = principal_phone(daily.phone, daily.cfg.workspace_id, daily.cfg.user_id)
    call = scoped.request(daily.cfg.workspace_id, capability,
                          {'idempotencyKey': REASON_PREFIX + identity,
                           'callDurationLimitSeconds': plan['maxSeconds'], 'useAvailableCredits': True},
                          kind='explicit', reason_key=REASON_PREFIX + identity,
                          _destination=daily.cfg.destination(), _destination_ref='james_env')
    return {**plan, 'testId': identity, 'call': call}


def status(service, values, identity):
    from .agent_team_acceptance import require_acceptance
    from .phone import store
    require_acceptance(values, phone=True)
    identity = test_identity(identity)
    daily = service.james_daily_call
    call_id = _prior(service, daily, identity)
    if not call_id:
        return {'testId': identity, 'state': 'not_requested', 'automaticRetry': False}
    with service.connection_factory() as db, db.cursor() as cur:
        call = store.call(cur, call_id)
        cur.execute('SELECT artifact FROM public.pr_agent_runs WHERE id=%s AND workspace_id=%s',
                    (call['voice_run_id'], daily.cfg.workspace_id))
        row = cur.fetchone()
    voice = ((row[0] or {}).get('voice') or {}) if row else {}
    turns = voice.get('transcript') or []
    # Counts and connection metadata only; transcript text and phone number stay private.
    return {'executionMode': 'staging_voice_test', 'testId': identity, 'call': store.public_call(call),
            'model': 'gpt-live-1', 'liveSessionStarted': bool(voice.get('liveSessionId')),
            'inputTranscriptTurns': sum(t.get('role') == 'user' and bool(t.get('text')) for t in turns),
            'outputTranscriptTurns': sum(t.get('role') == 'assistant' and bool(t.get('text')) for t in turns),
            'mediaClaimed': call.get('media_claimed_at') is not None,
            'automaticRetry': False, 'nativeAgentRequired': False}

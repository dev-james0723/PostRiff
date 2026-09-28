"""Single-use telephone admission from an authenticated Rafii session. Never trusts caller ID."""
import hashlib
import hmac
import re
import secrets

from postriff_alpha.domain import AlphaError
from ..permissions import require
from . import billing, contracts

CODE_SECONDS = 300
AUTH_SECONDS = 45
CODE_DIGITS = 12


def digest(phone, purpose, value):
    return hmac.new(phone.vault.fernet._signing_key,
                    ('rafii-inbound-v1|' + purpose + '|' + value).encode(), hashlib.sha256).hexdigest()


def available(phone):
    return bool(phone.config.enabled('RAFII_PHONE_ENABLED') and phone.config.enabled('RAFII_PHONE_INBOUND_ENABLED')
                and phone.provider and phone.provider.name == 'dial' and phone.provider.configured
                and phone.config.telephony_rate > 0)


def require_available(phone):
    if not available(phone):
        raise AlphaError('Dial-in calling is unavailable on this deployment.', 409, code='inbound_disabled')


def issue(phone, workspace_id, token, payload):
    require_available(phone)
    if not isinstance(payload, dict) or set(payload) - {'conversationId', 'maxMilliCredits', 'useAvailableCredits'}:
        raise AlphaError('Send valid Agent Pairing Code options.', 400)
    code = f'{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}'
    now = phone.clock()
    with phone.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(phone.hosted.ideas._member(row), 'edit')
        phone.hosted.repository.assert_fresh(token, principal)
        phone._lock(cur, principal)
        cur.execute('SELECT count(*),max(extract(epoch from created_at)) FROM public.pr_phone_inbound_codes '
                    'WHERE user_id=%s AND created_at>to_timestamp(%s)', (principal, now - 3600))
        count, last = cur.fetchone()
        if count >= 6 or (last is not None and now - float(last) < 30):
            raise AlphaError('Wait before creating another Agent Pairing Code.', 429, code='inbound_code_limit')
        conversation = payload.get('conversationId')
        if conversation:
            phone.hosted.ideas._conversation(cur, workspace_id, conversation)
        maximum = payload.get('maxMilliCredits')
        spending = billing.spending(phone, cur, workspace_id, direction='inbound', principal=principal)
        if maximum is not None and (type(maximum) is not int or not 0 <= maximum <= 100_000_000):
            raise AlphaError('Choose a valid call credit limit.', 400)
        if spending['usesCredits'] and payload.get('useAvailableCredits') is not True and (type(maximum) is not int or maximum < spending['ceilingMilliCredits']):
            raise AlphaError('Confirm a credit limit covering phone and voice time.', 402, code='phone_credit_limit')
        if spending['usesCredits'] and spending['availableMilliCredits'] < spending['ceilingMilliCredits']:
            raise AlphaError('Not enough available credits for this call.', 402, code='phone_credit_balance')
        # One outstanding code per person across workspaces. New code explicitly replaces the previous one.
        cur.execute('UPDATE public.pr_phone_inbound_codes SET revoked_at=to_timestamp(%s) '
                    'WHERE user_id=%s AND consumed_at IS NULL AND revoked_at IS NULL', (now, principal))
        cur.execute('INSERT INTO public.pr_phone_inbound_codes(user_id,workspace_id,conversation_id,code_hash,maximum_millicredits,use_available_credits,created_at,expires_at) '
                    'VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) RETURNING id::text',
                    (principal, workspace_id, conversation, digest(phone, 'code', code), maximum, payload.get('useAvailableCredits') is True, now, now + CODE_SECONDS))
        code_id = cur.fetchone()[0]
    # Only this response contains the code. Never put it in call history, query responses or diagnostics.
    return {'id': code_id, 'code': code, 'expiresAt': now + CODE_SECONDS,
            'phoneNumber': phone.provider.originating_number, 'conversationId': conversation}


def revoke(phone, workspace_id, token, code_id):
    with phone.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(phone.hosted.ideas._member(row), 'edit')
        phone._lock(cur, principal)
        cur.execute('UPDATE public.pr_phone_inbound_codes SET revoked_at=now() WHERE id::text=%s '
                    'AND user_id=%s AND workspace_id=%s AND consumed_at IS NULL', (code_id, principal, workspace_id))
    return {'revoked': True}


def status(phone, workspace_id, token, code_id):
    from . import store
    with phone.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(phone.hosted.ideas._member(row), 'edit')
        cur.execute('SELECT consumed_at IS NOT NULL,revoked_at IS NOT NULL,extract(epoch from expires_at),call_id::text '
                    'FROM public.pr_phone_inbound_codes WHERE id::text=%s AND user_id=%s AND workspace_id=%s',
                    (code_id, principal, workspace_id))
        ticket = cur.fetchone()
        if not ticket:
            raise AlphaError('Agent Pairing Code unavailable.', 404)
        used, revoked, expiry, call_id = ticket
        state = 'used' if used else 'revoked' if revoked else 'expired' if phone.clock() >= float(expiry) else 'ready'
        call = store.call(cur, call_id) if call_id else None
        return {'state': state, 'call': store.public_call(call) if call else None}


def begin(phone, call_ref, caller):
    """Called only after the provider signature and called number are verified. Shared DB rate limits."""
    require_available(phone)
    from .code_speech import RESERVE_USD_MICRO
    now = phone.clock()
    caller_hash = digest(phone, 'caller', caller)
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('phone-inbound-admission',0))")
        cleanup(phone, cur)
        cur.execute('SELECT count(*) FILTER(WHERE started_at>to_timestamp(%s)),count(*) FILTER(WHERE call_id IS NULL),'
                    'count(*) FILTER(WHERE caller_hash=%s AND started_at>to_timestamp(%s)),count(*) '
                    'FROM public.pr_phone_inbound_sessions WHERE started_at>to_timestamp(%s)',
                    (now - 3600, caller_hash, now - 600, now - 86400))
        hourly, unauthenticated, same_caller, total = cur.fetchone()
        cur.execute('SELECT count(*) FROM public.pr_phone_auth_challenges WHERE created_at>to_timestamp(%s)', (now - 86400,))
        repeat_exposure = cur.fetchone()[0] * 2 * phone.config.telephony_rate
        # Authenticated calls already reserve their 45s greeting in billing.estimates.
        # Keep failed/unknown greetings here, but never charge funded greetings twice.
        # The operator also reserves bounded STT for every admission, even if it later authenticates.
        reason = ('inbound_hourly_limit' if hourly >= 12 else 'inbound_caller_limit' if same_caller >= 3 else
                  'inbound_auth_budget' if (unauthenticated + 1) * phone.config.telephony_rate + (total + 1) * RESERVE_USD_MICRO + repeat_exposure > phone.config.inbound_auth_budget else None)
        if reason:
            from .diagnostics import report_failure
            report_failure(None, 'inbound_admission', AlphaError('Inbound admission unavailable.', 429, code=reason))
            return False
        cur.execute('INSERT INTO public.pr_phone_inbound_sessions(provider_call_ref,caller_hash,started_at) '
                    'VALUES(%s,%s,to_timestamp(%s)) ON CONFLICT DO NOTHING RETURNING provider_call_ref', (call_ref, caller_hash, now))
        return bool(cur.fetchone())


def cleanup(phone, cur):
    now = phone.clock()
    cur.execute('DELETE FROM public.pr_phone_inbound_sessions WHERE started_at<to_timestamp(%s)', (now - 172800,))
    cur.execute('DELETE FROM public.pr_phone_inbound_codes WHERE expires_at<to_timestamp(%s)', (now - 86400,))


def authenticate(phone, call_ref, code):
    """Three attempts per signed call; ticket consumption and call reservations commit together."""
    require_available(phone)
    now = phone.clock()
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute('UPDATE public.pr_phone_inbound_sessions SET attempts=attempts+1 WHERE provider_call_ref=%s '
                    'AND call_id IS NULL AND ended_at IS NULL AND attempts<3 AND coalesce(pairing_started_at,started_at)>to_timestamp(%s) RETURNING attempts',
                    (call_ref, now - AUTH_SECONDS))
        if not cur.fetchone():
            return None
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{12}', code):
            return None
        fingerprint = digest(phone, 'code', code)
        cur.execute('SELECT user_id::text,workspace_id::text,conversation_id::text,maximum_millicredits,use_available_credits '
                    'FROM public.pr_phone_inbound_codes WHERE code_hash=%s AND consumed_at IS NULL '
                    'AND revoked_at IS NULL AND expires_at>to_timestamp(%s)', (fingerprint, now))
        ticket = cur.fetchone()
    if not ticket:
        return None
    from .runtime import principal_phone
    user, workspace, conversation, maximum, use_available = ticket
    scoped, capability = principal_phone(phone, workspace, user)
    try:
        return scoped.request(workspace, capability, {'idempotencyKey': 'inbound:' + hashlib.sha256(call_ref.encode()).hexdigest(),
            'conversationId': conversation, 'maxMilliCredits': maximum, 'useAvailableCredits':use_available}, dispatch=False,
            _inbound=(call_ref, fingerprint))['id']
    except AlphaError:
        return None  # Same public failure for unknown code, revoked membership, active call and insufficient budget.


def claim(cur, phone, principal, workspace, call_ref, fingerprint):
    now = phone.clock()
    cur.execute('SELECT caller_hash FROM public.pr_phone_inbound_sessions WHERE provider_call_ref=%s '
                'AND call_id IS NULL AND ended_at IS NULL AND attempts BETWEEN 1 AND 3 '
                'AND coalesce(pairing_started_at,started_at)>to_timestamp(%s) FOR UPDATE', (call_ref, now - AUTH_SECONDS))
    session = cur.fetchone()
    cur.execute('SELECT id FROM public.pr_phone_inbound_codes WHERE code_hash=%s AND user_id=%s AND workspace_id=%s '
                'AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>to_timestamp(%s) FOR UPDATE',
                (fingerprint, principal, workspace, now))
    ticket = cur.fetchone()
    if not session or not ticket:
        raise AlphaError('Agent Pairing Code unavailable.', 403)
    cur.execute('SELECT 1 FROM public.pr_phone_auth_challenges c JOIN public.pr_phone_inbound_codes p ON p.id=%s WHERE c.provider_call_ref=%s AND (c.state<>\'fallback\' OR p.created_at<c.created_at)', (ticket[0], call_ref))
    if cur.fetchone():
        raise AlphaError('Issue a new Agent Pairing Code for recovery.', 403)
    cur.execute('UPDATE public.pr_phone_inbound_codes SET consumed_at=to_timestamp(%s) WHERE id=%s', (now, ticket[0]))
    from . import call_auth
    call_auth.enroll(cur, phone, principal, workspace, session[0], ticket[0])
    return ticket[0]


def ended(phone, call_ref):
    with phone.hosted.connection_factory() as db:
        db.execute('UPDATE public.pr_phone_inbound_sessions SET ended_at=coalesce(ended_at,now()) WHERE provider_call_ref=%s', (call_ref,))
        db.execute("UPDATE public.pr_phone_auth_challenges SET state='denied' WHERE provider_call_ref=%s AND state IN ('pending','approved')", (call_ref,))

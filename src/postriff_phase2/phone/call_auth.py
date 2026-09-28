"""Call-bound WebAuthn admission. Caller hashes select a route; they never authorize it."""
import hashlib
import re
from contextlib import contextmanager
from urllib.parse import urlparse

from postriff_alpha.domain import AlphaError
from ..permissions import require
from ..hosted_identity import verified_aal, verified_session_id, verified_webauthn_time
from . import inbound, billing

CHALLENGE_SECONDS = 90
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')


def unavailable():
    return AlphaError('This call verification is unavailable. Use a new Agent Pairing Code.', 409)


def enroll(cur, phone, user, workspace, caller_hash, code_id):
    cur.execute('INSERT INTO public.pr_phone_trusted_callers(user_id,workspace_id,caller_hash,created_from_code_id,verified_at) '
                'VALUES(%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(user_id,workspace_id,caller_hash) DO UPDATE SET '
                'created_from_code_id=excluded.created_from_code_id,verified_at=excluded.verified_at,revoked_at=NULL,updated_at=now()',
                (user, workspace, caller_hash, code_id, phone.clock()))


def routes(cur, caller_hash):
    cur.execute('SELECT t.id::text,t.user_id::text,t.workspace_id::text FROM public.pr_phone_trusted_callers t '
                'JOIN public.pr_memberships m ON m.user_id=t.user_id AND m.workspace_id=t.workspace_id '
                'JOIN public.pr_profiles p ON p.user_id=t.user_id '
                "WHERE t.caller_hash=%s AND t.revoked_at IS NULL AND m.status='active' AND p.deleted_at IS NULL ORDER BY t.id",
                (caller_hash,))
    return cur.fetchall()


def create(phone, call_ref):
    """Signed admission already exists. Serializes route/abuse checks; transactional outbox only."""
    notifications = getattr(phone.hosted, 'notifications', None)
    if not notifications or not notifications.enabled():
        return None  # No verification surface can be notified; use the pairing path.
    now = phone.clock()
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        # Share the operator budget lock with inbound.begin: a bootstrap admission and
        # a repeat waiting reservation must not both spend the same remaining exposure.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('phone-inbound-admission',0))")
        cur.execute('SELECT caller_hash FROM public.pr_phone_inbound_sessions WHERE provider_call_ref=%s '
                    'AND ended_at IS NULL AND call_id IS NULL FOR UPDATE', (call_ref,))
        session = cur.fetchone()
        if not session:
            return None
        choices = routes(cur, session[0])
        if len(choices) != 1:
            return None
        route, user, workspace = choices[0]
        cur.execute('SELECT 1 FROM public.pr_phone_trusted_callers WHERE id=%s AND suppressed_until>to_timestamp(%s)', (route, now))
        if cur.fetchone():
            return None
        cur.execute('SELECT id::text,state FROM public.pr_phone_auth_challenges WHERE provider_call_ref=%s', (call_ref,))
        prior = cur.fetchone()
        if prior:
            return prior[0] if prior[1] == 'pending' else None
        cur.execute("SELECT count(*),count(*) FILTER(WHERE created_at>to_timestamp(%s)),count(*) FILTER(WHERE state='denied' AND created_at>to_timestamp(%s)) "
                    'FROM public.pr_phone_auth_challenges WHERE user_id=%s AND created_at>to_timestamp(%s)',
                    (now - 60, now - 600, user, now - 3600))
        hourly, recent, denied = cur.fetchone()
        if hourly >= 3 or recent or denied:
            return None
        # Repeat waiting costs up to 90s plus a 45s fallback. Reserve the extra operator exposure.
        cur.execute('SELECT count(*) FROM public.pr_phone_auth_challenges WHERE created_at>to_timestamp(%s)', (now - 86400,))
        repeat_count = cur.fetchone()[0]
        from .code_speech import RESERVE_USD_MICRO
        cur.execute('SELECT count(*) FILTER(WHERE call_id IS NULL),count(*) FROM public.pr_phone_inbound_sessions WHERE started_at>to_timestamp(%s)', (now - 86400,))
        failed, total = cur.fetchone()
        if (failed + (repeat_count + 1) * 2) * phone.config.telephony_rate + total * RESERVE_USD_MICRO > phone.config.inbound_auth_budget:
            return None
        cur.execute('INSERT INTO public.pr_phone_auth_challenges(provider_call_ref,trusted_caller_id,user_id,workspace_id,caller_hash,created_at,expires_at) '
                    'VALUES(%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) RETURNING id::text',
                    (call_ref, route, user, workspace, session[0], now, now + CHALLENGE_SECONDS))
        challenge = cur.fetchone()[0]
        if notifications:
            notice = notifications.emit(cur, workspace_id=None, user_id=user, event_type='security.phone_call',
                dedupe_key='phone-auth:' + challenge, grouping_key='phone-auth:' + challenge, expires_at=now + CHALLENGE_SECONDS,
                payload={'title': 'Verify your current call', 'detail': 'Confirm this call with your passkey. If you did not call Rafii, ignore this request.',
                         'href': '/app/phone/verify-call?challenge=' + challenge}, channel_filter={'in_app', 'push'})
            if not any(d.get('status') in ('pending', 'delivered') for d in notice.get('deliveries', [])):
                cur.execute("UPDATE public.pr_phone_auth_challenges SET state='fallback' WHERE id=%s", (challenge,))
                return None
        return challenge


def load(cur, challenge):
    cur.execute('SELECT c.*,extract(epoch from c.created_at) AS created_seconds,extract(epoch from c.expires_at) AS expires_seconds,'
                'extract(epoch from c.ceremony_started_at) AS ceremony_seconds FROM public.pr_phone_auth_challenges c WHERE c.id::text=%s', (challenge,))
    row = cur.fetchone()
    return dict(zip([d.name for d in cur.description], row)) if row else None


def valid(cur, phone, item, *, states=('pending',)):
    if not item or item['state'] not in states or phone.clock() >= float(item['expires_seconds']):
        raise unavailable()
    cur.execute('SELECT caller_hash FROM public.pr_phone_inbound_sessions WHERE provider_call_ref=%s AND ended_at IS NULL AND call_id IS NULL FOR UPDATE', (item['provider_call_ref'],))
    session = cur.fetchone()
    cur.execute('SELECT 1 FROM public.pr_phone_trusted_callers WHERE id=%s AND revoked_at IS NULL FOR UPDATE', (item['trusted_caller_id'],))
    route = cur.fetchone()
    if not session or session[0] != item['caller_hash'] or not route or routes(cur, item['caller_hash']) != [(str(item['trusted_caller_id']), str(item['user_id']), str(item['workspace_id']))]:
        raise unavailable()
    cur.execute('SELECT 1 FROM public.pr_phone_auth_challenges WHERE id=%s FOR UPDATE', (item['id'],))
    # Re-read after the session/route locks; deny, hang-up and consume use the same lock order.
    current = load(cur, str(item['id']))
    if current['state'] not in states:
        raise unavailable()
    return current


@contextmanager
def user_challenge(phone, token, challenge):
    user = phone.hosted.repository.verify_session(token)
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        item = load(cur, challenge)
        if not item or str(item['user_id']) != user:
            raise AlphaError('Call verification unavailable.', 404)
        workspace = str(item['workspace_id'])
    with phone.hosted.repository.transaction(token, workspace) as (cur, row, principal):
        require(phone.hosted.ideas._member(row), 'edit')
        phone._lock(cur, principal)
        item = load(cur, challenge)
        if not item or str(item['user_id']) != principal:
            raise AlphaError('Call verification unavailable.', 404)
        yield cur, item, principal


def status(phone, token, challenge):
    with user_challenge(phone, token, challenge) as (cur, item, user):
        state = item['state']
        if state in ('pending', 'approved'):
            try:
                valid(cur, phone, item, states=('pending', 'approved'))
            except AlphaError:
                state = 'expired' if phone.clock() >= float(item['expires_seconds']) else 'denied'
        spending = billing.spending(phone, cur, str(item['workspace_id']), direction='inbound', principal=user)
        return {'state': state, 'startedAt': float(item['created_seconds']), 'expiresAt': float(item['expires_seconds']),
                'workspaceId': str(item['workspace_id']), 'spending': spending}


def origin(phone):
    value = str(getattr(phone.hosted, 'public_base_url', '') or '').rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.username or parsed.query or parsed.fragment:
        raise unavailable()
    return value, parsed.hostname


def factor_exists(phone, user, factor):
    identity = getattr(phone.hosted, 'identity', None)
    return bool(identity and any(f['id'] == factor and f['type'] == 'webauthn' for f in identity.verified_factors(user)))


def prepare(phone, token, challenge, payload):
    factor = payload.get('factorId')
    if not isinstance(factor, str) or not UUID.fullmatch(factor):
        raise unavailable()
    with user_challenge(phone, token, challenge) as (cur, item, user):
        item = valid(cur, phone, item)
        if item['ceremony_attempts'] >= 3 or not factor_exists(phone, user, factor):
            raise unavailable()
        session = phone.hosted.repository.verify_session.session_id(token, user)
        attempt = item['ceremony_attempts'] + 1
        cur.execute('UPDATE public.pr_phone_auth_challenges SET factor_id=%s,factor_challenge_id=NULL,ceremony_session_id=%s,'
                    'ceremony_started_at=to_timestamp(%s),ceremony_attempts=%s,verification_used=false WHERE id=%s',
                    (factor, session, phone.clock(), attempt, item['id']))
    # Commit the attempt before network I/O: failures cannot undo the attempt cap.
    site, rp = origin(phone)
    result = phone.hosted.identity.phone_mfa_challenge(token, factor, rp, site)
    if not UUID.fullmatch(str(result.get('id', ''))) or result.get('type') != 'webauthn' or (result.get('webauthn') or {}).get('type') != 'request':
        raise unavailable()
    with user_challenge(phone, token, challenge) as (cur, item, user):
        item = valid(cur, phone, item)
        if item['ceremony_attempts'] != attempt or item['ceremony_session_id'] != session:
            raise unavailable()
        cur.execute('UPDATE public.pr_phone_auth_challenges SET factor_challenge_id=%s WHERE id=%s', (result['id'], item['id']))
        return {'publicKey': result['webauthn']['credential_options']['publicKey']}


def approve(phone, token, challenge, payload):
    with user_challenge(phone, token, challenge) as (cur, item, user):
        item = valid(cur, phone, item)
        session = phone.hosted.repository.verify_session.session_id(token, user)
        if item['verification_used'] or not item['factor_challenge_id'] or item['ceremony_session_id'] != session or not factor_exists(phone, user, str(item['factor_id'])):
            raise unavailable()
        bound_nonce = item['factor_challenge_id']
        step_started = float(item['ceremony_seconds'])
        cur.execute('UPDATE public.pr_phone_auth_challenges SET verification_used=true WHERE id=%s', (item['id'],))
    # At most one verify request for each provider nonce, including uncertain/error outcomes.
    # No domain locks across provider I/O: hang-up, deny and revoke can invalidate this approval.
    site, rp = origin(phone)
    result = phone.hosted.identity.phone_mfa_verify(token, str(item['factor_id']), str(bound_nonce), rp, site, payload.get('credential'))
    fresh_token = result.get('access_token', '')
    verified = phone.hosted.repository.verify_session(fresh_token)
    step_time = verified_webauthn_time(fresh_token, user)
    if (verified != user or verified_aal(fresh_token, user) != 'aal2' or verified_session_id(fresh_token, user) != session
            or not int(step_started) <= step_time <= phone.clock() + 1):
        raise unavailable()
    with user_challenge(phone, fresh_token, challenge) as (cur, item, user):
        item = valid(cur, phone, item)
        if item['factor_challenge_id'] != bound_nonce or not factor_exists(phone, user, str(item['factor_id'])):
            raise unavailable()
        maximum, available = payload.get('maxMilliCredits'), payload.get('useAvailableCredits') is True
        if maximum is not None and (type(maximum) is not int or not 0 <= maximum <= 100_000_000):
            raise unavailable()
        spending = billing.spending(phone, cur, str(item['workspace_id']), direction='inbound', principal=user)
        if spending['usesCredits'] and not available and (maximum is None or maximum < spending['ceilingMilliCredits']):
            raise AlphaError('Confirm the phone and voice credit limit.', 402)
        cur.execute("UPDATE public.pr_phone_auth_challenges SET state='approved',approved_at=to_timestamp(%s),approved_session_id=%s,"
                    "approved_factor_kind='webauthn',maximum_millicredits=%s,use_available_credits=%s WHERE id=%s",
                    (phone.clock(), session, maximum, available, item['id']))
        return {'state': 'approved', 'session': {'access_token': fresh_token, 'refresh_token': result['refresh_token']}}


def dismiss(phone, token, challenge, action):
    if action not in ('deny', 'fallback', 'cancel'):
        raise unavailable()
    with user_challenge(phone, token, challenge) as (cur, item, _):
        item = valid(cur, phone, item, states=('pending', 'approved'))
        target = 'denied' if action == 'deny' else 'fallback'
        cur.execute('UPDATE public.pr_phone_auth_challenges SET state=%s WHERE id=%s', (target, item['id']))
        if action == 'deny':
            cur.execute('UPDATE public.pr_phone_trusted_callers SET suppressed_until=to_timestamp(%s) WHERE id=%s', (phone.clock() + 600, item['trusted_caller_id']))
    return {'state': target}


def fallback(phone, call_ref):
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT 1 FROM public.pr_phone_inbound_sessions WHERE provider_call_ref=%s AND ended_at IS NULL AND call_id IS NULL FOR UPDATE', (call_ref,))
        if not cur.fetchone():
            return False
        cur.execute('SELECT state FROM public.pr_phone_auth_challenges WHERE provider_call_ref=%s FOR UPDATE', (call_ref,))
        found = cur.fetchone()
        if found and found[0] in ('denied', 'consumed'):
            return False
        cur.execute("UPDATE public.pr_phone_auth_challenges SET state='fallback' WHERE provider_call_ref=%s AND state IN ('pending','approved','expired')", (call_ref,))
        cur.execute('UPDATE public.pr_phone_inbound_sessions SET pairing_started_at=coalesce(pairing_started_at,to_timestamp(%s)) WHERE provider_call_ref=%s', (phone.clock(), call_ref))
        return True


def poll(phone, call_ref, challenge):
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        item = load(cur, challenge)
        if not item or item['provider_call_ref'] != call_ref:
            return 'denied'
        if phone.clock() >= float(item['expires_seconds']):
            return 'expired'
        return item['state']


def consume(phone, call_ref, challenge):
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        item = load(cur, challenge)
        if not item or item['provider_call_ref'] != call_ref or item['state'] != 'approved':
            return None
    # Verify still-enrolled factor immediately before the atomic domain transaction.
    if not factor_exists(phone, str(item['user_id']), str(item['factor_id'])):
        return None
    from .runtime import principal_phone
    scoped, capability = principal_phone(phone, str(item['workspace_id']), str(item['user_id']))
    try:
        return scoped.request(str(item['workspace_id']), capability,
            {'idempotencyKey': 'inbound:' + hashlib.sha256(call_ref.encode()).hexdigest(),
             'maxMilliCredits': item['maximum_millicredits'], 'useAvailableCredits': item['use_available_credits']},
            dispatch=False, _inbound=(call_ref, challenge), _call_challenge=True)['id']
    except AlphaError:
        return None


def claim(cur, phone, user, workspace, call_ref, challenge):
    item = load(cur, challenge)
    if not item or item['provider_call_ref'] != call_ref or str(item['user_id']) != user or str(item['workspace_id']) != workspace:
        raise unavailable()
    item = valid(cur, phone, item, states=('approved',))
    cur.execute('SELECT 1 FROM public.pr_session_revocations WHERE user_id=%s AND session_id=%s', (user, item['approved_session_id']))
    if cur.fetchone() or item['approved_factor_kind'] != 'webauthn':
        raise unavailable()
    cur.execute("UPDATE public.pr_phone_auth_challenges SET state='consumed',consumed_at=to_timestamp(%s) WHERE id=%s", (phone.clock(), item['id']))
    cur.execute('UPDATE public.pr_phone_trusted_callers SET last_used_at=to_timestamp(%s) WHERE id=%s', (phone.clock(), item['trusted_caller_id']))
    return item['id']


def trusted(phone, workspace, token, revoke=None):
    with phone.hosted.repository.transaction(token, workspace) as (cur, row, user):
        require(phone.hosted.ideas._member(row), 'edit')
        phone._lock(cur, user)
        if revoke:
            phone.hosted.repository.assert_fresh(token, user)
            if phone.hosted.repository.verify_session.aal(token, user) != 'aal2':
                raise AlphaError('Confirm your passkey in Security settings first.', 403)
            cur.execute('UPDATE public.pr_phone_trusted_callers SET revoked_at=to_timestamp(%s),updated_at=now() WHERE id::text=%s AND user_id=%s AND workspace_id=%s', (phone.clock(), revoke, user, workspace))
            return {'revoked': True}
        cur.execute('SELECT id::text,extract(epoch from verified_at),extract(epoch from last_used_at) FROM public.pr_phone_trusted_callers WHERE user_id=%s AND workspace_id=%s AND revoked_at IS NULL ORDER BY verified_at DESC', (user, workspace))
        return {'callers': [{'id': r[0], 'pairedAt': float(r[1]), 'lastUsedAt': float(r[2]) if r[2] else None} for r in cur.fetchall()]}

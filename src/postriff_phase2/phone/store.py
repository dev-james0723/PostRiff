"""SQL phone ledger. Provider payloads and raw identity never enter call rows."""
import json

from .contracts import DEFAULTS, TERMINAL, failure_message, transition

CALL_COLUMNS = ('id', 'user_id', 'workspace_id', 'conversation_id', 'voice_run_id', 'kind', 'reason_key', 'idempotency_key', 'provider', 'provider_call_ref', 'state',
                'number_hash', 'max_seconds', 'live_reservation_id', 'telephony_reservation_id', 'reserved_usd_micro', 'requested_at', 'answered_at', 'ended_at',
                'duration_seconds', 'failure_class', 'media_claimed_at', 'live_usage_seconds', 'direction', 'funded_seconds', 'media_generation', 'media_resume_until', 'media_usage_seconds')
SELECT_CALL = ','.join('extract(epoch from '+v+')' if v.endswith('_at') or v == 'media_resume_until' else v+'::text' if v in ('id','user_id','workspace_id','conversation_id','voice_run_id','live_reservation_id','telephony_reservation_id') else v for v in CALL_COLUMNS)


def call(cur, call_id, *, lock=False):
    cur.execute(f'SELECT {SELECT_CALL} FROM public.pr_phone_calls WHERE id::text=%s' + (' FOR UPDATE' if lock else ''), (call_id,))
    row = cur.fetchone()
    return dict(zip(CALL_COLUMNS, row)) if row else None


def prefs(cur, principal, workspace_id):
    cur.execute('SELECT preferences FROM public.pr_phone_preferences WHERE user_id=%s AND workspace_id=%s', (principal, workspace_id))
    row = cur.fetchone()
    if row:
        return {**DEFAULTS,**row[0]}
    cur.execute('SELECT time_zone FROM public.pr_profiles WHERE user_id=%s',(principal,))
    profile=cur.fetchone()
    return {**DEFAULTS,'timeZone':profile[0] if profile and profile[0] else DEFAULTS['timeZone']}


def save_prefs(cur, principal, workspace_id, value):
    cur.execute('INSERT INTO public.pr_phone_preferences(user_id,workspace_id,preferences) VALUES(%s,%s,%s::jsonb) '
                'ON CONFLICT(user_id,workspace_id) DO UPDATE SET preferences=excluded.preferences,updated_at=now()', (principal, workspace_id, json.dumps(value)))


def number(cur, principal):
    cur.execute('SELECT phone_ciphertext,key_id,phone_hash,last_four,verified_at IS NOT NULL,verification_ref FROM public.pr_phone_numbers WHERE user_id=%s', (principal,))
    row = cur.fetchone()
    return dict(zip(('ciphertext','key_id','hash','last_four','verified','verification_ref'), row)) if row else None


def set_state(cur, value, state, duration=None):
    next_state = transition(value['state'], state)
    cur.execute('UPDATE public.pr_phone_calls SET state=%s,ringing_at=CASE WHEN %s=\'ringing\' THEN coalesce(ringing_at,now()) ELSE ringing_at END,'
                'answered_at=CASE WHEN %s IN (\'answered\',\'live\') THEN coalesce(answered_at,now()) ELSE answered_at END,'
                'ended_at=CASE WHEN %s THEN coalesce(ended_at,now()) ELSE ended_at END,duration_seconds=coalesce(%s,duration_seconds) WHERE id=%s',
                (next_state, next_state, next_state, next_state in TERMINAL, duration, value['id']))
    return next_state


def public_call(value):
    return {'id': value['id'], 'conversationId': value['conversation_id'], 'state': value['state'], 'kind': value['kind'], 'provider': value['provider'],
            'direction': value.get('direction', 'outbound'),
            'requestedAt': float(value['requested_at']), 'durationSeconds': value['duration_seconds'], 'failure': value['failure_class'],
            'failureMessage': failure_message(value['failure_class']) if value['failure_class'] or value['state'] in ('failed', 'cancelled') else None,
            'maxSeconds': value['max_seconds'], 'execution': 'fake' if value['provider'] == 'fake' else 'provider'}

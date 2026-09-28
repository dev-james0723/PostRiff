"""Phone cost approval uses the existing credit quotes, reservations and settlement."""
import math

from postriff_alpha.domain import AlphaError
from ..contracts import digest
from ..credit_meter import millicredits
from ..developer_usage import ai_usage_exempt
from . import store


# Keep the original ceiling for audit. Until BOTH components have confirmed usage,
# retain the whole hold; an ambiguous call must never free capacity for a redial.
# This also applies to existing rows, so no migration or ledger rewrite is needed.
DAILY_COST_SQL = """CASE WHEN live_cost_usd_micro IS NOT NULL AND telephony_cost_usd_micro IS NOT NULL
    THEN live_cost_usd_micro + telephony_cost_usd_micro
    ELSE greatest(reserved_usd_micro, coalesce(live_cost_usd_micro,0) + coalesce(telephony_cost_usd_micro,0)) END"""


def estimates(phone, *, direction='outbound', seconds=60):
    return (
        phone.agent().cfg.live_usd_micro_per_minute * math.ceil((seconds + 15) / 60),
        phone.config.telephony_rate * math.ceil((seconds + (45 if direction == 'inbound' else 0)) / 60),
    )


def spending(phone, cur, workspace_id, *, direction='outbound', principal=None):
    book = phone.hosted.ledger.credits
    active = bool(not ai_usage_exempt(principal) and book and book.policy(cur, workspace_id))
    return {'usesCredits': active, 'ceilingMilliCredits': sum(millicredits(v) for v in estimates(phone, direction=direction)),
            'availableMilliCredits': book.view(cur, workspace_id)['availableMilliCredits'] if active else None}


def authorities(phone, cur, workspace_id, principal, revision, *, maximum, conversation_id, number_hash, kind, reason, costs, use_available=False):
    if ai_usage_exempt(principal):
        return None, None
    book = phone.hosted.ledger.credits
    if not book or not book.policy(cur, workspace_id):
        return None, None
    ceilings = [millicredits(cost) for cost in costs]
    if not use_available and (type(maximum) is not int or not sum(ceilings) <= maximum <= 100_000_000):
        raise AlphaError('Confirm a credit limit covering phone and voice time before calling.', 402, code='phone_credit_limit')
    if book.view(cur, workspace_id)['availableMilliCredits'] < sum(ceilings):
        raise AlphaError('Not enough available credits for this call. No call was placed.', 402, code='phone_credit_balance')
    route = phone.agent().cfg.route('voice_front_end', reason='phone credit limit')
    result = []
    for cost, ceiling, provider, model in zip(costs, ceilings, ('openai', phone.provider.name), (route.model, 'pstn')):
        if not cost:
            result.append(None)
            continue
        binding = digest({'operation': 'phone', 'conversationId': conversation_id, 'numberHash': number_hash,
                          'kind': kind, 'reason': reason, 'capSeconds': phone.config.cap_seconds,
                          'costs': list(costs), 'model': model, 'provider': provider, 'approvedMaximum': maximum, 'useAvailableCredits': use_available})
        quote = book.issue(cur, workspace_id, principal, revision, binding, model, provider, ceiling)
        result.append(book.authorize(cur, workspace_id, principal, revision, binding, quote['quoteId']))
    return tuple(result)


def manager_approval(phone, call_id):
    """Use the authenticated call's remaining limit for shared Manager reservations.

    No model can supply this authority. Settled spend and unknown holds both count;
    this does not approve a writer, research, media or publishing operation.
    """
    def approve(cur, workspace_id, principal, revision, cost, route, run_id):
        if ai_usage_exempt(principal):
            value = store.call(cur, call_id, lock=True)
            if not value or value['workspace_id'] != workspace_id or value['user_id'] != principal or value['state'] not in ('answered', 'live'):
                raise AlphaError('This phone session ended.', 409, code='phone_ended')
            return None, {'phoneCallId': call_id}
        book = phone.hosted.ledger.credits
        if not book or not book.policy(cur, workspace_id):
            return None, {'phoneCallId': call_id}
        value = store.call(cur, call_id, lock=True)
        if not value or value['workspace_id'] != workspace_id or value['user_id'] != principal or value['state'] not in ('answered', 'live'):
            raise AlphaError('This phone session ended.', 409, code='phone_ended')
        cur.execute("SELECT artifact->'voice' FROM public.pr_agent_runs WHERE id=%s", (value['voice_run_id'],))
        voice = cur.fetchone()[0]
        maximum = voice.get('creditLimitMilliCredits')
        cur.execute("SELECT r.meta->'credits', (SELECT s.meta->'credits' FROM public.pr_usage_ledger s "
                    "WHERE s.reservation_id=r.id AND s.cost_state IN ('actual','released') ORDER BY s.at DESC LIMIT 1) "
                    "FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' "
                    "AND (r.id=ANY(%s::uuid[]) OR r.meta->>'phoneCallId'=%s)",
                    (workspace_id, [value['live_reservation_id'], value['telephony_reservation_id']], call_id))
        committed = sum((settled['used'] if isinstance(settled, dict) else reserved['maximum'])
                        for reserved, settled in cur.fetchall() if isinstance(reserved, dict))
        ceiling = millicredits(cost)
        if not voice.get('useAvailableCredits') and (type(maximum) is not int or maximum - committed < ceiling):
            raise AlphaError('This request exceeds the credit limit approved for the call. Review the task in Rafii.', 402, code='phone_task_credit_limit')
        binding = digest({'operation': 'phone-agent-turn', 'callId': call_id, 'runId': run_id, 'cost': cost,
                          'model': route.model, 'provider': route.provider, 'revision': revision})
        quote = book.issue(cur, workspace_id, principal, revision, binding, route.model, route.provider, ceiling)
        return book.authorize(cur, workspace_id, principal, revision, binding, quote['quoteId']), {'phoneCallId': call_id}
    return approve


def lock_workspace(cur, call_id):
    cur.execute('SELECT w.id FROM public.pr_workspaces w JOIN public.pr_phone_calls c ON c.workspace_id=w.id '
                'WHERE c.id::text=%s FOR UPDATE OF w', (call_id,))


def settle(phone, cur, value, component, outcome, actual):
    """Allocate cumulative usage exactly once over immutable minute holds, including old calls."""
    initial = value['live_reservation_id' if component == 'live' else 'telephony_reservation_id']
    cur.execute("SELECT id::text,estimated_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve' "
                "AND (id::text=%s OR (meta->>'phoneCallId'=%s AND meta->>'phoneComponent'=%s)) ORDER BY at,id",
                (value['workspace_id'], initial, value['id'], component))
    rows = cur.fetchall()
    remaining = actual
    for index, (reservation, estimate) in enumerate(rows):
        cost = None if actual is None else (remaining if index == len(rows)-1 else min(remaining, estimate))
        phone.hosted.ledger.settle(cur, value['workspace_id'], reservation, outcome, cost)
        if actual is not None:
            remaining -= cost


def renew(phone, call_id):
    """Fund the next minute before crossing its boundary. Never a provider call.

    Workspace lock serializes wallet spending with Manager/other tasks. Call lock
    makes concurrent watchdog retries idempotent. Failed funding rolls back both
    component holds; the current funded minute remains usable.
    """
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        lock_workspace(cur, call_id)
        value = store.call(cur, call_id, lock=True)
        if not value or value['state'] not in ('answered','live') or value['media_resume_until']:
            raise AlphaError('This phone session ended.',409,code='phone_ended')
        funded = value['funded_seconds']
        if funded is None:  # A call admitted by an older deployment keeps its approved limit.
            return
        elapsed = max(0, phone.clock() - float(value['answered_at']))
        if elapsed >= funded:
            raise AlphaError('The funded phone time has ended.',402,code='phone_credit_balance')
        if elapsed < funded - 10 or funded >= value['max_seconds']:
            return
        target = min(funded + 60, value['max_seconds'])
        cur.execute('SELECT artifact->\'voice\' FROM public.pr_agent_runs WHERE id=%s', (value['voice_run_id'],))
        voice = cur.fetchone()[0]
        rates = voice['meterRates']
        offset = 45 if value['direction'] == 'inbound' else 0
        # Initial startup and reconnect reserve are covered by the +15s voice margin.
        costs = (rates[0] * (math.ceil((target+15)/60)-math.ceil((funded+15)/60)),
                 rates[1] * (math.ceil((target+offset)/60)-math.ceil((funded+offset)/60)))
        book = phone.hosted.ledger.credits
        credit = bool(book and book.policy(cur,value['workspace_id']))
        if ('creditLimitMilliCredits' in voice) and not credit:
            raise AlphaError('Credit billing is paused.',503)
        if value['kind'] != 'explicit':
            from . import planner
            prefs = store.prefs(cur, value['user_id'], value['workspace_id'])
            cur.execute(f'SELECT coalesce(sum({DAILY_COST_SQL}),0) FROM public.pr_phone_calls '
                        'WHERE user_id=%s AND requested_at>=to_timestamp(%s)',
                        (value['user_id'], planner.day_start(phone.clock(),prefs['timeZone'])))
            if int(cur.fetchone()[0])+sum(costs) > phone.config.daily_budget:
                raise AlphaError('The phone spending allowance is exhausted.',402,code='phone_budget')
        maximum = voice.get('creditLimitMilliCredits')
        if credit and not voice.get('useAvailableCredits'):
            cur.execute("SELECT r.meta->'credits', (SELECT s.meta->'credits' FROM public.pr_usage_ledger s "
                        "WHERE s.reservation_id=r.id AND s.cost_state IN ('actual','released') LIMIT 1) "
                        "FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' AND r.meta->>'phoneCallId'=%s",
                        (value['workspace_id'],call_id))
            committed = sum((s['used'] if isinstance(s,dict) else r['maximum']) for r,s in cur.fetchall() if isinstance(r,dict))
            maximum = maximum-committed if type(maximum) is int else 0
        cur.execute('SELECT revision FROM public.pr_workspaces WHERE id=%s',(value['workspace_id'],))
        revision = cur.fetchone()[0]
        auth = authorities(phone,cur,value['workspace_id'],value['user_id'],revision,maximum=maximum,
                           use_available=bool(voice.get('useAvailableCredits')), conversation_id=value['conversation_id'],
                           number_hash=value['number_hash'],kind=value['kind'],reason=value['reason_key'],costs=costs)
        route=phone.agent().cfg.route('voice_front_end',reason='phone continuation')
        for component,cost,authority,provider,model in zip(('live','telephony'),costs,auth,('openai',value['provider']),(route.model,'pstn')):
            phone.hosted.ledger.reserve(cur,value['workspace_id'],value['user_id'],'tool',cost,
                f'phone-{component}:{call_id}:{target}',charge_batch=False,provider=provider,model=model,
                run_id=value['voice_run_id'],credit_authority=authority,
                meta={'via':'rafii_phone','phoneCallId':call_id,'phoneComponent':component,'throughSeconds':target})
        cur.execute('UPDATE public.pr_phone_calls SET funded_seconds=%s,reserved_usd_micro=reserved_usd_micro+%s WHERE id=%s',
                    (target,sum(costs),call_id))
        db.commit()

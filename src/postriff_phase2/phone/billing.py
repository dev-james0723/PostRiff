"""Phone cost approval uses the existing credit quotes, reservations and settlement."""
import math

from postriff_alpha.domain import AlphaError
from ..contracts import digest
from ..credit_meter import millicredits
from . import store


# Keep the original ceiling for audit. Until BOTH components have confirmed usage,
# retain the whole hold; an ambiguous call must never free capacity for a redial.
# This also applies to existing rows, so no migration or ledger rewrite is needed.
DAILY_COST_SQL = """CASE WHEN live_cost_usd_micro IS NOT NULL AND telephony_cost_usd_micro IS NOT NULL
    THEN live_cost_usd_micro + telephony_cost_usd_micro
    ELSE greatest(reserved_usd_micro, coalesce(live_cost_usd_micro,0) + coalesce(telephony_cost_usd_micro,0)) END"""


def estimates(phone):
    return (
        phone.agent().cfg.live_usd_micro_per_minute * math.ceil((phone.config.cap_seconds + 15) / 60),
        phone.config.telephony_rate * math.ceil(phone.config.cap_seconds / 60),
    )


def spending(phone, cur, workspace_id):
    book = phone.hosted.ledger.credits
    active = bool(book and book.policy(cur, workspace_id))
    return {'usesCredits': active, 'ceilingMilliCredits': sum(millicredits(v) for v in estimates(phone)),
            'availableMilliCredits': book.view(cur, workspace_id)['availableMilliCredits'] if active else None}


def authorities(phone, cur, workspace_id, principal, revision, *, maximum, conversation_id, number_hash, kind, reason, costs):
    book = phone.hosted.ledger.credits
    if not book or not book.policy(cur, workspace_id):
        return None, None
    ceilings = [millicredits(cost) for cost in costs]
    if type(maximum) is not int or not sum(ceilings) <= maximum <= 100_000_000:
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
                          'costs': list(costs), 'model': model, 'provider': provider, 'approvedMaximum': maximum})
        quote = book.issue(cur, workspace_id, principal, revision, binding, model, provider, ceiling)
        result.append(book.authorize(cur, workspace_id, principal, revision, binding, quote['quoteId']))
    return tuple(result)


def manager_approval(phone, call_id):
    """Use the authenticated call's remaining limit for shared Manager reservations.

    No model can supply this authority. Settled spend and unknown holds both count;
    this does not approve a writer, research, media or publishing operation.
    """
    def approve(cur, workspace_id, principal, revision, cost, route, run_id):
        book = phone.hosted.ledger.credits
        if not book or not book.policy(cur, workspace_id):
            return None, {'phoneCallId': call_id}
        value = store.call(cur, call_id, lock=True)
        if not value or value['workspace_id'] != workspace_id or value['user_id'] != principal or value['state'] not in ('answered', 'live'):
            raise AlphaError('This phone session ended.', 409, code='phone_ended')
        cur.execute("SELECT artifact->'voice'->'creditLimitMilliCredits' FROM public.pr_agent_runs WHERE id=%s", (value['voice_run_id'],))
        maximum = cur.fetchone()[0]
        cur.execute("SELECT r.meta->'credits', (SELECT s.meta->'credits' FROM public.pr_usage_ledger s "
                    "WHERE s.reservation_id=r.id AND s.cost_state IN ('actual','released') ORDER BY s.at DESC LIMIT 1) "
                    "FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' "
                    "AND (r.id=ANY(%s::uuid[]) OR r.meta->>'phoneCallId'=%s)",
                    (workspace_id, [value['live_reservation_id'], value['telephony_reservation_id']], call_id))
        committed = sum((settled['used'] if isinstance(settled, dict) else reserved['maximum'])
                        for reserved, settled in cur.fetchall() if isinstance(reserved, dict))
        ceiling = millicredits(cost)
        if type(maximum) is not int or maximum - committed < ceiling:
            raise AlphaError('This request exceeds the credit limit approved for the call. Review the task in Rafii.', 402, code='phone_task_credit_limit')
        binding = digest({'operation': 'phone-agent-turn', 'callId': call_id, 'runId': run_id, 'cost': cost,
                          'model': route.model, 'provider': route.provider, 'revision': revision})
        quote = book.issue(cur, workspace_id, principal, revision, binding, route.model, route.provider, ceiling)
        return book.authorize(cur, workspace_id, principal, revision, binding, quote['quoteId']), {'phoneCallId': call_id}
    return approve

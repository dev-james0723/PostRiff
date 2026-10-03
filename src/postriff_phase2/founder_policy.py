"""Owner-approved defaults and durable, versioned internal spending policy.

Product entitlement is unlimited. This policy limits external spending only;
provider configuration, consent and per-action financial confirmation still apply.
"""
from copy import deepcopy
from datetime import datetime
import re
from zoneinfo import ZoneInfo
from postriff_alpha.domain import AlphaError

APPROVAL = 'founder-owner-20261002'
DEFAULTS = {
    'version': 1, 'revision': 1, 'approvalRef': APPROVAL,
    'dailySpendMode': 'limited', 'dailySpendUsdMicro': 50_000_000, 'warnPercent': 80,
    'timeZone': 'America/Indiana/Indianapolis', 'replyTo': 'jamesau0723@gmail.com',
    'emailCanaryCount': 3, 'pushCanaryCount': 3,
    'dailyBriefingTime': '08:30', 'weeklyReviewTime': '09:00', 'weeklyReviewDay': 0,
    'quietStart': 1320, 'quietEnd': 480,
    'maxCallSeconds': 600, 'automaticCallAttemptsDaily': 2, 'concurrentCalls': 1,
    'entitlement': 'unlimited', 'financialConfirmationRequired': True,
    'financialRetention': 'immutable', 'supportSource': 'in_app_tickets', 'customerPiiDefault': 'masked'
}
EDITABLE = set(DEFAULTS) - {'version', 'revision', 'approvalRef', 'entitlement',
                          'financialConfirmationRequired', 'financialRetention', 'supportSource', 'customerPiiDefault'}


def defaults():
    return deepcopy(DEFAULTS)


def validate(current, patch):
    if not isinstance(patch, dict) or set(patch) - EDITABLE:
        raise AlphaError('Invalid Founder settings.', 400)
    out = {**defaults(), **(current or {}), **patch}
    if out['dailySpendMode'] not in ('limited', 'unlimited'):
        raise AlphaError('Select Custom or Unlimited spending.', 400)
    for key, low, high in (('dailySpendUsdMicro', 1, 10_000_000_000), ('warnPercent', 1, 100),
                          ('emailCanaryCount', 0, 100), ('pushCanaryCount', 0, 100),
                          ('weeklyReviewDay', 0, 6), ('quietStart', 0, 1439), ('quietEnd', 0, 1439),
                          ('maxCallSeconds', 60, 3600), ('automaticCallAttemptsDaily', 0, 100), ('concurrentCalls', 1, 10)):
        if type(out[key]) is not int or not low <= out[key] <= high:
            raise AlphaError('Invalid Founder setting: ' + key, 400)
    for key in ('dailyBriefingTime', 'weeklyReviewTime'):
        if not isinstance(out[key], str) or not re.fullmatch(r'\d{2}:\d{2}', out[key]):
            raise AlphaError('Use a 24-hour briefing time.', 400)
        try:
            datetime.strptime(out[key], '%H:%M')
        except ValueError:
            raise AlphaError('Use a valid briefing time.', 400) from None
    try:
        if not isinstance(out['timeZone'], str) or len(out['timeZone']) > 64:
            raise ValueError
        ZoneInfo(out['timeZone'])
    except (ValueError, KeyError, TypeError):
        raise AlphaError('Use a valid IANA time zone.', 400) from None
    email = out['replyTo']
    if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
        raise AlphaError('Use a valid Reply-To address.', 400)
    # Preserve the owner's durable financial and entitlement decisions.
    for key in set(DEFAULTS) - EDITABLE - {'revision', 'approvalRef'}:
        out[key] = DEFAULTS[key]
    return out


def policy_from_marker(marker):
    policy = (marker or {}).get('policy')
    if not isinstance(policy, dict) or type(policy.get('revision')) is not int or policy['revision'] < 1 or not policy.get('approvalRef'):
        raise AlphaError('Founder spending policy has not been saved. No provider request was made.', 402)
    return validate(policy, {})


def spending(cur, workspace_id, policy):
    """Observed spend today plus every unresolved hold, including earlier days.
    The workspace lock in reserve serializes concurrent external actions.
    """
    cur.execute("WITH reservations AS (SELECT r.id,r.estimated_usd_micro FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve'), "
                "costs AS (SELECT r.*,t.actual_usd_micro,t.at FROM reservations r LEFT JOIN LATERAL "
                "(SELECT s.actual_usd_micro,s.at FROM public.pr_usage_ledger s WHERE s.workspace_id=%s AND s.reservation_id=r.id "
                "AND s.cost_state IN ('actual','released') ORDER BY s.at DESC,s.id DESC LIMIT 1) t ON true) "
                "SELECT coalesce(sum(actual_usd_micro) FILTER(WHERE at AT TIME ZONE %s >= date_trunc('day',now() AT TIME ZONE %s)),0), "
                "coalesce(sum(estimated_usd_micro) FILTER(WHERE actual_usd_micro IS NULL),0) FROM costs",
                (workspace_id, workspace_id, policy['timeZone'], policy['timeZone']))
    actual, held = cur.fetchone()
    cap = policy['dailySpendUsdMicro'] if policy['dailySpendMode'] == 'limited' else None
    used = int(actual) + int(held)
    return {'actualUsdMicro': int(actual), 'heldUsdMicro': int(held), 'usedUsdMicro': used,
            'capUsdMicro': cap, 'warnUsdMicro': cap * policy['warnPercent'] // 100 if cap is not None else None,
            'warning': cap is not None and used >= cap * policy['warnPercent'] // 100,
            'newPaidActionsStopped': cap is not None and used >= cap, 'timeZone': policy['timeZone']}

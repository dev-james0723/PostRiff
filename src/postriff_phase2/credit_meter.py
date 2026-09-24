"""Versioned, non-billable credit proposal. Does not replace Ledger or create a wallet.

One USD of verified provider cost maps to 300 credits. Display resolution is 0.1
credit, rounded once per task. Existing plan terms and balances remain unchanged.
"""
POLICY_VERSION = 'credits-candidate-2026-09-23-v1'
MICRO_USD = 1_000_000
CREDITS_PER_USD = 300
MILLI_STEP = 100


def _amount(value):
    if type(value) is not int or value < 0 or value > 10**15:
        raise ValueError('Use a bounded, nonnegative integer USD-micro amount.')
    return value


def millicredits(cost_usd_micro):
    numerator = _amount(cost_usd_micro) * CREDITS_PER_USD * 1000
    denominator = MICRO_USD * MILLI_STEP
    return ((numerator + denominator - 1) // denominator) * MILLI_STEP


def quote_task(component_costs_usd_micro, *, route='managed'):
    if route not in ('managed', 'byok', 'cli'):
        raise ValueError('Choose a known billing route.')
    if not isinstance(component_costs_usd_micro, (list, tuple)) or len(component_costs_usd_micro) > 100:
        raise ValueError('Supply at most 100 bounded cost components.')
    total = _amount(sum(_amount(value) for value in component_costs_usd_micro))
    return {'policyVersion': POLICY_VERSION, 'status': 'proposed', 'billable': False,
            'route': route, 'providerCostUsdMicro': total,
            'reservedMilliCredits': millicredits(total) if route == 'managed' else 0}


def settle_preview(quote, actual_cost_usd_micro, outcome):
    if outcome not in ('completed', 'failed', 'unknown'):
        raise ValueError('Use an explicit known outcome.')
    if not isinstance(quote, dict) or quote.get('policyVersion') != POLICY_VERSION or quote.get('billable') is not False:
        raise ValueError('Only this non-billable policy preview is supported.')
    expected = quote_task([quote['providerCostUsdMicro']], route=quote['route'])
    if quote != expected:
        raise ValueError('The quote was modified; calculate it again.')
    reserved = expected['reservedMilliCredits']
    cost = None if actual_cost_usd_micro is None else _amount(actual_cost_usd_micro)
    result = {'policyVersion': POLICY_VERSION, 'billable': False, 'status': 'proposed',
              'providerCostUsdMicro': cost, 'usedMilliCredits': None,
              'heldMilliCredits': reserved, 'releasedMilliCredits': 0,
              'absorbedMilliCredits': 0, 'usageState': 'pending'}
    if outcome == 'unknown' or (outcome == 'completed' and cost is None):
        return result
    calculated = millicredits(cost or 0) if quote['route'] == 'managed' and outcome == 'completed' else 0
    used = min(reserved, calculated)
    result.update(usedMilliCredits=used, heldMilliCredits=0,
                  releasedMilliCredits=reserved-used,
                  absorbedMilliCredits=max(0, calculated-reserved),
                  usageState='released' if outcome == 'failed' else 'settled')
    return result

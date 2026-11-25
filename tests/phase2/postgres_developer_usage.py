"""Local synthetic DB only: account quota exemption, isolation, revocation and accounting."""
from local_pg_target import selected_target
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger, USD
from postriff_phase2.credit_meter import POLICY_VERSION

DEV = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'
os.environ['RAFII_AI_UNLIMITED_USER_IDS'] = DEV
os.environ['POSTRIFF_BUDGET_POLICY'] = 'paid-2026-09-24'
ledger = Ledger(credits_enabled=True)


def denied(call, text):
    try:
        call()
    except AlphaError as error:
        assert text in str(error), str(error)
        return
    raise AssertionError('Expected denial: ' + text)


with psycopg.connect(selected_target().dsn()) as db:
    db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/020_credit_quotes.sql').read_text())
    cur = db.cursor()
    cur.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (DEV,))
    wid = str(cur.fetchone()[0])
    ledger.ensure_entitlement(cur, wid, None)
    cur.execute('UPDATE public.pr_entitlements SET writing_batches_remaining=0,media_credits_remaining=0 WHERE workspace_id=%s', (wid,))
    for scope in ('workspace:' + wid, 'global', 'global-month'):
        ledger._budget(cur, scope, policy=__import__('postriff_phase2.billing', fromlist=['active_budget_policy']).active_budget_policy())
    cur.execute('UPDATE public.pr_budgets SET spent_usd_micro=stop_usd_micro+1,reserved_usd_micro=123')
    cur.execute('SELECT scope,spent_usd_micro,reserved_usd_micro FROM public.pr_budgets ORDER BY scope')
    before = cur.fetchall()
    # Paid policy: above per-request, per-person and every shared stop line, with zero allowances.
    for dimension, outcome in (('text_model', 'completed'), ('image_generation', 'failed'), ('tool', 'unknown')):
        result = ledger.reserve(cur, wid, DEV, dimension, 20 * USD, 'developer-' + dimension, charge_batch=True,
                                meta={'aiUsageExempt': False, 'budgetScopes': ['forged']})
        cur.execute('SELECT meta,charge_batch FROM public.pr_usage_ledger WHERE id::text=%s', (result['reservationId'],))
        meta, charge = cur.fetchone()
        assert meta['aiUsageExempt'] is True and meta['budgetScopes'] == [] and not charge
        assert ledger.reserve(cur, wid, DEV, dimension, 20 * USD, 'developer-' + dimension, charge_batch=True)['duplicate']
        ledger.settle(cur, wid, result['reservationId'], outcome, 12 * USD if outcome != 'unknown' else None)
        if outcome == 'unknown':
            # Original reservation scopes remain authoritative after exemption is revoked.
            os.environ['RAFII_AI_UNLIMITED_USER_IDS'] = ''
            ledger.settle(cur, wid, result['reservationId'], 'completed', 13 * USD)
            os.environ['RAFII_AI_UNLIMITED_USER_IDS'] = DEV
        assert ledger.settle(cur, wid, result['reservationId'], 'completed', 99 * USD)['duplicate']
    cur.execute('SELECT scope,spent_usd_micro,reserved_usd_micro FROM public.pr_budgets ORDER BY scope')
    assert cur.fetchall() == before, 'Developer costs must not leak into shared budgets at reserve/settlement'
    assert ledger._person_day(cur, DEV) >= 37 * USD, 'Actual developer costs still recorded'
    ent = ledger.ensure_entitlement(cur, wid, None)
    assert ent['writingBatchesRemaining'] == ent['mediaCreditsRemaining'] == 0
    denied(lambda: ledger.reserve(cur, wid, OTHER, 'text_model', 20 * USD, 'other-big', charge_batch=False), 'limit for one request')
    denied(lambda: ledger.reserve(cur, wid, OTHER, 'text_model', 1, 'other-allowance', charge_batch=True), 'No writing allowance')
    denied(lambda: ledger.reserve(cur, wid, OTHER, 'image_generation', 1, 'other-media', charge_batch=False), 'No media credits')
    denied(lambda: ledger.reserve(cur, wid, OTHER, 'text_model', 1, 'other-budget', charge_batch=False,
                                  meta={'aiUsageExempt': True}), 'AI spending limit')
    os.environ['RAFII_AI_UNLIMITED_USER_IDS'] = ''
    denied(lambda: ledger.reserve(cur, wid, DEV, 'text_model', 1, 'revoked', charge_batch=False), 'one person over 24 hours')
    os.environ['RAFII_AI_UNLIMITED_USER_IDS'] = DEV
    os.environ['POSTRIFF_AI_PAUSED'] = '1'
    denied(lambda: ledger.reserve(cur, wid, DEV, 'text_model', 1, 'paused', charge_batch=False), 'paused by the operator')
    os.environ.pop('POSTRIFF_AI_PAUSED')
    os.environ['POSTRIFF_BUDGET_POLICY'] = 'invalid'
    denied(lambda: ledger.reserve(cur, wid, DEV, 'text_model', 1, 'invalid-policy', charge_batch=False), 'names no known policy')
    os.environ['POSTRIFF_BUDGET_POLICY'] = 'paid-2026-09-24'
    # Credit plans: no fake grant/quote and no deduction; normal actors still need authority.
    terms = {'writingBatches': 0, 'mediaCredits': 0, 'connectedAccounts': 3, 'members': 3,
             'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    cur.execute("INSERT INTO public.pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('developer-test','studio',999,'Test',0,'active',%s::jsonb)", (json.dumps(terms),))
    cur.execute("UPDATE public.pr_entitlements SET plan_terms_id='developer-test' WHERE workspace_id=%s", (wid,))
    result = ledger.reserve(cur, wid, DEV, 'text_model', 20 * USD, 'credit-developer', charge_batch=True)
    cur.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND meta ? 'credits'", (wid,))
    assert cur.fetchone()[0] == 0, 'No invented credit grants or deductions'
    denied(lambda: ledger.reserve(cur, wid, OTHER, 'text_model', 1, 'credit-other', charge_batch=True), 'Confirm this task credit limit')
    assert ledger.usage_view(cur, wid, DEV)['credits'] is None
    assert ledger.usage_view(cur, wid, DEV)['aiUsageExempt'] is True
    db.rollback()

print(json.dumps({'status': 'pass', 'execution': 'disposable-local-postgres', 'providerCalls': 0,
                  'checks': ['request/person/shared budgets', 'empty allowances', 'immutable cost accounting',
                             'settlement after revocation', 'idempotency', 'nondeveloper isolation',
                             'forged metadata denied', 'pause and policy guards', 'credit quota exemption']}))

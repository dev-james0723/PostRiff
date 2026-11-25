"""Opt-in local-synthetic Pricing v2 fixture around the REAL hosted services.

No migration runner, PG binary, socket, process, HTTP client, credential discovery,
model/Stripe default transport, or production API registration lives here. Import
has no side effects. The parent supplies an already migrated isolated database on
its own PG 55439 and wraps its real HostedApplication with this controller.
Customer API responses are always produced by the existing application.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
from urllib.parse import urlparse
from uuid import uuid4

BASE_SHA = '3eb25c96e6978388efe6bfac154e9300a28a0ae5'
EXECUTION = 'local-synthetic-real-http-pg'
MODEL = 'google/gemini-2.5-flash-lite'
JEV_MODEL = 'typesafe-ai/jev'
PROVIDER = 'vercel-ai-gateway'
ENDPOINT = 'https://ai-gateway.vercel.sh/v1/chat/completions'
EVALUATE_ENDPOINT = 'https://ai-gateway.vercel.sh/v1/evaluate'
CONTROL_PREFIX = '/dev/pricing-v2-local-synthetic/'
POLICY = 'credits-v2-2026-09-28'
SCENARIOS = ('free-new', 'creator-49', 'creator-59', 'creator-79', 'creator-held',
             'creator-pending', 'creator-settled', 'creator-over-max', 'creator-failed',
             'legacy-19', 'legacy-39', 'trial-active', 'trial-expired', 'creator-ended-free')
_workspace = ContextVar('pricing_v2_local_synthetic_workspace', default=None)


def check_database(cur, expected_database):
    if (not isinstance(expected_database, str) or
            not re.fullmatch(r'pricing_v2_local_synthetic_[a-z0-9_]{1,32}', expected_database)):
        raise ValueError('Parent must name an isolated pricing_v2_local_synthetic_* database.')
    cur.execute('SELECT current_database(),host(inet_server_addr()),current_setting(\'port\')::int')
    if cur.fetchone() != (expected_database, '127.0.0.1', 55439):
        raise ValueError('Only the named parent-owned loopback PG 55439 database is allowed.')


def variant(price):
    if type(price) is not int or price not in (49, 59, 79): raise ValueError('Server variant allowlist only.')
    return {'terms': 'creator-v1', 'id': f'creator-{price}-v1', 'amountCents': price * 100,
            'monthlyCredits': 3500, 'priceId': f'price_local_synthetic_creator_{price}'}


def validate_catalog(cur):
    cur.execute("SELECT id,status,new_checkout_enabled,entitlements FROM public.pr_plan_terms WHERE id IN ('creator-v1','starter-v1','studio-v2') ORDER BY id")
    rows = cur.fetchall()
    if (len(rows) != 3 or [r[0] for r in rows] != ['creator-v1','starter-v1','studio-v2']
            or any(r[1] not in ('proposed','active') or bool(r[2]) != (r[0] in ('starter-v1','studio-v2')) for r in rows)
            or rows[0][3].get('monthlyCredits') != 3500 or rows[0][3].get('creditPolicy') != POLICY):
        raise ValueError('Existing inactive v2 catalog and exact Creator entitlement required.')
    cur.execute("SELECT id,plan_terms_id,amount_cents,status FROM public.pr_plan_price_variants ORDER BY amount_cents,id")
    if cur.fetchall() != [(f'creator-{price}-v1','creator-v1',price*100,'proposed') for price in (49,59,79)]:
        raise ValueError('Exact three seeded, proposed Creator price variants required.')
    cur.execute('SELECT count(*) FROM public.pr_credit_packs WHERE active')
    if cur.fetchone()[0]: raise ValueError('Active packs including legacy dev-pack are forbidden in the v2 fixture.')


def prepare_catalog(cur):
    # Enables existing subscribers' credit policy, NEVER new sale. No invented plan.
    cur.execute("UPDATE public.pr_plan_terms SET status='active',new_checkout_enabled=false WHERE id=%s", ('creator-v1',))
    for price in (49, 59, 79):
        v = variant(price)
        cur.execute("UPDATE public.pr_plan_price_variants SET provider_price_id=%s WHERE id=%s AND plan_terms_id='creator-v1' AND amount_cents=%s",
                    (v['priceId'], v['id'], v['amountCents']))
    for terms in ('starter-v1', 'studio-v2'):
        cur.execute('UPDATE public.pr_plan_terms SET provider_price_id=%s WHERE id=%s', ('price_local_synthetic_fixed_' + terms, terms))
    # Creator variants, packs and legacy plan status retain their original restrictions.
    # Historical signed webhook reconciliation does not require new-sale activation.


def parse_seed(body):
    if not isinstance(body, dict) or set(body) != {'scenario'} or body['scenario'] not in SCENARIOS:
        raise ValueError('Choose one named local-synthetic scenario; client prices are forbidden.')
    return body


def runtime_contract(now):
    return {'model': MODEL, 'provider': PROVIDER, 'executionProvider': 'google',
            'prices': (0.1, 0.4), 'expiresAt': int(now) + 3600,
            'evidence': 'local-synthetic-pinned-table-not-live-price-qualification'}


def preview_policy(paid_base_checks=False):
    return {'approved': True, 'id': 'local-synthetic-pricing-v2-preview', 'model': MODEL,
            'provider': PROVIDER, 'executionProvider': 'google', 'attemptMaxUsdMicro': 20000,
            'dailyUsdMicro': 2000000, 'monthlyUsdMicro': 4000000, 'dailyRuns': 100,
            'workspaceDailyRuns': 3, 'maxInputBytes': 64000, 'maxOutputTokens': 1500,
            'paidBaseChecks': paid_base_checks}


def rewrite_policy(now):
    # Same existing qualification schema; 13 worst-case physical attempts are
    # included by RewritePolicy.plan, including Jev retry and allowed fallback.
    routes = []
    for kind, model, serving in [('chat', MODEL, 'google'), ('evaluate', JEV_MODEL, 'typesafe-ai')]:
        routes.append({'kind': kind, 'model': model, 'provider': PROVIDER,
                       'endpoint': ENDPOINT if kind == 'chat' else EVALUATE_ENDPOINT,
                       'executionProviders': [serving], 'ceilingUsdMicro': 20000,
                       'maxInputBytes': 100000, 'maxOutputTokens': 4500 if kind == 'chat' else None,
                       'priceBasis': {'version': 'configured', 'inputUsdPerMTok': 0.1,
                                      'outputUsdPerMTok': 0.4} if kind == 'chat' else None})
    return {'approved': True, 'id': 'local-synthetic-pricing-v2-rewrite',
            'qualification': 'operator-approved-ceiling',
            'evidenceRef': 'local-synthetic-pinned-table-no-live-provider-qualification',
            'expiresAt': int(now) + 3600, 'routes': routes}


def sign_event(event, secret, timestamp):
    raw = json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    stamp = int(timestamp)
    return raw, f't={stamp},v1=' + hmac.new(secret.encode(), f'{stamp}.'.encode() + raw, hashlib.sha256).hexdigest()


def invoice_event(wid, price, start, end, *, terms=None):
    v = variant(price) if terms is None else {'terms': terms, 'id': None,
         'priceId': 'price_local_synthetic_' + terms, 'amountCents': price * 100}
    subscription = 'sub_local_synthetic_' + wid
    meta = {'workspace_id': wid, 'plan_terms_id': v['terms']}
    if v['id']: meta['price_variant_id'] = v['id']
    invoice = {'id': 'in_local_synthetic_' + wid, 'customer': 'cus_local_synthetic_' + wid,
               'subscription': subscription, 'status': 'paid', 'paid': True,
               'amount_paid': v['amountCents'], 'currency': 'usd', 'billing_reason': 'subscription_create',
               'payment_intent': 'pi_local_synthetic_' + wid,
               'subscription_details': {'metadata': meta}, 'lines': {'data': [
                   {'type': 'subscription', 'subscription': subscription, 'price': {'id': v['priceId']},
                    'period': {'start': int(start), 'end': int(end)}, 'amount': v['amountCents']}]}}
    return {'id': 'evt_local_synthetic_' + wid, 'type': 'invoice.paid', 'created': int(start),
            'livemode': False, 'data': {'object': invoice}}


def require_committed_hold(cur, wid, next_cost):
    # A separate connection must see an OPEN, committed hold. An unknown terminal
    # does not free the hold, but must not authorize another physical attempt.
    if type(next_cost) is not int or not 1 <= next_cost <= 10**15:
        raise ValueError('Positive finite physical-attempt ceiling required.')
    cur.execute("SELECT r.estimated_usd_micro,r.model,r.provider,r.meta FROM public.pr_usage_ledger r "
                "WHERE r.workspace_id=%s AND r.kind='reserve' AND NOT EXISTS "
                "(SELECT 1 FROM public.pr_usage_ledger s WHERE s.workspace_id=r.workspace_id "
                "AND s.reservation_id=r.id AND (s.cost_state IN ('actual','released') OR s.cost_state='estimated_unknown')) LIMIT 2", (wid,))
    rows = cur.fetchall()
    if len(rows) != 1: raise ValueError('Exactly one committed synthetic hold must precede physical IO.')
    ceiling, model, provider, meta = rows[0]
    if (type(ceiling) is not int or ceiling < next_cost or model != MODEL or provider != PROVIDER):
        raise ValueError('Current route or finite reservation ceiling is unqualified.')
    if 'credits' in meta:
        maximum = meta['credits'].get('maximum')
        required = math.ceil(next_cost * 300 / 1000000) * 1000
        if type(maximum) is not int or maximum < required: raise ValueError('MAX does not cover this attempt.')
    elif 'platformPreview' not in meta:
        raise ValueError('No customer MAX or independent platform-preview authority.')
    return {'committedSeenViaSeparateConnection':True,'reservedUsdMicro':ceiling,
            'authorityKind':'credits' if 'credits' in meta else 'platformPreview',
            'maximumMilliCredits':meta.get('credits',{}).get('maximum')}


def _answers(questions):
    answers = {}
    for name, question in questions.items():
        if question['type'] == 'boolean':
            answers[name] = {'type': 'boolean', 'probability': 0.01 if name.startswith('risk_') else 0.95}
        elif question['type'] == 'choice':
            options = question.get('choices', question.get('criteria', question.get('options', [])))
            names = [o['name'] if isinstance(o, dict) else o for o in options]
            choice = next(o for o in names if o != 'unsure')
            answers[name] = {'type': 'choice', 'choice': choice,
                             'probabilities': {o: float(o == choice) for o in names}}
        else: raise ValueError('Unsupported synthetic rubric question.')
    return answers


def refuse_legacy_growth_router(_sink, _writer=None):
    """No supported legacy Growth physical route in this v2 fixture.

    Real Growth's router factory is reached before its default Jev constructor.
    Managed RewriteFunding and approved platform-preview routers use their own
    real, guarded bridges to our synthetic transport and do not use this factory.
    Keep the legacy catalog/flags truthful; refuse execution before selecting a
    default evaluator, writer fallback, retry, or unscoped/public router.
    """
    from postriff_alpha.domain import AlphaError
    raise AlphaError('Legacy Growth AI is unsupported in this local-synthetic fixture.', 503,
                     code='local_synthetic_legacy_ai_unavailable')


class SyntheticStripeTransport:
    """Counts attempts, returns no checkout URL, and has NO network implementation."""
    def __init__(self): self.attempts, self.external_io = 0, 0
    def __call__(self, method, url, headers=None, form=None, body=None):
        self.attempts += 1
        allowed = {'price_local_synthetic_fixed_starter-v1', 'price_local_synthetic_fixed_studio-v2'}
        if method == 'POST' and url.endswith('/v1/checkout/sessions') and form and form.get('line_items[0][price]') in allowed:
            return {'status': 200, 'body': {'id': 'cs_local_synthetic_fixed_' + str(self.attempts), 'url': 'https://checkout.stripe.com/c/local_synthetic_fixed'}}
        raise RuntimeError('Only the two approved fixed-price synthetic checkout transports are allowed; no external IO.')


class SyntheticGatewayTransport:
    def __init__(self, committed_hold, *, clock=time.time, expires_at):
        self.committed_hold, self.clock, self.expires_at = committed_hold, clock, expires_at
        self.calls, self.external_io = [], 0
        self.mode = ContextVar('local_synthetic_outcome', default='completed')

    @contextmanager
    def outcome(self, mode):
        if mode not in ('completed', 'failed', 'unknown', 'over-max'): raise ValueError('Unknown synthetic outcome.')
        marker = self.mode.set(mode)
        try: yield
        finally: self.mode.reset(marker)

    def __call__(self, method, url, headers=None, body=None, **kwargs):
        if self.clock() >= self.expires_at: raise ValueError('Local-synthetic qualification expired.')
        model = body.get('model') if isinstance(body, dict) else None
        serving = 'google' if model == MODEL else 'typesafe-ai' if model == JEV_MODEL else None
        expected = ENDPOINT if model == MODEL else EVALUATE_ENDPOINT
        if (method != 'POST' or url != expected or not serving or 'models' in body or
                body.get('providerOptions', {}).get('gateway', {}).get('only') != [serving]):
            raise ValueError('Exact qualified local-synthetic model/provider/endpoint required.')
        if (len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode()) > 100000 or
                url == ENDPOINT and (type(body.get('max_tokens')) is not int or not 1 <= body['max_tokens'] <= 4500)):
            raise ValueError('Finite synthetic input/output qualification exceeded.')
        # Existing writer/Growth guard runs first. This additional receipt verifies
        # that a separate real connection observes the committed reservation.
        proof = self.committed_hold(10000)
        if not isinstance(proof,dict) or proof.get('committedSeenViaSeparateConnection') is not True:
            raise ValueError('Missing independent committed-hold receipt; no synthetic dispatch.')
        data = body if 'messages' not in body else json.loads(body['messages'][-1]['content'].split('\n\n')[0])
        if 'questions' in data:
            content = {'answers': _answers(data['questions'])}
        elif 'original' in data:
            content = {'changes': [{'index': 0, 'text': 'A clearer local-synthetic opening.',
                                   'dimension': 'hook', 'usesFacts': []}], 'missingFacts': [],
                       'notes': 'local-synthetic rewrite, no provider quality claim.'}
        elif 'destinations' in data:
            content = {'variants': [{'platform': d['platform'], 'language': d['languageId'],
                       **({'channelId': d['channelId']} if d.get('channelId') else {}),
                       'text': 'A local-synthetic draft for this bounded browser check.', 'sourceIds': [],
                       'warnings': ['local-synthetic; no live model quality evidence.']}
                      for d in data['destinations']]}
        else: raise ValueError('No synthetic response for an unplanned model operation.')
        mode = self.mode.get(); cost = None if mode == 'unknown' else 0 if mode == 'failed' else .03 if mode == 'over-max' else .01
        self.calls.append({'execution': 'local-synthetic', 'model': model, 'endpointKind': 'chat' if url == ENDPOINT else 'evaluate',
                           'physicalAttempt': len(self.calls) + 1, 'costUsd': cost, 'executionProvider': serving,
                           'committedHold':proof})
        response = {'id': 'local-synthetic-' + str(len(self.calls)), 'model': model,
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'inputTokens': 10, 'outputTokens': 20},
                    'providerMetadata': {'gateway': {'cost': cost, 'generationId': 'local-synthetic-' + str(len(self.calls)),
                                                    'routing': {'finalProvider': serving}}}}
        response.update(content if url == EVALUATE_ENDPOINT else {'choices': [{'message': {'content': json.dumps(content)}}]})
        return {'status': 500 if mode == 'unknown' else 400 if mode == 'failed' else 200, 'body': response}


def require_control(environ, token, origin):
    if (environ.get('REMOTE_ADDR') != '127.0.0.1' or environ.get('REQUEST_METHOD') != 'POST'
            or environ.get('HTTP_ORIGIN') != origin or not isinstance(token, str) or len(token) < 32
            or not hmac.compare_digest(environ.get('HTTP_X_PRICING_V2_FIXTURE', ''), token)):
        raise ValueError('Authenticated loopback synthetic control required.')


class PricingV2Fixture:
    def __init__(self, service, connection, *, enabled, expected_database, origin, token=None):
        parsed = urlparse(origin)
        if (enabled is not True or parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Explicit loopback local-synthetic fixture opt-in required.')
        if os.environ.get('VERCEL') or os.environ.get('POSTRIFF_BUDGET_POLICY'):
            raise ValueError('Deployed host or ambient automatic budget approval is forbidden.')
        # Construct v2 at the host's boundary. Replacing service.ledger later would
        # strand Ideas/Billing/Coworker references to a different credit engine.
        if not service.billing.pricing_v2_enabled or service.ledger.credits is None:
            raise ValueError('Parent must construct HostedWorkspaceService with pricing_v2_enabled and credits_enabled.')
        if service.billing.ledger is not service.ledger or service.ideas.ledger is not service.ledger:
            raise ValueError('One real Ledger must be shared by the existing services.')
        if service.credit_purchases_enabled:
            raise ValueError('Credit packs must stay disabled.')
        if service.email_lookup is not None: raise ValueError('Use no email lookup for this isolated fixture.')
        with connection() as db, db.cursor() as cur:
            check_database(cur, expected_database)
            validate_catalog(cur)
        self.service, self.connection, self.database, self.origin = service, connection, expected_database, origin.rstrip('/')
        self.token = token or secrets.token_urlsafe(32)
        self.secret = 'local-synthetic-hmac-' + secrets.token_hex(16)
        self.lock, self.seeds = threading.Lock(), {}
        contract = runtime_contract(service.clock())
        self.contract = contract
        self.gateway = SyntheticGatewayTransport(self._committed, clock=service.clock, expires_at=contract['expiresAt'])
        self.stripe_transport = SyntheticStripeTransport()
        # Imports are lazy so the bounded unit suite never loads a model or DB.
        from postriff_phase2.model_runtime import ServerModelRuntime
        from postriff_phase2.billing_stripe import StripePaymentProvider
        from postriff_phase2.growth.service import GrowthService
        self.runtime = ServerModelRuntime('local-synthetic-no-provider-key', model=MODEL, models=[MODEL],
            prices={MODEL: contract['prices']}, allowed_providers={MODEL: ['google']},
            transport=self.gateway, clock=service.clock)
        # Verify current qualification rather than overriding any qualified flag.
        model = next(m for m in self.runtime.list_supported_models() if m['id'] == MODEL)
        if not model['qualified'] or not model['priced'] or self.runtime.price_basis(MODEL) != {
                'version': 'configured', 'inputUsdPerMTok': .1, 'outputUsdPerMTok': .4}:
            raise ValueError('Current model qualification or pinned price contract changed.')
        service.ideas.runtime, service.ideas.runtimes = self.runtime, [self.runtime]
        service.ideas._discover_cli = False
        service.billing.provider = StripePaymentProvider('sk_test_local_synthetic_only', self.secret,
                                                         transport=self.stripe_transport, clock=service.clock)
        # Null email/address resolution prevents auth/billing notices from egress.
        self.growth = service.growth = GrowthService(service, router_factory=refuse_legacy_growth_router, env={
            'POSTRIFF_GROWTH': '1', 'POSTRIFF_POST_DOCTOR': '1', 'POSTRIFF_GENOME': '1',
            'POSTRIFF_POST_DOCTOR_V2': '1', 'POSTRIFF_JEV': '1',
            'AI_GATEWAY_API_KEY': 'local-synthetic-never-external',
            'POSTRIFF_GROWTH_DAILY_USD_CAP': '2', 'POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP': '1'})
        with self.connection() as db, db.cursor() as cur:
            check_database(cur, self.database)
            prepare_catalog(cur)
        self.policy_state = 'off'

    @contextmanager
    def scoped(self, wid):
        marker = _workspace.set(wid)
        try: yield
        finally: _workspace.reset(marker)

    def _committed(self, cost):
        wid = _workspace.get()
        if not wid or wid not in {s['workspaceId'] for s in self.seeds.values()}:
            raise ValueError('Physical synthetic IO outside a fixture-owned workspace is forbidden.')
        with self.connection() as db, db.cursor() as cur:
            check_database(cur, self.database)
            return require_committed_hold(cur, wid, cost)

    def _webhook(self, event):
        raw, signature = sign_event(event, self.secret, self.service.clock())
        # This is the service's real Stripe signature + catalog + grant pipeline.
        # The real HTTP webhook path is separately exercised by the browser.
        result = self.service.billing_webhook(signature, raw)
        if result.get('outcome') not in ('applied', 'duplicate', 'stale'):
            raise ValueError('Synthetic signed event was not reconciled: ' + str(result))
        return result

    def _budgets(self, wid):
        # Explicit finite local-only platform approvals, never broad approve-all.
        with self.connection() as db, db.cursor() as cur:
            check_database(cur, self.database)
            for scope, kind, stop in [('global', 'day', 2000000), ('workspace:' + wid, 'month', 1000000)]:
                cur.execute("INSERT INTO public.pr_budgets(scope,window_kind,window_start,warn_usd_micro,stop_usd_micro,status) "
                            "VALUES(%s,%s,date_trunc(%s,now()),%s,%s,'approved') ON CONFLICT(scope) DO NOTHING",
                            (scope, kind, kind, stop, stop))

    def set_policy(self, mode):
        if mode not in ('off', 'free-preview', 'paid-base', 'qualified', 'unavailable'):
            raise ValueError('Unknown local-synthetic funding state.')
        if self.service.clock() >= self.contract['expiresAt']: raise ValueError('Fixture qualification expired.')
        env = self.growth.env
        env.pop('POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY', None)
        env.pop('POSTRIFF_GROWTH_PLATFORM_PREVIEW', None)
        if mode != 'off': env['POSTRIFF_GROWTH_PLATFORM_PREVIEW'] = json.dumps(preview_policy(mode in ('paid-base','qualified','unavailable')))
        if mode in ('qualified', 'unavailable'):
            p = rewrite_policy(self.service.clock())
            if mode == 'unavailable': p['expiresAt'] = int(self.service.clock()) - 1
            env['POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY'] = json.dumps(p)
        self.policy_state = mode

    def seed(self, scenario):
        parse_seed({'scenario': scenario})
        if scenario in self.seeds:
            if self.seeds[scenario]['state'] != 'ready':
                raise ValueError('Previous synthetic bootstrap is incomplete; inspect evidence before retrying.')
            return self.seeds[scenario]
        actor, member = str(uuid4()), str(uuid4())
        token = 'dev:' + actor
        with self.connection() as db, db.cursor() as cur:
            check_database(cur, self.database)
            cur.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)', (actor, member))
            if scenario.startswith('legacy-') or scenario.startswith('trial-'):
                cur.execute('SELECT public.pr_bootstrap(%s,%s)', (actor, 'assist' if scenario == 'legacy-39' else 'studio'))
        result = self.service.bootstrap(token)
        wid = result['workspaceId']
        row = {'scenario': scenario, 'principal': actor, 'memberPrincipal': member,
               'workspaceId': wid, 'execution': EXECUTION, 'stripeTestMode': 'NOT_RUN', 'state': 'preparing'}
        self.seeds[scenario] = row  # Own the workspace before any physical synthetic attempt.
        with self.connection() as db, db.cursor() as cur:
            cur.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s)', (member,))
            cur.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (wid, member))
        if scenario.startswith('creator-'):
            price = int(scenario.split('-')[1]) if scenario in ('creator-49','creator-59','creator-79') else 59
            now = int(self.service.clock()); event = invoice_event(wid, price, now - 30, now + 30 * 86400)
            self._webhook(event); self._webhook(event)
            redelivery = copy.deepcopy(event); redelivery['id'] += '_redelivery'; self._webhook(redelivery)
            row.update(priceVariantId=variant(price)['id'], monthlyCredits=3500,
                       invoiceId=event['data']['object']['id'], expectedGrantCount=1)
            self._budgets(wid)
            if scenario == 'creator-ended-free':
                ended = {'id': 'evt_local_synthetic_ended_' + wid, 'type': 'customer.subscription.deleted',
                         'livemode': False, 'created': now + 1, 'data': {'object': {
                         'id': 'sub_local_synthetic_' + wid, 'customer': 'cus_local_synthetic_' + wid,
                         'status': 'canceled', 'current_period_end': now - 1,
                         'metadata': {'workspace_id': wid, 'plan_terms_id': 'creator-v1', 'price_variant_id': variant(price)['id']},
                         'items': {'data': [{'price': {'id': variant(price)['priceId']}}]}}}}
                self._webhook(ended)
            elif scenario in ('creator-held', 'creator-pending', 'creator-settled', 'creator-over-max', 'creator-failed'):
                row['reservationId'] = self._credit_state(wid, actor, scenario)
        elif scenario.startswith('legacy-'):
            price = 19 if scenario == 'legacy-19' else 39
            terms = 'studio-v1' if price == 19 else 'assist-v1'
            with self.connection() as db, db.cursor() as cur:
                cur.execute('UPDATE public.pr_plan_terms SET provider_price_id=%s WHERE id=%s', ('price_local_synthetic_' + terms, terms))
            self._webhook(invoice_event(wid, price, int(self.service.clock()) - 30, int(self.service.clock()) + 30 * 86400, terms=terms))
        elif scenario == 'trial-expired':
            with self.connection() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_trials SET expires_at=now()-interval '1 second' WHERE workspace_id=%s", (wid,))
        # Consent is explicit fixture state, never a fake customer response.
        saved = self.service.get(wid, token)
        self.growth.action(wid, token, saved['revision'], 'growth_consent', {
            'confirmed': True, 'routes': ['cloud:' + PROVIDER + ':' + MODEL, 'cloud:' + PROVIDER + ':' + JEV_MODEL]})
        row['expectedMode'] = 'legacy_allowances' if scenario in ('legacy-19','legacy-39','trial-active') else 'free_preview' if scenario in ('free-new','trial-expired','creator-ended-free') else 'managed_credits'
        row['state'] = 'ready'
        return row

    def _credit_state(self, wid, actor, scenario):
        from postriff_phase2.credit_task_guard import guard_credit_call
        from postriff_phase2.credit_meter import millicredits
        from postriff_phase2.contracts import digest
        from postriff_phase2.model_runtime import ProviderFailure
        token = 'dev:' + actor
        payload = {'text': 'Write a short Threads draft from this local-synthetic idea.',
                   'confirmUse': True, 'ownContent': True, 'research': False, 'model': MODEL,
                   'reasoning': 'quick', 'language': 'en', 'destinations': [{'platform':'Threads','language':'en'}]}
        saved = self.service.get(wid, token)
        runtime, model, request = self.service.ideas.estimate_request(saved['state'], payload, 'quick-start', actor)
        maximum_micro = max(20000, math.ceil(runtime.price_quote(request, model) * 1000000))
        binding = digest({'localSyntheticLedgerScene': scenario, 'request': payload})
        book = self.service.ledger.credits
        with self.connection() as db, db.cursor() as cur:
            q = book.issue(cur, wid, actor, saved['revision'], binding, model, PROVIDER, millicredits(maximum_micro))
            authority = book.authorize(cur, wid, actor, saved['revision'], binding, q['quoteId'])
            held = self.service.ledger.reserve(cur, wid, actor, 'text_model', maximum_micro,
                   'local-synthetic:' + scenario, charge_batch=False, provider=PROVIDER, model=model, credit_authority=authority)
        rid = held['reservationId']  # Commit finishes BEFORE actual synthetic writer.
        if scenario == 'creator-held': return rid
        request['_creditGuard'] = lambda **v: guard_credit_call(self.service.ledger, self.connection, wid, rid, **v)
        mode = {'creator-pending':'unknown','creator-failed':'failed','creator-over-max':'over-max'}.get(scenario,'completed')
        outcome, cost = 'completed', None
        with self.scoped(wid), self.gateway.outcome(mode):
            try:
                physical = runtime.start_turn(request, lambda _e: None)
                cost = math.ceil(physical['usage']['costUsd'] * 1000000)
            except ProviderFailure as error:
                outcome = 'unknown' if error.cost_usd is None else 'failed'
                cost = None if error.cost_usd is None else math.ceil(error.cost_usd * 1000000)
        with self.connection() as db, db.cursor() as cur:
            self.service.ledger.settle(cur, wid, rid, outcome, cost)
        return rid

    def snapshot(self):
        result = {'execution': EXECUTION, 'stripeTestMode': 'NOT_RUN', 'policyState': self.policy_state,
                  'syntheticModelAttempts': list(self.gateway.calls), 'syntheticStripeTransportAttempts': self.stripe_transport.attempts,
                  'externalIO': self.gateway.external_io + self.stripe_transport.external_io, 'scenes': []}
        with self.connection() as db, db.cursor() as cur:
            check_database(cur, self.database)
            for row in self.seeds.values():
                wid = row['workspaceId']; shown = dict(row)
                cur.execute('SELECT count(*),coalesce(sum(millicredits),0)::bigint FROM public.pr_credit_subscription_grants WHERE workspace_id=%s AND grant_id IS NOT NULL', (wid,))
                shown['periodGrants'] = list(cur.fetchone())
                shown['wallet'] = self.service.ledger._credit_book.view(cur, wid)
                cur.execute("SELECT kind,cost_state,actual_usd_micro,meta->'credits' FROM public.pr_usage_ledger WHERE workspace_id=%s ORDER BY at,id", (wid,))
                shown['ledger'] = [list(r) for r in cur.fetchall()]
                result['scenes'].append(shown)
        return result

    def wrap(self, application):
        """Parent installs outside /api only. No production endpoint is changed."""
        def wrapped(environ, start_response):
            path = environ.get('PATH_INFO', '')
            if path.startswith(CONTROL_PREFIX):
                try:
                    require_control(environ, self.token, self.origin)
                    length = int(environ.get('CONTENT_LENGTH') or 0)
                    if not 0 <= length <= 4096: raise ValueError('Synthetic control payload too large.')
                    body = json.loads(environ['wsgi.input'].read(length) or b'{}')
                    with self.lock:
                        if path == CONTROL_PREFIX + 'bootstrap': result = self.seed(parse_seed(body)['scenario'])
                        elif path == CONTROL_PREFIX + 'policy' and isinstance(body,dict) and set(body)=={'mode'}:
                            self.set_policy(body['mode']); result = {'mode': self.policy_state}
                        elif path == CONTROL_PREFIX + 'snapshot' and body == {}: result = self.snapshot()
                        elif path == CONTROL_PREFIX + 'webhook-replay' and isinstance(body,dict) and set(body)=={'scenario'}:
                            row = self.seeds[body['scenario']]
                            if 'priceVariantId' not in row: raise ValueError('Creator scene required.')
                            price = int(row['priceVariantId'].split('-')[1])
                            with self.connection() as db, db.cursor() as cur:
                                cur.execute('SELECT period_start,period_end FROM public.pr_credit_subscription_grants WHERE workspace_id=%s AND invoice_id=%s', (row['workspaceId'],row['invoiceId']))
                                period = cur.fetchone()
                            event = invoice_event(row['workspaceId'],price,*period); event['id'] += '_http_redelivery'
                            raw, signature = sign_event(event,self.secret,self.service.clock())
                            result = {'body': raw.decode(), 'signature': signature}
                        else: raise ValueError('Unknown synthetic control action.')
                    raw = json.dumps(result, allow_nan=False).encode()
                    start_response('200 OK', [('Content-Type','application/json'),('Cache-Control','no-store'),('Content-Length',str(len(raw)))])
                    return [raw]
                except (ValueError, KeyError, TypeError) as error:
                    raw = json.dumps({'error':str(error),'execution':'local-synthetic'}).encode()
                    start_response('403 Forbidden', [('Content-Type','application/json'),('Cache-Control','no-store'),('Content-Length',str(len(raw)))])
                    return [raw]
            parts = path.split('/')
            wid = parts[3] if len(parts)>3 and parts[1:3]==['api','workspaces'] else None
            with self.scoped(wid): return application(environ, start_response)
        return wrapped


def configure(service, connection, **options):
    return PricingV2Fixture(service, connection, **options)

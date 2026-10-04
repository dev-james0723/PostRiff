"""Server-only, expiring qualification for the existing Post Doctor rewrite pipeline.

An operator ceiling is a spending bound, not a claim of live price verification.
No declaration exists by default. Jev stays the primary evaluation model.
"""
from __future__ import annotations

import copy
import json
import math
from collections import Counter
from dataclasses import dataclass

from postriff_alpha.domain import AlphaError
from ..contracts import digest
from ..model_runtime import DEFAULT_ENDPOINT, ServerModelRuntime, thinking, output_cap
from .jev import DEFAULT_MODEL, EVALUATE_ENDPOINT
from .router import TASKS

OPERATION = 'post-doctor-rewrite'
ENV_KEY = 'POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY'
REQUEST_KEYS = frozenset({'checkId', 'model', 'facts', 'confirmed', 'requestKey'})


def unavailable():
    return AlphaError('This Growth route needs a qualified credit bridge before AI use.', 503,
                      code='growth_credit_bridge_unavailable')


def request(payload):
    if not isinstance(payload, dict) or set(payload) - (REQUEST_KEYS | {'creditQuoteId', 'expectedRevision'}):
        raise AlphaError('Supply the exact Post Doctor rewrite request.', 400)
    if (not isinstance(payload.get('checkId'), str) or not 1 <= len(payload['checkId']) <= 100
            or payload.get('confirmed') is not True or not isinstance(payload.get('requestKey'), str)
            or not 16 <= len(payload['requestKey']) <= 100
            or payload.get('model') is not None and (not isinstance(payload['model'], str) or not 1 <= len(payload['model']) <= 160)):
        raise AlphaError('Confirm the current Post Doctor rewrite request.', 400)
    facts = payload.get('facts', {})
    if (not isinstance(facts, dict) or len(facts) > 10 or any(not isinstance(k, str) or not 1 <= len(k) <= 40
            or not isinstance(v, str) or not 1 <= len(v) <= 1000 for k, v in facts.items())):
        raise AlphaError('Supply up to ten of your own facts or examples.', 400)
    return {k: copy.deepcopy(v) for k, v in payload.items() if k in REQUEST_KEYS}


@dataclass(frozen=True)
class RewritePlan:
    policy: object
    tasks: dict
    routes: dict
    limits: dict
    writer: str
    maximum_micro: int
    max_attempts: int
    fingerprint: str

    def record(self):
        return {'operation': OPERATION, 'fingerprint': self.fingerprint, 'maximumUsdMicro': self.maximum_micro,
                'maxAttempts': self.max_attempts, 'writer': self.writer}


@dataclass(frozen=True)
class RewritePolicy:
    value: dict

    @classmethod
    def from_env(cls, env, now):
        raw = env.get(ENV_KEY)
        if not raw: return None
        try:
            p = json.loads(raw)
            if (not isinstance(p, dict) or set(p) != {'approved', 'id', 'qualification', 'evidenceRef', 'expiresAt', 'routes'}
                    or p['approved'] is not True or p['qualification'] != 'operator-approved-ceiling'
                    or not isinstance(p['id'], str) or not 1 <= len(p['id']) <= 100
                    or not isinstance(p['evidenceRef'], str) or not 1 <= len(p['evidenceRef']) <= 300
                    or type(p['expiresAt']) is not int or not now < p['expiresAt'] <= now + 31*86400
                    or not isinstance(p['routes'], list) or not 1 <= len(p['routes']) <= 16):
                raise ValueError()
            seen = set()
            for r in p['routes']:
                if (not isinstance(r, dict) or set(r) != {'kind', 'model', 'provider', 'endpoint', 'executionProviders',
                            'ceilingUsdMicro', 'maxInputBytes', 'maxOutputTokens', 'priceBasis'}
                        or r['kind'] not in ('chat', 'evaluate') or r['provider'] != 'vercel-ai-gateway'
                        or not isinstance(r['model'], str) or not 1 <= len(r['model']) <= 160
                        or r['endpoint'] != (DEFAULT_ENDPOINT if r['kind'] == 'chat' else EVALUATE_ENDPOINT)
                        or not isinstance(r['executionProviders'], list) or len(r['executionProviders']) != 1
                        or not isinstance(r['executionProviders'][0], str) or not 1 <= len(r['executionProviders'][0]) <= 100
                        or type(r['ceilingUsdMicro']) is not int or not 1 <= r['ceilingUsdMicro'] <= 1_000_000
                        or type(r['maxInputBytes']) is not int or not 1000 <= r['maxInputBytes'] <= 256_000):
                    raise ValueError()
                if r['kind'] == 'evaluate':
                    if r['model'] != DEFAULT_MODEL or r['maxOutputTokens'] is not None or r['priceBasis'] is not None:
                        raise ValueError()
                elif (type(r['maxOutputTokens']) is not int or not 1 <= r['maxOutputTokens'] <= 8000
                        or not isinstance(r['priceBasis'], dict)):
                    raise ValueError()
                if r['kind'] == 'chat':
                    basis=r['priceBasis']
                    if (set(basis)!={'version','inputUsdPerMTok','outputUsdPerMTok'}
                            or not isinstance(basis['version'],str) or not 1<=len(basis['version'])<=100
                            or any(type(basis[k]) not in (int,float) or not math.isfinite(basis[k]) or basis[k]<0
                                   for k in ('inputUsdPerMTok','outputUsdPerMTok'))):
                        raise ValueError()
                key = (r['kind'], r['model'])
                if key in seen: raise ValueError()
                seen.add(key)
            return cls(p)
        except (ValueError, TypeError, KeyError):
            raise unavailable() from None

    def plan(self, runtime, writer, version, state, env):
        # Preserve the actual installed Jev primary; an absent key/route/flag cannot qualify a replacement.
        if (not isinstance(runtime, ServerModelRuntime) or runtime.cost_class != 'paid'
                or runtime.provider != 'vercel-ai-gateway' or runtime.endpoint != DEFAULT_ENDPOINT
                or writer not in runtime.models or version not in (1, 2)
                or env.get('POSTRIFF_JEV') != '1' or not env.get('AI_GATEWAY_API_KEY')
                or env.get('POSTRIFF_JEV_MODEL', DEFAULT_MODEL) != DEFAULT_MODEL
                or env.get('AI_GATEWAY_EVALUATE_ENDPOINT', EVALUATE_ENDPOINT) != EVALUATE_ENDPOINT):
            raise unavailable()
        consent = state.get('growthConsent', {}).get('routes', [])
        writer_cap=max(4000,output_cap(writer)) if thinking(writer) else 4000
        tasks = {'postdoctor.rewrite': ('chat', writer, (), 45.0, writer_cap)}
        evaluation = ['postdoctor.grounding', 'postdoctor.judge'] + (['postdoctor.compare'] if version == 2 else [])
        for task in evaluation:
            kind, primary, fallbacks, seconds, tokens = TASKS[task]
            if kind != 'evaluate' or primary != DEFAULT_MODEL or seconds <= 0: raise unavailable()
            selected=tuple(m for m in fallbacks if 'cloud:vercel-ai-gateway:'+m in consent)
            # chat_from_runtime's existing reasoning headroom is part of the actual
            # pipeline, including evaluation fallbacks. Quote it; never shrink it to qualify.
            cap=max([tokens,*[output_cap(m) for m in selected if thinking(m)]])
            tasks[task] = (kind, primary, selected, seconds, cap)
        qualified = {(r['kind'], r['model']): copy.deepcopy(r) for r in self.value['routes']}
        limits = Counter(); actual = {}; prices = {}
        for task, (kind, primary, fallbacks, _, tokens) in tasks.items():
            invocations = 2 if task == 'postdoctor.compare' else 1
            for model, count, call_kind in [(primary, 2 if kind == 'evaluate' else 1, kind),
                                           *((m, 1, 'chat') for m in fallbacks)]:
                r = qualified.get((call_kind, model))
                if not r or 'cloud:vercel-ai-gateway:'+model not in consent: raise unavailable()
                if call_kind == 'chat':
                    if (model not in runtime.models or runtime.allowed_for(model) != r['executionProviders']
                            or tokens > r['maxOutputTokens']): raise unavailable()
                    runtime._price(model)
                    basis = runtime.price_basis(model)
                    # Byte count is a conservative token upper bound; do not round USD
                    # down through the ordinary writer's six-decimal usual-cost helper.
                    cost_micro = r['maxInputBytes']*basis['inputUsdPerMTok'] + r['maxOutputTokens']*basis['outputUsdPerMTok']
                    if (basis != r['priceBasis'] or not math.isfinite(cost_micro) or cost_micro < 0
                            or math.ceil(cost_micro) > r['ceilingUsdMicro']): raise unavailable()
                    prices[model] = basis
                actual[(call_kind, model)] = r
                limits[(task, model)] += count * invocations
        maximum = sum(actual[('evaluate' if m == DEFAULT_MODEL else 'chat', m)]['ceilingUsdMicro'] * n
                      for (_, m), n in limits.items())
        fingerprint = digest([self.value, tasks, prices, version])
        return RewritePlan(self, tasks, actual, dict(limits), writer, maximum, sum(limits.values()), fingerprint)

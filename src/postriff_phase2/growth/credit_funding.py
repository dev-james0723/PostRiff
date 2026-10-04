"""Funding the real Growth router, with one event for each physical transport attempt.

Database guards finish before transport. The runtime's local router metadata is
not a second invoice; only this sink is persisted for managed rewrites.
"""
from __future__ import annotations

import copy
import json
import time
from collections import Counter

from postriff_alpha.domain import AlphaError
from ..model_runtime import gateway_routing, _gateway_metadata
from .credit_policy import unavailable
from .jev import JevService, DEFAULT_MODEL, EVALUATE_ENDPOINT
from .router import AIModelRouter, RouterError, chat_from_runtime
from .usage import UsageEvent, task_cost_usd_micro


def credit_guard():
    # This reusable guard is parent-owned. Missing integration must never become a no-op.
    try:
        from ..credit_task_guard import guard_credit_call
    except ImportError:
        raise unavailable() from None
    return guard_credit_call


class RewriteFunding:
    def __init__(self, plan, sink, guard, *, now=time.time):
        self.plan, self.sink, self.guard, self.now = plan, sink, guard, now
        self.current = None
        self.blocked = False

    def costs(self):
        return task_cost_usd_micro(self.sink.events)

    def invoke(self, task, model, route, fn, args, kwargs, ids):
        self.current = (task, model, route, ids.get('workspace_id'), ids.get('subject'))
        start_count = len(self.sink.events)
        try:
            return fn(*args, **kwargs)
        except Exception as error:
            # Jev/legacy runtime exceptions can otherwise discard a billed failed envelope.
            if len(self.sink.events) > start_count:
                e = self.sink.events[-1]
                error.usage = {'gatewayCost': e.cost_usd, 'executionProvider': e.provider,
                               'prompt_tokens': e.input_tokens, 'completion_tokens': e.output_tokens}
            raise
        finally:
            self.current = None

    def transport(self, underlying, kind):
        def send(method, url, headers=None, body=None, **kwargs):
            if self.current is None: raise RouterError('Missing rewrite attempt binding', 'growth_credit_bridge_unavailable')
            task, model, route, workspace, subject = self.current
            r = self.plan.routes.get((kind, model))
            data = copy.deepcopy(body)
            if kind == 'evaluate' and isinstance(data, dict):
                gateway = data.setdefault('providerOptions', {}).setdefault('gateway', {})
                gateway['only'] = list(r['executionProviders']) if r else []
            used = Counter((e.task, e.model) for e in self.sink.events)
            spent, unknown = self.costs()
            try:
                if (not r or self.blocked or unknown or self.now() >= self.plan.policy.value['expiresAt']
                        or used[(task, model)] >= self.plan.limits.get((task, model), 0)
                        or spent + r['ceilingUsdMicro'] > self.plan.maximum_micro
                        or method != 'POST' or url != r['endpoint'] or not isinstance(data, dict)
                        or data.get('model') != model or 'models' in data
                        or data.get('providerOptions', {}).get('gateway', {}).get('only') != r['executionProviders']
                        or len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > r['maxInputBytes']
                        or kind == 'chat' and (type(data.get('max_tokens')) is not int
                                               or not 1 <= data['max_tokens'] <= r['maxOutputTokens'])):
                    raise unavailable()
                self.guard(task, model, route, r['ceilingUsdMicro'])
            except (AlphaError, ValueError, TypeError) as error:
                # The guard rejected before any physical I/O; no unknown attempt is invented.
                raise RouterError('The rewrite approval changed; review the current maximum.',
                                  getattr(error, 'code', None) or 'growth_credit_bridge_unavailable') from error
            started = time.monotonic(); response = None; failed = False
            try:
                response = underlying(method, url, headers=headers, body=data, **kwargs)
            except Exception:
                failed = True
                raise
            finally:
                envelope = response.get('body') if isinstance(response, dict) else None
                provider, cost = gateway_routing(envelope)
                usage = envelope.get('usage', {}) if isinstance(envelope, dict) else {}
                usage = usage if isinstance(usage, dict) else {}
                meta = _gateway_metadata(envelope)
                generation = meta.get('generationId')
                event = UsageEvent(task, model, route,
                    'upstream' if failed or not isinstance(response, dict) or response.get('status') != 200 else 'ok',
                    max(0, round((time.monotonic()-started)*1000)), stage='rewrite-credit', provider=provider,
                    generation_id=generation[:200] if isinstance(generation, str) else None,
                    input_tokens=usage.get('prompt_tokens', usage.get('inputTokens')),
                    output_tokens=usage.get('completion_tokens', usage.get('outputTokens')),
                    cost_usd=cost, cost_source='gateway' if cost is not None else 'unknown',
                    workspace_id=workspace, subject=subject)
                self.sink.record(event)
                if (event.cost_usd_micro() is None or event.cost_usd_micro() > r['ceilingUsdMicro']
                        or provider not in r['executionProviders']
                        or isinstance(envelope, dict) and envelope.get('model', model) != model):
                    self.blocked = True
            if provider not in r['executionProviders'] or isinstance(envelope, dict) and envelope.get('model', model) != model:
                error = AlphaError('The Growth execution provider/model could not be verified.',502,code='execution_provider_unverified')
                error.usage = {'gatewayCost':cost,'executionProvider':provider}
                raise error
            return response
        return send

    def router(self, runtime, env):
        copied = copy.copy(runtime)
        copied.transport = self.transport(runtime.transport, 'chat')
        adapter = chat_from_runtime(copied, preserve_output_cap=True)
        jev = JevService(env['AI_GATEWAY_API_KEY'], endpoint=EVALUATE_ENDPOINT, model=DEFAULT_MODEL,
                         transport=self.transport(runtime.transport, 'evaluate'))
        router = AIModelRouter(jev=jev, chat=adapter, usage=None, tasks=self.plan.tasks)
        router.funding_call = self.invoke
        return router

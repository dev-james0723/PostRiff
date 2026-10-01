"""Server-only, default-OFF funding for bounded Growth first value. No wallet or grant.

The operator supplies an approved policy; generic Growth/billing caps cannot approve it.
Only the existing Gemini rubric route is supported, with a pinned execution provider.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math

from postriff_alpha.domain import AlphaError
from ..contracts import digest

MODEL = 'google/gemini-2.5-flash-lite'
ROUTE = 'cloud:vercel-ai-gateway:' + MODEL
SCOPES = ('platform-preview:day', 'platform-preview:month')


def unavailable():
    return AlphaError('Platform preview funding is not available.', 503, code='growth_platform_funding_unavailable')


@dataclass(frozen=True)
class PreviewPolicy:
    id: str
    attemptMaxUsdMicro: int
    dailyUsdMicro: int
    monthlyUsdMicro: int
    dailyRuns: int
    workspaceDailyRuns: int
    maxInputBytes: int
    maxOutputTokens: int
    paidBaseChecks: bool = False
    model: str = MODEL
    provider: str = 'vercel-ai-gateway'
    executionProvider: str = 'google'

    @classmethod
    def from_env(cls, env):
        raw = env.get('POSTRIFF_GROWTH_PLATFORM_PREVIEW')
        if not raw: return None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or value.pop('approved', None) is not True: raise ValueError()
            policy = cls(**value)
            bounds = {'attemptMaxUsdMicro': 1000000, 'dailyUsdMicro': 100000000,
                      'monthlyUsdMicro': 1000000000, 'dailyRuns': 10000, 'workspaceDailyRuns': 10,
                      'maxInputBytes': 128000, 'maxOutputTokens': 1500}
            if any(type(getattr(policy, key)) is not int or not 1 <= getattr(policy, key) <= maximum for key, maximum in bounds.items()): raise ValueError()
            if (not isinstance(policy.id, str) or not 1 <= len(policy.id) <= 80
                    or policy.model != MODEL or policy.provider != 'vercel-ai-gateway' or policy.executionProvider != 'google'
                    or type(policy.paidBaseChecks) is not bool
                    or policy.attemptMaxUsdMicro > policy.dailyUsdMicro or policy.dailyUsdMicro > policy.monthlyUsdMicro): raise ValueError()
            return policy
        except (ValueError, TypeError):
            raise unavailable() from None

    @property
    def fingerprint(self): return digest(asdict(self))

    def binding(self, runtime):
        from ..model_runtime import DEFAULT_ENDPOINT, ServerModelRuntime
        if (not isinstance(runtime, ServerModelRuntime) or runtime.endpoint != DEFAULT_ENDPOINT
                or runtime.allowed_for(self.model) != [self.executionProvider]): raise unavailable()
        runtime._price(self.model)
        cost=runtime._cost(self.model,self.maxInputBytes+256,self.maxOutputTokens)
        if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0 or math.ceil(cost*1000000)>self.attemptMaxUsdMicro:
            raise unavailable()
        return {'policy': self.fingerprint, 'model': self.model, 'provider': self.provider,
                'executionProvider': self.executionProvider, 'endpoint': runtime.endpoint,
                'priceBasis': runtime.price_basis(self.model)}

    def bound_call(self, runtime, binding, model, tokens, prompt_bytes):
        if (binding != self.binding(runtime) or model != self.model or type(tokens) is not int
                or not 1 <= tokens <= self.maxOutputTokens or prompt_bytes > self.maxInputBytes): raise unavailable()
        # UTF-8 bytes conservatively bound input tokens; include message framing headroom.
        cost = runtime._cost(model, prompt_bytes + 256, tokens)
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0 or math.ceil(cost * 1000000) > self.attemptMaxUsdMicro:
            raise unavailable()


@dataclass(frozen=True)
class PreviewAuthority:
    """Never accepted from JSON/meta. Bound to an existing server-created, running run."""
    policy: PreviewPolicy
    run_id: str
    kind: str
    maximum_micro: int
    max_attempts: int
    binding: dict

    def record(self):
        return {'runId': self.run_id, 'kind': self.kind, 'maximumMicro': self.maximum_micro,
                'maxAttempts': self.max_attempts, 'binding': self.binding}

    def validate(self, cur, workspace_id, dimension, amount, provider, model, run_id, charge_batch):
        if (dimension != 'tool' or charge_batch or amount != self.maximum_micro or amount <= 0
                or provider != self.policy.provider or model != self.policy.model or run_id != self.run_id
                or self.kind not in ('check', 'genome') or not 1 <= self.max_attempts <= (1 if self.kind == 'check' else 40)
                or amount != self.policy.attemptMaxUsdMicro * self.max_attempts): raise unavailable()
        cur.execute('SELECT kind,status,body FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND id=%s', (workspace_id, self.run_id))
        row = cur.fetchone()
        if not row or row[:2] != (self.kind, 'running') or row[2].get('_preview') != self.record(): raise unavailable()


def recent_samples(state, permitted):
    """Select from the actual retained/granted corpus, never a declared quantity or order."""
    def timestamp(source):
        try:
            published = datetime.fromisoformat(str(source.get('publishedAt', '')).replace('Z', '+00:00'))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            return published.timestamp()
        except (ValueError, TypeError, OverflowError):
            value = source.get('createdAt', 0)
            return float(value) if type(value) in (int, float) and math.isfinite(value) else 0
    return [s['id'] for s in sorted((s for s in state.get('sources', []) if s.get('id') in permitted
            and s.get('kind') == 'voice_sample' and s.get('active') and s.get('selected')),
            key=lambda s: (timestamp(s), str(s['id'])), reverse=True)[:20]]

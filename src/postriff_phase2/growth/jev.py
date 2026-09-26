"""Server-side client for Jev through Vercel AI Gateway's Evaluation API (growth Phase 0).

POST https://ai-gateway.vercel.sh/v1/evaluate with {model, state, questions}; the response carries
`answers`, `usage` and `providerMetadata.gateway` (cost, generationId, routing). This client sends exactly one
request per call and never retries: callers (AIModelRouter) own retry and fallback policy. The API key is used
only in the Authorization header and never appears in exceptions, reprs or logs. Answer contents are validated
by JudgmentService, not here.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from postriff_alpha.domain import AlphaError

from ..model_runtime import gateway_routing, model_transport
from .questions import estimate_tokens

EVALUATE_ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
DEFAULT_MODEL = "typesafe-ai/jev"
STATE_AND_QUESTION_LIMIT = 32_000   # tokens: state plus the longest single question (Gateway catalog)
REQUEST_LIMIT = 64_000              # tokens per request


class JevError(Exception):
    code = "error"

    def __init__(self, message, *, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class JevAuthError(JevError):
    code = "auth"


class JevBudgetExceeded(JevError):
    code = "budget"


class JevBadRequest(JevError):
    code = "bad_request"


class JevRateLimited(JevError):
    code = "rate_limited"


class JevUpstream(JevError):
    code = "upstream"


class JevTimeout(JevError):
    code = "timeout"


class JevMalformed(JevError):
    code = "malformed"


@dataclass(frozen=True)
class RawEvaluation:
    model: str
    answers: dict
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    cost_source: str
    generation_id: str | None
    final_provider: str | None
    latency_ms: int


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class JevService:
    def __init__(self, api_key, *, endpoint=None, model=None, transport=None, clock=time.monotonic, zero_data_retention=True):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("JevService needs a server-side AI Gateway key")
        self._api_key = api_key
        self.endpoint = endpoint or os.environ.get("AI_GATEWAY_EVALUATE_ENDPOINT") or EVALUATE_ENDPOINT
        if not self.endpoint.startswith("https://"):
            raise ValueError("The evaluation endpoint must use HTTPS")
        self.model = model or os.environ.get("POSTRIFF_JEV_MODEL") or DEFAULT_MODEL
        self.transport = transport or model_transport
        self.clock = clock
        self.zero_data_retention = zero_data_retention

    def __repr__(self):
        return f"JevService(endpoint={self.endpoint!r}, model={self.model!r})"

    def body(self, state, questions):
        body = {"model": self.model, "state": state, "questions": questions}
        if self.zero_data_retention:
            body["providerOptions"] = {"gateway": {"zeroDataRetention": True}}
        return body

    def check_size(self, state, questions):
        """Refuse before sending when the Gateway limits would be exceeded (estimate, conservative)."""
        if not isinstance(questions, dict) or not questions:
            raise JevBadRequest("At least one question is required")
        state_tokens = estimate_tokens(state)
        longest = max(estimate_tokens(q) for q in questions.values())
        if state_tokens + longest > STATE_AND_QUESTION_LIMIT or state_tokens + estimate_tokens(questions) > REQUEST_LIMIT:
            raise JevBadRequest("The evaluation state is too large; trim the excerpt or split the questions")

    def evaluate(self, state, questions, *, timeout_s):
        self.check_size(state, questions)
        started = self.clock()
        try:
            response = self.transport("POST", self.endpoint, headers={"Authorization": f"Bearer {self._api_key}"},
                                      body=self.body(state, questions), timeout=timeout_s)
        except AlphaError as error:
            raise JevUpstream("Couldn't reach the evaluation model") from error
        except TimeoutError as error:
            raise JevTimeout("The evaluation model did not answer in time") from error
        latency_ms = max(0, round((self.clock() - started) * 1000))
        status = response.get("status") if isinstance(response, dict) else None
        data = response.get("body") if isinstance(response, dict) else None
        if status in (401, 403):
            raise JevAuthError("The AI Gateway rejected the evaluation credentials", status=status)
        if status == 402:
            raise JevBudgetExceeded("The AI Gateway budget for evaluations is exhausted", status=status)
        if status == 429:
            retry = None
            if isinstance(data, dict):
                value = data.get("retry_after") or data.get("retryAfter")
                retry = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None
            raise JevRateLimited("The evaluation model is rate limiting", status=status, retry_after=retry)
        if status in (400, 404, 413, 422):
            raise JevBadRequest("The evaluation request was rejected", status=status)
        if status is None or status >= 500:
            raise JevUpstream("The evaluation model failed", status=status)
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise JevMalformed("The evaluation response had an unexpected shape", status=status)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        provider, cost = gateway_routing(data)
        meta = (data.get("providerMetadata") or {}).get("gateway") if isinstance(data.get("providerMetadata"), dict) else None
        generation = meta.get("generationId") if isinstance(meta, dict) and isinstance(meta.get("generationId"), str) else None
        return RawEvaluation(
            model=data.get("model") if isinstance(data.get("model"), str) else self.model,
            answers=data["answers"],
            input_tokens=_count(usage.get("inputTokens")),
            output_tokens=_count(usage.get("outputTokens")),
            cost_usd=cost,
            cost_source="gateway" if cost is not None else "unknown",
            generation_id=generation,
            final_provider=provider,
            latency_ms=latency_ms,
        )

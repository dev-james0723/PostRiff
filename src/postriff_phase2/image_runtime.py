"""Provider-independent image generation for Ideas chat.

The selected writing model (managed model, Claude CLI, Codex CLI, or fixture)
never owns this capability. Image requests use one qualified, server-side media
route so the same chat affordance behaves consistently for every writer.
"""
import base64
import json
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from postriff_alpha.domain import AlphaError, clean

from . import ai_call_events
from .model_runtime import gateway_generation, gateway_routing, provider_map, _gateway_metadata
from .growth.usage import cost_usd_micro


DEFAULT_ENDPOINT = "https://ai-gateway.vercel.sh/v1/images/generations"
DEFAULT_MODEL = "openai/gpt-image-2.5-flare"
DEFAULT_ESTIMATE_USD_MICRO = 100_000
MAX_RESPONSE_BYTES = 9 * 1024 * 1024
TIMEOUT_SECONDS = 120


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise ImageGenerationError("The image provider redirected the request; no image was accepted.", uncertain=True)


class ImageGenerationError(AlphaError):
    """A provider failure with an explicit spend-reconciliation state."""

    def __init__(self, message, status=502, *, uncertain=False, cost_usd=None):
        super().__init__(message, status)
        self.uncertain = uncertain
        self.cost_usd = cost_usd


def image_transport(method, url, headers=None, body=None, timeout=TIMEOUT_SECONDS):
    if url != DEFAULT_ENDPOINT:
        raise ImageGenerationError("Image generation must use the qualified gateway endpoint.", 503, cost_usd=0.0)
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except HTTPError as error:
        raw, status = error.read(65536), error.code
    except (URLError, TimeoutError, OSError) as error:
        raise ImageGenerationError(
            "The image request outcome is unknown. Usage must be reconciled before retrying.",
            uncertain=True,
        ) from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ImageGenerationError("The image response exceeded the safe size limit.", uncertain=True)
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError as error:
        # A successful dispatch with unreadable bytes has no verified cost. Keep
        # the existing zero-cost refusal classification only for HTTP 4xx.
        refused = 400 <= status < 500
        raise ImageGenerationError("The image provider returned an unreadable response.",
                                   uncertain=not refused, cost_usd=0.0 if refused else None) from error
    return {"status": status, "body": parsed}


class GatewayImageRuntime:
    """One image candidate through AI Gateway, independent from the writing route."""

    provider = "vercel-ai-gateway"
    cost_class = "paid"
    ESTIMATE_BASIS = "approved_image_ceiling"

    def __init__(self, api_key, model=DEFAULT_MODEL, *, transport=None, estimate_usd_micro=DEFAULT_ESTIMATE_USD_MICRO, allowed_providers=None, credit_policy=None, clock=time.time):
        if not isinstance(api_key, str) or not api_key:
            raise AlphaError("An image gateway key is required.", 503)
        if not isinstance(model, str) or "/" not in model or len(model) > 160:
            raise AlphaError("Image generation isn't available yet.", 503)
        if type(estimate_usd_micro) is not int or not 1 <= estimate_usd_micro <= 1_000_000:
            raise AlphaError("Configure a bounded image-generation cost estimate.", 503)
        self.api_key = api_key
        self.model = model
        self.transport = transport or image_transport
        self.estimate_usd_micro = estimate_usd_micro
        # Execution providers the gateway may route this model to (and fall back between); default: its maker.
        self.allowed_providers = [str(p) for p in allowed_providers] if allowed_providers else [model.split("/", 1)[0]]
        self.credit_policy = dict(credit_policy) if isinstance(credit_policy, dict) else None
        self.clock = clock

    def credit_basis(self):
        """A scoped operator-approved ceiling, separate from the guessed legacy estimate.

        A key or feature flag does not qualify a price. Activation requires an explicit,
        short-lived server cost record; synthetic records are test evidence only.
        """
        p = self.credit_policy
        required = {'model', 'provider', 'count', 'size', 'ceilingUsdMicro',
                    'expiresAt', 'qualification', 'evidenceRef', 'executionProviders'}
        if not isinstance(p, dict) or set(p) != required:
            return None
        now = self.clock()
        if (p['model'] != self.model or p['provider'] != self.provider or type(p['count']) is not int
                or p['count'] != 1 or p['size'] != '1024x1024'
                or type(p['ceilingUsdMicro']) is not int or not 1 <= p['ceilingUsdMicro'] <= 1_000_000
                or type(p['expiresAt']) is not int or not now < p['expiresAt'] <= now + 31 * 86400
                or p['qualification'] != 'operator-approved-ceiling'
                or not isinstance(p['evidenceRef'], str) or not 1 <= len(p['evidenceRef'].strip()) <= 160
                or p['executionProviders'] != self.allowed_providers):
            return None
        return {'ceilingUsdMicro': p['ceilingUsdMicro'], 'basis': self.ESTIMATE_BASIS}

    @staticmethod
    def _reported_cost(body):
        usage = body.get('usage') if isinstance(body.get('usage'), dict) else {}
        _provider, gateway = gateway_routing(body)
        if 'cost' in _gateway_metadata(body):
            return gateway if cost_usd_micro(gateway) is not None else None
        value = usage.get('cost')
        return float(value) if cost_usd_micro(value) is not None else None

    def generate(self, prompt, *, count=1, emit=lambda _event: None, credit_approved=False, credit_guard=None):
        # A request that reached the provider is one pr_ai_call_events attempt (Founder Admin §8.B), noted in the active
        # ai_call_events scope whatever the outcome; nothing is noted when the request was refused before sending.
        meter = {}
        try:
            return self._generate(prompt, count=count, emit=emit, meter=meter, credit_approved=credit_approved, credit_guard=credit_guard)
        finally:
            if meter:
                began = meter.pop("began")
                ai_call_events.attempt(provider=self.provider, model=self.model, workload="image_generation", latency_ms=round((time.monotonic() - began) * 1000), **meter)

    def _generate(self, prompt, *, count, emit, meter, credit_approved, credit_guard):
        prompt = clean(prompt, 4000)
        if not prompt:
            raise AlphaError("Describe the image you want to generate.", 400)
        if type(count) is not int or count != 1:
            raise AlphaError("This chat generates one reviewable image candidate at a time.", 400)
        basis = self.credit_basis()
        qualified = basis is not None
        if credit_approved and not qualified:
            raise ImageGenerationError('The image credit price qualification expired. Review it again.', 503, cost_usd=0.0)
        if credit_approved:
            if not callable(credit_guard):
                raise ImageGenerationError('The image funding approval is unavailable.', 503, cost_usd=0.0)
            try:
                credit_guard(next_usd_micro=basis['ceilingUsdMicro'], spent_usd_micro=0, unknown=False,
                             model=self.model, provider=self.provider)
            except AlphaError as error:
                raise ImageGenerationError(str(error), error.status, cost_usd=0.0) from error
        emit({"type": "progress.updated", "stage": "image_generation", "percent": 25})
        meter.update(began=time.monotonic(), started_at=time.time(), status="unknown")
        response = self.transport(
            "POST",
            DEFAULT_ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}"},
            body={
                "model": self.model,
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json",
                "providerOptions": {"gateway": {"only": list(self.allowed_providers)}},
            },
        )
        if not isinstance(response, dict):
            raise ImageGenerationError('The image provider returned an unreadable response.', uncertain=True)
        status = response.get('status')
        meter['http_status'] = status if type(status) is int else None
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        final_provider, _gateway_cost = gateway_routing(body)
        cost = self._reported_cost(body)
        reported = ('cost' in _gateway_metadata(body)
                    or isinstance(body.get('usage'), dict) and 'cost' in body['usage'])
        # Refusals without accounting evidence retain their existing zero-cost state.
        # An explicit unusable charge is unknown, including on error responses.
        failure_cost = cost if reported else 0.0 if type(status) is int and 400 <= status < 500 else None
        if cost is not None:
            meter.update(cost_usd_micro=cost_usd_micro(cost), cost_source="gateway")
        if status == 429:
            meter.update(status="rate_limited", images=0)
            if failure_cost is not None:
                meter.update(cost_usd_micro=cost_usd_micro(failure_cost), cost_source="provider")
            raise ImageGenerationError("The image provider is busy. No automatic retry was made.", 429, uncertain=failure_cost is None, cost_usd=failure_cost)
        if type(status) is not int or status >= 500:
            raise ImageGenerationError("The image request outcome must be reconciled before retrying.", uncertain=failure_cost is None, cost_usd=failure_cost)
        if status != 200:
            meter.update(status="failed", images=0)
            if failure_cost is not None:
                meter.update(cost_usd_micro=cost_usd_micro(failure_cost), cost_source="provider")
            raise ImageGenerationError("The image provider rejected this request; no image was saved.", status=502, uncertain=failure_cost is None, cost_usd=failure_cost)
        meter.update(status="ok", images=1, provider_request_id=gateway_generation(body))
        if qualified and not final_provider:
            raise ImageGenerationError('The image execution provider could not be verified.', uncertain=cost is None, cost_usd=cost)
        if final_provider and final_provider not in self.allowed_providers:
            raise ImageGenerationError(
                f"The image was made by {final_provider}, outside the approved providers, so it was not kept.",
                uncertain=cost is None,
                cost_usd=cost,
            )
        try:
            encoded = body["data"][0]["b64_json"]
            raw = base64.b64decode(encoded, validate=True)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ImageGenerationError("The image provider returned no usable image bytes.", uncertain=cost is None, cost_usd=cost) from error
        if not 1 <= len(raw) <= 8 * 1024 * 1024 or not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
            raise ImageGenerationError("The generated image failed the media boundary checks.", uncertain=cost is None, cost_usd=cost)
        emit({"type": "progress.updated", "stage": "image_generation", "percent": 75})
        return {
            "images": [raw],
            "usage": {
                "provenance": "provider_reported" if cost is not None else "provider_cost_pending",
                "modelRequests": 1,
                "costUsd": cost,
                "model": self.model,
                "provider": self.provider,
                **({"executionProvider": final_provider} if final_provider else {}),
            },
        }


def from_environment(values):
    key = values.get("AI_GATEWAY_API_KEY")
    if not key:
        return None
    raw_estimate = values.get("POSTRIFF_IMAGE_ESTIMATE_USD_MICRO") or str(DEFAULT_ESTIMATE_USD_MICRO)
    try:
        estimate = int(raw_estimate)
    except (TypeError, ValueError) as error:
        raise AlphaError("POSTRIFF_IMAGE_ESTIMATE_USD_MICRO must be an integer.", 503) from error
    model = values.get("POSTRIFF_IMAGE_MODEL") or DEFAULT_MODEL
    raw_policy = values.get('POSTRIFF_IMAGE_CREDIT_COST_POLICY')
    try:
        credit_policy = json.loads(raw_policy) if raw_policy else None
    except (ValueError, TypeError):
        credit_policy = None  # Credit pricing fails closed; legacy capability is preserved.
    return GatewayImageRuntime(key, model, estimate_usd_micro=estimate,
                               allowed_providers=provider_map(values).get(model), credit_policy=credit_policy)

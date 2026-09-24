"""Provider-independent image generation for Ideas chat.

The selected writing model (managed model, Claude CLI, Codex CLI, or fixture)
never owns this capability. Image requests use one qualified, server-side media
route so the same chat affordance behaves consistently for every writer.
"""
import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from postriff_alpha.domain import AlphaError, clean


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

    def __init__(self, message, status=502, *, uncertain=False):
        super().__init__(message, status)
        self.uncertain = uncertain


def image_transport(method, url, headers=None, body=None, timeout=TIMEOUT_SECONDS):
    if url != DEFAULT_ENDPOINT:
        raise ImageGenerationError("Image generation must use the qualified gateway endpoint.", 503)
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
        raise ImageGenerationError("The image provider returned an unreadable response.", uncertain=status >= 500) from error
    return {"status": status, "body": parsed}


class GatewayImageRuntime:
    """One image candidate through AI Gateway, independent from the writing route."""

    provider = "vercel-ai-gateway"
    cost_class = "paid"

    def __init__(self, api_key, model=DEFAULT_MODEL, *, transport=None, estimate_usd_micro=DEFAULT_ESTIMATE_USD_MICRO):
        if not isinstance(api_key, str) or not api_key:
            raise AlphaError("An image gateway key is required.", 503)
        if not isinstance(model, str) or "/" not in model or len(model) > 160:
            raise AlphaError("Configure an exact qualified image model.", 503)
        if type(estimate_usd_micro) is not int or not 1 <= estimate_usd_micro <= 1_000_000:
            raise AlphaError("Configure a bounded image-generation cost estimate.", 503)
        self.api_key = api_key
        self.model = model
        self.transport = transport or image_transport
        self.estimate_usd_micro = estimate_usd_micro

    def generate(self, prompt, *, count=1, emit=lambda _event: None):
        prompt = clean(prompt, 4000)
        if not prompt:
            raise AlphaError("Describe the image you want to generate.", 400)
        if count != 1:
            raise AlphaError("This chat generates one reviewable image candidate at a time.", 400)
        emit({"type": "progress.updated", "stage": "image_generation", "percent": 25})
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
            },
        )
        status, body = response.get("status"), response.get("body") or {}
        if status == 429:
            raise ImageGenerationError("The image provider is busy. No automatic retry was made.", 429, uncertain=False)
        if status is None or status >= 500:
            raise ImageGenerationError("The image request outcome is unknown. Usage must be reconciled before retrying.", uncertain=True)
        if status != 200:
            raise ImageGenerationError("The image provider rejected this request; no image was saved.", status=502, uncertain=False)
        try:
            encoded = body["data"][0]["b64_json"]
            raw = base64.b64decode(encoded, validate=True)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ImageGenerationError("The image provider returned no usable image bytes.", uncertain=True) from error
        if not 1 <= len(raw) <= 8 * 1024 * 1024 or not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
            raise ImageGenerationError("The generated image failed the media boundary checks.", uncertain=True)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        reported = usage.get("cost")
        cost = float(reported) if type(reported) in (int, float) and reported >= 0 else None
        emit({"type": "progress.updated", "stage": "image_generation", "percent": 75})
        return {
            "images": [raw],
            "usage": {
                "provenance": "provider_reported" if cost is not None else "provider_cost_pending",
                "modelRequests": 1,
                "costUsd": cost,
                "model": self.model,
                "provider": self.provider,
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
    return GatewayImageRuntime(key, values.get("POSTRIFF_IMAGE_MODEL") or DEFAULT_MODEL, estimate_usd_micro=estimate)

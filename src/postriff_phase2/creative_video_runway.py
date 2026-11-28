"""Bounded, single-attempt Runway task protocol for direct and gateway models."""
import http.client
import json
import re
import ssl
import time
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from .creative_video_media import MAX_MEDIA_BYTES
from .creative_video_media_provider import ProviderError
from .creative_video_health import worker_health
from .creative_video_models import MODELS, RUNWAY_CREDIT_USD_MICRO, RUNWAY_GEN4, RUNWAY_VEO
from .mp4_boxes import brand


API_HOST = "api.dev.runwayml.com"
# This exact Runway distribution is documented at https://docs.dev.runwayml.com/assets/outputs/.
# An unfamiliar distribution requires operator review. The worker never authorizes a wildcard CDN.
ASSET_HOST = "dnznrvs05pmza.cloudfront.net"
UUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", re.ASCII)


class _UnsupportedContent(ValueError):
    """A complete provider response cannot fit the approved media contract."""


def _http(host, method, path, *, headers, body=None, types, limit):
    deadline = time.monotonic() + 60
    conn = http.client.HTTPSConnection(host, timeout=30, context=ssl.create_default_context())
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        if response.status not in (200, 201, 202):
            return response.status, b""
        mime = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if mime not in types or response.getheader("Content-Encoding", "identity") != "identity":
            raise _UnsupportedContent("Unexpected output format.")
        length = response.getheader("Content-Length")
        if length is not None and (not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > limit):
            raise _UnsupportedContent("Invalid content length.")
        raw = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Read deadline reached.")
            chunk = response.read1(min(256 * 1024, limit - len(raw) + 1))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > limit:
                raise _UnsupportedContent("Output is too large.")
        if length is not None and len(raw) != int(length):
            raise ValueError("Output is incomplete.")
        return response.status, bytes(raw)
    finally:
        conn.close()


def _request(method, path, body, key):
    status, data = _http(API_HOST, method, path, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "Accept": "application/json", "X-Runway-Version": "2024-11-06"}, body=None if body is None else json.dumps(body).encode(),
        types=("application/json",), limit=64 * 1024)
    return status, json.loads(data) if data else {}


def asset_request_path(url):
    try:
        if not isinstance(url, str) or not 0 < len(url) <= 16_384 or not re.fullmatch(r"[!-~]+", url) or "\\" in url:
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != ASSET_HOST or not parsed.path.startswith("/") or parsed.fragment:
            raise ValueError()
        return parsed.path + ("?" + parsed.query if parsed.query else "")
    except ValueError:
        raise ProviderError("The completed task returned an unapproved asset location.", uncertain=True,
                            code="creative_video_provider_output_invalid") from None


def _download(path):
    # Signed provider asset URLs never receive the API token; no redirects are followed.
    try:
        status, data = _http(ASSET_HOST, "GET", path, headers={"Accept": "video/mp4"}, types=("video/mp4", "application/octet-stream"),
                             limit=MAX_MEDIA_BYTES)
    except _UnsupportedContent:
        raise ProviderError("The saved task asset exceeds the supported media contract.",
                            code="creative_video_provider_output_invalid") from None
    if status in (404, 410) or (status == 200 and (not data or brand(data[:1024]) is None)):
        raise ProviderError("The saved task has no usable MP4 output.", code="creative_video_provider_output_invalid")
    if status != 200:
        raise OSError("The saved task asset is temporarily unavailable.")
    return data


def _receipt(response, verified_unit):
    cost = response.get("cost")
    units = cost.get("credits") if isinstance(cost, dict) else None
    if type(units) is not int or not 0 <= units <= 10**7:
        units = None
    actual = 0 if units == 0 else None
    if units is not None and type(verified_unit) is int and 0 < verified_unit <= RUNWAY_CREDIT_USD_MICRO:
        actual = units * verified_unit
    return {"providerCredits": units, "costUsdMicro": actual,
            "costSource": "provider_task_usage" if actual is not None else "provider_invoice_pending"}


class RunwayProvider:
    provider = "runway"

    def __init__(self, model, key):
        self.model = model
        self._key = key
        self.transport = _request
        self.download = _download
        self.may_submit = True
        self.health_scope = None

    @classmethod
    def from_environment(cls, model, env):
        key = env.get("RAFII_CREATIVE_VIDEO_RUNWAY_KEY")
        if model not in (RUNWAY_GEN4, RUNWAY_VEO) or not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_~.+/=-]{1,8192}", key):
            raise ProviderError("Runway requires a scoped server credential.", status=503, code="creative_video_provider_unavailable")
        return cls(model, key)

    @staticmethod
    def _check_operation(operation):
        if not isinstance(operation, str) or not UUID.fullmatch(operation):
            raise AlphaError("The saved Runway operation is invalid.", 409)

    def _call(self, method, path, body=None):
        try:
            status, result = self.transport(method, path, body, self._key)
            if status in (200, 201, 202, 204) and isinstance(result, dict):
                worker_health.observe(self.health_scope, status)
                return result
        except (OSError, TimeoutError, ValueError, http.client.HTTPException):
            status = None
        worker_health.observe(self.health_scope, status)
        if method == "POST":
            if status in (400, 401, 402, 403, 404, 413, 422, 429):
                raise ProviderError("Runway declined this generation request.", status=429 if status == 429 else 502)
            raise ProviderError("The Runway submission outcome is unknown. Reconcile the saved claim.", uncertain=True,
                                code="creative_video_submission_unknown")
        if method == "GET" and status in (404, 410):
            raise ProviderError("Runway cannot find the saved task.", uncertain=True, code="creative_video_operation_unavailable")
        raise ProviderError("The saved Runway task could not be checked. Recheck that same task.", uncertain=True,
                            status=503, code="creative_video_poll_unavailable")

    def submit(self, *, prompt, duration_ms, aspect_ratio, strategy):
        if not self.may_submit:
            raise ProviderError("This Runway credential is being used to recover an existing operation.", status=503)
        if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt or len(prompt.encode("utf-16-le")) // 2 > 1000:
            raise AlphaError("Runway accepts up to 1,000 UTF-16 units of scene direction.", 422)
        if strategy.get("model") != self.model:
            raise AlphaError("This quote belongs to a different model.", 409)
        profile = MODELS[self.model].profile(duration_ms, aspect_ratio, strategy["resolution"], strategy["audio"])
        body = {"model": self.model, "promptText": prompt, "duration": profile["durationMs"] // 1000,
                "ratio": f"{profile['width']}:{profile['height']}"}
        if self.model == RUNWAY_VEO:
            body["audio"] = profile["hasAudio"]
        response = self._call("POST", "/v1/text_to_video", body)
        handle = response.get("id")
        if not isinstance(handle, str) or not UUID.fullmatch(handle):
            raise ProviderError("Runway did not return a usable operation ID. Reconciliation is required.", uncertain=True,
                                code="creative_video_submission_unknown")
        return handle

    def cancel(self, operation):
        self._check_operation(operation)
        self._call("DELETE", f"/v1/tasks/{operation}")
        # The provider may already have started processing. Only the terminal receipt establishes cost.
        return {"state": "pending", "reason": "cancellation_requested", **_receipt({}, None)}

    def poll(self, operation, *, verified_unit_usd_micro=None):
        self._check_operation(operation)
        result = self._call("GET", f"/v1/tasks/{operation}")
        if result.get("id") != operation:
            raise ProviderError("The returned task does not match the saved Runway operation.", uncertain=True)
        status = result.get("status")
        if status in ("PENDING", "THROTTLED", "RUNNING"):
            return {"state": "pending", **_receipt({}, None)}
        receipt = _receipt(result, verified_unit_usd_micro)
        if status in ("CANCELLED", "CANCELED"):
            return {"state": "cancelled", "reason": "provider_cancelled", **receipt}
        if status == "FAILED":
            return {"state": "failed", "reason": "provider_operation_failed", **receipt}
        if status != "SUCCEEDED":
            raise ProviderError("Runway returned an unrecognized operation state.", uncertain=True)
        outputs = result.get("output")
        unusable = {"state": "failed", "reason": "provider_output_unusable", **receipt}
        if not isinstance(outputs, list) or len(outputs) != 1:
            return unusable
        try:
            path = asset_request_path(outputs[0])
            raw = self.download(path)
        except ProviderError as error:
            if error.code == "creative_video_provider_output_invalid":
                return unusable
            raise
        except (OSError, TimeoutError, ValueError, http.client.HTTPException):
            raise ProviderError("The existing Runway asset could not be retrieved. Recheck its saved operation.",
                                uncertain=True, code="creative_video_poll_unavailable") from None
        return {"state": "completed", "video": raw, **receipt}

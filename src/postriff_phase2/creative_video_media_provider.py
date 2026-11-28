"""Google Cloud Veo adapter. The workspace job owns billing and retries."""
import base64
import binascii
import http.client
import json
import os
import re
import ssl
import time

from postriff_alpha.domain import AlphaError
from .creative_video_media import FPS, MAX_MEDIA_BYTES, MAX_SCENE_MS, MIN_SCENE_MS, SIZES
from .creative_video_models import MODELS, VERTEX_FAST
from . import creative_video_first_frame as frames
from .creative_video_health import worker_health
from .mp4_boxes import brand


HOST = "us-central1-aiplatform.googleapis.com"
MODEL = VERTEX_FAST
RATE_MICRO_USD = MODELS[MODEL].rates_for("720p", "generated")
TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]{1,8192}", re.ASCII)


class ProviderError(AlphaError):
    def __init__(self, message, *, uncertain=False, status=502, code="creative_video_provider_error"):
        super().__init__(message, status, code=code)
        self.uncertain = uncertain


def _workload_token():
    """An attached GCP service account only. This never searches user ADC, files, CLI accounts or a supplied URL."""
    conn = http.client.HTTPConnection("metadata.google.internal", timeout=2)
    try:
        conn.request("GET", "/computeMetadata/v1/instance/service-accounts/default/token",
                     headers={"Metadata-Flavor": "Google", "Accept": "application/json"})
        response = conn.getresponse()
        if (response.status != 200 or response.getheader("Metadata-Flavor") != "Google" or
                (response.getheader("Content-Type") or "").partition(";")[0].strip() != "application/json"):
            raise ValueError()
        size = response.getheader("Content-Length")
        if size is not None and (not re.fullmatch(r"[0-9]{1,5}", size) or int(size) > 16_384):
            raise ValueError()
        data = bytearray()
        deadline = time.monotonic() + 3
        while len(data) <= 16_384 and time.monotonic() < deadline:
            part = response.read1(16_385 - len(data))
            if not part:
                break
            data.extend(part)
        else:
            raise ValueError()
        body = json.loads(data)
        token = body.get("access_token") if isinstance(body, dict) else None
        if (not isinstance(token, str) or not TOKEN.fullmatch(token) or body.get("token_type") != "Bearer"
                or type(body.get("expires_in")) is not int or not 30 <= body["expires_in"] <= 3600):
            raise ValueError()
        return token
    except (OSError, TimeoutError, http.client.HTTPException, ValueError):
        raise ProviderError("The attached Google service account could not supply a short-lived worker credential.",
                            status=503, code="creative_video_workload_unavailable") from None
    finally:
        conn.close()


def _transport(path, body, token, limit):
    # The client owns the fixed HTTPS origin. Redirects are never followed.
    connection = http.client.HTTPSConnection(HOST, timeout=35, context=ssl.create_default_context())
    try:
        connection.request("POST", path, body=json.dumps(body, ensure_ascii=False).encode(), headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return response.status, {}
        if response.getheader("Content-Type", "").partition(";")[0].lower() != "application/json":
            raise ValueError("Unexpected video response type.")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isascii() or not length.isdigit() or int(length) > limit):
            raise ValueError("Video response exceeds the supported size.")
        data = bytearray()
        deadline = time.monotonic() + 60
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Video response exceeded the read deadline.")
            chunk = response.read1(min(256 * 1024, limit - len(data) + 1))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Video response exceeds the supported size.")
        return response.status, json.loads(data)
    finally:
        connection.close()


def requested_seconds(duration_ms):
    if type(duration_ms) is not int or not MIN_SCENE_MS <= duration_ms <= MAX_SCENE_MS:
        raise AlphaError("Choose a scene between 42 milliseconds and 8 seconds.", 422)
    return next(seconds for seconds in (4, 6, 8) if duration_ms <= 1000 * seconds)


def output_profile(duration_ms, aspect_ratio):
    if aspect_ratio not in ("16:9", "9:16"):
        raise AlphaError("Veo supports landscape or vertical generation.", 422)
    width, height = SIZES[aspect_ratio]
    return {"width": width, "height": height, "fps": FPS, "hasAudio": True,
            "durationMs": requested_seconds(duration_ms) * 1000, "minFrames": (duration_ms * FPS + 999) // 1000}


class VideoProvider:
    """The caller persists the submission claim before calling submit exactly once.

    One poll only retrieves the same saved operation. A lost submit response
    cannot safely be turned into a new request. No provider fallback or spend
    takes place when configuration is incomplete.
    """
    provider = "vertex-veo"
    model = MODEL

    def __init__(self, project, token):
        self.model_path = f"projects/{project}/locations/us-central1/publishers/google/models/{MODEL}"
        self._token = token
        self.transport = _transport
        self.may_submit = True
        self.health_scope = None

    @classmethod
    def from_environment(cls, values=None):
        values = os.environ if values is None else values
        project = values.get("RAFII_CREATIVE_VIDEO_PROJECT", "")
        token = values.get("RAFII_CREATIVE_VIDEO_ACCESS_TOKEN", "")
        auth = values.get("RAFII_CREATIVE_VIDEO_AUTH", "runtime-token")
        credential_ok = ((auth == "runtime-token" and isinstance(token, str) and TOKEN.fullmatch(token)) or
                         (auth == "attached-service-account" and not token))
        if (values.get("VERCEL_ENV") == "preview" or values.get("RAFII_CREATIVE_VIDEO_PROVIDER") != cls.provider or not isinstance(project, str)
                or not re.fullmatch(r"(?:[a-z][a-z0-9-]{4,28}[a-z0-9]|[0-9]{6,20})", project)
                or not credential_ok):
            raise ProviderError("Video generation needs an enabled Google Cloud project and worker credential.",
                                status=503, code="creative_video_provider_unavailable")
        return cls(project, token if auth == "runtime-token" else None)

    @staticmethod
    def estimate(duration_ms):
        return requested_seconds(duration_ms) * RATE_MICRO_USD

    def _operation(self, value):
        return isinstance(value, str) and bool(re.fullmatch(re.escape(self.model_path) + r"/operations/[A-Za-z0-9_-]{1,128}", value))

    def _call(self, action, body, limit, *, submitting):
        # A failure here precedes the only network submission and is known to have no provider effect.
        token = self._token or _workload_token()
        try:
            status, response = self.transport(f"/v1/{self.model_path}:{action}", body, token, limit)
            if status == 200 and isinstance(response, dict):
                worker_health.observe(self.health_scope, status)
                return response
        except (OSError, TimeoutError, http.client.HTTPException, ValueError):
            status = None
        worker_health.observe(self.health_scope, status)
        if submitting and status in (400, 401, 403, 404, 413, 422, 429):
            raise ProviderError("The configured video provider declined the request.", status=429 if status == 429 else 502)
        if not submitting and status in (404, 410):
            raise ProviderError("The configured provider no longer has the saved operation.",
                                code="creative_video_operation_unavailable")
        if submitting:
            raise ProviderError("The video submission outcome is unknown. Reconcile the existing request before retrying.",
                                uncertain=True, code="creative_video_submission_unknown")
        raise ProviderError("The saved video operation could not be checked. Check this same operation again.",
                            uncertain=True, status=503, code="creative_video_poll_unavailable")

    def submit(self, *, prompt, duration_ms, aspect_ratio, strategy=None, first_frame=None):
        if not self.may_submit:
            raise ProviderError("This Veo credential is being used to recover an existing operation.", status=503)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000 or "\x00" in prompt:
            raise AlphaError("Use a scene description of up to 4,000 characters.", 422)
        if strategy is not None and strategy.get("model") != self.model:
            raise AlphaError("This quote belongs to a different model.", 409)
        resolution = strategy["resolution"] if strategy else "720p"
        audio = strategy["audio"] if strategy else "generated"
        profile = MODELS[self.model].profile(duration_ms, aspect_ratio, resolution, audio)
        body = {"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": aspect_ratio, "resolution": resolution,
                "durationSeconds": profile["durationMs"] // 1000, "generateAudio": profile["hasAudio"], "sampleCount": 1}}
        settings = (strategy or {}).get("settings", {})
        approved = (strategy or {}).get("firstFrame")
        if first_frame is not None or approved is not None or settings.get("firstFrameAssetId"):
            if (not isinstance(approved, dict) or not approved.get("assetId") or
                    approved["assetId"] != settings.get("firstFrameAssetId") or settings.get("firstFrameConsent") is not True):
                raise AlphaError("Review a quote for this exact first frame.", 409)
            frames.verify(first_frame, approved)
            body["instances"][0]["image"] = {"mimeType": "image/jpeg",
                                              "bytesBase64Encoded": base64.b64encode(first_frame).decode("ascii")}
            body["parameters"]["resizeMode"] = "pad"
        response = self._call("predictLongRunning", body, 64 * 1024, submitting=True)
        name = response.get("name")
        if not self._operation(name):
            raise ProviderError("The provider did not identify the submitted video. Reconciliation is required.",
                                uncertain=True, code="creative_video_submission_unknown")
        return name

    def poll(self, operation):
        if not self._operation(operation):
            raise AlphaError("This video operation does not belong to the configured provider project.", 409)
        response = self._call("fetchPredictOperation", {"operationName": operation},
                              4 * ((MAX_MEDIA_BYTES + 2) // 3) + 65536, submitting=False)
        if response.get("name") != operation:
            raise ProviderError("The returned video operation did not match the request.", uncertain=True)
        receipt = {"costUsdMicro": None, "costSource": "provider_invoice_pending"}
        if "done" in response and type(response["done"]) is not bool:
            raise ProviderError("The video operation state is invalid.", uncertain=True)
        if not response.get("done"):
            return {"state": "pending", **receipt}
        if "error" in response:
            return {"state": "failed", "reason": "provider_operation_failed", **receipt}
        result = response.get("response")
        if isinstance(result, dict) and result.get("raiMediaFilteredCount") and not result.get("videos"):
            return {"state": "failed", "reason": "provider_content_filtered", **receipt}
        try:
            videos = result["videos"]
            if not isinstance(videos, list) or len(videos) != 1 or videos[0].get("mimeType") != "video/mp4":
                raise ValueError()
            data = videos[0]["bytesBase64Encoded"]
            if not isinstance(data, str) or len(data) > 4 * ((MAX_MEDIA_BYTES + 2) // 3):
                raise ValueError()
            raw = base64.b64decode(data, validate=True)
            if not 0 < len(raw) <= MAX_MEDIA_BYTES or brand(raw[:1024]) is None:
                raise ValueError()
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, binascii.Error) as error:
            raise ProviderError("The provider finished without a supported inline MP4. Reconcile the saved operation.",
                                uncertain=True, code="creative_video_provider_output_invalid") from error
        return {"state": "completed", "video": raw, **receipt}

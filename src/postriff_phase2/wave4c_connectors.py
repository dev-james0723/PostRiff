"""Wave 4C connectors for per-instance Pixelfed and Xiaohongshu identity.

Pixelfed reuses the Mastodon-compatible identity path only after probing the chosen instance as Pixelfed.
Xiaohongshu uses the official Web device-code flow and requests only basic_info. Content abilities stay disabled.
"""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlparse

from postriff_alpha.domain import AlphaError
from .provider_base import OAuthProvider, _credential_shape, default_transport
from .social_connectors import MastodonProvider, _https_origin
from .net_guard import assert_public, pinned_public_json_transport, public_host
from .wave4_publishers import PixelfedPosts


class PixelfedProvider(MastodonProvider):
    id, platform, capability_version = "pixelfed", "Pixelfed", 1
    wave, feature_flag_required = "4C", True
    SCOPES = {"identity": ["read"], "publish": ["read", "write"]}
    EXPLAIN = {"identity": "Connect your identity on this Pixelfed instance. Rafii probes the instance first and requests read-only access."}
    account_requirement = "An account on a Pixelfed instance that exposes its OAuth and compatible identity endpoints."
    normalized = {
        "identity": "supported", "account_discovery": "supported",
        "publish_image": "supported", "publish_video": "account_type_limited",
        "owned_content_read": "requires_review", "owned_analytics": "unsupported",
        "comments_read": "requires_review", "comments_reply": "requires_review",
        "refresh_token": "account_type_limited", "revoke": "supported", "scheduled_publish": "unsupported",
        "public_search": "account_type_limited",
    }
    publish_scope = "write"
    publish_required = frozenset({"write"})
    publisher = PixelfedPosts()

    def __init__(self, website, transport=None, production_reviewed=False, resolver=None):
        import socket
        self.resolver = resolver or socket.getaddrinfo
        safe_transport = transport or (lambda method, url, **kw: pinned_public_json_transport(
            method, url, resolver=self.resolver, **kw))
        super().__init__(website, transport=safe_transport, production_reviewed=production_reviewed,
                         resolver=self.resolver)

    def _server(self, value):
        raw = value.strip() if isinstance(value, str) else ""
        parsed = urlparse(raw) if raw.startswith("https://") else None
        if ("@" in raw or "#" in raw or "?" in raw or (parsed and
            (parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.port not in (None, 443)))):
            raise AlphaError("Enter only the public Pixelfed instance name.", 400)
        return assert_public(public_host(raw), self.resolver)

    def write_qualified(self, token):
        return self.session(token)["instance"] in getattr(self, "qualified_instances", frozenset())

    @classmethod
    def mount(cls, values, transport=None):
        flag, base = values.get("POSTRIFF_OAUTH_PIXELFED_ENABLED"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        presence = {"clientId": flag is not None, "clientSecret": bool(base)}
        missing = [name for name, present in (("POSTRIFF_OAUTH_PIXELFED_ENABLED", flag is not None), ("POSTRIFF_PUBLIC_BASE_URL", bool(base))) if not present]
        state = ("not_configured" if flag is None else "partial_configuration" if missing
                 else "configured" if str(flag).lower() == "true" and _https_origin(base) else "invalid_configuration")
        diagnostic = {"configurationState": state, "credentialPresence": presence, "missingVariables": missing}
        return (cls(base, transport=transport) if state == "configured" else None), diagnostic

    def _probe(self, host):
        response = self.transport("GET", f"https://{host}/api/v2/instance")
        if response.get("status") != 200 or not isinstance(response.get("body"), dict):
            response = self.transport("GET", f"https://{host}/api/v1/instance")
        body = response.get("body") if response.get("status") == 200 and isinstance(response.get("body"), dict) else None
        marker = json.dumps(body or {}, sort_keys=True).lower()
        if body is None or "pixelfed" not in marker:
            raise AlphaError("That server did not identify itself as a compatible Pixelfed instance.", 409)
        return {"version": str(body.get("version") or "unknown")[:80]}

    def begin(self, redirect, state, verifier, challenge, scopes, instance):
        host = self._server(instance)
        probe = self._probe(host)
        begun = super().begin(redirect, state, verifier, challenge, scopes, host)
        begun["context"]["pixelfedProbe"] = probe
        return begun


def verify_xiaohongshu_webhook(webhook_key, timestamp, raw_body, supplied_signature, now_ms=None):
    """Verify timestamp + '.' + exact raw bytes and reject requests outside the five-minute window."""
    if not _credential_shape(webhook_key) or not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{13}", timestamp):
        return False
    if not isinstance(raw_body, bytes) or not isinstance(supplied_signature, str) or not re.fullmatch(r"[a-f0-9]{64}", supplied_signature):
        return False
    current = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if abs(current - int(timestamp)) > 300_000:
        return False
    expected = hmac.new(webhook_key.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied_signature)


class XiaohongshuProvider(OAuthProvider):
    """Official Xiaohongshu account identity through its Web device-code flow."""
    id, platform, capability_version = "xiaohongshu", "Xiaohongshu", 1
    wave, feature_flag_required, provider_approval_required = "4C", True, True
    connect_kind = "device_code"
    BASE = "https://openaccount.xiaohongshu.com"
    SCOPES = {"identity": ["basic_info"]}
    EXPLAIN = {"identity": "Connect your Xiaohongshu identity by scanning the provider's code. Rafii requests only basic_info for nickname and avatar."}
    account_requirement = "An approved Xiaohongshu Open Platform application. Web connection requires the user to scan and approve the provider's device code."
    normalized = {
        "identity": "supported", "publish_text": "unsupported", "publish_image": "unsupported",
        "publish_video": "unsupported", "owned_content_read": "unsupported", "owned_analytics": "unsupported",
        "comments_read": "unsupported", "comments_reply": "unsupported", "comments_moderate": "unsupported",
        "webhooks": "requires_review", "refresh_token": "supported", "revoke": "requires_review",
        "scheduled_publish": "unsupported", "public_search": "unsupported",
    }
    documented_scopes = ("basic_info",)
    start_input = None
    has_destinations = False

    def __init__(self, client_id, client_secret, transport=None, production_reviewed=False, webhook_secret=None):
        if not client_id or not client_secret:
            raise AlphaError("Xiaohongshu client credentials are required.", 503)
        self.client_id, self.client_secret = client_id, client_secret
        self.transport = transport or default_transport()
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True
        self.webhook_secret = webhook_secret if _credential_shape(webhook_secret) and len(webhook_secret) >= 32 else None

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, valid, diagnostic = cls.credential_pair(values)
        return (cls(client_id, secret, transport=transport) if valid else None), diagnostic

    @staticmethod
    def _data(response, allow_pending=False):
        body = response.get("body") if isinstance(response, dict) else None
        if not isinstance(body, dict) or response.get("status") != 200:
            raise AlphaError("Xiaohongshu did not complete this authorization step.", 502)
        if allow_pending and body.get("code") in (37002, 37009):
            return {"pending": True, "reason": "scanned" if body.get("code") == 37009 else "waiting"}
        if body.get("code") != 0 or body.get("success") is not True or not isinstance(body.get("data"), dict):
            raise AlphaError("Xiaohongshu did not complete this authorization step.", 409)
        return body["data"]

    def _post(self, path, payload, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        return self.transport("POST", self.BASE + path, headers=headers, body=payload)

    @staticmethod
    def _grant(data, previous_refresh=None):
        if not isinstance(data, dict) or not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise AlphaError("Xiaohongshu did not return a usable access token.", 502)
        if not isinstance(data.get("open_id"), str) or not data["open_id"]:
            raise AlphaError("Xiaohongshu did not identify the authorized account.", 502)
        scopes = sorted(set(data.get("scope") or [])) if isinstance(data.get("scope"), list) else []
        expires_in = max(1, int(data.get("expire_time") or 0) - int(time.time())) if data.get("expire_time") else None
        session = {"v": 1, "at": data["access_token"], "openId": str(data["open_id"]), "scope": scopes}
        return {"accessToken": json.dumps(session), "refreshToken": data.get("refresh_token") or previous_refresh,
                "expiresIn": expires_in, "scopes": scopes}

    @staticmethod
    def _session(value):
        try:
            session = json.loads(value)
        except (TypeError, ValueError) as error:
            raise AlphaError("This account needs to be reconnected.", 409) from error
        if not isinstance(session, dict) or not isinstance(session.get("at"), str) or not isinstance(session.get("openId"), str):
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def begin_device(self, state, scopes):
        data = self._data(self._post("/api/sns/v1/oauth2/device/code", {"app_id": self.client_id, "app_secret": self.client_secret,
                                                                        "scopes": scopes, "client_name": "Rafii Web", "device_id": state, "scene": "web"}))
        uri = data.get("verification_uri_complete")
        if not isinstance(uri, str) or urlparse(uri).scheme != "https" or urlparse(uri).hostname != "openaccount.xiaohongshu.com":
            raise AlphaError("Xiaohongshu returned an invalid verification page.", 502)
        if not isinstance(data.get("device_code"), str) or not isinstance(data.get("user_code"), str):
            raise AlphaError("Xiaohongshu did not create a device authorization.", 502)
        interval = data.get("interval")
        expires_in = data.get("expires_in")
        if type(interval) is not int or not 1 <= interval <= 60 or type(expires_in) is not int or not 30 <= expires_in <= 900:
            raise AlphaError("Xiaohongshu returned invalid device authorization timing.", 502)
        return {"authorizeUrl": uri, "userCode": data["user_code"],
                "instructions": ["Open the Xiaohongshu verification page and scan its code with the Xiaohongshu app.",
                                 "Review that Rafii requests only basic_info, then approve or cancel in Xiaohongshu.",
                                 "Return here and choose Check connection."],
                "context": {"kind": self.connect_kind, "deviceCode": data["device_code"], "interval": interval,
                            "providerExpiresIn": expires_in}}

    def poll_device(self, context):
        device = context.get("deviceCode") if isinstance(context, dict) else None
        if not isinstance(device, str) or not device:
            raise AlphaError("Connection request unavailable.", 404)
        result = self._data(self._post("/api/sns/v1/oauth2/device/token", {"app_id": self.client_id, "app_secret": self.client_secret,
                                                                           "device_code": device}), allow_pending=True)
        if result.get("pending"):
            return result
        return {"grant": self._grant(result)}

    def authorize_url(self, *_):
        raise AlphaError("Use Xiaohongshu's Web device authorization.", 409)

    def exchange(self, code, verifier, redirect):
        data = self._data(self._post("/api/sns/v1/oauth2/access_token", {"app_id": self.client_id, "app_secret": self.client_secret, "code": code}))
        return self._grant(data)

    def identity(self, access_token):
        session = self._session(access_token)
        data = self._data(self._post("/api/sns/v1/oauth2/batch_get_min_user_info", {}, token=session["at"]))
        if str(data.get("open_id")) != session["openId"]:
            raise AlphaError("Xiaohongshu returned a different account.", 409)
        return {"providerAccountId": session["openId"], "handle": str(data.get("nickname") or session["openId"]),
                "accountType": "profile", "pictureUrl": data.get("avatar") if isinstance(data.get("avatar"), str) else None}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self._session(access_token)
        data = self._data(self._post("/api/sns/v1/oauth2/token_status", {"access_token": session["at"]}))
        if expected_account_id and str(data.get("open_id")) != expected_account_id:
            return None
        scopes = data.get("scope")
        return sorted(set(scopes)) if isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes) else None

    def refresh(self, refresh_token):
        data = self._data(self._post("/api/sns/v1/oauth2/refresh_token", {"app_id": self.client_id, "refresh_token": refresh_token}))
        return self._grant(data, refresh_token)

    def revoke(self, token):
        session = self._session(token)
        response = self._post("/api/sns/v1/oauth2/revoke", {"app_id": self.client_id, "app_secret": self.client_secret,
                                                             "access_token": session["at"], "reason": "user_unbind"})
        body = response.get("body") if isinstance(response, dict) else None
        return response.get("status") == 200 and isinstance(body, dict) and body.get("code") == 0 and body.get("success") is True

"""Wave 4B connectors: LINE Official Account, Reddit and Zhihu.

Reddit exposes an identity-only OAuth path behind explicit platform approval. LINE and Zhihu remain
readiness contracts: LINE needs a product-owned confidential channel-token handoff, while current
Zhihu publishing permission could not be independently verified. No browser or password fallback is used.
"""
import base64
import hashlib
import hmac
import json
import re
from urllib.parse import quote, urlencode

from postriff_alpha.domain import AlphaError
from .provider_base import OAuthProvider, _credential_shape


def verify_line_signature(channel_secret, raw_body, supplied_signature):
    """Verify LINE's x-line-signature over the exact, unmodified request bytes."""
    if not _credential_shape(channel_secret) or not isinstance(raw_body, bytes) or not isinstance(supplied_signature, str):
        return False
    expected = base64.b64encode(hmac.new(channel_secret.encode(), raw_body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, supplied_signature)


class _ApprovalGatedProvider(OAuthProvider):
    wave, feature_flag_required, provider_approval_required = "4B", True, True
    SCOPES = {}
    assisted_fallback = False
    oauth_contract_verified = False

    def authorize_url(self, *_):
        raise AlphaError(f"{self.platform} connection is awaiting its approved provider onboarding path.", 409)


class LineOfficialAccountProvider(_ApprovalGatedProvider):
    id, platform, capability_version = "line_official_account", "LINE Official Account", 1
    account_requirement = "A LINE Official Account with a Messaging API channel. Channel credentials need a confidential server-side handoff and webhook verification."
    normalized = {
        "identity": "requires_review", "account_discovery": "requires_review",
        "publish_text": "requires_review", "publish_image": "requires_review",
        "owned_analytics": "requires_review", "messaging_read": "requires_review",
        "messaging_reply": "requires_review", "webhooks": "requires_review",
        "refresh_token": "unsupported", "revoke": "requires_review", "scheduled_publish": "unsupported",
    }


class RedditProvider(OAuthProvider):
    id, platform, capability_version = "reddit", "Reddit", 1
    wave, feature_flag_required, provider_approval_required = "4B", True, True
    AUTH = "https://www.reddit.com/api/v1/authorize"
    TOKEN = "https://www.reddit.com/api/v1/access_token"
    REVOKE = "https://www.reddit.com/api/v1/revoke_token"
    ME = "https://oauth.reddit.com/api/v1/me"
    SCOPES = {"identity": ["identity"]}
    EXPLAIN = {"identity": "Connect your Reddit identity only. Posting and commenting remain separate, explicit user actions that require Reddit approval."}
    account_requirement = "A Reddit account and a Reddit-approved Rafii app. Commercial API use requires Reddit's written approval."
    refresh_margin = 300
    normalized = {
        "identity": "supported", "publish_text": "requires_review", "publish_image": "requires_review",
        "owned_content_read": "requires_review", "comments_read": "requires_review",
        "comments_reply": "requires_review", "comments_moderate": "account_type_limited",
        "refresh_token": "supported", "revoke": "supported", "scheduled_publish": "unsupported",
        "public_search": "requires_review",
    }
    documented_scopes = ("identity", "submit", "read", "history")

    def __init__(self, client_id, client_secret, contact, transport=None, production_reviewed=False):
        super().__init__(client_id, client_secret, transport=transport, production_reviewed=production_reviewed)
        self.contact = contact

    @classmethod
    def mount(cls, values, transport=None):
        client_id, secret, pair_valid, diagnostic = cls.credential_pair(values)
        prefix = cls.env_prefix()
        contact = values.get(prefix + "CONTACT")
        contact_present = contact is not None
        contact_valid = isinstance(contact, str) and re.fullmatch(r"u/[A-Za-z0-9_-]{3,20}", contact) is not None
        missing = list(diagnostic["missingVariables"]) + ([] if contact_present else [prefix + "CONTACT"])
        anything = diagnostic["configurationState"] != "not_configured" or contact_present
        state = "not_configured" if not anything else "partial_configuration" if missing else "configured" if pair_valid and contact_valid else "invalid_configuration"
        diagnostic = {**diagnostic, "configurationState": state, "missingVariables": missing}
        return (cls(client_id, secret, contact, transport=transport) if state == "configured" else None), diagnostic

    def _basic(self):
        raw = f"{quote(self.client_id, safe='')}:{quote(self.client_secret, safe='')}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _headers(self, token=None):
        headers = {"User-Agent": f"web:com.rafii.postriff:1.0 (by /{self.contact})"}
        if token:
            headers["Authorization"] = "Bearer " + token
        return headers

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "response_type": "code", "state": state,
                                             "redirect_uri": redirect, "duration": "permanent", "scope": " ".join(scopes)})

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = sorted(set(body.get("scope", "").split())) if isinstance(body.get("scope"), str) else []
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes}),
                "refreshToken": body.get("refresh_token") or refresh_token, "expiresIn": body.get("expires_in"), "scopes": scopes}

    @staticmethod
    def _session(value):
        try:
            session = json.loads(value)
        except (TypeError, ValueError) as error:
            raise AlphaError("This account needs to be reconnected.", 409) from error
        if not isinstance(session, dict) or not isinstance(session.get("at"), str) or not session["at"]:
            raise AlphaError("This account needs to be reconnected.", 409)
        return session

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, headers={**self._headers(), "Authorization": self._basic()},
                                       form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}), "access_token")
        return self._grant(body)

    def identity(self, access_token):
        session = self._session(access_token)
        body = self._ok(self.transport("GET", self.ME, headers=self._headers(session["at"])), "id", "name")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", str(body["name"])):
            raise AlphaError("Reddit could not verify this account.", 502)
        return {"providerAccountId": str(body["id"]), "handle": "u/" + body["name"], "accountType": "member",
                "pictureUrl": body.get("icon_img") if isinstance(body.get("icon_img"), str) else None}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = self._session(access_token)
        return list(session.get("scope") or [])

    def refresh(self, refresh_token):
        body = self._ok(self.transport("POST", self.TOKEN, headers={**self._headers(), "Authorization": self._basic()},
                                       form={"grant_type": "refresh_token", "refresh_token": refresh_token}), "access_token")
        return self._grant(body, refresh_token)

    def revoke(self, token):
        session = self._session(token)
        response = self.transport("POST", self.REVOKE, headers={**self._headers(), "Authorization": self._basic()},
                                  form={"token": session["at"], "token_type_hint": "access_token"})
        return response.get("status") == 200


class ZhihuProvider(_ApprovalGatedProvider):
    id, platform, capability_version = "zhihu", "Zhihu", 1
    account_requirement = "A Zhihu developer application with current OAuth and creator-data permissions independently confirmed by Zhihu."
    normalized = {
        "identity": "requires_review", "account_discovery": "requires_review",
        "publish_text": "unsupported", "publish_image": "unsupported",
        "owned_content_read": "requires_review", "comments_read": "requires_review",
        "comments_reply": "requires_review", "owned_analytics": "requires_review",
        "refresh_token": "requires_review", "revoke": "requires_review", "public_search": "requires_review",
    }

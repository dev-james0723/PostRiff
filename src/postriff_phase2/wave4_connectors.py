"""Wave 4A hosted account connectors.

Only the identity/account-discovery paths whose current official contracts are independently documented are executable.
Provider-review, enterprise-only and paid abilities stay in the normalized contract but do not become OAuth actions.
No adapter in this module turns an old or undocumented endpoint into a production permission.
"""
import json
import re
from urllib.parse import quote, urlencode

from postriff_alpha.domain import AlphaError
from .provider_base import OAuthProvider


def _scopes(value):
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return sorted(set(value))
    if isinstance(value, str):
        return sorted(set(part for part in re.split(r"[\s,]+", value.strip()) if part))
    return []


def _data(response):
    body = response.get("body") if isinstance(response, dict) else None
    if not isinstance(body, dict):
        raise AlphaError("The provider did not complete this authorization step.", 502)
    nested = body.get("data")
    return nested if isinstance(nested, dict) else body


def _session(value):
    try:
        session = json.loads(value)
    except (TypeError, ValueError) as error:
        raise AlphaError("This account needs to be reconnected.", 409) from error
    if not isinstance(session, dict) or not isinstance(session.get("at"), str) or not session["at"]:
        raise AlphaError("This account needs to be reconnected.", 409)
    return session


class _ReviewGatedProvider(OAuthProvider):
    """Catalogue entry for an official platform whose current OAuth endpoint contract is still behind its human gate."""
    wave, feature_flag_required, provider_approval_required = "4A", True, True
    SCOPES = {}
    normalized = {"identity": "requires_review"}
    assisted_fallback = False
    oauth_contract_verified = False

    def authorize_url(self, *_):
        raise AlphaError(f"{self.platform} OAuth is awaiting provider documentation and approval.", 409)


class WeiboProvider(_ReviewGatedProvider):
    id, platform, capability_version = "weibo", "Weibo", 1
    account_requirement = "A Weibo developer service and account approved for the requested APIs. API credits may be required."
    normalized = {
        "identity": "requires_review", "publish_text": "requires_review", "publish_image": "requires_review",
        "owned_content_read": "requires_review", "owned_analytics": "requires_review",
        "comments_read": "requires_review", "comments_reply": "requires_review", "public_search": "requires_review",
        "revoke": "requires_review",
    }


class BilibiliProvider(_ReviewGatedProvider):
    id, platform, capability_version = "bilibili", "Bilibili", 1
    account_requirement = "A Bilibili Open Platform developer identity and an approved application linked to the creator account."
    normalized = {
        "identity": "requires_review", "publish_text": "requires_review", "publish_video": "requires_review",
        "owned_content_read": "requires_review", "owned_analytics": "requires_review",
        "comments_read": "requires_review", "comments_reply": "requires_review", "webhooks": "requires_review",
        "revoke": "requires_review",
    }


class DouyinProvider(OAuthProvider):
    id, platform, capability_version = "douyin", "Douyin", 1
    wave, feature_flag_required, provider_approval_required = "4A", True, True
    AUTH = "https://open.douyin.com/platform/oauth/connect/"
    TOKEN = "https://open.douyin.com/oauth/access_token/"
    REFRESH = "https://open.douyin.com/oauth/refresh_token/"
    USERINFO = "https://open.douyin.com/oauth/userinfo/"
    SCOPES = {"identity": ["user_info"]}
    EXPLAIN = {"identity": "Connect your Douyin identity. Rafii reads only your public account name and avatar. Video publishing, analytics and comments remain separate platform-review permissions."}
    account_requirement = "A Douyin account; publishing and comments additionally require approved Open Platform permissions."
    read_scope = "video.list"
    refresh_margin = 3600
    normalized = {
        "identity": "supported", "publish_video": "requires_review", "owned_content_read": "requires_review",
        "owned_analytics": "requires_review", "comments_read": "account_type_limited",
        "comments_reply": "account_type_limited", "comments_moderate": "account_type_limited",
        "refresh_token": "supported", "revoke": "requires_review", "public_search": "requires_review",
    }
    documented_scopes = ("user_info", "video.create.bind", "video.list", "video.comment")

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_key": self.client_id, "response_type": "code", "scope": ",".join(scopes), "redirect_uri": redirect, "state": state})

    def exchange(self, code, verifier, redirect):
        response = self.transport("POST", self.TOKEN, form={"client_key": self.client_id, "client_secret": self.client_secret, "code": code, "grant_type": "authorization_code"})
        body = _data(response)
        if response.get("status") != 200 or not body.get("access_token") or not body.get("open_id"):
            raise AlphaError("Douyin did not complete this authorization step.", 502)
        scopes = _scopes(body.get("scope"))
        session = {"v": 1, "at": body["access_token"], "openId": str(body["open_id"]), "scope": scopes}
        return {"accessToken": json.dumps(session), "refreshToken": body.get("refresh_token"), "expiresIn": body.get("expires_in"), "scopes": scopes}

    def identity(self, access_token):
        session = _session(access_token)
        response = self.transport("POST", self.USERINFO, headers={"access-token": session["at"]}, body={"open_id": session["openId"]})
        body = _data(response)
        if response.get("status") != 200 or int(body.get("error_code") or 0) != 0:
            raise AlphaError("Douyin could not verify this account.", 502)
        return {"providerAccountId": session["openId"], "handle": str(body.get("nickname") or session["openId"]),
                "accountType": "enterprise" if body.get("e_account_role") else "creator", "pictureUrl": body.get("avatar")}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = _session(access_token)
        return list(session.get("scope") or []) if not expected_account_id or session.get("openId") == expected_account_id else None

    def refresh(self, refresh_token):
        response = self.transport("POST", self.REFRESH, form={"client_key": self.client_id, "refresh_token": refresh_token, "grant_type": "refresh_token"})
        body = _data(response)
        if response.get("status") != 200 or not body.get("access_token") or not body.get("open_id"):
            raise AlphaError("Douyin access could not be refreshed; reconnect this account.", 409)
        scopes = _scopes(body.get("scope"))
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "openId": str(body["open_id"]), "scope": scopes}),
                "refreshToken": body.get("refresh_token") or refresh_token, "expiresIn": body.get("expires_in"), "scopes": scopes}


class KuaishouProvider(OAuthProvider):
    id, platform, capability_version = "kuaishou", "Kuaishou", 1
    wave, feature_flag_required, provider_approval_required = "4A", True, True
    AUTH = "https://open.kuaishou.com/oauth2/authorize"
    TOKEN = "https://open.kuaishou.com/oauth2/access_token"
    REFRESH = "https://open.kuaishou.com/oauth2/refresh_token"
    USERINFO = "https://open.kuaishou.com/openapi/user_info"
    SCOPES = {"identity": ["user_info"]}
    EXPLAIN = {"identity": "Connect your Kuaishou account and read its public profile. Video upload is a separate permission and will not be requested here."}
    account_requirement = "A Kuaishou account. The website flow may ask you to scan a QR code or verify sign-in yourself."
    read_scope = "user_video_info"
    refresh_margin = 3600
    normalized = {
        "identity": "supported", "publish_video": "requires_review", "owned_content_read": "requires_review",
        "owned_analytics": "requires_review", "comments_read": "requires_review", "comments_reply": "unsupported",
        "refresh_token": "supported", "revoke": "unsupported",
    }
    documented_scopes = ("user_info", "user_video_publish", "user_video_info")

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"app_id": self.client_id, "scope": ",".join(scopes), "response_type": "code", "ua": "pc", "redirect_uri": redirect, "state": state})

    def _grant(self, response, refresh_token=None):
        body = _data(response)
        access = body.get("access_token") or body.get("accessToken")
        open_id = body.get("open_id") or body.get("openId")
        if response.get("status") != 200 or not access or not open_id:
            raise AlphaError("Kuaishou did not complete this authorization step.", 502)
        scopes = _scopes(body.get("scopes") or body.get("scope"))
        session = {"v": 1, "at": access, "openId": str(open_id), "scope": scopes}
        return {"accessToken": json.dumps(session), "refreshToken": body.get("refresh_token") or body.get("refreshToken") or refresh_token,
                "expiresIn": body.get("expires_in") or body.get("expiresIn"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        return self._grant(self.transport("POST", self.TOKEN, form={"app_id": self.client_id, "app_secret": self.client_secret, "code": code, "grant_type": "authorization_code"}))

    def identity(self, access_token):
        session = _session(access_token)
        response = self.transport("GET", self.USERINFO + "?" + urlencode({"app_id": self.client_id, "access_token": session["at"]}))
        body = _data(response)
        info = body.get("user_info") or body.get("userInfo")
        if response.get("status") != 200 or body.get("result") not in (1, "1") or not isinstance(info, dict):
            raise AlphaError("Kuaishou could not verify this account.", 502)
        return {"providerAccountId": session["openId"], "handle": str(info.get("name") or session["openId"]), "accountType": "creator",
                "pictureUrl": info.get("bigHead") or info.get("head")}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = _session(access_token)
        return list(session.get("scope") or []) if not expected_account_id or session.get("openId") == expected_account_id else None

    def refresh(self, refresh_token):
        return self._grant(self.transport("POST", self.REFRESH, form={"app_id": self.client_id, "app_secret": self.client_secret,
                                                                       "refresh_token": refresh_token, "grant_type": "refresh_token"}), refresh_token)


class GoogleBusinessProfileProvider(OAuthProvider):
    id, platform, capability_version = "google_business_profile", "Google Business Profile", 1
    wave, feature_flag_required, provider_approval_required = "4A", True, True
    AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN = "https://oauth2.googleapis.com/token"
    REVOKE = "https://oauth2.googleapis.com/revoke"
    TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
    USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
    ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
    LOCATIONS = "https://mybusinessbusinessinformation.googleapis.com/v1"
    BUSINESS_SCOPE = "https://www.googleapis.com/auth/business.manage"
    SCOPES = {"identity": ["openid", "profile", BUSINESS_SCOPE]}
    EXPLAIN = {"identity": "Google uses one Business Profile management permission for account discovery, posts, performance and review replies. Rafii initially lists only accounts and locations; write actions remain unavailable until the project and each feature are verified."}
    account_requirement = "A Google account that manages at least one Business Profile location; Google must approve Rafii's Cloud project."
    has_destinations = True
    destination_scope, destination_label = "connection", "Location"
    refresh_margin = 300
    normalized = {
        "identity": "supported", "account_discovery": "supported", "publish_text": "requires_review",
        "publish_image": "requires_review", "owned_content_read": "requires_review", "owned_analytics": "requires_review",
        "comments_read": "requires_review", "comments_reply": "requires_review", "comments_moderate": "unsupported",
        "refresh_token": "supported", "revoke": "supported", "scheduled_publish": "unsupported",
    }

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect,
                                            "scope": " ".join(scopes), "state": state, "code_challenge": challenge,
                                            "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent",
                                            "include_granted_scopes": "true"})

    @staticmethod
    def _grant(body, refresh_token=None):
        scopes = _scopes(body.get("scope"))
        return {"accessToken": json.dumps({"v": 1, "at": body["access_token"], "scope": scopes, "location": None}),
                "refreshToken": body.get("refresh_token") or refresh_token, "expiresIn": body.get("expires_in"), "scopes": scopes}

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, form={"code": code, "client_id": self.client_id, "client_secret": self.client_secret,
                                                                  "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier}), "access_token")
        return self._grant(body)

    def refresh(self, refresh_token):
        body = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret,
                                                                  "refresh_token": refresh_token, "grant_type": "refresh_token"}), "access_token")
        return self._grant(body, refresh_token)

    def _get(self, token, url):
        return self.transport("GET", url, headers={"Authorization": "Bearer " + _session(token)["at"]})

    def identity(self, access_token):
        body = self._ok(self._get(access_token, self.USERINFO), "sub")
        return {"providerAccountId": str(body["sub"]), "handle": str(body.get("name") or body["sub"]), "accountType": "business_manager",
                "pictureUrl": body.get("picture")}

    def inspect_scopes(self, access_token, expected_account_id=None):
        session = _session(access_token)
        body = self._ok(self.transport("GET", self.TOKENINFO + "?" + urlencode({"access_token": session["at"]})))
        if body.get("aud") != self.client_id:
            return None
        return _scopes(body.get("scope"))

    def destinations(self, access_token):
        session = _session(access_token)
        accounts_body = self._ok(self._get(access_token, self.ACCOUNTS), "accounts")
        accounts = accounts_body["accounts"][:20] if isinstance(accounts_body.get("accounts"), list) else []
        locations = []
        for account in accounts:
            name = account.get("name") if isinstance(account, dict) else None
            if not isinstance(name, str) or not re.fullmatch(r"accounts/[0-9]+", name):
                continue
            url = self.LOCATIONS + "/" + quote(name, safe="/") + "/locations?" + urlencode({"readMask": "name,title,storeCode,metadata", "pageSize": "100"})
            response = self._get(access_token, url)
            body = response.get("body") if response.get("status") == 200 and isinstance(response.get("body"), dict) else {}
            for location in body.get("locations") or []:
                resource = location.get("name") if isinstance(location, dict) else None
                if isinstance(resource, str) and re.fullmatch(r"locations/[0-9]+", resource):
                    full = name + "/" + resource
                    locations.append({"id": full, "name": str(location.get("title") or location.get("storeCode") or full),
                                      "kind": "location", "selected": full == session.get("location")})
        return locations[:500]

    @staticmethod
    def valid_destination_id(value):
        return isinstance(value, str) and re.fullmatch(r"accounts/[0-9]+/locations/[0-9]+", value) is not None

    def with_destination(self, access_token, destination_id):
        if not self.valid_destination_id(destination_id):
            raise AlphaError("Choose a Business Profile location.", 400)
        if destination_id not in {item["id"] for item in self.destinations(access_token)}:
            raise AlphaError("Choose a Business Profile location you can manage.", 409)
        return json.dumps({**_session(access_token), "location": destination_id})

    def revoke(self, token):
        response = self.transport("POST", self.REVOKE, form={"token": _session(token)["at"]})
        return response.get("status") in (200, 204)

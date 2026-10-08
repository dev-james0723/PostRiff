"""OAuth provider adapters for the selected launch connectors (connector-audit.md, D12).

LinkedIn member posting, Threads, Instagram professional, plus the Wave 1 hosted channels of the
Rafii Hosted Channels Plan: Bluesky (atproto_oauth.py), X, Mastodon, Discord and Telegram
(social_connectors.py). Each adapter only builds requests and parses responses through an injected
transport; nothing is mounted unless its credentials exist in server secrets, and `production_reviewed`
is true only when the operator declares the provider's review gate passed.
"""
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from postriff_alpha.domain import AlphaError

from .provider_base import GRAPH_VERSION  # noqa: E402  (re-exported; shared with the Wave 3 Meta adapter)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise AlphaError("Provider redirects are not allowed.", 502)


def http_transport(method, url, headers=None, form=None, body=None, data=None, response_format="json"):
    """Bounded HTTPS transport: 20 s timeout, no redirects, 256 KB response cap; JSON, form or raw bytes.

    `data` is an upload body sent as-is; the caller names its Content-Type in `headers`."""
    if not url.startswith("https://"):
        raise AlphaError("Provider requests must use HTTPS.", 502)
    if response_format not in ('json','csv'): raise AlphaError('Unsupported provider response format.',500)
    response_limit = 512_000 if response_format == 'csv' else 262144
    raw_upload = data
    data = raw_upload if raw_upload is not None else urlencode(form).encode() if form is not None else (json.dumps(body).encode() if body is not None else None)
    request_headers = {"Accept": "application/json", **(headers or {})}
    if raw_upload is not None:
        if not any(key.lower() == "content-type" for key in request_headers):
            raise AlphaError("An upload needs a content type.", 500)
    elif form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=20) as response:
            raw = response.read(response_limit+1)
            status, response_headers = response.status, dict(response.headers)
    except HTTPError as error:
        with error:
            raw, status, response_headers = error.read(response_limit+1), error.code, dict(error.headers)
    except (URLError, TimeoutError, OSError) as error:
        raise AlphaError("The provider is temporarily unreachable.", 503) from error
    if len(raw) > response_limit:
        raise AlphaError("Provider response limit exceeded.", 502)
    if response_format == 'csv' and status == 200:
        import csv, hashlib, io
        try:
            reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')))
            columns = next(reader, [])
            if not columns or len(columns) > 200 or len(set(columns)) != len(columns): raise ValueError('Invalid CSV columns')
            rows = []
            for row in reader:
                if len(row) != len(columns): raise ValueError('Invalid CSV row')
                rows.append(row)
                if len(rows) > 500: break
            parsed = {'columns':columns, 'rows':rows[:500], 'truncated':len(rows)>500, 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
        except (UnicodeError,ValueError,csv.Error) as error: raise AlphaError('Provider report is not valid bounded CSV.',502) from error
        return {'status':status, 'headers':{k.lower():v for k,v in response_headers.items()}, 'body':parsed}
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = {"raw": raw[:2000].decode("utf-8", "replace")}
    return {"status": status, "headers": {k.lower(): v for k, v in response_headers.items()}, "body": parsed}


from .provider_base import OAuthProvider, _credential_shape  # noqa: E402,F401  (re-exported)


class LinkedInProvider(OAuthProvider):
    id, platform, capability_version = "linkedin", "LinkedIn", 4
    AUTH = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
    REVOKE = "https://www.linkedin.com/oauth/v2/revoke"
    USERINFO = "https://api.linkedin.com/v2/userinfo"
    # Member posting is self-serve ("Share on LinkedIn"); org/analytics/comments need the Community Management API, not held.
    SCOPES = {"identity": ["openid", "profile"], "publish": ["openid", "profile", "w_member_social"], "schedule": ["openid", "profile", "w_member_social"]}
    account_requirement = "LinkedIn member profile."
    read_scope, publish_scope = "r_member_social", "w_member_social"
    publish_required = frozenset({"w_member_social"})
    server_schedule = True
    EXPLAIN = {"publish": "Rafii will publish posts to your LinkedIn member profile only when you approve each exact post. Organization pages and analytics are not requested."}

    history_approved = False
    has_destinations = True
    destination_scope, destination_label = "post", "Member or Organization"
    SCOPES = {**SCOPES,
              "organization_identity": ["openid", "profile", "r_organization_admin"],
              "organization_posts_read": ["openid", "profile", "r_organization_admin", "r_organization_social"],
              "organization_publish": ["openid", "profile", "w_organization_social", "rw_organization_admin"],
              "organization_comments_read": ["openid", "profile", "r_organization_admin", "r_organization_social_feed"], "organization_reply": ["openid", "profile", "r_organization_admin", "w_organization_social_feed"],
              "organization_analytics": ["openid", "profile", "rw_organization_admin"],
              'organization_video_analytics': ['openid','profile','r_organization_admin','r_organization_social'],
              "analytics": ["openid", "profile", "r_member_postAnalytics"],
              "comments_read": ["openid", "profile", "r_member_social_feed"],
              "reply": ["openid", "profile", "w_member_social_feed"]}

    def member_publishing_approved(self):
        """Verified Share product access for this deployment, never Community Management.

        The operator supplies evidence; a customer still needs a real write grant
        and must approve each exact operation. Preview evidence cannot enable production.
        """
        return self.member_publishing_status()['approved']

    def member_publishing_status(self):
        """Actionable presence/configuration diagnostics; never credential values."""
        from urllib.parse import urlparse
        environment = getattr(self, 'deployment_environment', None)
        runtime = {'runtimeEnvironmentVerified': environment in ('preview', 'production'),
                   'runtimeEnvironment': environment if environment in ('preview', 'production') else None}
        def blocked(code, action):
            return {'approved': False, 'code': code, **runtime,
                    'message': 'Rafii member publishing access is not verified for this deployment. ' + action}
        approvals = getattr(self, 'official_approvals', {})
        record = approvals.get('share_on_linkedin') if isinstance(approvals, dict) else None
        if not isinstance(record, dict):
            return blocked('share_evidence_missing', 'The operator must record the existing Share on LinkedIn product evidence; customers do not need a developer app.')
        origin = getattr(self, 'public_origin', '')
        try:
            parsed = urlparse(origin)
        except (ValueError, TypeError):
            return blocked('callback_origin_invalid', 'The operator must configure the fixed public HTTPS origin.')
        if environment not in ('preview', 'production'):
            return blocked('runtime_environment_unverified', 'The operator must verify VERCEL_ENV in the backend runtime.')
        if record.get('environment') != environment:
            return blocked('environment_mismatch', 'The operator must bind product evidence to this deployment environment.')
        if parsed.scheme != 'https' or not parsed.hostname or any((parsed.path, parsed.query, parsed.fragment, parsed.username, parsed.password)):
            return blocked('callback_origin_invalid', 'The operator must configure the fixed public HTTPS origin.')
        if record.get('callbackUri') != origin + '/api/oauth/linkedin/callback':
            return blocked('callback_mismatch', 'The operator must reconcile the registered callback with the exact callback generated by this deployment.')
        if record.get('appId') != self.client_id:
            return blocked('oauth_client_mismatch', 'The operator must verify that product evidence belongs to the configured LinkedIn OAuth client.')
        if record.get('state') != 'approved' or record.get('audience') != 'external':
            return blocked('external_access_unverified', 'The operator must verify public external-user access for the Share on LinkedIn product.')
        if not isinstance(record.get('evidenceRef'), str) or not record['evidenceRef'].strip():
            return blocked('evidence_reference_missing', 'The operator must retain the redacted provider-console evidence reference.')
        approved = record.get('approvedScopes')
        if not isinstance(approved, list) or not all(isinstance(scope, str) for scope in approved) or not self.publish_required.issubset(approved):
            return blocked('share_scope_unverified', 'The operator must verify w_member_social for this app; organization and read permissions are separate.')
        return {'approved': True, 'code': 'share_access_verified', **runtime,
                'message': 'Share on LinkedIn product evidence matches this deployment. Account consent and exact-operation approval remain required.'}

    def capability_scopes(self, capability):
        if capability == "posts_read":
            return ["openid", "profile", "r_member_social"] if self.history_approved else []
        scopes = super().capability_scopes(capability)
        restricted = set(scopes) - {"openid", "profile", "w_member_social"}
        return scopes if restricted.issubset(getattr(self, "approved_scopes", ())) else []

    def api(self, token, method, path, **kwargs):
        from .official_publishers import OfficialPublishers
        return self.transport(method, "https://api.linkedin.com/rest" + path,
                              headers=OfficialPublishers.linkedin_headers(token), **kwargs)

    def destinations(self, token):
        member = self.identity(token)
        items = [{"id": member["providerAccountId"], "name": member["handle"], "kind": "member", "selected": False}]
        scopes = set(self.inspect_scopes(token, member["providerAccountId"]) or [])
        if not scopes.intersection({"r_organization_admin", "rw_organization_admin"}):
            return items
        for start in range(0, 1000, 100):
            response = self.api(token, "GET", "/organizationAcls?" + urlencode({"q": "roleAssignee", "state": "APPROVED", "start": start, "count": 100}))
            body = self._ok(response)
            elements = body.get("elements") or []
            for item in elements:
                urn = item.get("organization")
                if item.get("state") != "APPROVED" or not isinstance(urn, str) or not re.fullmatch(r"urn:li:organization:\d+", urn): continue
                identity = self._ok(self.api(token, "GET", "/organizations/"+urn.rsplit(":", 1)[1]))
                items.append({"id": urn, "name": identity.get("localizedName") or urn,
                              "kind": "organization", "role": item.get("role"), "selected": False})
            if len(elements) < 100: break
        return list({item["id"]: item for item in items}.values())

    def organization_authorized(self, token, member, organization, action):
        if not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]+", str(member)) or not re.fullmatch(r"urn:li:organization:\d+", str(organization)) or action not in ("CREATE", "UPDATE", "DELETE", "READ", 'SHARE_ANALYTICS', 'FOLLOWER_ANALYTICS', 'PAGE_ANALYTICS'):
            return False
        # Permission-based authorization, refreshed for the exact operation. Role
        # discovery is account selection, not proof that the selected action is allowed.
        action_type = {"CREATE": "ORGANIC_SHARE_CREATE", "UPDATE": "ORGANIC_SHARE_EDIT", "DELETE": "ORGANIC_SHARE_DELETE", "READ": "ORGANIC_SHARE_VIEW_AS_AUTHOR", 'SHARE_ANALYTICS':'UPDATE_ANALYTICS_READ', 'FOLLOWER_ANALYTICS':'FOLLOWER_ANALYTICS_READ', 'PAGE_ANALYTICS':'VISITOR_ANALYTICS_READ'}[action]
        family = 'organizationAnalyticsAuthorizationAction' if action.endswith('ANALYTICS') else 'organizationContentAuthorizationAction'
        key = f"(impersonator:{quote(member, safe='')},organization:{quote(organization, safe='')},action:({family}:(actionType:{action_type})))"
        response = self.api(token, "GET", "/organizationAuthorizations/" + key)
        return response.get("status") == 200 and response.get("body", {}).get("status", {}).get("com.linkedin.organization.Approved") == {}

    def organization_feed_authorized(self, token, member, organization, *, write=False):
        """Refresh the documented feed roles, independently of content authorization.

        r_organization_admin enables the role finder. Never require the broader
        rw_organization_admin/ORGANIC_SHARE_CREATE for a feed comment or reaction.
        """
        if not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]+", str(member)) or not re.fullmatch(r"urn:li:organization:\d+", str(organization)):
            return False
        roles = {"ADMINISTRATOR", "DIRECT_SPONSORED_CONTENT_POSTER"}
        if write: roles.add("RECRUITING_POSTER")
        for start in range(0, 1000, 100):
            body = self._ok(self.api(token, "GET", "/organizationAcls?"+urlencode({"q":"roleAssignee", "state":"APPROVED", "start":start, "count":100})))
            elements = body.get("elements") or []
            if any(item.get("organization") == organization and item.get("state") == "APPROVED" and item.get("role") in roles and item.get("roleAssignee", member) == member for item in elements):
                return True
            if len(elements) < 100: break
        return False

    def explain(self, capability):
        if capability == "identity":
            return "Connect your LinkedIn member identity only. This does not grant publishing or historical-post access."
        if capability == "posts_read":
            return "Read your own LinkedIn posts for a sample picker. You separately choose and approve samples for voice analysis. This requires LinkedIn's restricted r_member_social approval; no publishing permission is requested."
        return super().explain(capability)

    def authorize_url(self, redirect, state, challenge, scopes):
        # LinkedIn's documented flow has no PKCE parameter; the verifier still binds our transaction server-side.
        return self.AUTH + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect, "state": state, "scope": " ".join(scopes)})

    def exchange(self, code, verifier, redirect):
        body = self._ok(self.transport("POST", self.TOKEN, form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": self.client_id, "client_secret": self.client_secret}), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token"), "expiresIn": body.get("expires_in"), "scopes": re.split(r'[\s,]+', body['scope'].strip()) if isinstance(body.get('scope'), str) and body['scope'].strip() else None}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.USERINFO, headers={"Authorization": "Bearer " + access_token}), "sub")
        # `picture` is part of the OpenID `profile` claims already requested; previews draw it (account_pictures.py).
        return {"providerAccountId": "urn:li:person:" + str(body["sub"]), "handle": body.get("name") or str(body["sub"]), "accountType": "member", "pictureUrl": body.get("picture")}

    def inspect_scopes(self, access_token, expected_account_id):
        # Identity is independently checked by the caller. Introspection binds token to this app.
        body = self._ok(self.transport("POST", "https://www.linkedin.com/oauth/v2/introspectToken", form={"client_id": self.client_id, "client_secret": self.client_secret, "token": access_token}))
        if body.get("active") is not True or body.get("client_id") != self.client_id or not isinstance(body.get("scope"), str):
            return None
        return list(dict.fromkeys(scope for scope in re.split(r"[,\s]+", body["scope"].strip()) if scope))

    def refresh(self, refresh_token):
        # Refresh tokens are issued only to approved partners; otherwise the customer re-authorizes every 60 days.
        body = self._ok(self.transport("POST", self.TOKEN, form={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id, "client_secret": self.client_secret}), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token", refresh_token), "expiresIn": body.get("expires_in")}

    def revoke(self, token):
        return self.transport("POST", self.REVOKE, form={"client_id": self.client_id, "client_secret": self.client_secret, "token": token}).get("status") == 200


class ThreadsProvider(OAuthProvider):
    id, platform, capability_version = "threads", "Threads", 1
    AUTH = "https://threads.net/oauth/authorize"
    TOKEN = "https://graph.threads.net/oauth/access_token"
    LONG_LIVED = "https://graph.threads.net/access_token"
    REFRESH = "https://graph.threads.net/refresh_access_token"
    from .official_social import THREADS_VERSION
    ME = f"https://graph.threads.net/{THREADS_VERSION}/me"
    account_requirement = "Threads profile."
    publish_required = frozenset({"threads_basic", "threads_content_publish"})
    SCOPES = {"identity": ["threads_basic"], "publish": ["threads_basic", "threads_content_publish"], "schedule": ["threads_basic", "threads_content_publish"], "analytics": ["threads_basic", "threads_manage_insights"], "comments_read": ["threads_basic", "threads_read_replies"], "reply": ["threads_basic", "threads_manage_replies"]}
    EXPLAIN = {"publish": "Rafii will create Threads posts on this profile only when you approve each exact post.", "analytics": "Allows Rafii to read available views, likes, replies, reposts and quotes for this account's own posts. When History Import is available, you can separately confirm reading up to 90 days, 300 posts and 12 pages of historical metadata and analytics. Rafii retains post IDs, dates, media types, links and caption length, never caption text or caption hashes. Disconnecting removes imported metadata and its analytics; delayed purges retry and block further imports. Analytics permission alone does not start an import.", "comments_read": "Rafii will read replies to your posts.", "reply": "Rafii will post replies only after you approve the exact text."}
    SCOPES = {**SCOPES, "posts_read": ["threads_basic"],
              "reply": ["threads_basic", "threads_content_publish"],
              "moderate": ["threads_basic", "threads_manage_replies"],
              "delete": ["threads_basic", "threads_delete"],
              "mentions": ["threads_basic", "threads_manage_mentions"]}
    SCOPES = {**SCOPES, 'location':['threads_basic','threads_location_tagging']}

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "scope": ",".join(scopes), "response_type": "code", "state": state})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}), "access_token", "user_id")
        long_lived = self._ok(self.transport("GET", self.LONG_LIVED + "?" + urlencode({"grant_type": "th_exchange_token", "client_secret": self.client_secret, "access_token": short["access_token"]})), "access_token")
        # Long-lived tokens (60 days) refresh with themselves; we store the same value as the refresh secret.
        return {"accessToken": long_lived["access_token"], "refreshToken": long_lived["access_token"], "expiresIn": long_lived.get("expires_in", 5184000), "scopes": None, "userId": str(short["user_id"])}

    def inspect_scopes(self, access_token, expected_account=None):
        # Meta's official Threads Postman collection documents /debug_token with OAuth bearer auth.
        response = self.transport('GET', 'https://graph.threads.net/debug_token?' + urlencode({'input_token':access_token}), headers={'Authorization':'Bearer ' + access_token})
        data = response.get('body', {}).get('data', {})
        scopes = data.get('scopes') if isinstance(data, dict) else None
        if response.get('status') != 200 or data.get('is_valid') is not True or str(data.get('app_id')) != str(self.client_id) or not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            return None
        if expected_account and str(data.get('user_id')) != str(expected_account):
            return None
        return sorted(set(scopes))

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"fields": "id,username,threads_profile_picture_url", "access_token": access_token})), "id")
        return {"providerAccountId": str(body["id"]), "handle": "@" + body["username"] if body.get("username") else str(body["id"]), "accountType": "profile", "pictureUrl": body.get("threads_profile_picture_url")}

    def refresh(self, refresh_token):
        body = self._ok(self.transport("GET", self.REFRESH + "?" + urlencode({"grant_type": "th_refresh_token", "access_token": refresh_token})), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body["access_token"], "expiresIn": body.get("expires_in", 5184000)}


class InstagramProvider(OAuthProvider):
    id, platform, capability_version = "instagram", "Instagram", 1
    AUTH = "https://www.instagram.com/oauth/authorize"
    TOKEN = "https://api.instagram.com/oauth/access_token"
    LONG_LIVED = "https://graph.instagram.com/access_token"
    REFRESH = "https://graph.instagram.com/refresh_access_token"
    ME = f"https://graph.instagram.com/{GRAPH_VERSION}/me"
    account_requirement = "Instagram Creator or Business account. No Facebook Page required."
    read_scope, publish_scope = "instagram_business_basic", "instagram_business_content_publish"
    publish_required = frozenset({"instagram_business_basic", "instagram_business_content_publish"})
    # Meta Standard Access can legitimately grant these permissions to professional accounts
    # owned/managed by app-role users before Advanced Access is approved for the public. A
    # live grant is therefore account-scoped execution evidence; it must never be promoted
    # into provider-wide "productionReviewed" status.
    account_scoped_direct = True
    # Instagram has no native "publish later" endpoint; Rafii's own queue can hold an
    # approved manifest and call the normal Content Publishing API at the scheduled time.
    server_schedule = True
    SCOPES = {"identity": ["instagram_business_basic"], "publish": ["instagram_business_basic", "instagram_business_content_publish"], "schedule": ["instagram_business_basic", "instagram_business_content_publish"], "analytics": ["instagram_business_basic", "instagram_business_manage_insights"], "comments_read": ["instagram_business_basic", "instagram_business_manage_comments"], "reply": ["instagram_business_basic", "instagram_business_manage_comments"]}
    EXPLAIN = {"publish": "Rafii will publish image posts to this professional account only when you approve each exact post (limit 100 per 24 hours).", "analytics": "Allows Rafii to read available reach, views, likes, comments, saves and shares for this account's own posts. When History Import is available, you can separately confirm reading up to 90 days, 300 posts and 12 pages of historical metadata and analytics. Rafii retains post IDs, dates, media types, links and caption length, never caption text or caption hashes. Disconnecting removes imported metadata and its analytics; delayed purges retry and block further imports. Analytics permission alone does not start an import.", "comments_read": "Rafii will read comments on your posts.", "reply": "Rafii will reply only after you approve the exact text."}
    SCOPES = {**SCOPES, "moderate": ["instagram_business_basic", "instagram_business_manage_comments"],
              "messaging": ["instagram_business_basic", "instagram_business_manage_messages"]}

    def capability_scopes(self, capability):
        if capability == "posts_read":
            return ["instagram_business_basic"]
        if capability == 'analytics':
            from .official_social import CATALOG
            if CATALOG['instagram']['insights'].support != 'documented': return []
        return super().capability_scopes(capability)

    def explain(self, capability):
        if capability in ("identity", "posts_read"):
            return "Connect your Instagram Creator or Business account and read its profile and media. No Facebook Page or publishing permission is requested. Selecting samples and allowing AI processing are separate choices."
        return super().explain(capability)

    def verify_read_access(self, access_token, expected_account_id):
        """Prove basic media read access, not undocumented publish/insight scopes.

        Instagram Login is not Facebook Login: do not invent a Facebook app-token
        introspection call. An authenticated account match and a successful bounded
        media read prove only instagram_business_basic. Never infer write permissions.
        """
        from .social_history import fetch_page
        identity = self.identity(access_token)
        if identity['providerAccountId'] != expected_account_id:
            raise AlphaError("The connected Instagram account changed. Reconnect it.", 409)
        fetch_page(self, access_token, expected_account_id, limit=1)
        return ['instagram_business_basic']

    def authorize_url(self, redirect, state, challenge, scopes):
        return self.AUTH + "?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect, "scope": ",".join(scopes), "response_type": "code", "state": state})

    def exchange(self, code, verifier, redirect):
        short = self._ok(self.transport("POST", self.TOKEN, form={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}), "access_token", "user_id")
        long_lived = self._ok(self.transport("GET", self.LONG_LIVED + "?" + urlencode({"grant_type": "ig_exchange_token", "client_secret": self.client_secret, "access_token": short["access_token"]})), "access_token")
        return {"accessToken": long_lived["access_token"], "refreshToken": long_lived["access_token"], "expiresIn": long_lived.get("expires_in", 5184000), "scopes": short.get("permissions") if isinstance(short.get("permissions"), list) else None, "userId": str(short["user_id"])}

    def identity(self, access_token):
        body = self._ok(self.transport("GET", self.ME + "?" + urlencode({"fields": "id,username,account_type,profile_picture_url", "access_token": access_token})), "id")
        return {"providerAccountId": str(body["id"]), "handle": "@" + body["username"] if body.get("username") else str(body["id"]), "accountType": (body.get("account_type") or "professional").lower(), "pictureUrl": body.get("profile_picture_url")}

    def refresh(self, refresh_token):
        body = self._ok(self.transport("GET", self.REFRESH + "?" + urlencode({"grant_type": "ig_refresh_token", "access_token": refresh_token})), "access_token")
        return {"accessToken": body["access_token"], "refreshToken": body["access_token"], "expiresIn": body.get("expires_in", 5184000)}


from .atproto_oauth import BlueskyProvider  # noqa: E402
from .social_connectors import DiscordProvider, MastodonProvider, TelegramConnector, XProvider  # noqa: E402
from .wave3_connectors import FacebookPagesProvider, PinterestProvider, TikTokProvider, YouTubeProvider  # noqa: E402
from .wave4_connectors import (BilibiliProvider, DouyinProvider, GoogleBusinessProfileProvider,
                               KuaishouProvider, WeiboProvider)  # noqa: E402
from .wave4b_connectors import LineOfficialAccountProvider, RedditProvider, ZhihuProvider  # noqa: E402
from .wave4c_connectors import PixelfedProvider, XiaohongshuProvider  # noqa: E402

ADAPTERS = {"linkedin": LinkedInProvider, "threads": ThreadsProvider, "instagram": InstagramProvider,
            "bluesky": BlueskyProvider, "mastodon": MastodonProvider, "telegram": TelegramConnector,
            "discord": DiscordProvider, "x": XProvider,
            "facebook": FacebookPagesProvider, "youtube": YouTubeProvider, "tiktok": TikTokProvider, "pinterest": PinterestProvider,
            "weibo": WeiboProvider, "bilibili": BilibiliProvider, "douyin": DouyinProvider, "kuaishou": KuaishouProvider,
            "google_business_profile": GoogleBusinessProfileProvider,
            "line_official_account": LineOfficialAccountProvider, "reddit": RedditProvider, "zhihu": ZhihuProvider,
            "pixelfed": PixelfedProvider, "xiaohongshu": XiaohongshuProvider}


def adapter_class_for_platform(platform):
    return next((cls for cls in ADAPTERS.values() if cls.platform == platform), None)


class ProviderRegistry(dict):
    """Adapters plus presence-only diagnostics, including when no adapter can mount."""
    def __init__(self):
        super().__init__()
        self.diagnostics = {}


def registry_from_environment(values, transport=None):
    """Only valid-shaped complete pairs mount. Review is an explicit operator declaration."""
    registry = ProviderRegistry()
    for provider_id, cls in ADAPTERS.items():
        prefix = f"POSTRIFF_OAUTH_{provider_id.upper()}_"
        adapter, diagnostic = cls.mount(values, transport=transport)
        registry.diagnostics[provider_id] = diagnostic
        if adapter is None:
            continue
        adapter.production_reviewed = str(values.get(prefix + "REVIEWED", "")).lower() == "true"
        adapter.publish_live_tested = str(values.get(prefix + "PUBLISH_LIVE_TESTED", "")).lower() == "true"
        adapter.publishing_permission = str(values.get(prefix + "PUBLISH_APPROVED", "")).lower() == "true"
        if provider_id == "pixelfed":
            adapter.qualified_instances = frozenset(re.split(r"[\s,]+", str(values.get(prefix + "QUALIFIED_INSTANCES", "")).strip())) - {""}
        webhook_configured = True
        if provider_id == "xiaohongshu":
            webhook_secret = values.get(prefix + "WEBHOOK_SECRET")
            adapter.webhook_secret = webhook_secret if _credential_shape(webhook_secret) and len(webhook_secret) >= 32 else None
            webhook_configured = bool(adapter.webhook_secret)
        enabled = str(values.get(prefix + "ENABLED", "")).lower() == "true"
        provider_verified = str(values.get(prefix + "VERIFIED", "")).lower() == "true"
        operator_disabled = str(values.get(prefix + "DISABLED", "")).lower() == "true"
        adapter.execution_enabled = (not operator_disabled
                                     and (enabled or not getattr(cls, "feature_flag_required", False))
                                     and (provider_verified or not getattr(cls, "provider_approval_required", False)))
        approved_scopes = [scope for scope in re.split(r"[\s,]+", str(values.get(prefix + "APPROVED_SCOPES", "")).strip()) if scope]
        adapter.approved_scopes = frozenset(approved_scopes)
        from .official_social import CATALOG
        def records(suffix):
            try:
                data = json.loads(values.get(prefix + suffix) or '{}')
                return data if isinstance(data, dict) else {}
            except (ValueError, TypeError):
                return {}
        adapter.official_approvals = records('PRODUCT_APPROVALS_JSON')
        if provider_id == 'linkedin':
            adapter.public_origin = values.get('POSTRIFF_PUBLIC_BASE_URL', '')
            adapter.deployment_environment = values.get('VERCEL_ENV')
        if provider_id in CATALOG:
            adapter.connection_review = records('CONNECTION_REVIEW_JSON')
        adapter.official_evidence = records('E2E_EVIDENCE_JSON')
        if provider_id == 'x':
            adapter.budget_enforced = True
            adapter.budget_policies = records('BUDGET_POLICIES_JSON')
            adapter.onboarding_budget_policy = records('ONBOARDING_BUDGET_JSON')
        if provider_id == 'facebook':
            configs = records('LOGIN_CONFIGS_JSON')
            adapter.login_configs = {tuple(sorted(key.split(','))): value for key, value in configs.items()
                                     if isinstance(key, str) and isinstance(value, str) and re.fullmatch(r'\d{5,25}', value)}
        if provider_id == 'tiktok':
            adapter.verified_media_domains = frozenset(str(values.get(prefix+'VERIFIED_MEDIA_DOMAINS', '')).split(',')) - {''}
        from .official_social import IMPLEMENTED
        adapter.official_implemented = tuple(IMPLEMENTED.get(provider_id, ()))
        adapter.official_social_enabled = str(values.get("POSTRIFF_OFFICIAL_SOCIAL_ENABLED", "")).lower() == "true"
        if provider_id == 'linkedin' and prefix + 'OFFICIAL_SOCIAL_ENABLED' in values:
            # An independently approved LinkedIn rollout need not enable every
            # provider behind the historical shared workflow switch.
            adapter.official_social_enabled = str(values[prefix + 'OFFICIAL_SOCIAL_ENABLED']).lower() == 'true'
        registry.diagnostics[provider_id].update({
            "featureFlagEnabled": enabled if getattr(cls, "feature_flag_required", False) else True,
            "operatorDisabled": operator_disabled,
            "providerAppCreated": str(values.get(prefix + "APP_CREATED", "")).lower() == "true",
            "providerVerified": provider_verified,
            "approvedScopes": sorted(set(approved_scopes)),
            "oauthLiveTest": str(values.get(prefix + "OAUTH_LIVE_TESTED", "")).lower() == "true",
            "tokenRefreshLiveTest": str(values.get(prefix + "REFRESH_LIVE_TESTED", "")).lower() == "true",
            "webhookVerified": (str(values.get(prefix + "WEBHOOK_VERIFIED", "")).lower() == "true"
                                and webhook_configured),
            "publishingPermission": adapter.publishing_permission,
            "publishLiveTest": adapter.publish_live_tested,
            "analyticsPermission": str(values.get(prefix + "ANALYTICS_APPROVED", "")).lower() == "true",
            "commentsPermission": str(values.get(prefix + "COMMENTS_APPROVED", "")).lower() == "true",
            "productionEnabled": enabled and adapter.production_reviewed and (provider_verified or not getattr(cls, "provider_approval_required", False)),
        })
        if provider_id == "linkedin":
            # Allows requesting the restricted scope, never substitutes for a real grant.
            adapter.history_approved = str(values.get(prefix + "HISTORY_APPROVED", "")).lower() == "true"
        registry[provider_id] = adapter
    return registry

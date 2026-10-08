"""Audited official capabilities, distinct from grants, implementation and live qualification.

This catalogue is also the release checklist. No operator's blanket REVIEWED flag,
successful identity request, or synthetic test can promote a row to READY.
"""
from dataclasses import dataclass, asdict, replace
import hashlib
import json
from pathlib import Path

AUDITED_AT = "2026-10-05"
LINKEDIN_VERSION = "202609"
THREADS_VERSION = "v1.0"  # Threads has its own version; never use Facebook's version.

SOURCES = {
    "linkedin": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-09",
    "linkedin_media": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api?view=li-lms-2026-09",
    "linkedin_org": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-authorizations/organization-authorizations?view=li-lms-2026-09",
    "linkedin_analytics": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?view=li-lms-2026-09",
    "threads": "https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api",
    "instagram": "https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login",
    "facebook": "https://developers.facebook.com/docs/pages-api/",
    "x": "https://docs.x.com/openapi.json",
    "x_cost": "https://docs.x.com/x-api/getting-started/pricing",
    "youtube": "https://developers.google.com/youtube/v3/docs/",
    "youtube_analytics": "https://developers.google.com/youtube/analytics/reference/reports/query",
    "tiktok": "https://developers.tiktok.com/doc/content-posting-api-get-started",
    "pinterest": "https://github.com/pinterest/api-description/blob/main/v5/openapi.yaml",
}


@dataclass(frozen=True)
class Feature:
    key: str
    method: str
    scopes: tuple
    product: str
    account: str
    permission_group: str = "identity"
    support: str = "documented"
    limitation: str = ""
    source: str = ""
    implemented: bool = False
    scheduling: str = "none"
    scope_alternatives: tuple = ()


CATALOG = {provider: {} for provider in ("linkedin", "threads", "instagram", "facebook", "x", "youtube", "tiktok", "pinterest")}


def _add(provider, keys, method, scopes, product, account, group="identity", **options):
    for key in keys.split():
        CATALOG[provider][key] = Feature(key, method, tuple(scopes.split()), product, account, group,
                                       source=SOURCES[provider], **options)


def _unsupported(provider, keys, reason):
    _add(provider, keys, "none", "", "none", "none", support="unsupported", limitation=reason)


_add("linkedin", "connected member_identity", "GET /v2/userinfo", "openid profile", "openid_connect", "member", implemented=True)
_add("linkedin", "organization_identity organization_roles", "GET /rest/organizationAcls; GET /rest/organizations/{id}", "r_organization_admin", "community_management", "authorized organization", "organization_identity")
_add("linkedin", "member_publish text link image video document multi_image poll edit delete schedule", "POST /rest/posts; POST|DELETE /rest/posts/{URN}; /rest/images|videos|documents", "w_member_social", "share_on_linkedin", "member", "publish", scheduling="rafii", limitation="ArticleContent is an external link card. Media must reach AVAILABLE before posting.")
_add("linkedin", "organization_publish", "POST /rest/posts; GET /rest/organizationAuthorizations", "w_organization_social rw_organization_admin", "community_management", "organization with current content authorization", "organization_publish", scheduling="rafii")
_add("linkedin", "organization_text organization_link organization_image organization_video organization_document organization_multi_image organization_poll organization_edit organization_delete organization_schedule", "POST|DELETE /rest/posts; /rest/images|videos|documents", "w_organization_social rw_organization_admin", "community_management", "organization with current content authorization", "organization_publish", scheduling="rafii")
_add("linkedin", "organization_comments_read organization_reactions", "GET /rest/socialActions/{URN}/comments; GET /rest/socialMetadata/{URN}", "r_organization_admin r_organization_social_feed", "community_management", "ADMINISTRATOR or DIRECT_SPONSORED_CONTENT_POSTER; fresh role finder", "organization_comments_read")
_add("linkedin", "organization_reply organization_reaction_write", "POST /rest/socialActions/{URN}/comments; POST|DELETE /rest/reactions", "r_organization_admin w_organization_social_feed", "community_management", "ADMINISTRATOR, DIRECT_SPONSORED_CONTENT_POSTER or RECRUITING_POSTER; fresh role finder", "organization_reply")
_add("linkedin", "organization_posts_read", "GET /rest/posts?q=author", "r_organization_admin r_organization_social", "community_management", "organization; fresh feed role", "organization_posts_read")
_unsupported("linkedin", "celebration_publish", "UNSUPPORTED BY OFFICIAL API: the official Celebration API permits fetching only; external creation returns 400.")
_add("linkedin", "historical_content_read", "GET /rest/posts?q=author", "r_member_social", "restricted_member_read", "member", "posts_read", limitation="BLOCKED — LINKEDIN APPROVAL unless specifically approved.")
_add("linkedin", "comments_read reactions", "GET /rest/socialActions/{URN}/comments; GET /rest/socialMetadata/{URN}", "r_member_social_feed", "community_management", "member", "comments_read")
_add("linkedin", "reply", "POST /rest/socialActions/{URN}/comments", "w_member_social_feed", "community_management", "member", "reply")
_add("linkedin", "reaction_write", "POST|DELETE /rest/reactions", "w_member_social_feed", "community_management", "member", "reply")
_add("linkedin", "analytics", "GET /rest/memberCreatorPostAnalytics", "r_member_postAnalytics", "community_management", "member", "analytics")
_add("linkedin", "organization_analytics organization_follower_analytics organization_page_analytics", "GET /rest/organizationalEntityShareStatistics|organizationalEntityFollowerStatistics|organizationPageStatistics", "rw_organization_admin", "community_management", "authorized organization", "organization_analytics")
_add("linkedin", "video_analytics", "GET /rest/videoAnalytics", "r_organization_admin r_organization_social", "community_management", "organization-owned video; fresh feed role", "organization_video_analytics")
_add("linkedin", "document_analytics", "not verified for organic documents", "", "community_management", "organization", support="audit_unavailable", limitation="Do not substitute advertising document metrics for organic analytics.")
_unsupported("linkedin", "article_newsletter_publish", "UNSUPPORTED BY OFFICIAL API: Posts ArticleContent shares a URL; it does not author a LinkedIn article/newsletter.")

_add("threads", "connected identity post_read", "GET /me; GET /{user}/threads; GET /{post}", "threads_basic", "threads", "Threads profile", implemented=True)
_add("threads", "publish text image video carousel reply quote repost poll text_attachment ghost_post schedule", "POST /{user}/threads; POST /{user}/threads_publish; POST /{post}/repost", "threads_basic threads_content_publish", "threads", "Threads profile", "publish", scheduling="rafii", limitation="Carousel 2–20 children in order. Publish parent only after processing.")
_add("threads", "replies_read", "GET /{post}/replies; GET /{post}/conversation", "threads_basic threads_read_replies", "threads", "Threads profile", "comments_read", implemented=True)
_add("threads", "reply_management", "POST /{reply}/manage_reply", "threads_basic threads_manage_replies", "threads", "owned conversation", "moderate")
_add("threads", "insights account_insights", "GET /{post|user}/insights", "threads_basic threads_manage_insights", "threads", "owned account/media", "analytics")
_add("threads", "delete", "DELETE /{post}", "threads_basic threads_delete", "threads", "owned post", "delete", limitation="Current permission requires app review; live contract still needs verification.")
_add("threads", "mentions", "GET /{user}/mentions", "threads_basic threads_manage_mentions", "threads", "Threads profile", "mentions")
_add('threads','gif_attachment spoilers reply_approvals','POST /{user}/threads','threads_basic threads_content_publish','threads','Threads profile','publish')
_add('threads','location','POST /{user}/threads?location_id','threads_basic threads_content_publish threads_location_tagging','threads','Threads profile','location')
IMPLEMENTED_EXTRA = {'threads': ['gif_attachment','spoilers','reply_approvals','location'], 'linkedin':['reaction_write','organization_reactions','organization_reaction_write']}
_unsupported("threads", "edit", "No currently verified official post-edit authoring endpoint; delete has a separate permission.")

_add("instagram", "connected identity media_read", "GET /me; GET /{user}/media", "instagram_business_basic", "instagram_login", "Creator or Business, no Facebook Page", implemented=True)
_add("instagram", "publish image carousel reel schedule", "POST /{user}/media; GET /{container}; POST /{user}/media_publish", "instagram_business_basic instagram_business_content_publish", "instagram_login", "professional account", "publish", scheduling="rafii")
_add("instagram", "story", "POST /{user}/media?media_type=STORIES", "instagram_business_basic instagram_business_content_publish", "instagram_login", "Business account", "publish", limitation="24-hour expiry; account/flow eligibility must be verified.")
_add("instagram", "comments_read reply moderation", "GET /{media}/comments; GET|POST /{comment}/replies; POST|DELETE /{comment}", "instagram_business_basic instagram_business_manage_comments", "instagram_login", "owned media", "comments_read")
_add("instagram", "insights account_insights reel_insights", "GET /{user|media}/insights", "instagram_business_basic instagram_business_manage_insights", "instagram_login", "owned professional account/media", "analytics", support="audit_unavailable", limitation="Selected Instagram Login Insights permission/metric contract needs accessible primary documentation; Meta returned 429. Engineering must not qualify this row as READY.")
_add("instagram", "messaging", "Messenger for Instagram /{user}/messages", "instagram_business_basic instagram_business_manage_messages", "instagram_messaging", "professional account", "messaging", limitation="Separate intentional enablement and review. No outbound automation added.")
_add("instagram", "edit delete", "contract not verified", "", "instagram_login", "professional account", support="audit_unavailable", limitation="Selected Login path write contract must be verified; SDK method existence alone is not authorization.")
_unsupported("instagram", "location_tag product_tag", "The selected Instagram Login official collection excludes tagging and ads.")

_add("facebook", "connected_person page_selected page_identity page_roles", "GET /me; GET /me/accounts?fields=id,name,tasks,access_token", "pages_show_list", "facebook_login_business", "managed Page", implemented=True)
_add("facebook", "page_publish text link photo multi_photo video reel story schedule edit delete", "POST /{page}/feed|photos|videos|video_reels|photo_stories|video_stories; POST|DELETE /{post}", "pages_show_list pages_read_engagement pages_manage_posts", "pages", "Page with CREATE_CONTENT", "publish", scheduling="per_format", limitation="Native feed scheduling; Reels use start/upload/status/finish. Current SDK confirms Story endpoints, but ordinary-account live eligibility remains unverified.")
_add("facebook", "comments", "GET /{post}/comments", "pages_show_list pages_read_engagement pages_read_user_content", "pages", "Page with MODERATE", "comments_read")
_add("facebook", "reactions", "GET /{post}/reactions", "pages_show_list pages_read_engagement", "pages", "selected authorized Page", "identity")
_add("facebook", "reply", "POST /{comment}/comments", "pages_show_list pages_read_engagement pages_manage_engagement", "pages", "Page with MODERATE", "reply")
_add("facebook", "moderation", "POST|DELETE /{comment}", "pages_show_list pages_read_engagement pages_manage_engagement", "pages", "Page with MODERATE", "moderate")
_add("facebook", "insights", "GET /{page|post|video}/insights", "pages_read_engagement read_insights", "pages", "Page with ANALYZE", "analytics", limitation="Version-specific metric availability must be revalidated; do not use removed metrics.")
_add("facebook", "messaging", "Messenger /{page}/messages", "pages_messaging", "messenger", "Page with MESSAGING", "messaging")
_unsupported("facebook", "personal_timeline_publish", "UNSUPPORTED BY OFFICIAL API for this app: personal timelines are not Page destinations.")

_add("x", "connected identity", "GET /2/users/me", "users.read tweet.read offline.access", "x_api", "X account", implemented=True)
_add("x", "publish text reply quote thread poll edit delete schedule", "POST /2/tweets; DELETE /2/tweets/{id}", "users.read tweet.read tweet.write offline.access", "x_api", "account with credits and endpoint access", "publish", scheduling="rafii", limitation="Editing depends on provider edit_controls. Calls are metered; an approved budget is required.")
CATALOG['x']['quote'] = replace(CATALOG['x']['quote'], product='x_enterprise', account='approved Enterprise API contract; actual member grant and cost budget', limitation='Official create-post documentation excludes quote_tweet_id from self-serve pay-per-use. BLOCKED — X ENTERPRISE ACCESS until verified.')
_add("x", "image multi_image gif video alt_text", "POST /2/media/upload; /2/media/upload/initialize; /{id}/append; /{id}/finalize; GET /2/media/upload; POST /2/media/metadata", "users.read tweet.read tweet.write media.write offline.access", "x_api", "account with media access and credits", "publish")
_add("x", "post_read conversation_read analytics", "GET /2/tweets/{id}; GET /2/tweets/search/recent", "users.read tweet.read offline.access", "x_api", "account with read credits", "analytics", limitation="Public metrics differ from owner organic/non-public metrics. Charge reads per returned resource.")
_add("x", "repost", "POST /2/users/{id}/retweets", "users.read tweet.read tweet.write", "x_api", "X account with credits", "publish")
_add("x", "messaging", "X Direct Messages API", "dm.read dm.write users.read tweet.read", "x_api_dm", "eligible X account", "messaging", limitation="Separate scope and intentional product enablement; no DM execution added.")
_add("x", "article_publish", "POST /2/articles/draft; POST /2/articles/{article_id}/publish", "users.read tweet.read tweet.write", "x_articles", "account/app with Article authoring endpoint access and credits", "publish", limitation="Present in the current official OpenAPI; actual account/tier eligibility and live access must be proven separately.")

_yt = "https://www.googleapis.com/auth/"
_add("youtube", "connected channel_identity media_read", "GET /youtube/v3/channels?mine=true; GET /youtube/v3/videos", _yt+"youtube.readonly", "youtube_data", "YouTube channel", implemented=True)
_add("youtube", "video short schedule disclosure localization", "POST /upload/youtube/v3/videos?uploadType=resumable", _yt+"youtube.upload", "youtube_data", "YouTube channel; public uploads require compliance audit", "publish", scheduling="native_publishAt", limitation="Shorts use videos.insert and current eligibility. Upload completion is not processing success.")
_add("youtube", "thumbnail captions playlists podcast comments_read reply moderation edit delete live_broadcast live_stream live_chat live_moderation", "YouTube Data API v3 / Live Streaming API", _yt+"youtube.force-ssl", "youtube_data", "channel; feature-specific live/thumbnail eligibility", "manage")
_add("youtube", "comments_read", "GET /youtube/v3/commentThreads; GET /youtube/v3/comments", _yt+"youtube.readonly", "youtube_data", "video with accessible comments", "comments_read")
_add("youtube", "thumbnail", "POST /upload/youtube/v3/thumbnails/set", _yt+"youtube.upload", "youtube_data", "channel with custom thumbnails enabled", "publish", scope_alternatives=((_yt+'youtube.force-ssl',),))
_add("youtube", "analytics shorts_analytics reporting", "GET youtubeanalytics.googleapis.com/v2/reports; youtubereporting.googleapis.com/v1/jobs", _yt+"yt-analytics.readonly", "youtube_analytics", "owned channel", "analytics")
_add("youtube", "reporting_download", "GET /v1/jobs/{job}/reports/{report}; GET /v1/media/{name}?alt=media", _yt+"yt-analytics.readonly", "youtube_analytics", "owned channel reporting job", "analytics", limitation="Bounded CSV up to 512 kB, 500 returned rows; full-file hash and period retained. Larger reports need a separate streaming export workflow.")
_add("youtube", "monetary_analytics", "GET youtubeanalytics.googleapis.com/v2/reports", _yt+"yt-analytics-monetary.readonly", "youtube_analytics_monetary", "eligible monetized channel", "monetary_analytics")
_add("youtube", "memberships", "GET /youtube/v3/members|membershipsLevels", _yt+"youtube.channel-memberships.creator", "youtube_memberships", "eligible channel with memberships", "memberships")
_unsupported("youtube", "community_posts", "UNSUPPORTED BY OFFICIAL API: no public Community Posts authoring method in YouTube Data API v3.")

_add("tiktok", "connected identity", "GET /v2/user/info/", "user.info.basic", "login_kit", "TikTok account", implemented=True)
_add("tiktok", "creator_info video direct_post photo privacy interactions processing schedule", "POST /v2/post/publish/creator_info/query/; /video/init/; /content/init/; /status/fetch/", "user.info.basic video.publish", "content_posting", "current creator capabilities and domain verification for URL transfer", "publish", scheduling="rafii", limitation="Public Publishing: BLOCKED — TIKTOK AUDIT until approved. Creator information is refreshed before every post.")
_add("tiktok", "upload_inbox", "POST /v2/post/publish/inbox/video/init/", "user.info.basic video.upload", "content_posting_upload", "TikTok account", "upload_inbox", limitation="SEND_TO_USER_INBOX is a handoff, not a published post.")
_add("tiktok", "photo_inbox", "POST /v2/post/publish/content/init/ post_mode=MEDIA_UPLOAD", "user.info.basic video.upload", "content_posting_upload", "verified media domain; TikTok inbox completion by creator", "upload_inbox", implemented=True)
_add("tiktok", "video_url_transfer cover_frame ai_disclosure", "POST /v2/post/publish/video/init/; /content/init/", "user.info.basic video.publish", "content_posting", "verified URL domain for PULL_FROM_URL; current creator capabilities", "publish", implemented=True, limitation="Video cover timestamp must be within approved duration. Photo AI disclosure is top-level; video disclosure belongs to post_info.")
_add("tiktok", "cancel_transfer", "POST /v2/post/publish/cancel/", "user.info.basic video.publish", "content_posting", "owned publish ID; still-cancellable URL transfer", "publish", implemented=True, limitation="Best-effort transfer cancellation, never deletion of a published post.")
CATALOG['tiktok']['cancel_transfer'] = replace(CATALOG['tiktok']['cancel_transfer'], scope_alternatives=(('user.info.basic','video.upload'),))
_add("tiktok", "media_read", "POST /v2/video/list/; /v2/video/query/", "user.info.basic video.list", "display_api", "owned account", "posts_read")
_unsupported("tiktok", "analytics comments_read reply edit delete", "No verified general public creator-management endpoint. Research API access does not qualify.")

_add("pinterest", "connected identity", "GET /v5/user_account", "user_accounts:read", "pinterest_v5", "Pinterest business account", implemented=True)
_add("pinterest", "boards sections", "GET|POST|PATCH|DELETE /v5/boards; /boards/{id}/sections", "boards:read boards:write", "pinterest_v5", "owned board; Standard for release", "boards")
_add("pinterest", "image video publish edit delete schedule", "POST /v5/media; GET /v5/media/{id}; POST|PATCH|DELETE /v5/pins", "boards:read pins:read pins:write", "pinterest_v5", "owned board; approved access tier", "publish", scheduling="rafii", limitation="Video media registration/upload/processing precedes Pin creation; ambiguous creates never retry automatically.")
_add("pinterest", "pin_read analytics video_analytics account_analytics", "GET /v5/pins/{id}; /pins/{id}/analytics; /user_account/analytics|analytics/top_video_pins", "pins:read user_accounts:read", "pinterest_v5", "owned Pins/business account", "analytics")
_add("pinterest", "trends", "GET /v5/trends/keywords/{region}/top/{trend_type}", "user_accounts:read", "pinterest_v5", "approved access tier", "trends")
_add("pinterest", "audience_insights", "GET /v5/ad_accounts/{id}/audience_insights", "ads:read", "pinterest_ads", "ad account", "audience_insights", limitation="Advertising/account eligibility; not assumed for an ordinary creator.")
_add("pinterest", "commerce", "GET /v5/catalogs|catalogs/product_groups|catalogs/feeds", "catalogs:read", "pinterest_commerce", "merchant/catalog eligibility", "commerce")
_add("pinterest", "commerce_write", "POST|PATCH|DELETE /v5/catalogs/feeds|catalogs/product_groups; POST /catalogs/feeds/{id}/ingest", "catalogs:read catalogs:write", "pinterest_commerce", "eligible RETAIL merchant", "commerce_write", limitation="Separately enabled; immutable native-action approvals. Credential-protected feeds, hotel/creative catalogs and item-batch mutation are outside the implemented retail feed flow.")
_add("pinterest", "product_tag", "POST /v5/pins/{id}/product_tags", "boards:read boards:write pins:read pins:write", "pinterest_commerce", "eligible merchant and product Pins; sandbox disabled", "product_tag")
_unsupported("pinterest", "comments_read reply", "UNSUPPORTED BY OFFICIAL API: engagement counts do not grant comment/reply management.")

# Engineering coverage is a code fact, never evidence of provider approval or
# ordinary-account E2E. Conditional commerce and messaging remain separate.
IMPLEMENTED = {
    'linkedin': 'connected member_identity organization_identity organization_roles member_publish organization_publish text link image multi_image video document poll edit delete schedule organization_text organization_link organization_image organization_multi_image organization_video organization_document organization_poll organization_edit organization_delete organization_schedule historical_content_read organization_posts_read comments_read organization_comments_read reply organization_reply reactions analytics organization_analytics organization_follower_analytics organization_page_analytics video_analytics'.split(),
    'threads': 'connected identity post_read publish text image video carousel reply quote repost poll text_attachment ghost_post schedule replies_read reply_management insights account_insights delete mentions'.split(),
    'instagram': 'connected identity media_read publish image carousel reel story schedule comments_read reply moderation insights account_insights reel_insights'.split(),
    'facebook': 'connected_person page_selected page_identity page_roles page_publish text link photo multi_photo video reel story schedule edit delete comments reply moderation reactions insights'.split(),
    'x': 'connected identity publish text reply quote thread poll edit delete schedule image multi_image gif video alt_text post_read conversation_read analytics repost article_publish'.split(),
    'youtube': 'connected channel_identity media_read video short schedule disclosure localization thumbnail captions playlists podcast comments_read reply moderation edit delete live_broadcast live_stream live_chat live_moderation analytics shorts_analytics reporting monetary_analytics memberships'.split(),
    'tiktok': 'connected identity creator_info video direct_post photo privacy interactions processing schedule upload_inbox media_read'.split(),
    'pinterest': 'connected identity boards sections image video publish edit delete schedule pin_read analytics video_analytics account_analytics trends audience_insights commerce product_tag'.split(),
}
IMPLEMENTED['pinterest'].append('commerce_write')
IMPLEMENTED['youtube'].append('reporting_download')
for pid, keys in IMPLEMENTED_EXTRA.items(): IMPLEMENTED[pid].extend(keys)


def implementation_revision():
    files = ("official_social.py", "official_publishers.py", "official_operations.py", "official_action_contracts.py", "official_media.py", "social_formats.py", "social_documents.py", "social_budget.py", "providers.py", "provider_base.py", "wave3_connectors.py", "social_connectors.py", "oauth.py", "hosted_worker.py", "hosted_social.py", "hosted_storage.py", "outcomes.py", "store.py", "publish_options.py", "hosted.py")
    root = Path(__file__).parent
    return hashlib.sha256(b"".join((root/f).read_bytes() for f in files if (root/f).exists())).hexdigest()


def capability_states(provider, channel=None, *, approvals=None, evidence=None, implemented=None, connection_approval=None, now=0):
    """Release qualification from six independent dimensions; secrets never enter this result.

    approvals/evidence are server-owned records, not submitted by a customer's browser.
    Evidence is tied to account, destination, exact grant, implementation and app.
    connection_approval is minimum-scope evidence validated against the adapter
    and callback by public_connection_review; it cannot approve other products.
    """
    channel, approvals, evidence = channel or {}, approvals or {}, evidence or {}
    implemented = set(IMPLEMENTED.get(provider, ()) if implemented is None else implemented)
    scopes = set(channel.get("scopes") or [])
    connection_approval = connection_approval or {}
    connected = (channel.get("evidenceSource") == "live_provider" and not channel.get("revoked")
                 and bool(channel.get("providerAccountId")) and channel.get("identityVerified") is True
                 and (channel.get("nonExpiring") is True or (channel.get("expiresAt") or 0) > now))
    revision = implementation_revision()
    grant_hash = hashlib.sha256(json.dumps(sorted(scopes)).encode()).hexdigest()
    result = {}
    for key, feature in CATALOG[provider].items():
        proof = evidence.get(key) or {}
        approval = approvals.get(feature.product) or {}
        app_approved = approval.get("state") == "approved" and bool(approval.get("evidenceRef"))
        member_identity = provider == "linkedin" and key in ("connected", "member_identity")
        approved_connection_scopes = connection_approval.get("approvedScopes")
        if (member_identity and not app_approved and connection_approval.get("state") == "approved"
                and connection_approval.get("audience") == "external"
                and isinstance(connection_approval.get("appId"), str) and connection_approval["appId"].strip()
                and isinstance(connection_approval.get("evidenceRef"), str) and connection_approval["evidenceRef"].strip()
                and isinstance(approved_connection_scopes, list)
                and all(isinstance(scope, str) for scope in approved_connection_scopes)
                and set(feature.scopes).issubset(approved_connection_scopes)):
            approval, app_approved = connection_approval, True
        # A verified /userinfo response proves member identity, not organization
        # eligibility, publication approval or a complete live acceptance test.
        eligible = (channel.get("eligibility", {}).get(key) is True
                    or (member_identity and connected and channel.get("accountType") == "member"))
        built = feature.implemented or key in implemented
        live = (proof.get("state") == "passed" and proof.get("kind") == "live_api"
                and proof.get("accountId") == channel.get("providerAccountId")
                and proof.get("destinationId") == channel.get("destinationId")
                and proof.get("implementationRevision") == revision and proof.get("grantHash") == grant_hash
                and proof.get("appId") == approval.get("appId") and bool(proof.get("evidenceRef"))
                and isinstance(proof.get("at"), (int, float)) and 0 <= now-proof["at"] <= 30*86400)
        granted = connected and any(set(required).issubset(scopes) for required in (feature.scopes, *feature.scope_alternatives))
        blockers = []
        if feature.support != "documented":
            blockers.append("UNSUPPORTED BY OFFICIAL API" if feature.support == "unsupported" else "OFFICIAL AUDIT UNAVAILABLE")
        if not app_approved:
            blockers.append("BLOCKED — LINKEDIN APPROVAL" if provider == "linkedin" else "APP APPROVAL NOT VERIFIED")
        if not granted: blockers.append("ACTUAL GRANT MISSING OR EXPIRED")
        if not eligible: blockers.append("ACCOUNT/DESTINATION ELIGIBILITY NOT VERIFIED")
        if not built: blockers.append("IMPLEMENTATION PENDING")
        if not live: blockers.append("LIVE E2E NOT PROVEN")
        result[key] = {**asdict(feature), "implemented": built, "officialSupport": feature.support,
                       "appApproved": app_approved, "granted": granted, "eligible": eligible,
                       "liveE2E": live, "state": "READY" if not blockers else "BLOCKED", "blockers": blockers,
                       "auditDate": AUDITED_AT, "implementationRevision": revision}
    return result

"""Can PostRiff really publish this post here, now? (orchestration: never fake capability)

Raffi says a post "will publish" only when every link of the chain exists: a hosted publisher for the platform, a
provider that is production-reviewed and not paused, live transport switched on for this deployment, a connected
account whose publish permission was verified, and a plan that can publish. Anything missing is named in plain words,
the draft is still prepared, and the step that cannot run is blocked instead of pretending.

The same answer feeds the chat confirmation (at creation), the run's items (at generation) and the commit gate
(right before publishing, where billing is checked with live SQL).
"""
from __future__ import annotations

# Platforms with a hosted publisher (hosted_social.HostedSocial) and their provider ids.
HOSTED_PUBLISHERS = {"LinkedIn": "linkedin", "Threads": "threads", "Instagram": "instagram",
                     "Bluesky": "bluesky", "Mastodon": "mastodon", "Telegram": "telegram", "Discord": "discord", "X": "x",
                     "Facebook": "facebook", "YouTube": "youtube", "TikTok": "tiktok", "Pinterest": "pinterest"}
NO_ROUTE = {
    "Xiaohongshu": "Xiaohongshu has no publishing connection in Rafii, so the Xiaohongshu version is prepared as a draft for you to post.",
}


def _no_route(platform: str) -> str:
    return NO_ROUTE.get(platform) or f"Rafii can't publish to {platform} yet, so that version is prepared as a draft for you to post."


def publish_route(state: dict, destination: dict, *, providers: dict | None = None, live: bool = False, can_publish: bool | None = None,
                  channel_state=None) -> dict:
    """{"publish": bool, "code": str, "reason": str} for one destination {platform, channelId?}.

    `providers` maps provider ids to adapters (OAuthService.providers); `live` says whether hosted publishing
    transport is mounted in this deployment; `can_publish` is the plan's answer when known; `channel_state` is the
    Phase 2 engine's readiness function when the caller needs a fresh "Ready for posting" (the commit gate re-verifies
    first, so creation-time checks pass None and judge the connection by its verified permissions)."""
    platform = destination.get("platform") or ""
    provider_id = HOSTED_PUBLISHERS.get(platform)
    if provider_id is None:
        return {"publish": False, "code": "no_route", "reason": _no_route(platform)}
    if platform == "Instagram" and not destination.get("hasImage"):
        return {"publish": False, "code": "needs_image", "reason": "Instagram posts need an image, and this automation writes text, so the Instagram version is kept as a draft to post with an image."}
    adapter = (providers or {}).get(provider_id)
    if adapter is None:
        return {"publish": False, "code": "not_configured", "reason": f"Publishing to {platform} isn't available yet, so the {platform} version is prepared as a draft."}
    if not getattr(adapter, "production_reviewed", False):
        return {"publish": False, "code": "awaiting_review", "reason": f"{platform} hasn't approved Rafii's publishing access yet, so the {platform} version is prepared as a draft."}
    if not getattr(adapter, "execution_enabled", True):
        return {"publish": False, "code": "paused", "reason": f"Publishing to {platform} is paused for maintenance, so the {platform} version waits as a draft."}
    if not live:
        return {"publish": False, "code": "not_live", "reason": "Publishing isn't switched on yet, so posts are prepared as drafts."}
    channels = [c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and c.get("platform") == platform]
    channel_id = destination.get("channelId")
    channel = next((c for c in channels if c.get("id") == channel_id), None) if channel_id else None
    if channel is None:
        live_accounts = [c for c in channels if not c.get("revoked")]
        if channel_id:
            return {"publish": False, "code": "disconnected", "reason": f"The {platform} account for this automation is no longer connected. Reconnect it to publish; the draft is kept."}
        if not live_accounts:
            return {"publish": False, "code": "not_connected", "reason": f"{platform} isn't connected yet. Connect it to publish; until then Rafii prepares the draft."}
        return {"publish": False, "code": "choose_account", "reason": f"Choose which {platform} account to publish to."}
    if channel.get("revoked"):
        return {"publish": False, "code": "disconnected", "reason": f"{channel.get('account') or platform} was disconnected. Reconnect it to publish; the draft is kept."}
    if channel.get("evidenceSource", "synthetic") == "synthetic":
        return {"publish": False, "code": "demo_account", "reason": f"{channel.get('account') or platform} is a demo account, so nothing is really published there."}
    if not channel.get("identityVerified") or not channel.get("capabilityVerified"):
        return {"publish": False, "code": "reauthorize", "reason": f"{channel.get('account') or platform} needs to be reconnected before Rafii can publish there."}
    if channel_state is not None and channel_state(channel) != "Ready for posting":
        return {"publish": False, "code": "disconnected", "reason": f"{channel.get('account') or platform} needs to be reconnected before Rafii can publish there."}
    if can_publish is False:
        return {"publish": False, "code": "plan", "reason": "Your plan doesn't include publishing right now, so posts wait as drafts. Choose a plan to publish."}
    return {"publish": True, "code": "ok", "reason": f"Publishes to {channel.get('account') or platform}."}


def summary(state: dict, destinations: list[dict], **kwargs) -> list[dict]:
    """One line per destination for the chat card: platform, account, whether it can publish and why not."""
    labels = {c.get("id"): c.get("account") for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict)}
    out = []
    for destination in destinations:
        route = publish_route(state, destination, **kwargs)
        out.append({"platform": destination.get("platform"), "account": labels.get(destination.get("channelId")) or None,
                    "canPublish": route["publish"], "code": route["code"], "reason": route["reason"]})
    return out

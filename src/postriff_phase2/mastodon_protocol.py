"""Federated Mastodon contracts. No credentials, private content, or invented metrics."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from .net_guard import public_host

VISIBILITIES = ("public", "unlisted", "private", "direct")
ID = re.compile(r"[0-9]{1,40}\Z")


def instance_host(value):
    raw = value.strip() if isinstance(value, str) else ""
    if raw.startswith("https://"):
        try:
            parsed = urlsplit(raw)
            allowed = (not parsed.username and not parsed.password and parsed.port in (None, 443)
                       and parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
        except ValueError:
            allowed = False
        if not allowed:
            raise AlphaError("Enter an HTTPS server domain or @name@server account.", 400)
        raw = parsed.hostname or ""
    elif "@" in raw:
        if not re.fullmatch(r"@?[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+", raw):
            raise AlphaError("Enter an account such as @name@mastodon.social.", 400)
        raw = raw.rsplit("@", 1)[1]
    elif any(c in raw for c in "/?#:\\"):
        raise AlphaError("Enter a server domain such as mastodon.social.", 400)
    return public_host(raw)


def version_at_least(version, minimum):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(version))
    return bool(match and tuple(map(int, match.groups())) >= minimum)


def discover(transport, host):
    origin = "https://" + host
    response = transport("GET", origin + "/api/v2/instance")
    if response.get("status") == 404:
        response = transport("GET", origin + "/api/v1/instance")
    body = response.get("body")
    if response.get("status") != 200 or not isinstance(body, dict) or not isinstance(body.get("version"), str):
        raise AlphaError("This server did not expose a compatible Mastodon instance API.", 409)
    version = body["version"][:100]
    config = body.get("configuration") if isinstance(body.get("configuration"), dict) else {}
    statuses = config.get("statuses") if isinstance(config.get("statuses"), dict) else {}
    media = config.get("media_attachments") if isinstance(config.get("media_attachments"), dict) else {}
    polls = config.get("polls") if isinstance(config.get("polls"), dict) else {}
    accounts = config.get('accounts') if isinstance(config.get('accounts'), dict) else {}
    profile_defaults = {'max_display_name_length': 30, 'max_note_length': 500,
                        'max_profile_fields': 4, 'profile_field_name_limit': 255, 'profile_field_value_limit': 255,
                        'max_avatar_description_length': 1500, 'max_header_description_length': 1500}
    profile_limits = {key: accounts.get(key, default) for key, default in profile_defaults.items()}
    for key, value in profile_limits.items():
        maximum = 16 if key == 'max_profile_fields' else 100000
        minimum = 0 if key == 'max_profile_fields' else 1
        if type(value) is not int or not minimum <= value <= maximum:
            raise AlphaError('This server returned invalid account limits.', 502)
    capabilities = {
        "instance": host, "version": version, "pkce": version_at_least(version, (4, 3, 0)),
        "edit": version_at_least(version, (3, 5, 0)), "schedule": version_at_least(version, (2, 7, 0)),
        "polls": version_at_least(version, (2, 8, 0)), "quotes": version_at_least(version, (4, 5, 0)),
        "maxCharacters": statuses.get("max_characters", body.get("max_toot_chars", 500)),
        "maxMediaAttachments": statuses.get("max_media_attachments", 4),
        "charactersReservedPerUrl": statuses.get("characters_reserved_per_url", 23),
        "media": {k: media[k] for k in ("supported_mime_types", "image_size_limit", "video_size_limit",
                   "audio_size_limit", "image_matrix_limit", "video_matrix_limit", "video_frame_rate_limit") if k in media},
        "pollLimits": {k: polls[k] for k in ("max_options", "max_characters_per_option", "min_expiration", "max_expiration") if k in polls},
        "scopesSupported": None, "streamingUrl": None, "profileLimits": profile_limits,
        "dataScope": "instance-local; federation delivery and completeness are not guaranteed",
    }
    from .mastodon_streaming import bound_origin
    urls = config.get('urls') if isinstance(config.get('urls'), dict) else {}
    legacy_urls = body.get('urls') if isinstance(body.get('urls'), dict) else {}
    capabilities['streamingUrl'] = bound_origin(host, urls.get('streaming') or legacy_urls.get('streaming_api'))
    for key, maximum in (("maxCharacters", 100000), ("maxMediaAttachments", 16), ("charactersReservedPerUrl", 1000)):
        if type(capabilities[key]) is not int or not 0 < capabilities[key] <= maximum:
            raise AlphaError("This server returned invalid posting limits.", 502)
    if capabilities["pkce"]:
        metadata = transport("GET", origin + "/.well-known/oauth-authorization-server")
        document = metadata.get("body")
        if metadata.get("status") == 200 and isinstance(document, dict):
            if document.get("issuer") not in (origin, origin + "/"):
                raise AlphaError("This server's OAuth identity does not match its HTTPS origin.", 409)
            for name, path in (("authorization_endpoint", "/oauth/authorize"), ("token_endpoint", "/oauth/token")):
                if document.get(name) != origin + path:
                    raise AlphaError("This server's OAuth identity does not match its HTTPS origin.", 409)
            methods = document.get("code_challenge_methods_supported", [])
            if not isinstance(methods, list) or "S256" not in methods:
                raise AlphaError("This server does not support secure S256 authorization.", 409)
            scopes = document.get("scopes_supported")
            if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
                raise AlphaError("This server returned invalid OAuth permissions.", 502)
            capabilities["scopesSupported"] = sorted(set(scopes))
        elif metadata.get("status") != 404:
            raise AlphaError("This server's OAuth discovery is unavailable.", 503)
    return capabilities


def has_scopes(granted, required):
    granted = set(granted or [])
    return all(s in granted or s.split(":", 1)[0] in granted for s in required)


def status_options(options, media=(), *, capabilities=None, now=None):
    """Canonical fields bound to Rafii's approval digest, never pass arbitrary provider parameters."""
    if not isinstance(options, dict):
        raise AlphaError("Expected Mastodon post settings.", 400)
    visibility = options.get("visibility", "public")
    if visibility not in VISIBILITIES:
        raise AlphaError("Choose Public, Unlisted, Followers-only or Private Mentions.", 400)
    sensitive = options.get("sensitive", False)
    if type(sensitive) is not bool:
        raise AlphaError("Choose whether the Mastodon media is sensitive.", 400)
    warning = options.get("spoiler_text", "")
    if not isinstance(warning, str) or len(warning) > 5000:
        raise AlphaError("Use a content warning of at most 5,000 characters.", 400)
    result = {"visibility": visibility, "sensitive": sensitive, "spoiler_text": warning}
    for key in ("in_reply_to_id", "quoted_status_id"):
        if key in options:
            if not isinstance(options[key], str) or not ID.fullmatch(options[key]):
                raise AlphaError("Use a valid Mastodon post ID.", 400)
            result[key] = options[key]
    if result.get("quoted_status_id") and capabilities and not capabilities.get("quotes"):
        raise AlphaError("This server does not support quote posts.", 409)
    if "language" in options:
        if not isinstance(options["language"], str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", options["language"]):
            raise AlphaError("Choose a valid post language.", 400)
        result["language"] = options["language"]
    if "poll" in options:
        poll = options["poll"]
        if not isinstance(poll, dict) or set(poll) - {'options', 'expires_in', 'multiple', 'hide_totals'}:
            raise AlphaError("Use only the supported Mastodon poll fields.", 400)
        limits = (capabilities or {}).get("pollLimits", {})
        defaults = {'max_options': 4, 'max_characters_per_option': 50, 'min_expiration': 300, 'max_expiration': 2629746}
        if not isinstance(limits, dict) or any(type(limits.get(key, default)) is not int or limits.get(key, default) < (2 if key == 'max_options' else 1) for key, default in defaults.items()):
            raise AlphaError("This server returned invalid poll limits.", 502)
        if limits.get('min_expiration', 300) > limits.get('max_expiration', 2629746):
            raise AlphaError("This server returned inconsistent poll duration limits.", 502)
        choices = poll.get("options")
        if media or not isinstance(choices, list) or not 2 <= len(choices) <= limits.get("max_options", 4):
            raise AlphaError("A poll needs supported answer choices and cannot include media.", 400)
        if not all(isinstance(c, str) and 0 < len(c.strip()) <= limits.get("max_characters_per_option", 50) for c in choices):
            raise AlphaError("The poll answers exceed this server's limits.", 400)
        seconds = poll.get("expires_in")
        if type(seconds) is not int or not limits.get("min_expiration", 300) <= seconds <= limits.get("max_expiration", 2629746):
            raise AlphaError("Choose a supported poll duration.", 400)
        if capabilities and not capabilities.get("polls"):
            raise AlphaError("This server does not support polls.", 409)
        if any(type(poll.get(k, False)) is not bool for k in ("multiple", "hide_totals")):
            raise AlphaError("Choose the poll settings.", 400)
        result["poll"] = {"options": [c.strip() for c in choices], "expires_in": seconds,
                          "multiple": poll.get("multiple", False), "hide_totals": poll.get("hide_totals", False)}
    if "scheduled_at" in options:
        if capabilities and not capabilities.get("schedule"):
            raise AlphaError("Native scheduling is unavailable on this server. Use the Rafii calendar.", 409)
        try:
            instant = datetime.fromisoformat(options["scheduled_at"].replace("Z", "+00:00"))
            if instant.tzinfo is None or instant.timestamp() < (now if now is not None else datetime.now(timezone.utc).timestamp()) + 300:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise AlphaError("Native scheduling needs a time at least five minutes in the future.", 400)
        result["scheduled_at"] = instant.astimezone(timezone.utc).isoformat()
    return result


def validate_status(text, options, media, capabilities, *, now=None):
    selected = status_options(options, media, capabilities=capabilities, now=now)
    if not isinstance(text, str) or (not text.strip() and not media):
        raise AlphaError("Write a post or attach media.", 400)
    reserved = capabilities.get("charactersReservedPerUrl", 23)
    measured = len(re.sub(r"https?://[^\s<>]+", lambda m: "x" * reserved, text)) + len(selected["spoiler_text"])
    if measured > capabilities.get("maxCharacters", 500):
        raise AlphaError("This post exceeds the selected Mastodon server's character limit.", 400)
    if len(media) > capabilities.get("maxMediaAttachments", 4):
        raise AlphaError("Too many media attachments for this Mastodon server.", 400)
    return {"status": text, **selected}

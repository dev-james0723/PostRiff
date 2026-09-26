"""Dedicated connector execution for the hosted worker (architecture §13).

`submit` runs exactly one approved manifest against the customer's own encrypted grant;
`reconcile` looks the outcome up before any retry. Every ambiguous response is
`uncertain`; permission failures are `held`; explicit pre-acceptance rejections are
`scheduled` (429) or `failed`. HTTP 200 alone is never `published`.
"""
import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from postriff_alpha.domain import AlphaError
from .atproto_oauth import tid
from .capabilities import HOSTED_PUBLISHERS
from .provider_candidates import LinkedInCandidate, little_plain
from .providers import GRAPH_VERSION, http_transport
from .social_connectors import multipart

WAVE1 = ("Bluesky", "Mastodon", "Telegram", "Discord", "X")
_URL = re.compile(r"https?://[^\s<>\"]+")


def _provider_reason(body):
    """The provider's own short error text: first plain message field, control characters removed, at most 300 characters."""
    if not isinstance(body, dict):
        return ""
    candidates = [body.get(key) for key in ("detail", "message", "description", "error_description", "error", "title")]
    errors = body.get("errors")
    if isinstance(errors, list):
        candidates += [e.get("message") for e in errors if isinstance(e, dict)]
    text = next((c for c in candidates if isinstance(c, str) and c.strip()), "")
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", text).split())[:300]

LINKEDIN_VERSION = "202609"  # official versioning + Posts API docs checked 2026-09-20; live account validation pending


def _uncertain(message):
    return {"state": "uncertain", "confirmed": message}


class HostedSocial:
    """Mounted only when at least one production-reviewed provider is registered."""
    X_RECONCILE_LIMIT = 3  # billed reads before X reconciliation stops and asks a person
    MASTODON_MEDIA_POLLS, MASTODON_MEDIA_WAIT = 5, 2.0

    def __init__(self, oauth, providers, assets=None, transport=None, sleep=time.sleep):
        self.oauth, self.providers, self.assets = oauth, providers, assets
        self.transport = transport or http_transport
        self.sleep = sleep
        self.linkedin = LinkedInCandidate(transport=None, version=LINKEDIN_VERSION)

    # --- helpers ------------------------------------------------------------------
    def _grant(self, manifest):
        try:
            return self.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        except AlphaError as error:
            return None, {"state": "held", "confirmed": f"Connection unavailable: {error}"}
        finally:
            pass

    def _provider(self, manifest):
        provider = self.providers.get(HOSTED_PUBLISHERS.get(manifest["platform"]))
        if provider is None or not provider.production_reviewed or not getattr(provider, "execution_enabled", True):
            return None
        return provider

    def _image_url(self, manifest):
        if not manifest.get("media"):
            return None
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        asset = manifest["media"][0]
        return self.assets.storage.signed_url(manifest["workspaceId"], "media", asset.get("objectName") or asset["id"], 600)

    # --- submit -------------------------------------------------------------------
    def submit(self, manifest):
        provider = self._provider(manifest)
        if provider is None:
            return {"state": "held", "confirmed": "Publishing to this platform isn't available yet. Nothing was posted."}
        grant = self.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        required = ({"LinkedIn": {"w_member_social"}, "Threads": {"threads_basic", "threads_content_publish"}, "Instagram": {"instagram_business_basic", "instagram_business_content_publish"}}.get(manifest["platform"])
                    or set(getattr(provider, "publish_required", ())))
        if not required or not required.issubset(grant.get("scopes", [])):
            return {"state": "held", "confirmed": "Publishing permissions changed or are unverified; reconnect and review again."}
        token = grant["accessToken"]
        try:
            if manifest["platform"] == "LinkedIn":
                return self._submit_linkedin(manifest, token)
            if manifest["platform"] == "Threads":
                return self._submit_threads(manifest, token)
            if manifest["platform"] == "Instagram":
                return self._submit_instagram(manifest, token)
            if manifest["platform"] in WAVE1:
                return getattr(self, "_submit_" + manifest["platform"].lower())(manifest, provider, token)
        except AlphaError as error:
            return _uncertain(f"Submission could not be completed conclusively: {error}")
        return {"state": "held", "confirmed": "No connector for this platform."}

    # --- Wave 1 publishers (Bluesky, Mastodon, Telegram, Discord, X) --------------------------------------------
    def _image(self, manifest):
        """(bytes, mime, alt) for the manifest's single image, or None. Video is not published by these connectors."""
        if not manifest.get("media"):
            return None
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        asset = manifest["media"][0]
        mime = str(asset.get("mime") or "")
        if not mime.startswith("image/"):
            raise AlphaError("Only a single image can be attached here.", 409, code="unsupported_media")
        raw = self.assets.storage.get(manifest["workspaceId"], "media", asset.get("objectName") or asset["id"])
        return raw, mime, str(asset.get("alt") or "")

    @staticmethod
    def _unsupported_media(manifest):
        media = manifest.get("media") or []
        if len(media) > 1 or (media and not str(media[0].get("mime") or "").startswith("image/")):
            return {"state": "failed", "confirmed": f"{manifest['platform']} posts from Rafii carry text and at most one image. Nothing was posted."}
        return None

    @staticmethod
    def bluesky_rkey(manifest):
        """A record key fixed by the approved job: a retry of the same job can never create a second post.

        TID syntax (13 base32-sortable characters) from the scheduled second plus key-derived microseconds and clock id."""
        seed = int(hashlib.sha256(str(manifest["idempotencyKey"]).encode()).hexdigest(), 16)
        timestamp = (manifest.get("timing") or {}).get("timestamp")
        seconds = int(timestamp) if isinstance(timestamp, (int, float)) and 0 < timestamp < 2 ** 40 else 1_700_000_000
        return tid(seconds * 1_000_000 + seed % 1_000_000, (seed >> 20) & 0x3FF)

    def _submit_bluesky(self, manifest, provider, token):
        refusal = self._unsupported_media(manifest)
        if refusal:
            return refusal
        session = json.loads(token)
        text = manifest["payload"]["text"]
        rkey = self.bluesky_rkey(manifest)
        reference = f"at://{session['did']}/app.bsky.feed.post/{rkey}"
        record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")}
        facets = []
        for match in _URL.finditer(text):
            url = match.group(0).rstrip(".,;:!?)")
            start = len(text[:match.start()].encode())
            facets.append({"index": {"byteStart": start, "byteEnd": start + len(url.encode())}, "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
        if facets:
            record["facets"] = facets
        image = self._image(manifest)
        if image:
            raw, mime, alt = image
            uploaded = provider.xrpc_post(session, "com.atproto.repo.uploadBlob", data=raw, content_type=mime)
            early = self._classify_status(uploaded.get("status"), uploaded.get("body"), "Bluesky")
            if early:
                return early
            blob = uploaded.get("body", {}).get("blob") if isinstance(uploaded.get("body"), dict) else None
            if uploaded.get("status") != 200 or not isinstance(blob, dict):
                return {"state": "failed", "confirmed": "Bluesky did not accept the image, so nothing was posted."}
            record["embed"] = {"$type": "app.bsky.embed.images", "images": [{"image": blob, "alt": alt}]}
        try:
            response = provider.xrpc_post(session, "com.atproto.repo.createRecord", body={"repo": session["did"], "collection": "app.bsky.feed.post", "rkey": rkey, "record": record})
        except AlphaError:
            return {**_uncertain("Bluesky did not answer the create request; reconcile by record key; do not resubmit"), "reference": reference}
        uri = response.get("body", {}).get("uri") if isinstance(response.get("body"), dict) else None
        if response.get("status") == 200 and uri == reference:
            return {"state": "provider_accepted", "reference": reference, "confirmed": "Bluesky created the post record; read-back pending"}
        if response.get("status") == 400:
            # The key is fixed per job, so an earlier attempt that did land shows up here as an existing record.
            existing = provider.xrpc_get(session, "com.atproto.repo.getRecord", {"repo": session["did"], "collection": "app.bsky.feed.post", "rkey": rkey})
            value = existing.get("body", {}).get("value") if isinstance(existing.get("body"), dict) else None
            if existing.get("status") == 200 and isinstance(value, dict) and value.get("text") == text:
                return {"state": "provider_accepted", "reference": reference, "confirmed": "Bluesky already holds this job's post from an earlier attempt; read-back pending"}
        early = self._classify_status(response.get("status"), response.get("body"), "Bluesky")
        if early:
            return early
        return {**_uncertain("No conclusive Bluesky create response; reconcile by record key; do not resubmit"), "reference": reference}

    def _mastodon_media(self, provider, session, image):
        """Upload once, then poll the same media id while the server processes it (never a second upload)."""
        raw, mime, alt = image
        body, content_type = multipart([("description", alt)], [("file", "image", mime, raw)])
        uploaded = provider.api(session, "POST", "/api/v2/media", headers={"Content-Type": content_type}, data=body)
        early = self._classify_status(uploaded.get("status"), uploaded.get("body"), "Mastodon")
        if early:
            return None, early
        media_id = str(uploaded.get("body", {}).get("id", "")) if isinstance(uploaded.get("body"), dict) else ""
        if uploaded.get("status") not in (200, 202) or not media_id.isdigit():
            return None, {"state": "failed", "confirmed": "Mastodon did not accept the image, so nothing was posted."}
        ready = uploaded.get("status") == 200
        for _ in range(0 if ready else self.MASTODON_MEDIA_POLLS):
            self.sleep(self.MASTODON_MEDIA_WAIT)
            polled = provider.api(session, "GET", "/api/v1/media/" + media_id)
            if polled.get("status") == 200 and isinstance(polled.get("body"), dict) and polled["body"].get("url"):
                ready = True
                break
            if polled.get("status") not in (200, 206):
                break
        if not ready:
            return None, {"state": "scheduled", "confirmed": "Mastodon is still processing the image; Rafii will try again shortly. Nothing was posted."}
        return media_id, None

    def _submit_mastodon(self, manifest, provider, token):
        refusal = self._unsupported_media(manifest)
        if refusal:
            return refusal
        session = provider.session(token)
        media_ids = []
        image = self._image(manifest)
        if image:
            media_id, outcome = self._mastodon_media(provider, session, image)
            if outcome:
                return outcome
            media_ids.append(media_id)
        # Mastodon keeps an Idempotency-Key for an hour, so a retried request returns the same status.
        response = provider.api(session, "POST", "/api/v1/statuses", headers={"Idempotency-Key": manifest["idempotencyKey"][:64]},
                                body={"status": manifest["payload"]["text"], "media_ids": media_ids, "visibility": "public"})
        status_id = str(response.get("body", {}).get("id", "")) if isinstance(response.get("body"), dict) else ""
        if response.get("status") == 200 and status_id.isdigit():
            return {"state": "provider_accepted", "reference": status_id, "confirmed": "Mastodon created the post; read-back pending"}
        early = self._classify_status(response.get("status"), response.get("body"), "Mastodon")
        if early:
            return early
        return _uncertain("No conclusive Mastodon create response; do not resubmit")

    def _submit_telegram(self, manifest, provider, token):
        refusal = self._unsupported_media(manifest)
        if refusal:
            return refusal
        chat, text = provider.session(token)["chat"], manifest["payload"]["text"]
        if manifest.get("media"):
            if len(text) > 1024:
                return {"state": "failed", "confirmed": "Telegram photo captions allow 1024 characters. Nothing was posted."}
            response = provider.request("sendPhoto", {"chat_id": chat, "photo": self._image_url(manifest), "caption": text})
        else:
            response = provider.request("sendMessage", {"chat_id": chat, "text": text, "link_preview_options": {"is_disabled": False}})
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or body.get("ok") is not True:
            code = body.get("error_code") if isinstance(body.get("error_code"), int) else response.get("status")
            reason = _provider_reason(body)
            if code in (400, 403):
                # Telegram refused before posting anything (bad request, or the bot may not post in this channel).
                return {"state": "failed", "confirmed": "Telegram rejected the post; nothing was published" + (f": {reason}" if reason else ".")}
            if code == 429:
                return {"state": "scheduled", "confirmed": "Telegram rate limited the request before acceptance"}
            return _uncertain("Telegram's answer was inconclusive; check the channel; do not resubmit")
        message = body.get("result")
        posted_text = (message.get("caption") if manifest.get("media") else message.get("text")) if isinstance(message, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("message_id"), int) or (message.get("chat") or {}).get("id") != chat:
            return _uncertain("Telegram's reply did not identify the created message; check the channel; do not resubmit")
        reference = f"{chat}/{message['message_id']}"
        if posted_text != text:
            return {"state": "published", "reference": reference, "confirmed": "Telegram created the message, but its text differs from the approved text; review it in the channel"}
        receipt = {"state": "verified", "reference": reference, "verification": "provider_receipt",
                   "confirmed": "Telegram returned the created channel message with the exact approved text (bots cannot read messages back)"}
        username = (message.get("chat") or {}).get("username")
        if isinstance(username, str):
            receipt["url"] = f"https://t.me/{username}/{message['message_id']}"
        return receipt

    def _submit_discord(self, manifest, provider, token):
        refusal = self._unsupported_media(manifest)
        if refusal:
            return refusal
        session = provider.session(token)
        channel = session.get("channel")
        if not channel:
            return {"state": "held", "confirmed": "Choose a Discord channel for this server first. Nothing was posted."}
        # enforce_nonce makes Discord return the first message instead of posting again for a repeated nonce.
        payload = {"content": manifest["payload"]["text"], "allowed_mentions": {"parse": []}, "nonce": str(manifest["idempotencyKey"])[:25], "enforce_nonce": True}
        image = self._image(manifest)
        if image:
            raw, mime, alt = image
            filename = "image." + {"image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(mime, "jpg")
            body, content_type = multipart([("payload_json", json.dumps({**payload, "attachments": [{"id": 0, "filename": filename, "description": alt[:1024]}]}))],
                                           [("files[0]", filename, mime, raw)])
            response = provider._bot("POST", f"/channels/{channel}/messages", headers={"Content-Type": content_type}, data=body)
        else:
            response = provider._bot("POST", f"/channels/{channel}/messages", body=payload)
        message_id = str(response.get("body", {}).get("id", "")) if isinstance(response.get("body"), dict) else ""
        if response.get("status") == 200 and message_id.isdigit():
            return {"state": "provider_accepted", "reference": f"{channel}/{message_id}", "confirmed": "Discord created the message; read-back pending"}
        early = self._classify_status(response.get("status"), response.get("body"), "Discord")
        if early:
            return early
        return _uncertain("No conclusive Discord create response; do not resubmit")

    def _submit_x(self, manifest, provider, token):
        refusal = self._unsupported_media(manifest)
        if refusal:
            return refusal
        payload = {"text": manifest["payload"]["text"]}
        image = self._image(manifest)
        if image:
            raw, mime, _ = image
            body, content_type = multipart([("media_category", "tweet_image")], [("media", "image", mime, raw)])
            uploaded = provider.api(token, "POST", "/2/media/upload", headers={"Content-Type": content_type}, data=body)
            early = self._classify_status(uploaded.get("status"), uploaded.get("body"), "X")
            if early:
                return early
            data = uploaded.get("body", {}).get("data") if isinstance(uploaded.get("body"), dict) else None
            media_id = str(data.get("id", "")) if isinstance(data, dict) else ""
            if uploaded.get("status") not in (200, 201) or not media_id.isdigit():
                return {"state": "failed", "confirmed": "X did not accept the image, so nothing was posted."}
            payload["media"] = {"media_ids": [media_id]}
        response = provider.api(token, "POST", "/2/tweets", body=payload)
        data = response.get("body", {}).get("data") if isinstance(response.get("body"), dict) else None
        post_id = str(data.get("id", "")) if isinstance(data, dict) else ""
        if response.get("status") == 201 and post_id.isdigit():
            return {"state": "provider_accepted", "reference": post_id, "confirmed": "X created the post; read-back pending"}
        early = self._classify_status(response.get("status"), response.get("body"), "X")
        if early:
            return early
        return _uncertain("No conclusive X create response; do not resubmit")

    @staticmethod
    def _x_expanded(data):
        """X's stored text as the author wrote it: entities decoded, t.co links expanded, the attached-media link dropped."""
        text = str(data.get("text") or "")
        urls = ((data.get("entities") or {}).get("urls") or []) if isinstance(data.get("entities"), dict) else []
        for entity in sorted((u for u in urls if isinstance(u, dict)), key=lambda u: -int(u.get("start") or 0)):
            short, expanded = entity.get("url"), entity.get("expanded_url")
            if not isinstance(short, str) or short not in text:
                continue
            media = entity.get("media_key") or re.search(r"/status/\d+/(photo|video)/\d+$", str(expanded or ""))
            text = text.replace(short, "" if media else str(expanded or short), 1)
        return html.unescape(text).strip()

    def _reconcile_wave1(self, manifest, provider, token, reference, job=None):
        platform, text = manifest["platform"], manifest["payload"]["text"]
        if not reference:
            return _uncertain(f"No {platform} reference was recorded; check the account; do not resubmit")
        if platform == "Bluesky":
            session = json.loads(token)
            match = re.fullmatch(r"at://(did:[a-z0-9:._-]+)/app\.bsky\.feed\.post/([a-z2-7]{13})", reference)
            if not match or match.group(1) != session["did"]:
                return _uncertain("Bluesky reference does not belong to this account; do not resubmit")
            response = provider.xrpc_get(session, "com.atproto.repo.getRecord", {"repo": match.group(1), "collection": "app.bsky.feed.post", "rkey": match.group(2)})
            value = response.get("body", {}).get("value") if isinstance(response.get("body"), dict) else None
            if response.get("status") == 200 and isinstance(value, dict) and value.get("text") == text:
                return {"state": "verified", "reference": reference, "url": f"https://bsky.app/profile/{match.group(1)}/post/{match.group(2)}",
                        "confirmed": "Bluesky read-back matched the approved text and account", "verification": "provider_lookup"}
            return _uncertain("Bluesky read-back did not match the exact approved post")
        if platform == "Mastodon":
            session = provider.session(token)
            response = provider.api(session, "GET", "/api/v1/statuses/" + quote(reference))
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            account = str((body.get("account") or {}).get("id", ""))
            # Tags go before entities are decoded, so literal "<" typed in a post survives the comparison.
            plain = " ".join(html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>|</p>\s*<p>", " ", str(body.get("content") or "")))).split())
            if response.get("status") == 200 and f"{account}@{session['instance']}" == manifest["providerAccountId"] and plain == " ".join(text.split()):
                return {"state": "verified", "reference": reference, "confirmed": "Mastodon read-back matched the approved text and account", "verification": "provider_lookup"}
            return _uncertain("Mastodon read-back did not match the exact approved post")
        if platform == "Discord":
            channel, _, message_id = reference.partition("/")
            response = provider._bot("GET", f"/channels/{channel}/messages/{message_id}")
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            session = provider.session(token)
            if response.get("status") == 200 and body.get("content") == text and str(body.get("channel_id")) == channel == str(session.get("channel")):
                return {"state": "verified", "reference": reference, "url": f"https://discord.com/channels/{session['guild']}/{channel}/{message_id}",
                        "confirmed": "Discord read-back matched the approved text and channel", "verification": "provider_lookup"}
            return _uncertain("Discord read-back did not match the exact approved message")
        if platform == "X":
            # Every X read is billed: after a few inconclusive checks, stop reading and leave it to a person.
            if (job or {}).get("checks", 0) > self.X_RECONCILE_LIMIT:
                return _uncertain("X read-back stopped after repeated inconclusive checks (each read is billed); check the account manually; do not resubmit")
            response = provider.api(token, "GET", f"/2/tweets/{quote(reference)}?" + urlencode({"tweet.fields": "author_id,text,entities"}))
            data = response.get("body", {}).get("data") if isinstance(response.get("body"), dict) else None
            if response.get("status") == 200 and isinstance(data, dict) and str(data.get("author_id")) == manifest["providerAccountId"] and self._x_expanded(data) == text.strip():
                result = {"state": "verified", "reference": reference, "confirmed": "X read-back matched the approved text and account", "verification": "provider_lookup"}
                username = str(manifest.get("account") or "").lstrip("@")
                if re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
                    result["url"] = f"https://x.com/{username}/status/{reference}"
                return result
            return _uncertain("X read-back did not match the exact approved post")
        # Telegram receipts are verified at submission; a job only reaches here when that receipt was inconclusive.
        return _uncertain("Telegram bots cannot read messages back; check the channel; do not resubmit")

    def _classify_status(self, status, body=None, platform=None):
        """Answers that prove nothing was posted. Anything else is left for the caller to judge, never guessed."""
        reason = _provider_reason(body)
        if platform == "X" and status == 403 and "duplicate" in reason.lower():
            return {"state": "failed", "confirmed": "Duplicate content: X already has an identical post on this account and created nothing new. Change the text before approving it again."}
        if status in (400, 422):
            return {"state": "failed", "confirmed": f"{platform or 'The provider'} rejected the post; nothing was published" + (f": {reason}" if reason else ".")}
        if status in (401, 403):
            return {"state": "held", "confirmed": "Provider rejected the permission or session; re-authorization required" + (f" ({reason})" if reason else "")}
        if status == 429:
            return {"state": "scheduled", "confirmed": "Provider rate limited the request before acceptance"}
        return None

    def _submit_linkedin(self, manifest, token):
        descriptor = self.linkedin.prepare(manifest, manifest["providerAccountId"])
        response = self.transport("POST", descriptor["url"], headers={**descriptor["headers"], "Authorization": "Bearer " + token}, body=descriptor["body"])
        early = self._classify_status(response.get("status"))
        if early:
            return early
        reference = response.get("headers", {}).get("x-restli-id")
        if response.get("status") == 201 and isinstance(reference, str) and reference.startswith(("urn:li:share:", "urn:li:ugcPost:")):
            return {"state": "provider_accepted", "reference": reference, "confirmed": "LinkedIn accepted the create request; publication verification pending"}
        return _uncertain("No conclusive LinkedIn acceptance evidence; do not resubmit")

    def _submit_threads(self, manifest, token):
        user = manifest["providerAccountId"]
        image_url = self._image_url(manifest)
        params = {"media_type": "IMAGE" if image_url else "TEXT", "text": manifest["payload"]["text"], "access_token": token}
        if image_url:
            params["image_url"] = image_url
            params["alt_text"] = manifest["media"][0].get("alt", "")
        container = self.transport("POST", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(user)}/threads", form=params)
        early = self._classify_status(container.get("status"))
        if early:
            return early
        container_id = str(container.get("body", {}).get("id", ""))
        if container.get("status") != 200 or not container_id.isdigit():
            return _uncertain("Threads did not return a container id; do not resubmit")
        publish = self.transport("POST", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(user)}/threads_publish", form={"creation_id": container_id, "access_token": token})
        media_id = str(publish.get("body", {}).get("id", ""))
        if publish.get("status") == 200 and media_id.isdigit():
            return {"state": "provider_accepted", "reference": media_id, "container": container_id, "confirmed": "Threads returned a media id; publication verification pending"}
        return _uncertain(f"Threads container {container_id} was created but publish was inconclusive; reconcile by container")

    def _submit_instagram(self, manifest, token):
        user = manifest["providerAccountId"]
        image_url = self._image_url(manifest)
        if not image_url:
            return {"state": "failed", "confirmed": "Instagram requires a decoded image"}
        container = self.transport("POST", f"https://graph.instagram.com/{GRAPH_VERSION}/{quote(user)}/media", form={"image_url": image_url, "caption": manifest["payload"]["text"], "alt_text": manifest["media"][0].get("alt", ""), "access_token": token})
        early = self._classify_status(container.get("status"))
        if early:
            return early
        container_id = str(container.get("body", {}).get("id", ""))
        if container.get("status") != 200 or not container_id.isdigit():
            return _uncertain("Instagram did not return a container id; do not resubmit")
        return {"state": "processing", "container": container_id,
                "progress": {"version": 1, "stage": "container_created"},
                "confirmed": "Instagram container created; processing is not publication"}

    def advance_instagram(self, manifest, job, action):
        """One bounded request. Worker has durably recorded intent before a POST."""
        if self._provider(manifest) is None:
            return {"state": "held", "confirmed": "Provider review is unavailable; a new review is required"}
        try:
            grant = self.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        except AlphaError:
            return {"state": "held", "confirmed": "Connection unavailable; re-authorize and review again"}
        if not {"instagram_business_basic", "instagram_business_content_publish"}.issubset(grant["scopes"]):
            return {"state": "held", "confirmed": "Instagram publishing scopes missing; re-authorize and review again"}
        token = grant['accessToken']
        if action == 'create':
            return self._submit_instagram(manifest, token)
        container = job.get('container')
        if not isinstance(container, str) or not container.isdigit():
            return _uncertain('Missing durable container; manual review required; do not resubmit')
        if action == 'status':
            try:
                response = self.transport('GET', f'https://graph.instagram.com/{GRAPH_VERSION}/{container}?' + urlencode({'fields': 'status_code', 'access_token': token}))
            except (AlphaError, OSError):
                return {"state": "processing", "container": container,
                        "progress": {"version": 1, "stage": "container_created"},
                        "confirmed": "Read-only container lookup unavailable; no publish attempted"}
            status = response.get('status')
            if status in (401, 403):
                return {"state": "held", "confirmed": "Container lookup requires re-authorization and a new review"}
            code = response.get('body', {}).get('status_code') if status == 200 else None
            if code in ('ERROR', 'EXPIRED'):
                return {"state": "failed", "confirmed": "Unpublished container reports " + code}
            if code == 'PUBLISHED':
                return _uncertain('Container unexpectedly reports published; inspect platform; do not resubmit')
            return {"state": "processing", "container": container,
                    "progress": {"version": 1, "stage": "container_ready" if code == 'FINISHED' else 'container_created'},
                    "confirmed": "Container ready for approved publication" if code == 'FINISHED' else "Container processing or lookup unavailable; no publish attempted"}
        if action != 'publish' or job.get('progress', {}).get('stage') != 'publish_attempted':
            return _uncertain('No durable publish intent; do not submit')
        response = self.transport('POST', f'https://graph.instagram.com/{GRAPH_VERSION}/{quote(manifest["providerAccountId"])}/media_publish', form={'creation_id': container, 'access_token': token})
        media_id = response.get('body', {}).get('id')
        if response.get('status') == 200 and isinstance(media_id, str) and media_id.isdigit():
            return {"state": "provider_accepted", "reference": media_id, "container": container,
                    "progress": {"version": 1, "stage": "provider_accepted"},
                    "confirmed": "Instagram accepted publication; canonical lookup pending"}
        # Even a rate-limit response here must not authorize a second publish.
        return _uncertain('Publish outcome not confirmed; check the platform; do not resubmit')

    # --- reconcile ----------------------------------------------------------------
    def reconcile(self, manifest, job):
        provider = self._provider(manifest)
        if provider is None:
            return _uncertain("Provider reconciliation is unavailable; do not resubmit")
        try:
            grant = self.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        except AlphaError as error:
            return _uncertain(f"Cannot reconcile without a valid grant: {error}")
        token, reference = grant["accessToken"], job.get("providerReference")
        try:
            if manifest["platform"] in WAVE1:
                return self._reconcile_wave1(manifest, provider, token, reference, job)
            if manifest["platform"] == "LinkedIn":
                if not reference or "r_member_social" not in grant["scopes"]:
                    return _uncertain("LinkedIn read scope unavailable; verify the exact post manually")
                response = self.transport("GET", "https://api.linkedin.com/rest/posts/" + quote(reference, safe=""), headers={"Linkedin-Version": LINKEDIN_VERSION, "X-Restli-Protocol-Version": "2.0.0", "Authorization": "Bearer " + token})
                body = response.get("body", {})
                if response.get("status") == 200 and body.get("lifecycleState") == "PUBLISHED" and little_plain(body.get("commentary") or "") == manifest["payload"]["text"]:
                    return {"state": "verified", "reference": reference, "confirmed": "LinkedIn reports the exact post as PUBLISHED", "verification": "provider_lookup"}
                if response.get("status") == 200 and body.get("lifecycleState") == "PUBLISH_FAILED":
                    return {"state": "failed", "confirmed": "LinkedIn reports PUBLISH_FAILED"}
                return _uncertain("LinkedIn lookup did not confirm the exact post")
            if manifest["platform"] in ("Threads", "Instagram"):
                base = "https://graph.threads.net" if manifest["platform"] == "Threads" else "https://graph.instagram.com"
                if reference:
                    fields = "id,text,permalink,owner" if manifest["platform"] == "Threads" else "id,caption,permalink,owner"
                    response = self.transport("GET", f"{base}/{GRAPH_VERSION}/{quote(reference)}?" + urlencode({"fields": fields, "access_token": token}))
                    body = response.get("body", {})
                    text_key = "text" if manifest["platform"] == "Threads" else "caption"
                    owner_matches = isinstance(body.get('owner'), dict) and str(body['owner'].get('id')) == manifest['providerAccountId']
                    if response.get("status") == 200 and owner_matches and str(body.get("id")) == str(reference) and body.get(text_key) == manifest["payload"]["text"] and str(body.get("permalink", "")).startswith("https://"):
                        return {"state": "verified", "reference": reference, "url": body["permalink"], "confirmed": "Provider lookup matched the approved text and account", "verification": "provider_lookup"}
                    return _uncertain("Provider lookup did not match the exact approved publication")
                container = job.get("container") or next((e.get("container") for e in reversed(job.get("events", [])) if e.get("container")), None)
                if container:
                    if manifest['platform'] == 'Instagram':
                        response = self.transport('GET', f'{base}/{GRAPH_VERSION}/{quote(str(container))}?' + urlencode({'fields': 'status_code', 'access_token': token}))
                        code = response.get('body', {}).get('status_code') if response.get('status') == 200 else None
                        return _uncertain('Container ' + str(code or 'lookup unavailable') + '; publish outcome requires manual review; do not resubmit')
                    response = self.transport("GET", f"{base}/{GRAPH_VERSION}/{quote(str(container))}?" + urlencode({"fields": "status_code,status", "access_token": token}))
                    code = response.get("body", {}).get("status_code") or response.get("body", {}).get("status")
                    if code == "PUBLISHED":
                        return {"state": "published", "confirmed": "Container reports PUBLISHED; media lookup pending"}
                    if code in ("ERROR", "EXPIRED"):
                        return {"state": "failed", "confirmed": f"Container reports {code}"}
                    return {"state": "provider_accepted", "confirmed": f"Container {code or 'pending'}"}
        except AlphaError as error:
            return _uncertain(f"Reconciliation request failed: {error}")
        return _uncertain("No reconciliation path for this platform")

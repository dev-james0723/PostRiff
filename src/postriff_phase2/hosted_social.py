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
from urllib.parse import quote, urlencode, urlsplit, parse_qs
from postriff_alpha.domain import AlphaError
from .atproto_oauth import tid
from .capabilities import HOSTED_PUBLISHERS
from .provider_candidates import LinkedInCandidate, little_plain
from .providers import GRAPH_VERSION, http_transport
from .outcomes import valid_receipt_url
from .social_connectors import multipart
from .mastodon_release import write_qualified as mastodon_write_qualified
from .wave3_connectors import provider_host

WAVE1 = ("Bluesky", "Mastodon", "Telegram", "Discord", "X")
WAVE3 = ("Facebook", "YouTube", "TikTok", "Pinterest")
_URL = re.compile(r"https?://[^\s<>\"]+")


def _provider_reason(body):
    """The provider's own short error text: first plain message field, control characters removed, at most 300 characters."""
    if not isinstance(body, dict):
        return ""
    nested = body.get("error") if isinstance(body.get("error"), dict) else {}  # Graph, Google and TikTok nest their errors
    candidates = [body.get(key) for key in ("detail", "message", "description", "error_description", "error", "title")] + [nested.get("message")]
    errors = body.get("errors") if isinstance(body.get("errors"), list) else nested.get("errors")
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
        pinterest = providers.get('pinterest')
        if getattr(pinterest, 'private_trial', False) is True:
            pinterest.private_trial_media_gate = self._pinterest_source_matches
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
        if provider is None or not getattr(provider, "execution_enabled", True):
            return None
        if manifest['platform'] == 'Mastodon' and not mastodon_write_qualified(provider):
            return None
        # Provider-wide review unlocks public accounts. Instagram Standard Access can also
        # issue a real grant to an app-role owned/managed account before Advanced Access;
        # that grant is checked again below against the exact required scopes.
        if manifest['platform'] == 'YouTube':
            return provider if getattr(provider, 'creator_enabled', False) else None
        private_trial = manifest['platform'] == 'Pinterest' and getattr(provider, 'private_trial', False) is True
        if private_trial:
            require_manifest = getattr(getattr(provider, 'trial_policy', None), 'require_manifest', None)
            if not callable(require_manifest):
                return None
            try:
                require_manifest(manifest)
            except (AlphaError, AttributeError, TypeError, ValueError):
                return None
        if not provider.production_reviewed and not private_trial and not getattr(provider, "account_scoped_direct", False):
            return None
        if getattr(provider, "publisher", None) is not None and (not getattr(provider, "publish_live_tested", False)
                or not getattr(provider, "publishing_permission", False)):
            return None
        return provider

    def _image_url(self, manifest):
        if not manifest.get("media"):
            return None
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        asset = manifest["media"][0]
        return self.assets.storage.signed_url(manifest["workspaceId"], "media", asset.get("objectName") or asset["id"], 600)

    def _pinterest_source_matches(self, manifest, source):
        """Bind the signed delivery path to the exact immutable approved asset."""
        try:
            from .pinterest_safety import https_url
            if not https_url(source) or self.assets is None or len(manifest.get('media') or []) != 1:
                return False
            storage, asset = self.assets.storage, manifest['media'][0]
            origin, actual = urlsplit(storage.project_url), urlsplit(source)
            object_name = asset.get('objectName') or asset['id']
            path = storage._path(manifest['workspaceId'], 'media', object_name)
            expected = '/storage/v1/object/sign/' + quote(storage._bucket('media')) + '/' + quote(path, safe='/')
            query = parse_qs(actual.query, keep_blank_values=True)
            return (actual.scheme == origin.scheme == 'https' and actual.netloc == origin.netloc
                    and actual.path == expected and not actual.fragment
                    and set(query) == {'token'} and len(query['token']) == 1 and bool(query['token'][0]))
        except (AlphaError, AttributeError, KeyError, TypeError, ValueError):
            return False

    # --- submit -------------------------------------------------------------------
    def submit(self, manifest, *, dispatch_context=None):
        if manifest.get('platform') == 'Discord':
            return {'state': 'held', 'confirmed': 'Discord requires a fenced, destination-bound human approval. Nothing was posted.',
                    'discordDeliveryEvidence': 'not_sent'}
        if manifest['platform'] == 'Mastodon':
            try:
                with self.oauth.mastodon_dispatch_fence(manifest['workspaceId'], manifest['channelId']):
                    return self._submit(manifest, dispatch_context=dispatch_context)
            except AlphaError as error:
                if error.code != 'mastodon_dispatch_busy':
                    raise
                return {'state': 'held', 'confirmed': str(error)}
        return self._submit(manifest, dispatch_context=dispatch_context)

    def _submit(self, manifest, *, dispatch_context=None):
        provider = self._provider(manifest)
        if provider is None:
            return {"state": "held", "confirmed": "Publishing to this platform isn't available yet. Nothing was posted."}
        if manifest['platform'] == 'YouTube':
            try:
                return self._submit_youtube(manifest, provider, None)
            except AlphaError as error:
                return {'state': 'held', 'confirmed': str(error)}
        grant = self.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        required = ({"LinkedIn": {"w_member_social"}, "Threads": {"threads_basic", "threads_content_publish"}, "Instagram": {"instagram_business_basic", "instagram_business_content_publish"}}.get(manifest["platform"])
                    or set(getattr(provider, "publish_required", ())))
        if not required or not required.issubset(grant.get("scopes", [])):
            return {"state": "held", "confirmed": "Publishing permissions changed or are unverified; reconnect and review again."}
        token = grant["accessToken"]
        if getattr(provider, "publisher", None) is not None and not getattr(provider, "write_qualified", lambda _token: True)(token):
            return {"state": "held", "confirmed": "This exact account or destination is not qualified for hosted publishing."}
        try:
            publisher = getattr(provider, "publisher", None)
            if publisher is not None:
                return publisher.submit(manifest, provider, token, self)
            if manifest["platform"] == "LinkedIn":
                return self._submit_linkedin(manifest, token)
            if manifest["platform"] == "Threads":
                return self._submit_threads(manifest, token)
            if manifest["platform"] == "Instagram":
                return self._submit_instagram(manifest, token)
            if manifest['platform'] == 'Pinterest':
                return self._submit_pinterest(manifest, provider, token, dispatch_context=dispatch_context)
            if manifest["platform"] in WAVE1 + WAVE3:
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
            return None, {"state": "held", "confirmed": f"Mastodon media {media_id} is still processing. No post was sent; automatic re-upload is stopped pending review."}
        return media_id, None

    def _submit_mastodon(self, manifest, provider, token):
        from .mastodon_protocol import discover, validate_status
        session = provider.session(token)
        capabilities = discover(provider.transport, session['instance'])
        attachments = manifest.get('media') or []
        body = validate_status(manifest['payload']['text'], manifest.get('publishOptions') or {}, attachments, capabilities)
        media_ids = []
        for asset in attachments:
            if self.assets is None:
                return {'state': 'held', 'confirmed': 'Media storage unavailable. Nothing was posted.'}
            mime = str(asset.get('mime') or '')
            supported = capabilities.get('media', {}).get('supported_mime_types')
            if supported is not None and mime not in supported:
                return {'state': 'failed', 'confirmed': 'This Mastodon server does not support the approved media format. Nothing was posted.'}
            if not mime.startswith(('image/', 'video/', 'audio/')):
                return {'state': 'failed', 'confirmed': 'Unsupported Mastodon media. Nothing was posted.'}
            from .mastodon_publishing import approved_bytes
            raw = approved_bytes(self, manifest, asset)
            if len(raw) != asset.get('bytes') or hashlib.sha256(raw).hexdigest() != asset.get('hash'):
                return {'state': 'held', 'confirmed': 'The stored media changed after approval. Nothing was uploaded or posted.'}
            limits = capabilities.get('media', {})
            maximum = limits.get('image_size_limit' if mime.startswith('image/') else 'audio_size_limit' if mime.startswith('audio/') else 'video_size_limit', 40_000_000)
            if type(maximum) is not int or len(raw) > maximum:
                return {'state': 'failed', 'confirmed': 'This attachment exceeds the Mastodon server media limit. Nothing was posted.'}
            media_id, outcome = self._mastodon_media(provider, session, (raw, mime, str(asset.get('alt') or '')))
            if outcome:
                return outcome
            media_ids.append(media_id)
        # Mastodon keeps an Idempotency-Key for an hour, so a retried request returns the same status.
        response = provider.api(session, "POST", "/api/v1/statuses", headers={"Idempotency-Key": hashlib.sha256(manifest["idempotencyKey"].encode()).hexdigest()},
                                body={**body, 'media_ids': media_ids})
        status_id = str(response.get("body", {}).get("id", "")) if isinstance(response.get("body"), dict) else ""
        if response.get("status") == 200 and status_id.isdigit():
            return {"state": "provider_accepted", "reference": status_id, "confirmed": "Mastodon created the post; read-back pending"}
        early = self._classify_status(response.get("status"), response.get("body"), "Mastodon")
        if early:
            return early
        return _uncertain("No conclusive Mastodon create response; do not resubmit")

    def advance_mastodon(self, manifest, job, checkpoint, clock=time.time):
        from .mastodon_publishing import advance, LocalCooldown
        try:
            with self.oauth.mastodon_dispatch_fence(manifest['workspaceId'], manifest['channelId']):
                return advance(self, manifest, job, checkpoint, clock)
        except LocalCooldown as wait:
            return wait.receipt
        except AlphaError as error:
            if error.code != 'mastodon_dispatch_busy':
                raise
            return {'state': 'held', 'confirmed': str(error),
                    **({'progress': job['progress']} if job.get('progress') else {})}

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

    def prepare_discord_dispatch(self, manifest, *, read_authorize=None):
        """Provider checks and immutable media reads outside all worker SQL locks."""
        from .discord.authorization import grant_matches, wire_content, digest
        provider = self._provider(manifest)
        if provider is None or not getattr(provider, 'authorization_v2_enabled', False):
            raise AlphaError('Discord publishing is paused pending authorization and rollout validation.', 409, code='discord_paused')
        grant = self.oauth.discord_grant_for_worker(manifest['workspaceId'], manifest['channelId'])
        if not grant_matches(manifest, grant, provider.session(grant['accessToken'])):
            raise AlphaError('Discord was reconnected or changed. Review the post again.', 409)
        wire = wire_content(manifest)
        if digest(wire) != manifest['discord']['wireDigest']:
            raise AlphaError('The approved Discord payload changed.', 409)
        if manifest.get('operation') == 'discord.reply' and not callable(read_authorize):
            raise AlphaError('Discord reply consent must be rechecked before provider reads.', 409)
        evidence = provider.authorize_destination(grant['accessToken'], manifest['discord']['target'], media=bool(wire['files']), read_authorize=read_authorize)
        if manifest.get('operation') == 'discord.reply':
            from .discord.engagement import validate_parent
            from .discord.message_content import verify as verify_content
            import time
            verify_content(provider, manifest['discord']['target'], manifest['engagementReply'], read_authorize, time.time())
            if not evidence.get('userPermissions', 0) & provider.READ_HISTORY:
                raise AlphaError('Discord reply history permission changed.', 409)
            parent = provider._json(provider._bot('GET', f"/channels/{manifest['discord']['target']['channelId']}/messages/{manifest['engagementReply']['parentMessageId']}", read_authorize=read_authorize), dict)
            validate_parent(manifest, parent)
        image = self._image(manifest)
        if image and (hashlib.sha256(image[0]).hexdigest() != wire['files'][0]['sha256']
                      or len(image[0]) != wire['files'][0]['bytes']):
            raise AlphaError('The Discord attachment bytes changed after approval. Nothing was posted.', 409)
        return {'grant': grant, 'evidence': evidence, 'image': image,
                'wireDigest': digest(wire), 'manifestDigest': digest(manifest)}

    def reserve_discord_send(self, manifest, *, job=None, workspace_id=None, worker_id=None):
        """Reserve cross-worker capacity outside SQL before sealing the durable intent."""
        from .discord.rate_limits import RateCoordinatorUnavailable, publish_binding
        provider = self._provider(manifest)
        if provider is None or not getattr(provider, 'authorization_v2_enabled', False):
            raise RateCoordinatorUnavailable()
        if not getattr(provider, 'rate_v1_enabled', False):
            return None  # only the historical feature-off synthetic path
        binding = publish_binding(job, workspace_id, worker_id)
        channel = manifest['discord']['target']['channelId']
        if manifest.get('senderKind') == 'webhook':
            from .discord.webhooks import path, require_enabled
            require_enabled(provider)
            grant = self.oauth.discord_grant_for_worker(manifest['workspaceId'], manifest['channelId'])
            session = provider.session(grant['accessToken'])
            from .discord.authorization import grant_matches
            if not grant_matches(manifest, grant, session):
                raise AlphaError('Discord webhook grant changed.', 409)
            return provider.rate_limiter.reserve('POST', path(session, execute=True),
                identity=provider._rate_identity('webhook', session['secret']), binding=binding,
                valid_until=min(job['leaseUntil'], manifest['expiresAt']))
        return provider.admit_bot_request('POST', f'/channels/{channel}/messages', binding=binding,
                                         valid_until=min(job['leaseUntil'],manifest['expiresAt']))

    def discord_read_attempt_limit(self):
        provider = self.providers.get('discord')
        policy = getattr(getattr(provider,'rate_limiter',None),'policy',None)
        return policy.read_attempts if policy is not None else 1

    def submit_discord_authorized(self, manifest, dispatch):
        """Private worker entry point. An ordinary submit cannot reach Discord POST."""
        provider = self._provider(manifest)
        if provider is None:
            return {'state': 'held', 'confirmed': 'Discord transport is unavailable. Nothing was posted.', 'discordDeliveryEvidence': 'not_sent'}
        return self._submit_discord(manifest, provider, dispatch['grant']['accessToken'], dispatch)

    def _submit_discord(self, manifest, provider, token, dispatch=None):
        from .discord.authorization import grant_matches, wire_content, digest, snowflake
        from .discord.rate_limits import Permit, RateDelayed, UnconsumedPublishPermit
        if (not dispatch or not getattr(provider, 'authorization_v2_enabled', False)
                or (getattr(provider, 'rate_v1_enabled', False)
                    and (not isinstance(dispatch.get('ratePermit'), Permit)
                         or not dispatch['ratePermit'].binding_hash
                         or not callable(dispatch.get('rateAuthorize'))))
                or dispatch.get('manifestDigest') != digest(manifest)
                or dispatch.get('wireDigest') != manifest.get('discord', {}).get('wireDigest')
                or dispatch.get('intent', {}).get('manifestDigest') != digest(manifest)
                or dispatch.get('intent', {}).get('publicationId') != manifest.get('discord', {}).get('publicationId')
                or not grant_matches(manifest, dispatch.get('grant', {}), provider.session(token))):
            return {'state': 'held', 'confirmed': 'Discord dispatch authorization is missing or stale. Nothing was posted.', 'discordDeliveryEvidence': 'not_sent'}
        target = manifest['discord']['target']
        channel = target['channelId']
        wire = wire_content(manifest)
        # Discord dedupes nonces only over a recent window. Durable Rafii intents
        # block a fresh POST after an ambiguous result, including beyond that window.
        payload = {'content': wire['content'], 'allowed_mentions': wire['allowed_mentions'],
                   'nonce': hashlib.sha256(manifest['idempotencyKey'].encode()).hexdigest()[:25], 'enforce_nonce': True}
        if 'message_reference' in wire:
            payload['message_reference'] = wire['message_reference']
        image = dispatch.get('image')
        rate_arguments = {'rate_permit':dispatch.get('ratePermit'), 'rate_binding':dispatch.get('rateBinding'),
                          'rate_intent_id':dispatch['intent']['id'], 'rate_authorize':dispatch.get('rateAuthorize')}
        try:
            if manifest.get('senderKind') == 'webhook':
                from .discord.webhooks import request
                response = request(provider, 'POST', provider.session(token),
                    body={**{k: wire[k] for k in ('content', 'allowed_mentions', 'flags')},
                          **({'username': wire['username']} if 'username' in wire else {})}, **rate_arguments)
            elif image:
                raw, mime, _alt = image
                file = wire['files'][0]
                if hashlib.sha256(raw).hexdigest() != file['sha256'] or len(raw) != file['bytes']:
                    return {'state': 'held', 'confirmed': 'Discord attachment changed. Nothing was posted.', 'discordDeliveryEvidence': 'not_sent'}
                attachment = {k: file[k] for k in ('id', 'filename', 'description')}
                body, content_type = multipart([('payload_json', json.dumps({**payload, 'attachments': [attachment]}))],
                                               [('files[0]', file['filename'], mime, raw)])
                response = provider._bot('POST', f'/channels/{channel}/messages', headers={'Content-Type': content_type}, data=body, **rate_arguments)
            else:
                response = provider._bot('POST', f'/channels/{channel}/messages', body=payload, **rate_arguments)
        except UnconsumedPublishPermit:
            raise  # Only the fenced worker can verify and archive unsent intent.
        except RateDelayed:
            # No HTTP call occurred, but the P0 intent was already sealed.
            # Keep it for manual reconciliation rather than make another POST.
            return {'state': 'uncertain', 'confirmed': 'Discord reserved rate slot expired after sealing. No POST was started; manual review required before any fresh approval.', 'discordDeliveryEvidence': 'uncertain'}
        except Exception:
            return {'state': 'uncertain', 'confirmed': 'Discord delivery is uncertain. Reconcile before any further publication.', 'discordDeliveryEvidence': 'uncertain'}
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        message_id = str(body.get('id', ''))
        if response.get('status') == 200 and snowflake(message_id):
            receipt = {'reference': f'{channel}/{message_id}',
                       'url': f"https://discord.com/channels/{target['guildId']}/{channel}/{message_id}",
                       'discordDeliveryEvidence': 'accepted'}
            if manifest.get('senderKind') == 'webhook':
                from .discord.webhooks import message_matches
                if not message_matches(body, manifest, message_id):
                    return {**receipt, 'state': 'uncertain', 'confirmed': 'Discord webhook receipt differs from approval. Do not resubmit.'}
                return {**receipt, 'state': 'provider_accepted', 'confirmed': 'Discord webhook created the approved message; read-back pending.'}
            if (body.get('channel_id') != channel or body.get('content') != wire['content']
                    or (body.get('author') or {}).get('id') != target['botUserId']
                    or ('message_reference' in wire and not self._discord_reply_reference_matches(body, manifest))):
                return {**receipt, 'state': 'uncertain', 'confirmed': 'Discord returned a message with unexpected identity, destination or text. Review the receipt; do not resubmit.'}
            return {**receipt, 'state': 'provider_accepted', 'confirmed': 'Discord created the approved channel message; read-back pending'}
        status = response.get('status')
        if status == 429:
            # Shared cooldown is recorded by DiscordProvider; the POST was
            # attempted, so P0 never silently resubmits this publication.
            return {'state': 'held', 'discordDeliveryEvidence': 'rejected',
                    'discordRateLimited': True,
                    'confirmed': 'Discord returned HTTP 429. The shared cooldown was recorded; this approved publication will not be automatically reposted.'}
        if status in (400, 401, 403, 404):
            return {'state': 'failed' if status == 400 else 'held', 'discordDeliveryEvidence': 'rejected',
                    'confirmed': 'Discord rejected the message before acceptance. Restore permission or review configuration and approve again.'}
        return {'state': 'uncertain', 'confirmed': 'No conclusive Discord create response; reconcile without resubmitting.', 'discordDeliveryEvidence': 'uncertain'}

    @staticmethod
    def _discord_reply_reference_matches(body, manifest):
        reference = body.get('message_reference')
        target = manifest['discord']['target']
        return (isinstance(reference, dict) and reference.get('type', 0) == 0
                and reference.get('message_id') == manifest['engagementReply']['parentMessageId']
                and reference.get('channel_id') == target['channelId']
                and reference.get('guild_id', target['guildId']) == target['guildId']
                and body.get('type') == 19)

    def reconcile_discord(self, manifest, job, *, read_authorize=None):
        """Only GET a known message in the original channel; never use the default."""
        from .discord.authorization import SCHEMA, wire_content, digest, snowflake
        from .discord.rate_limits import RateDelayed, ReadAdmissionDelayed
        frozen = manifest.get('discord') or {}
        target = frozen.get('target') or {}
        reference = job.get('providerReference')
        if frozen.get('schema') != SCHEMA or not isinstance(reference, str):
            return _uncertain('The original Discord target or message ID is missing. Manual reconciliation required; do not resubmit.')
        channel, separator, message_id = reference.partition('/')
        if not separator or channel != target.get('channelId') or not snowflake(message_id):
            return _uncertain('The Discord receipt does not match the approved channel. Do not resubmit.')
        provider = self.providers.get('discord')
        if (not provider or provider.client_id != target.get('applicationId')
                or not getattr(provider, 'execution_enabled', True)):
            return _uncertain('The original Discord application is unavailable. Keep the receipt for manual review.')
        try:
            if manifest.get('operation') == 'discord.reply':
                if not callable(read_authorize) or read_authorize() is not True:
                    raise AlphaError('Discord reply read consent is unavailable.', 409)
                grant = self.oauth.discord_grant_for_worker(manifest['workspaceId'], manifest['channelId'])
                evidence = provider.authorize_destination(grant['accessToken'], target, read_authorize=read_authorize)
                if not evidence.get('userPermissions', 0) & provider.READ_HISTORY:
                    raise AlphaError('Discord history permission changed.', 409)
            if manifest.get('senderKind') == 'webhook':
                from .discord.webhooks import request, verify, message_matches
                from .discord.authorization import grant_matches
                grant = self.oauth.discord_grant_for_worker(manifest['workspaceId'], manifest['channelId'])
                session = provider.session(grant['accessToken'])
                if not grant_matches(manifest, grant, session):
                    return _uncertain('The original webhook authorization changed. Keep the receipt; do not resubmit.')
                verify(provider, session)
                response = request(provider, 'GET', session, message=message_id)
                if (digest(wire_content(manifest)) != frozen['wireDigest'] or response.get('status') != 200
                        or not message_matches(response.get('body'), manifest, message_id)):
                    return _uncertain('Discord webhook read-back differs from the approved sender, target, text or mention policy.')
                return {'state': 'verified', 'reference': reference, 'verification': 'provider_lookup',
                        'url': f"https://discord.com/channels/{target['guildId']}/{channel}/{message_id}",
                        'confirmed': 'Discord webhook message read back with exact sender, channel and text.', 'discordDeliveryEvidence': 'accepted'}
            if provider._bot_identity(read_authorize=read_authorize) != target.get('botUserId'):
                return _uncertain('Discord bot identity changed; keep the original receipt for review.')
            response = provider._bot('GET', f'/channels/{channel}/messages/{message_id}', read_authorize=read_authorize)
            if read_authorize is not None and read_authorize() is not True:
                raise AlphaError('Discord reply read consent changed during lookup.', 409)
            body = response.get('body') if isinstance(response.get('body'), dict) else {}
            wire = wire_content(manifest)
            if (digest(wire) != frozen['wireDigest'] or response.get('status') != 200
                    or body.get('id') != message_id or body.get('channel_id') != channel
                    or (body.get('author') or {}).get('id') != target['botUserId']
                    or (body.get('author') or {}).get('bot') is not True
                    or body.get('content') != wire['content'] or body.get('mention_everyone') is not False
                    or body.get('mentions') != [] or body.get('mention_roles') != []
                    or ('message_reference' in wire and not self._discord_reply_reference_matches(body, manifest))):
                return _uncertain('Discord read-back did not match the approved message, author, channel and mention policy.')
            # Discord attachment metadata does not prove the original byte hash.
            # Keep media receipts pending rather than overstating verification.
            if wire['files'] or body.get('attachments') != []:
                return {**_uncertain('Discord media delivery needs byte-level reconciliation; do not resubmit.'), 'reference': reference}
            return {'state': 'verified', 'reference': reference, 'verification': 'provider_lookup',
                    'url': f"https://discord.com/channels/{target['guildId']}/{channel}/{message_id}",
                    'confirmed': 'Discord read-back matched the approved text, bot, channel and mention policy.', 'discordDeliveryEvidence': 'accepted'}
        except RateDelayed as error:
            # A denied GET cannot undo an existing create receipt. Resume only
            # this exact lookup, preserving the message ID and frozen target.
            import math
            return {'state': 'provider_accepted', 'reference': reference,
                    'confirmed': 'Discord message receipt retained; awaiting shared capacity for the exact read-back. Do not resubmit.',
                    'discordDeliveryEvidence': 'accepted', 'discordReadDeferred': True,
                    'discordReadAdmissionDenied': isinstance(error, ReadAdmissionDelayed),
                    'retryAfterSeconds': max(1, math.ceil(error.retry_after_seconds))}
        except (AlphaError, KeyError, TypeError, ValueError):
            return _uncertain('Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.')

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

    def reconcile_mastodon_thread(self, manifest, job, checkpoint, clock=time.time):
        from .mastodon_publishing import checked_progress
        from .mastodon_threads import reconcile
        provider = self._provider(manifest)
        if provider is None: return {'state': 'held', 'confirmed': 'Mastodon is unavailable; saved thread IDs were retained.'}
        try:
            grant = self.oauth.token_for_worker(manifest['workspaceId'], manifest['channelId'])
        except AlphaError as error:
            from .mastodon_publishing import grant_retry
            result = grant_retry(manifest, job, clock(), error)
            if result.get('progress'): checkpoint(result['progress'], before_external=False)
            return result
        if grant.get('providerAccountId') != manifest.get('providerAccountId'):
            return {'state': 'held', 'confirmed': 'The connected thread account changed. Reconnect and inspect saved IDs.'}
        return reconcile(provider, grant, manifest, checked_progress(job['progress'], manifest), checkpoint, clock)

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
            if (job or {}).get('progress', {}).get('version') == 3 and job['progress'].get('stage') == 'native_scheduled':
                from .mastodon_publishing import native_reconcile
                return native_reconcile(provider, token, manifest, job, self.oauth.clock() if hasattr(self.oauth, 'clock') else time.time())
            from .mastodon_protocol import ID
            if not isinstance(reference, str) or not ID.fullmatch(reference):
                return _uncertain('Invalid Mastodon post reference; do not resubmit')
            session = provider.session(token)
            response = provider.api(session, "GET", "/api/v1/statuses/" + quote(reference))
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            account = str((body.get("account") or {}).get("id", ""))
            # Tags go before entities are decoded, so literal "<" typed in a post survives the comparison.
            plain = " ".join(html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>|</p>\s*<p>", " ", str(body.get("content") or "")))).split())
            options = manifest.get('publishOptions') or {}
            visibility_matches = body.get('visibility', 'public') == options.get('visibility', 'public')
            warning_matches = body.get('spoiler_text', '') == options.get('spoiler_text', '')
            sensitive_matches = body.get('sensitive', False) == options.get('sensitive', False)
            reply_matches = not options.get('in_reply_to_id') or str(body.get('in_reply_to_id')) == options['in_reply_to_id']
            progress = (job or {}).get('progress') or {}
            media_matches = progress.get('version') != 3 or [str(a.get('id')) for a in body.get('media_attachments') or [] if isinstance(a, dict)] == [a.get('id') for a in progress.get('attachments', [])]
            exact_matches = (str(body.get('id')) == reference
                    and f"{account}@{session['instance']}" == manifest['providerAccountId']
                    and plain == ' '.join(text.split())
                    and visibility_matches and warning_matches and sensitive_matches and reply_matches and media_matches)
            if progress.get('version') == 3:
                from .mastodon_threads import matches
                exact_matches = matches(body, manifest, [reference], 0, session['instance'], progress.get('attachments', []))
            if response.get('status') == 200 and exact_matches:
                result = {"state": "verified", "reference": reference, "confirmed": "Mastodon read-back matched the approved text, visibility, warning and account", "verification": "provider_lookup"}
                url = body.get('url')
                if isinstance(url, str) and url.startswith('https://' + session['instance'] + '/'):
                    result['url'] = url
                return result
            return _uncertain("Mastodon read-back did not match the exact approved post")
        if platform == 'Discord':
            return self.reconcile_discord(manifest, {**(job or {}), 'providerReference': reference})
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

    # --- Wave 3 publishers (Facebook Pages, YouTube, TikTok, Pinterest) -----------------------------------------
    def _facebook_rejection(self, response):
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        code, reason = error.get("code"), _provider_reason(body)
        if code in (102, 190) or code in (10, 200, 283, 299) or (isinstance(code, int) and 200 <= code <= 299):
            return {"state": "held", "confirmed": "Facebook rejected the Page permission or session; reconnect and review again" + (f" ({reason})" if reason else "")}
        if code in (4, 17, 32, 613):
            return {"state": "scheduled", "confirmed": "Facebook rate limited the request before acceptance"}
        if code == 368:
            return {"state": "held", "confirmed": "Facebook has temporarily blocked posting from this Page" + (f" ({reason})" if reason else "")}
        return self._classify_status(response.get("status"), body, "Facebook")

    def _submit_facebook(self, manifest, provider, token):
        refusal = self._unsupported_media(manifest)
        if refusal:
            return refusal
        session = provider.session(token)
        page = session.get("page")
        if not isinstance(page, dict):
            return {"state": "held", "confirmed": "Choose the Facebook Page for this account first. Nothing was posted."}
        text = manifest["payload"]["text"]
        # Rafii's worker runs at the approved time, so the post is published now, never scheduled on Facebook.
        if manifest.get("media"):
            response = provider.graph("POST", f"/{page['id']}/photos", page["token"], form={"url": self._image_url(manifest), "caption": text})
        else:
            response = provider.graph("POST", f"/{page['id']}/feed", page["token"], form={"message": text})
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        # A photo answers with its own id and, once on the Page, the Page post's id: the post id is the one to read back.
        post_id = str(body.get("post_id") or body.get("id") or "")
        if response.get("status") == 200 and re.fullmatch(r"\d{5,25}_\d{5,30}|\d{5,30}", post_id):
            return {"state": "provider_accepted", "reference": post_id, "confirmed": "Facebook created the Page post; read-back pending"}
        return self._facebook_rejection(response) or _uncertain("No conclusive Facebook create response; do not resubmit")


    def _video(self, manifest):
        media = manifest.get("media") or []
        if len(media) != 1 or media[0].get("mime") not in ("video/mp4", "video/quicktime"):
            return None, {"state": "failed", "confirmed": f"{manifest['platform']} needs exactly one verified video. Nothing was posted."}
        if self.assets is None:
            return None, {"state": "held", "confirmed": "Approved video storage is unavailable. Nothing was posted."}
        asset = media[0]
        storage = self.assets.storage
        verified = asset.get("verified") if isinstance(asset.get("verified"), dict) else {}
        if (asset.get("bucket") != storage.video_bucket or verified.get("container") is not True
                or verified.get("locationChecked") is not True or asset.get("durationSource") != "container"):
            return None, {"state": "held", "confirmed": "This video needs a fresh storage verification and review. Nothing was posted."}
        try:
            raw = storage.get_verified_video(manifest["workspaceId"], asset.get("objectName"),
                                             expected_bytes=asset.get("bytes"), expected_mime=asset["mime"],
                                             expected_etag=asset.get("etag"))
        except AlphaError:
            return None, {"state": "held", "confirmed": "Approved video bytes are unavailable or changed. Nothing was posted; review the video again."}
        return (raw, asset), None

    def _video_stream(self, manifest):
        """Wave 4 video route: verify the immutable object and return a bounded iterator."""
        media = manifest.get("media") or []
        if len(media) != 1 or media[0].get("mime") != "video/mp4" or self.assets is None:
            raise AlphaError("This post needs one approved MP4 video.", 409)
        asset = media[0]
        storage = self.assets.storage
        verified = asset.get("verified") if isinstance(asset.get("verified"), dict) else {}
        duration = asset.get("duration")
        if (asset.get("bucket") != storage.video_bucket or verified.get("container") is not True
                or verified.get("locationChecked") is not True or asset.get("durationSource") != "container"
                or type(duration) not in (int, float) or not 0 < duration <= 180):
            raise AlphaError("This video needs fresh storage and duration verification.", 409)
        return storage.iter_verified_video(manifest["workspaceId"], asset.get("objectName"),
                                           expected_bytes=asset.get("bytes"), expected_mime="video/mp4",
                                           expected_etag=asset.get("etag")), asset

    def _submit_youtube(self, manifest, provider, token):
        if not getattr(self, "youtube", None):
            return {"state": "held", "confirmed": "Durable YouTube creator execution is unavailable. Nothing was uploaded."}
        return self.youtube.upload(manifest)

    def _tiktok_rejection(self, status, error):
        code, message = error.get("code"), error.get("message") if isinstance(error.get("message"), str) else ""
        reason = f" ({message[:200]})" if message else ""
        if code in ("access_token_invalid", "scope_not_authorized", "scope_permission_missed") or status == 401:
            return {"state": "held", "confirmed": "TikTok rejected the permission or session; reconnect and review again" + reason}
        if code == "rate_limit_exceeded" or status == 429:
            return {"state": "scheduled", "confirmed": "TikTok rate limited the request before acceptance"}
        if code in ("spam_risk_too_many_posts", "spam_risk_too_many_pending_share", "spam_risk_user_banned_from_posting", "reached_active_user_cap"):
            return {"state": "held", "confirmed": "TikTok won't take more posts from this account right now" + reason}
        if code == "unaudited_client_can_only_post_to_private_accounts":
            return {"state": "failed", "confirmed": "Until TikTok audits Rafii, it can post only to private TikTok accounts. Make the account private or wait for the audit; nothing was posted."}
        if code == "privacy_level_option_mismatch":
            return {"state": "held", "confirmed": "TikTok no longer offers the chosen privacy setting for this account. Review the post again; nothing was posted."}
        if isinstance(status, int) and 400 <= status < 500:
            return {"state": "failed", "confirmed": "TikTok rejected the post; nothing was published" + (f": {message[:300]}" if message else ".")}
        return None

    def _submit_tiktok(self, manifest, provider, token):
        options = manifest.get("publishOptions") or {}
        if options.get("privacyLevel") is None or options.get("consent") is not True:
            return {"state": "failed", "confirmed": "This post has no TikTok privacy choice or consent. Review it again; nothing was posted."}
        video, refusal = self._video(manifest)
        if refusal:
            return refusal
        raw, media = video
        # Guidelines: read the creator's current settings again right before posting.
        info = provider.creator_info(token)
        if not info.get("ok"):
            return self._tiktok_rejection(info.get("status"), {"code": info.get("code"), "message": info.get("message")}) or \
                _uncertain("TikTok did not confirm this account's posting settings; nothing was posted")
        if options["privacyLevel"] not in info["privacyLevelOptions"]:
            return {"state": "held", "confirmed": "TikTok no longer offers the chosen privacy setting for this account. Review the post again; nothing was posted."}
        limit = info.get("maxVideoPostDurationSec")
        if isinstance(limit, int) and float(media.get("duration") or 0) > limit:
            return {"state": "failed", "confirmed": f"This video is longer than TikTok allows this account ({limit} seconds). Nothing was posted."}
        commercial = options.get("commercial") or {}
        chunk, count = provider.chunks(len(raw))
        opened = provider.api(token, "POST", "/v2/post/publish/video/init/", body={
            "post_info": {"title": manifest["payload"]["text"], "privacy_level": options["privacyLevel"],
                          # A setting the creator turned off stays off whatever the post allowed.
                          "disable_comment": options.get("allowComment") is not True or info["commentDisabled"],
                          "disable_duet": options.get("allowDuet") is not True or info["duetDisabled"],
                          "disable_stitch": options.get("allowStitch") is not True or info["stitchDisabled"],
                          "brand_content_toggle": commercial.get("brandedContent") is True, "brand_organic_toggle": commercial.get("yourBrand") is True},
            "source_info": {"source": "FILE_UPLOAD", "video_size": len(raw), "chunk_size": chunk, "total_chunk_count": count}})
        body = opened.get("body") if isinstance(opened.get("body"), dict) else {}
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if opened.get("status") != 200 or error.get("code") not in (None, "ok") or not isinstance(publish_id, str) or not isinstance(upload_url, str):
            return self._tiktok_rejection(opened.get("status"), error) or {"state": "failed", "confirmed": "TikTok did not start the upload, so nothing was posted."}
        try:
            provider_host(upload_url, provider.UPLOAD_HOSTS)
        except AlphaError:
            return {"state": "failed", "confirmed": "TikTok returned an upload address outside TikTok's own hosts, so Rafii sent nothing. Nothing was posted."}
        for index in range(count):
            start = index * chunk
            end = len(raw) if index == count - 1 else start + chunk
            try:
                sent = provider.transport("PUT", upload_url, headers={"Content-Type": str(media.get("mime")), "Content-Range": f"bytes {start}-{end - 1}/{len(raw)}"}, data=raw[start:end])
            except AlphaError:
                sent = {"status": None}
            if sent.get("status") not in (200, 201, 206):
                return {**_uncertain("The video upload to TikTok was interrupted; reconcile by publish id; do not resubmit"), "reference": publish_id}
        private = " Until TikTok audits Rafii, the post is private: only you can see it." if options["privacyLevel"] != "SELF_ONLY" else ""
        return {"state": "provider_accepted", "reference": publish_id, "confirmed": "TikTok received the video and is processing it; it may take a few minutes." + private}

    def _submit_pinterest(self, manifest, provider, token, *, dispatch_context=None):
        from .publish_options import normalize
        from .pinterest_safety import https_url
        options = manifest.get("publishOptions") or {}
        media = manifest.get("media") or []
        def preflight_error(error):
            if error.code == 'pinterest_rate_limited':
                return {'state':'scheduled', 'pinterestBudgetDeferred':True,
                        'confirmed':'Pinterest request budget reached before publication. This approved Pin waits for the next window; nothing was posted.'}
            return {'state':'held', 'confirmed':str(error)}
        try:
            canonical = normalize('Pinterest', options, media, manifest['payload']['text'])
            if canonical != options:
                return {'state': 'held', 'confirmed': 'Pin choices changed. Review the exact Pin again; nothing was posted.'}
            if provider.identity(token)['providerAccountId'] != manifest.get('providerAccountId'):
                return {'state': 'held', 'confirmed': 'The Pinterest account changed. Reconnect and review again; nothing was posted.'}
        except AlphaError as error:
            return preflight_error(error)
        # The board must be one of this person's own boards (the composer offers only those; it may have gone since).
        try:
            if options["boardId"] not in {board["id"] for board in provider.destinations(token) if board.get('eligible')}:
                return {"state": "failed", "confirmed": "That board isn't one of this Pinterest account's boards any more. Choose another board and review the Pin again; nothing was posted."}
            section = options.get('boardSectionId')
            if section and section not in {s['id'] for s in provider.sections(token, options['boardId'])}:
                return {'state': 'failed', 'confirmed': 'This section is unavailable on the chosen board. Review again; nothing was posted.'}
            source = self._image_url(manifest)
        except AlphaError as error:
            return preflight_error(error)
        if not https_url(source):
            return {'state': 'held', 'confirmed': 'The approved image has no usable HTTPS source. Upload it again; nothing was posted.'}
        pin = {"board_id": options["boardId"], "description": manifest["payload"]["text"], "media_source": {"source_type": "image_url", "url": source}}
        if section:
            pin['board_section_id'] = section
        if options.get("title"):
            pin["title"] = options["title"]
        if options.get("link"):
            pin["link"] = options["link"]
        if media[0].get("alt"):
            pin["alt_text"] = media[0]["alt"]
        dispatch = getattr(self.oauth, 'pinterest_dispatch', None)
        if dispatch is None:
            return {'state': 'held', 'confirmed': 'Pinterest dispatch fencing is unavailable. Nothing was posted.'}
        attempted = False
        try:
            trial_context = {'trial_pin': pin} if getattr(provider, 'private_trial', False) is True else {}
            with dispatch(manifest, token, dispatch_context, **trial_context) as proof:
                attempted = True
                response = provider.api(token, 'POST', '/v5/pins', content=True, body=pin)
                accepted = response.get('body') if isinstance(response.get('body'), dict) else {}
                candidate_id = str(accepted.get('id') or '')
                if response.get('status') in (200, 201) and re.fullmatch(r'\d{5,30}', candidate_id):
                    proof['pinId'] = candidate_id
        except AlphaError as error:
            if attempted and error.code not in ('pinterest_rate_limited', 'pinterest_quota_unavailable', 'pinterest_trial_intent_consumed', 'pinterest_trial_denied', 'pinterest_trial_account_mismatch', 'pinterest_oauth_binding_changed'):
                return _uncertain('Pinterest submission was interrupted. Check the board and reconcile; do not resubmit.')
            return preflight_error(error)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        pin_id = str(body.get("id") or "")
        if response.get("status") in (200, 201) and re.fullmatch(r"\d{5,30}", pin_id):
            visibility = ('creator_only_trial' if getattr(provider, 'private_trial', False) is True
                          else 'creator_only_sandbox' if provider.sandbox else 'unverified')
            detail = ' as a creator-only Trial Pin' if visibility == 'creator_only_trial' else ' in its sandbox (Trial access)' if provider.sandbox else ''
            return {"state": "provider_accepted", "reference": pin_id, 'visibility': visibility,
                    "confirmed": "Pinterest created the Pin" + detail + "; read-back pending"}
        # Pinterest error bodies are untrusted and can echo secrets or personal data.
        reason = ''
        if response.get("status") == 404:
            return {"state": "failed", "confirmed": "Pinterest can't find that board, so nothing was posted" + (f" ({reason})" if reason else "") + ". Choose another board and review the Pin again."}
        if response.get("status") == 403:
            return {"state": "failed", "confirmed": "Pinterest won't let this account pin to that board, so nothing was posted" + (f" ({reason})" if reason else "") + ". Choose another board and review the Pin again."}
        return self._classify_status(response.get("status"), {}, "Pinterest") or _uncertain("No conclusive Pinterest create response; do not resubmit")

    def _reconcile_wave3(self, manifest, provider, token, reference, job=None):
        platform, text = manifest["platform"], manifest["payload"]["text"]
        options = manifest.get("publishOptions") or {}
        if platform == "Facebook":
            session = provider.session(token)
            page = session.get("page") if isinstance(session.get("page"), dict) else None
            if not reference or not page:
                return _uncertain("No Facebook reference or Page was recorded; check the Page; do not resubmit")
            if "_" not in reference:
                # A bare photo id: a photo carries its caption as `name` and links to its Page post through page_story_id.
                response = provider.graph("GET", f"/{reference}", page["token"], {"fields": "id,name,page_story_id,from"})
                body = response.get("body") if isinstance(response.get("body"), dict) else {}
                if response.get("status") == 200 and str((body.get("from") or {}).get("id")) == page["id"] and body.get("name") == text:
                    story = str(body.get("page_story_id") or "")
                    return {"state": "verified", "reference": story if re.fullmatch(r"\d{5,25}_\d{5,30}", story) else reference,
                            "confirmed": "Facebook read-back matched the approved photo caption and Page", "verification": "provider_lookup"}
                return _uncertain("Facebook read-back did not match the exact approved photo")
            response = provider.graph("GET", f"/{reference}", page["token"], {"fields": "id,message,is_published,permalink_url,from"})
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            if response.get("status") != 200 or str((body.get("from") or {}).get("id")) != page["id"] or body.get("message") != text:
                return _uncertain("Facebook read-back did not match the exact approved post")
            if body.get("is_published") is False:
                return _uncertain("Facebook holds the post but shows it as unpublished; check the Page; do not resubmit")
            result = {"state": "verified", "reference": reference, "confirmed": "Facebook read-back matched the approved text and Page", "verification": "provider_lookup"}
            permalink = body.get("permalink_url")
            if valid_receipt_url(permalink, "Facebook"):
                result["url"] = permalink
            return result
        if platform == "YouTube":
            if not getattr(self, 'youtube', None):
                return _uncertain('Durable YouTube reconciliation is unavailable; do not resubmit')
            if (job or {}).get('progress', {}).get('version') != 2:
                # A legacy reference has no resumable journal. Re-entering submit could duplicate a video.
                return self.youtube.reconcile_legacy(manifest, reference)
            return self.youtube.upload(manifest, cancel=bool((job or {}).get('cancelRequested')), reconciliation=True)
        if platform == "TikTok":
            if not reference:
                return _uncertain("No TikTok publish id was recorded; check the account; do not resubmit")
            response = provider.api(token, "POST", "/v2/post/publish/status/fetch/", body={"publish_id": reference})
            data = response.get("body", {}).get("data") if isinstance(response.get("body"), dict) else None
            state = data.get("status") if isinstance(data, dict) else None
            if response.get("status") == 200 and state == "PUBLISH_COMPLETE":
                return {"state": "verified", "reference": reference, "verification": "provider_lookup",
                        "confirmed": "TikTok reports the post complete" + (" (private until TikTok audits Rafii)" if options.get("privacyLevel") != "SELF_ONLY" else "")}
            if response.get("status") == 200 and state in ("PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX"):
                return {"state": "provider_accepted", "reference": reference, "confirmed": "TikTok is still processing the video"}
            if response.get("status") == 200 and state == "FAILED":
                reason = data.get("fail_reason")
                return {"state": "failed", "reference": reference, "verification": "provider_lookup",
                        "confirmed": "TikTok reports the post failed" + (f" ({reason})" if isinstance(reason, str) and reason else "") + "."}
            return _uncertain("TikTok did not report this post's status; check the account")
        if platform == "Pinterest":
            if not reference and getattr(provider, 'private_trial', False) is True:
                recover = getattr(provider, 'private_trial_recover_reference', None)
                try:
                    if callable(recover):
                        reference = recover(provider.trial_policy, manifest.get('idempotencyKey'))
                except AlphaError:
                    return _uncertain('The private Trial response journal is unavailable. Reconcile later; do not resubmit.')
            if not isinstance(reference, str) or not re.fullmatch(r'\d{5,30}', reference):
                return _uncertain("No Pin id was recorded; check the board; do not resubmit")
            if provider.identity(token)['providerAccountId'] != manifest.get('providerAccountId'):
                return _uncertain('The Pinterest account changed. No write or retry is authorized.')
            response = provider.api(token, "GET", f"/v5/pins/{quote(reference)}", content=True)
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            matches = (str(body.get('id')) == reference and str(body.get('board_id')) == options.get('boardId')
                       and body.get('description') == text and (body.get('title') or '') == options.get('title', '')
                       and (body.get('link') or '') == options.get('link', '')
                       and (body.get('board_section_id') or '') == options.get('boardSectionId', '')
                       and isinstance(body.get('media'), dict) and body['media'].get('media_type') == 'image')
            if response.get("status") == 200 and matches:
                visibility = ('creator_only_trial' if getattr(provider, 'private_trial', False) is True
                              else 'creator_only_sandbox' if provider.sandbox else 'unverified')
                detail = (' Creator-only Trial visibility applies.' if visibility == 'creator_only_trial'
                          else ' Creator-only Sandbox visibility applies.' if provider.sandbox
                          else ' Public visibility has not been verified.')
                result = {"state": "verified", "reference": reference,
                          "confirmed": "Pinterest API read-back matched the approved Pin, account, board and metadata." + detail,
                          "verification": "provider_lookup", 'visibility': visibility}
                if not provider.sandbox:
                    result["url"] = f"https://www.pinterest.com/pin/{reference}/"
                return result
            return _uncertain("Pinterest read-back did not match the exact approved Pin")
        return _uncertain("No reconciliation path for this platform")


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
        if manifest.get('platform') == 'Discord':
            return self.reconcile_discord(manifest, job)
        provider = self._provider(manifest)
        if provider is None:
            return _uncertain("Provider reconciliation is unavailable; do not resubmit")
        try:
            grant = self.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        except AlphaError as error:
            if manifest['platform'] == 'Mastodon':
                from .mastodon_publishing import grant_retry
                return grant_retry(manifest, job, self.oauth.clock() if hasattr(self.oauth, 'clock') else time.time(), error)
            return _uncertain(f"Cannot reconcile without a valid grant: {error}")
        token, reference = grant["accessToken"], job.get("providerReference")
        try:
            publisher = getattr(provider, "publisher", None)
            if publisher is not None:
                return publisher.reconcile(manifest, job, provider, token, self)
            if manifest["platform"] in WAVE1:
                return self._reconcile_wave1(manifest, provider, token, reference, job)
            if manifest["platform"] in WAVE3:
                return self._reconcile_wave3(manifest, provider, token, reference, job)
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

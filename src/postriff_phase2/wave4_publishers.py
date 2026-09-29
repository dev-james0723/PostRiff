"""Provider write contracts for Wave 4. No class here grants itself production approval."""
import hashlib
import html
import json
import re
from urllib.parse import quote, urlencode

from postriff_alpha.domain import AlphaError
from .social_connectors import multipart
from .provider_media import stream_multipart_video
from .net_guard import pinned_public_json_transport


def _body(response):
    return response.get("body") if isinstance(response, dict) and isinstance(response.get("body"), dict) else {}


def _uncertain(reason):
    return {"state": "uncertain", "confirmed": reason + " Do not resubmit this post."}


class GoogleBusinessPosts:
    """Local Posts are scoped to a user-selected and freshly verified GBP location."""
    required_scopes = frozenset({"https://www.googleapis.com/auth/business.manage"})
    API = "https://mybusiness.googleapis.com/v4/"
    REFERENCE = re.compile(r"accounts/[0-9]+/locations/[0-9]+/localPosts/[A-Za-z0-9_-]+")

    def _location(self, provider, token):
        session = provider._session_for_publish(token)
        location = session.get("location")
        if not provider.valid_destination_id(location):
            raise AlphaError("Choose a Business Profile location before publishing.", 409)
        if location not in {item["id"] for item in provider.destinations(token)}:
            raise AlphaError("The chosen Business Profile location is no longer available.", 409)
        return location

    @staticmethod
    def _post(manifest, social):
        text = manifest.get("payload", {}).get("text")
        options = (manifest.get("publishOptions") or {}).get("gbp") or {}
        topic = options.get("topicType", "STANDARD")
        if not isinstance(text, str) or not text.strip() or len(text) > 1500 or topic not in ("STANDARD", "EVENT", "OFFER"):
            raise AlphaError("Review this Business Profile post format again.", 409)
        post = {"summary": text, "topicType": topic}
        if topic in ("EVENT", "OFFER"):
            event = options.get("event")
            if not isinstance(event, dict) or not isinstance(event.get("title"), str) or not isinstance(event.get("schedule"), dict):
                raise AlphaError("An Event or Offer post needs its title and schedule.", 409)
            post["event"] = {"title": event["title"], "schedule": event["schedule"]}
        if topic == "OFFER":
            offer = options.get("offer")
            if not isinstance(offer, dict) or not any(offer.get(k) for k in ("couponCode", "redeemOnlineUrl", "termsConditions")):
                raise AlphaError("An Offer post needs its offer details.", 409)
            post["offer"] = {k: offer[k] for k in ("couponCode", "redeemOnlineUrl", "termsConditions") if isinstance(offer.get(k), str)}
        media = manifest.get("media") or []
        if len(media) > 1 or any(item.get("mime") != "image/jpeg" for item in media):
            raise AlphaError("Business Profile posts support at most one approved JPEG here.", 409)
        if media:
            post["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": social._image_url(manifest)}]
        return post

    def submit(self, manifest, provider, token, social):
        post = self._post(manifest, social)
        location = self._location(provider, token)
        response = provider._request_for_publish(token, "POST", self.API + location + "/localPosts", body=post)
        body = _body(response)
        reference = body.get("name")
        if response.get("status") in (200, 201) and isinstance(reference, str) and self.REFERENCE.fullmatch(reference) and reference.startswith(location + "/"):
            return {"state": "provider_accepted", "reference": reference,
                    "confirmed": "Google accepted the Local Post; location, content and live state await read-back."}
        if response.get("status") in (401, 403):
            return {"state": "held", "confirmed": "Google rejected this Business Profile grant or API approval. Nothing was confirmed."}
        if response.get("status") == 429:
            return {"state": "scheduled", "confirmed": "Google rate limited the request before acceptance."}
        return _uncertain("The Local Post create response was inconclusive.")

    def reconcile(self, manifest, job, provider, token, social):
        reference = job.get("providerReference")
        if not isinstance(reference, str) or not self.REFERENCE.fullmatch(reference):
            return _uncertain("No safe Google post reference is available.")
        location = self._location(provider, token)
        if not reference.startswith(location + "/"):
            return _uncertain("The Google post reference belongs to a different location.")
        response = provider._request_for_publish(token, "GET", self.API + reference)
        body = _body(response)
        expected = self._post(manifest, social)
        if (response.get("status") != 200 or body.get("name") != reference or body.get("summary") != expected["summary"]
                or body.get("topicType") != expected["topicType"]
                or any(body.get(key) != expected[key] for key in ("event", "offer") if key in expected)):
            return _uncertain("Google read-back did not match the approved location and content.")
        if body.get("state") == "LIVE":
            if manifest.get("media"):
                return {"state": "provider_accepted", "reference": reference,
                        "confirmed": "Google reports the Local Post live, but the approved image cannot yet be independently matched in read-back."}
            result = {"state": "verified", "reference": reference, "verification": "provider_lookup",
                      "confirmed": "Google reports the approved Local Post live at the selected location."}
            return result
        if body.get("state") in ("REJECTED", "FAILED"):
            return {"state": "failed", "reference": reference, "verification": "provider_lookup",
                    "confirmed": "Google rejected the Local Post."}
        return {"state": "provider_accepted", "reference": reference, "confirmed": "Google is still processing the Local Post."}


class PixelfedPosts:
    """Media-first Pixelfed publishing; each request remains on the token's pinned public instance."""
    required_scopes = frozenset({"write"})
    ID = re.compile(r"[A-Za-z0-9_-]{1,80}")

    def submit(self, manifest, provider, token, social):
        media = manifest.get("media") or []
        if len(media) != 1 or media[0].get("mime") not in ("image/jpeg", "image/png"):
            return {"state": "failed", "confirmed": "This Pixelfed instance needs one approved image. Nothing was posted."}
        session = provider.session(token)
        account = manifest.get("providerAccountId")
        if not isinstance(account, str) or not account.endswith("@" + session["instance"]):
            return {"state": "held", "confirmed": "The Pixelfed instance changed; reconnect and review again."}
        image = social._image(manifest)
        if image is None or len(image[0]) > 8 * 1024 * 1024:
            return {"state": "failed", "confirmed": "The Pixelfed image is unavailable or too large."}
        raw, mime, alt = image
        upload, content_type = multipart([], [("file", "rafii-image.jpg", mime, raw)])
        response = provider.api(session, "POST", "/api/v1/media", headers={"Content-Type": content_type}, data=upload)
        media_id = _body(response).get("id")
        if response.get("status") not in (200, 201, 202) or not isinstance(media_id, str) or not self.ID.fullmatch(media_id):
            return {"state": "held", "confirmed": "This Pixelfed instance did not accept the image; its publishing path needs review."}
        for _ in range(5):
            item = provider.api(session, "GET", "/api/v1/media/" + quote(media_id))
            if item.get("status") == 200 and _body(item).get("url"):
                break
            social.sleep(2)
        else:
            return {"state": "held", "confirmed": "Pixelfed is still processing the image; no status was submitted."}
        if alt:
            provider.api(session, "PUT", "/api/v1/media/" + quote(media_id), form={"description": alt[:1000]})
        text = manifest.get("payload", {}).get("text") or ""
        response = provider.api(session, "POST", "/api/v1/statuses",
                                headers={"Idempotency-Key": str(manifest["idempotencyKey"])[:64]},
                                form={"status": text, "media_ids[]": media_id, "visibility": "public"})
        body = _body(response)
        reference = body.get("id")
        owner = body.get("account") if isinstance(body.get("account"), dict) else {}
        if response.get("status") in (200, 201) and isinstance(reference, str) and self.ID.fullmatch(reference) and str(owner.get("id")) + "@" + session["instance"] == account:
            return {"state": "provider_accepted", "reference": reference, "container": media_id,
                    "confirmed": "Pixelfed accepted the status; exact account and content read-back are pending."}
        return _uncertain("The Pixelfed status response was inconclusive.")

    def reconcile(self, manifest, job, provider, token, social):
        reference = job.get("providerReference")
        if not isinstance(reference, str) or not self.ID.fullmatch(reference):
            return _uncertain("No safe Pixelfed status reference is available.")
        session = provider.session(token)
        response = provider.api(session, "GET", "/api/v1/statuses/" + quote(reference))
        body = _body(response)
        owner = body.get("account") if isinstance(body.get("account"), dict) else {}
        plain = html.unescape(re.sub(r"<[^>]*>", " ", str(body.get("content") or ""))).strip()
        expected = str(manifest.get("payload", {}).get("text") or "").strip()
        attachments = body.get("media_attachments") if isinstance(body.get("media_attachments"), list) else []
        media_id = job.get("container")
        if (response.get("status") != 200 or str(body.get("id")) != reference
                or str(owner.get("id")) + "@" + session["instance"] != manifest.get("providerAccountId")
                or body.get("visibility") != "public"
                or not isinstance(media_id, str) or not self.ID.fullmatch(media_id)
                or len(attachments) != 1 or not isinstance(attachments[0], dict)
                or str(attachments[0].get("id")) != media_id
                or " ".join(plain.split()) != " ".join(expected.split())):
            return _uncertain("Pixelfed read-back did not match the approved account, caption and image attachment.")
        result = {"state": "verified", "reference": reference, "verification": "provider_lookup",
                  "confirmed": "Pixelfed read-back matched the approved caption, image attachment and exact account."}
        return result


class DouyinVideos:
    required_scopes = frozenset({"video.create.bind"})
    BASE = "https://open.douyin.com/api/douyin/v1/video/"

    @staticmethod
    def _good(response):
        body = _body(response)
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        extra = body.get("extra") if isinstance(body.get("extra"), dict) else {}
        return (response.get("status") == 200 and data.get("error_code", 0) == 0
                and extra.get("error_code", 0) == 0), data

    def submit(self, manifest, provider, token, social):
        text = manifest.get("payload", {}).get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= 1000:
            return {"state": "failed", "confirmed": "Douyin requires a reviewed caption of at most 1,000 characters."}
        session = provider.session(token)
        if session["openId"] != manifest.get("providerAccountId"):
            return {"state": "held", "confirmed": "The Douyin account changed; reconnect and review again."}
        chunks, media = social._video_stream(manifest)
        query = urlencode({"open_id": session["openId"]})
        headers = {"access-token": session["at"]}
        if media["bytes"] <= 50_000_000:
            uploaded = stream_multipart_video(self.BASE + "upload_video/?" + query, session["at"], chunks, media["bytes"])
            good, data = self._good(uploaded)
        else:
            opened = provider.transport("POST", self.BASE + "init_video_part_upload/?" + query, headers=headers, body={})
            good, data = self._good(opened)
            upload_id = data.get("upload_id")
            if not good or not isinstance(upload_id, str) or not upload_id:
                return {"state": "held", "confirmed": "Douyin did not initialize the video upload."}
            count = 0
            for count, chunk in enumerate(chunks, 1):
                part_query = urlencode({"open_id": session["openId"], "upload_id": upload_id, "part_number": count})
                body, content_type = multipart([], [("video", f"part-{count}.mp4", "video/mp4", chunk)])
                sent = provider.transport("POST", self.BASE + "upload_video_part/?" + part_query,
                                          headers={**headers, "Content-Type": content_type}, data=body)
                good, _ = self._good(sent)
                if not good:
                    return {"state": "held", "confirmed": "Douyin did not accept a video part; no post was created."}
            if not count:
                return {"state": "held", "confirmed": "The approved Douyin video is empty."}
            finished = provider.transport("POST", self.BASE + "complete_video_part_upload/?" +
                                          urlencode({"open_id": session["openId"], "upload_id": upload_id}),
                                          headers=headers, body={})
            good, data = self._good(finished)
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        video_id = video.get("video_id")
        if not good or not isinstance(video_id, str) or not video_id:
            return {"state": "held", "confirmed": "Douyin did not confirm the video upload; no post was created."}
        # This is the first public write. An ambiguous response is never retried automatically.
        created = provider.transport("POST", self.BASE + "create_video/?" + query, headers=headers,
                                     body={"text": text, "video_id": video_id})
        good, data = self._good(created)
        item_id = data.get("item_id")
        if good and isinstance(item_id, str) and item_id:
            return {"state": "provider_accepted", "reference": item_id, "container": video_id,
                    "confirmed": "Douyin accepted the video; moderation and publication are still pending."}
        return _uncertain("Douyin did not conclusively answer the create request.")

    def reconcile(self, manifest, job, provider, token, social):
        reference = job.get("providerReference")
        if not isinstance(reference, str) or not reference or len(reference) > 256:
            return _uncertain("No safe Douyin item reference is available.")
        session = provider.session(token)
        if "posting.behavior" not in session.get("scope", []):
            return {"state": "provider_accepted", "reference": reference,
                    "confirmed": "Douyin accepted the video; app access to the official read-back endpoint is still required."}
        queried = provider.transport("POST", self.BASE + "video_basic_info/?" + urlencode({"open_id": session["openId"]}),
                                     headers={"access-token": session["at"]}, body={"item_ids": [reference]})
        good, data = self._good(queried)
        items = data.get("list") if isinstance(data.get("list"), list) else []
        item = next((x for x in items if isinstance(x, dict) and x.get("item_id") == reference), None)
        if not good or not item or item.get("title") != manifest.get("payload", {}).get("text"):
            return _uncertain("Douyin read-back did not match the approved video.")
        # The platform stopped returning video_status to new apps; title + id prove ownership,
        # but do not prove moderation passed or that the post is public.
        return {"state": "provider_accepted", "reference": reference,
                "confirmed": "Douyin read-back found the exact item; public visibility still needs provider evidence."}


class KuaishouVideos:
    required_scopes = frozenset({"user_video_publish"})
    BASE = "https://open.kuaishou.com/openapi/photo/"

    @staticmethod
    def _gateway(host):
        if (not isinstance(host, str) or len(host) > 253 or "/" in host or ":" in host
                or not (host.endswith(".gifshow.com") or host.endswith(".kuaishou.com"))):
            raise AlphaError("Kuaishou returned an unapproved upload gateway.", 502)
        return host

    def submit(self, manifest, provider, token, social):
        session = provider.session(token)
        if session["openId"] != manifest.get("providerAccountId"):
            return {"state": "held", "confirmed": "The Kuaishou account changed; reconnect and review again."}
        caption = manifest.get("payload", {}).get("text")
        if not isinstance(caption, str) or not caption.strip() or len(caption) > 1000:
            return {"state": "failed", "confirmed": "Review the Kuaishou video caption again."}
        media = (manifest.get("media") or [None])[0]
        poster = media.get("poster") if isinstance(media, dict) else None
        if not isinstance(poster, dict) or not poster.get("objectName"):
            return {"state": "held", "confirmed": "Kuaishou requires an approved JPEG cover image."}
        cover = social.assets.storage.get(manifest["workspaceId"], "media", poster["objectName"])
        if (len(cover) > 8 * 1024 * 1024 or not cover.startswith(b"\xff\xd8")
                or poster.get("bytes") != len(cover) or hashlib.sha256(cover).hexdigest() != poster.get("hash")):
            return {"state": "held", "confirmed": "The Kuaishou cover image is unavailable or invalid."}
        chunks, _ = social._video_stream(manifest)
        common = {"access_token": session["at"], "app_id": provider.client_id}
        opened = provider.transport("POST", self.BASE + "start_upload?" + urlencode(common))
        data = _body(opened)
        upload_token = data.get("upload_token")
        if opened.get("status") != 200 or data.get("result") != 1 or not isinstance(upload_token, str):
            return {"state": "held", "confirmed": "Kuaishou did not initialize the video upload."}
        host = self._gateway(data.get("endpoint"))
        # Public docs still show HTTP. Rafii never sends an upload token over cleartext:
        # only a gateway that actually accepts HTTPS can move to the publish step.
        count = -1
        for count, chunk in enumerate(chunks):
            url = "https://" + host + "/api/upload/fragment?" + urlencode({"upload_token": upload_token, "fragment_id": count})
            result = pinned_public_json_transport("POST", url, headers={"Content-Type": "video/mp4"}, data=chunk)
            if result.get("status") != 200 or _body(result).get("result") != 1:
                return {"state": "held", "confirmed": "The Kuaishou HTTPS upload gateway did not accept this video. No post was created."}
        if count < 0:
            return {"state": "held", "confirmed": "The approved Kuaishou video is empty."}
        finished = pinned_public_json_transport("POST", "https://" + host + "/api/upload/complete?" +
                                                 urlencode({"upload_token": upload_token, "fragment_count": count + 1}),
                                                 headers={"Content-Type": "application/json"}, body={})
        if finished.get("status") != 200 or _body(finished).get("result") != 1:
            return {"state": "held", "confirmed": "Kuaishou did not confirm the video upload. No post was created."}
        upload, content_type = multipart([("caption", caption)], [("cover", "cover.jpg", "image/jpeg", cover)])
        created = provider.transport("POST", self.BASE + "publish?" + urlencode({**common, "upload_token": upload_token}),
                                     headers={"Content-Type": content_type}, data=upload)
        data = _body(created)
        info = data.get("video_info") if isinstance(data.get("video_info"), dict) else {}
        photo_id = info.get("photo_id")
        if created.get("status") == 200 and data.get("result") == 1 and isinstance(photo_id, str) and photo_id:
            return {"state": "provider_accepted", "reference": photo_id,
                    "confirmed": "Kuaishou accepted the video; processing and account read-back are pending."}
        return _uncertain("Kuaishou did not conclusively answer the publish request.")

    def reconcile(self, manifest, job, provider, token, social):
        reference = job.get("providerReference")
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", reference):
            return _uncertain("No safe Kuaishou photo reference is available.")
        session = provider.session(token)
        response = provider.transport("GET", self.BASE + "info?" + urlencode({
            "photo_id": reference, "app_id": provider.client_id, "access_token": session["at"]}))
        body = _body(response)
        info = body.get("video_info") if isinstance(body.get("video_info"), dict) else {}
        if response.get("status") != 200 or body.get("result") != 1 or info.get("photo_id") != reference or info.get("caption") != manifest.get("payload", {}).get("text"):
            return _uncertain("Kuaishou read-back did not match the approved video.")
        if info.get("pending") is True or not info.get("play_url"):
            return {"state": "provider_accepted", "reference": reference, "confirmed": "Kuaishou is still processing the video."}
        return {"state": "verified", "reference": reference, "verification": "provider_lookup",
                "confirmed": "Kuaishou read-back matched the exact video caption and confirmed playback."}

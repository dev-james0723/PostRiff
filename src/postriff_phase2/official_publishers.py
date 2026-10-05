"""Official media lifecycles. A container/asset receipt is never a publication receipt.

Every advance is driven by a durably recorded worker intent. Unknown publish outcomes
are reconciled, never retried as creates. Network transports are injected for testing.
"""
import hashlib
import json
import re
from urllib.parse import quote, urlencode
from postriff_alpha.domain import AlphaError
from .official_social import LINKEDIN_VERSION, THREADS_VERSION

ASYNC_PLATFORMS = ("LinkedIn", "Threads", "Instagram", "Facebook", "X", "YouTube", "TikTok", "Pinterest")
FORWARD_STAGES = ("assets_uploaded", "children_created", "children_ready", "container_created", "container_ready", "upload_session", "upload_finalizable", "next_asset", "metadata_pending", "thread_ready")


def _unknown(message, **context):
    return {"state": "uncertain", "confirmed": message + "; do not resubmit", **context}


def _receipt(response, name):
    value = response.get("body", {}).get(name)
    if response.get("status") not in (200, 201) or not isinstance(value, str) or not value:
        raise AlphaError("Provider did not return a usable media identifier.", 502)
    return value


def _upload_host(url, domains):
    from .wave3_connectors import provider_host
    provider_host(url, domains)
    return url


class OfficialPublishers:
    def __init__(self, host):
        self.host, self.transport = host, host.transport
        from .official_media import AdditionalPublishers
        self.additional = AdditionalPublishers(self)

    def bytes(self, manifest, asset):
        if asset.get("rightsConfirmed") is not True:
            raise AlphaError("Approve media rights before uploading.", 409)
        if str(asset.get("mime", "")).startswith("video/"):
            video, refusal = self.host._video({**manifest, "media": [asset]})
            if refusal: raise AlphaError(refusal["confirmed"], 409)
            raw = video[0]
        else:
            if not self.host.assets: raise AlphaError("Approved media storage is unavailable.", 503)
            raw = self.host.assets.storage.get(manifest["workspaceId"], "media", asset.get("objectName") or asset["id"])
        if (not isinstance(raw, bytes) or len(raw) != asset.get("bytes")
                or hashlib.sha256(raw).hexdigest() != asset.get("hash")):
            raise AlphaError("Approved media bytes changed; review again.", 409)
        return raw

    def media_url(self, manifest, asset):
        # Verify the immutable rendition before granting a provider a temporary URL.
        self.bytes(manifest, asset)
        category = "video" if str(asset.get("mime", "")).startswith("video/") else "media"
        if manifest['platform']=='TikTok':
            return self.host.assets.storage.tiktok_transfer_url(manifest['workspaceId'],category,asset.get('objectName') or asset['id'])
        return self.host.assets.storage.signed_url(manifest["workspaceId"], category, asset.get("objectName") or asset["id"], 600)

    @staticmethod
    def _progress(stage, container, assets=(), **extra):
        return {"state": "processing", "container": container,
                "providerAssets": list(assets), "progress": {"version": 1, "stage": stage},
                "confirmed": "Provider media " + stage.replace("_", " ") + "; not published", **extra}

    def advance(self, manifest, job, action):
        provider = self.host._provider(manifest)
        if not provider:
            return {"state": "held", "confirmed": "Provider approval or execution permission unavailable"}
        grant = self.host.oauth.token_for_worker(manifest["workspaceId"], manifest["channelId"])
        token = grant["accessToken"]
        required = set(getattr(provider, "publish_required", ()))
        if manifest["platform"] == "LinkedIn":
            organization = (manifest.get("publishOptions") or {}).get("destinationType") == "organization"
            required = {"w_organization_social", "rw_organization_admin"} if organization else {"w_member_social"}
        if manifest['platform'] == 'TikTok' and (manifest.get('publishOptions') or {}).get('mode') == 'inbox':
            required = {'video.upload'}
        if manifest.get('media') and manifest['platform'] == 'X': required.add('media.write')
        if manifest['platform'] == 'Threads' and (manifest.get('publishOptions') or {}).get('location_id'): required.add('threads_location_tagging')
        if not required.issubset(grant.get("scopes") or []):
            return {"state": "held", "confirmed": "Publishing grant changed; reconnect and review"}
        if action not in ("status",) and job.get("progress", {}).get("stage") != action + "_attempted":
            return _unknown("Missing durable provider intent")
        try:
            if manifest["platform"] == "LinkedIn":
                return self.linkedin(manifest, job, action, provider, token)
            if manifest['platform'] in ('Threads', 'Instagram'):
                return self.meta(manifest, job, action, provider, token)
            return self.additional.advance(manifest, job, action, provider, grant)
        except AlphaError as error:
            return _unknown(str(error), **({"container": job["container"]} if job.get("container") else {}))

    @staticmethod
    def linkedin_headers(token):
        return {"Authorization": "Bearer " + token, "LinkedIn-Version": LINKEDIN_VERSION,
                "X-Restli-Protocol-Version": "2.0.0"}

    def linkedin(self, manifest, job, action, provider, token):
        headers = self.linkedin_headers(token)
        options = manifest.get("publishOptions") or {}
        owner = options.get("authorUrn") or manifest["providerAccountId"]
        if options.get("destinationType") == "organization":
            if not provider.organization_authorized(token, manifest["providerAccountId"], owner, "CREATE"):
                return {"state": "held", "confirmed": "LinkedIn did not authorize this member to publish for this organization"}
        elif owner != manifest["providerAccountId"] or not owner.startswith("urn:li:person:"):
            return {"state": "held", "confirmed": "Member destination does not match the authenticated member"}
        media = manifest.get("media") or []
        assets = job.get("providerAssets") or []
        if action == "create" and media:
            for asset in media:
                mime = asset.get("mime")
                kind = "videos" if str(mime).startswith("video/") else "documents" if mime == "application/pdf" else "images"
                raw = self.bytes(manifest, asset)
                initialize = {"owner": owner}
                if kind == "videos": initialize.update(fileSizeBytes=len(raw), uploadCaptions=False, uploadThumbnail=False)
                response = self.transport("POST", f"https://api.linkedin.com/rest/{kind}?action=initializeUpload", headers=headers,
                                          body={"initializeUploadRequest": initialize})
                value = response.get("body", {}).get("value") or {}
                urn = value.get(kind[:-1])
                if response.get("status") != 200 or not isinstance(urn, str) or not urn.startswith("urn:li:"+kind[:-1]+":"):
                    return _unknown("LinkedIn upload initialization unavailable", providerAssets=assets)
                part_ids = []
                instructions = value.get("uploadInstructions") if kind == "videos" else [{"uploadUrl": value.get("uploadUrl"), "firstByte": 0, "lastByte": len(raw)-1}]
                if not isinstance(instructions, list) or not instructions:
                    return _unknown("LinkedIn upload instructions missing", providerAssets=assets)
                offset = 0
                for instruction in instructions:
                    start, end = instruction.get("firstByte"), instruction.get("lastByte")
                    if type(start) is not int or type(end) is not int or start != offset or not start <= end < len(raw):
                        return _unknown("LinkedIn upload ranges invalid", providerAssets=assets)
                    address = _upload_host(instruction.get("uploadUrl"), ("www.linkedin.com", "api.linkedin.com"))
                    uploaded = self.transport("PUT", address, headers={"Content-Type": mime}, data=raw[start:end+1])
                    if uploaded.get("status") not in (200, 201):
                        return _unknown("LinkedIn media transfer interrupted", providerAssets=assets)
                    if kind == "videos":
                        etag = uploaded.get("headers", {}).get("etag")
                        if not etag: return _unknown("LinkedIn video part receipt missing", providerAssets=assets)
                        part_ids.append(etag.strip('"'))
                    offset = end+1
                if offset != len(raw): return _unknown("LinkedIn incomplete upload ranges", providerAssets=assets)
                if kind == "videos":
                    final = self.transport("POST", "https://api.linkedin.com/rest/videos?action=finalizeUpload", headers=headers,
                                           body={"finalizeUploadRequest": {"video": urn, "uploadToken": value.get("uploadToken", ""), "uploadedPartIds": part_ids}})
                    if final.get("status") not in (200, 201, 202, 204): return _unknown("LinkedIn video finalization inconclusive", providerAssets=assets)
                assets.append({"id": urn, "kind": kind, "assetId": asset["id"], "alt": asset.get("alt", "")})
            return self._progress("assets_uploaded", assets[0]["id"], assets)
        if action == "status":
            for asset in assets:
                response = self.transport("GET", f'https://api.linkedin.com/rest/{asset["kind"]}/{quote(asset["id"], safe="")}', headers=headers)
                if response.get('status') == 403 and asset['kind'] == 'images' and owner.startswith('urn:li:person:'):
                    # Official Images API explicitly allows legacy GET with
                    # w_member_social. This grants no historical post access.
                    response = self.transport('GET', f'https://api.linkedin.com/rest/images/{quote(asset["id"], safe="")}',
                        headers={'Authorization': 'Bearer '+token, 'X-Restli-Protocol-Version': '2.0.0'})
                if response.get("status") in (401, 403):
                    return {"state": "held", "container": job["container"], "providerAssets": assets,
                            "confirmed": "LinkedIn asset processing cannot be verified with this grant; no post created. Member image GET is write-scope restricted."}
                status = response.get("body", {}).get("status")
                if status in ("PROCESSING_FAILED", "FAILED"):
                    return {"state": "failed", "container": job["container"], "providerAssets": assets, "confirmed": "LinkedIn asset processing failed"}
                if response.get("status") != 200 or status != "AVAILABLE":
                    return self._progress("assets_uploaded", job["container"], assets)
            return self._progress("container_ready", job["container"], assets)
        if action not in ("create", "publish"): return _unknown("Unsupported LinkedIn transition")
        payload = {"author": owner, "commentary": manifest["payload"]["text"], "visibility": "PUBLIC",
                   "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                   "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        if media:
            if action != "publish" or len(assets) != len(media): return _unknown("Media is not ready for publication")
            if len(assets) > 1:
                payload["content"] = {"multiImage": {"images": [{"id": a["id"], "altText": a["alt"]} for a in assets]}}
            else: payload["content"] = {"media": {"id": assets[0]["id"], "title": options.get("title") or ""}}
        if options.get("link"):
            payload["content"] = {"article": {"source": options["link"], "title": options.get("title") or "", "description": options.get("description") or ""}}
        if options.get("poll"): payload["content"] = {"poll": options["poll"]}
        response = self.transport("POST", "https://api.linkedin.com/rest/posts", headers=headers, body=payload)
        reference = response.get("headers", {}).get("x-restli-id")
        if response.get("status") == 201 and isinstance(reference, str) and reference.startswith(("urn:li:share:", "urn:li:ugcPost:")):
            return {"state": "provider_accepted", "reference": reference, "providerAssets": assets,
                    "confirmed": "LinkedIn created the post; provider read-back pending"}
        return _unknown("LinkedIn create result inconclusive", providerAssets=assets)

    def meta(self, manifest, job, action, provider, token):
        instagram = manifest["platform"] == "Instagram"
        from .providers import GRAPH_VERSION
        base = "https://graph.instagram.com/"+GRAPH_VERSION if instagram else "https://graph.threads.net/"+THREADS_VERSION
        edge, publish_edge = ("media", "media_publish") if instagram else ("threads", "threads_publish")
        user = quote(manifest["providerAccountId"], safe="")
        options, media = manifest.get("publishOptions") or {}, manifest.get("media") or []
        assets = job.get("providerAssets") or []
        if action in ('create', 'publish'):
            quota_edge = 'content_publishing_limit' if instagram else 'threads_publishing_limit'
            response = self.transport('GET', f'{base}/{user}/{quota_edge}?'+urlencode({'fields': 'quota_usage,config', 'access_token': token}))
            body = response.get('body') or {}
            quota = body.get('data', [body])
            quota = quota[0] if isinstance(quota, list) and quota else {}
            usage, total = quota.get('quota_usage'), (quota.get('config') or {}).get('quota_total')
            if response.get('status') != 200 or type(usage) is not int or type(total) is not int:
                return {'state': 'held', 'confirmed': 'Provider publishing quota could not be verified; no publication requested'}
            if usage >= total: return {'state': 'held', 'confirmed': 'Provider-native publishing quota is exhausted; wait and review'}
        if action == "create":
            children = len(media) > 1
            if not media and instagram: return {"state": "failed", "confirmed": "Instagram needs approved media"}
            params = {"caption" if instagram else "text": manifest["payload"]["text"]}
            if not instagram:
                params.update({key: options[key] for key in ("reply_to_id", "quote_post_id", "reply_control", "topic_tag", "link_attachment", "poll_attachment", "text_attachment", "is_ghost_post", 'gif_attachment', 'location_id','text_entities','is_spoiler_media','enable_reply_approvals') if key in options})
            if options.get("format") == "story":
                if not instagram or provider.identity(token).get("accountType", "").lower() != "business":
                    return {"state": "held", "confirmed": "Stories require a verified eligible Business account"}
                params = {"media_type": "STORIES"}
            for item in media or [None]:
                form = {} if children else dict(params)
                if item:
                    video = str(item.get("mime", "")).startswith("video/")
                    form["video_url" if video else "image_url"] = self.media_url(manifest, item)
                    if video: form["media_type"] = "VIDEO" if children or not instagram else "REELS"
                    elif not instagram: form["media_type"] = "IMAGE"
                    if item.get("alt") and not video: form["alt_text"] = item["alt"]
                else: form["media_type"] = "TEXT"
                if children: form["is_carousel_item"] = "true"
                if children and not instagram and 'is_spoiler_media' in options: form['is_spoiler_media'] = options['is_spoiler_media']
                if options.get("format") == "story": form["media_type"] = "STORIES"
                response = self.transport("POST", f"{base}/{user}/{edge}", form={**form, "access_token": token})
                try: cid = _receipt(response, "id")
                except AlphaError: return _unknown("Media container creation inconclusive", providerAssets=assets)
                if not cid.isdigit(): return _unknown("Invalid provider container id", providerAssets=assets)
                assets.append({"id": cid, "kind": "child" if children else "container", "assetId": item["id"] if item else None})
            return self._progress("children_created" if children else "container_created", assets[0]["id"], assets)
        if action == "status":
            children = job.get("progress", {}).get("stage") == "children_created"
            check = assets if children else [{"id": job.get("container")}]
            for asset in check:
                response = self.transport("GET", f'{base}/{quote(str(asset["id"]), safe="")}?'+urlencode({"fields": "status_code", "access_token": token}))
                if response.get("status") in (401, 403): return {"state": "held", "confirmed": "Container processing permission lost"}
                status = response.get("body", {}).get("status_code")
                if status in ("ERROR", "EXPIRED"): return {"state": "failed", "confirmed": "Provider media processing "+status}
                if status == "PUBLISHED": return _unknown("Container already published; reconcile its outcome")
                if response.get("status") != 200 or status != "FINISHED":
                    return self._progress("children_created" if children else "container_created", job["container"], assets)
            return self._progress("children_ready" if children else "container_ready", job["container"], assets)
        if action == "parent":
            parent_options = {} if instagram else {key: options[key] for key in ("reply_to_id", "quote_post_id", "reply_control", "topic_tag", 'location_id','text_entities','enable_reply_approvals') if key in options}
            response = self.transport("POST", f"{base}/{user}/{edge}", form={**parent_options, "media_type": "CAROUSEL", "children": ",".join(a["id"] for a in assets),
                         "caption" if instagram else "text": manifest["payload"]["text"], "access_token": token})
            try: cid = _receipt(response, "id")
            except AlphaError: return _unknown("Parent container creation inconclusive", providerAssets=assets)
            if not cid.isdigit(): return _unknown("Invalid parent container identifier", providerAssets=assets)
            return self._progress("container_created", cid, assets)
        if action != "publish" or not job.get("container"): return _unknown("Invalid publication transition")
        response = self.transport("POST", f"{base}/{user}/{publish_edge}", form={"creation_id": job["container"], "access_token": token})
        try: mid = _receipt(response, "id")
        except AlphaError: return _unknown("Parent publication result inconclusive", container=job["container"], providerAssets=assets)
        return {"state": "provider_accepted", "container": job["container"], "reference": mid,
                "providerAssets": assets, "confirmed": "Provider returned publication ID; read-back pending"}

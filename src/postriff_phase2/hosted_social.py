"""Dedicated connector execution for the hosted worker (architecture §13).

`submit` runs exactly one approved manifest against the customer's own encrypted grant;
`reconcile` looks the outcome up before any retry. Every ambiguous response is
`uncertain`; permission failures are `held`; explicit pre-acceptance rejections are
`scheduled` (429) or `failed`. HTTP 200 alone is never `published`.
"""
from urllib.parse import quote, urlencode
from postriff_alpha.domain import AlphaError
from .provider_candidates import LinkedInCandidate, little_plain
from .providers import GRAPH_VERSION, http_transport

LINKEDIN_VERSION = "202609"  # official versioning + Posts API docs checked 2026-09-20; live account validation pending


def _uncertain(message):
    return {"state": "uncertain", "confirmed": message}


class HostedSocial:
    """Mounted only when at least one production-reviewed provider is registered."""
    def __init__(self, oauth, providers, assets=None, transport=None):
        self.oauth, self.providers, self.assets = oauth, providers, assets
        self.transport = transport or http_transport
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
        provider = self.providers.get({"LinkedIn": "linkedin", "Threads": "threads", "Instagram": "instagram"}.get(manifest["platform"]))
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
        required = {"LinkedIn": {"w_member_social"}, "Threads": {"threads_basic", "threads_content_publish"}, "Instagram": {"instagram_business_basic", "instagram_business_content_publish"}}.get(manifest["platform"], set())
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
        except AlphaError as error:
            return _uncertain(f"Submission could not be completed conclusively: {error}")
        return {"state": "held", "confirmed": "No connector for this platform."}

    def _classify_status(self, status):
        if status in (401, 403):
            return {"state": "held", "confirmed": "Provider rejected the permission or session; re-authorization required"}
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

"""Connect-only shared Mastodon application cache; no management endpoints."""
import json
from .contracts import digest
from .mastodon_protocol import refuse_rate_limited_registration
from .provider_base import _credential_shape
from postriff_alpha.domain import AlphaError


class ApplicationCache:
    def __init__(self, oauth, provider):
        self.oauth, self.provider = oauth, provider

    def __call__(self, host, redirect, scopes, value=None):
        binding = digest({"redirect": redirect, "scopes": sorted(scopes), "website": self.provider.website})
        with self.oauth.repository.connection_factory() as db, db.cursor() as cur:
            # Serialize per binding across processes; do not register thousands of duplicate apps.
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", ("mastodon-app:" + host + binding,))
            if not cur.fetchone()[0]:
                raise AlphaError('Rafii is registering on this server. Try connecting again shortly.', 409, code='mastodon_registration_busy')
            cur.execute("SELECT credentials_ciphertext,key_id FROM public.pr_mastodon_applications WHERE instance=%s AND binding_digest=%s", (host, binding))
            stored = cur.fetchone()
            if stored:
                credentials = json.loads(self.oauth.vault.decrypt(stored[0], stored[1]))
                expiry = credentials.get("client_secret_expires_at", 0) if isinstance(credentials, dict) else None
                if (isinstance(credentials, dict) and _credential_shape(credentials.get('client_id'))
                        and _credential_shape(credentials.get('client_secret'))
                        and type(expiry) is int and (expiry == 0 or expiry > self.oauth.clock() + 600)):
                    return credentials
            response = self.provider.transport("POST", "https://" + host + "/api/v1/apps", form={
                "client_name": "Rafii", "redirect_uris": redirect, "scopes": " ".join(scopes), "website": self.provider.website})
            refuse_rate_limited_registration(response)
            body = self.provider._ok(response, "client_id", "client_secret")
            expiry = body.get('client_secret_expires_at', 0)
            if (not _credential_shape(body.get('client_id')) or not _credential_shape(body.get('client_secret'))
                    or type(expiry) is not int or expiry < 0
                    or (expiry != 0 and expiry <= self.oauth.clock() + 600)):
                raise AlphaError('This Mastodon server returned invalid application credentials.', 502)
            credentials = {key: body[key] for key in ("client_id", "client_secret", "client_secret_expires_at") if key in body}
            ciphertext, key_id = self.oauth.vault.encrypt(json.dumps(credentials))
            cur.execute("INSERT INTO public.pr_mastodon_applications(instance,binding_digest,credentials_ciphertext,key_id) VALUES(%s,%s,%s,%s) ON CONFLICT(instance,binding_digest) DO UPDATE SET credentials_ciphertext=excluded.credentials_ciphertext,key_id=excluded.key_id,updated_at=now()", (host, binding, ciphertext, key_id))
            return credentials

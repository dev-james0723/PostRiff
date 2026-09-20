"""PostRiff-owned OAuth transactions and encrypted credential custody (architecture §12.2).

Flow: authenticated `start` → provider consent → PostRiff public callback (redirect only,
never exchanges) → authenticated `complete` (same member, same workspace, single use, PKCE)
→ tokens encrypted at rest → channel + capability rows. Tokens are decrypted only for the
server-side connector worker; they never reach the browser, the agent, or a log.
"""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode, urlparse
from postriff_alpha.domain import AlphaError, clean
from .audience import COMMENT_READ_PROVIDERS
from . import account_pictures
from .permissions import require
from .channels import CAPABILITIES, assisted_matrix, customer_view, set_level, unsupported_matrix

TRANSACTION_TTL = 600
PUBLISH_CAPABILITIES = ("publish", "schedule")


class CredentialVault:
    """Application-layer encryption (Fernet: AES-128-CBC + HMAC-SHA256). Key from server secrets."""
    def __init__(self, key=None):
        self.fernet, self.key_id = None, None
        if key:
            from cryptography.fernet import Fernet
            self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
            self.key_id = hashlib.sha256(key.encode() if isinstance(key, str) else key).hexdigest()[:12]

    @staticmethod
    def generate_key():
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext):
        if not self.fernet:
            raise AlphaError("Credential custody is not configured on this deployment.", 503)
        return self.fernet.encrypt(plaintext.encode()).decode(), self.key_id

    def decrypt(self, ciphertext, key_id):
        if not self.fernet:
            raise AlphaError("Credential custody is not configured on this deployment.", 503)
        if key_id != self.key_id:
            raise AlphaError("This credential was sealed under a rotated key; re-authorize the account.", 409)
        from cryptography.fernet import InvalidToken
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as error:
            raise AlphaError("Stored credential could not be opened; re-authorize the account.", 409) from error


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


class OAuthService:
    def __init__(self, repository, commands, vault, providers, public_base_url, clock=time.time):
        self.repository, self.commands, self.vault, self.clock = repository, commands, vault, clock
        self.providers = providers or {}
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.picture_fetch = account_pictures.fetch_image  # replaced in tests; never reached without a picture URL

    def _provider(self, provider_id):
        adapter = self.providers.get(provider_id)
        if adapter is None:
            raise AlphaError("This provider is not available for connection yet.", 404)
        return adapter

    def callback_uri(self, provider_id):
        if not self.public_base_url.startswith("https://"):
            raise AlphaError("A public HTTPS PostRiff base URL is required for OAuth.", 503)
        return f"{self.public_base_url}/api/oauth/{provider_id}/callback"

    # --- start ----------------------------------------------------------------------
    def start(self, workspace_id, token, provider_id, capability):
        adapter = self._provider(provider_id)
        if capability not in CAPABILITIES or capability in ("media_types", "webhooks"):
            raise AlphaError("Choose the capability you want to enable.", 400)
        scopes = adapter.capability_scopes(capability)
        if not scopes:
            raise AlphaError(f"{adapter.platform} does not offer '{capability}' through its official API for this app.", 409)
        redirect = self.callback_uri(provider_id)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit, throttle
            require(_membership(row), "manage_connections")
            throttle(cur, f"oauth-start:{workspace_id}", 20, 600)
            state = secrets.token_urlsafe(32)
            verifier, challenge = pkce_pair()
            ciphertext, key_id = self.vault.encrypt(verifier)
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s)) RETURNING id::text", (workspace_id, principal, provider_id, capability, redirect, list(scopes), hashlib.sha256(state.encode()).hexdigest(), ciphertext, key_id, TRANSACTION_TTL))
            transaction_id = cur.fetchone()[0]
            audit(cur, workspace_id, principal, "oauth.started", transaction_id, {"provider": provider_id, "capability": capability})
            return {"transactionId": transaction_id, "provider": provider_id, "platform": adapter.platform, "capability": capability, "scopes": list(scopes), "permissionExplanation": adapter.explain(capability), "authorizeUrl": adapter.authorize_url(redirect, state, challenge, scopes), "expiresAt": self.clock() + TRANSACTION_TTL}

    # --- public callback (redirect only) -------------------------------------------
    @staticmethod
    def callback_redirect(web_base_url, provider_id, query):
        """The public callback never exchanges codes; it hands state/code back to the signed-in app."""
        allowed = {k: clean(v, 512) for k, v in query.items() if k in ("state", "code", "error", "error_description")}
        allowed["provider"] = provider_id
        return f"{web_base_url.rstrip('/')}/channels/connect?{urlencode(allowed)}"

    # --- complete (authenticated exchange) ----------------------------------------
    def complete(self, workspace_id, token, provider_id, state, code, error=None):
        adapter = self._provider(provider_id)
        if not isinstance(state, str) or not 20 <= len(state) <= 128:
            raise AlphaError("Connection request unavailable.", 404)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT id::text,member_id::text,provider,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE state_hash=%s AND workspace_id=%s FOR UPDATE", (state_hash, workspace_id))
            txn = cur.fetchone()
            if not txn:
                raise AlphaError("Connection request unavailable.", 404)
            transaction_id, member_id, provider, capability, redirect, scopes, verifier_ct, key_id, expires_at, consumed = txn
            if consumed or provider != provider_id or member_id != principal:
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=coalesce(consumed_at,now()),outcome=coalesce(outcome,'mismatch') WHERE id::text=%s", (transaction_id,))
                audit(cur, workspace_id, principal, "oauth.rejected", transaction_id, {"reason": "mismatch_or_replay"})
                raise AlphaError("Connection request unavailable.", 404)
            if expires_at <= self.clock():
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='expired' WHERE id::text=%s", (transaction_id,))
                raise AlphaError("This connection request expired. Start again.", 409)
            if error or not code:
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='denied' WHERE id::text=%s", (transaction_id,))
                audit(cur, workspace_id, principal, "oauth.denied", transaction_id, {"provider": provider_id})
                return {"connected": False, "reason": "denied"}
            cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='exchanged' WHERE id::text=%s", (transaction_id,))
            verifier = self.vault.decrypt(verifier_ct, key_id)
            grant = adapter.exchange(code, verifier, redirect)
            identity = adapter.identity(grant["accessToken"])
            granted = sorted(set(grant.get("scopes") or scopes))
            missing = sorted(set(scopes) - set(granted))
            connection_id = hashlib.sha256(f"{provider_id}:{identity['providerAccountId']}".encode()).hexdigest()[:32]
            from .billing import require_plan_capacity
            require_plan_capacity(cur, workspace_id, "connected_accounts", connection_id)
            access_ct, key_id = self.vault.encrypt(grant["accessToken"])
            refresh_ct = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else None
            expires = self.clock() + float(grant.get("expiresIn") or 0) if grant.get("expiresIn") else None
            cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at,refresh_supported) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET access_ciphertext=excluded.access_ciphertext,refresh_ciphertext=excluded.refresh_ciphertext,key_id=excluded.key_id,scopes=excluded.scopes,access_expires_at=excluded.access_expires_at,refresh_supported=excluded.refresh_supported,revoked_at=NULL,updated_at=now()", (workspace_id, connection_id, provider_id, identity["providerAccountId"], access_ct, refresh_ct, key_id, granted, expires, bool(refresh_ct)))
            now = self.clock()
            matrix = self._capabilities(adapter, capability, granted, missing, now)
            for name, value in matrix.items():
                cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level=excluded.level,evidence=excluded.evidence,capability_version=excluded.capability_version,verified_at=excluded.verified_at,updated_at=now()", (workspace_id, connection_id, name, value["level"], value["evidence"], value["capabilityVersion"], value["verifiedAt"]))
            audit(cur, workspace_id, principal, "channel.connected", connection_id, {"provider": provider_id, "capability": capability, "missingScopes": missing, "publishLevel": matrix["publish"]["level"]})
        channel = {"id": connection_id, "platform": adapter.platform, "account": identity.get("handle") or identity["providerAccountId"], "accountType": identity.get("accountType", "member"), "language": "English", "scopes": granted, "verifiedAt": now, "expiresAt": expires or now + 86400 * 30, "capabilityVersion": adapter.capability_version, "providerAccountId": identity["providerAccountId"]}
        snapshot = self.repository.get(workspace_id, token)
        saved = self.repository.command(workspace_id, token, snapshot["revision"], lambda state, actor: self.commands.upsert_verified_channel(state, actor, channel, capability_verified=not missing and matrix["publish"]["level"] == "Direct"), requirement="manage_connections")
        self._keep_picture(workspace_id, token, connection_id, identity)
        return {"connected": True, "connectionId": connection_id, "account": channel["account"], "providerAccountId": identity["providerAccountId"], "confirmAccount": True, "missingScopes": missing, "capabilities": matrix, "revision": saved["revision"]}

    def _keep_picture(self, workspace_id, token, connection_id, identity):
        """Download outside any transaction, then store: the account's picture for previews (account_pictures.py)."""
        outcome = account_pictures.picture_from_identity(identity, self.picture_fetch)
        if outcome[0] == "unavailable":
            return  # keep whatever picture was stored before
        try:
            with self.repository.transaction(token, workspace_id) as (cur, _, _):
                account_pictures.guarded(cur, account_pictures.store, workspace_id, connection_id, outcome)
        except AlphaError:
            pass  # membership ended in between; nothing to decorate

    def picture(self, workspace_id, token, connection_id):
        """The connected account's profile picture as (jpeg, digest); any member of the workspace may see it."""
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            found = account_pictures.guarded(cur, account_pictures.read, workspace_id, connection_id)
        if not found:
            raise AlphaError("This account has no picture.", 404)
        return found

    @staticmethod
    def _capabilities(adapter, requested, granted, missing, now):
        matrix = assisted_matrix() if adapter.assisted_fallback else unsupported_matrix()
        set_level(matrix, "identity", "Direct", "Provider identity endpoint matched the confirmed account.", now, adapter.capability_version)
        if requested in PUBLISH_CAPABILITIES:
            if missing:
                set_level(matrix, "publish", "Assisted" if adapter.assisted_fallback else "Unsupported", f"Granted scopes lack {', '.join(missing)}; export only.", now, adapter.capability_version)
            elif not adapter.production_reviewed:
                set_level(matrix, "publish", "Assisted" if adapter.assisted_fallback else "Unsupported", "Scopes granted, but the PostRiff app has not passed this provider's production review; export only.", now, adapter.capability_version)
            else:
                set_level(matrix, "publish", "Direct", "Official publish scope granted to a production-reviewed PostRiff app.", now, adapter.capability_version)
                set_level(matrix, "schedule", "Direct" if adapter.native_schedule else "Assisted", "Native scheduling" if adapter.native_schedule else "Scheduled by PostRiff workers; provider has no native schedule.", now, adapter.capability_version)
        for name in ("analytics", "comments_read", "reply", "moderate"):
            if name == requested and not missing:
                set_level(matrix, name, "Direct" if adapter.production_reviewed else "Unsupported", "Scope granted." if adapter.production_reviewed else "Awaiting provider review.", now, adapter.capability_version)
        return matrix

    # --- read / refresh / disconnect -------------------------------------------------
    def channels(self, workspace_id, token):
        snapshot = self.repository.get(workspace_id, token)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT connection_id,capability,level,evidence,capability_version,extract(epoch from verified_at) FROM public.pr_channel_capabilities WHERE workspace_id=%s", (workspace_id,))
            rows = cur.fetchall()
            pictures = account_pictures.guarded(cur, account_pictures.digests, workspace_id) or {}
        matrices = {}
        for connection_id, capability, level, evidence, version, verified in rows:
            matrices.setdefault(connection_id, unsupported_matrix())[capability] = {"level": level, "evidence": evidence, "capabilityVersion": version, "verifiedAt": float(verified) if verified else None}
        now = self.clock()
        return {"channels": [{**customer_view(c, matrices.get(c["id"], assisted_matrix()), now), "pictureDigest": pictures.get(c["id"])} for c in snapshot["state"].get("phase2", {}).get("channels", [])], "providers": [{"id": pid, "platform": a.platform, "productionReviewed": a.production_reviewed, "commentsReadImplemented": pid in COMMENT_READ_PROVIDERS, "capabilities": {cap: bool(a.capability_scopes(cap)) for cap in ("publish", "analytics", "comments_read", "reply")}} for pid, a in self.providers.items()]}

    def token_for_worker(self, workspace_id, connection_id):
        """Server-side only. Decrypts for the connector worker; refreshes when supported and expired."""
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT provider,access_ciphertext,refresh_ciphertext,key_id,extract(epoch from access_expires_at),refresh_supported,revoked_at IS NOT NULL,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s FOR UPDATE", (workspace_id, connection_id))
                row = cur.fetchone()
                if not row or row[6]:
                    raise AlphaError("Connection unavailable.", 404)
                provider, access_ct, refresh_ct, key_id, expires, refresh_supported, _, scopes = row
                if expires and expires <= self.clock():
                    if not (refresh_supported and refresh_ct):
                        raise AlphaError("Access expired and cannot be refreshed; re-authorization required.", 409)
                    grant = self._provider(provider).refresh(self.vault.decrypt(refresh_ct, key_id))
                    access_ct, key_id = self.vault.encrypt(grant["accessToken"])
                    new_refresh = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else refresh_ct
                    expires = self.clock() + float(grant.get("expiresIn") or 3600)
                    cur.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,access_expires_at=to_timestamp(%s),rotated_at=now(),updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (access_ct, new_refresh, key_id, expires, workspace_id, connection_id))
                return {"provider": provider, "accessToken": self.vault.decrypt(access_ct, key_id), "scopes": list(scopes), "expiresAt": expires}

    def verify(self, workspace_id, token, connection_id):
        """Re-check identity and scope drift for an existing connection."""
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT provider,provider_account_id,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))
            stored = cur.fetchone()
            if not stored:
                raise AlphaError("Connection unavailable.", 404)
        provider_id, account_id, scopes = stored
        adapter = self._provider(provider_id)
        try:
            grant = self.token_for_worker(workspace_id, connection_id)
            identity = adapter.identity(grant["accessToken"])
            drift = identity["providerAccountId"] != account_id
            result = {"connectionId": connection_id, "identityVerified": not drift, "scopes": list(scopes), "state": "reauthorization_required" if drift else "read_verified"}
            if not drift:
                self._keep_picture(workspace_id, token, connection_id, identity)
        except AlphaError as error:
            result = {"connectionId": connection_id, "identityVerified": False, "state": "token_expired", "detail": str(error)}
        with self.repository.transaction(token, workspace_id) as (cur, _, principal):
            from .hosted import audit
            audit(cur, workspace_id, principal, "channel.verified", connection_id, {"state": result["state"]})
        return result

    def disconnect(self, workspace_id, token, connection_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            self.repository.assert_fresh(token, principal)
            cur.execute("SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            stored = cur.fetchone()
            if not stored:
                raise AlphaError("Connection unavailable.", 404)
            remote = None
            try:
                remote = self._provider(stored[0]).revoke(self.vault.decrypt(stored[1], stored[2]))
            except AlphaError:
                remote = False
            cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Disconnected by the customer.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            account_pictures.guarded(cur, account_pictures.remove, workspace_id, connection_id)
            audit(cur, workspace_id, principal, "channel.disconnected", connection_id, {"remoteRevoked": bool(remote)})
        snapshot = self.repository.get(workspace_id, token)
        try:
            saved = self.repository.mutate(workspace_id, token, snapshot["revision"], "p2_channel_disconnect", {"channelId": connection_id})
            revision = saved["revision"]
        except AlphaError:
            revision = snapshot["revision"]  # channel absent from state; credentials are already revoked
        return {"connectionId": connection_id, "disconnected": True, "remoteRevoked": bool(remote), "revision": revision, "note": "Local execution access removed; approved jobs for this account are held at the next claim."}

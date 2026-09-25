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
            raise AlphaError("Connecting accounts isn't available right now.", 503)
        return self.fernet.encrypt(plaintext.encode()).decode(), self.key_id

    def decrypt(self, ciphertext, key_id):
        if not self.fernet:
            raise AlphaError("Connecting accounts isn't available right now.", 503)
        if key_id != self.key_id:
            raise AlphaError("This account needs to be reconnected.", 409)
        from cryptography.fernet import InvalidToken
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as error:
            raise AlphaError("This account needs to be reconnected.", 409) from error


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


class OAuthService:
    def __init__(self, repository, commands, vault, providers, public_base_url, clock=time.time):
        self.repository, self.commands, self.vault, self.clock = repository, commands, vault, clock
        self.providers = providers if providers is not None else {}
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.picture_fetch = account_pictures.fetch_image  # replaced in tests; never reached without a picture URL
        from .social_history import SocialHistoryService
        self.history = SocialHistoryService(self)

    def provider_catalog(self):
        """Secret-free deployment readiness; an unconfigured tile is never an adapter."""
        from .providers import ADAPTERS
        entries = []
        for pid, cls in ADAPTERS.items():
            adapter = self.providers.get(pid)
            issues = []
            diagnostic = getattr(self.providers, 'diagnostics', {}).get(pid, {})
            configuration = diagnostic.get('configurationState', 'configured' if adapter else 'not_configured')
            presence = diagnostic.get('credentialPresence', {'clientId': adapter is not None, 'clientSecret': adapter is not None})
            if adapter is None:
                prefix = f'POSTRIFF_OAUTH_{pid.upper()}_'
                missing = diagnostic.get('missingVariables', [prefix + 'CLIENT_ID', prefix + 'CLIENT_SECRET'])
                issues.append('Server setup required: configure ' + ' and '.join(missing) + '. These are channel credentials, not app sign-in providers.' if missing else 'The OAuth credential pair contains a blank, whitespace or placeholder value. Correct it in secure server configuration.')
            if not self.vault.fernet:
                issues.append('Server setup required: POSTRIFF_CREDENTIAL_KEY must protect connected-account tokens.')
            try:
                callback = self.callback_uri(pid)
            except AlphaError:
                callback = None
                issues.append('Set POSTRIFF_PUBLIC_BASE_URL to the fixed HTTPS app origin and register its callback with the provider.')
            paused = adapter is not None and not getattr(adapter, 'execution_enabled', True)
            if paused:
                issues.append('This connector is paused by the operator.')
            history = pid == 'instagram' or (pid == 'linkedin' and bool(getattr(adapter, 'history_approved', False)))
            connect_ready = adapter is not None and not issues
            reviewed = bool(adapter and adapter.production_reviewed)
            readiness = configuration if adapter is None else 'paused' if paused else 'configuration_blocked' if not connect_ready else 'identity_connection_available' if reviewed else 'configured_awaiting_provider_review'
            entries.append({'id': pid, 'platform': cls.platform, 'configured': adapter is not None,
                            'connectReady': connect_ready, 'configurationState': configuration, 'credentialPresence': presence,
                            'readinessState': readiness, 'publicConnectionReady': connect_ready and reviewed, 'liveVerified': False,
                            'reviewStatus': 'operator_declared_reviewed' if reviewed else 'not_confirmed',
                            'reviewNote': 'Review readiness is operator-declared, not independently verified with the platform. Unreviewed apps may be limited to eligible app-role test accounts.',
                            'productionReviewed': reviewed, 'executionPaused': paused,
                            'callbackUri': callback, 'setupIssues': issues, 'commentsReadImplemented': pid in COMMENT_READ_PROVIDERS,
                            'historyAvailableForApp': history,
                            'accountRequirement': 'Instagram Creator or Business account. No Facebook Page required.' if pid == 'instagram' else 'LinkedIn member profile.' if pid == 'linkedin' else 'Threads profile.',
                            'capabilities': {cap: bool(adapter and adapter.capability_scopes(cap)) for cap in ('identity', 'posts_read', 'publish', 'analytics', 'comments_read', 'reply')}})
        # Keep explicitly injected/test providers visible without changing their authority.
        for pid, adapter in self.providers.items():
            if pid not in ADAPTERS:
                entries.append({'id': pid, 'platform': adapter.platform, 'configured': True, 'productionReviewed': adapter.production_reviewed,
                                'executionPaused': not getattr(adapter, 'execution_enabled', True),
                                'capabilities': {cap: bool(adapter.capability_scopes(cap)) for cap in ('identity', 'publish', 'analytics', 'comments_read', 'reply')}})
        return entries

    @staticmethod
    def connection_readiness(channel, provider):
        """Independent permissions from the last verified grant, not a live acceptance claim."""
        connected = channel.get('connectionState') in ('read_verified', 'publish_verified')
        provider = provider or {}
        usable = connected and provider.get('configured') and provider.get('connectReady') and not provider.get('executionPaused')
        scopes = set(channel.get('scopes') or [])
        platform = channel.get('platform')
        read_scope = 'instagram_business_basic' if platform == 'Instagram' else 'r_member_social' if platform == 'LinkedIn' else None
        publish_scope = 'instagram_business_content_publish' if platform == 'Instagram' else 'w_member_social' if platform == 'LinkedIn' else None
        history = 'HISTORICAL_IMPORT_UNAVAILABLE'
        publishing = 'PUBLISHING_PERMISSION_UNAVAILABLE'
        if usable:
            if platform == 'LinkedIn' and not provider.get('historyAvailableForApp'):
                history = 'HISTORICAL_IMPORT_AWAITING_PROVIDER_APPROVAL'
            elif read_scope and read_scope in scopes:
                history = 'HISTORICAL_IMPORT_AVAILABLE'
            elif read_scope:
                history = 'HISTORICAL_IMPORT_PERMISSION_UNAVAILABLE'
            if publish_scope and publish_scope in scopes:
                if not provider.get('productionReviewed'):
                    publishing = 'PUBLISHING_AWAITING_PROVIDER_REVIEW'
                elif channel.get('capabilities', {}).get('publish', {}).get('level') == 'Direct':
                    publishing = 'PUBLISHING_AVAILABLE'
        return {'connection': 'CONNECTED' if connected else 'REAUTHORIZATION_REQUIRED' if channel.get('connectionState') in ('token_expired', 'reauthorization_required', 'scope_missing') else 'NOT_CONNECTED',
                'history': history, 'publishing': publishing,
                'fullyAvailable': history == 'HISTORICAL_IMPORT_AVAILABLE' and publishing == 'PUBLISHING_AVAILABLE',
                'evidence': 'last_verified_grant', 'liveVerified': False}

    def _provider(self, provider_id):
        adapter = self.providers.get(provider_id)
        if adapter is None:
            raise AlphaError("This platform isn't available yet.", 404)
        return adapter

    def callback_uri(self, provider_id):
        origin = urlparse(self.public_base_url)
        if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            raise AlphaError("A fixed public HTTPS app origin, without a path or query, is required for OAuth.", 503)
        return f"{self.public_base_url}/api/oauth/{provider_id}/callback"

    # --- start ----------------------------------------------------------------------
    def start(self, workspace_id, token, provider_id, capability):
        adapter = self._provider(provider_id)
        if not getattr(adapter, "execution_enabled", True):
            raise AlphaError("This platform is paused for now. Your post history stays available.", 503)
        if capability not in (*CAPABILITIES, 'posts_read') or capability in ("media_types", "webhooks"):
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
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s)) RETURNING id::text", (workspace_id, principal, provider_id, 'identity' if capability == 'posts_read' else capability, redirect, list(scopes), hashlib.sha256(state.encode()).hexdigest(), ciphertext, key_id, TRANSACTION_TTL))
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
        if not getattr(adapter, "execution_enabled", True):
            raise AlphaError("This platform is paused for now. Connect again when it's back.", 503)
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
            # Requested scopes are not proof of granted scopes. Empty/unknown fails closed.
            reported = grant.get('scopes')
            if reported is None and hasattr(adapter, 'inspect_scopes'):
                reported = adapter.inspect_scopes(grant['accessToken'], identity['providerAccountId'])
            if reported is None and hasattr(adapter, 'verify_read_access'):
                # This proves basic read access only; it never supplies requested write scopes.
                reported = adapter.verify_read_access(grant['accessToken'], identity['providerAccountId'])
            granted = sorted(set(reported)) if isinstance(reported, list) and all(isinstance(s, str) for s in reported) else []
            missing = sorted(set(scopes) - set(granted))
            connection_id = hashlib.sha256(f"{provider_id}:{identity['providerAccountId']}".encode()).hexdigest()[:32]
            from .billing import require_plan_capacity
            require_plan_capacity(cur, workspace_id, "connected_accounts", connection_id)
            access_ct, key_id = self.vault.encrypt(grant["accessToken"])
            refresh_ct = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else None
            expires = self.clock() + float(grant.get("expiresIn") or 0) if grant.get("expiresIn") else None
            cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at,refresh_supported) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET access_ciphertext=excluded.access_ciphertext,refresh_ciphertext=excluded.refresh_ciphertext,key_id=excluded.key_id,scopes=excluded.scopes,access_expires_at=excluded.access_expires_at,refresh_supported=excluded.refresh_supported,revoked_at=NULL,rotated_at=now(),updated_at=now()", (workspace_id, connection_id, provider_id, identity["providerAccountId"], access_ct, refresh_ct, key_id, granted, expires, bool(refresh_ct)))
            now = self.clock()
            matrix = self._capabilities(adapter, capability, granted, missing, now)
            for name, value in matrix.items():
                cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level=excluded.level,evidence=excluded.evidence,capability_version=excluded.capability_version,verified_at=excluded.verified_at,updated_at=now()", (workspace_id, connection_id, name, value["level"], value["evidence"], value["capabilityVersion"], value["verifiedAt"]))
            audit(cur, workspace_id, principal, "channel.connected", connection_id, {"provider": provider_id, "capability": capability, "missingScopes": missing, "publishLevel": matrix["publish"]["level"]})
        channel = {"id": connection_id, "platform": adapter.platform, "account": identity.get("handle") or identity["providerAccountId"], "accountType": identity.get("accountType", "member"), "scopes": granted, "verifiedAt": now, "expiresAt": expires or now + 86400 * 30, "capabilityVersion": adapter.capability_version, "providerAccountId": identity["providerAccountId"]}
        snapshot = self.repository.get(workspace_id, token)
        saved = self.repository.command(workspace_id, token, snapshot["revision"], lambda state, actor: self.commands.upsert_verified_channel(state, actor, channel, capability_verified=not missing and matrix["publish"]["level"] == "Direct"), requirement="manage_connections")
        self._keep_picture(workspace_id, token, connection_id, identity)
        return {"connected": True, "connectionId": connection_id, "account": channel["account"], "providerAccountId": identity["providerAccountId"], "confirmAccount": True, "missingScopes": missing, "capabilities": matrix, "revision": saved["revision"]}

    def _keep_picture(self, workspace_id, token, connection_id, identity):
        """Download outside any transaction, then store: the account's picture for previews (account_pictures.py)."""
        try:
            outcome = account_pictures.picture_from_identity(identity, self.picture_fetch)
        except Exception:  # noqa: BLE001 - runs after the connection is saved; a picture fault must not report it as failed
            return
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
        set_level(matrix, "identity", "Direct", "Account confirmed.", now, adapter.capability_version)
        if requested in PUBLISH_CAPABILITIES:
            if missing:
                set_level(matrix, "publish", "Assisted" if adapter.assisted_fallback else "Unsupported", "Some permissions weren't granted, so you post the last step yourself.", now, adapter.capability_version)
            elif not adapter.production_reviewed:
                set_level(matrix, "publish", "Assisted" if adapter.assisted_fallback else "Unsupported", f"{adapter.platform} hasn't approved Rafii's publishing yet, so you post the last step yourself.", now, adapter.capability_version)
            else:
                set_level(matrix, "publish", "Direct", "You approve each post; Rafii publishes it.", now, adapter.capability_version)
                set_level(matrix, "schedule", "Direct" if adapter.native_schedule else "Assisted", f"Scheduled on {adapter.platform}." if adapter.native_schedule else "Rafii publishes at the scheduled time.", now, adapter.capability_version)
        for name in ("analytics", "comments_read", "reply", "moderate"):
            if name == requested and not missing:
                set_level(matrix, name, "Direct" if adapter.production_reviewed else "Unsupported", "Granted." if adapter.production_reviewed else f"Waiting for {adapter.platform} to approve Rafii.", now, adapter.capability_version)
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
        catalog = self.provider_catalog()
        by_platform = {provider['platform']: provider for provider in catalog}
        views = [{**customer_view(c, matrices.get(c['id'], assisted_matrix()), now), 'pictureDigest': pictures.get(c['id'])} for c in snapshot['state'].get('phase2', {}).get('channels', [])]
        for view in views:
            view['socialReadiness'] = self.connection_readiness(view, by_platform.get(view['platform']))
        return {'channels': views, 'providers': catalog}

    def token_for_worker(self, workspace_id, connection_id):
        """Server-only token custody. Instagram renews while valid, never after expiry."""
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                # float8: extract() is numeric (a Decimal) since PostgreSQL 14, and Decimal - float raises TypeError.
                cur.execute("SELECT provider,access_ciphertext,refresh_ciphertext,key_id,extract(epoch from access_expires_at)::float8,refresh_supported,revoked_at IS NOT NULL,scopes,provider_account_id,extract(epoch from coalesce(rotated_at,updated_at,created_at))::float8 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s FOR UPDATE", (workspace_id, connection_id))
                row = cur.fetchone()
                if not row or row[6]:
                    raise AlphaError("Connection unavailable.", 404)
                provider, access_ct, refresh_ct, key_id, expires, refresh_supported, _, scopes, account_id, issued_at = row
                if not getattr(self._provider(provider), "execution_enabled", True):
                    raise AlphaError("This platform is paused for now. Your post history stays available.", 503)
                now = self.clock()
                expired = bool(expires and expires <= now)
                if provider == 'instagram' and expired:
                    raise AlphaError('Instagram access expired; re-authorization required. Expired long-lived tokens cannot be refreshed.', 409, code='reauthorization_required')
                # Refresh requires a still-valid token at least 24 hours old.
                # Unknown age never grants permission to renew; reconnect remains available.
                renew_instagram = (provider == 'instagram' and expires and 0 < expires - now <= 7 * 86400
                                   and issued_at is not None and now - issued_at >= 86400
                                   and refresh_supported and refresh_ct)
                if expired or renew_instagram:
                    if not (refresh_supported and refresh_ct):
                        raise AlphaError("Access expired and cannot be refreshed; re-authorization required.", 409)
                    grant = self._provider(provider).refresh(self.vault.decrypt(refresh_ct, key_id))
                    access_ct, key_id = self.vault.encrypt(grant["accessToken"])
                    new_refresh = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else refresh_ct
                    expires = self.clock() + float(grant.get("expiresIn") or 3600)
                    cur.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,access_expires_at=to_timestamp(%s),rotated_at=now(),updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (access_ct, new_refresh, key_id, expires, workspace_id, connection_id))
                access_token = self.vault.decrypt(access_ct, key_id)
                inspector = getattr(self._provider(provider), "inspect_scopes", None)
                if inspector:
                    reported = inspector(access_token, account_id)
                    scopes = reported if isinstance(reported, list) and all(isinstance(s, str) for s in reported) else []
                    cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (scopes, workspace_id, connection_id))
                return {"provider": provider, "accessToken": access_token, "scopes": list(scopes), "expiresAt": expires}

    def verify(self, workspace_id, token, connection_id):
        """Re-check identity and scope drift for an existing connection."""
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT provider,provider_account_id,scopes,access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))
            stored = cur.fetchone()
            if not stored:
                raise AlphaError("Connection unavailable.", 404)
        provider_id, account_id, scopes, starting_ciphertext = stored
        adapter = self._provider(provider_id)
        grant = None
        reported = []
        identity = None
        # A read proof (Instagram Login) never observes write scopes. When it sees a strict subset of the stored
        # grant, the grant is kept as stored and trust is not extended, as in reverify_for_worker.
        lower_bound = False
        try:
            grant = self.token_for_worker(workspace_id, connection_id)
            identity = adapter.identity(grant["accessToken"])
            drift = identity["providerAccountId"] != account_id
            inspected = hasattr(adapter, "inspect_scopes")
            reported = grant["scopes"] if inspected and not drift else []
            if not drift and not inspected and hasattr(adapter, 'verify_read_access'):
                reported = adapter.verify_read_access(grant['accessToken'], account_id)
                lower_bound = bool(reported) and set(reported) < set(scopes)
            changed = set(reported) != set(scopes)
            result = {"connectionId": connection_id, "identityVerified": not drift, "scopes": list(scopes) if lower_bound else reported,
                      "state": "reauthorization_required" if drift else "scope_missing" if not reported else "read_verified" if lower_bound or not changed else "scope_changed"}
        except AlphaError:
            # Do not leak provider responses, nor label a transient network failure as token expiry.
            result = {"connectionId": connection_id, "identityVerified": False, "scopes": [], "state": "verification_unavailable"}
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            current = cur.fetchone()
            if not current or (grant and self.vault.decrypt(current[0], current[1]) != grant["accessToken"]) or (not grant and current[0] != starting_ciphertext):
                raise AlphaError("Connection changed during verification; reload and verify again.", 409)
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            channel = next((c for c in state.get("phase2", {}).get("channels", []) if c["id"] == connection_id), None)
            if channel is None:
                raise AlphaError("Connection unavailable.", 404)
            if lower_bound:
                channel["identityVerified"] = True
            else:
                channel.update(scopes=reported, identityVerified=result["identityVerified"], verifiedAt=self.clock())
            if grant:
                channel["expiresAt"] = float(grant["expiresAt"]) if grant["expiresAt"] else channel.get("expiresAt", 0)
            if result["state"] != "read_verified":
                channel["capabilityVerified"] = False
                cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Permissions changed or could not be verified; reconnect and review.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND capability<>'identity'", (workspace_id, connection_id))
            if result["state"] == "reauthorization_required":
                channel["revoked"] = True
            if not lower_bound:
                cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (reported, workspace_id, connection_id))
            self.commands.engine.invalidate(state)
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            audit(cur, workspace_id, principal, "channel.verified", connection_id, {"state": result["state"]})
        if identity and result["identityVerified"]:
            self._keep_picture(workspace_id, token, connection_id, identity)
        return result

    # --- worker re-verification (orchestration §5 step 2) ------------------------------
    WORKER_REVERIFIED = "channel.reverified_by_worker"

    def reverify_for_worker(self, workspace_id, connection_id):
        """Re-verify a channel on the worker's own authority, right before an approved post is committed.

        SERVER-SIDE ONLY: there is no session token and no membership check, so this must never be reachable
        from an HTTP route. The publish worker calls it at publishAt - 30 min so the channel stays
        "Ready for posting" (verifiedAt + 3600 >= now) until the post goes out.

        Mirrors verify(): stored credential -> token_for_worker -> identity -> account drift -> live scopes, with
        the same states (read_verified | scope_changed | scope_missing | reauthorization_required |
        verification_unavailable). Differences, all in the worker's favour of doing no harm:
        - It never upgrades authority. capabilityVerified and capability levels only ever go down here; only a
          person reconnecting (complete) restores them.
        - store.current() compares manifest scopes to channel scopes as LISTS, so when the reported set equals
          the channel's set the stored list is kept as is (a provider reordering its scopes must not hold every
          approved job). A different set is stored sorted and takes verify()'s downgrade path. A difference from
          either the credential's or the channel's scopes counts as scope_changed.
        - Provider or network failure, a credential rotated by a person mid-check, a workspace pending deletion,
          or a provider that can only prove a subset of the stored grant (Instagram's verify_read_access proves
          read access, never write scopes) returns verification_unavailable with the channel untouched:
          verifiedAt is not extended and nothing is downgraded.
        - The account picture is not refreshed (that path needs a member session).
        Raises AlphaError 404 only for an unknown or revoked connection. Every outcome is audited with a NULL
        (system) actor. Returns {"connectionId", "state", "ready"}; ready means read_verified and the channel is
        "Ready for posting" now.
        """
        from .hosted import audit
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT c.provider,c.provider_account_id,w.state FROM public.pr_encrypted_credentials c JOIN public.pr_workspaces w ON w.id=c.workspace_id WHERE c.workspace_id=%s AND c.connection_id=%s AND c.revoked_at IS NULL", (workspace_id, connection_id))
                stored = cur.fetchone()
        if not stored:
            raise AlphaError("Connection unavailable.", 404)
        provider_id, account_id, state = stored
        state = json.loads(state) if isinstance(state, str) else state
        if not any(c.get("id") == connection_id for c in state.get("phase2", {}).get("channels", [])):
            raise AlphaError("Connection unavailable.", 404)

        def unavailable(cur, reason):
            audit(cur, workspace_id, None, self.WORKER_REVERIFIED, connection_id, {"state": "verification_unavailable", "reason": reason})
            return {"connectionId": connection_id, "state": "verification_unavailable", "ready": False}

        if state.get("accountDeletion"):
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    return unavailable(cur, "account_deletion_pending")
        lower_bound = False
        try:
            adapter = self._provider(provider_id)
            grant = self.token_for_worker(workspace_id, connection_id)
            identity = adapter.identity(grant["accessToken"])
            drift = identity["providerAccountId"] != account_id
            inspected = hasattr(adapter, "inspect_scopes")
            reported = grant["scopes"] if inspected and not drift else []
            if not drift and not inspected and hasattr(adapter, "verify_read_access"):
                reported = adapter.verify_read_access(grant["accessToken"], account_id)
                lower_bound = True
        except (AlphaError, KeyError, TypeError, ValueError, OSError):
            # Do not leak provider responses, and never turn a transient failure into lost authority.
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    return unavailable(cur, "provider_unavailable")
        reported = list(reported) if isinstance(reported, list) and all(isinstance(s, str) for s in reported) else []
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
                locked = cur.fetchone()
                cur.execute("SELECT access_ciphertext,key_id,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
                current = cur.fetchone()
                if not locked or not current:
                    raise AlphaError("Connection unavailable.", 404)
                try:
                    same_credential = self.vault.decrypt(current[0], current[1]) == grant["accessToken"]
                except AlphaError:
                    same_credential = False
                if not same_credential:
                    return unavailable(cur, "credential_rotated")  # a person re-authorized meanwhile; their grant wins
                state = json.loads(locked[0]) if isinstance(locked[0], str) else locked[0]
                if state.get("accountDeletion"):
                    return unavailable(cur, "account_deletion_pending")
                channel = next((c for c in state.get("phase2", {}).get("channels", []) if c.get("id") == connection_id), None)
                if channel is None:
                    raise AlphaError("Connection unavailable.", 404)
                existing, credential_scopes, observed = set(channel.get("scopes") or []), set(current[2] or []), set(reported)
                if lower_bound and observed and observed <= existing and observed <= credential_scopes and not observed == existing == credential_scopes:
                    return unavailable(cur, "grant_not_observable")
                changed = observed != credential_scopes or observed != existing
                outcome = "reauthorization_required" if drift else "scope_missing" if not reported else "scope_changed" if changed else "read_verified"
                if observed != existing:
                    channel["scopes"] = sorted(observed)
                channel.update(identityVerified=not drift, verifiedAt=self.clock())
                channel["expiresAt"] = float(grant["expiresAt"]) if grant.get("expiresAt") else channel.get("expiresAt", 0)
                if outcome != "read_verified":
                    channel["capabilityVerified"] = False
                    cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Permissions changed or could not be verified; reconnect and review.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND capability<>'identity'", (workspace_id, connection_id))
                if outcome == "reauthorization_required":
                    channel["revoked"] = True
                if observed != credential_scopes:
                    cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (sorted(observed), workspace_id, connection_id))
                self.commands.engine.invalidate(state)
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
                audit(cur, workspace_id, None, self.WORKER_REVERIFIED, connection_id, {"state": outcome})
                ready = outcome == "read_verified" and self.commands.engine.channel_state(channel) == "Ready for posting"
        return {"connectionId": connection_id, "state": outcome, "ready": ready}

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
            from .social_history import revoke_connection_samples
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            revoked_samples = revoke_connection_samples(state, connection_id, principal, self.clock())
            if revoked_samples:
                self.commands.engine.invalidate(state)
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))
                audit(cur, workspace_id, principal, 'voice.connection_samples_revoked', connection_id, {'samples': revoked_samples})
            account_pictures.guarded(cur, account_pictures.remove, workspace_id, connection_id)
            audit(cur, workspace_id, principal, "channel.disconnected", connection_id, {"remoteRevoked": bool(remote)})
        snapshot = self.repository.get(workspace_id, token)
        try:
            saved = self.repository.mutate(workspace_id, token, snapshot["revision"], "p2_channel_disconnect", {"channelId": connection_id})
            revision = saved["revision"]
        except AlphaError:
            revision = snapshot["revision"]  # channel absent from state; credentials are already revoked
        return {"connectionId": connection_id, "disconnected": True, "remoteRevoked": bool(remote), "revision": revision, "note": "Local execution access removed; approved jobs for this account are held at the next claim."}

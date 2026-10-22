"""Telegram OIDC identity linking. Bot destination grants remain independent."""
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from postriff_alpha.domain import AlphaError
from ..permissions import require
from ..providers import http_transport
from ..oauth import pkce_pair

ISSUER = "https://oauth.telegram.org"


def decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_id_token(token, jwks, client_id, now):
    """Pin RS256 and Telegram's keys; reject algorithm/key injection and stale claims."""
    try:
        if not isinstance(token, str) or len(token) > 16384:
            raise ValueError()
        header64, claims64, signature64 = token.split(".")
        header, claims = json.loads(decode(header64)), json.loads(decode(claims64))
        if header.get("alg") != "RS256" or header.get("crit") or not isinstance(header.get("kid"), str):
            raise ValueError()
        keys = [k for k in jwks["keys"] if k.get("kid") == header["kid"] and k.get("kty") == "RSA"
                and k.get("use", "sig") == "sig" and k.get("alg", "RS256") == "RS256"]
        if len(keys) != 1:
            raise ValueError()
        key = keys[0]
        public = rsa.RSAPublicNumbers(int.from_bytes(decode(key["e"]), "big"), int.from_bytes(decode(key["n"]), "big")).public_key()
        if public.key_size < 2048:
            raise ValueError()
        public.verify(decode(signature64), (header64 + "." + claims64).encode(), padding.PKCS1v15(), hashes.SHA256())
        if claims.get("iss") != ISSUER or claims.get("aud") != str(client_id):
            raise ValueError()
        for field in ("iat", "exp"):
            if type(claims.get(field)) not in (int, float) or not math.isfinite(claims[field]):
                raise ValueError()
        if claims["exp"] <= now or claims["iat"] > now + 30 or claims["exp"] <= claims["iat"]:
            raise ValueError()
        if "nbf" in claims and (type(claims["nbf"]) not in (int, float) or not math.isfinite(claims["nbf"]) or claims["nbf"] > now):
            raise ValueError()
        if not isinstance(claims.get("sub"), str) or not re.fullmatch(r"[0-9]{1,64}", claims["sub"]):
            raise ValueError()
        if type(claims.get("id")) is not int or not 0 < claims["id"] < 2**52:
            raise ValueError()
        return {"subject": claims["sub"], "telegramUserId": str(claims["id"]),
                "name": str(claims.get("name", ""))[:256], "username": str(claims.get("preferred_username", ""))[:64]}
    except Exception:
        raise AlphaError("Telegram identity verification failed. Start a new connection.", 403) from None


class TelegramLogin:
    def __init__(self, telegram, values=None, transport=None, clock=time.time):
        self.telegram, self.repository, self.vault = telegram, telegram.repository, telegram.vault
        values = values or {}
        self.client_id, self.client_secret = values.get("POSTRIFF_TELEGRAM_LOGIN_CLIENT_ID"), values.get("POSTRIFF_TELEGRAM_LOGIN_CLIENT_SECRET")
        self.transport, self.clock = transport or http_transport, clock
        self.canary_mode = values.get("POSTRIFF_TELEGRAM_LOGIN_USE_DEPLOYMENT_ORIGIN") == "true"
        self.canary_scope = None
        # Identity callbacks must return to the build that started the flow. Keep
        # their origin separate from the existing bot webhook/public API origin.
        self.base = "https://rafii.io" if values.get("VERCEL_ENV") == "production" else (telegram.oauth.public_base_url or "").rstrip("/")
        if self.canary_mode:
            self.base = ""  # An invalid canary must not silently return to live.
            try:
                from ..social_release import require_production_binding
                require_production_binding(values)
                scope = getattr((getattr(telegram.oauth, "providers", None) or {}).get("telegram"), "candidate_scope", None)
                expires = scope.get("expiresAt") if isinstance(scope, dict) else None
                host = values.get("VERCEL_URL", "")
                if (values.get("VERCEL_ENV") == "production" and values.get("POSTRIFF_TELEGRAM_CANARY_ENABLED") == "true"
                        and type(expires) in (int, float) and math.isfinite(expires) and self.clock() < expires <= self.clock() + 86400
                        and isinstance(host, str) and len(host) <= 253
                        and re.fullmatch(r"postriff-phase2-private-[a-z0-9-]+\.vercel\.app", host)):
                    self.base = "https://" + host
                    self.canary_scope = scope
            except (ValueError, TypeError):
                pass
        self.keys, self.keys_until = None, 0

    def configured(self):
        parsed = urlparse(self.base)
        if self.canary_mode and (not self.canary_scope or self.canary_scope["expiresAt"] <= self.clock()):
            return False
        return bool(isinstance(self.client_id, str) and re.fullmatch(r"[0-9]{5,16}", self.client_id)
                    and isinstance(self.client_secret, str) and self.client_secret
                    and parsed.scheme == "https" and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment)

    def _require_canary_actor(self, workspace, actor):
        if self.canary_mode and (not self.configured() or str(workspace) != self.canary_scope.get("workspaceId")
                                 or str(actor) != self.canary_scope.get("actorId")):
            raise AlphaError("This Telegram identity acceptance grant is unavailable for this member or workspace.", 403)

    def list(self, workspace, token):
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            from ..hosted import _membership
            require(_membership(row), "manage_connections")
            self._require_canary_actor(workspace, actor)
            cur.execute("SELECT id::text,identity FROM public.pr_telegram_identities WHERE workspace_id=%s AND member_id=%s AND revoked_at IS NULL ORDER BY linked_at", (workspace, actor))
            return {"configured": self.configured(), "identities": [{"id": r[0], **r[1]} for r in cur.fetchall()],
                    "permissionExplanation": "Telegram Login verifies your identity. Authorize channels, groups and Secretary conversations separately."}

    def start(self, workspace, token):
        if not self.configured():
            raise AlphaError("Telegram Login needs BotFather Allowed URLs and login credentials configured by Rafii.", 503)
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        redirect = self.base + "/api/telegram/login/callback"
        from ..hosted import _membership, audit, throttle
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections")
            self._require_canary_actor(workspace, actor)
            self.repository.assert_fresh(token, actor)
            ciphertext, key = self.vault.encrypt(json.dumps({"pkce": verifier, "clientId": self.client_id}))
            throttle(cur, "telegram-login:" + workspace, 20, 600)
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,'telegram_login','identity',%s,%s,%s,%s,%s,now()+interval '10 minutes')", (workspace, actor, redirect, ["openid", "profile"], hashlib.sha256(state.encode()).hexdigest(), ciphertext, key))
            audit(cur, workspace, actor, "telegram.identity.started", "", {})
        return {"authorizeUrl": ISSUER + "/auth?" + urlencode({"client_id": self.client_id, "redirect_uri": redirect,
                "response_type": "code", "scope": "openid profile", "state": state, "code_challenge": challenge,
                "code_challenge_method": "S256"}), "expiresAt": self.clock() + 600}

    def complete(self, workspace, token, body):
        state, code = body.get("state"), body.get("code")
        if not self.configured():
            raise AlphaError("Telegram Login is unavailable.", 503)
        if not isinstance(state, str) or not 32 <= len(state) <= 128:
            raise AlphaError("Connection request unavailable.", 404)
        from ..hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections")
            self._require_canary_actor(workspace, actor)
            self.repository.assert_fresh(token, actor)
            cur.execute("SELECT id::text,member_id::text,verifier_ciphertext,key_id,redirect_uri,extract(epoch from expires_at),consumed_at FROM public.pr_oauth_transactions WHERE workspace_id=%s AND provider='telegram_login' AND state_hash=%s FOR UPDATE", (workspace, hashlib.sha256(state.encode()).hexdigest()))
            txn = cur.fetchone()
            if not txn or txn[1] != actor or txn[6] is not None or txn[5] <= self.clock():
                raise AlphaError("Connection request expired or unavailable.", 404)
            custody = json.loads(self.vault.decrypt(txn[2], txn[3]))
            if not hmac.compare_digest(custody["clientId"], self.client_id):
                raise AlphaError("Telegram Login configuration changed. Start again.", 409)
            # Claim before exchange; a timeout cannot cause the same code to be exchanged twice.
            cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='denied',verifier_ciphertext='' WHERE id=%s", (txn[0],))
        if body.get("error"):
            return {"status": "denied"}
        if not isinstance(code, str) or not 1 <= len(code) <= 2048:
            raise AlphaError("Telegram authorization code unavailable.", 400)
        try:
            response = self.transport("POST", ISSUER + "/token", headers={"Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + base64.b64encode((self.client_id + ":" + self.client_secret).encode()).decode()},
                data=urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": txn[4],
                                "client_id": self.client_id, "code_verifier": custody["pkce"]}).encode())
            if response.get("status") != 200:
                raise ValueError()
            if self.keys is None or self.keys_until <= self.clock():
                result = self.transport("GET", ISSUER + "/.well-known/jwks.json")
                if result.get("status") != 200 or not isinstance(result.get("body", {}).get("keys"), list) or len(result["body"]["keys"]) > 16:
                    raise ValueError()
                self.keys, self.keys_until = result["body"], self.clock() + 300
            identity = verify_id_token(response["body"].get("id_token"), self.keys, self.client_id, self.clock())
        except AlphaError:
            raise
        except Exception:
            raise AlphaError("Telegram authorization could not be verified. Start a new connection.", 502) from None
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections")
            self._require_canary_actor(workspace, actor)
            self.repository.assert_fresh(token, actor)
            # Global owner fence serializes linking the same Telegram identity across tenants.
            cur.execute("INSERT INTO public.pr_telegram_identity_owners(bot_id,subject,member_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (self.client_id, identity["subject"], actor))
            cur.execute("SELECT member_id::text FROM public.pr_telegram_identity_owners WHERE bot_id=%s AND subject=%s FOR UPDATE", (self.client_id, identity["subject"]))
            if cur.fetchone()[0] != actor:
                raise AlphaError("This Telegram identity is linked to another Rafii account.", 409)
            cur.execute("INSERT INTO public.pr_telegram_identities(workspace_id,member_id,bot_id,subject,telegram_user_id,identity) VALUES(%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(workspace_id,member_id,bot_id,subject) DO UPDATE SET identity=excluded.identity,revoked_at=NULL,linked_at=now() RETURNING id::text", (workspace, actor, self.client_id, identity["subject"], identity["telegramUserId"], json.dumps(identity)))
            identity_id = cur.fetchone()[0]
            cur.execute("UPDATE public.pr_oauth_transactions SET outcome='exchanged' WHERE id=%s", (txn[0],))
            audit(cur, workspace, actor, "telegram.identity.linked", identity_id, {})
        return {"status": "connected", "identity": {"id": identity_id, **identity}, "managementGranted": False}

    def disconnect(self, workspace, token, identity_id):
        from ..hosted import _membership, audit
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "manage_connections")
            self._require_canary_actor(workspace, actor)
            self.repository.assert_fresh(token, actor)
            cur.execute("UPDATE public.pr_telegram_identities SET revoked_at=now(),identity='{}'::jsonb WHERE workspace_id=%s AND member_id=%s AND id=%s RETURNING id", (workspace, actor, identity_id))
            if not cur.fetchone():
                raise AlphaError("Identity unavailable.", 404)
            audit(cur, workspace, actor, "telegram.identity.disconnected", identity_id, {})
        return {"disconnected": True, "destinationPermissions": "unchanged; manage destinations separately"}

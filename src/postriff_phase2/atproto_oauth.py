"""Bluesky (AT Protocol) OAuth as a confidential web client (atproto.com/specs/oauth, read 2026-09-25).

client_id is the HTTPS URL of Rafii's client metadata document. Every authorization uses PAR, PKCE (S256), a
private_key_jwt client assertion signed with POSTRIFF_BLUESKY_CLIENT_JWK, and DPoP (ES256) with server nonces.
The callback's `iss` must equal the authorization server found for the handle, and the token `sub` must equal the
handle's DID. Tokens are DPoP-bound, so each connection keeps its own DPoP key inside its encrypted grant.
"""
import base64
import hashlib
import json
import re
import secrets
import socket
import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from postriff_alpha.domain import AlphaError
from .net_guard import public_host, public_https_url
from .provider_base import OAuthProvider, _credential_shape, default_transport

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
_HANDLE = re.compile(r"^(?=.{3,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")
_DID = re.compile(r"^did:(plc:[a-z2-7]{24}|web:[a-z0-9.-]{3,253})$")


# --- JOSE (ES256) ------------------------------------------------------------------------------------------------
def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64u_decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _coordinate(value):
    return value.to_bytes(32, "big")


def generate_jwk(kid=None):
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.private_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "x": b64u(_coordinate(numbers.public_numbers.x)),
           "y": b64u(_coordinate(numbers.public_numbers.y)), "d": b64u(_coordinate(numbers.private_value))}
    if kid:
        jwk["kid"] = kid
    return jwk


def private_key(jwk):
    """The P-256 key a JWK holds, after checking its public half matches."""
    from cryptography.hazmat.primitives.asymmetric import ec
    if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or not all(isinstance(jwk.get(k), str) for k in ("x", "y", "d")):
        raise ValueError("Not an ES256 private JWK")
    key = ec.derive_private_key(int.from_bytes(b64u_decode(jwk["d"]), "big"), ec.SECP256R1())
    public = key.public_key().public_numbers()
    if b64u(_coordinate(public.x)) != jwk["x"] or b64u(_coordinate(public.y)) != jwk["y"]:
        raise ValueError("JWK public coordinates do not match its private key")
    return key


def public_jwk(jwk):
    public = {k: jwk[k] for k in ("kty", "crv", "x", "y")}
    if jwk.get("kid"):
        public.update(kid=jwk["kid"], use="sig", alg="ES256")
    return public


def sign(jwk, header, payload):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    encode = lambda value: b64u(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())
    signing_input = encode(header) + "." + encode(payload)
    r, s = decode_dss_signature(private_key(jwk).sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return signing_input + "." + b64u(_coordinate(r) + _coordinate(s))


def dpop_proof(jwk, method, url, now, nonce=None, access_token=None):
    parts = urlsplit(url)
    payload = {"jti": secrets.token_urlsafe(16), "htm": method, "htu": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), "iat": int(now)}
    if nonce:
        payload["nonce"] = nonce
    if access_token:
        payload["ath"] = b64u(hashlib.sha256(access_token.encode()).digest())
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": {k: jwk[k] for k in ("kty", "crv", "x", "y")}}
    return sign(jwk, header, payload)


def client_assertion(jwk, client_id, audience, now):
    header = {"alg": "ES256", "kid": jwk["kid"]}
    return sign(jwk, header, {"iss": client_id, "sub": client_id, "aud": audience, "jti": secrets.token_urlsafe(16), "iat": int(now), "exp": int(now) + 60})


def parse_client_jwk(raw):
    """POSTRIFF_BLUESKY_CLIENT_JWK: one ES256 private JWK with a kid, as JSON (spacing allowed). Never echoed in errors."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 8192 or not _credential_shape("".join(raw.split())):
        return None
    try:
        jwk = json.loads(raw)
        private_key(jwk)
    except (ValueError, TypeError):
        return None
    if not isinstance(jwk.get("kid"), str) or not 1 <= len(jwk["kid"]) <= 64:
        return None
    return jwk


# --- adapter ---------------------------------------------------------------------------------------------------
class BlueskyProvider(OAuthProvider):
    id, platform, capability_version = "bluesky", "Bluesky", 1
    SCOPES = {"identity": ["atproto", "transition:generic"], "publish": ["atproto", "transition:generic"], "schedule": ["atproto", "transition:generic"]}
    EXPLAIN = {"identity": "Connect your Bluesky account. Rafii confirms the account on your own server and posts nothing.",
               "publish": "Rafii will post to this Bluesky account only when you approve each exact post."}
    account_requirement = "Any Bluesky account, on bsky.social or your own server."
    publish_scope = "transition:generic"
    publish_required = frozenset({"atproto", "transition:generic"})
    start_input = {"name": "handle", "label": "Bluesky handle", "placeholder": "name.bsky.social"}
    requires_issuer = True
    refresh_margin = 300  # access tokens last at most 15 minutes
    METADATA_PATH = "/api/oauth/bluesky/client-metadata.json"
    JWKS_PATH = "/api/oauth/bluesky/jwks.json"
    RESOLVE_HANDLE = "https://bsky.social/xrpc/com.atproto.identity.resolveHandle"
    PLC_DIRECTORY = "https://plc.directory/"

    def __init__(self, client_jwk, public_base_url, transport=None, production_reviewed=False, clock=time.time, resolver=socket.getaddrinfo):
        if not isinstance(client_jwk, dict) or not client_jwk.get("kid"):
            raise AlphaError("Bluesky client key is required.", 503)
        self.client_jwk = client_jwk
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.client_id = self.public_base_url + self.METADATA_PATH
        self.client_secret = None
        self.transport = transport or default_transport()
        self.production_reviewed = bool(production_reviewed)
        self.execution_enabled = True
        self.clock, self.resolver = clock, resolver

    @classmethod
    def mount(cls, values, transport=None):
        raw, base = values.get("POSTRIFF_BLUESKY_CLIENT_JWK"), values.get("POSTRIFF_PUBLIC_BASE_URL")
        presence = {"clientId": bool(base), "clientSecret": raw is not None}
        missing = [name for name, present in (("POSTRIFF_PUBLIC_BASE_URL", bool(base)), ("POSTRIFF_BLUESKY_CLIENT_JWK", raw is not None)) if not present]
        jwk = parse_client_jwk(raw) if raw is not None else None
        origin = urlsplit(base or "")
        base_ok = origin.scheme == "https" and bool(origin.hostname) and not origin.path.strip("/") and not origin.query
        state = "not_configured" if raw is None else "partial_configuration" if missing else "configured" if jwk and base_ok else "invalid_configuration"
        diagnostic = {"configurationState": state, "credentialPresence": presence, "missingVariables": missing}
        if state != "configured":
            return None, diagnostic
        return cls(jwk, base, transport=transport), diagnostic

    # --- public documents -------------------------------------------------------------------------------------
    def client_metadata(self):
        base = self.public_base_url
        return {"client_id": self.client_id, "application_type": "web", "client_name": "Rafii", "client_uri": base,
                "dpop_bound_access_tokens": True, "grant_types": ["authorization_code", "refresh_token"],
                "redirect_uris": [base + "/api/oauth/bluesky/callback"], "response_types": ["code"],
                "scope": " ".join(self.SCOPES["publish"]), "token_endpoint_auth_method": "private_key_jwt",
                "token_endpoint_auth_signing_alg": "ES256", "jwks_uri": base + self.JWKS_PATH}

    def jwks(self):
        return {"keys": [public_jwk(self.client_jwk)]}

    # --- resolution ---------------------------------------------------------------------------------------------
    def _get_json(self, url):
        response = self.transport("GET", public_https_url(url, self.resolver))
        body = response.get("body")
        if response.get("status") != 200 or not isinstance(body, dict):
            raise AlphaError("Bluesky could not confirm this account right now.", 502)
        return body

    @staticmethod
    def normalize_handle(value):
        handle = (value or "").strip().lower().lstrip("@") if isinstance(value, str) else ""
        if not _HANDLE.match(handle) or handle.endswith((".local", ".localhost", ".invalid", ".test", ".example")):
            raise AlphaError("Enter your Bluesky handle, for example name.bsky.social.", 400)
        return handle

    def resolve_did(self, handle):
        did = None
        try:
            response = self.transport("GET", public_https_url(f"https://{public_host(handle)}/.well-known/atproto-did", self.resolver))
            text = response.get("body", {}).get("raw") if isinstance(response.get("body"), dict) else None
            if response.get("status") == 200 and isinstance(text, str) and _DID.match(text.strip()):
                did = text.strip()
        except AlphaError:
            did = None
        if did is None:
            body = self._get_json(self.RESOLVE_HANDLE + "?" + urlencode({"handle": handle}))
            did = body.get("did") if isinstance(body.get("did"), str) and _DID.match(body.get("did")) else None
        if did is None:
            raise AlphaError("That Bluesky handle could not be found.", 404)
        return did

    def did_document(self, did):
        if did.startswith("did:plc:"):
            document = self._get_json(self.PLC_DIRECTORY + quote(did, safe=":"))
        else:
            document = self._get_json(f"https://{public_host(did[len('did:web:'):])}/.well-known/did.json")
        if document.get("id") != did:
            raise AlphaError("Bluesky returned a mismatched account record.", 502)
        return document

    @staticmethod
    def pds_endpoint(document):
        for service in document.get("service") or []:
            if isinstance(service, dict) and str(service.get("id", "")).endswith("#atproto_pds") and service.get("type") == "AtprotoPersonalDataServer":
                endpoint = service.get("serviceEndpoint")
                if isinstance(endpoint, str) and endpoint.startswith("https://"):
                    return endpoint.rstrip("/")
        raise AlphaError("This Bluesky account has no server Rafii can reach.", 502)

    def authorization_server(self, pds):
        resource = self._get_json(pds + "/.well-known/oauth-protected-resource")
        servers = resource.get("authorization_servers")
        if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
            raise AlphaError("This Bluesky server does not offer sign-in for apps.", 502)
        issuer = servers[0].rstrip("/")
        metadata = self._get_json(issuer + "/.well-known/oauth-authorization-server")
        if str(metadata.get("issuer", "")).rstrip("/") != issuer:
            raise AlphaError("This Bluesky server's sign-in details don't match.", 502)
        for key in ("pushed_authorization_request_endpoint", "authorization_endpoint", "token_endpoint"):
            public_https_url(metadata.get(key), self.resolver)
        if metadata.get("revocation_endpoint") is not None:
            public_https_url(metadata.get("revocation_endpoint"), self.resolver)
        if "atproto" not in (metadata.get("scopes_supported") or ["atproto"]) or "ES256" not in (metadata.get("dpop_signing_alg_values_supported") or ["ES256"]):
            raise AlphaError("This Bluesky server doesn't support Rafii's sign-in.", 502)
        return issuer, metadata

    # --- DPoP requests --------------------------------------------------------------------------------------------
    def _dpop_post(self, url, form, jwk, nonce=None, audience=None):
        """POST with DPoP; one retry when the server asks for a nonce. Returns (response, latest nonce).

        Stored endpoints are re-checked here, at request time: a name that resolved publicly at connect time
        may not any more."""
        public_https_url(url, self.resolver)
        for _ in range(2):
            fields = dict(form)
            if audience:
                fields.update(client_id=self.client_id, client_assertion_type=ASSERTION_TYPE,
                              client_assertion=client_assertion(self.client_jwk, self.client_id, audience, self.clock()))
            response = self.transport("POST", url, headers={"DPoP": dpop_proof(jwk, "POST", url, self.clock(), nonce)}, form=fields)
            offered = response.get("headers", {}).get("dpop-nonce")
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            if response.get("status") in (400, 401) and body.get("error") == "use_dpop_nonce" and offered and offered != nonce:
                nonce = offered
                continue
            return response, offered or nonce
        return response, nonce

    def _dpop_get(self, url, session):
        public_https_url(url, self.resolver)
        nonce = session.get("pdsNonce")
        for _ in range(2):
            response = self.transport("GET", url, headers={"Authorization": "DPoP " + session["at"],
                                                           "DPoP": dpop_proof(session["jwk"], "GET", url, self.clock(), nonce, session["at"])})
            offered = response.get("headers", {}).get("dpop-nonce")
            if response.get("status") == 401 and offered and offered != nonce:
                nonce = offered
                continue
            return response
        return response

    # --- flow -----------------------------------------------------------------------------------------------------
    def begin(self, redirect, state, verifier, challenge, scopes, handle):
        handle = self.normalize_handle(handle)
        did = self.resolve_did(handle)
        document = self.did_document(did)
        if f"at://{handle}" not in (document.get("alsoKnownAs") or []):
            raise AlphaError("That handle doesn't point back to its Bluesky account.", 409)
        pds = self.pds_endpoint(document)
        public_https_url(pds, self.resolver)
        issuer, metadata = self.authorization_server(pds)
        dpop_jwk = generate_jwk()
        response, nonce = self._dpop_post(metadata["pushed_authorization_request_endpoint"], {
            "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
            "redirect_uri": redirect, "scope": " ".join(scopes), "login_hint": handle}, dpop_jwk, audience=issuer)
        request_uri = response.get("body", {}).get("request_uri") if isinstance(response.get("body"), dict) else None
        if response.get("status") not in (200, 201) or not isinstance(request_uri, str):
            raise AlphaError("Bluesky did not start the sign-in. Try again.", 502)
        authorize = metadata["authorization_endpoint"] + "?" + urlencode({"client_id": self.client_id, "request_uri": request_uri})
        context = {"issuer": issuer, "tokenEndpoint": metadata["token_endpoint"], "revocationEndpoint": metadata.get("revocation_endpoint"),
                   "did": did, "handle": handle, "pds": pds, "dpopJwk": dpop_jwk, "dpopNonce": nonce}
        return {"authorizeUrl": authorize, "context": context}

    def _session(self, body, context, nonce):
        access, refresh = body.get("access_token"), body.get("refresh_token")
        if not isinstance(access, str) or not access or str(body.get("token_type", "")).lower() != "dpop":
            raise AlphaError("Bluesky did not complete this authorization step.", 502)
        if body.get("sub") != context["did"]:
            raise AlphaError("The Bluesky account that signed in isn't the one you entered.", 409)
        scopes = body.get("scope").split() if isinstance(body.get("scope"), str) else []
        common = {"v": 1, "did": context["did"], "pds": context["pds"], "iss": context["issuer"], "tokenEndpoint": context["tokenEndpoint"],
                  "revocationEndpoint": context.get("revocationEndpoint"), "jwk": context["dpopJwk"]}
        # The refresh token rides along (encrypted like the rest) so disconnecting can revoke the whole grant.
        session = {**common, "at": access, "rt": refresh if isinstance(refresh, str) else None, "scope": scopes, "nonce": nonce}
        refresh_blob = json.dumps({**common, "rt": refresh, "nonce": nonce}) if isinstance(refresh, str) and refresh else None
        return {"accessToken": json.dumps(session), "refreshToken": refresh_blob, "expiresIn": body.get("expires_in") or 900, "scopes": scopes, "userId": context["did"]}

    def exchange(self, code, verifier, redirect, iss=None):
        try:
            context = json.loads(verifier)
        except (TypeError, ValueError) as error:
            raise AlphaError("Connection request unavailable.", 404) from error
        if not isinstance(iss, str) or iss.rstrip("/") != context["issuer"]:
            raise AlphaError("The Bluesky sign-in came back from the wrong server.", 400)
        response, nonce = self._dpop_post(context["tokenEndpoint"], {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                                                                     "code_verifier": context["verifier"]}, context["dpopJwk"], context.get("dpopNonce"), audience=context["issuer"])
        if response.get("status") != 200 or not isinstance(response.get("body"), dict):
            raise AlphaError("Bluesky did not complete this authorization step.", 502)
        return self._session(response["body"], context, nonce)

    def refresh(self, refresh_token):
        stored = json.loads(refresh_token)
        context = {"issuer": stored["iss"], "tokenEndpoint": stored["tokenEndpoint"], "revocationEndpoint": stored.get("revocationEndpoint"),
                   "did": stored["did"], "pds": stored["pds"], "dpopJwk": stored["jwk"]}
        response, nonce = self._dpop_post(stored["tokenEndpoint"], {"grant_type": "refresh_token", "refresh_token": stored["rt"]}, stored["jwk"], stored.get("nonce"), audience=stored["iss"])
        if response.get("status") != 200 or not isinstance(response.get("body"), dict):
            raise AlphaError("Bluesky access expired; reconnect the account.", 409, code="reauthorization_required")
        return self._session(response["body"], context, nonce)

    def identity(self, access_token):
        session = json.loads(access_token)
        response = self._dpop_get(session["pds"] + "/xrpc/com.atproto.server.getSession", session)
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        if response.get("status") != 200 or body.get("did") != session["did"]:
            raise AlphaError("Bluesky could not confirm this account right now.", 502)
        handle = body.get("handle") if isinstance(body.get("handle"), str) else session["did"]
        return {"providerAccountId": session["did"], "handle": "@" + handle, "accountType": "profile"}

    def inspect_scopes(self, access_token, expected_account_id=None):
        """Scopes the token response granted, returned only after the token works live for the same DID."""
        session = json.loads(access_token)
        if expected_account_id and session.get("did") != expected_account_id:
            return None
        try:
            self.identity(access_token)
        except AlphaError:
            return None
        return sorted(set(session.get("scope") or []))

    def revoke(self, token):
        """Revoke the grant at its authorization server (RFC 7009), refresh token first so the whole grant ends."""
        session = json.loads(token)
        endpoint = session.get("revocationEndpoint")
        if not isinstance(endpoint, str):
            return False
        value, hint = (session["rt"], "refresh_token") if session.get("rt") else (session["at"], "access_token")
        response, _ = self._dpop_post(endpoint, {"token": value, "token_type_hint": hint}, session["jwk"], session.get("nonce"), audience=session["iss"])
        return response.get("status") == 200

    # --- publishing helpers (hosted_social) -------------------------------------------------------------------------
    def xrpc_post(self, session, method, *, body=None, data=None, content_type=None):
        url = public_https_url(session["pds"] + "/xrpc/" + method, self.resolver)
        nonce = session.get("pdsNonce")
        for _ in range(2):
            headers = {"Authorization": "DPoP " + session["at"], "DPoP": dpop_proof(session["jwk"], "POST", url, self.clock(), nonce, session["at"])}
            if data is not None:
                response = self.transport("POST", url, headers={**headers, "Content-Type": content_type}, data=data)
            else:
                response = self.transport("POST", url, headers=headers, body=body)
            offered = response.get("headers", {}).get("dpop-nonce")
            if response.get("status") == 401 and offered and offered != nonce:
                nonce = offered
                continue
            session["pdsNonce"] = offered or nonce
            return response
        return response

    def xrpc_get(self, session, method, params):
        return self._dpop_get(session["pds"] + "/xrpc/" + method + "?" + urlencode(params), session)


_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def tid(micros, clock_id=0):
    """AT Protocol record key: 13 base32-sortable characters of (microseconds << 10 | clock id)."""
    value, out = (int(micros) << 10) | (clock_id & 0x3FF), []
    for _ in range(13):
        out.append(_TID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))

"""Server-only Supabase Auth lifecycle operations and verified JWT session IDs."""
import base64
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from postriff_alpha.domain import AlphaError


SESSION = re.compile(r"[A-Za-z0-9_-]{16,160}")
USER_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _verified_payload(access_token, principal):
    """Decode only after Supabase getUser verified the token and exact subject."""
    try:
        encoded = access_token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError, TypeError, UnicodeDecodeError) as error:
        raise AlphaError("Verified session required.", 401) from error
    if not isinstance(payload, dict) or payload.get("sub") != principal:
        raise AlphaError("Verified session required.", 401)
    return payload


def verified_session_id(access_token, principal):
    session_id = _verified_payload(access_token, principal).get("session_id")
    if not isinstance(session_id, str) or not SESSION.fullmatch(session_id):
        raise AlphaError("Verified session required.", 401)
    return session_id


def verified_auth_time(access_token, principal):
    """Seconds since epoch when this session was last verified by sign-in (JWT iat).

    Used only for step-up freshness; a missing or malformed claim counts as stale.
    """
    value = _verified_payload(access_token, principal).get("iat")
    if type(value) not in (int, float) or value <= 0:
        return 0
    return float(value)


def verified_aal(access_token, principal):
    """Authenticator assurance level Supabase stamped on this session: "aal2" only after a second
    factor was verified. Anything missing or unexpected counts as "aal1"."""
    value = _verified_payload(access_token, principal).get("aal")
    return "aal2" if value == "aal2" else "aal1"


class SupabaseIdentityAdmin:
    def __init__(self, project_url, publishable_key, service_key, send=None, fetch=None):
        self.project_url = project_url.rstrip("/")
        self.publishable_key = publishable_key
        self.service_key = service_key
        self.send = send or self._send      # (method, url, headers, body) -> status
        self.fetch = fetch or self._fetch   # (method, url, headers) -> (status, parsed JSON body or {})

    @staticmethod
    def _send(method, url, headers, body):
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
                return response.status
        except HTTPError as error:
            error.read(65536)
            return error.code
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("The identity service is temporarily unavailable.", 503) from error

    @staticmethod
    def _fetch(method, url, headers):
        request = Request(url, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
                status, raw = response.status, response.read(262144)
        except HTTPError as error:
            error.read(65536)
            return error.code, {}
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("The identity service is temporarily unavailable.", 503) from error
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {}
        return status, parsed if isinstance(parsed, dict) else {}

    def _admin_headers(self):
        return {"apikey": self.service_key, "Authorization": "Bearer " + self.service_key, "Accept": "application/json"}

    def email_for(self, principal):
        """Real Supabase Admin lookup (GET /auth/v1/admin/users/{id}); the address is used for one
        send and never stored (decisions D16). Returns None when the user is gone or has no email;
        raises AlphaError when the identity service fails so callers can treat it as a send failure.
        """
        if not isinstance(principal, str) or not USER_ID.fullmatch(principal):
            raise AlphaError("Verified user required.", 400)
        status, body = self.fetch("GET", self.project_url + "/auth/v1/admin/users/" + quote(principal), self._admin_headers())
        if status == 404:
            return None
        if status != 200:
            raise AlphaError("The identity service could not resolve this account.", 502)
        email = body.get("email")
        if not isinstance(email, str) or "@" not in email or not 3 <= len(email) <= 254:
            return None
        return email.strip().lower()

    def verified_factors(self, principal):
        """Second factors the user has finished enrolling (Admin GET user → `factors`, status
        'verified'). Content-free: ids, type and friendly name only; never secrets."""
        if not isinstance(principal, str) or not USER_ID.fullmatch(principal):
            raise AlphaError("Verified user required.", 400)
        status, body = self.fetch("GET", self.project_url + "/auth/v1/admin/users/" + quote(principal), self._admin_headers())
        if status == 404:
            return []
        if status != 200:
            raise AlphaError("The identity service could not resolve this account.", 502)
        factors = body.get("factors")
        if not isinstance(factors, list):
            return []
        return [
            {"id": str(item.get("id", "")), "type": str(item.get("factor_type", "")), "name": str(item.get("friendly_name") or "")[:80]}
            for item in factors
            if isinstance(item, dict) and item.get("status") == "verified"
        ]

    def logout(self, access_token):
        status = self.send(
            "POST",
            self.project_url + "/auth/v1/logout?scope=local",
            {"apikey": self.publishable_key, "Authorization": "Bearer " + access_token, "Content-Type": "application/json"},
            b"{}",
        )
        if status not in (200, 204, 401):
            raise AlphaError("The hosted session could not be closed remotely.", 502)
        return status != 401

    def logout_others(self, access_token):
        """Revoke every refresh token of this user except the one behind `access_token`."""
        status = self.send(
            "POST",
            self.project_url + "/auth/v1/logout?scope=others",
            {"apikey": self.publishable_key, "Authorization": "Bearer " + access_token, "Content-Type": "application/json"},
            b"{}",
        )
        if status not in (200, 204, 401):
            raise AlphaError("Other sessions could not be signed out remotely.", 502)
        return status != 401

    def delete_user(self, principal):
        status = self.send(
            "DELETE",
            self.project_url + "/auth/v1/admin/users/" + quote(principal),
            {"apikey": self.service_key, "Authorization": "Bearer " + self.service_key, "Content-Type": "application/json"},
            None,
        )
        if status not in (200, 204, 404):
            raise AlphaError("Workspace data was removed, but identity deletion needs reconciliation.", 502)
        return status != 404

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


def verified_session_id(access_token, principal):
    """Decode only after Supabase getUser verified the token and exact subject."""
    try:
        encoded = access_token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError, TypeError, UnicodeDecodeError) as error:
        raise AlphaError("Verified session required.", 401) from error
    session_id = payload.get("session_id")
    if payload.get("sub") != principal or not isinstance(session_id, str) or not SESSION.fullmatch(session_id):
        raise AlphaError("Verified session required.", 401)
    return session_id


class SupabaseIdentityAdmin:
    def __init__(self, project_url, publishable_key, service_key, send=None):
        self.project_url = project_url.rstrip("/")
        self.publishable_key = publishable_key
        self.service_key = service_key
        self.send = send or self._send

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

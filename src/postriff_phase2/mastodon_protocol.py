"""Mastodon Connect origin/discovery contracts; never supplies token authority."""
import re
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError
from .net_guard import public_host


def instance_host(value):
    raw = value.strip() if isinstance(value, str) else ""
    if raw.startswith("https://"):
        try:
            parsed = urlsplit(raw)
            allowed = (not parsed.username and not parsed.password and parsed.port in (None, 443)
                       and parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
        except ValueError:
            allowed = False
        if not allowed:
            raise AlphaError("Enter an HTTPS server domain or @name@server account.", 400)
        raw = parsed.hostname or ""
    elif "@" in raw:
        if not re.fullmatch(r"@?[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+", raw):
            raise AlphaError("Enter an account such as @name@mastodon.social.", 400)
        raw = raw.rsplit("@", 1)[1]
    elif any(c in raw for c in "/?#:\\"):
        raise AlphaError("Enter a server domain such as mastodon.social.", 400)
    return public_host(raw)


def version_at_least(version, minimum):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(version))
    return bool(match and tuple(map(int, match.groups())) >= minimum)



def discover(transport, host):
    origin = "https://" + host
    response = transport("GET", origin + "/api/v2/instance")
    if response.get("status") == 404:
        response = transport("GET", origin + "/api/v1/instance")
    body = response.get("body")
    if response.get("status") != 200 or not isinstance(body, dict) or not isinstance(body.get("version"), str):
        raise AlphaError("This server did not expose a compatible Mastodon instance API.", 409)
    version = body["version"][:100]
    capabilities = {"instance": host, "version": version,
                    "pkce": version_at_least(version, (4, 3, 0)), "scopesSupported": None}
    if capabilities["pkce"]:
        metadata = transport("GET", origin + "/.well-known/oauth-authorization-server")
        document = metadata.get("body")
        if metadata.get("status") == 200 and isinstance(document, dict):
            if document.get("issuer") not in (origin, origin + "/"):
                raise AlphaError("This server's OAuth identity does not match its HTTPS origin.", 409)
            for name, path in (("authorization_endpoint", "/oauth/authorize"), ("token_endpoint", "/oauth/token")):
                if document.get(name) != origin + path:
                    raise AlphaError("This server's OAuth identity does not match its HTTPS origin.", 409)
            methods = document.get("code_challenge_methods_supported", [])
            if not isinstance(methods, list) or "S256" not in methods:
                raise AlphaError("This server does not support secure S256 authorization.", 409)
            scopes = document.get("scopes_supported")
            if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
                raise AlphaError("This server returned invalid OAuth permissions.", 502)
            capabilities["scopesSupported"] = sorted(set(scopes))
        elif metadata.get("status") != 404:
            raise AlphaError("This server's OAuth discovery is unavailable.", 503)
    return capabilities


def has_scopes(granted, required):
    granted = set(granted or [])
    return all(s in granted or s.split(":", 1)[0] in granted for s in required)

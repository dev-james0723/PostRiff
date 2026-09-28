"""Outbound requests to hosts a customer names (a Bluesky PDS, a Mastodon server): public HTTPS only.

The resolution check narrows server-side request forgery to public addresses. It does not pin the address the
transport later connects to, so a DNS answer that changes between the two lookups is not excluded.
"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".invalid", ".test", ".example", ".onion")


def public_host(value, *, message="Enter a server name such as mastodon.social."):
    """A bare public DNS name, lower-cased. Accepts a pasted https:// URL or an @user@host address."""
    host = (value or "").strip().lower() if isinstance(value, str) else ""
    if host.startswith("https://"):
        host = host[len("https://"):]
    host = host.split("/", 1)[0].rsplit("@", 1)[-1].rstrip(".")
    if not host or len(host) > 253 or "." not in host or ":" in host:
        raise AlphaError(message, 400)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AlphaError(message, 400)
    labels = host.split(".")
    if not all(_LABEL.match(label) for label in labels) or labels[-1].isdigit():
        raise AlphaError(message, 400)
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise AlphaError(message, 400)
    return host


def assert_public(host, resolver=socket.getaddrinfo):
    try:
        answers = resolver(host, 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise AlphaError("That server can't be reached.", 400) from error
    if not answers:
        raise AlphaError("That server can't be reached.", 400)
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (ValueError, IndexError, TypeError) as error:
            raise AlphaError("That server address isn't allowed.", 400) from error
        if not address.is_global or address.is_multicast:
            raise AlphaError("That server address isn't allowed.", 400)
    return host


def public_https_url(url, resolver=socket.getaddrinfo):
    """An https URL on a public host, default port, no credentials; returned unchanged."""
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        port = parts.port if parts else None
    except ValueError:
        parts, port = None, None
    if not parts or parts.scheme != "https" or not parts.hostname or parts.username or parts.password or port not in (None, 443):
        raise AlphaError("The provider returned an address Rafii can't use.", 502)
    assert_public(public_host(parts.hostname, message="The provider returned an address Rafii can't use."), resolver)
    return url

"""Agent routes accept interactive sessions only (like the site agent): an API token has no agent scope."""
from postriff_alpha.domain import AlphaError


def require_session_token(token) -> None:
    from ..api_tokens import is_api_token
    if is_api_token(token):
        raise AlphaError("API tokens can't use Rafii's agent. Sign in to use it.", 403)

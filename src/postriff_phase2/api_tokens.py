"""Workspace-scoped read/draft credentials; no publish, approval, reply, account or billing authority.

Creation is a fresh interactive-session action. Only its response carries the secret. Every use
checks expiry, revocation, account deletion and the creator's current membership. The repository
rechecks and locks that grant inside each workspace transaction, closing the request/commit gap.
"""
import hashlib
import re
import secrets
from postriff_alpha.domain import AlphaError
from .permissions import Membership, require


def is_api_token(raw):
    return isinstance(raw, str) and raw.startswith("prt_")


def route_scope(method, parts):
    """Explicit allowlist, never blanket GET or action access. Unknown future routes stay closed."""
    if len(parts) < 3 or parts[:2] != ["api", "workspaces"]:
        return None
    tail = parts[3:]
    if method == "GET":
        if not tail or tail in (["channels"], ["memory"]):
            return "read"
        if tail == ["ideas", "conversations"]:
            return "read"
        if len(tail) == 4 and tail[:2] == ["ideas", "conversations"] and tail[3] == "messages":
            return "read"
        if len(tail) == 4 and tail[:2] == ["ideas", "runs"] and tail[3] == "events":
            return "read"
    if method == "POST":
        if tail in (["ideas", "quick-start"], ["ideas", "conversations"]):
            return "draft"
        if len(tail) == 4 and tail[:2] == ["ideas", "conversations"] and tail[3] in ("turns", "attachments"):
            return "draft"
        if len(tail) == 4 and tail[:2] == ["ideas", "runs"] and tail[3] in ("apply", "cancel"):
            return "draft"
    return None


COLUMNS = "id::text,name,prefix,scopes,extract(epoch from created_at),extract(epoch from expires_at),extract(epoch from last_used_at),last_used_client,extract(epoch from revoked_at),created_by::text"


def view(row):
    return dict(zip(("tokenId", "name", "prefix", "scopes", "createdAt", "expiresAt", "lastUsedAt", "lastUsedClient", "revokedAt", "createdBy"),
                    [row[0], row[1], row[2], row[3], float(row[4]), float(row[5]), float(row[6]) if row[6] is not None else None, row[7], float(row[8]) if row[8] is not None else None, row[9]]))


class ApiTokens:
    def __init__(self, repository):
        self.repository = repository
        self.clock = repository.clock

    @staticmethod
    def session_only(token):
        if is_api_token(token):
            raise AlphaError("Use an interactive session to manage API tokens.", 403, code="token_scope_denied")

    def create(self, workspace_id, token, payload):
        from .hosted import _membership, audit, throttle
        self.session_only(token)
        name, scopes, days = payload.get("name"), payload.get("scopes"), payload.get("expiresDays")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise AlphaError("Name the token using 1 to 40 characters.")
        if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes) or not set(scopes) <= {"read", "draft"} or "read" not in scopes:
            raise AlphaError("Token scopes are read, or read and draft.")
        if type(days) is not int or days not in (30, 90, 365):
            raise AlphaError("Choose an expiry of 30, 90 or 365 days.")
        raw = "prt_" + secrets.token_urlsafe(32)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "manage_connections")
            self.repository.assert_fresh(token, principal)
            throttle(cur, "api_token.create:" + principal, 5, 60)
            cur.execute(f"INSERT INTO public.pr_api_tokens(workspace_id,created_by,name,prefix,token_hash,scopes,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) RETURNING {COLUMNS}",
                        (workspace_id, principal, name.strip(), raw[:12], hashlib.sha256(raw.encode()).hexdigest(), sorted(set(scopes)), now, now + days * 86400))
            result = view(cur.fetchone())
            audit(cur, workspace_id, principal, "api_token.created", result["tokenId"], {"scopes": result["scopes"], "expiresDays": days})
        return {"item": result, "secret": raw}

    def list(self, workspace_id, token):
        from .hosted import _membership
        self.session_only(token)
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(_membership(row), "manage_connections")
            cur.execute(f"SELECT {COLUMNS} FROM public.pr_api_tokens WHERE workspace_id=%s AND (revoked_at IS NULL OR revoked_at > to_timestamp(%s)-interval '30 days') ORDER BY created_at DESC", (workspace_id, self.clock()))
            return {"tokens": [view(row) for row in cur.fetchall()]}

    def revoke(self, workspace_id, token, token_id):
        from .hosted import _membership, audit
        self.session_only(token)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "manage_connections")
            cur.execute("UPDATE public.pr_api_tokens SET revoked_at=coalesce(revoked_at,to_timestamp(%s)) WHERE workspace_id=%s AND id::text=%s RETURNING id::text", (self.clock(), workspace_id, token_id))
            result = cur.fetchone()
            if not result:
                raise AlphaError("Token unavailable.", 404)
            audit(cur, workspace_id, principal, "api_token.revoked", result[0])
        return {"tokenId": result[0], "revoked": True}

    def validate(self, cur, raw, workspace_id=None):
        if not isinstance(raw, str) or not re.fullmatch(r"prt_[A-Za-z0-9_-]{43}", raw):
            raise AlphaError("API token expired or revoked.", 401, code="api_token_invalid")
        cur.execute("""SELECT t.id::text,t.workspace_id::text,t.created_by::text,t.scopes,m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections
          FROM public.pr_api_tokens t JOIN public.pr_memberships m ON m.workspace_id=t.workspace_id AND m.user_id=t.created_by
          JOIN public.pr_profiles p ON p.user_id=t.created_by
          WHERE t.token_hash=%s AND t.revoked_at IS NULL AND t.expires_at>to_timestamp(%s) AND m.status='active' AND p.deleted_at IS NULL
          AND NOT EXISTS(SELECT 1 FROM public.pr_account_tombstones d WHERE d.user_id=t.created_by) FOR UPDATE OF t FOR SHARE OF m""", (hashlib.sha256(raw.encode()).hexdigest(), self.clock()))
        row = cur.fetchone()
        if not row:
            raise AlphaError("API token expired or revoked.", 401, code="api_token_invalid")
        if workspace_id is not None and str(workspace_id) != row[1]:
            raise AlphaError("Workspace unavailable.", 403, code="token_scope_denied")
        return {"tokenId": row[0], "workspaceId": row[1], "createdBy": row[2], "scopes": row[3], "membership": Membership.from_row(*row[4:9])}

    def resolve(self, raw, workspace_id=None):
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                return self.validate(cur, raw, workspace_id)

    def authorize(self, raw, method, parts, client=None):
        scope = route_scope(method, parts)
        if scope is None:
            raise AlphaError("This route is unavailable to API tokens.", 403, code="token_scope_denied")
        from .hosted import throttle, audit
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                # Match repository/revoke lock order: workspace, then credential.
                cur.execute("SELECT id FROM public.pr_workspaces WHERE id::text=%s FOR UPDATE", (parts[2],))
                grant = self.validate(cur, raw, parts[2])
                if scope not in grant["scopes"]:
                    raise AlphaError("This token does not have the required scope.", 403, code="token_scope_denied")
                require(grant["membership"], "edit" if scope == "draft" else "read")
                if method == "POST":
                    throttle(cur, "api_token.draft:" + grant["tokenId"], 20, 60)
                    audit(cur, parts[2], grant["createdBy"], "api_token.draft_requested", grant["tokenId"], {"route": parts[-1]})
                cur.execute("UPDATE public.pr_api_tokens SET last_used_at=to_timestamp(%s),last_used_client=%s WHERE id=%s AND (last_used_at IS NULL OR last_used_at<to_timestamp(%s)-interval '60 seconds')", (self.clock(), (client or "API client")[:120], grant["tokenId"], self.clock()))
                return grant

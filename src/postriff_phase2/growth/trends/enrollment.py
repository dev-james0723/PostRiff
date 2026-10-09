"""Owner self-serve enrollment for Trends (GET | POST | DELETE .../coworker/trends/enrollment).

feature_enrollment('trend_radar') owns the enrollment row, the kill switch, the
cohort cap and the denylist. This module adds the HTTP-facing rules for Trends:

- interactive session only (API tokens refused), origin guard in hosted_app,
  owner role for changes, any member may read the caller's own status;
- responses carry only this workspace's own status and eligibility, never other
  workspaces' enrollment or cohort counts;
- enrolling is availability, not egress: no source policy, ingestion job, model
  budget or consent is created. The only data grant is a pr_trend_entitlements row
  for the configured shared corpus scope (RAFII_TREND_SHARED_CORPUS_SCOPE), and only
  when a ready, unexpired, reviewed shared policy explicitly allows
  share_across_workspaces (and retrieval / derived metrics) for that audience.
  Without one the workspace is admitted but readiness says source_rights_pending.
- leaving revokes that entitlement with our own SQL, which changes the scope
  signature, so previously signed list cursors stop working.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from postriff_alpha.domain import AlphaError
from ... import feature_enrollment
from ...permissions import require
from . import admission, contracts, readiness

FEATURE = "trend_radar"
SHARED_SCOPE_ENV = "RAFII_TREND_SHARED_CORPUS_SCOPE"
GRANT_OPERATIONS = ["retrieve", "derive_metrics"]
REQUIRED_RIGHTS = ("retrieve", "derive_metrics", "share_across_workspaces")
MAX_GRANT = timedelta(days=30)
ACCEPT_BODY = {"accept": True}


def _first(cur):
    found = cur.fetchone()
    if found is None:
        return None
    return next(iter(found.values())) if isinstance(found, dict) else found[0]


def _instant(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return contracts.instant(value)


def shared_scope(values=None):
    """The configured shared corpus scope, or None (absent or malformed means no grant)."""
    raw = str(feature_enrollment._source(values).get(SHARED_SCOPE_ENV, "")).strip()
    if not raw.startswith("shared:"):
        return None
    try:
        contracts.scope(raw)
    except (contracts.ContractError, ValueError, TypeError):
        return None
    return raw


def reviewed_shared_policy(cur, scope, now=None):
    """Earliest expiry of a reviewed policy explicitly allowing cross-workspace use, else None."""
    cur.execute("SELECT to_regclass('public.pr_trend_source_policies') IS NOT NULL AND to_regclass('public.pr_trend_entitlements') IS NOT NULL", ())
    if not _first(cur):
        return None
    cur.execute("""SELECT p.rights,p.expires_at,c.expires_at FROM public.pr_trend_source_policies p
        JOIN public.pr_trend_provider_contracts c ON (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
        JOIN public.pr_trend_scopes s ON s.scope_key=p.scope_key
        WHERE p.scope_key=%s AND s.enabled AND s.workspace_id IS NULL AND p.readiness='ready'
        AND p.revoked_at IS NULL AND c.revoked_at IS NULL
        AND p.valid_from<=clock_timestamp() AND p.expires_at>clock_timestamp()
        AND c.valid_from<=clock_timestamp() AND c.expires_at>clock_timestamp()
        AND p.operations @> %s::text[] AND c.operations @> %s::text[]
        ORDER BY p.expires_at DESC LIMIT 20""", (scope, list(REQUIRED_RIGHTS), list(REQUIRED_RIGHTS)))
    rows = cur.fetchall() or []
    now = now or datetime.now(timezone.utc)
    at = contracts.iso(now)
    best = None
    for found in rows:
        rights, policy_end, contract_end = (tuple(found.values()) if isinstance(found, dict) else tuple(found))
        if not isinstance(rights, dict) or not all(contracts.permits(rights, name, scope, at) for name in REQUIRED_RIGHTS):
            continue
        ends = [_instant(policy_end), _instant(contract_end)] + [contracts.instant(rights[name]["expires_at"]) for name in REQUIRED_RIGHTS]
        end = min(ends)
        if end > now and (best is None or end > best):
            best = end
    return best


class TrendEnrollment:
    def __init__(self, service):
        self.service = service
        self.hosted = service.hosted
        self.repository = service.repository
        self.values = service.values

    @contextmanager
    def transaction(self, workspace_id, token, requirement):
        from .service import error, ident
        workspace_id = ident(workspace_id)
        if not token:
            raise error("unauthenticated", 401)
        if str(token).startswith("prt_"):
            # Enrollment is a person's decision in an interactive session.
            raise error("forbidden", 403)
        entered = False
        try:
            with self.repository.transaction(token, workspace_id) as (cur, row, actor):
                entered = True
                member = self.hosted.ideas._member(row)
                require(member, requirement)
                yield workspace_id, cur, actor, member.role
        except AlphaError as exc:
            if not entered:
                # Foreign and missing workspaces stay indistinguishable.
                raise error("unauthenticated" if exc.status == 401 else "not_found", 401 if exc.status == 401 else 404) from None
            if exc.status == 403 and exc.code not in feature_enrollment_codes():
                raise error("forbidden", 403) from None
            raise

    def view(self, cur, workspace_id, role):
        own = feature_enrollment.status(cur, workspace_id, FEATURE)
        eligibility = feature_enrollment.eligibility(cur, workspace_id, FEATURE, self.values)
        source = admission.admission_source(cur, workspace_id, self.values)
        return {"feature": FEATURE, "status": own or "not_enrolled", "admission": source,
                "eligible": bool(eligibility.get("eligible")), "reason": eligibility.get("reason"),
                "can_manage": role == "owner", "shared_corpus": self._shared_state(cur, workspace_id)}

    def _shared_state(self, cur, workspace_id):
        scope = shared_scope(self.values)
        if scope is None:
            return "source_rights_pending"
        cur.execute("SELECT to_regclass('public.pr_trend_entitlements') IS NOT NULL", ())
        if not _first(cur):
            return "source_rights_pending"
        cur.execute("""SELECT EXISTS(SELECT 1 FROM public.pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s
            AND revoked_at IS NULL AND expires_at>clock_timestamp() AND 'retrieve'=ANY(operations))""", (workspace_id, scope))
        return "granted" if _first(cur) else "source_rights_pending"

    def get(self, workspace_id, token):
        with self.transaction(workspace_id, token, "read") as (wid, cur, _actor, role):
            return {"data": self.view(cur, wid, role)}

    def enroll(self, workspace_id, token, payload):
        from .service import error
        if payload != ACCEPT_BODY:
            raise error("invalid_request", 400)
        # feature_enrollment re-checks the owner role and answers owner_required.
        with self.transaction(workspace_id, token, "read") as (wid, cur, actor, role):
            if not readiness.flags_on(self.values):
                raise error("forbidden", 403)
            from ...hosted import audit
            result = feature_enrollment.enroll(cur, wid, FEATURE, actor=actor, role=role, values=self.values, audit=audit)
            granted = self._grant(cur, wid)
            return {"data": {**self.view(cur, wid, role), "replayed": result["replayed"],
                             "entitlement": "granted" if granted else "source_rights_pending"}}

    def leave(self, workspace_id, token):
        with self.transaction(workspace_id, token, "read") as (wid, cur, actor, role):
            from ...hosted import audit
            result = feature_enrollment.unenroll(cur, wid, FEATURE, actor=actor, role=role, audit=audit)
            if not result["replayed"]:
                self._revoke(cur, wid)
            return {"data": {**self.view(cur, wid, role), "replayed": result["replayed"]}}

    def _grant(self, cur, workspace_id):
        """Entitle the shared corpus only under a reviewed cross-workspace policy."""
        scope = shared_scope(self.values)
        if scope is None:
            return False
        expires = reviewed_shared_policy(cur, scope)
        if expires is None:
            return False
        now = datetime.now(timezone.utc)
        expires = min(expires, now + MAX_GRANT)
        from .store import TrendStore
        TrendStore(self.hosted.connection_factory).grant_entitlement(
            workspace_id, scope, list(GRANT_OPERATIONS), contracts.iso(expires), cursor=cur)
        return True

    def _revoke(self, cur, workspace_id):
        scope = shared_scope(self.values)
        if scope is None:
            return 0
        cur.execute("SELECT to_regclass('public.pr_trend_entitlements') IS NOT NULL", ())
        if not _first(cur):
            return 0
        # Revocation changes the scope signature (TrendStore.scope_signature digests
        # entitlement rows), so cursors signed under the old access no longer decode.
        cur.execute("""UPDATE public.pr_trend_entitlements SET revoked_at=clock_timestamp()
            WHERE workspace_id=%s AND scope_key=%s AND revoked_at IS NULL""", (workspace_id, scope))
        return cur.rowcount or 0


def feature_enrollment_codes():
    return ENROLLMENT_CODES


# Safe, bounded refusal codes from feature_enrollment that the HTTP boundary passes through.
ENROLLMENT_CODES = frozenset(("owner_required", "self_serve_paused", "cohort_full", "workspace_not_eligible",
                              "enrollment_unavailable"))

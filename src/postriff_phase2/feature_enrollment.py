"""Owner-initiated, policy-bounded self-serve enrollment for Trends and Growth measurement.

This is the product admission path for ordinary workspaces. It replaces "ask an
operator to edit an env allowlist" with an explicit owner action, while keeping
every boundary that existed before:

- Kill switch: each feature's self-serve switch must be on. Turning it off stops
  new enrollments AND stops admitting already-enrolled workspaces (instant cohort
  rollback without a database write). Legacy env allowlists are untouched.
- Cohort cap: a bounded integer per feature; empty, invalid or negative means 0.
  There is no wildcard value.
- Denylist: explicit workspace UUIDs that can never self-enroll.
- Only the workspace owner may enroll or leave, from an interactive session (the
  HTTP layer checks the session; this module re-checks the role).
- Enrollment is availability, never egress: it creates no provider policy, no
  ingestion job, no model budget and no consent. Those keep their own checks.

The table is created by migrations/postriff/103_feature_enrollments.sql. Until it
exists, every check reports "not enrolled" instead of failing the page.
"""
from __future__ import annotations

import json
import uuid as uuidlib

from postriff_alpha.domain import AlphaError

from .coworker import flags

FEATURES = {
    "trend_radar": {"switch": "RAFII_TREND_SELF_SERVE_ENABLED", "cap": "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES"},
    "growth_measurement": {"switch": "POSTRIFF_METRIC_SELF_SERVE_ENABLED", "cap": "POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES"},
}
DENYLIST = "RAFII_FEATURE_WORKSPACE_DENYLIST"
POLICY_VERSION = "self-serve-20261009-v1"
MAX_COHORT = 10000
# Enrollment changes per workspace+person in a fixed window (pr_auth_throttle).
THROTTLE_LIMIT = 10
THROTTLE_WINDOW_SECONDS = 600


def _source(values):
    return flags._source(values)


def _feature(feature):
    if feature not in FEATURES:
        raise KeyError(feature)
    return FEATURES[feature]


def _uuid(value):
    return str(uuidlib.UUID(str(value)))


def _first(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def self_serve_open(feature, values=None):
    spec = _feature(feature)
    return flags._truthy(_source(values).get(spec["switch"], ""))


def cohort_cap(feature, values=None):
    raw = str(_source(values).get(_feature(feature)["cap"], "")).strip()
    if not raw.isdigit():
        return 0
    return min(int(raw), MAX_COHORT)


def denied(workspace_id, values=None):
    try:
        workspace_id = _uuid(workspace_id)
    except ValueError:
        return True
    listed = set()
    for part in str(_source(values).get(DENYLIST, "")).split(","):
        try:
            if part.strip():
                listed.add(_uuid(part.strip()))
        except ValueError:
            continue
    return workspace_id in listed


def table_ready(cur):
    cur.execute("SELECT to_regclass('public.pr_feature_enrollments') IS NOT NULL")
    return bool(_first(cur))


def status(cur, workspace_id, feature):
    """'active', 'revoked' or None. Never raises for a missing table."""
    _feature(feature)
    if not table_ready(cur):
        return None
    cur.execute("SELECT status FROM public.pr_feature_enrollments WHERE workspace_id=%s AND feature=%s",
                (_uuid(workspace_id), feature))
    return _first(cur)


def admitted(cur, workspace_id, feature, values=None):
    """Enrollment-based admission only. Callers OR this with their legacy allowlist."""
    try:
        workspace_id = _uuid(workspace_id)
    except ValueError:
        return False
    if not self_serve_open(feature, values) or denied(workspace_id, values):
        return False
    return status(cur, workspace_id, feature) == "active"


def admitted_workspaces(cur, feature, values=None):
    """Sorted active enrollments when self-serve is open; [] otherwise (for claim SQL)."""
    _feature(feature)
    if not self_serve_open(feature, values) or not table_ready(cur):
        return []
    cur.execute("SELECT workspace_id::text FROM public.pr_feature_enrollments WHERE feature=%s AND status='active' ORDER BY workspace_id",
                (feature,))
    rows = cur.fetchall()
    found = [next(iter(r.values())) if isinstance(r, dict) else r[0] for r in rows]
    return [w for w in found if not denied(w, values)]


def eligibility(cur, workspace_id, feature, values=None):
    """Why an owner may or may not enroll now. Content-free reason codes only."""
    if denied(workspace_id, values):
        return {"eligible": False, "reason": "workspace_not_eligible"}
    if not self_serve_open(feature, values):
        return {"eligible": False, "reason": "self_serve_paused"}
    if not table_ready(cur):
        return {"eligible": False, "reason": "enrollment_unavailable"}
    if status(cur, workspace_id, feature) == "active":
        return {"eligible": True, "reason": "already_enrolled"}
    cur.execute("SELECT count(*) FROM public.pr_feature_enrollments WHERE feature=%s AND status='active'", (feature,))
    if int(_first(cur) or 0) >= cohort_cap(feature, values):
        return {"eligible": False, "reason": "cohort_full"}
    return {"eligible": True, "reason": "enrollment_open"}


def enroll(cur, workspace_id, feature, *, actor, role, values=None, audit=None):
    """Idempotent owner enrollment under a per-feature advisory lock (cohort cap holds under concurrency)."""
    workspace_id = _uuid(workspace_id)
    actor = _uuid(actor)
    _feature(feature)
    if role != "owner":
        raise AlphaError("Only the workspace owner can turn this on.", 403, code="owner_required")
    if denied(workspace_id, values):
        raise AlphaError("This workspace cannot join yet.", 403, code="workspace_not_eligible")
    if not self_serve_open(feature, values):
        raise AlphaError("New workspaces cannot join right now.", 409, code="self_serve_paused")
    if not table_ready(cur):
        raise AlphaError("Enrollment is not available yet.", 503, code="enrollment_unavailable")
    _throttle(cur, workspace_id, actor)
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("pr_feature_enrollments:" + feature,))
    cur.execute("SELECT status FROM public.pr_feature_enrollments WHERE workspace_id=%s AND feature=%s FOR UPDATE",
                (workspace_id, feature))
    current = _first(cur)
    if current == "active":
        return {"feature": feature, "status": "active", "replayed": True}
    cur.execute("SELECT count(*) FROM public.pr_feature_enrollments WHERE feature=%s AND status='active'", (feature,))
    if int(_first(cur) or 0) >= cohort_cap(feature, values):
        raise AlphaError("This early-access group is full right now.", 409, code="cohort_full")
    cur.execute("""INSERT INTO public.pr_feature_enrollments(workspace_id,feature,status,policy_version,enrolled_by,enrolled_at)
                   VALUES(%s,%s,'active',%s,%s,now())
                   ON CONFLICT(workspace_id,feature) DO UPDATE SET status='active',policy_version=excluded.policy_version,
                     enrolled_by=excluded.enrolled_by,enrolled_at=now(),revoked_by=NULL,revoked_at=NULL,
                     revision=public.pr_feature_enrollments.revision+1""",
                (workspace_id, feature, POLICY_VERSION, actor))
    _audit(cur, audit, workspace_id, actor, "feature.enrolled", feature)
    return {"feature": feature, "status": "active", "replayed": False}


def unenroll(cur, workspace_id, feature, *, actor, role, audit=None):
    """Idempotent owner exit. Leaving is always allowed, whatever the switches say."""
    workspace_id = _uuid(workspace_id)
    actor = _uuid(actor)
    _feature(feature)
    if role != "owner":
        raise AlphaError("Only the workspace owner can turn this off.", 403, code="owner_required")
    if not table_ready(cur):
        return {"feature": feature, "status": "revoked", "replayed": True}
    _throttle(cur, workspace_id, actor)
    cur.execute("""UPDATE public.pr_feature_enrollments SET status='revoked',revoked_by=%s,revoked_at=now(),revision=revision+1
                   WHERE workspace_id=%s AND feature=%s AND status='active'""", (actor, workspace_id, feature))
    changed = cur.rowcount == 1
    if changed:
        _audit(cur, audit, workspace_id, actor, "feature.unenrolled", feature)
    return {"feature": feature, "status": "revoked", "replayed": not changed}


def _throttle(cur, workspace_id, actor):
    from .hosted import throttle  # lazy: hosted imports most of the app

    try:
        throttle(cur, f"feature_enrollment:{workspace_id}:{actor}", THROTTLE_LIMIT, THROTTLE_WINDOW_SECONDS)
    except AlphaError as error:
        raise AlphaError("Too many changes. Wait a few minutes and try again.", 429, code="rate_limited") from error


def _audit(cur, audit, workspace_id, actor, kind, feature):
    meta = {"feature": feature, "policyVersion": POLICY_VERSION}
    if audit is not None:
        audit(cur, workspace_id, actor, kind, feature, meta)
        return
    cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,%s,%s,%s,%s::jsonb)",
                (workspace_id, actor, kind, feature, json.dumps(meta)))

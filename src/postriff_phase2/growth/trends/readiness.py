"""Trends page readiness: one honest answer to "can this workspace use Trends now?".

Built only with feature_readiness.blocker()/resolve() and validated before return.
Everything here is a read: no provider, no model, no write, no ingestion. Every
aggregate is restricted to the caller's own authorized scopes (its workspace scope
plus shared scopes it is currently entitled to), so the answer never reveals
another workspace's enrollment, cohort size, data or policies. Missing tables are
guarded with to_regclass so an unapplied migration reports a state, not a 500.

Branches (mutually exclusive, so the frozen precedence holds trivially):
- flags off                                  -> feature_disabled / trends_off
- not admitted, self-serve open and eligible -> setup_required / enrollment_required
  (owner: consent /app/trends#enroll; everyone else: contact_owner)
- not admitted, paused / full / denied       -> not_entitled / self_serve_paused |
  cohort_full | workspace_not_eligible (wait / wait / none)
- admitted, no reviewed source policy covers any authorized scope
                                             -> unsupported / source_rights_pending
- every authorized provider reports unavailable or gap
                                             -> temporarily_unavailable / provider_unavailable |
  coverage_gap (stored results stay readable; wait)
- zero valid trend projections               -> insufficient_data / no_projections_yet
- otherwise ready (canRun for owner/editor, the roles TrendStore lets write)
"""
from __future__ import annotations

from ... import feature_enrollment, feature_readiness as R
from . import admission, config

FEATURE = "trend_radar"
ENROLL_HREF = "/app/trends#enroll"
REQUIRED_FLAGS = ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS")
# TrendStore._actor(write=True) admits owner/editor only. Admin alignment is an
# integrator change to store.py; until then readiness must not promise admin runs.
WRITE_ROLES = ("owner", "editor")
TABLES = ("pr_trend_scopes", "pr_trend_entitlements", "pr_trend_source_policies", "pr_trend_provider_contracts",
          "pr_trend_projections")
OPTIONAL_TABLES = ("pr_trend_source_health", "pr_trend_ingestion_batches")
OUTAGE = {"unavailable": "provider_unavailable", "revoked": "provider_unavailable", "gap": "coverage_gap"}
# Bounded scan for "is anything valid at all": the newest candidates only.
PROJECTION_PROBE = 50


def flags_on(values=None):
    return all(config.enabled(name, values) for name in REQUIRED_FLAGS)


def _value(cur):
    found = cur.fetchone()
    if found is None:
        return None
    return next(iter(found.values())) if isinstance(found, dict) else found[0]


def _rows(cur):
    found = cur.fetchall() or []
    return [tuple(r.values()) if isinstance(r, dict) else tuple(r) for r in found]


def _tables(cur, names):
    present = {}
    for name in names:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", ("public." + name,))
        present[name] = bool(_value(cur))
    return present


def authorized_scopes(cur, workspace_id):
    """Same rule as TrendStore.authorized_scopes, without its membership lock.

    The caller already holds a verified membership transaction for this workspace.
    """
    cur.execute("""SELECT s.scope_key FROM public.pr_trend_scopes s WHERE s.enabled AND
        (s.workspace_id=%s OR (s.workspace_id IS NULL AND EXISTS(SELECT 1 FROM public.pr_trend_entitlements e
        WHERE e.workspace_id=%s AND e.scope_key=s.scope_key AND e.revoked_at IS NULL
        AND e.expires_at>clock_timestamp() AND 'retrieve'=ANY(e.operations)))) ORDER BY s.scope_key""",
                (workspace_id, workspace_id))
    return [r[0] for r in _rows(cur)]


def reviewed_policy(cur, scopes):
    """A ready, unrevoked, unexpired policy (and contract) allowing retrieval in an authorized scope."""
    if not scopes:
        return False
    cur.execute("""SELECT EXISTS(SELECT 1 FROM public.pr_trend_source_policies p
        JOIN public.pr_trend_provider_contracts c ON (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
        WHERE p.scope_key=ANY(%s) AND p.readiness='ready' AND p.revoked_at IS NULL AND c.revoked_at IS NULL
        AND p.valid_from<=clock_timestamp() AND p.expires_at>clock_timestamp()
        AND c.valid_from<=clock_timestamp() AND c.expires_at>clock_timestamp()
        AND 'retrieve'=ANY(p.operations) AND 'retrieve'=ANY(c.operations))""", (scopes,))
    return bool(_value(cur))


def source_health(cur, scopes):
    """Latest health per (authorized scope, provider). Codes only, never provider text."""
    if not scopes:
        return []
    cur.execute("""SELECT provider_id,status,notes_code,observed_at FROM public.pr_trend_source_health
        WHERE scope_key=ANY(%s) ORDER BY provider_id,scope_key""", (scopes,))
    return [{"provider_id": r[0], "status": r[1], "reason": r[2], "observed_at": r[3]} for r in _rows(cur)]


def last_successful_read(cur, scopes):
    if not scopes:
        return None
    cur.execute("SELECT max(committed_at) FROM public.pr_trend_ingestion_batches WHERE scope_key=ANY(%s)", (scopes,))
    return _value(cur)


def has_valid_projection(cur, scopes):
    if not scopes:
        return False
    cur.execute("""SELECT EXISTS(SELECT 1 FROM (SELECT p.scope_key,p.projection_id FROM public.pr_trend_projections p
        WHERE p.scope_key=ANY(%s) AND p.kind='trend' AND p.available_at<=clock_timestamp()
        AND p.retention_until>clock_timestamp() ORDER BY p.available_at DESC LIMIT %s) c
        WHERE postriff_private.trend_node_valid(c.scope_key,c.projection_id))""", (scopes, PROJECTION_PROBE))
    return bool(_value(cur))


def _not_admitted(cur, workspace_id, role, values):
    eligibility = feature_enrollment.eligibility(cur, workspace_id, FEATURE, values)
    reason = eligibility.get("reason")
    if eligibility.get("eligible") and reason == "enrollment_open":
        step = R.owner_step("consent", ENROLL_HREF, role=role)
        blocker = R.blocker("setup_required", "enrollment_required", blocks_read=True, **step)
    elif reason == "cohort_full":
        blocker = R.blocker("not_entitled", "cohort_full", next_kind="wait", blocks_read=True)
    elif reason == "workspace_not_eligible":
        blocker = R.blocker("not_entitled", "workspace_not_eligible", blocks_read=True)
    else:
        # self_serve_paused, enrollment_unavailable (table not applied) and the
        # unreachable "already_enrolled but not admitted" all mean: not open now.
        blocker = R.blocker("not_entitled", "self_serve_paused", next_kind="wait", blocks_read=True)
    return R.resolve([blocker], can_read=False, can_run=False)


def trend_readiness(cur, workspace_id, *, role, values=None):
    """FeatureReadiness for /app/trends. ``role`` is the caller's verified membership role."""
    if not flags_on(values):
        return R.validate(R.resolve([R.blocker("feature_disabled", "trends_off", blocks_read=True)],
                                    can_read=False, can_run=False))
    if not admission.admitted(cur, workspace_id, values):
        return R.validate(_not_admitted(cur, workspace_id, role, values))
    present = _tables(cur, TABLES + OPTIONAL_TABLES)
    if not all(present[name] for name in TABLES):
        return R.validate(R.resolve([R.blocker("temporarily_unavailable", "trends_schema_unavailable",
                                               next_kind="retry", blocks_read=True)], can_read=False, can_run=False))
    scopes = authorized_scopes(cur, workspace_id)
    can_run = role in WRITE_ROLES
    if not reviewed_policy(cur, scopes):
        # Admitted, but no reviewed source rights cover anything this workspace may
        # read (e.g. the shared corpus rights review is still pending).
        return R.validate(R.resolve([R.blocker("unsupported", "source_rights_pending", next_kind="wait", blocks_read=True)],
                                    can_read=False, can_run=False))
    blockers = []
    health = source_health(cur, scopes) if present["pr_trend_source_health"] else []
    last_read = last_successful_read(cur, scopes) if present["pr_trend_ingestion_batches"] else None
    if health and all(item["status"] in OUTAGE for item in health):
        reason = "provider_unavailable" if any(OUTAGE[item["status"]] == "provider_unavailable" for item in health) else "coverage_gap"
        blockers.append(R.blocker("temporarily_unavailable", reason, next_kind="wait", blocks_read=False, blocks_run=False))
    if not has_valid_projection(cur, scopes):
        blockers.append(R.blocker("insufficient_data", "no_projections_yet", blocks_read=False, blocks_run=False))
    return R.validate(R.resolve(blockers, can_read=True, can_run=can_run, last_successful_read_at=last_read))


def safe_trend_readiness(cur, workspace_id, *, role, values=None):
    """Status must never fail because readiness could not be computed.

    A savepoint keeps a failed aggregate from aborting the caller's transaction.
    None tells the browser to treat readiness as unverified (retry only).
    """
    try:
        cur.execute("SAVEPOINT trend_readiness")
    except Exception:  # noqa: BLE001 - a cursor double without savepoints
        return None
    try:
        result = trend_readiness(cur, workspace_id, role=role, values=values)
        cur.execute("RELEASE SAVEPOINT trend_readiness")
        return result
    except Exception:  # noqa: BLE001 - reported as unverified, never as data
        try:
            cur.execute("ROLLBACK TO SAVEPOINT trend_readiness")
        except Exception:  # noqa: BLE001
            pass
        return None

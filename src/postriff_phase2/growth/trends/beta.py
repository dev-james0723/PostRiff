"""Read-only Beta availability and native post tracking; never dispatches work."""
from datetime import timedelta

from . import config
from .contracts import instant
from .store import row
from ..metric_schedule import OFFSETS
from ...insights import INSIGHT_METRICS


def acquisition_evidence(store, workspace_id):
    """A current, workspace-local collection receipt is the only active proof.

    The query reads counts and health, never provider payloads. A stale success
    cannot mask a newer pause, and a flag cannot manufacture a collection.
    """
    with store.transaction() as cur:
        cur.execute("""SELECT p.readiness, p.revoked_at, p.expires_at,
                c.revoked_at AS contract_revoked_at, c.expires_at AS contract_expires_at,
                h.status AS health, h.observed_at AS health_observed_at, h.next_allowed_at,
                b.committed_at AS collected_at
            FROM public.pr_trend_source_policies p
            JOIN public.pr_trend_provider_contracts c
              ON (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
            LEFT JOIN public.pr_trend_source_health h
              ON (h.scope_key,h.provider_id)=(p.scope_key,p.provider_id)
            LEFT JOIN LATERAL (
              SELECT b.committed_at FROM public.pr_trend_ingestion_batches b
              JOIN public.pr_trend_jobs j ON (j.scope_key,j.job_id)=(b.scope_key,b.job_id)
              WHERE b.scope_key=p.scope_key AND b.provider_id=p.provider_id
                AND j.source_policy_version=p.version AND j.state='succeeded'
                AND b.committed_at>=clock_timestamp()-interval '15 minutes'
              ORDER BY b.committed_at DESC LIMIT 1
            ) b ON true
            WHERE p.scope_key=%s AND p.provider_id='bluesky'
              AND p.manifest->>'operation'='live_sample'
              AND p.valid_from<=clock_timestamp()
            ORDER BY p.valid_from DESC LIMIT 1""", ("workspace:" + workspace_id,))
        evidence = row(cur)
        if not evidence:
            return "unverified"
        cur.execute('SELECT clock_timestamp() AS now')
        now = row(cur)['now']
    if (evidence['revoked_at'] or evidence['contract_revoked_at']
            or evidence['readiness'] != 'ready'
            or instant(evidence['expires_at']) <= instant(now)
            or instant(evidence['contract_expires_at']) <= instant(now)
            or evidence['health'] in ('gap', 'unavailable', 'revoked')
            or evidence['next_allowed_at'] and instant(evidence['next_allowed_at']) > instant(now)):
        return "degraded"
    recent_health = (evidence['health'] in ('healthy', 'partial') and evidence['health_observed_at']
                     and instant(evidence['health_observed_at']) >= instant(now) - timedelta(minutes=15))
    return "active" if evidence['collected_at'] and recent_health else "unverified"


def status(workspace_id, values=None, *, metric_reads_enabled, store=None):
    ready = all(config.enabled(k, values) for k in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS"))
    allowed = config.workspace_allowed(workspace_id, values)
    state = "feature_off" if not ready else "workspace_not_allowlisted" if not allowed else "stored_radar"
    # A provider flag alone admits no operation. Even an explicit operation is
    # configuration, not proof of recent collection or qualified live coverage.
    source = config.flags._source(values)
    operations = [entry.strip().split(":", 1)
                  for entry in str(source.get("RAFII_TREND_ALLOWED_OPERATIONS", "")).split(",")]
    admitted = any(pair == ['bluesky', 'live_sample'] and config.dispatch_allowed(*pair, source)
                   for pair in operations)
    coverage = "unverified" if ready and allowed and admitted else "none"
    if coverage == "unverified" and store is not None:
        coverage = acquisition_evidence(store, workspace_id)
    return {"state": state, "radar_available": ready and allowed, "acquisition": coverage,
            "metric_reads_enabled": bool(metric_reads_enabled), "follower_conversion": "unavailable"}


def horizon_state(row, due, now):
    if row is None:
        return "pending_horizon" if due > now else "unscheduled"
    if row["status"] == "done":
        return "measured" if row["measured"] else "unavailable"
    if row["status"] == "cancelled":
        return "disconnected"
    if row["status"] == "unavailable":
        return "unavailable"
    if row["status"] == "claimed":
        return "pending"
    return "pending_horizon" if due > now else "scheduled"


def tracking(cur, workspace_id, state, now, *, enabled):
    history = (state.get("phase2") or {}).get("jobs", [])
    jobs = [j for j in history if j.get("state") == "verified" and j.get("providerReference")][-120:]
    result = {"enabled": bool(enabled), "as_of": now, "truncated": len(history) > 120, "posts": []}
    rows, direct = {}, set()
    schema_ready = False
    if enabled and jobs:
        cur.execute("SELECT to_regclass('public.pr_metric_reads') IS NOT NULL")
        schema_ready = cur.fetchone()[0]
        if schema_ready:
            cur.execute("""SELECT connection_id FROM public.pr_channel_capabilities
                WHERE workspace_id=%s AND capability='analytics' AND level='Direct'""", (workspace_id,))
            direct = {r[0] for r in cur.fetchall()}
            cur.execute("""SELECT r.job_id,r.connection_id,r.provider,r.provider_post_id,r.read_offset,r.status,
                extract(epoch from r.due_at),r.failure_class,
                EXISTS(SELECT 1 FROM public.pr_metric_observations o WHERE o.workspace_id=r.workspace_id
                  AND o.job_id=r.job_id AND o.connection_id=r.connection_id AND o.provider=r.provider
                  AND o.provider_post_id=r.provider_post_id AND o.read_offset=r.read_offset
                  AND o.availability='available' AND o.value>=0 AND o.value<'Infinity'::float8)
                FROM public.pr_metric_reads r WHERE r.workspace_id=%s AND r.job_id=ANY(%s)""",
                (workspace_id, [j["id"] for j in jobs]))
            rows = {tuple(r[:5]): {"status": r[5], "due": float(r[6]), "reason": r[7], "measured": r[8]}
                    for r in cur.fetchall()}
    channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels", []) if not c.get("revoked")}
    for job in reversed(jobs):
        m = job.get("manifest") or {}
        provider, account = str(m.get("platform", "")).lower(), m.get("channelId")
        anchor = job.get("verifiedAt") or (job.get("verification") or {}).get("at")
        base = ("disabled" if not enabled else "unsupported" if provider not in INSIGHT_METRICS
                else "disconnected" if account not in channels or state.get("accountDeletion")
                else "unavailable" if not schema_ready else "rights_unavailable" if account not in direct else None)
        horizons = []
        for offset, seconds in OFFSETS:
            row = rows.get((job["id"], account, provider, str(job["providerReference"]), offset))
            due = row["due"] if row else anchor + seconds if type(anchor) in (int, float) else None
            measured_state = base or (horizon_state(row, due, now) if due is not None else "unavailable")
            horizons.append({"window": offset, "state": measured_state, "due_at": due,
                             "reason": row["reason"] if row and not base else None})
        result["posts"].append({"job_id": job["id"], "provider": provider, "account": account or "unknown", "horizons": horizons})
    return result

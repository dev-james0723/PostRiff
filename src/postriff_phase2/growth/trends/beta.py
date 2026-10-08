"""Read-only Beta availability and native post tracking; never dispatches work."""
from . import config
from ..metric_schedule import OFFSETS
from ...insights import INSIGHT_METRICS


def status(workspace_id, values=None, *, metric_reads_enabled):
    ready = all(config.enabled(k, values) for k in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS"))
    allowed = config.workspace_allowed(workspace_id, values)
    state = "feature_off" if not ready else "workspace_not_allowlisted" if not allowed else "stored_radar"
    # A provider flag alone admits no operation. Even an explicit operation is
    # configuration, not proof of recent collection or qualified live coverage.
    source = config.flags._source(values)
    operations = [entry.strip().split(":", 1)
                  for entry in str(source.get("RAFII_TREND_ALLOWED_OPERATIONS", "")).split(",")]
    admitted = any(len(pair) == 2 and all(pair) and config.dispatch_allowed(*pair, source)
                   for pair in operations)
    coverage = "unverified" if ready and allowed and admitted else "none"
    return {"state": state, "radar_available": ready and allowed, "acquisition": coverage,
            "metric_reads_enabled": bool(metric_reads_enabled), "follower_conversion": "unavailable"}


def horizon_state(row, due, now):
    if row is None:
        return "unscheduled"
    if row["status"] == "done":
        return "measured" if row["measured"] else "unavailable"
    if row["status"] == "cancelled":
        return "disconnected"
    if row["status"] in ("unavailable", "dead"):
        return "unavailable"
    if row["status"] == "claimed":
        return "pending"
    return "pending_horizon" if due > now else "scheduled"


def tracking(cur, workspace_id, state, now, *, enabled, limit=120):
    if type(limit) is not int or not 1 <= limit <= 300:
        raise ValueError("Tracking limit must be between 1 and 300 posts.")
    history = (state.get("phase2") or {}).get("jobs", [])
    candidates = [j for j in history if j.get("state") == "verified" and j.get("providerReference")]
    jobs = candidates[-limit:]
    result = {"enabled": bool(enabled), "as_of": now, "truncated": len(candidates) > limit, "posts": []}
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
                  AND o.period_start=r.anchor_at
                  AND o.observed_at>=r.anchor_at+make_interval(secs=>CASE r.read_offset WHEN 't0' THEN 0 WHEN '1h' THEN 3600 WHEN '24h' THEN 86400 WHEN '7d' THEN 604800 END)
                  AND o.observed_at<=r.anchor_at+make_interval(secs=>CASE r.read_offset WHEN 't0' THEN 600 WHEN '1h' THEN 4200 WHEN '24h' THEN 87000 WHEN '7d' THEN 605400 END)
                  AND o.availability='available' AND o.value>=0 AND o.value<'Infinity'::float8),extract(epoch from r.anchor_at)
                FROM public.pr_metric_reads r WHERE r.workspace_id=%s AND r.job_id=ANY(%s)""",
                (workspace_id, [j["id"] for j in jobs]))
            rows = {tuple(r[:5]): {"status": r[5], "next_attempt": float(r[6]), "reason": r[7], "measured": r[8], "anchor": float(r[9])}
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
            due = row['anchor']+seconds if row else anchor + seconds if type(anchor) in (int, float) else None
            measured_state = base or (horizon_state(row, due, now) if due is not None else "unavailable")
            horizons.append({"window": offset, "state": measured_state, "due_at": due,
                             'deadline_at':due+600 if due is not None else None,
                             'next_attempt_at':row['next_attempt'] if row else None,
                             "reason": row["reason"] if row and not base else None})
        result["posts"].append({"job_id": job["id"], "provider": provider, "account": account or "unknown", "horizons": horizons})
    return result

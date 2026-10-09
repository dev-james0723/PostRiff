"""Descriptive usage feedback (engineering spec §4 UsageEvent, §11; PRD R15, D6; T11).

`asset_usage(ctx, ref)` lists where an asset (every version in its stack) actually appeared:

    library_event  pr_library_usage_events (source packs, draft attachments, scheduled/published posts, answers, downloads)
    post_job       legacy prepared posts in workspace state (phase2.jobs[].manifest.media and pending reviews, the same rule
                   as the Library UI's buildUsage)
    ideas_draft    Ideas drafts (variants) citing an Ideas source imported from one of these versions
    citation       explicit used_in relations (source packs, drafts, posts), including stale ones

Post metrics come from the existing insights store (pr_metric_observations via insights.latest_observations) with each
reading's source time. A missing or unavailable metric is null and displays "unknown" — never 0. The response describes;
it never claims that an item caused a result: metrics belong to the posts, which shows correlation, not causation.

`record_usage(cur, …)` is the idempotent writer other modules (source packs, the publish path) call.
"""
from __future__ import annotations

import json
import math
import re
import uuid

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import versions

EVENT_TYPES = ("source_pack", "draft_attached", "post_scheduled", "post_published", "agent_answer", "downloaded")
POST_SOURCES = ("library_event", "post_job", "post_review")
HIDDEN = ("deleting", "duplicate", "missing")
MAX_EVENTS = 100
MAX_CITATIONS = 100
MAX_USES = 200
MAX_METRICS = 20
ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
CHANNEL = re.compile(r"^[a-z0-9_\-]{1,60}$")
METRIC = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
NOTE = ("Rafii lists where this item was used and what those posts recorded. Metrics belong to the posts: they show correlation, not causation, "
        "and Rafii cannot tell how much this item contributed. Missing values stay unknown.")

USAGE_PUT = ("/*lio:usage.put*/ INSERT INTO public.pr_library_usage_events(id,workspace_id,asset_key,version_key,segment_id,event_type,draft_id,post_id,"
             "channel,dedup_key,source,metrics,metrics_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,to_timestamp(%s)) "
             "ON CONFLICT(workspace_id,dedup_key) DO NOTHING RETURNING id::text")
USAGE_LIST = ("/*lio:usage.list*/ SELECT event_type,asset_key,version_key,segment_id::text,draft_id,post_id,channel,source,metrics,"
              "extract(epoch from metrics_at),extract(epoch from at) FROM public.pr_library_usage_events WHERE workspace_id=%s "
              "AND (asset_key=ANY(%s) OR version_key=ANY(%s)) ORDER BY at DESC LIMIT %s")
USAGE_CITED = ("/*lio:usage.cited*/ SELECT from_version,from_segment::text,to_kind,to_key,status FROM public.pr_library_relations WHERE workspace_id=%s "
               "AND relation='used_in' AND status IN ('active','stale') AND from_version=ANY(%s) ORDER BY created_at DESC LIMIT %s")


def _key(value) -> str:
    return str(value).replace("-", "").lower()


# --- writer ---------------------------------------------------------------------------------------------------------------
def _optional(value, pattern, label):
    if value is None:
        return None
    if not isinstance(value, str) or not pattern.fullmatch(value):
        c.fail(f"{label} is invalid.")
    return value


def _metrics_in(value):
    if value is None:
        return None
    if not isinstance(value, dict) or len(value) > MAX_METRICS:
        c.fail(f"Record at most {MAX_METRICS} metrics.")
    out = {}
    for name, number in value.items():
        if not isinstance(name, str) or not METRIC.fullmatch(name):
            c.fail("Use simple metric names such as likes or views.")
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0):
            c.fail("A metric is a non-negative number or null when unknown.")
        out[name] = number
    return out


def record_usage(cur, workspace_id, asset_key, version_key, event_type, *, draft_id=None, post_id=None, channel=None, dedup_key, source,
                 segment_id=None, metrics=None, metrics_at=None) -> dict:
    """Record one real use of one version, once per dedup key. Validates that the version exists in this workspace; the
    stored asset key is always that version's lineage. Re-evaluates smart collections that filter by usage."""
    if event_type not in EVENT_TYPES:
        c.fail("Choose a known usage event.")
    asset, version_key = c.asset_key(asset_key), c.asset_key(version_key)
    if not isinstance(dedup_key, str) or not 8 <= len(dedup_key) <= 300 or "\x00" in dedup_key:
        c.fail("Each usage event needs a dedup key of 8 to 300 characters.")
    if not isinstance(source, dict) or len(json.dumps(source, default=str)) > 2000:
        c.fail("Describe the usage source in a short object.")
    draft_id, post_id = _optional(draft_id, ID, "Draft id"), _optional(post_id, ID, "Post id")
    channel = _optional(channel, CHANNEL, "Channel")
    segment = uuid.UUID(hex=c.asset_key(segment_id)) if segment_id is not None else None
    metrics = _metrics_in(metrics)
    if metrics_at is not None and (isinstance(metrics_at, bool) or not isinstance(metrics_at, (int, float))):
        c.fail("metrics_at is an epoch time.")
    from .jobs import system_context
    ctx = system_context(cur, workspace_id)
    if ctx is None:
        return {"recorded": False, "reason": "workspace_unavailable"}
    version = versions.load(ctx, [version_key]).get(version_key)
    if version is None or version["status"] in HIDDEN or asset not in (version["assetId"], version["versionId"]):
        return {"recorded": False, "reason": "unavailable"}
    cur.execute(USAGE_PUT, (uuid.uuid4(), ctx.workspace_id, version["assetId"], version_key, segment, event_type, draft_id, post_id, channel, dedup_key,
                            json.dumps(source, default=str), json.dumps(metrics) if metrics is not None else None,
                            float(metrics_at) if metrics_at is not None else None))
    row = cur.fetchone()
    if row:
        from . import collections
        collections.reevaluate_for_asset(cur, ctx.workspace_id, version_key)  # never raises; usage filters stay current
    return {"recorded": bool(row), "id": _key(row[0]) if row else None}


# --- metrics --------------------------------------------------------------------------------------------------------------
def _metric(value, availability, observed, read_offset=None) -> dict:
    number = None
    if availability == "available" and value is not None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = None
        if number is not None and (not math.isfinite(number) or number < 0):
            number = None
    state = availability if number is not None or availability != "available" else "unavailable"
    display = (str(int(number)) if number.is_integer() else f"{number:g}") if number is not None else "unknown"
    out = {"value": number, "display": display, "availability": state, "observedAt": float(observed) if observed is not None else None}
    if read_offset:
        out["readOffset"] = read_offset
    return out


def _observations(ctx) -> tuple[dict, list]:
    """Latest readings per post from the existing insights store, keyed by job id and provider post id."""
    from .. import insights
    warnings = []
    try:
        ctx.cur.execute("SAVEPOINT library_usage_metrics")
    except Exception:
        return {}, ["Post metrics are unavailable right now; they show as unknown."]
    try:
        rows = insights.latest_observations(ctx.cur, ctx.workspace_id)
        ctx.cur.execute("RELEASE SAVEPOINT library_usage_metrics")
    except Exception:
        try:
            ctx.cur.execute("ROLLBACK TO SAVEPOINT library_usage_metrics")
        except Exception:
            pass
        return {}, ["Post metrics are unavailable right now; they show as unknown."]
    out: dict = {}
    for provider, post_id, job_id, metric, _, value, _, availability, observed, _, _, read_offset in rows:
        reading = _metric(value, availability, observed, read_offset)
        for key in (("job", job_id), ("post", post_id)):
            if key[1]:
                out.setdefault(key, {})[str(metric)] = reading
    return out, warnings


def _status(metrics) -> str:
    if not metrics:
        return "unknown"
    states = {m["value"] is not None for m in metrics.values()}
    return "available" if states == {True} else ("unknown" if states == {False} else "partial")


# --- reads ----------------------------------------------------------------------------------------------------------------
def _media_ids(manifest) -> set:
    return {m.get("id") for m in (manifest or {}).get("media") or [] if isinstance(m, dict) and isinstance(m.get("id"), str)}


def _legacy(ctx, keys: set, by_key: dict) -> list:
    """Prepared posts that reference these items: every job (any state), and reviews awaiting approval that are not
    already a job — the Library UI's buildUsage rule."""
    phase2 = ctx.state.get("phase2") or {}
    out, job_keys = [], set()
    for job in phase2.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        manifest = job.get("manifest") or {}
        job_keys.update(x for x in (job.get("approvalDigest"), manifest.get("idempotencyKey")) if x)
        for media_id in sorted(_media_ids(manifest) & keys):
            out.append({"source": "post_job", "type": "post_job", "jobId": job.get("id"), "postId": job.get("providerReference"),
                        "channel": manifest.get("platform"), "account": manifest.get("account"), "state": job.get("state"),
                        "at": job.get("createdAt") if isinstance(job.get("createdAt"), (int, float)) else None,
                        "version": versions.ref(by_key[media_id])})
    for review in phase2.get("reviews") or []:
        if not isinstance(review, dict) or review.get("status") != "needs_review":
            continue
        manifest = review.get("manifest") or {}
        if review.get("digest") in job_keys or manifest.get("idempotencyKey") in job_keys:
            continue
        for media_id in sorted(_media_ids(manifest) & keys):
            out.append({"source": "post_review", "type": "post_review", "reviewId": review.get("id"), "channel": manifest.get("platform"),
                        "account": manifest.get("account"), "state": "needs_review", "version": versions.ref(by_key[media_id])})
    return out


def _ideas(ctx, keys: set, by_key: dict) -> list:
    sources = {}
    for source in ctx.state.get("sources") or []:
        origin = source.get("origin") if isinstance(source, dict) else None
        if isinstance(origin, dict) and origin.get("kind") == "library" and origin.get("assetId") in keys:
            sources[source.get("id")] = origin["assetId"]
    out = []
    for variant in ctx.state.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        for source_id in variant.get("sourceIds") or []:
            if source_id in sources:
                out.append({"source": "ideas_draft", "type": "draft_cites_source", "draftId": variant.get("id"), "sourceId": source_id,
                            "channel": variant.get("platform"), "version": versions.ref(by_key[sources[source_id]])})
    return out


def asset_usage(ctx, ref) -> dict:
    """asset_usage(ctx, ref) -> descriptive usage data for the asset's whole version stack."""
    ctx.require("read")
    version = versions.resolve(ctx, ref)
    try:
        stack = versions.stack(ctx, version["assetId"])
    except AlphaError:
        stack = [version]
    by_key = {v["versionId"]: v for v in stack}
    by_key.setdefault(version["versionId"], version)
    keys = set(by_key)
    uses = []
    ctx.cur.execute(USAGE_LIST, (ctx.workspace_id, sorted({version["assetId"]} | keys), sorted(keys), MAX_EVENTS))
    for event_type, _, version_key, segment, draft_id, post_id, channel, source, metrics, metrics_at, at in ctx.cur.fetchall():
        entry = {"source": "library_event", "type": event_type, "version": versions.ref(by_key[version_key]) if version_key in by_key else None,
                 "draftId": draft_id, "postId": post_id, "channel": channel, "at": float(at) if at is not None else None}
        if segment:
            entry["segmentId"] = _key(segment)
        if isinstance(metrics, dict) and metrics:
            entry["recordedMetrics"] = {str(name): _metric(value, "available" if value is not None else "unavailable", metrics_at)
                                        for name, value in list(metrics.items())[:MAX_METRICS]}
        uses.append(entry)
    uses += _legacy(ctx, keys, by_key)
    uses += _ideas(ctx, keys, by_key)
    ctx.cur.execute(USAGE_CITED, (ctx.workspace_id, sorted(keys), MAX_CITATIONS))
    for from_version, segment, to_kind, to_key, status in ctx.cur.fetchall():
        entry = {"source": "citation", "type": "used_in", "kind": to_kind, "key": to_key, "status": status,
                 "version": versions.ref(by_key[from_version]) if from_version in by_key else None}
        if to_kind == "draft":
            entry["draftId"] = to_key
        if segment:
            entry["segmentId"] = _key(segment)
        uses.append(entry)
    observations, warnings = _observations(ctx) if any(u["source"] in POST_SOURCES for u in uses) else ({}, [])
    for entry in uses:
        if entry["source"] not in POST_SOURCES:
            entry["metricsStatus"] = "not_applicable"
            continue
        found = observations.get(("job", entry.get("jobId"))) if entry.get("jobId") else None
        if found is None and entry.get("postId"):
            found = observations.get(("job", entry["postId"])) or observations.get(("post", entry["postId"]))
        if found is None and entry.get("recordedMetrics"):
            found = entry["recordedMetrics"]
        entry.pop("recordedMetrics", None)
        entry["metrics"] = found or None
        entry["metricsStatus"] = _status(found)
    posts = [u for u in uses if u["source"] in POST_SOURCES]
    statuses = {u["metricsStatus"] for u in posts}
    summary = {"uses": len(uses), "drafts": len({u["draftId"] for u in uses if u.get("draftId")}),
               "posts": len({u.get("jobId") or u.get("postId") or u.get("reviewId") for u in posts}),
               "channels": sorted({str(u["channel"]) for u in uses if u.get("channel")}),
               "metricsStatus": "not_applicable" if not posts else (statuses.pop() if len(statuses) == 1 else "partial")}
    return {"assetRef": versions.ref(version), "versions": [versions.ref(v) for v in stack], "uses": uses[:MAX_USES], "summary": summary, "note": NOTE,
            "truncated": len(uses) > MAX_USES, "warnings": warnings}


def usage_http(ctx, request):
    """GET .../assets/{key}/usage."""
    version = versions.get(ctx, request["params"]["key"])
    return asset_usage(ctx, versions.ref(version))

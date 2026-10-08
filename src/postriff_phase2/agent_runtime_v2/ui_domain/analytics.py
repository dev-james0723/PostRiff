"""J06 — Analytics / content performance from the existing metric definitions (`insights`, DEFINITION_VERSION, native units,
the "Unavailable, never 0" rule) and the post-feedback comparison of the growth module.

Everything is computed here, server-side, because the OpenUI builtins coerce unknowns to zero: a missing reading is
`null` with its availability, a bucket without readings is `null`, cohorts are never summed across providers, a
comparison below the minimum sample says so, and every derived number names its rule and definition version. Coverage is
a port of web/src/features/analytics/coverage.ts (`buildCoverage`/`coverageState`), checked against the same fixtures by
both languages.
"""
from __future__ import annotations

import datetime as dt
from fractions import Fraction
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import common, query

DATE = {"type": "string", "format": "date", "maxLength": 10}
ZONE = {"type": "string", "maxLength": 64, "pattern": r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$"}
ID = {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:-]{1,120}$"}
METRICS = ("views", "reach", "likes", "comments", "replies", "reposts", "quotes", "shares", "saved")
METRIC = {"type": "string", "enum": list(METRICS)}


def _jobs(state):
    return [j for j in (state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict)]


def _published_at(job):
    timing = (job.get("manifest") or {}).get("timing") or {}
    for key in ("publishedAt", "verifiedAt"):
        if isinstance(job.get(key), (int, float)):
            return float(job[key])
    return timing.get("timestamp") if isinstance(timing.get("timestamp"), (int, float)) else None


def _summary(dctx, basis=None):
    from ... import insights
    return insights.summary(dctx.cur, dctx.workspace_id, _jobs(dctx.state), dctx.now, basis=basis)


def _filtered(dctx, inputs, posts):
    lo, hi = common.window(inputs, dctx.zone, dctx.now, default_days=30)
    jobs = {j.get("id"): j for j in _jobs(dctx.state)}
    kept, undated = [], 0
    for post in posts:
        if inputs.get("platform") and post.get("platform") != inputs["platform"]:
            continue
        if inputs.get("connectionId") and post.get("connectionId") != inputs["connectionId"]:
            continue
        job = jobs.get(post.get("jobId"))
        at = _published_at(job) if job else None
        if at is None:
            undated += 1
            continue
        if lo <= at < hi:
            kept.append((at, post))
    kept.sort(key=lambda item: (-item[0], str(item[1].get("providerPostId"))))
    return kept, undated, lo, hi


def _metric_view(value: dict) -> dict:
    return {"value": value.get("value"), "availability": value.get("availability"), "unit": value.get("unit"), "readOffset": value.get("readOffset"),
            "observedAt": common.iso(value.get("observedAt")), "definitionVersion": value.get("definitionVersion")}


def _verified_in_window(dctx, inputs, lo, hi):
    out = []
    for job in _jobs(dctx.state):
        manifest = job.get("manifest") or {}
        at = _published_at(job)
        if job.get("state") != "verified" or at is None or not lo <= at < hi:
            continue
        if inputs.get("platform") and manifest.get("platform") != inputs["platform"]:
            continue
        if inputs.get("connectionId") and manifest.get("channelId") != inputs["connectionId"]:
            continue
        out.append(job)
    return out


def analytics_posts(dctx, inputs, cursor):
    from ... import insights
    summary = _summary(dctx)
    kept, undated, lo, hi = _filtered(dctx, inputs, summary["posts"])
    page, next_cursor, start = common.paginate("analytics_posts", inputs, cursor, kept, default=50)
    zone = dctx.zone
    rows = []
    for at, post in page:
        metrics = {name: _metric_view(value) for name, value in (post.get("metrics") or {}).items()}
        if inputs.get("metric"):
            metrics = {k: v for k, v in metrics.items() if k == inputs["metric"]} or {inputs["metric"]: {"value": None, "availability": "not_read", "unit": "count",
                                                                                                         "readOffset": None, "observedAt": None, "definitionVersion": insights.DEFINITION_VERSION}}
        rows.append({"ref": common.ref("job", post.get("jobId")), "jobId": post.get("jobId"), "provider": post.get("provider"), "platform": post.get("platform"),
                     "connectionId": post.get("connectionId"), "providerPostId": post.get("providerPostId"), "language": post.get("language"),
                     "publishedAt": common.iso(at), "publishedLocal": common.local(at, zone), "contentOrigin": post.get("contentOrigin"),
                     "metrics": metrics, "rates": post.get("rates"), "cohort": post.get("cohort"),
                     "freshness": {"observedAt": common.iso((post.get("freshness") or {}).get("observedAt")), "ingestedAt": common.iso((post.get("freshness") or {}).get("ingestedAt"))}})
    measured = sum(1 for _, p in kept if any((m or {}).get("availability") == "available" for m in (p.get("metrics") or {}).values()))
    verified = _verified_in_window(dctx, inputs, lo, hi)
    latest = max((p.get("freshness") or {}).get("observedAt") or 0 for _, p in kept) if kept else None
    data = {"posts": rows, "offset": start, "timeZone": zone, "startUtc": common.iso(lo), "endUtc": common.iso(hi), "families": summary.get("families"),
            "rules": summary.get("rules"), "definitionVersion": insights.DEFINITION_VERSION, "undated": undated,
            "verifiedPostsInWindow": len(verified), "postsWithReadings": measured}
    state = "available" if kept else ("empty" if verified == [] else "partial")
    return ui_contracts.query_result(state, data, as_of=common.iso(latest) if latest else common.iso(dctx.now), source_refs=[r["ref"] for r in rows],
                                     next_cursor=next_cursor, known=measured, total=len(verified),
                                     note="Unavailable is never 0. Reach is never summed across platforms." + (f" {undated} reading(s) have no publish time and are left out." if undated else ""),
                                     warnings=["Some verified posts in this period have no reading yet."] if len(verified) > measured else [])


def analytics_compare(dctx, inputs, _cursor):
    from ... import insights
    basis = None if inputs.get("basis") == "latest" else insights.COMPARISON_BASIS
    summary = _summary(dctx, basis=basis)
    kept, undated, lo, hi = _filtered(dctx, inputs, summary["posts"])
    cohorts: dict[tuple, list] = {}
    for _, post in kept:
        cohorts.setdefault(tuple(sorted((post.get("cohort") or {}).items())), []).append(post)
    rows = []
    for key, posts in cohorts.items():
        try:
            outcome = insights.compare(posts, inputs["metric"])
        except AlphaError as error:
            outcome = {"interpretation": "not_comparable", "reason": str(error)[:200]}
        rows.append({"cohort": dict(key), "metric": inputs["metric"], **outcome, "jobIds": [p.get("jobId") for p in posts][:50]})
    rows.sort(key=lambda r: (-int(r.get("sampleSize") or 0), str(r["cohort"].get("account"))))
    data = {"metric": inputs["metric"], "basis": basis or "latest", "comparisons": rows,
            "rules": {"minimum": insights.MIN_COMPARABLE, "basis": insights.COMPARISON_BASIS, "definitionVersion": insights.DEFINITION_VERSION,
                      "like_for_like": summary.get("rules", {}).get("comparison"), "causalityEstablished": False},
            "startUtc": common.iso(lo), "endUtc": common.iso(hi), "timeZone": dctx.zone, "undated": undated}
    comparable = sum(1 for r in rows if r.get("interpretation") == "observation_only")
    return ui_contracts.query_result("available" if comparable else ("partial" if rows else "empty"), data, as_of=common.iso(dctx.now),
                                     known=comparable, total=len(rows),
                                     note=f"A comparison needs at least {insights.MIN_COMPARABLE} comparable posts; it observes, it doesn't establish cause.")


def _bucket(at, zone, size):
    day = dt.datetime.fromtimestamp(at, ZoneInfo(zone)).date()
    if size == "week":
        day = day - dt.timedelta(days=day.weekday())
    return day.isoformat()


def analytics_series(dctx, inputs, _cursor):
    from ... import insights
    summary = _summary(dctx)
    kept, undated, lo, hi = _filtered(dctx, inputs, summary["posts"])
    zone, size, metric = dctx.zone, inputs.get("bucket") or "day", inputs["metric"]
    # Every bucket of the window exists, with null (not 0) when nothing was read there.
    first = dt.datetime.fromtimestamp(lo, ZoneInfo(zone)).date()
    last = dt.datetime.fromtimestamp(hi - 1, ZoneInfo(zone)).date()
    labels, cursor_day = [], first
    while cursor_day <= last:
        label = _bucket(dt.datetime.combine(cursor_day, dt.time(12), ZoneInfo(zone)).timestamp(), zone, size)
        if label not in labels:
            labels.append(label)
        cursor_day += dt.timedelta(days=1)
    series: dict[str, dict] = {}
    for at, post in kept:
        key = f"{post.get('provider')}:{post.get('connectionId')}"
        entry = series.setdefault(key, {"provider": post.get("provider"), "platform": post.get("platform"), "connectionId": post.get("connectionId"),
                                        "buckets": {label: {"posts": 0, "measured": 0, "sum": 0.0} for label in labels}})
        bucket = entry["buckets"].get(_bucket(at, zone, size))
        if bucket is None:
            continue
        bucket["posts"] += 1
        value = ((post.get("metrics") or {}).get(metric) or {})
        if value.get("availability") == "available" and value.get("value") is not None:
            bucket["measured"] += 1
            bucket["sum"] += float(value["value"])
    out = []
    for entry in series.values():
        points = []
        for label in labels:
            b = entry["buckets"][label]
            points.append({"bucket": label, "posts": b["posts"], "measured": b["measured"], "total": b["sum"] if b["measured"] else None,
                           "mean": (str(Fraction(int(b["sum"]), b["measured"])) if b["measured"] and float(b["sum"]).is_integer() else (b["sum"] / b["measured"] if b["measured"] else None))})
        out.append({k: entry[k] for k in ("provider", "platform", "connectionId")} | {"points": points})
    data = {"metric": metric, "bucket": size, "timeZone": zone, "series": out, "definitionVersion": insights.DEFINITION_VERSION, "unit": "count",
            "rule": "one series per provider account; buckets by publish time in this time zone; a bucket with no reading is null, never 0", "undated": undated}
    measured = sum(p["measured"] for s in out for p in s["points"])
    return ui_contracts.query_result("available" if measured else ("partial" if kept else "empty"), data, as_of=common.iso(dctx.now),
                                     known=measured, total=sum(p["posts"] for s in out for p in s["points"]))


# --- coverage (port of web/src/features/analytics/coverage.ts) ---------------------------------------------------------
def build_coverage(channels: list[dict], providers: list[dict], jobs: list[dict], posts: list[dict]) -> dict:
    """Mirror of coverage.ts buildCoverage: every count is the length of a real list; nothing is estimated."""
    by_id = {}
    for channel in channels:
        capability = (channel.get("capabilities") or {}).get("analytics") or {}
        provider = next((p for p in providers if str(p.get("platform") or "").lower() == str(channel.get("platform") or "").lower()), None)
        by_id[channel["id"]] = {"id": channel["id"], "platform": channel.get("platform"), "account": channel.get("account"),
                                "level": capability.get("level") or "Unsupported", "evidence": capability.get("evidence") or "",
                                "verifiedAt": capability.get("verifiedAt"), "providerOffersAnalytics": bool(((provider or {}).get("capabilities") or {}).get("analytics", False)),
                                "providerId": (provider or {}).get("id"), "direct": capability.get("level") == "Direct", "verifiedJobs": [], "readJobIds": [], "posts": [],
                                "lastObservedAt": None}

    def match_job(job):
        manifest = job.get("manifest") or {}
        if manifest.get("channelId") and manifest["channelId"] in by_id:
            return manifest["channelId"]
        hit = next((c for c in channels if str(c.get("platform") or "").lower() == str(manifest.get("platform") or "").lower() and c.get("account") == manifest.get("account")), None)
        return hit["id"] if hit else None

    for job in jobs:
        if job.get("state") != "verified":
            continue
        target = match_job(job)
        if target:
            by_id[target]["verifiedJobs"].append(job)
    by_reference = {str(j["providerReference"]): j for j in jobs if j.get("providerReference")}
    by_job = {j.get("id"): j for j in jobs}
    unmatched, fallback = [], False
    for post in posts:
        if post.get("connectionId"):
            match, by_platform = (post["connectionId"] if post["connectionId"] in by_id else None), False
        else:
            platform = str(post.get("platform") or post.get("provider") or "").lower()
            same = [c for c in channels if str(c.get("platform") or "").lower() == platform]
            match, by_platform = (same[0]["id"], True) if len(same) == 1 else (None, False)
        target = by_id.get(match) if match else None
        if target is None:
            unmatched.append(post)
            continue
        fallback = fallback or by_platform
        target["posts"].append(post)
        job = by_reference.get(str(post.get("providerPostId"))) or (by_job.get(post.get("jobId")) if post.get("jobId") else None)
        if job and job.get("state") == "verified" and job.get("id") not in target["readJobIds"]:
            target["readJobIds"].append(job.get("id"))
        at = (post.get("freshness") or {}).get("observedAt")
        if isinstance(at, (int, float)) and (target["lastObservedAt"] is None or at > target["lastObservedAt"]):
            target["lastObservedAt"] = at
    return {"connections": list(by_id.values()), "unmatchedPosts": unmatched, "usesPlatformFallback": fallback}


def unread_verified_count(connections: list[dict]) -> int:
    return sum(sum(1 for job in c["verifiedJobs"] if job.get("id") not in c["readJobIds"]) for c in connections)


def coverage_state(coverage: dict) -> str:
    direct = [c for c in coverage["connections"] if c["direct"]]
    if not direct:
        return "unavailable"
    if sum(len(c["posts"]) for c in direct) == 0:
        return "pending"
    return "partial" if unread_verified_count(direct) > 0 else "ready"


def _channel_views(dctx):
    from ...channels import assisted_matrix, customer_view
    from ...site_agent import tools
    matrices = tools._matrices(dctx.site_context())
    channels = [c for c in (dctx.state.get("phase2") or {}).get("channels") or [] if isinstance(c, dict)]
    return [customer_view(c, matrices.get(c["id"], assisted_matrix()), dctx.now) for c in channels]


def analytics_coverage(dctx, _inputs, _cursor):
    oauth = getattr(dctx.service, "oauth", None)
    providers = oauth.provider_catalog() if oauth is not None and hasattr(oauth, "provider_catalog") else []
    coverage = build_coverage(_channel_views(dctx), providers, _jobs(dctx.state), _summary(dctx)["posts"])
    state_name = coverage_state(coverage)
    rows = [{"connectionId": c["id"], "platform": c["platform"], "account": c["account"], "level": c["level"], "direct": c["direct"],
             "providerOffersAnalytics": c["providerOffersAnalytics"], "verifiedPosts": len(c["verifiedJobs"]), "readPosts": len(c["readJobIds"]),
             "readings": len(c["posts"]), "lastObservedAt": common.iso(c["lastObservedAt"]), "evidence": c["evidence"][:400] if c["evidence"] else None,
             "enableHref": f"/app/channels?connect={c['providerId']}&capability=analytics" if c["providerId"] else "/app/channels"} for c in coverage["connections"]]
    data = {"state": state_name, "connections": rows, "unmatchedReadings": len(coverage["unmatchedPosts"]), "usesPlatformFallback": coverage["usesPlatformFallback"],
            "rule": "no Direct account → unavailable; Direct but nothing read → pending; some verified posts unread → partial; all read → ready"}
    direct = [r for r in rows if r["direct"]]
    return ui_contracts.query_result({"ready": "available", "partial": "partial", "pending": "partial", "unavailable": "unavailable"}[state_name] if rows else "empty",
                                     data if rows else data, as_of=common.iso(dctx.now), known=sum(r["readPosts"] for r in direct), total=sum(r["verifiedPosts"] for r in direct),
                                     note=None if state_name == "ready" else {"unavailable": "No account shares analytics with Rafii directly.",
                                                                               "pending": "Waiting for the first reading.", "partial": "Some verified posts have no reading yet."}.get(state_name))


def post_feedback(dctx, inputs, _cursor):
    import os
    if os.environ.get("POSTRIFF_GROWTH") != "1" or os.environ.get("POSTRIFF_POST_DOCTOR") != "1":
        return ui_contracts.query_result("unavailable", as_of=common.iso(dctx.now), note="Post feedback is turned off for this deployment.", warnings=["feature_disabled"])
    from ...growth import performance
    jobs = [j for j in _jobs(dctx.state) if j.get("state") == "verified" and j.get("verification") and j.get("providerReference")]
    if not any(j.get("id") == inputs["jobId"] for j in jobs):
        return ui_contracts.query_result("unavailable", as_of=common.iso(dctx.now), note="This post's publication isn't verified, so it has no readings.",
                                         warnings=["publication_not_verified"])
    posts = []
    for job in jobs:
        m = job.get("manifest") or {}
        posts.append({"id": job["id"], "platform": m.get("platform"), "connectionId": m.get("channelId"), "providerPostId": str(job["providerReference"]),
                      "provider": {"Threads": "threads", "Instagram": "instagram"}.get(m.get("platform")), "language": (m.get("payload") or {}).get("language"),
                      "format": (m.get("contentType") or {}).get("formatId", "text"), "timeBucket": "unknown"})
    posts = performance.attach_readings(dctx.cur, dctx.workspace_id, posts)
    post = next(p for p in posts if p["id"] == inputs["jobId"])
    readings = [performance.compare(post, posts, h) for h in performance.HORIZONS]
    observed = sum(1 for r in readings if isinstance(r, dict) and r.get("status") == "observed")
    return ui_contracts.query_result("available" if observed == len(readings) else ("partial" if observed else "unavailable"),
                                     {"jobId": inputs["jobId"], "readings": readings, "minimumBaselinePosts": performance.MIN_BASELINE, "causal": False},
                                     as_of=common.iso(dctx.now), source_refs=[common.ref("job", inputs["jobId"])], known=observed, total=len(readings),
                                     note="Observed outcomes are associations, not causes.")


WINDOW = {"start": DATE, "end": DATE, "zone": ZONE, "platform": {"type": "string", "maxLength": 40}, "connectionId": ID}
query("analytics_posts", "J06", "Published posts in a date range with each native metric (value or null, availability, unit, read offset, definition version), rates and "
      "cohort; coverage = posts with a reading vs verified posts in the range.", {**WINDOW, "metric": METRIC, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
      analytics_posts, page=50, refresh=300)
query("analytics_compare", "J06", "Like-for-like comparison of one metric within each cohort (same account, provider, window, language, post type, definition): sample size, "
      "measured, missing, mean, minimum sample; never across platforms; never causal.",
      {**WINDOW, "metric": METRIC, "basis": {"type": "string", "enum": ["24h", "latest"]}}, analytics_compare, required=("metric",), refresh=300)
query("analytics_series", "J06", "One metric over time per account (day or week buckets by publish time in a time zone); an empty bucket is null, never 0.",
      {**WINDOW, "metric": METRIC, "bucket": {"type": "string", "enum": ["day", "week"]}}, analytics_series, required=("metric",), refresh=300)
query("analytics_coverage", "J06", "Which accounts share analytics directly, how many verified posts have a reading, and the honest state (unavailable/pending/partial/ready).",
      {}, analytics_coverage, refresh=300, tool="channels.capabilities")
query("post_feedback", "J06", "One verified post's readings at 1 h / 24 h / 7 d against the account's own baseline (median, multiple, percentile), when post feedback is on.",
      {"jobId": ID}, post_feedback, required=("jobId",), refresh=300)

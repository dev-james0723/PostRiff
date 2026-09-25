"""Closed-loop performance learning (adaptive coworker spec §9, §12; architecture lock P1).

Account-specific, like-for-like, and never causal:
- posts are compared only inside one cohort (same provider, language and metric definition version, via
  `insights.summary`); unavailable metrics are Unavailable, never 0;
- a dimension (opening style, length, call to action, image, weekday, time of day) splits the cohort into two arms;
  a hypothesis exists only when both arms have at least MIN_ARM measured posts and the difference is material;
- every hypothesis keeps its sample sizes, date range, evidence ids, counter-evidence ids, confidence and expiry,
  is phrased as "may … for this account", and is stored with causal = false (the table refuses anything else);
- a hypothesis never edits voice or learned preferences. The owner may run it as an experiment, dismiss it or
  reject it; otherwise it expires.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import insights

MIN_ARM = 5
MIN_RELATIVE = 0.20
EXPIRY_DAYS = 60
PRIMARY = {"threads": "views", "instagram": "reach"}
PLATFORM = {"threads": "Threads", "instagram": "Instagram"}
_QUESTION = re.compile(r"\?|？")
_CTA = re.compile(r"\b(link in bio|sign up|subscribe|register|book|buy|shop|download|learn more|read more|join|follow|comment below|dm us|order)\b|報名|登記|購買|订阅|訂閱|下載|留言", re.I)


def _zone(name):
    try:
        return ZoneInfo(name) if isinstance(name, str) and name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def published_at(job):
    stamp = ((job.get("manifest") or {}).get("timing") or {}).get("timestamp") or job.get("approvedAt")
    return float(stamp) if isinstance(stamp, (int, float)) else None


def _text(job):
    manifest = job.get("manifest") or {}
    payload = manifest.get("payload") or {}
    for key in ("text", "caption", "body"):
        if isinstance(payload.get(key), str):
            return payload[key]
    return manifest.get("text") or ""


def features(job):
    text = _text(job)
    first = (text.strip().split("\n")[0] if text else "")[:200]
    timing = (job.get("manifest") or {}).get("timing") or {}
    stamp = timing.get("timestamp") or job.get("approvedAt")
    when = datetime.fromtimestamp(stamp, _zone(timing.get("timeZone"))) if isinstance(stamp, (int, float)) else None   # the post's own local time
    media = ((job.get("manifest") or {}).get("payload") or {}).get("media") or (job.get("manifest") or {}).get("media")
    return {
        "opening": ("question", "statement")[0 if _QUESTION.search(first) else 1],
        "length": ("short", "long")[0 if len(text) < 280 else 1],
        "cta": ("with_cta", "no_cta")[0 if _CTA.search(text) else 1],
        "visual": ("with_image", "text_only")[0 if media else 1],
        "weekday": ("weekend", "weekday")[0 if when and when.weekday() >= 5 else 1] if when else None,
        "time": ("morning", "later")[0 if when and when.hour < 12 else 1] if when else None,
    }


DIMENSIONS = {
    "opening": ("question", "statement", "Opening with a question"),
    "length": ("short", "long", "Shorter posts"),
    "cta": ("with_cta", "no_cta", "A clear call to action"),
    "visual": ("with_image", "text_only", "Posts with an image"),
    "weekday": ("weekend", "weekday", "Weekend posting"),
    "time": ("morning", "later", "Morning posting"),
}


def observations(cur, workspace_id, state, now):
    jobs = (state.get("phase2") or {}).get("jobs") or []
    summary = insights.summary(cur, workspace_id, jobs, now)
    by_ref = {j.get("providerReference"): j for j in jobs if j.get("providerReference")}
    rows = []
    for post in summary["posts"]:
        metric = PRIMARY.get(post["provider"])
        value = (post["metrics"].get(metric) or {}).get("value") if metric else None
        job = by_ref.get(post["providerPostId"])
        if job is None or job.get("state") != "verified":
            continue  # only posts the application verified as published are evidence
        rows.append({"postId": post["providerPostId"], "jobId": job.get("id"), "provider": post["provider"], "cohort": post["cohort"], "metric": metric,
                     "value": value, "observedAt": post["freshness"]["observedAt"], "publishedAt": published_at(job), "features": features(job)})
    return rows


ANOMALY_LOW, ANOMALY_HIGH, WEEK = 0.25, 4.0, 7 * 86400


def anomalies(rows, now):
    """A post from the last 7 days whose primary metric is at most a quarter, or at least four times, the median of at
    least MIN_ARM earlier measured posts in its like-for-like group. One post is a signal to look at, never a pattern."""
    out = []
    groups = {}
    for row in rows:
        if row["value"] is not None and row.get("publishedAt"):
            groups.setdefault(json.dumps(row["cohort"], sort_keys=True), []).append(row)
    for members in groups.values():
        for row in members:
            if not now - WEEK <= row["publishedAt"] <= now:
                continue
            earlier = [r["value"] for r in members if r["publishedAt"] < row["publishedAt"]]
            if len(earlier) < MIN_ARM:
                continue
            usual = statistics.median(earlier)
            if usual <= 0 or ANOMALY_LOW * usual < row["value"] < ANOMALY_HIGH * usual:
                continue
            platform = PLATFORM.get(row["provider"], row["provider"])
            ratio = row["value"] / usual
            direction = f"{ratio:.1f} times" if ratio >= 1 else f"{ratio:.0%} of"
            out.append({"postId": row["postId"], "jobId": row["jobId"], "platform": platform, "value": row["value"], "usual": usual, "samples": len(earlier),
                        "reason": f"A recent {platform} post reached {row['value']:,} {row['metric']}, {direction} the usual {usual:,.0f} for this account "
                                  f"(median of {len(earlier)} earlier posts). One post is worth a look, not a pattern."})
    return out


def hypotheses_from(rows, now):
    """Deterministic hypotheses from comparable rows. Returns [{...}] ready to store; nothing is written here."""
    out = []
    cohorts = {}
    for row in rows:
        if row["value"] is None:
            continue
        cohorts.setdefault(json.dumps(row["cohort"], sort_keys=True), []).append(row)
    for key, members in cohorts.items():
        cohort = json.loads(key)
        provider = cohort.get("provider")
        for dimension, (arm_a, arm_b, label) in DIMENSIONS.items():
            a = [r for r in members if r["features"].get(dimension) == arm_a]
            b = [r for r in members if r["features"].get(dimension) == arm_b]
            if len(a) < MIN_ARM or len(b) < MIN_ARM:
                continue
            median_a, median_b = statistics.median(r["value"] for r in a), statistics.median(r["value"] for r in b)
            base = max(median_a, median_b)
            if base <= 0 or abs(median_a - median_b) / base < MIN_RELATIVE:
                continue
            better, worse, better_arm = (a, b, arm_a) if median_a > median_b else (b, a, arm_b)
            threshold = statistics.median(r["value"] for r in worse)
            evidence = [r["jobId"] for r in better if r["value"] > threshold]
            counter = [r["jobId"] for r in better if r["value"] <= threshold]
            n = min(len(a), len(b))
            relative = abs(median_a - median_b) / base
            confidence = "high" if n >= 20 and relative >= 0.3 and len(counter) <= len(better) // 4 else "moderate" if n >= 10 else "low"
            subject = label if better_arm == arm_a else {"opening": "Opening with a statement", "length": "Longer posts", "cta": "Posts without a call to action",
                                                         "visual": "Text-only posts", "weekday": "Weekday posting", "time": "Posting later in the day"}[dimension]
            platform = PLATFORM.get(provider, provider)
            out.append({"platform": platform, "dimension": dimension, "cohort": cohort, "metric": rows[0]["metric"] if rows else "views",
                        "arm_a": arm_a, "arm_b": arm_b, "sample_a": len(a), "sample_b": len(b), "effect": round((median_a - median_b) / base, 3),
                        "statement": f"{subject} may reach more people on {platform} for this account ({n}+ posts per group; not proven to cause it).",
                        "evidence_ids": evidence[:20], "counter_evidence_ids": counter[:20], "confidence": confidence,
                        "date_from": min(r["observedAt"] for r in members), "date_to": max(r["observedAt"] for r in members)})
    return out


def refresh(cur, workspace_id, state, now, notifications=None):
    """Recompute this workspace's hypotheses; update support, supersede flipped ones, expire stale ones."""
    rows = observations(cur, workspace_id, state, now)
    found = hypotheses_from(rows, now)
    created = updated = superseded = 0
    for h in found:
        cur.execute("""SELECT id::text, arm_a, arm_b, effect, revision, status FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND platform=%s AND dimension=%s
                       AND metric=%s AND status IN ('candidate','experiment','supported') ORDER BY revision DESC LIMIT 1""", (workspace_id, h["platform"], h["dimension"], h["metric"]))
        current = cur.fetchone()
        flipped = current is not None and current[3] is not None and (float(current[3]) > 0) != (h["effect"] > 0)
        if current is not None and not flipped:
            cur.execute("""UPDATE public.pr_strategy_hypotheses SET sample_a=%s, sample_b=%s, effect=%s, evidence_ids=%s::jsonb, counter_evidence_ids=%s::jsonb,
                           confidence=%s, statement=%s, last_supported_at=now(), expires_at=now() + make_interval(days => %s), date_to=to_timestamp(%s) WHERE id::text=%s""",
                        (h["sample_a"], h["sample_b"], h["effect"], json.dumps(h["evidence_ids"]), json.dumps(h["counter_evidence_ids"]), h["confidence"], h["statement"],
                         EXPIRY_DAYS, h["date_to"], current[0]))
            updated += 1
            continue
        revision = (current[4] + 1) if current else 1
        if flipped:
            cur.execute("UPDATE public.pr_strategy_hypotheses SET status='rejected', decided_at=now() WHERE id::text=%s", (current[0],))
            superseded += 1
        cur.execute("""INSERT INTO public.pr_strategy_hypotheses(workspace_id,platform,dimension,cohort,statement,metric,arm_a,arm_b,sample_a,sample_b,effect,date_from,date_to,
                              evidence_ids,counter_evidence_ids,confidence,causal,status,revision,replaces_id,last_supported_at,expires_at)
                       VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),%s::jsonb,%s::jsonb,%s,false,'candidate',%s,%s,now(),now() + make_interval(days => %s))
                       ON CONFLICT DO NOTHING""",
                    (workspace_id, h["platform"], h["dimension"], json.dumps(h["cohort"]), h["statement"], h["metric"], h["arm_a"], h["arm_b"], h["sample_a"], h["sample_b"],
                     h["effect"], h["date_from"], h["date_to"], json.dumps(h["evidence_ids"]), json.dumps(h["counter_evidence_ids"]), h["confidence"], revision,
                     current[0] if flipped else None, EXPIRY_DAYS))
        created += cur.rowcount
    cur.execute("UPDATE public.pr_strategy_hypotheses SET status='expired' WHERE workspace_id=%s AND status IN ('candidate','supported') AND expires_at < now()", (workspace_id,))
    expired = cur.rowcount
    recent = [r for r in rows if r.get("publishedAt") and now - WEEK <= r["publishedAt"] <= now]
    if notifications is not None and recent:   # "last week" means posts published in the last 7 days, nothing older
        week = datetime.fromtimestamp(now, timezone.utc).isocalendar()
        measured = sum(1 for r in recent if r["value"] is not None)
        notifications.emit(cur, workspace_id=workspace_id, event_type="analytics.weekly_ready", dedupe_key=f"analytics_weekly:{week[0]}-W{week[1]:02d}",
                           entity_type="analytics", entity_id=workspace_id,
                           payload={"href": "/app/analytics", "metrics": [{"label": "Verified posts in the last 7 days", "value": str(len(recent))},
                                                                          {"label": "With metrics", "value": str(measured)},
                                                                          {"label": "Hypotheses", "value": str(len(found))}]})
    if notifications is not None:
        for anomaly in anomalies(rows, now):
            notifications.emit(cur, workspace_id=workspace_id, event_type="analytics.anomaly_detected", dedupe_key=f"anomaly:{anomaly['postId']}",
                               entity_type="job", entity_id=anomaly["jobId"], payload={"href": "/app/analytics", "platform": anomaly["platform"], "reason": anomaly["reason"]})
    return {"posts": len(rows), "hypotheses": len(found), "created": created, "updated": updated, "superseded": superseded, "expired": expired}


def view(cur, workspace_id, state, now):
    rows = observations(cur, workspace_id, state, now)
    cur.execute("""SELECT id::text, platform, dimension, statement, confidence, status, sample_a, sample_b, effect, evidence_ids, counter_evidence_ids, causal,
                          extract(epoch from date_from), extract(epoch from date_to), extract(epoch from expires_at), revision, experiment
                   FROM public.pr_strategy_hypotheses WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 50""", (workspace_id,))
    items = [{"id": r[0], "platform": r[1], "dimension": r[2], "statement": r[3], "confidence": r[4], "status": r[5], "samples": {"a": r[6], "b": r[7]},
              "effect": float(r[8]) if r[8] is not None else None, "evidenceIds": r[9], "counterEvidenceIds": r[10], "causal": r[11],
              "dateRange": [r[12], r[13]], "expiresAt": r[14], "revision": r[15], "experiment": r[16],
              "why": f"Compared {r[6]} and {r[7]} verified posts in one like-for-like group; {len(r[10] or [])} posts go against it. This is a pattern for this account, not a rule and not a cause."}
             for r in cur.fetchall()]
    measured = [r for r in rows if r["value"] is not None]
    return {"posts": len(rows), "measured": len(measured), "unavailable": len(rows) - len(measured), "hypotheses": items,
            "rules": {"minimumPerGroup": MIN_ARM, "minimumDifference": f"{int(MIN_RELATIVE * 100)}%", "causal": False,
                      "note": "Only verified posts count. Unavailable metrics are never treated as zero. One strong post never becomes a rule."}}

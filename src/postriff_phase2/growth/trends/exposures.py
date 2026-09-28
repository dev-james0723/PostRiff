"""Private descriptive exposure-to-published lineage; no causal attribution."""
from copy import deepcopy
from statistics import median
from datetime import timedelta
from .context import bounded, digest, envelope, finite, source_index, supported, timestamp, visible


def build_lineage(payload):
    cutoff = timestamp(payload["decision_cutoff"])
    events, seen = [], {}
    for row in bounded(payload.get("events", [])):
        if row.get("workspace_id") != payload["workspace_id"]:
            continue
        if not visible(row, cutoff) or timestamp(row["event_at"]) > cutoff:
            continue
        key = row["event_id"]
        if key in seen and seen[key] != digest(row):
            raise ValueError("conflicting event retry")
        if key not in seen:
            seen[key] = digest(row)
            events.append(row)
    events.sort(key=lambda r: (timestamp(r["event_at"]), r["event_id"]))
    exposures, published, ignored, post_keys = {}, {}, [], set()
    for row in events:
        kind, eid = row["event_type"], row.get("exposure_id")
        if kind == "exposure":
            eligible = row.get("eligible_candidate_ids", [])
            chosen = row.get("chosen_candidate_id")
            if not eligible or (chosen is not None and chosen not in eligible):
                raise ValueError("invalid exposure candidate set")
            if eid in exposures:
                raise ValueError("duplicate exposure identity")
            exposures[eid] = {"exposure_id": eid, "eligible_candidate_ids": deepcopy(eligible),
                              "chosen_candidate_id": chosen, "policy_id": row.get("policy_id"),
                              "events": [], "published": [], "outcomes": []}
            continue
        exposure = exposures.get(eid)
        if not exposure:
            ignored.append(row["event_id"])
            continue
        exposure["events"].append({k: deepcopy(row.get(k)) for k in (
            "event_id", "event_type", "event_at", "draft_id", "draft_revision", "angle_id", "format", "hook_id")})
        if kind == "published":
            approvals = [e for e in exposure["events"] if e["event_type"] == "approval" and
                         e["draft_id"] == row.get("draft_id") and e["draft_revision"] == row.get("draft_revision")]
            if row.get("verified") is not True or not row.get("platform_post_id") or not approvals:
                ignored.append(row["event_id"])
                continue
            post_key = (row.get("platform"), row["platform_post_id"])
            if post_key in post_keys:
                ignored.append(row["event_id"])
                continue
            post_keys.add(post_key)
            original_angle = next((e["angle_id"] for e in exposure["events"] if e["event_type"] == "acceptance"), None)
            record = {k: deepcopy(row.get(k)) for k in ("event_id", "draft_id", "draft_revision", "platform", "platform_post_id", "event_at", "angle_id")}
            record["treatment_changed"] = original_angle != row.get("angle_id")
            record["attribution"] = "published_only_descriptive"
            exposure["published"].append(record)
            published[row["event_id"]] = (eid, record)
        elif kind == "outcome":
            link = published.get(row.get("publication_event_id"))
            if (not link or link[0] != eid or row.get("rights", {}).get("analysis") is not True
                    or row.get("complete") is not True or row.get("metric_value") is None):
                ignored.append(row["event_id"])
                continue
            finite(row["metric_value"], minimum=0)
            horizon = finite(row.get("horizon_hours"), minimum=0)
            if timestamp(row["event_at"]) < timestamp(link[1]["event_at"]) + timedelta(hours=horizon):
                ignored.append(row["event_id"])
                continue
            exposure["outcomes"].append({k: deepcopy(row.get(k)) for k in (
                "event_id", "publication_event_id", "metric_definition", "metric_value", "horizon_hours", "event_at")})
    return envelope(payload, workspace_id=payload["workspace_id"], exposures=list(exposures.values()),
                    ignored_event_ids=ignored, exposure_count=len(exposures),
                    published_count=sum(len(e["published"]) for e in exposures.values()),
                    missing_outcomes=sum(not e["outcomes"] for e in exposures.values()),
                    causal_effect=None, strategy_adopted=False)


def creator_baseline(payload):
    cutoff = timestamp(payload["decision_cutoff"])
    target = payload["target"]
    values, excluded = [], 0
    match = ("account_id", "platform", "format", "language", "horizon_hours", "metric_definition")
    for row in bounded(payload.get("outcomes", [])):
        if (row.get("workspace_id") != payload["workspace_id"] or row.get("post_id") == target["post_id"]
                or any(row.get(k) != target.get(k) for k in match) or row.get("verified_published") is not True
                or row.get("rights", {}).get("analysis") is not True or not visible(row, cutoff)
                or timestamp(row["observed_at"]) > cutoff or row.get("complete") is not True
                or row.get("paid_promotion") is not False):
            excluded += 1
            continue
        value = finite(row["value"], minimum=0)
        if payload.get("normalize_impressions") is True:
            impressions = row.get("impressions")
            if impressions is None or finite(impressions, minimum=0) == 0 or row.get("impression_definition") != target.get("impression_definition"):
                excluded += 1
                continue
            value /= impressions
        values.append(value)
    center = median(values) if values else None
    return envelope(payload, workspace_id=payload["workspace_id"], count=len(values), excluded_count=excluded,
                    median=center, mad=median([abs(v-center) for v in values]) if values else None,
                    state="descriptive" if values else "unknown", causal_effect=None,
                    confounders=["audience_change", "selection_bias", "unobserved_promotion"])

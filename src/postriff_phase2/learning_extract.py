"""Extraction from what the person did (preference-learning design §5.2 C1, §5.3): deterministic rules over
learning events become observations; observations are consolidated into proposals with a threshold, a
decay, counter-evidence, scope promotion, conflict handling and an anti-noise gate.

Pure: events and state in, proposals out. No database, no model. A model extractor (C2) feeds the same
consolidation with its own observations, so a candidate from either source clears the same bar.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from postriff_alpha import learning

HALF_LIFE_DAYS = 45
WINDOW_DAYS = 90
# Three edits weigh 3.0 when fresh and decay from there, so the bar sits at 2.5: three edits within about
# twelve days, or four within a month, clear it; two never do.
MIN_SUPPORT = 2.5
MIN_DRAFTS = 2
MAX_COUNTER_RATIO = 0.25
RETIRE_SUPPORT = 2.5
LOW_ACCEPT_RATE = 0.3
LOW_ACCEPT_SAMPLE = 5
MAX_EVIDENCE = 6
WEIGHTS = {"draft.edited": 1.0, "draft.rejected": 1.0, "draft.approved": 0.5, "draft.update_accepted": 0.25, "model": 1.0}

STATEMENTS = {
    ("hashtags.use", "avoid"): "No hashtags.", ("hashtags.use", "do"): "Use hashtags.",
    ("emoji.use", "avoid"): "No emoji.", ("emoji.use", "do"): "Use emoji.",
    ("exclamation.use", "avoid"): "No exclamation marks.",
    ("closing.cta", "avoid"): "Don't end with a call to action.", ("closing.cta", "do"): "End with a call to action.",
    ("lists.use", "avoid"): "No bullet lists.", ("lists.use", "do"): "Use bullet lists.",
    ("opening.style", "avoid"): "Don't open with a question.", ("opening.style", "do"): "Use shorter openings.",
    ("paragraphs.density", "do"): "Keep paragraphs short.",
}
PARAMS = {("opening.style", "do"): {"shortOpenings": True}}
# What an unedited approval says against a rule: the feature the rule would remove was present and stayed.
COUNTERS = {
    ("hashtags.use", "avoid"): lambda f: f.get("hashtags", 0) > 0, ("hashtags.use", "do"): lambda f: f.get("hashtags", 0) == 0,
    ("emoji.use", "avoid"): lambda f: f.get("emoji", 0) > 0, ("emoji.use", "do"): lambda f: f.get("emoji", 0) == 0,
    ("exclamation.use", "avoid"): lambda f: f.get("exclamations", 0) > 0,
    ("closing.cta", "avoid"): lambda f: bool(f.get("closingCta")), ("closing.cta", "do"): lambda f: not f.get("closingCta"),
    ("lists.use", "avoid"): lambda f: f.get("listLines", 0) > 0, ("lists.use", "do"): lambda f: f.get("listLines", 0) == 0,
    ("opening.style", "avoid"): lambda f: bool(f.get("firstLineQuestion")),
}


def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _scope(event):
    scope = event.get("scope") or {}
    return {"platform": scope.get("platform"), "language": scope.get("language"), "contentTypeId": None}


def _observation(event, rule, polarity, weight, value=None):
    scope = _scope(event)
    return {"ruleKey": rule, "polarity": polarity, "scope": scope, "scopeKey": learning.scope_key("writing_preference", rule, polarity, scope),
            "weight": weight, "at": _epoch(event.get("at")), "eventId": event.get("id"), "variantId": (event.get("subject") or {}).get("variantId"), "value": value, "source": "deterministic"}


def _edit_rules(before, after):
    """The rules one edit's feature change suggests (design §5.2 C1)."""
    if before.get("hashtags", 0) > 0 and after.get("hashtags", 0) == 0:
        yield "hashtags.use", "avoid", None
    elif before.get("hashtags", 0) == 0 and after.get("hashtags", 0) > 0:
        yield "hashtags.use", "do", None
    if before.get("emoji", 0) > 0 and after.get("emoji", 0) == 0:
        yield "emoji.use", "avoid", None
    elif before.get("emoji", 0) == 0 and after.get("emoji", 0) > 0:
        yield "emoji.use", "do", None
    if before.get("exclamations", 0) > 0 and after.get("exclamations", 0) == 0:
        yield "exclamation.use", "avoid", None
    if before.get("closingCta") and not after.get("closingCta"):
        yield "closing.cta", "avoid", None
    elif not before.get("closingCta") and after.get("closingCta"):
        yield "closing.cta", "do", None
    if before.get("listLines", 0) > 0 and after.get("listLines", 0) == 0:
        yield "lists.use", "avoid", None
    elif before.get("listLines", 0) == 0 and after.get("listLines", 0) > 0:
        yield "lists.use", "do", None
    if before.get("firstLineQuestion") and not after.get("firstLineQuestion"):
        yield "opening.style", "avoid", None
    if before.get("firstLineTokens", 0) >= 8 and after.get("firstLineTokens", 0) <= 0.7 * before.get("firstLineTokens", 0):
        yield "opening.style", "do", None
    if before.get("tokens", 0) >= 40 and after.get("tokens", 0) <= 0.75 * before.get("tokens", 0):
        yield "length.target", "avoid", after.get("tokens", 0)
    if after.get("paragraphs", 0) > before.get("paragraphs", 0) and after.get("sentencesPerParagraph", 0) < before.get("sentencesPerParagraph", 0):
        yield "paragraphs.density", "do", None


def observations(events):
    """Observations (support) and counter-observations from learning events. Text never enters here."""
    support, counter = [], []
    for event in events:
        kind, features = event.get("kind"), event.get("features") or {}
        if kind == "draft.edited" and isinstance(features.get("before"), dict) and isinstance(features.get("after"), dict):
            for rule, polarity, value in _edit_rules(features["before"], features["after"]):
                support.append(_observation(event, rule, polarity, WEIGHTS[kind], value))
        elif kind == "draft.rejected":
            reasons = features.get("reasons") or []
            if "too_long" in reasons:
                support.append(_observation(event, "length.target", "avoid", WEIGHTS[kind], (features.get("text") or {}).get("tokens")))
        elif kind == "draft.approved" and isinstance(features.get("approved"), dict):
            approved = features["approved"]
            if features.get("editCount") == 0:
                for (rule, polarity), present in COUNTERS.items():
                    if present(approved):
                        counter.append(_observation(event, rule, polarity, WEIGHTS[kind]))
    return support, counter


def _decayed(observation, now):
    age_days = max(0.0, (now - observation["at"]) / 86400)
    return observation["weight"] * (0.5 ** (age_days / HALF_LIFE_DAYS))


def _statement(rule, polarity, scope, values):
    if rule == "length.target":
        measured = [v for v in values if isinstance(v, (int, float)) and v > 0]
        if not measured:
            return None
        target = int(round(statistics.median(measured) / 10.0) * 10) or 10
        unit = "characters" if (scope.get("language") or "").endswith("中文") else "words"
        return f"Keep posts under {target} {unit}."
    return STATEMENTS.get((rule, polarity))


def accept_rate(decisions):
    """Share of recent decisions that kept a proposal; None until there are enough to judge."""
    recent = [d for d in decisions if d in ("remembered", "edited", "dismissed", "post_only")][:10]
    if len(recent) < LOW_ACCEPT_SAMPLE:
        return None
    return sum(1 for d in recent if d in ("remembered", "edited")) / len(recent)


def _levels(scope):
    """The scopes an observation counts towards: its own, its language, everyone (deduplicated)."""
    own = {"platform": scope.get("platform"), "language": scope.get("language"), "contentTypeId": None}
    language = {"platform": None, "language": scope.get("language"), "contentTypeId": None}
    everyone = {"platform": None, "language": None, "contentTypeId": None}
    out = []
    for candidate in (own, language, everyone):
        if candidate not in out:
            out.append(candidate)
    return out


def _group(rule, polarity, scope):
    return {"support": 0.0, "drafts": set(), "evidence": [], "values": [], "first": None, "last": None, "rule": rule, "polarity": polarity, "scope": scope, "sources": set(), "platforms": set(), "languages": set(), "statement": None}


def _add(group, observation, weight):
    group["support"] += weight
    if observation.get("statement") and not group["statement"]:
        group["statement"] = observation["statement"]  # a model's wording, used when no template names the rule
    if observation.get("variantId"):
        group["drafts"].add(observation["variantId"])
    if observation.get("eventId") or observation.get("variantId"):
        group["evidence"].append({k: observation.get(k) for k in ("eventId", "variantId") if observation.get(k)})
    if observation.get("value") is not None:
        group["values"].append(observation["value"])
    group["first"] = observation["at"] if group["first"] is None else min(group["first"], observation["at"])
    group["last"] = observation["at"] if group["last"] is None else max(group["last"], observation["at"])
    group["sources"].add(observation.get("source") or "deterministic")
    scope = observation.get("scope") or {}
    if scope.get("platform"):
        group["platforms"].add(scope["platform"])
    if scope.get("language"):
        group["languages"].add(scope["language"])


def consolidate(support, counter, state, now, dismissed_keys=(), recent_decisions=(), extra=()):
    """Turn observations into proposals worth asking about (design §5.3).

    Every observation counts at three levels: its platform and language, its language across platforms,
    and everyone. A level qualifies with enough decayed support from enough distinct drafts and little
    counter-evidence; the broadest qualifying level that spans two languages (or two platforms) is
    proposed once, otherwise each qualifying platform on its own. Dismissed scopes stay quiet, an
    identical active item is not re-proposed, an opposite active item becomes an update, and an active
    item the person now edits against becomes a retire proposal.
    """
    rate = accept_rate(list(recent_decisions))
    threshold = MIN_SUPPORT * (2 if rate is not None and rate < LOW_ACCEPT_RATE else 1)
    active = {item["scopeKey"]: item for item in learning.active_items(state)}
    levels, against = {}, {}

    def group_for(rule, polarity, scope):
        key = learning.scope_key("writing_preference", rule, polarity, scope)
        return key, levels.setdefault(key, _group(rule, polarity, scope))

    for observation in list(support) + list(extra):
        weight = _decayed(observation, now)
        for scope in _levels(observation.get("scope") or {}):
            _add(group_for(observation["ruleKey"], observation["polarity"], scope)[1], observation, weight)
    for observation in counter:
        weight = _decayed(observation, now)
        for scope in _levels(observation.get("scope") or {}):
            key = learning.scope_key("writing_preference", observation["ruleKey"], observation["polarity"], scope)
            against[key] = against.get(key, 0.0) + weight

    def qualifies(key, group):
        return group["support"] >= threshold and len(group["drafts"]) >= MIN_DRAFTS and against.get(key, 0.0) / group["support"] <= MAX_COUNTER_RATIO

    selected = {}
    for rule, polarity in sorted({(g["rule"], g["polarity"]) for g in levels.values()}):
        key1, everyone = group_for(rule, polarity, {"platform": None, "language": None, "contentTypeId": None})
        if qualifies(key1, everyone) and len(everyone["languages"]) >= 2:
            selected[key1] = everyone
            continue
        for language in sorted(everyone["languages"]):
            key2, per_language = group_for(rule, polarity, {"platform": None, "language": language, "contentTypeId": None})
            if qualifies(key2, per_language) and len(per_language["platforms"]) >= 2:
                selected[key2] = per_language
                continue
            for platform in sorted(per_language["platforms"]):
                key3, own = group_for(rule, polarity, {"platform": platform, "language": language, "contentTypeId": None})
                if qualifies(key3, own):
                    selected[key3] = own

    proposals = []
    for key, group in sorted(selected.items(), key=lambda item: -item[1]["support"]):
        if key in dismissed_keys:
            continue
        statement = _statement(group["rule"], group["polarity"], group["scope"], group["values"]) or group.get("statement")
        if not statement:
            continue
        current = active.get(key)
        if current and current["statement"] == statement:
            continue
        opposite = active.get(learning.scope_key("writing_preference", group["rule"], "do" if group["polarity"] == "avoid" else "avoid", group["scope"]))
        drafts = len(group["drafts"])
        since = datetime.fromtimestamp(group["first"], timezone.utc).strftime("%Y-%m-%d")
        proposals.append({"type": "writing_preference", "ruleKey": group["rule"], "polarity": group["polarity"], "scope": group["scope"], "statement": statement,
                          "params": PARAMS.get((group["rule"], group["polarity"]), {}), "source": "model" if group["sources"] == {"model"} else "deterministic",
                          "why": f"Seen in {drafts} of your drafts on {learning.scope_label(group['scope'])} since {since}.", "evidence": group["evidence"][-MAX_EVIDENCE:],
                          "replaces": opposite["id"] if opposite else (current["id"] if current else None), "support": round(group["support"], 2)})
    # Retire: an active item the person now edits against, at the item's own scope, strongly enough to have proposed the opposite.
    for item in active.values():
        opposite_key = learning.scope_key("writing_preference", item["ruleKey"], "do" if item["polarity"] == "avoid" else "avoid", item["scope"])
        group = levels.get(opposite_key)
        if group and group["support"] >= RETIRE_SUPPORT and len(group["drafts"]) >= MIN_DRAFTS and not any(p["replaces"] == item["id"] for p in proposals):
            proposals.append({"type": item["type"], "ruleKey": item["ruleKey"], "polarity": item["polarity"], "scope": item["scope"], "statement": item["statement"], "params": item.get("params") or {},
                              "source": "deterministic", "op": "retire", "replaces": item["id"], "evidence": group["evidence"][-MAX_EVIDENCE:],
                              "why": f"Your last {len(group['drafts'])} drafts on {learning.scope_label(item['scope'])} went the other way.", "support": round(group["support"], 2)})
    return proposals


# --- Phase D: performance as supporting evidence, and the kill switch -------------------------------

PERFORMANCE_METRICS = ("saved", "likes", "views", "reach")
MIN_MEASURED = 3
NEUTRAL_BAND = 0.10
# Whether the feature a rule is about is present in an approved text.
PRESENCE = {
    "hashtags.use": lambda f: f.get("hashtags", 0) > 0, "emoji.use": lambda f: f.get("emoji", 0) > 0, "exclamation.use": lambda f: f.get("exclamations", 0) > 0,
    "closing.cta": lambda f: bool(f.get("closingCta")), "lists.use": lambda f: f.get("listLines", 0) > 0,
}
REGRESSION_AFTER, REGRESSION_BEFORE, REGRESSION_MARGIN = 5, 3, 0.05


def _in_scope(scope, event_scope):
    return all(scope.get(key) in (None, event_scope.get(key)) for key in ("platform", "language"))


def performance_note(candidate, approved_events, metrics_by_job):
    """Design §3 signal 11: how posts with and without the feature did, like for like (same scope and the
    same content type, following insights.compare), on the first native metric measured on at least three
    posts of each kind. An observation attached to a proposal, never a reason to make one, never a cause."""
    present = PRESENCE.get(candidate.get("ruleKey"))
    if present is None:
        return None
    by_content_type = {}
    for event in approved_events:
        features = (event.get("features") or {}).get("approved")
        job_id = (event.get("subject") or {}).get("jobId")
        metrics = metrics_by_job.get(job_id) if job_id else None
        scope = event.get("scope") or {}
        if not isinstance(features, dict) or not metrics or not _in_scope(candidate.get("scope") or {}, scope):
            continue
        group = by_content_type.setdefault(scope.get("contentTypeId"), ([], []))
        group[0 if present(features) else 1].append(metrics)
    if not by_content_type:
        return None
    content_type, (with_feature, without_feature) = max(by_content_type.items(), key=lambda item: len(item[1][0]) + len(item[1][1]))
    for metric in PERFORMANCE_METRICS:
        a = [m[metric] for m in with_feature if isinstance(m.get(metric), (int, float))]
        b = [m[metric] for m in without_feature if isinstance(m.get(metric), (int, float))]
        if len(a) < MIN_MEASURED or len(b) < MIN_MEASURED:
            continue
        mean_with, mean_without = statistics.mean(a), statistics.mean(b)
        larger = max(mean_with, mean_without) or 1.0
        if abs(mean_with - mean_without) / larger < NEUTRAL_BAND:
            direction = "neutral"
        else:
            better_without = mean_without > mean_with
            direction = "supports" if (better_without == (candidate.get("polarity") == "avoid")) else "contradicts"
        return {"metric": metric, "contentTypeId": content_type, "withFeature": {"posts": len(a), "mean": round(mean_with, 1)}, "withoutFeature": {"posts": len(b), "mean": round(mean_without, 1)},
                "direction": direction, "note": f"Observation from {len(a) + len(b)} published posts of one kind, not a cause; timing and topic also moved."}
    return None


def revision_stats(events):
    """Design §8.1 online metrics: per style revision, how much editing approved drafts needed and how
    many were approved untouched. Read on the Memory page; the number that says whether learning helps."""
    buckets = {}
    for event in events:
        features = event.get("features") or {}
        distance = features.get("editDistance")
        if event.get("kind") != "draft.approved" or not isinstance(distance, (int, float)):
            continue
        revision = int(event.get("styleRevision") or 0)
        bucket = buckets.setdefault(revision, {"approvals": 0, "distance": 0.0, "unedited": 0})
        bucket["approvals"] += 1
        bucket["distance"] += distance
        bucket["unedited"] += 1 if features.get("editCount") == 0 else 0
    return [{"styleRevision": revision, "approvals": b["approvals"], "meanEditDistance": round(b["distance"] / b["approvals"], 3), "uneditedShare": round(b["unedited"] / b["approvals"], 3)}
            for revision, b in sorted(buckets.items())]


def regressions(state, events, now):
    """Design §8.3 kill switch: an active item whose scope's approved drafts needed more editing since it
    took effect (five approvals after against at least three before, by edit distance) becomes a retire
    proposal. The person decides; nothing retires on its own."""
    approvals = [e for e in events if e.get("kind") == "draft.approved" and isinstance((e.get("features") or {}).get("editDistance"), (int, float))]
    proposals = []
    for item in learning.active_items(state):
        since = _epoch(item.get("since"))
        in_scope = [e for e in approvals if learning.applies(item, (e.get("scope") or {}).get("platform"), (e.get("scope") or {}).get("language"))]
        before = [e["features"]["editDistance"] for e in in_scope if _epoch(e.get("at")) < since]
        after = [e for e in in_scope if _epoch(e.get("at")) >= since]
        if len(after) < REGRESSION_AFTER or len(before) < REGRESSION_BEFORE:
            continue
        mean_after, mean_before = statistics.mean(e["features"]["editDistance"] for e in after), statistics.mean(before)
        if mean_after <= mean_before + REGRESSION_MARGIN:
            continue
        proposals.append({"type": item["type"], "ruleKey": item["ruleKey"], "polarity": item["polarity"], "scope": item["scope"], "statement": item["statement"], "params": item.get("params") or {},
                          "source": "deterministic", "op": "retire", "replaces": item["id"], "evidence": [{k: (e.get(k) or (e.get("subject") or {}).get("variantId")) for k in ("id",)} | {"variantId": (e.get("subject") or {}).get("variantId")} for e in after[-MAX_EVIDENCE:]],
                          "why": f"Since this rule, your drafts on {learning.scope_label(item['scope'])} needed more editing ({mean_after:.0%} of the text changed before approval, against {mean_before:.0%} before).",
                          "support": round(mean_after - mean_before, 3)})
    return proposals

"""Active Scout deterministic core. Bounded summaries live inside existing Listening.

Search snippets are leads, not verified creator facts. Metrics never come from
JEV. Every private judgment is workspace scoped; all decisions can abstain.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from . import questions
from .judgments import JudgmentService, subject_hash
from .router import RouterError
from .scout_evidence import number

OBJECTIVES = ("reach", "shareability", "conversation", "follower_conversion", "authority")
DAY = 86400
MAX_SIGNALS = 120
MAX_TRENDS = 30
MAX_OPPORTUNITIES = 50


def key(prefix, *parts):
    return prefix + hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def terms(text):
    return set(re.findall(r"[^\W_]{3,}|[一-鿿]{2}", str(text).lower())) - {"the", "and", "with", "from", "this", "that", "for"}


def timestamp(value):
    if number(value):
        return float(value)
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d.timestamp() if d.tzinfo else None
        except ValueError:
            pass
    return None


def normalize(item, workspace_id, now):
    if not isinstance(item, dict):
        return None
    try:
        u = urlsplit(item.get("url") or "")
        if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password:
            return None
        url = urlunsplit((u.scheme, u.netloc.lower(), u.path or "/", urlencode([(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith("utm_")]), ""))
    except ValueError:
        return None
    p = item.get("provenance") or {}
    if not isinstance(p, dict):
        return None
    # Keep only the existing provenance contract, never arbitrary provider payloads.
    p = {k: copy.deepcopy(v) for k, v in p.items() if k in ("provider", "kind", "accessMethod", "platform", "retrievedAt", "publishedAt", "author",
                                                          "representedScope", "evidenceType", "rights", "injectionFlags", "freshnessDays", "contentHash")}
    if len(json.dumps(p, default=str)) > 8000:
        return None
    text = " ".join(str(item.get("snippet") or "").split())[:800]
    title = " ".join(str(item.get("title") or "").split())[:200]
    published = timestamp(p.get("publishedAt"))
    if published is None and number(p.get("freshnessDays")) and p["freshnessDays"] >= 0:
        published = now - p["freshnessDays"] * DAY
    age = (now - published) / DAY if published is not None and published <= now else None
    creator = p["author"].strip()[:200] or None if isinstance(p.get("author"), str) else None
    content_hash = p.get("contentHash")
    if not isinstance(content_hash, str) or not content_hash.strip() or len(content_hash) > 256:
        content_hash = subject_hash(title, text)
    observed = None
    if p.get("kind") == "official_api" and isinstance(item.get("observedOutcome"), dict):
        from . import scout_outcomes
        row = item["observedOutcome"]
        if p.get("provider") and row.get("provider") == p.get("provider") and row.get("account") and row.get("objective") in OBJECTIVES:
            history = item.get("creatorHistory")
            result = scout_outcomes.evaluate(row, history[:120] if isinstance(history, list) else [])
            observed = {"provider": row["provider"], "account": row["account"], "objective": row["objective"],
                        "window": row.get("window"), "metric": result["metric"], "value": result["value"],
                        "baseline": result["baseline"], "samples": result["samples"], "lift": result["lift"], "state": result["state"],
                        "receipts": [{"metric": name, "value": scout_outcomes.value(row, name), "observedAt": m.get("observedAt"),
                                      "receipt": str(m.get("receipt") or "")[:300], "definition": m.get("definition") or row.get("definition"),
                                      "coverage": m.get("coverage"), "denominator": m.get("denominator")}
                                     for name, m in (row.get("metrics") if isinstance(row.get("metrics"), dict) else {}).items() if name in scout_outcomes.METRICS and isinstance(m, dict)]}
    return {"id": key("sig_", workspace_id, url), "url": url, "title": title, "text": text,
            "contentHash": content_hash, "publishedAt": published, "retrievedAt": now, "ageDays": age,
            "creator": creator, "source": u.hostname.lower(), "platform": p.get("platform") or "web", "provenance": {**p, "retrievedAt": now},
            "rights": p.get("rights") or {}, "mediaType": item.get("mediaType") or "text", "duration": item.get("duration"),
            "coverage": "search_lead" if p.get("evidenceType") == "search_snippet" else "source_reference", "observedOutcome": observed}


def cluster(signals, watchlist_id, workspace_id, now, prior=()):
    """Bounded lexical/time preclustering. An author's repeated posts count once.

    Unknown creators don't become independent just because two URLs exist.
    Lifecycle describes source evidence, never inferred social performance.
    """
    groups = []
    for s in sorted(signals, key=lambda s: (s["retrievedAt"], s["id"]))[:MAX_SIGNALS]:
        words = terms(s["title"])
        group = next((g for g in groups if words and len(words & g["terms"]) / max(1, len(words | g["terms"])) >= .35
                      and abs(s["retrievedAt"] - g["signals"][0]["retrievedAt"]) <= 7 * DAY), None)
        if group is None:
            group = {"terms": words, "signals": []}
            groups.append(group)
        group["signals"].append(s)
    out = []
    for g in groups[:MAX_TRENDS]:
        ss = g["signals"]
        ids = {s["id"] for s in ss}
        old = next((t for t in prior if t.get("watchlistId") == watchlist_id and ids & set(t["signalIds"])), None)
        creators = sorted({f'{s["platform"]}:{s["creator"]}' for s in ss if s["creator"]})
        sources = sorted({s["source"] for s in ss})
        ages = [s["ageDays"] for s in ss if s["ageDays"] is not None]
        known_fresh = [s for s in ss if s["ageDays"] is not None and 0 <= s["ageDays"] <= 3]
        first = min(s["retrievedAt"] for s in ss)
        repeats = len(ss) - len({s["contentHash"] for s in ss})
        saturated = len(ss) >= 4 and repeats / len(ss) >= .5
        stage = "insufficient_evidence"
        if ages and min(ages) > 7:
            stage = "expired"
        elif saturated:
            stage = "saturated"
        elif len(creators) >= 2 and len(sources) >= 2 and len(known_fresh) >= 2:
            stage = "emerging"
            if old and len(ids - set(old["signalIds"])) >= 2 and len(creators) >= 3:
                stage = "rising"
            elif old and old["stage"] in ("rising", "peak"):
                stage = "peak" if len(known_fresh) >= 3 else "declining"
        out.append({"id": old["id"] if old else key("trend_", workspace_id, watchlist_id, ss[0]["id"]), "watchlistId": watchlist_id,
                    "title": ss[0]["title"], "signalIds": sorted(ids), "signals": ss, "firstSeenAt": old["firstSeenAt"] if old else first,
                    "lastSeenAt": max(s["retrievedAt"] for s in ss), "stage": stage,
                    "stageBasis": "Distinct known creators, sources, publication age and new signals; no measured audience velocity.",
                    "independentCreators": len(creators), "sourceCount": len(sources), "platformMix": sorted({s["platform"] for s in ss}),
                    "evidenceCount": len(ss), "saturation": "repeated" if saturated else "not_established", "repetitions": repeats,
                    "velocity": {"newSignals": len(ids - set(old["signalIds"])) if old else len(ids), "observedSince": old["lastSeenAt"] if old else first},
                    "coverage": "partial", "normalizedAnomalies": [s["observedOutcome"] for s in ss if s.get("observedOutcome") and s["observedOutcome"]["lift"] is not None],
                    "expiresAt": min(s["publishedAt"] + 7 * DAY for s in ss if s["publishedAt"] is not None) if ages else now + DAY})
    return out


class ScoutJudge:
    def __init__(self, router):
        self.services = {name: JudgmentService(router.evaluator("scout." + name)) for name in ("signal", "cluster", "workspace_fit", "execution")}

    def judge(self, name, state, workspace_id):
        qs = questions.get("scout_" + name, 1)
        try:
            j = self.services[name].judge(qs, {"rules": qs.state_rules, "evidence": state}, subject=subject_hash(questions.canonical(state)),
                                         scope=f"personal:{workspace_id}", model="typesafe-ai/jev", workspace_id=workspace_id)
        except RouterError as e:
            return {"status": e.code, "answers": {}, "questionSet": qs.key}
        values = {n: (a.value if a.type != "boolean" else a.value >= .65) for n, a in j.answers.items() if not a.abstained}
        return {"status": j.status, "answers": values, "questionSet": qs.key, "digest": qs.digest, "model": j.model,
                "route": j.route, "calibrated": j.calibrated, "cached": j.cached, "invalid": list(j.invalid)}


NATIVE = {
    "Threads": ("short_pov", "Lead with a supported tension; close with one genuine question.", "conversation", "text"),
    "LinkedIn": ("evidence_explainer", "Context, cited evidence, then a bounded professional implication.", "authority", "text"),
    "Instagram": ("carousel", "Visual question, evidence panels, then an original reference checklist.", "save_reference", "original_visuals"),
    "TikTok": ("short_video", "Show an original demonstration, explain the proof, then the payoff.", "watch_and_discuss", "original_video"),
    "YouTube": ("video_explainer", "State the question, show original proof, then a supported explanation.", "watch_and_discuss", "original_video"),
}


def execution_plan(opportunity, channel, language="en"):
    platform = channel.get("platform")
    if platform not in NATIVE or channel.get("revoked"):
        return None
    form, hook, interaction, media = NATIVE[platform]
    objective = opportunity["primaryObjective"]
    return {"id": key("exec_", opportunity["id"], channel["id"], objective, language), "opportunityId": opportunity["id"],
            "trendObjectId": opportunity["trendObjectId"], "platform": platform, "account": channel["id"], "primaryObjective": objective,
            "language": language, "format": form, "angle": opportunity.get("missingAngle") or "Develop an original perspective using creator-supplied facts.",
            "hookStrategy": hook, "evidenceIds": [s["id"] for s in opportunity["evidence"]], "intendedInteraction": interaction,
            "cta": "Ask a specific answerable question" if objective == "conversation" else None,
            "constraints": ["Use current destination validation in Queue", "Ask for missing creator facts; never invent examples"],
            "reason": f"{form.replace('_', ' ')} supports the declared {objective.replace('_', ' ')} objective; outcome is unmeasured.",
            "mediaMode": media, "visualPlan": "Create original evidence panels or demonstration" if media != "text" else None,
            "audioPlan": "Creator's own explanation" if media == "original_video" else None, "captionPlan": "State the supported takeaway and cite references",
            "keyMomentRefs": [{"sourceId": s["id"], "start": m["start"], "end": m["end"], "title": m["title"],
                               "retainUntil": s["mediaEvidence"]["rights"]["retainUntil"]}
                              for s in opportunity["evidence"] for m in (s.get("mediaEvidence") or {}).get("moments", [])][:6],
            "shareMechanism": opportunity.get("shareMechanism", "unsure"), "retentionHypothesis": "Test whether showing proof early helps attention" if media == "original_video" else None,
            "rightsState": "pattern_learning_only", "assetReuseAllowed": False}


def prepare(state, watchlist, items, workspace_id, now, judge=None, max_judgments=8, enrich=None):
    """Pure preparation outside DB locks. At most two clusters reach four JEV gates."""
    listening = (state.get("coworker") or {}).get("listening") or {}
    old_signals = [copy.deepcopy(s) for s in listening.get("scoutSignals", []) if s.get("watchlistId") == watchlist["id"] and s["retrievedAt"] >= now - 7 * DAY]
    for s in old_signals:
        s["ageDays"] = (now - s["publishedAt"]) / DAY if s.get("publishedAt") is not None else None
    unique = {s["url"]: s for s in old_signals}
    for item in items[:12]:
        s = normalize(item, workspace_id, now)
        if s and (s["url"] not in unique or unique[s["url"]]["contentHash"] != s["contentHash"] or s["observedOutcome"] is not None):
            s["watchlistId"] = watchlist["id"]
            unique[s["url"]] = s
    signals = list(unique.values())[-MAX_SIGNALS:]
    trends = cluster(signals, watchlist["id"], workspace_id, now, listening.get("trends", []))
    objective = watchlist.get("primaryObjective")
    if objective not in OBJECTIVES:
        return {"signals": signals, "trends": trends, "opportunities": [], "reason": "Choose a primary growth objective", "judgments": 0}
    opportunities, calls = [], 0
    recent = terms(" ".join(v.get("text", "") for v in (state.get("variants") or [])[-30:]))
    for t in trends:
        words = terms(t["title"] + " " + " ".join(s["text"] for s in t["signals"]))
        wanted = terms(watchlist["query"])
        relevance = len(words & wanted) / max(1, len(wanted))
        novelty = 1 - len(words & recent) / max(1, len(words))
        if relevance < .25 or t["expiresAt"] <= now:
            continue
        decisions = {}
        if judge and calls + 4 <= max_judgments:
            data = {"signals": t["signals"], "trend": {k: v for k, v in t.items() if k != "signals"},
                    "goal": watchlist.get("goal"), "objective": objective, "audience": (state.get("brandHub") or {}).get("audience"),
                    "acceptedPlanningPreferences": [p for p in state.get("_scoutPlanningPreferences", []) if p["cohort"].get("objective") == objective],
                    "alreadyCovered": novelty < .25}
            for gate in ("signal", "cluster", "workspace_fit", "execution"):
                decisions[gate] = judge.judge(gate, data, workspace_id)
                calls += 1
                if gate == "signal" and enrich and decisions[gate].get("answers", {}).get("enrich_worthwhile") is True:
                    for signal in t["signals"][:2]:
                        if signal["mediaType"] == "video":
                            result = enrich(signal)
                            signal["mediaStatus"] = result["status"]
                            if result.get("evidence"):
                                signal["mediaEvidence"] = result["evidence"]
                    data["signals"] = t["signals"]
        answers = {k: v for decision in decisions.values() for k, v in decision.get("answers", {}).items()}
        ready = all(answers.get(k) is True for k in ("meaningful", "sufficient", "audience_fit", "goal_fit", "original_angle", "standalone", "native_fit"))
        share = answers.get("forwarding_utility", "unsure")
        if objective == "shareability" and share in ("none", "unsure"):
            ready = False
        skip = novelty < .25 or t["stage"] == "saturated" or any(answers.get(k) is False for k in ("audience_fit", "goal_fit", "original_angle", "meaningful"))
        action = "skip" if skip else "act_now" if ready and t["stage"] in ("emerging", "rising", "peak") else "watch"
        reason = "Already covered, repeated, or judged a weak fit." if skip else "Independent fresh evidence and bounded gates support an original action." if action == "act_now" else "More evidence or a confident fit judgment is needed."
        measured = [s["observedOutcome"] for s in t["signals"] if s.get("observedOutcome") and s["observedOutcome"]["objective"] == objective and s["observedOutcome"]["lift"] is not None]
        normalized_lift = min(2, max((m["lift"] for m in measured), default=0))
        freshness = max((max(0, 1 - s["ageDays"] / 7) for s in t["signals"] if s["ageDays"] is not None), default=0)
        op = {"id": key("op_", workspace_id, t["id"], objective), "version": "scout.v1.2", "watchlistId": watchlist["id"], "trendObjectId": t["id"],
              "title": t["title"], "url": t["signals"][0]["url"], "evidence": [{**s, "snippet": s["text"]} for s in t["signals"]][:12],
              **{k: t[k] for k in ("stage", "stageBasis", "evidenceCount", "independentCreators", "sourceCount", "platformMix", "saturation", "coverage", "expiresAt")},
              "relevance": relevance, "novelty": novelty, "freshness": freshness, "score": round(relevance + novelty + freshness / 2 + normalized_lift / 2 + min(3, t["independentCreators"]) / 3, 3),
              "normalizedEvidence": measured,
              "confidence": "moderate" if ready else "low", "status": "open", "createdAt": now, "primaryObjective": objective,
              "workspaceFit": answers.get("audience_fit"), "goalFit": answers.get("goal_fit"), "missingAngle": None,
              "growthRationale": f"Your declared goal: {watchlist.get('goal') or objective.replace('_', ' ')}. Test this objective against observed outcomes.",
              "funnelCoverage": {k: "unavailable" for k in ("reach", "shares", "saves", "profile_visits", "follows")},
              "actionType": action, "actionReason": reason, "whyNow": reason, "why": reason, "proposedAction": {"act_now": "Make an original post", "watch": "Watch for more evidence", "skip": "Skip this opportunity"}[action],
              "shareMechanism": share, "jev": decisions, "unknowns": ["Search leads require verification before factual use", "Creator-normalized audience performance unavailable" if not measured else "Normalized evidence covers only the listed accounts and windows", "Business return unmeasured"],
              "executionPlans": []}
        op["executionPlans"] = [p for c in ((state.get("phase2") or {}).get("channels") or [])[:12] if (p := execution_plan(op, c, c.get("language") or "en"))]
        for plan in op["executionPlans"]:
            plan["planningPreferences"] = [p for p in state.get("_scoutPlanningPreferences", []) if p["cohort"].get("account") == plan["account"] and p["cohort"].get("objective") == objective and p["cohort"].get("language") == plan["language"] and p["expiresAt"] > now][:3]
        opportunities.append(op)
    return {"signals": signals, "trends": trends, "opportunities": opportunities, "judgments": calls}


def store(state, watchlist, prepared, now):
    from ..coworker.listening import root
    listening = root(state)
    for name, incoming, cap in (("scoutSignals", prepared["signals"], MAX_SIGNALS), ("trends", prepared["trends"], MAX_TRENDS)):
        listening[name] = ([s for s in listening.get(name, []) if s.get("watchlistId") != watchlist["id"]] + incoming)[-cap:]
    existing = {o["id"]: o for o in listening["opportunities"]}
    new = []
    for op in prepared["opportunities"]:
        prior = existing.get(op["id"])
        if prior:
            for field in ("status", "createdAt", "decidedBy", "decidedAt", "sourceId", "creation"):
                if field in prior:
                    op[field] = prior[field]
        elif op["actionType"] == "act_now":
            new.append(op)
        existing[op["id"]] = op
    listening["opportunities"] = sorted(existing.values(), key=lambda o: (o["status"] != "open", -o["score"]))[:MAX_OPPORTUNITIES]
    watchlist["lastRunAt"] = now
    return new[:3]


def prune_media(state, now):
    """No raw frames or transcripts are persisted; remove derived media when retention expires."""
    root = (state.get("coworker") or {}).get("listening") or {}
    root["mediaCache"] = [e for e in root.get("mediaCache", []) if e["expiresAt"] > now][-24:]
    expiries = [e["expiresAt"] for e in root["mediaCache"]]
    def prune(value):
        if isinstance(value, dict):
            media = value.get("mediaEvidence")
            if media and (media.get("rights") or {}).get("retainUntil", 0) <= now:
                value.pop("mediaEvidence", None)
            elif media:
                expiries.append(media["rights"]["retainUntil"])
            if "keyMomentRefs" in value:
                value["keyMomentRefs"] = [m for m in value["keyMomentRefs"] if m.get("retainUntil", 0) > now]
            for child in value.values():
                prune(child)
        elif isinstance(value, list):
            for child in value:
                prune(child)
    prune(root)
    for source in state.get("sources", []):
        if (source.get("origin") or {}).get("kind") == "scout_opportunity":
            prune(source["origin"])
    root["mediaPurgeAt"] = min(expiries) if expiries else None


def lineage(state, source_ids):
    """Server-owned intent lineage; never a claim that a search snippet is an approved fact."""
    return [{"sourceId": s["id"], "sourceHash": subject_hash(s["text"], s["origin"]["executionPlan"]["id"]),
             "executionPlan": {k: v for k, v in s["origin"]["executionPlan"].items() if k != "keyMomentRefs"}}
            for s in state.get("sources", []) if s["id"] in source_ids and s.get("active") and
            (s.get("origin") or {}).get("kind") == "scout_opportunity"][:6]


def validate_lineage(state, bindings):
    from postriff_alpha.domain import AlphaError
    if bindings != lineage(state, [b["sourceId"] for b in bindings]):
        raise AlphaError("The opportunity source changed or was withdrawn. Review it before drafting again.", 409)


def retention_sweep(cur, now, limit=20):
    """Bounded physical purge, using the existing coworker retention cron step."""
    cur.execute("""SELECT id::text,state FROM public.pr_workspaces
                   WHERE CASE WHEN jsonb_typeof(state #> '{coworker,listening,mediaPurgeAt}')='number'
                              THEN (state #>> '{coworker,listening,mediaPurgeAt}')::double precision <= %s ELSE false END
                   LIMIT %s FOR UPDATE SKIP LOCKED""", (now, min(20, limit)))
    rows = cur.fetchall()
    for workspace_id, state in rows:
        prune_media(state, now)
        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
    return len(rows)

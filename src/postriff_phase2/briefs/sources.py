"""Stored-only readers that turn existing opportunity records into brief candidates (PRD R-BRF-01).

Three permitted sources, each read exactly as its own feature stores it, never re-fetched:

* Social Trend Intelligence: ``TrendService.list(..., {"pool": "weekly"}, kind="opportunity")`` — verified, unexpired
  stored projections only, already filtered by the trend pool's own eligibility, dismissal and exposure cooldowns;
* Listening: open opportunities in ``state.coworker.listening`` that the daily watchlist run already stored;
* Radar: completed/partial stored scans in ``pr_radar_runs`` whose consent/context digest is still current.

No reader starts research, a provider call, a model call or a Radar quote/start/advance; a disabled or unreadable
source is reported as ``unavailable`` with a reason, never as an empty result.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError

from . import composer

LISTENING_COVERAGE = "Public web search results through the Research Broker, with the owner's research consent."
# radar.core's placeholder for an opportunity that was never analysed: the same words for every item, so a brief
# replaces it with an item-specific angle (each brief item shows a distinct angle).
RADAR_GENERIC_ANGLE = "What does this development change for your audience? Add a first-hand example you can verify."
TREND_COVERAGE = "Only stored results in the selected authorized scope; absence is not platform-wide absence."


def epoch(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text[:10], "%Y-%m-%d")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            from datetime import timezone
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def host(url):
    try:
        name = (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return None
    return name[4:] if name.startswith("www.") else (name or None)


def _https(url):
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    return url if parts.scheme == "https" and parts.hostname and not parts.username else None


def coverage(source, state, reason=None, considered=0):
    return {"source": source, "state": state, "reason": reason, "considered": considered}


# --- Social Trend Intelligence -----------------------------------------------------------------------------------------
def _angle_text(angle, projection):
    return " ".join(str(angle.get("title") or angle.get("contribution") or projection.get("contribution") or "").split())[:240]


def trend_candidates(envelope):
    cov = envelope.get("coverage") or {}
    latest = epoch(cov.get("latest_successful_read"))
    out = []
    for p in envelope.get("data") or []:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        angles = [a for a in p.get("angles") or [] if isinstance(a, dict)]
        angle = angles[0] if angles else {}
        fit = p.get("workspace_fit") or {}
        out.append({"source": "trends", "sourceRef": str(p["id"]), "sourceRevision": p.get("revision"), "kind": "signal",
                    "title": p.get("title"), "excerpt": None,
                    "evidence": [{"url": None, "ref": p.get("trust_receipt_id"), "label": "Verified trust receipt"}] if p.get("trust_receipt_id") else [],
                    "publishedAt": None, "retrievedAt": latest, "expiresAt": epoch(p.get("expires_at")),
                    "freshnessBasis": "verified_unexpired_projection" if p.get("verification_state") == "verified" else None,
                    "coverage": {"availability": "available", "representation": cov.get("representation") or "sampled_posts",
                                 "completeness": cov.get("completeness") or "unknown", "scope": "workspace", "note": TREND_COVERAGE},
                    "angle": {"id": angle.get("id"), "text": angle.get("title") or angle.get("contribution") or p.get("contribution")},
                    "effortHint": "deep" if any(a.get("factual_requirements") for a in angles) else None,
                    "platforms": list(p.get("platform_targets") or []),
                    "fit": {k: fit.get(k) for k in ("audience", "brand", "risk", "trend_relevance", "timing", "originality") if isinstance(fit.get(k), dict)},
                    "interests": [], "matchText": p.get("contribution") or "",
                    "action": {"kind": "accept", "requires": ["angleId", "channelId"], "angleIds": [a["id"] for a in angles if a.get("id")][:3],
                               # Each choosable angle with its own words, so the accept form never shows a bare id.
                               "angles": [{"id": a["id"], "text": _angle_text(a, p)} for a in angles if a.get("id")][:3],
                               "revision": p.get("revision"), "platforms": list(p.get("platform_targets") or [])[:6]},
                    "limitations": [p.get("uncertainty")] if p.get("uncertainty") else [],
                    "href": f"/app/trends?opportunity={p['id']}"})
    return out


def trends_allowed(workspace_id, values=None):
    from ..growth.trends import config
    try:
        return config.workspace_allowed(workspace_id, values) and config.enabled("RADAR", values)
    except KeyError:
        return False


def read_trends(hosted, workspace_id, token, *, repository=None, values=None):
    """The trend weekly pool through TrendService (its own authenticated transaction; call it before taking the
    workspace lock). Returns (candidates, coverage); never raises."""
    if not trends_allowed(workspace_id, values):
        return [], coverage("trends", "unavailable", "trends_not_enabled")
    try:
        from ..coworker import runtime
        coworker = runtime.ensure(hosted).coworker
        if repository is not None:
            import copy
            from ..growth.trends.service import TrendService
            bound = copy.copy(coworker)
            bound.hosted = copy.copy(hosted)
            bound.hosted.repository = repository
            service = TrendService(bound)
            service.repository = repository
        else:
            service = coworker.trends
        envelope = service.list(workspace_id, token, {"pool": "weekly"}, kind="opportunity")
    except AlphaError as error:
        reason = {403: "trends_not_permitted", 404: "trends_unavailable", 410: "trends_evidence_unavailable"}.get(error.status, "trends_source_unavailable")
        return [], coverage("trends", "unavailable", reason)
    except Exception as error:  # noqa: BLE001 - a missing trend schema or store never breaks the brief
        return [], coverage("trends", "unavailable", "trends_" + type(error).__name__.lower()[:30])
    candidates = trend_candidates(envelope)
    return candidates, coverage("trends", "available" if candidates else "empty", None, len(candidates))


# --- Listening ---------------------------------------------------------------------------------------------------------
def listening_candidates(state, enabled):
    if not enabled:
        return [], coverage("listening", "unavailable", "listening_not_enabled")
    listening = (state.get("coworker") or {}).get("listening") or {}
    watchlists = {w.get("id"): w for w in listening.get("watchlists") or [] if isinstance(w, dict)}
    out = []
    for op in listening.get("opportunities") or []:
        if not isinstance(op, dict) or op.get("status") != "open" or not op.get("id"):
            continue
        evidence = [e for e in op.get("evidence") or [] if isinstance(e, dict)]
        first = (evidence[0].get("provenance") if evidence else None) or {}
        watch = watchlists.get(op.get("watchlistId")) or {}
        title = " ".join(str(op.get("title") or "").split())
        question = composer.is_question(title)
        angle = (f"Answer “{title[:80]}” from your own experience, with one example you can verify." if question
                 else f"What “{title[:80]}” changes for your audience, with a first-hand example you can verify.")
        out.append({"source": "listening", "sourceRef": str(op["id"]), "sourceRevision": int(op.get("createdAt") or 0),
                    "kind": "question" if question else "signal", "title": title, "excerpt": None,
                    "evidence": [{"url": _https(e.get("url")), "label": host(e.get("url")),
                                  "publishedAt": epoch((e.get("provenance") or {}).get("publishedAt")),
                                  "retrievedAt": epoch((e.get("provenance") or {}).get("retrievedAt"))} for e in evidence[:3]],
                    "publishedAt": epoch(first.get("publishedAt")), "retrievedAt": epoch(first.get("retrievedAt")) or epoch(op.get("createdAt")),
                    "expiresAt": epoch(op.get("expiresAt")),
                    "coverage": {"availability": "available", "representation": "search_results", "completeness": "partial", "scope": "watchlist", "note": LISTENING_COVERAGE},
                    "angle": {"id": None, "text": angle}, "effortHint": "quick", "platforms": [],
                    "interests": [{"label": watch.get("query"), "via": "watchlist"}] if watch.get("query") else [],
                    "matchText": "",
                    "unsafe": any((e.get("provenance") or {}).get("injectionFlags") for e in evidence),
                    "lowConfidence": op.get("confidence") == "low",
                    "action": {"kind": "save_idea"},
                    "limitations": [op.get("note") or "A search result is a lead; read the source before relying on it."],
                    "href": "/app/weekly?tab=opportunities"})
    return out, coverage("listening", "available" if out else "empty", None, len(out))


# --- Radar -------------------------------------------------------------------------------------------------------------
def radar_enabled(env):
    return (env or {}).get("POSTRIFF_GROWTH") == "1" and (env or {}).get("POSTRIFF_RADAR") == "1"


def radar_candidates(cur, workspace_id, state, now, env):
    """Stored completed/partial scans whose consent context is current; a scan from older consent is stale and not
    shown (Radar itself withholds it). Read only: no lease, quote, start or advance."""
    if not radar_enabled(env):
        return [], coverage("radar", "unavailable", "radar_not_enabled")
    from ..radar.service import Radar
    try:
        cur.execute("SAVEPOINT brief_radar_read")
        cur.execute("""SELECT id::text, context_digest, body, extract(epoch from created_at) FROM public.pr_radar_runs
                       WHERE workspace_id=%s AND status IN ('completed','partial') AND expires_at>to_timestamp(%s)
                       ORDER BY created_at DESC, id DESC LIMIT 5""", (workspace_id, now))
        rows = cur.fetchall()
        cur.execute("RELEASE SAVEPOINT brief_radar_read")
    except Exception:  # noqa: BLE001 - an unapplied Radar migration is "unavailable", not a failure
        cur.execute("ROLLBACK TO SAVEPOINT brief_radar_read")
        return [], coverage("radar", "unavailable", "radar_unreadable")
    current = Radar.context(state)
    out, stale = [], 0
    for run_id, context_digest, body, created in rows:
        body = body if isinstance(body, dict) else json.loads(body)
        if context_digest != current:
            stale += 1
            continue
        finished = epoch(body.get("finishedAt")) or float(created)
        for op in body.get("opportunities") or []:
            if not isinstance(op, dict) or not op.get("eligible") or op.get("dismissed") or op.get("sourceId") or not op.get("id"):
                continue
            evidence = [e for e in op.get("evidence") or [] if isinstance(e, dict)]
            excerpt = next((e.get("excerpt") for e in evidence if (e.get("rights") or {}).get("displayExcerpt") and e.get("excerpt")), None)
            known = [epoch(e.get("publishedAt")) for e in evidence if epoch(e.get("publishedAt")) is not None]
            title = " ".join(str(op.get("title") or "").split())
            angle = op.get("angle") if op.get("angle") and op.get("angle") != RADAR_GENERIC_ANGLE else \
                f"What “{title[:80]}” changes for your audience — add a first-hand example you can verify."
            out.append({"source": "radar", "sourceRef": f"{run_id}:{op['id']}",
                        "sourceRevision": hashlib.sha256(json.dumps(sorted(op.get("evidenceIds") or [])).encode()).hexdigest()[:16],
                        "kind": "signal", "title": op.get("title"), "excerpt": excerpt,
                        "evidence": [{"url": _https(e.get("url")), "label": e.get("source") or host(e.get("url")),
                                      "publishedAt": epoch(e.get("publishedAt")), "retrievedAt": epoch(e.get("retrievedAt"))} for e in evidence[:3]],
                        "publishedAt": max(known) if known else None, "retrievedAt": finished,
                        "expiresAt": epoch(op.get("expiresAt")),
                        "coverage": {"availability": "available", "representation": "search_lead", "completeness": "incomplete", "scope": "radar_scan",
                                     "note": body.get("notice") or "Source coverage and causal impact are not established."},
                        "angle": {"id": f"radar:{op['id']}", "text": angle},
                        "effortHint": "deep" if len(evidence) >= 3 else "medium", "platforms": [],
                        "interests": ([{"label": body.get("query"), "via": "radar"}] if body.get("query") else [])
                                     + ([{"label": "a supported Content DNA lesson", "via": "content_dna"}] if op.get("forYou") else []),
                        "matchText": "",
                        "unsafe": any(e.get("injection") for e in evidence),
                        "action": {"kind": "save_idea", "via": "radar", "scanId": run_id, "opportunityId": op["id"]},
                        "limitations": [str(x) for x in (op.get("confidenceReasons") or [])[:2]],
                        "href": "/app/growth?tab=radar"})
    state_name = "available" if out else ("stale" if stale else "empty")
    return out, {**coverage("radar", state_name, "stale_consent" if stale and not out else None, len(out)), "staleScans": stale}


# --- the person's goals and material -----------------------------------------------------------------------------------
def context(state):
    from ..coworker import growth_loop, weekly_operator
    goal = growth_loop.active_goal(state)
    weekly = weekly_operator.view(state)
    goals = ([goal["name"]] if goal and goal.get("name") else []) + [g for r in weekly.get("recipes") or [] if r.get("status") == "active" for g in r.get("goals") or []]
    material = [{"id": s.get("id"), "title": s.get("title")} for s in state.get("sources") or []
                if s.get("active") and s.get("kind") != "voice_sample" and s.get("title") and s.get("title") != "Source note"][-40:]
    angles = [slot.get("angle") for week in (weekly.get("weeks") or [])[-2:] for slot in week.get("slots") or [] if slot.get("angle")]
    return {"goals": goals[:8], "material": material, "brand": (state.get("brandHub") or {}).get("subject"), "recentAngles": angles[:60],
            "goalId": goal.get("id") if goal else None}

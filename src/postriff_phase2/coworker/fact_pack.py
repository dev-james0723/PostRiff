"""FactPack and CanonicalBrief (adaptive coworker spec §11-§12; architecture lock S2).

A FactPack is the evidence a campaign may use: atomic claims, each with its evidence (source item, relation
supports/contradicts/context_only, evidence type), a status, freshness and whether a draft may use it. It ports the
claim/contradiction semantics of the local studio's source log (not imported) into hosted state.

Rules:
- a search snippet alone is `unverified` and never `usableForDraft`;
- first-party material the person supplied is `attributed` to that source (their own claim, kept with attribution);
- a page's claim is `attributed` to its publisher, `corroborated` when a second independent host states it;
- two claims on the same subject with different figures are both `disputed`, listed in `contradictions` and kept
  out of drafts: the conflict survives instead of one side being picked silently;
- prompt-injection text found in a source is reported with the source and never becomes a claim.
"""
from __future__ import annotations

import hashlib
import json
import re

from .research_broker import INJECTION_PATTERNS

STATUSES = ("confirmed", "corroborated", "attributed", "disputed", "unverified")
MAX_CLAIMS = 30
FRESH_DAYS = {"news": 14, "statistic": 365, "event": 60, "statement": 3650, "quote": 3650}
_SENTENCE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_NUMBER = re.compile(r"\d[\d,.]*\s*(?:%|percent|萬|万|億|亿|million|billion|k\b)?", re.I)
_QUOTE = re.compile(r"[“\"「『]([^”\"」』]{8,300})[”\"」』]")
_DATE = re.compile(r"\b(?:19|20)\d{2}\b|\d{1,2}\s*月|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_INJECTION = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
_STOP = set("the a an of to in on for and or with is are was were be been by at from this that it its as our we you they their".split())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _claim_type(text):
    if _QUOTE.search(text):
        return "quote"
    if _NUMBER.search(text):
        return "statistic"
    if _DATE.search(text):
        return "event"
    return "statement"


def _subject(text):
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text) if w.lower() not in _STOP]
    cjk = re.findall(r"[一-鿿]{2}", text)
    return frozenset(words[:6] + cjk[:6])


def _numbers(text):
    return {re.sub(r"[,\s]", "", n).lower() for n in _NUMBER.findall(text)}


def extract_claims(text, limit=MAX_CLAIMS):
    """Candidate atomic claims: sentences that carry something checkable (a figure, a date, a quote, a named
    statement). Instruction-like text is never a claim."""
    out = []
    for sentence in _SENTENCE.split(text or ""):
        sentence = " ".join(sentence.split()).strip(" -•")
        if len(sentence) < 20 or len(sentence) > 400:
            continue
        if any(p.search(sentence) for p in _INJECTION):
            continue
        out.append(sentence)
        if len(out) >= limit:
            break
    return out


def build(sources, now, window_days=None):
    """FactPack from SourceArtifacts (or research items shaped like them): {schema, id, claims, contradictions,
    unknowns, injectionFlags, sourceIds, hash}. Each source: {id, text, provenance{evidenceType, host, publishedAt,
    retrievedAt, kind}}."""
    claims, flags = [], []
    for source in sources:
        prov = source.get("provenance") or {}
        evidence_type = prov.get("evidenceType") or "user_supplied"
        for flag in prov.get("injectionFlags") or []:
            flags.append({"sourceId": source["id"], **flag})
        for index, text in enumerate(extract_claims(source.get("text") or "")):
            kind = _claim_type(text)
            if evidence_type == "search_snippet":
                status, usable = "unverified", False
            elif evidence_type in ("user_supplied", "transcript", "social_post", "image_text", "owned_post"):
                status, usable = "attributed", True
            else:
                status, usable = "attributed", True
            claims.append({"claimId": f"cl_{hashlib.sha256((source['id'] + text).encode()).hexdigest()[:12]}", "text": text, "claimType": kind,
                           "status": status, "usableForDraft": usable, "evidence": [{"sourceId": source["id"], "relation": "supports", "evidenceType": evidence_type,
                                                                                    "host": prov.get("host"), "locator": f"sentence {index + 1}"}],
                           "freshness": {"publishedAt": prov.get("publishedAt"), "retrievedAt": prov.get("retrievedAt"),
                                         "windowDays": window_days or FRESH_DAYS.get(kind, 365), "stale": False},
                           "qualification": None})
    # Corroboration: the same figures stated by a second independent host.
    for claim in claims:
        if claim["status"] != "attributed" or claim["evidence"][0]["evidenceType"] != "page_text":
            continue
        numbers = _numbers(claim["text"])
        for other in claims:
            if other is claim or other["evidence"][0]["host"] in (None, claim["evidence"][0]["host"]):
                continue
            if numbers and numbers <= _numbers(other["text"]) and len(_subject(claim["text"]) & _subject(other["text"])) >= 2:
                claim["status"] = "corroborated"
                claim["evidence"].append({**other["evidence"][0], "relation": "supports"})
                break
    # Contradictions: same subject, different figures, from different sources. Both stay, both are kept out of drafts.
    contradictions = []
    for i, first in enumerate(claims):
        for second in claims[i + 1:]:
            if first["evidence"][0]["sourceId"] == second["evidence"][0]["sourceId"]:
                continue
            a, b = _numbers(first["text"]), _numbers(second["text"])
            if a and b and a != b and not (a & b) and len(_subject(first["text"]) & _subject(second["text"])) >= 3:
                for claim, other in ((first, second), (second, first)):
                    claim["status"], claim["usableForDraft"] = "disputed", False
                    claim["evidence"].append({"sourceId": other["evidence"][0]["sourceId"], "relation": "contradicts", "evidenceType": other["evidence"][0]["evidenceType"],
                                              "host": other["evidence"][0].get("host"), "claimId": other["claimId"]})
                contradictions.append({"claims": [first["claimId"], second["claimId"]], "note": "Different figures for the same subject; both are shown, neither is used in drafts."})
    unknowns = []
    if not any(c["usableForDraft"] for c in claims):
        unknowns.append("No claim in these sources can be used in a draft yet: they are unverified leads or disputed.")
    pack = {"schema": "rafii.factpack.v1", "claims": claims[:MAX_CLAIMS], "contradictions": contradictions, "unknowns": unknowns,
            "injectionFlags": flags, "sourceIds": [s["id"] for s in sources], "createdAt": now}
    pack["hash"] = _digest({k: pack[k] for k in ("claims", "contradictions", "sourceIds")})
    pack["id"] = "fp_" + pack["hash"][:16]
    return pack


def canonical_brief(pack, *, goal, audience, cta=None, exclusions=()):
    """One core message from the usable claims, the claims it relies on (by id), CTA, exclusions (every disputed or
    unverified claim is excluded explicitly) and unknowns. Drafts are written from this, never from the raw source."""
    usable = [c for c in pack["claims"] if c["usableForDraft"]]
    core = " ".join(c["text"] for c in usable[:2])[:400]
    excluded = [{"claimId": c["claimId"], "why": c["status"]} for c in pack["claims"] if not c["usableForDraft"]]
    brief = {"schema": "rafii.brief.v1", "factPackId": pack["id"], "factPackHash": pack["hash"], "goal": goal, "audience": audience,
             "coreMessage": core, "claimIds": [c["claimId"] for c in usable], "cta": cta, "exclusions": excluded + [{"claimId": None, "why": x} for x in exclusions],
             "unknowns": list(pack["unknowns"]), "contradictions": pack["contradictions"]}
    brief["hash"] = _digest(brief)
    return brief


def angles(pack, brief, limit=4):
    """Two to four distinct angles, each tied to specific claims."""
    usable = [c for c in pack["claims"] if c["usableForDraft"]]
    out = []
    first = usable[0] if usable else None
    if first:
        out.append({"id": "an_news", "label": "What happened", "claimIds": [first["claimId"]], "angle": f"State plainly what happened: {first['text'][:120]}"})
    stats = [c for c in usable if c["claimType"] == "statistic"]
    if stats:
        out.append({"id": "an_number", "label": "The number that matters", "claimIds": [stats[0]["claimId"]], "angle": f"Lead with the figure and what it means for {brief['audience'] or 'the audience'}."})
    quotes = [c for c in usable if c["claimType"] == "quote"]
    if quotes:
        out.append({"id": "an_quote", "label": "In their words", "claimIds": [quotes[0]["claimId"]], "angle": "Build around the quote, attributed exactly as given."})
    if usable:
        out.append({"id": "an_why", "label": "Why it matters", "claimIds": [c["claimId"] for c in usable[:3]], "angle": f"Explain why this matters for the goal: {brief['goal'][:120]}"})
    return out[:limit]

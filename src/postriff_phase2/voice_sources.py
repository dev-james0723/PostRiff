"""Explicitly retained writing samples for voice analysis and conditioned drafting.

Imported text is untrusted data. Retention, selection, purpose and route consent are
separate fields, and projections expose only the exact revisions currently allowed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from typing import Any

from postriff_alpha.domain import AlphaError, uid
from .contracts import digest

MAX_RECORDS = 50
MAX_TEXT_CHARS = 8_000
MAX_IMPORT_BYTES = 512 * 1024
MAX_RETRIEVAL_SAMPLES = 6
MAX_RETRIEVAL_CHARS = 12_000
PURPOSES = ("analysis", "generation")
LABELS = ("representative", "outdated", "sponsored", "guest", "ai_generated")
# A writing (generation) grant names one exact writer route, or this class: every model Rafii's managed writer offers
# through the Vercel AI Gateway, now or later. Each draft still records the exact route it used (voiceContext.route) and
# the sample revisions it read (bindings). Analysis always names one exact route.
MANAGED_WRITER_ROUTE = "cloud:vercel-ai-gateway:*"
_CLASS_PREFIXES = {MANAGED_WRITER_ROUTE: MANAGED_WRITER_ROUTE[:-1]}


def route_class(route: str) -> str | None:
    """The class grant that covers this exact writer route, if any."""
    return next((grant for grant, prefix in _CLASS_PREFIXES.items() if isinstance(route, str) and route.startswith(prefix) and len(route) > len(prefix) and not route.endswith("*")), None)


def route_granted(source: dict, purpose: str, route: str) -> bool:
    """Whether this sample may be used for this purpose on this exact writer route: an exact grant, or (writing only)
    the class grant that covers the route."""
    grants = [grant for grant in source.get("useGrants", []) if isinstance(grant, dict) and grant.get("purpose") == purpose]
    if any(grant.get("route") == route for grant in grants):
        return True
    covering = route_class(route) if purpose == "generation" else None
    return covering is not None and any(grant.get("route") == covering for grant in grants)


def _bounded(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AlphaError("Voice sample fields must be text.")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(value) > limit:
        raise AlphaError(f"Each voice sample must be at most {limit} characters.", 413)
    return value


def normalize_import(payload: dict) -> list[dict]:
    """Parse and validate an entire bounded batch before callers mutate workspace state."""
    if not isinstance(payload, dict):
        raise AlphaError("Expected a voice sample import.")
    format_name = payload.get("format", "pasted")
    if format_name == "pasted":
        raw_records = [{key: payload.get(key) for key in ("text", "title", "externalId", "platform", "account", "publishedAt", "language", "label", "partialCoverage")}]
    elif format_name == "json":
        raw_records = payload.get("records")
        if raw_records is None:
            data = payload.get("data", "")
            if not isinstance(data, str) or len(data.encode("utf-8")) > MAX_IMPORT_BYTES:
                raise AlphaError("JSON voice imports must be at most 512 KiB.", 413)
            try:
                raw_records = json.loads(data)
            except (TypeError, json.JSONDecodeError) as error:
                raise AlphaError("Voice sample JSON is invalid.") from error
        if not isinstance(raw_records, list):
            raise AlphaError("Voice sample JSON must contain an array.")
    elif format_name == "csv":
        data = payload.get("data", "")
        if not isinstance(data, str) or len(data.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise AlphaError("CSV voice imports must be at most 512 KiB.", 413)
        try:
            raw_records = list(csv.DictReader(io.StringIO(data)))
        except csv.Error as error:
            raise AlphaError("Voice sample CSV is invalid.") from error
    else:
        raise AlphaError("Choose pasted text, CSV or JSON for voice samples.")

    if not 1 <= len(raw_records) <= MAX_RECORDS:
        raise AlphaError("Import between 1 and 50 voice samples at a time.")

    records = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise AlphaError("Every voice sample must be an object.")
        text = _bounded(raw.get("text"), MAX_TEXT_CHARS)
        if not text:
            raise AlphaError("Every voice sample needs text.")
        label = _bounded(raw.get("label"), 40).lower()
        if label and label not in LABELS:
            raise AlphaError("Choose a supported voice sample label.")
        record = {
            "text": text,
            "title": _bounded(raw.get("title"), 200) or "Writing sample",
            # Only the server's verified social importer can attest official provenance.
            "voiceOrigin": "user_provided",
            "externalId": _bounded(raw.get("externalId"), 300),
            "platform": _bounded(raw.get("platform"), 80),
            "account": _bounded(raw.get("account"), 200),
            "publishedAt": _bounded(raw.get("publishedAt"), 80),
            "language": _bounded(raw.get("language"), 80),
            "label": label or None,
            "partialCoverage": raw.get("partialCoverage") is True,
        }
        record["contentHash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        identity_parts = [record["platform"].casefold(), record["account"].casefold(), record["externalId"]]
        record["importIdentity"] = "external:" + digest(identity_parts) if record["externalId"] else "content:" + record["contentHash"]
        records.append(record)
    return records


def _source(state: dict, source_id: str) -> dict:
    source = next((item for item in state.get("sources", []) if item.get("id") == source_id and item.get("kind") == "voice_sample"), None)
    if source is None:
        raise AlphaError("This voice sample is not available in your workspace.", 404)
    return source


def _remove_evidence_quotes(profile: dict, source_id: str) -> None:
    """Revoking a sample also removes its copied excerpts from retained proposals."""
    for dimension in profile.get('dimensions', []):
        if isinstance(dimension, dict):
            dimension['quotes'] = [quote for quote in dimension.get('quotes', []) if isinstance(quote, dict) and quote.get('sourceId') != source_id]


def apply_action(state: dict, action: str, payload: dict, actor: str, now: float) -> dict:
    state.setdefault("sources", [])
    if action == "voice_samples_import":
        records = normalize_import(payload)
        result = {"imported": [], "unchanged": [], "revised": []}
        by_identity = {item.get("importIdentity"): item for item in state["sources"] if item.get("kind") == "voice_sample" and item.get("active")}
        for record in records:
            existing = by_identity.get(record["importIdentity"])
            if existing and existing.get("contentHash") == record["contentHash"]:
                result["unchanged"].append(existing["id"])
                continue
            if existing:
                revision = int(existing.get("revision") or 1) + 1
                existing.update({**record, "revision": revision, "updatedAt": now, "updatedBy": actor, "selected": False})
                existing.setdefault("revisions", []).append({"revision": revision, "text": record["text"], "contentHash": record["contentHash"], "at": now, "actor": actor})
                existing["purposeGrants"] = []
                existing["routeGrants"] = []
                existing["useGrants"] = []
                result["revised"].append(existing["id"])
                continue
            source_id = uid()
            source = {
                **record,
                "id": source_id,
                "kind": "voice_sample",
                "active": True,
                "selected": False,
                "revision": 1,
                "revisions": [{"revision": 1, "text": record["text"], "contentHash": record["contentHash"], "at": now, "actor": actor}],
                "purposeGrants": [],
                "routeGrants": [],
                "useGrants": [],
                "retainedBy": actor,
                "retainedAt": now,
                "facts": [],
                "visibility": "workspace-private",
                "untrustedData": True,
                "unknowns": ["A writing sample supplies style evidence only; its facts are not approved for a new post."],
            }
            state["sources"].append(source)
            by_identity[record["importIdentity"]] = source
            result["imported"].append(source_id)
        return result

    source = _source(state, payload.get("sourceId"))
    if action == "voice_sample_select":
        if not source.get("active"):
            raise AlphaError("This voice sample was revoked.", 409)
        if type(payload.get("selected")) is not bool:
            raise AlphaError("Choose whether this sample is selected.")
        source["selected"] = payload["selected"]
        source["selectionChangedBy"], source["selectionChangedAt"] = actor, now
        return {"sourceId": source["id"], "selected": source["selected"]}
    if action == "voice_sample_grant":
        grants = payload.get("grants")
        if payload.get("confirmed") is not True:
            raise AlphaError("Confirm the exact voice use and provider routes.")
        if not isinstance(grants, list) or not grants:
            raise AlphaError("Choose the exact purpose and writer route for this voice sample.")
        normalized = []
        for grant in grants:
            if not isinstance(grant, dict) or grant.get("purpose") not in PURPOSES:
                raise AlphaError("Choose analysis or generation for every voice-use grant.")
            route = grant.get("route")
            if not isinstance(route, str) or not route.strip() or len(route) > 120:
                raise AlphaError("Choose the exact writer route for every voice-use grant.")
            if route.strip() in _CLASS_PREFIXES and grant["purpose"] != "generation":
                raise AlphaError("AI analysis needs one exact model; only writing may be allowed for every Rafii AI writer model.")
            normalized.append({"purpose": grant["purpose"], "route": route.strip()})
        source["useGrants"] = sorted({(item["purpose"], item["route"]) for item in normalized})
        source["useGrants"] = [{"purpose": purpose, "route": route} for purpose, route in source["useGrants"]]
        source["purposeGrants"] = sorted({item["purpose"] for item in source["useGrants"]})
        source["routeGrants"] = sorted({item["route"] for item in source["useGrants"]})
        source["grantRevision"] = int(source.get("grantRevision") or 0) + 1
        source["grantedBy"], source["grantedAt"] = actor, now
        return {"sourceId": source["id"], "grants": source["useGrants"], "grantRevision": source["grantRevision"]}
    if action == "voice_sample_exclude":
        source["selected"] = False
        source["excludedBy"], source["excludedAt"] = actor, now
        return {"sourceId": source["id"], "selected": False}
    if action == "voice_sample_revoke":
        if payload.get("confirmed") is not True:
            raise AlphaError("Confirm that this retained voice sample should be revoked.")
        source.update({"active": False, "selected": False, "text": "", "revisions": [], "purposeGrants": [], "routeGrants": [], "useGrants": [], "revokedBy": actor, "revokedAt": now, "cleanupStatus": "complete"})
        for profile in state.get("speaker", {}).get("revisions", []):
            evidence_ids = profile.get("evidenceSourceIds", [])
            if isinstance(profile.get("profile"), dict):
                evidence_ids = profile["profile"].get("evidenceSourceIds", evidence_ids)
            if source["id"] in evidence_ids:
                profile["stale"] = True
                profile["staleReason"] = "supporting_sample_revoked"
                profile['writingExample'] = ''
                if isinstance(profile.get('profile'), dict):
                    profile['profile']['writingExample'] = ''
                    _remove_evidence_quotes(profile['profile'], source['id'])
                _remove_evidence_quotes(profile, source['id'])
        provisional = state.get("speaker", {}).get("provisional")
        if isinstance(provisional, dict) and source["id"] in provisional.get("evidenceSourceIds", []):
            provisional["status"] = "stale"
            provisional["staleReason"] = "supporting_sample_revoked"
            provisional['writingExample'] = ''
            _remove_evidence_quotes(provisional, source['id'])
        for variant in state.get("variants", []):
            if source["id"] in variant.get("sourceIds", []) or source["id"] in variant.get("voiceSourceIds", []):
                variant["blockedByRetraction"] = True
                variant["needsReview"] = True
        return {"sourceId": source["id"], "revoked": True, "cleanupStatus": source["cleanupStatus"]}
    raise AlphaError("Unsupported voice sample action.")


def project(state: dict, source_ids: list[str], purpose: str, route: str) -> dict:
    if purpose not in PURPOSES:
        raise AlphaError("Unsupported voice sample purpose.")
    if not isinstance(route, str) or not route or len(route) > 120 or route in _CLASS_PREFIXES:
        raise AlphaError("Choose an exact writer route.")
    if not isinstance(source_ids, list) or len(source_ids) > MAX_RECORDS or any(not isinstance(source_id, str) for source_id in source_ids) or len(set(source_ids)) != len(source_ids):
        raise AlphaError("Select at most 50 distinct voice samples.")
    samples, excluded = [], []
    for source_id in source_ids:
        source = _source(state, source_id)
        reason = None
        if not source.get("active"):
            reason = "revoked"
        elif not source.get("selected"):
            reason = "not_selected"
        elif purpose not in source.get("purposeGrants", []):
            reason = "purpose_not_granted"
        elif not route_granted(source, purpose, route):
            reason = "route_not_granted"
        if reason:
            excluded.append({"id": source_id, "revision": source.get("revision"), "reason": reason})
            continue
        samples.append({
            "id": source["id"], "revision": source["revision"], "text": source["text"], "contentHash": source["contentHash"],
            "platform": source.get("platform"), "language": source.get("language"), "label": source.get("label"), "untrustedData": True,
        })
    binding = [{"id": item["id"], "revision": item["revision"], "contentHash": item["contentHash"]} for item in samples]
    return {"schema": "postriff.voice-context.v1", "purpose": purpose, "route": route, "samples": samples, "excluded": excluded, "digest": digest(binding)}


def retrieve(
    state: dict,
    source_ids: list[str],
    purpose: str,
    route: str,
    query: str = "",
    limit: int = MAX_RETRIEVAL_SAMPLES,
    max_chars: int = MAX_RETRIEVAL_CHARS,
) -> dict:
    """Return the most relevant consented samples within hard count/character bounds."""
    if type(limit) is not int or not 1 <= limit <= MAX_RETRIEVAL_SAMPLES:
        raise AlphaError(f"Retrieve between 1 and {MAX_RETRIEVAL_SAMPLES} voice samples.")
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_RETRIEVAL_CHARS:
        raise AlphaError(f"Voice context must be between 1 and {MAX_RETRIEVAL_CHARS} characters.")
    projection = project(state, source_ids, purpose, route)
    terms = {token.casefold() for token in re.findall(r"[\w\u3400-\u9fff]+", query) if len(token) > 1}

    def rank(sample: dict) -> tuple[int, int, str]:
        haystack = " ".join(str(sample.get(key) or "") for key in ("text", "platform", "language", "label")).casefold()
        return (-sum(term in haystack for term in terms), -int(sample.get("revision") or 0), sample["id"])

    selected, used = [], 0
    for sample in sorted(projection["samples"], key=rank):
        remaining = max_chars - used
        if remaining <= 0 or len(selected) >= limit:
            break
        text = sample["text"][:remaining]
        if not text:
            break
        selected.append({**sample, "text": text, "truncated": len(text) < len(sample["text"])})
        used += len(text)
    bindings = [{"id": item["id"], "revision": item["revision"], "contentHash": item["contentHash"]} for item in selected]
    return {**projection, "samples": selected, "bindings": bindings, "digest": digest(bindings), "retrievedChars": used}


def bounded_style_directives(value) -> dict:
    """Only formatting booleans may cross the writer boundary; never sample prose."""
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ("shortOpenings", "shortParagraphs", "usesEmoji", "usesHashtags")
            if type(value.get(key)) is bool}


def style_directives(projection: dict) -> dict:
    """Extract formatting signals only; sample words and claims never become draft material."""
    texts = [item.get("text", "") for item in projection.get("samples", [])]
    lines = [line.strip() for text in texts for line in text.splitlines() if line.strip()]
    openings = [next((line.strip() for line in text.splitlines() if line.strip()), "") for text in texts]
    return {
        "shortOpenings": bool(openings) and sum(len(line) <= 45 for line in openings) * 2 >= len(openings),
        "usesEmoji": any(re.search(r"[\U0001F300-\U0001FAFF]", text) for text in texts),
        "usesHashtags": any(re.search(r"(?:^|\s)#[\w\u3400-\u9fff]+", text) for text in texts),
        "shortParagraphs": bool(lines) and sum(len(line) <= 120 for line in lines) * 2 >= len(lines),
    }


def validate_bindings(state: dict, voice_context: dict) -> None:
    """Reject a candidate when retained evidence or exact consent changed after drafting."""
    if not voice_context or voice_context.get("mode") == "neutral":
        return
    current = project(
        state,
        [item["id"] for item in voice_context.get("bindings", [])],
        "generation",
        voice_context.get("route", ""),
    )
    current_bindings = [{"id": item["id"], "revision": item["revision"], "contentHash": item["contentHash"]} for item in current["samples"]]
    if current["excluded"] or current_bindings != voice_context.get("bindings"):
        raise AlphaError("Voice samples or their consent changed. Preserve the candidate and draft again with current evidence.", 409)

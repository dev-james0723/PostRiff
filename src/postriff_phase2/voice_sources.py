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
import unicodedata
from typing import Any

from postriff_alpha.domain import AlphaError, uid
from .contracts import digest

MAX_RECORDS = 50
MAX_TEXT_CHARS = 8_000
MAX_IMPORT_BYTES = 512 * 1024
MAX_RETRIEVAL_SAMPLES = 6
MAX_RETRIEVAL_CHARS = 12_000
# "generation" lets a writer use a sample's style signals only (counts, form, what repeats): no prose leaves.
# "examples" is a separate, narrower permission: this exact writer may also read the sample's own text as a style
# example. It is never implied by "generation", never covered by a class grant, and bounded below.
PURPOSES = ("analysis", "generation", "examples")
MAX_EXAMPLE_SAMPLES = 3
MAX_EXAMPLE_CHARS = 1_500
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
            if route.strip() in _CLASS_PREFIXES and grant["purpose"] == "examples":
                raise AlphaError("A style example needs one exact writer; only the style permission may cover every Rafii AI writer model.")
            if route.strip() in _CLASS_PREFIXES and grant["purpose"] != "generation":
                raise AlphaError("AI analysis needs one exact model; only writing may be allowed for every Rafii AI writer model.")
            normalized.append({"purpose": grant["purpose"], "route": route.strip()})
        if not source.get("active"):
            raise AlphaError("A revoked sample cannot receive new grants. Retain a new sample with explicit consent.", 409)
        # An example permission exists only beside the style permission for that same exact writer. One left behind
        # when that style permission goes is dropped here, so a wider style permission can never revive it.
        styled = {item["route"] for item in normalized if item["purpose"] == "generation"}
        normalized = [item for item in normalized if item["purpose"] != "examples" or item["route"] in styled]
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
                profile.setdefault("redactions", []).append({"sourceId": source["id"], "at": now, "reason": "supporting_sample_revoked", "priorProfileDigest": digest(profile.get("profile", profile))})
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
        state.get("speaker", {}).pop("brandBrainPreview", None)
        state.get("speaker", {}).pop("analysisQuote", None)
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


_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff]")
# Only text that plainly addresses a model: an order to drop its instructions (all of them, "your", the previous or
# above ones), a request for the system prompt, or markup posing as a section of the request. "Forget the rules,
# just play" is a sentence, not an attack.
_OVERRIDE = re.compile(r"(?:ignore|disregard|forget|override)\s+(?P<all>(?:all|any)\s+)?(?:of\s+)?(?:(?P<whose>your)\s+|the\s+)?(?P<before>(?:previous|prior|above|earlier|system)\s+)?"
                       r"(?:instructions?|rules?|prompts?)(?P<after>\s+(?:above|before|earlier|so far))?", re.I)
_POSING = re.compile(r"<\s*/?\s*(?:system|assistant|voicesamples)\b|\[INST\]|(?:reveal|show|print|output)\s+(?:the\s+|your\s+)?(?:system\s+)?prompt"
                     r"|(?:忽略|無視|无视|不要理會|不要理会|唔好理)[^。\n]{0,12}(?:指示|指令|規則|规则|提示)", re.I)
_CJK_CHAR = "\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af"
_COPY_TOKEN = re.compile(f"[{_CJK_CHAR}]|[^\\W_{_CJK_CHAR}]+")
_TAG = re.compile(r"(?<![\w#])#[\w\u3400-\u9fff]+")
# What can carry a fact out of a sample: a link or bare domain, a handle, a price or percentage, a longer number.
# ASCII classes and bounded repeats, so neighbouring Chinese text is not swallowed and long input stays linear.
_LINK = re.compile(r"(?:https?://)?(?:www\.)?(?P<host>[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63}){0,8}\.[a-z]{2,24})(?P<path>/[A-Za-z0-9._~%&=+/-]{0,200})?", re.I)
_HANDLE = re.compile(r"(?<![A-Za-z0-9_.])@[A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?")
_NUMBER = re.compile(r"(?<![A-Za-z0-9#_])(?P<sign>(?:HK|US)?[$€£¥]\s?)?(?P<digits>\d{1,12}(?:[ ,.\-]\d{1,12}){0,6})(?P<percent>\s?%)?(?![A-Za-z0-9_])")
COPIED_WORDS = 8


def reads_like_instruction(text: str) -> bool:
    """A sample that addresses a model rather than a reader is never sent as an example. A pattern list cannot catch
    every phrasing; the structured data field, the writer's rule and the check on the finished draft are the rest."""
    text = unicodedata.normalize("NFKC", _ZERO_WIDTH.sub("", text or ""))
    return bool(_POSING.search(text)) or any(found["all"] or found["whose"] or found["before"] or found["after"] for found in _OVERRIDE.finditer(text))


def example_granted(source: dict, route: str) -> bool:
    """This exact writer holds both the style permission and the example permission for the sample. A class grant
    ("any Rafii AI writer model") never counts for examples, in either half."""
    grants = {(grant.get("purpose"), grant.get("route")) for grant in source.get("useGrants", []) if isinstance(grant, dict)}
    return bool(route) and ("examples", route) in grants and ("generation", route) in grants


def _fact_tokens(text: str) -> set[str]:
    """Links (with and without their path), handles, prices, percentages and numbers of three or more digits, each
    in one normal form so `https://www.site.com/a/`, `site.com/a` and `９１２３ ４５６７`, `91234567` compare equal.
    A bare year is not a fact worth a warning."""
    text = unicodedata.normalize("NFKC", text or "")
    tokens = set()
    for found in _LINK.finditer(text):
        host = found["host"].casefold()
        tokens.add(host)
        if found["path"] and found["path"].strip("/"):
            tokens.add(host + "/" + found["path"].strip("/").rstrip(".,;:!?)").casefold())
    text = _LINK.sub(" ", text)
    tokens.update(found.group().casefold() for found in _HANDLE.finditer(text))
    for found in _NUMBER.finditer(_HANDLE.sub(" ", text)):
        digits = re.sub(r"\D", "", found["digits"])
        priced = bool(found["sign"] or found["percent"])
        if (priced and len(digits) >= 2) or (len(digits) >= 3 and not (len(digits) == 4 and digits[:2] in ("19", "20") and not priced)):
            tokens.add(("%" if found["percent"] else "$" if found["sign"] else "#") + digits)
    return tokens


def copied_from_examples(text: str, samples: list[str], supplied: str) -> list[str]:
    """Reminders for a draft that took wording or a fact from a style example instead of only its form.

    Flags a run of wording shared with one sample (eight words, or twelve characters where the text has no spaces,
    as in Chinese and Japanese) and a link, handle, price, percentage or longer number that is in a sample and in
    the draft but not in what the person supplied for this post. Tags, and wording that recurs across two or more
    of the examples (a sign-off), are the person's house form and are never flagged."""
    def runs(value):
        """Runs of wording within one line: a sign-off is its own line, and a run never joins it to its neighbours."""
        found = set()
        for line in _TAG.sub(" ", (value or "").casefold()).splitlines():
            sequence = _COPY_TOKEN.findall(line)
            for size, least in ((COPIED_WORDS, 24), (12, 0)):   # eight tokens that are real words, or any twelve tokens
                for index in range(len(sequence) - size + 1):
                    window = sequence[index:index + size]
                    if sum(len(token) for token in window) >= least:
                        found.add(" ".join(window))
        return found

    samples = [sample[:MAX_EXAMPLE_CHARS] for sample in samples]   # only what was sent can have been copied
    per_sample = [runs(sample) for sample in samples]
    house = {run for index, found in enumerate(per_sample) for run in found if any(run in other for other in per_sample[:index] + per_sample[index + 1:])}
    draft, given = runs(text), runs(supplied)
    shared = sorted((draft & set().union(*per_sample)) - given - house, key=len, reverse=True) if per_sample else []
    notes = []
    if shared:
        notes.append(f"This draft repeats wording from one of your style examples (“{shared[0][:80]}…”). Examples are for style only: rewrite it, or keep it if the words are yours to reuse.")
    lifted = sorted((_fact_tokens(text) & set().union(*[_fact_tokens(sample) for sample in samples])) - _fact_tokens(supplied)) if samples else []
    if lifted:
        notes.append(f"This draft contains {', '.join(token.lstrip('#$%') for token in lifted[:3])}, which appears in a style example but not in what you supplied for this post. Check it before publishing.")
    return notes


def style_examples(state: dict, projection: dict) -> list[dict]:
    """The retrieved samples this exact writer may also read as style examples, most relevant first.

    A sample qualifies only with its own "examples" permission for the projection's route, on top of the writing
    permission that put it in the projection. At most three, each cut to a fixed length; a sample that reads like an
    instruction to a model is left out. Callers record the returned bindings on the run."""
    route = projection.get("route")
    examples = []
    for sample in projection.get("samples", []):
        source = _source(state, sample["id"])
        if not example_granted(source, route) or reads_like_instruction(sample.get("text") or ""):
            continue
        text = sample["text"][:MAX_EXAMPLE_CHARS]
        examples.append({"id": sample["id"], "revision": sample["revision"], "contentHash": sample["contentHash"], "platform": sample.get("platform"),
                         "language": sample.get("language"), "text": text, "truncated": len(text) < len(source.get("text") or "")})
        if len(examples) >= MAX_EXAMPLE_SAMPLES:
            break
    return examples


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
    # A draft that read a sample's own text is only kept while that exact permission and that exact text still stand.
    for example in voice_context.get("examples") or []:
        source = next((item for item in state.get("sources", []) if item.get("id") == example.get("id") and item.get("kind") == "voice_sample"), None)
        if (source is None or not source.get("active") or not source.get("selected") or source.get("revision") != example.get("revision")
                or source.get("contentHash") != example.get("contentHash") or not example_granted(source, voice_context.get("route", ""))):
            raise AlphaError("Voice samples or their consent changed. Preserve the candidate and draft again with current evidence.", 409)

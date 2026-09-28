"""Authenticated, stored-only trend projections and existing-workflow handoffs.

No provider/model/worker dispatch is reachable from a read. TrendStore owns policy,
dependency and entitlement checks, including for historical pagination cutoffs.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import math
import re
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from ...permissions import require
from . import config, contracts, opportunities, relevance, exposure_events

PLATFORMS = ("bluesky", "reddit", "youtube", "x", "threads", "instagram", "tiktok", "linkedin", "facebook", "pinterest", "web")
FILTER_KEYS = {"query", "platforms", "stages", "languages", "regions", "niches", "since", "until", "limit", "cursor", "method_bundle", "view", "platform", "language", "niche", "pool"}
DEAD = {"inputs_expired", "inputs_deleted", "policy_revoked"}
KINDS = {"methodology": "methodology", "calibration": "calibration", "language-patterns": "language_pattern",
         "genome": "genome", "propagation": "graph", "saturation": "saturation", "forecast": "forecast", "whitespace": "whitespace", "lab": "lab_run"}
FEATURES = {"calibration": "CALIBRATION", "language-patterns": "MODEL_ENRICHMENT", "genome": "GRAPH_GENOME",
            "propagation": "GRAPH_GENOME", "saturation": "SATURATION", "forecast": "FORECASTS", "whitespace": "WHITESPACE", "lab": "OPPORTUNITY_LAB"}


def error(code, status):
    messages = {"invalid_request": "The request contains an invalid field.", "unauthenticated": "Sign in to continue.",
                "forbidden": "This feature or action is not available to this workspace member.", "not_found": "Record unavailable.",
                "evidence_unavailable": "The retained evidence is no longer available under current permissions or retention.",
                "revision_conflict": "The record or workspace context changed. Review the current version.",
                "source_unavailable": "Stored trend data is currently unavailable.", "budget_or_rate_limited": "The operation is temporarily limited."}
    return AlphaError(messages[code], status, code=code)


def ident(value):
    try:
        return contracts.uuid(value)
    except ValueError:
        raise error("invalid_request", 400) from None


def coverage(value=None, scope="unknown"):
    value = value if isinstance(value, dict) else {}
    return {"availability": value.get("availability", "unavailable"), "representation": value.get("representation", "sampled_posts"),
            "completeness": value.get("completeness", "unknown"), "breadth": value.get("breadth", "unknown"),
            "scope_ref": value.get("scope_ref", scope), "coverage_epoch": value.get("coverage_epoch", "unknown"),
            "scope": value.get("scope", scope), "latest_successful_read": value.get("latest_successful_read"),
            "freshness_deadline": value.get("freshness_deadline"), "sources": copy.deepcopy(value.get("sources", []))}


def envelope(data, at, *, cov=None, limitations=(), execution_state="stored_result", next_cursor=None):
    return {"schema_version": "1.0", "request_id": str(uuid.uuid4()), "as_of": opportunities.iso(at), "data": data,
            "coverage": coverage(cov), "limitations": list(limitations), "execution_state": execution_state, "next_cursor": next_cursor}


def filters(raw, as_of):
    # All snapshot bounds share PostgreSQL/ISO microsecond precision. Comparing
    # a rounded ISO endpoint with an unrounded float can reject an empty query.
    as_of = opportunities.epoch(opportunities.iso(as_of))
    if not isinstance(raw, dict) or set(raw) - FILTER_KEYS:
        raise error("invalid_request", 400)
    raw = dict(raw)
    for singular, plural in (("platform", "platforms"), ("language", "languages"), ("niche", "niches")):
        if singular in raw:
            if plural in raw:
                raise error("invalid_request", 400)
            raw[plural] = raw.pop(singular)
    view = raw.get("view", "for_you")
    if view not in ("for_you", "rising", "breaking", "hot", "niche", "platforms"):
        raise error("invalid_request", 400)
    if view in contracts.STAGES:
        raw["stages"] = [view]
    out = {"view": view}
    if 'pool' in raw:
        if raw['pool'] not in ('home', 'weekly') or raw.get('cursor'):
            raise error('invalid_request', 400)
        out['pool'] = raw['pool']
    for field, choices in (("platforms", PLATFORMS), ("stages", contracts.STAGES), ("languages", contracts.LANGUAGES)):
        value = raw.get(field, [])
        if isinstance(value, str):
            value = value.split(",") if value else []
        if not isinstance(value, list) or len(value) > 12 or any(v not in choices for v in value):
            raise error("invalid_request", 400)
        out[field] = sorted(set(value))
    for field, size in (("regions", 12), ("niches", 120)):
        value = raw.get(field, [])
        if isinstance(value, str):
            value = value.split(",") if value else []
        if not isinstance(value, list) or len(value) > 8 or any(not isinstance(v, str) or not 1 <= len(v) <= size for v in value):
            raise error("invalid_request", 400)
        if field == "regions" and any(not re.fullmatch(r"[A-Z]{2}|global|unknown", v) for v in value):
            raise error("invalid_request", 400)
        out[field] = sorted(set(value))
    query = raw.get("query", "")
    if not isinstance(query, str) or len(query) > 200:
        raise error("invalid_request", 400)
    out["query"] = " ".join(query.split())
    limit = raw.get("limit", 3 if 'pool' in raw else 20)
    if isinstance(limit, str) and limit.isdecimal():
        limit = int(limit)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise error("invalid_request", 400)
    out["limit"] = limit
    if 'pool' in raw and limit > 3:
        raise error('invalid_request', 400)
    try:
        for key in ("since", "until"):
            if key in raw:
                contracts.instant(raw[key])
        out["since"] = opportunities.iso(raw.get("since", as_of - 7 * 86400))
        out["until"] = opportunities.iso(raw.get("until", as_of))
        if not as_of - 366 * 86400 <= opportunities.epoch(out["since"]) < opportunities.epoch(out["until"]) <= as_of:
            raise ValueError()
    except (ValueError, TypeError):
        raise error("invalid_request", 400) from None
    bundle = raw.get("method_bundle", "stored-at-cutoff.v1")
    if not isinstance(bundle, str) or not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", bundle):
        raise error("invalid_request", 400)
    if bundle != "stored-at-cutoff.v1" and bundle.count("@") != 1:
        raise error("invalid_request", 400)
    out["method_bundle"] = bundle
    return out


def _metrics(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, item in list(value.items())[:40]:
        if not isinstance(item, dict) or not all(k in item for k in ("value", "unit", "definition_id", "definition_version", "window", "null_reason")):
            continue
        number = item["value"]
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)):
            continue
        if number is None and not item["null_reason"]:
            continue
        try:
            start, end = (contracts.instant(item["window"][k]) for k in ("start", "end"))
            if start >= end:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        result[name] = {k: copy.deepcopy(item.get(k)) for k in ("value", "unit", "definition_id", "definition_version", "window", "baseline_ref", "denominator", "null_reason")}
    return result


def build_trend_payload(receipt, *, trend_id, episode_id, scope_key, evidence, canonical_topic, expires_at, method_bundle):
    """Pure v2 receipt -> stored wire projection. No verification or promotion.

    Pipeline persists the raw receipt separately and attaches its durable UUID as
    projection.receipt_id. The service reads verification only from TrendStore.
    """
    from .methods import metric_definitions
    ident(trend_id)
    ident(episode_id)
    contracts.scope(scope_key)
    contracts.instant(expires_at)
    calculated = receipt.get("calculated") or {}
    window = calculated.get("current_window")
    if not isinstance(window, dict) or contracts.instant(window["start"]) >= contracts.instant(window["end"]):
        raise ValueError("receipt_metric_window_required")
    definitions = metric_definitions()

    def metric(name, raw, observed=False):
        value = raw.get("value")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value)):
            raise ValueError("finite_metric_required")
        definition = definitions.get(name, {})
        return {"value": value, "unit": raw.get("unit", "count"), "definition_id": name,
                "definition_version": definition.get("version", "observed-components.v1" if observed else str(method_bundle["version"])),
                "window": copy.deepcopy(window), "baseline_ref": None if observed else calculated.get("baseline_id"),
                "denominator": str(raw["denominator"]) if raw.get("denominator") is not None else None,
                "null_reason": str(raw.get("reason") or "not_observed") if value is None else None}

    observed = {}
    # Counts/components remain observations. Exclusions maps and labels are not
    # accidentally coerced into measured numbers.
    for name, value in (receipt.get("observed") or {}).items():
        if value is None or type(value) in (int, float):
            observed[name] = metric(name, {"value": value, "unit": "fraction" if "fraction" in name or "share" in name else "count"}, True)
    metrics = {name: metric(name, value) for name, value in calculated.items() if isinstance(value, dict) and "value" in value and "unit" in value}
    rate = metrics.get("mention_rate")
    cov = coverage(receipt.get("coverage"), scope_key)
    # A calculation time is not a successful provider read: freshness remains
    # unknown unless the worker provides an actual source-health timestamp.
    inferred = {"stage": None, "data_state": "provisional", "explanation": "Candidate method; public lifecycle claims have not qualified.",
                "confidence": "unknown", "calibration_state": "insufficient", "evidence_refs": list(receipt.get("snapshot_refs", []))}
    return {"id": trend_id, "episode_id": episode_id, "canonical_topic": str(canonical_topic)[:300],
            "observed": {"summary": "Stored observations within the declared collection scope.", "first_detected": None,
                         "latest_observed": None, "metrics": observed, "timeline": [{"at": window["end"], "value": rate["value"],
                            "unit": rate["unit"], "state": "complete" if rate["value"] is not None else "gap", "reason": rate["null_reason"]}] if rate else []},
            "calculated": metrics, "inferred": inferred, "interpretation": None, "unverified_claims": [],
            "coverage": cov, "limitations": list(receipt.get("limitations", [])), "verification_state": "pending",
            "expires_at": expires_at, "platform_states": [], "evidence": copy.deepcopy(evidence[:20]), "workspace_fit": None,
            "cohort_qualified": False, "method_state": "shadow", "recipe_digest": contracts.digest(receipt),
            "raw_receipt_id": receipt.get("receipt_id")}


def build_receipt_payload(receipt, *, trend_id, method_bundle):
    """Storage receipt adapter; preserve canonical replay identity separately."""
    ident(trend_id)
    from .methods import metric_definitions
    return {"trend_id": trend_id, "recipe_digest": contracts.digest(receipt), "raw_receipt_id": receipt.get("receipt_id"),
            "method": {"id": str(method_bundle["method_id"]), "version": str(method_bundle["version"]),
                       "formula": "; ".join(name + " = " + value["formula"] for name, value in metric_definitions().items()),
                       "calibration_cohort": receipt.get("calibration_ref"), "snapshot_refs": list(receipt.get("snapshot_refs", []))},
            "receipt": copy.deepcopy(receipt)}


def project_advanced(resource, payload):
    fields = {
        "methodology": ("method_id", "version", "summary", "definitions", "blind_spots"),
        "calibration": ("state", "cohort", "evaluated", "unknown_outcomes", "metrics", "limitations"),
        "language-patterns": ("id", "expression", "language", "context", "meaning", "uncertainty", "evidence"),
        "genome": ("version", "dimensions", "narrative_variants"),
        "propagation": ("version", "scope", "nodes", "edges", "truncated"),
        "saturation": ("dimensions",),
        "whitespace": ("schema_version", "state", "workspace_id", "trend_id", "trust_receipt_id", "context_digest",
            "facts_digest", "opportunities", "opportunity_refs", "rejected", "gaps", "claim_scope",
            "semantic_qualification", "expires_at", "truncated", "limitations", "source_decision_cutoff", "computed_at"),
        "lab": ("id", "state", "draft_id", "draft_revision", "opportunity_id", "opportunity_revision", "context_revision", "trust_receipt_id", "expires_at", "failure_reason", "diagnostics"),
    }
    required = fields.get(resource)
    if required is None or not isinstance(payload, dict) or any(k not in payload for k in required):
        raise error("source_unavailable", 503)
    data = {k: copy.deepcopy(payload[k]) for k in required}
    if resource == "language-patterns":
        # Language/cultural analysis remains empirically gated. A stored model
        # narrative cannot qualify itself merely by being present.
        if payload.get("empirically_qualified") is not True and payload.get('derivation_kind') != 'deterministic_extraction':
            raise error("source_unavailable", 503)
        data["evidence"] = [{"id": e["id"], "display_state": "restricted", "reason": "Read the current trend receipt for permitted evidence."} for e in data["evidence"]]
    return data


class TrendService:
    def __init__(self, coworker, *, store_factory=None, cursor_secret=None, jobs_factory=None, platform_states_reader=None):
        self.coworker = coworker
        self.hosted = coworker.hosted
        self.repository = coworker.repository
        self.clock = coworker.clock
        self.values = coworker.values
        self.store_factory = store_factory
        self.jobs_factory = jobs_factory
        self.platform_states_reader = platform_states_reader
        secret = cursor_secret or self.values.get("RAFII_TREND_CURSOR_SIGNING_KEY")
        self.cursor_secret = secret.encode() if isinstance(secret, str) else secret

    def _enabled(self, name):
        return config.enabled(name, self.values)

    @contextmanager
    def transaction(self, workspace_id, token, requirement="read"):
        workspace_id = ident(workspace_id)
        if not token:
            raise error("unauthenticated", 401)
        if str(token).startswith("prt_"):
            raise error("forbidden", 403)
        entered = False
        try:
            with self.repository.transaction(token, workspace_id) as (cur, row, actor):
                entered = True
                require(self.hosted.ideas._member(row), requirement)
                if not config.workspace_allowed(workspace_id, self.values):
                    raise error("forbidden", 403)
                # Disabled deployments never construct a store or query an unapplied migration.
                factory = self.store_factory
                if factory is None:
                    from .store import TrendStore
                    factory = TrendStore
                store = factory(self.hosted.connection_factory)
                scopes = store.authorized_scopes(workspace_id, actor, cursor=cur)
                yield store, cur, row, actor, self.hosted.ideas._state(row), scopes
        except AlphaError as exc:
            if not entered:
                raise error("unauthenticated" if exc.status == 401 else "not_found", 401 if exc.status == 401 else 404) from None
            if exc.status == 403:
                raise error("forbidden", 403) from None
            raise
        except (ImportError, AttributeError) as exc:
            raise error("source_unavailable", 503) from exc
        except contracts.ContractError as exc:
            code = str(getattr(exc, "code", ""))
            if code in ("idempotency_conflict", "revision_conflict", "watch_revision_conflict", "job_idempotency_conflict", "projection_revision_conflict"):
                raise error("revision_conflict", 409) from None
            if code in ("opportunity_unavailable", "projection_unavailable"):
                raise error("evidence_unavailable", 410) from None
            raise error("source_unavailable", 503) from None
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in ("42P01", "42703", "08006", "08003", "57P01"):
                raise error("source_unavailable", 503) from None
            raise

    def _cursor(self, body):
        if not isinstance(self.cursor_secret, bytes) or len(self.cursor_secret) < 32:
            raise error("source_unavailable", 503)
        payload = contracts.canonical(body).encode()
        signature = hmac.new(self.cursor_secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def _decode(self, cursor):
        if not isinstance(cursor, str) or len(cursor) > 4096 or not self.cursor_secret:
            raise error("invalid_request", 400)
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.new(self.cursor_secret, payload, hashlib.sha256).digest()):
                raise ValueError()
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError, UnicodeError):
            raise error("invalid_request", 400) from None

    @staticmethod
    def _current(row, now):
        if row is None:
            raise error("not_found", 404)
        state = row.get("verification_state", "pending")
        if row.get("validity") != "valid" or state in DEAD or row.get("revoked_at") is not None:
            raise error("evidence_unavailable", 410)
        try:
            if opportunities.epoch(row["expires_at"]) <= now:
                raise error("evidence_unavailable", 410)
        except (KeyError, ValueError, TypeError):
            raise error("evidence_unavailable", 410) from None
        if not isinstance(row.get("payload"), dict):
            raise error("source_unavailable", 503)
        return row

    def _get(self, store, cur, workspace_id, actor, kind, object_id, now, revision=None):
        row = store.get_projection(workspace_id, actor, kind, ident(object_id), revision=revision, cursor=cur)
        return self._current(row, now)

    def _inference(self, value, verification, qualified=False, method_state=None):
        value = value if isinstance(value, dict) else {}
        allowed = config.stage_allowed(verification_state=verification, cohort_qualified=qualified,
                                       method_state=method_state, values=self.values)
        return {"stage": value.get("stage") if allowed and value.get("stage") in contracts.STAGES else None,
                "data_state": value.get("data_state", "qualified") if allowed else "collecting",
                "explanation": value.get("explanation", "Current evidence does not qualify a lifecycle claim.") if allowed else "Lifecycle claims are unavailable until receipt, method and cohort qualification pass.",
                "confidence": value.get("confidence", "unknown") if allowed else "unknown",
                "calibration_state": "qualified" if allowed else "insufficient", "evidence_refs": list(value.get("evidence_refs", [])) if allowed else []}

    def _trend(self, store, cur, workspace_id, actor, row, now, *, model_visible=False, compose_related=False, as_of=None):
        self._current(row, now)
        if model_visible and row.get("policy", {}).get("llm_process") is not True:
            raise error("forbidden", 403)
        p = row["payload"]
        receipt_id = row.get("receipt_id") or p.get("trust_receipt_id")
        verification = "pending"
        receipt = None
        if receipt_id and self._enabled("TRUST_RECEIPTS"):
            receipt = self._get(store, cur, workspace_id, actor, "receipt", receipt_id, now)
            verification = receipt.get("verification_state", "pending")
            if model_visible and receipt.get("policy", {}).get("llm_process") is not True:
                raise error("forbidden", 403)
            if receipt["payload"].get("trend_id") != row["object_id"]:
                raise error("evidence_unavailable", 410)
        verified = verification == "verified"
        observed = p.get("observed") or {}
        cov = coverage(p.get("coverage"), row["scope_key"])
        result = {"id": row["object_id"], "canonical_topic": str(p.get("canonical_topic", ""))[:300],
                  "observed": {"summary": str(observed.get("summary", "Stored observations within the declared source scope."))[:1200],
                               "first_detected": observed.get("first_detected"), "latest_observed": observed.get("latest_observed"),
                               "metrics": _metrics(observed.get("metrics")), "timeline": copy.deepcopy(observed.get("timeline", []))[:200]},
                  "calculated": _metrics(p.get("calculated")) if verified else {},
                  "inferred": self._inference(p.get("inferred"), verification, p.get("cohort_qualified") is True, p.get("method_state")),
                  "interpretation": copy.deepcopy(p.get("interpretation")) if self._enabled("MODEL_ENRICHMENT") and p.get("interpretation_qualified") is True else None,
                  "unverified_claims": list(p.get("unverified_claims", []))[:20], "coverage": cov,
                  "limitations": list(p.get("limitations", []))[:30], "trust_receipt_id": receipt_id if receipt else None,
                  "verification_state": verification, "expires_at": opportunities.iso(min(opportunities.epoch(row["expires_at"]), opportunities.epoch(receipt["expires_at"]) if receipt else opportunities.epoch(row["expires_at"]))),
                  "platform_states": [], "evidence": [], "workspace_fit": None}
        for platform in p.get("platform_states", [])[:12]:
            result["platform_states"].append({"platform": platform["platform"], "coverage": coverage(platform.get("coverage"), row["scope_key"]),
                "inferred": self._inference(platform.get("inferred"), verification, platform.get("cohort_qualified") is True, platform.get("method_state"))})
        # The store rechecks dependency rights. Independent excerpt/link grants are
        # checked again here; denied content is absent, not merely hidden in the UI.
        at = opportunities.iso(now)
        for item in p.get("evidence", [])[:20]:
            item_scope = item.get("scope_key", row["scope_key"])
            rights = item.get("rights") or {}
            text_ok = row.get("policy", {}).get("display_excerpt") is True and contracts.permits(rights, "display_excerpt", item_scope, at)
            link_ok = row.get("policy", {}).get("display_link") is True and contracts.permits(rights, "display_link", item_scope, at)
            try:
                fresh = opportunities.epoch(item["expires_at"]) > now
            except (KeyError, ValueError, TypeError):
                fresh = False
            if not fresh or not (text_ok or link_ok):
                result["evidence"].append({"id": item["id"], "display_state": "expired" if not fresh else "aggregate_only", "reason": "Representative evidence is unavailable under current display rights."})
                continue
            result["evidence"].append({"id": item["id"], "display_state": "displayable", "platform": item.get("platform", "unknown"),
                "language": item.get("language", "und"), "excerpt": str(item.get("excerpt", ""))[:800] if text_ok else None,
                "url": item.get("url") if link_ok and isinstance(item.get("url"), str) and urlsplit(item["url"]).scheme == "https" and urlsplit(item["url"]).hostname and not urlsplit(item["url"]).username else None,
                "observed_at": item["observed_at"], "expires_at": opportunities.iso(item["expires_at"]),
                "policy_ref": rights["display_excerpt" if text_ok else "display_link"]["policy_ref"]})
        if compose_related and verified and not model_visible:
            from .platform_states import related_platform_states
            reader = self.platform_states_reader or related_platform_states
            try:
                related = reader(store, workspace_id=workspace_id, actor_id=actor, trend_id=row["object_id"],
                                 as_of=opportunities.iso(now if as_of is None else as_of), cursor=cur, limit=20)
                snapshots = related.get("snapshots", [])
                primary = next((r for r in snapshots if r.get("trend_id") == row["object_id"]), None)
                if snapshots and (primary is None or primary.get("trust_receipt_id") != receipt_id):
                    raise error("source_unavailable", 503)
                refs = {r["platform"]: r for r in snapshots}
                seen = {p["platform"] for p in result["platform_states"]}
                for platform in related.get("platform_states", [])[:12]:
                    name = platform["platform"]; ref = refs.get(name)
                    if name in seen or not ref or len(result["platform_states"]) >= 12:
                        continue
                    result["platform_states"].append({"platform": name,
                        "coverage": coverage(platform.get("coverage"), ref["scope_key"]),
                        "inferred": self._inference(platform.get("inferred"), ref.get("verification_state"),
                            ref.get("cohort_qualified") is True, ref.get("method_state"))})
                    seen.add(name)
                if snapshots:
                    result["expires_at"] = opportunities.iso(min(opportunities.epoch(result["expires_at"]), opportunities.epoch(related["expires_at"])))
                    result["limitations"] = list(dict.fromkeys(result["limitations"] + related.get("limitations", [])))[:60]
            except (contracts.ContractError, KeyError, TypeError, ValueError) as exc:
                if getattr(exc, "code", None) in {"platform_primary_unavailable", "platform_receipt_unavailable"}:
                    raise error("evidence_unavailable", 410) from None
                result["limitations"].append("Related platform snapshots are unavailable under current evidence or bindings.")
        return result

    def list(self, workspace_id, token, query=None, *, kind="trend", model_visible=False):
        query = query or {}
        now = opportunities.epoch(opportunities.iso(self.clock()))
        with self.transaction(workspace_id, token) as (store, cur, _row, actor, state, scopes):
            if not self._enabled("RADAR"):
                raise error("forbidden", 403)
            saved = self._decode(query["cursor"]) if query.get("cursor") else None
            as_of = saved.get("as_of") if saved else now
            if isinstance(as_of, bool) or not isinstance(as_of, (int, float)) or not now - 86400 <= as_of <= now:
                raise error("invalid_request", 400)
            selected = filters(query, as_of)
            pool = selected.get('pool')
            if pool and kind != 'opportunity':
                raise error('invalid_request', 400)
            binding = {"workspace": workspace_id, "actor": actor, "scopes": store.scope_signature(workspace_id, actor, cursor=cur),
                       "filters": contracts.digest(selected), "method_bundle": selected["method_bundle"], "as_of": as_of, "kind": kind,
                       "purpose": "model" if model_visible else "display"}
            if saved and any(saved.get(k) != v for k, v in binding.items()):
                raise error("invalid_request", 400)
            method = selected["method_bundle"].split("@")
            method = {"method_id": method[0], "version": method[1]} if len(method) == 2 else None
            from . import opportunity_pool
            page = store.list_projections(workspace_id, actor, kind=kind, limit=opportunity_pool.SCAN_LIMIT if pool else selected["limit"],
                before=saved.get("before") if saved else None, as_of=opportunities.iso(as_of),
                filters={k: v for k, v in selected.items() if k not in ("limit", "method_bundle", "view", "pool") and v}, method_bundle=method, cursor=cur)
            output = []
            quiet, history_complete = (opportunity_pool.quiet_ids(store, cur, workspace_id, actor,
                [r['object_id'] for r in page['items']], now) if pool and page['items'] else (set(), True))
            for row in page["items"]:
                try:
                    if model_visible and row.get("policy", {}).get("llm_process") is not True:
                        continue
                    if kind == "trend":
                        output.append(self._trend(store, cur, workspace_id, actor, row, now, model_visible=model_visible,
                                                  compose_related=not model_visible, as_of=as_of))
                    else:
                        p, _trend = self._opportunity_read(store, cur, workspace_id, actor, row, state, now, model_visible=model_visible)
                        if pool and (p['id'] in quiet or not opportunity_pool.eligible(row, p, _trend, state, now, pool)):
                            continue
                        output.append(p)
                except AlphaError as exc:
                    if exc.status not in (404, 410, 409):
                        raise
            if pool:
                output = output[:selected['limit']]
            cursor = self._cursor({**binding, "before": page["next_key"]}) if page.get("next_key") and not pool else None
            cov = output[0].get("coverage") if output else coverage(scope="workspace:" + workspace_id)
            limitations = ["Only stored results in the selected authorized scope; absence is not platform-wide absence."]
            if pool:
                limitations.append('A bounded recent opportunity pool; ordered by stored recency, not predicted performance. Existing planned work is unchanged.')
                if not history_complete:
                    limitations.append('Recent exposure history exceeds the bounded read; recommendations are withheld.')
            response = envelope(output, as_of, cov=cov, limitations=limitations,
                            execution_state="partial" if len(output) < len(page["items"]) else "stored_result", next_cursor=cursor)
            if kind == "opportunity":
                response["exposure_token"] = None if model_visible else exposure_events.page_token(
                    self, store, cur, workspace_id, actor, state, output, as_of, now)
            return response

    def get(self, workspace_id, token, trend_id, resource=None, object_id=None, *, model_visible=False):
        now = self.clock()
        with self.transaction(workspace_id, token) as (store, cur, _row, actor, _state, _scopes):
            receipt = None
            if resource == "receipts":
                receipt = self._get(store, cur, workspace_id, actor, "receipt", object_id, now)
                if receipt["payload"].get("trend_id") != ident(trend_id):
                    raise error("not_found", 404)
                if model_visible and receipt.get("policy", {}).get("llm_process") is not True:
                    raise error("forbidden", 403)
                if all(k in receipt["payload"] for k in ("canonical_topic", "observed", "calculated", "coverage")):
                    # A historical receipt is its frozen calculation and evidence,
                    # rechecked against current rights; never the latest trend body.
                    row = {**receipt, "object_id": trend_id, "receipt_id": object_id}
                else:
                    row = self._get(store, cur, workspace_id, actor, "trend", trend_id, now)
                    if (row.get("receipt_id") or row["payload"].get("trust_receipt_id")) != object_id:
                        raise error("source_unavailable", 503)
            else:
                row = self._get(store, cur, workspace_id, actor, "trend", trend_id, now)
            if model_visible and row.get("policy", {}).get("llm_process") is not True:
                raise error("forbidden", 403)
            trend = self._trend(store, cur, workspace_id, actor, row, now, model_visible=model_visible,
                                compose_related=resource is None and not model_visible)
            if resource is None:
                data = trend
            elif resource == "examples":
                data = trend["evidence"]
            elif resource == "snapshots":
                data = trend["observed"]["timeline"]
            elif resource == "receipts":
                data = {**trend, "receipt_id": object_id, "method": receipt["payload"].get("method")}
                if not data["method"]:
                    raise error("source_unavailable", 503)
            elif resource == 'forecast':
                if not self._enabled('FORECASTS') or not self._enabled('TRUST_RECEIPTS'):
                    raise error('forbidden',403)
                from .forecast_admission import ForecastAdmission
                page=store.list_projections(workspace_id,actor,kind='forecast',limit=20,cursor=cur)
                data=None
                for saved in page['items']:
                    try:
                        ref=saved.get('payload',{}).get('admission',{}).get('candidate',{})
                        candidate=store.get_projection(workspace_id,actor,'forecast_candidate',ref.get('object_id'),revision=ref.get('revision'),cursor=cur)
                        if (not candidate or candidate['validity']!='valid'
                                or candidate['payload'].get('trend_id')!=trend_id
                                or candidate['payload'].get('trust_receipt_id')!=trend['trust_receipt_id']):
                            continue
                        if model_visible and any(r.get('policy',{}).get('llm_process') is not True for r in (saved,candidate)):
                            continue
                        current=ForecastAdmission(store,values=self.values).read(workspace_id,actor,saved['object_id'],revision=saved['revision'],cursor=cur)
                        data=self._forecast_wire(current)
                        break
                    except (contracts.ContractError,KeyError,ValueError,TypeError):
                        continue
                if data is None:
                    raise error('source_unavailable',503)
            elif resource == 'whitespace':
                data = self._whitespace_read(store,cur,workspace_id,actor,trend_id,now,model_visible=model_visible)
                if data['trust_receipt_id'] != trend['trust_receipt_id']:
                    raise error('source_unavailable',503)
            elif resource in FEATURES:
                if not self._enabled(FEATURES[resource]):
                    raise error("forbidden", 403)
                advanced = store.get_projection(workspace_id, actor, KINDS[resource], trend_id, cursor=cur)
                if advanced is None:
                    raise error("source_unavailable", 503)
                advanced = self._current(advanced, now)
                if (trend["verification_state"] != "verified" or not trend["trust_receipt_id"]
                        or advanced["payload"].get("trust_receipt_id") != trend["trust_receipt_id"]):
                    # An artifact from an earlier receipt cannot describe a
                    # corrected trend, even while both retained DAGs are valid.
                    raise error("source_unavailable", 503)
                if model_visible and advanced.get("policy", {}).get("llm_process") is not True:
                    raise error("forbidden", 403)
                self._semantic_current(store,cur,workspace_id,actor,_state,advanced)
                data = project_advanced(resource, advanced["payload"])
            else:
                raise error("not_found", 404)
            return envelope(data, now, cov=trend["coverage"], limitations=trend["limitations"],
                            execution_state="partial" if trend["coverage"]["completeness"] != "complete_within_scope" else "stored_result")

    def _semantic_current(self,store,cur,workspace_id,actor,state,saved):
        from .advanced_pipeline import SEMANTIC_KINDS, _method
        kind=saved.get('kind')
        if kind not in SEMANTIC_KINDS:
            return
        if saved['method_bundle']['method_id']!='trend.'+kind+'.local':
            raise error('source_unavailable',503)
        payload=saved.get('payload') or {}
        if '_semantic_bindings' not in payload or saved['method_bundle']['version']!=_method(kind)['method_version']:
            raise error('source_unavailable',503)
        from .semantic_admission import validate_current
        validate_current(store,cur,workspace_id,actor,state,payload['_semantic_bindings'])
        if payload['_semantic_bindings'] and not self._enabled('MODEL_ENRICHMENT'):
            raise error('source_unavailable',503)
        if kind == 'genome':
            from .advanced_pipeline import AdvancedPipeline
            from .interpretation_context import validate_current as validate_interpretation
            if '_interpretation_bindings' not in payload:
                raise error('source_unavailable',503)
            advanced=AdvancedPipeline(store,values=self.values,clock=lambda:opportunities.iso(self.clock()))
            _trend,receipt,_manifest,inputs=advanced._load(cur,workspace_id,actor,saved['object_id'],read_only=True)
            if receipt['object_id']!=payload.get('trust_receipt_id'):
                raise error('source_unavailable',503)
            validate_interpretation(cur,store,workspace_id,actor,inputs,receipt_id=receipt['object_id'],
                state=state,bindings=payload['_interpretation_bindings'],values=self.values,now=opportunities.iso(self.clock()))

    def _whitespace_read(self, store, cur, workspace_id, actor, trend_id, now, *, model_visible=False):
        if not all(self._enabled(n) for n in ('WHITESPACE','TRUST_RECEIPTS')):
            raise error('forbidden',403)
        from .whitespace_admission import WhitespaceAdmission
        saved = self._get(store,cur,workspace_id,actor,'whitespace',trend_id,now)
        if model_visible and saved.get('policy',{}).get('llm_process') is not True:
            raise error('forbidden',403)
        current = WhitespaceAdmission(store,values=self.values).current_result(workspace_id,actor,trend_id,cursor=cur)
        if current is None:
            raise error('source_unavailable',503)
        return project_advanced('whitespace',current)

    @staticmethod
    def _forecast_wire(saved):
        # Replay returns numeric predictions and reviewed qualification only.
        # Internal approval identities/DAG references do not enter the public wire.
        payload=copy.deepcopy(saved['payload'])
        payload.pop('admission',None)
        return {'id':saved['object_id'],'revision':saved['revision'],'expires_at':opportunities.iso(saved['expires_at']),
                'method':saved['method_bundle'],**payload}

    def forecast_operation(self,workspace_id,token,*,action=None,payload=None,object_id=None,revision=None):
        with self.transaction(workspace_id,token,'edit' if action else 'read') as (store,cur,_row,actor,_state,_scopes):
            if not all(self._enabled(n) for n in ('RADAR','TRUST_RECEIPTS','FORECASTS')):
                raise error('forbidden',403)
            from .forecast_admission import ForecastAdmission
            admission=ForecastAdmission(store,values=self.values)
            if object_id is not None:
                if type(revision) is not int or revision<1:raise error('invalid_request',400)
                result=admission.read(workspace_id,actor,ident(object_id),revision=revision,cursor=cur)
                return envelope(self._forecast_wire(result),self.clock())
            if not isinstance(payload,dict):raise error('invalid_request',400)
            if action=='admit' and set(payload)=={'candidate','evaluation','review'}:
                result=admission.persist(workspace_id,actor,**payload,cursor=cur)
                return envelope(self._forecast_wire(result),self.clock())
            if action=='evaluate' and set(payload)=={'preregistration','candidates'}:
                from .forecast_evaluation import ForecastEvaluation
                result=ForecastEvaluation(store,values=self.values).evaluate(workspace_id,actor,payload['preregistration'],payload['candidates'],cursor=cur)
                value=result.get('payload',result)
                allowed=('state','reason','qualification','forecast_wording_enabled','paired_count','episode_count','censored_count',
                         'report_digest','dataset_digest','missing_slots','missing_candidate_refs')
                return envelope({k:copy.deepcopy(value[k]) for k in allowed if k in value}
                    | ({'id':result['object_id'],'revision':result['revision']} if result.get('object_id') else {}),self.clock())
            raise error('invalid_request',400)

    def stored(self, workspace_id, token, resource, object_id=None, *, model_visible=False):
        now = self.clock()
        with self.transaction(workspace_id, token) as (store, cur, _row, actor, _state, _scopes):
            if resource in FEATURES and not self._enabled(FEATURES[resource]):
                raise error("forbidden", 403)
            kind = KINDS[resource]
            if object_id:
                saved = self._get(store, cur, workspace_id, actor, kind, object_id, now)
                if model_visible and saved.get("policy", {}).get("llm_process") is not True:
                    raise error("forbidden", 403)
                self._semantic_current(store,cur,workspace_id,actor,_state,saved)
                data = (self._whitespace_read(store,cur,workspace_id,actor,object_id,now,model_visible=model_visible)
                    if resource == 'whitespace' else project_advanced(resource, saved['payload']))
                if resource == "lab":
                    from .opportunity_lab import project_run
                    op_row = self._get(store, cur, workspace_id, actor, "opportunity", data["opportunity_id"], now)
                    op, trend = self._opportunity_read(store, cur, workspace_id, actor, op_row, _state, now, model_visible=model_visible)
                    draft = next((v for v in _state.get("variants", []) if v["id"] == data["draft_id"]), None)
                    receipt = self._get(store, cur, workspace_id, actor, "receipt", op["trust_receipt_id"], now)
                    if not draft or "frozen_run" not in saved["payload"]:
                        data.update(state="stale", diagnostics=[], failure_reason="stale_dependencies")
                    else:
                        inputs = self._lab_inputs(workspace_id, _state, op, op_row, receipt, draft, trend, now, cursor=cur)
                        data = self._lab_project(store,cur,workspace_id,actor,_state,saved,inputs)
            else:
                rows = store.list_projections(workspace_id, actor, kind=kind, limit=20, cursor=cur)
                rows = rows["items"] if isinstance(rows, dict) else rows
                if model_visible:
                    rows = [r for r in rows if r.get("policy", {}).get("llm_process") is True]
                if resource == 'language-patterns':
                    rows = [r for r in rows if r.get('policy',{}).get('display_excerpt') is True]
                if not rows:
                    raise error("source_unavailable", 503)
                if resource == 'whitespace':
                    data = []
                    for saved in rows:
                        # Operator review records use this storage kind too;
                        # only current admitted producer results are user data.
                        if saved.get('payload',{}).get('schema_version') != 'rafii.trend-whitespace-admission.v1':
                            continue
                        try:
                            data.append(self._whitespace_read(store,cur,workspace_id,actor,saved['object_id'],now,model_visible=model_visible))
                        except (AlphaError,contracts.ContractError):
                            continue
                elif resource == 'language-patterns':
                    data = []
                    for r in rows:
                        p = self._current(r,now)['payload']
                        items = p.get('patterns', [p])
                        data.extend(project_advanced(resource,item) for item in items[:20])
                    data = data[:100]
                else:
                    data=[]
                    for r in rows:
                        current=self._current(r,now)
                        try:
                            self._semantic_current(store,cur,workspace_id,actor,_state,current)
                        except (AlphaError,contracts.ContractError):
                            continue
                        data.append(project_advanced(resource,current['payload']))
                if resource in ("methodology", "calibration"):
                    data = data[0]
            return envelope(data, now)

    def _opportunity_read(self, store, cur, workspace_id, actor, row, state, now, *, model_visible=False):
        self._current(row, now)
        if model_visible and row.get("policy", {}).get("llm_process") is not True:
            raise error("forbidden", 403)
        if row["scope_key"] != "workspace:" + workspace_id:
            raise error("not_found", 404)
        p = {**row["payload"], "id": row["object_id"], "revision": row["revision"],
             "expires_at": opportunities.iso(row["expires_at"]), "workspace_id": workspace_id}
        opportunities.check_current(p, state, now, workspace_id=workspace_id)
        from .whitespace_admission import validate_opportunity
        validate_opportunity(store,cursor=cur,workspace_id=workspace_id,actor_id=actor,opportunity=p,state=state)
        trend = self._trend(store, cur, workspace_id, actor,
                            self._get(store, cur, workspace_id, actor, "trend", p["trend_id"], now), now, model_visible=model_visible)
        if p.get("trust_receipt_id") != trend["trust_receipt_id"]:
            raise error("revision_conflict", 409)
        fit = p.get("workspace_fit") or p.get("dimensions") or {}
        keys = {"trend_relevance": "trend_relevance", "audience": "audience_relevance", "brand": "brand_fit", "timing": "timing_opportunity", "originality": "originality_opportunity", "risk": "risk", "confidence": "confidence"}
        fit = {key: copy.deepcopy(fit.get(key, fit.get(source, {"assessment": "unknown", "reason": "Not evaluated", "evidence_refs": []}))) for key, source in keys.items()}
        fit.update(reason=str(p.get("fit_reason", "Independent workspace dimensions; no combined score.")),
                   sufficient=p.get("executable_ready") is True or p.get("qualified") is True)
        wire_state = {"eligible": "ready", "suggested": "ready", "drafting": "accepted", "linked": "accepted", "retracted": "blocked"}.get(p.get("state"), p.get("state", "candidate"))
        source = next((s for s in state.get("sources", []) if (s.get("origin") or {}).get("trendLineage", {}).get("opportunity_id") == p["id"] and s.get("active")), None)
        decision = exposure_events.latest_decision(cur, workspace_id, p["id"], p["revision"])
        if decision and decision["decision"] == "dismiss":
            wire_state = "dismissed"
        drafts = [v for v in state.get("variants", []) if any(b.get("opportunity_id") == p["id"] for b in v.get("trendLineage", []))]
        draft = drafts[0] if len(drafts) == 1 else None
        data = {"id": p["id"], "revision": p["revision"], "trend_id": p["trend_id"], "trust_receipt_id": p["trust_receipt_id"],
                "state": "accepted" if source else wire_state, "platform_targets": p.get("platform_targets", []),
                "context_digest": p["context_digest"], "context_revision": p["context_digest"], "verification_state": trend["verification_state"],
                "expires_at": opportunities.iso(min(opportunities.epoch(row["expires_at"]), opportunities.epoch(trend["expires_at"]))),
                "title": p.get("title", trend["canonical_topic"]), "contribution": p.get("contribution", ""),
                "uncertainty": p.get("uncertainty", "Workspace fit is a hypothesis, not a measured social outcome."),
                "workspace_fit": fit, "source_id": source["id"] if source else None, "draft_id": draft["id"] if draft else None,
                "angles": [{"id": a["id"], "title": a.get("title", ""), "contribution": a.get("contribution", ""),
                            "factual_requirements": a.get("factual_requirements", []), "format_reason": a.get("format_reason", "")} for a in p.get("angles", [])[:3]]}
        return data, trend

    def opportunity(self, workspace_id, token, opportunity_id, *, model_visible=False):
        now = self.clock()
        with self.transaction(workspace_id, token) as (store, cur, _row, actor, state, _scopes):
            row = self._get(store, cur, workspace_id, actor, "opportunity", opportunity_id, now)
            p, trend = self._opportunity_read(store, cur, workspace_id, actor, row, state, now, model_visible=model_visible)
            return envelope(p, now, cov=trend["coverage"], limitations=trend["limitations"])

    def accept(self, workspace_id, token, opportunity_id, payload):
        required = {"revision", "angle_id", "channel_id", "goal", "idempotency_key"}
        if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - {"exposure_id"} or type(payload["revision"]) is not int or payload["revision"] < 1:
            raise error("invalid_request", 400)
        if any(not isinstance(payload[k], str) or not 1 <= len(payload[k]) <= (1000 if k == "goal" else 200) for k in required - {"revision"}):
            raise error("invalid_request", 400)
        if "exposure_id" in payload:
            ident(payload["exposure_id"])
        now = self.clock()
        with self.transaction(workspace_id, token, "edit") as (store, cur, row, actor, state, _scopes):
            exposure_events.require_flags(self)
            current = self._get(store, cur, workspace_id, actor, "opportunity", opportunity_id, now)
            if current["scope_key"] != "workspace:" + workspace_id:
                raise error("not_found", 404)
            op = {**current["payload"], "id": current["object_id"], "revision": current["revision"], "workspace_id": workspace_id,
                  "expires_at": opportunities.iso(current["expires_at"])}
            opportunities.check_current(op, state, now, workspace_id=workspace_id)
            trend = self._trend(store, cur, workspace_id, actor, self._get(store, cur, workspace_id, actor, "trend", op["trend_id"], now), now)
            if trend["verification_state"] != "verified" or trend["trust_receipt_id"] != op["trust_receipt_id"]:
                raise error("evidence_unavailable", 410)
            store.lock_dependencies(workspace_id, actor, [{"kind": "opportunity", "object_id": opportunity_id, "revision": payload["revision"]},
                {"kind": "receipt", "object_id": op["trust_receipt_id"]}, {"kind": "trend", "object_id": op["trend_id"]}], cursor=cur)
            now = self.clock()
            self._current(current, now)
            opportunities.check_current(op, state, now, workspace_id=workspace_id)
            from .whitespace_admission import validate_opportunity
            validate_opportunity(store,cursor=cur,workspace_id=workspace_id,actor_id=actor,opportunity=op,state=state,mutation=True)
            prior = exposure_events.latest_decision(cur, workspace_id, opportunity_id, payload["revision"])
            if prior and prior["decision"] == "dismiss":
                raise error("revision_conflict", 409)
            exposure_events.check_exposure(self, store, cur, workspace_id, actor, op, payload.get("exposure_id"), now)
            before = copy.deepcopy(state)
            result = opportunities.accept_source(state, actor, op, trend, {**payload, "workspace_id": workspace_id}, now, self.hosted.commands)
            decision = store.decide_opportunity(workspace_id, actor, opportunity_id, revision=payload["revision"], decision="accept",
                idempotency_key=payload["idempotency_key"], result={"source_id": result["source_id"], "selection_digest": contracts.digest({k:v for k,v in payload.items() if k != "idempotency_key"}),
                    **({"exposure_id": payload["exposure_id"]} if "exposure_id" in payload else {})}, cursor=cur)
            if decision.get("result", {}).get("source_id") != result["source_id"]:
                raise error("revision_conflict", 409)
            if state != before:
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
                from ...hosted import audit
                audit(cur, workspace_id, actor, "trend.opportunity_accepted", opportunity_id, {"revision": payload["revision"], "sourceId": result["source_id"]})
                for effect in self.repository.effects:
                    effect(cur, workspace_id, before, state, actor)
                for item in trend["evidence"]:
                    if item["display_state"] == "displayable":
                        prov = {"provider": item["platform"], "kind": "social", "accessMethod": "stored_trend_projection",
                                "url": item["url"], "evidenceType": "search_snippet", "representedScope": "workspace:" + workspace_id,
                                "retrievedAt": now, "rights": {"receipt_id": trend["trust_receipt_id"], "expires_at": item["expires_at"]}}
                        self.coworker._store_evidence(cur, workspace_id, "trend:" + opportunity_id, prov, item["excerpt"] or "")
            return envelope(result, now, cov=trend["coverage"], limitations=trend["limitations"])

    def exposure(self, workspace_id, token, payload):
        return exposure_events.record(self, ident(workspace_id), token, payload)

    def learning(self, workspace_id, token, *, payload=None, window='24h', assessment=False):
        from . import learning, learning_options
        with self.transaction(workspace_id,token,'edit' if payload is not None else 'read') as (store,cur,row,actor,state,_scopes):
            exposure_events.require_flags(self)
            now=self.clock()
            if payload is None:
                descriptor=learning.report(cur,workspace_id,actor,now,store=store,window=window)
                descriptor['choice_options']=learning_options.choices(store,cur,workspace_id,actor,state,now)
                return envelope(descriptor,now)
            before=copy.deepcopy(state)
            try:
                if assessment:
                    from . import treatment
                    if not isinstance(payload,dict) or type(payload.get('expected_revision')) is not int:
                        raise ValueError('workspace_revision_required')
                    if payload['expected_revision'] != row[0]:
                        raise error('revision_conflict',409)
                    choice=treatment.record(state,actor,{k:v for k,v in payload.items() if k!='expected_revision'},now)
                else:
                    learning_options.require_choice(learning_options.choices(store,cur,workspace_id,actor,state,now),payload)
                    choice=learning.record_metric_choice(state,actor,payload,now)
            except (ValueError,TypeError,KeyError):
                raise error('invalid_request',400) from None
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),workspace_id))
            from ...hosted import audit
            audit(cur,workspace_id,actor,'trend.treatment_assessed' if assessment else 'trend.metric_choice_saved',
                  choice['variant_id'] if assessment else choice['id'],
                  {'treatment_changed':choice['treatment_changed']} if assessment else {'metric':choice['metric'],'window':choice['window']})
            for effect in self.repository.effects:
                effect(cur,workspace_id,before,state,actor)
            return envelope(choice,now)

    def media(self, workspace_id, token, *, payload=None, job_id=None, result_id=None, artifact_sha256=None):
        """Explicit bounded media run; storage staging never runs inside the cron budget."""
        import time
        from .media_jobs import MediaJobs, KIND
        deadline=time.monotonic()+180
        with self.transaction(workspace_id,token,'read' if result_id is not None else 'edit') as (store,cur,_row,actor,_state,_scopes):
            if not all(self._enabled(k) for k in ('RADAR','TRUST_RECEIPTS','MULTIMODAL')):
                raise error('forbidden',403)
            if sum(value is not None for value in (payload,job_id,result_id))!=1 or (artifact_sha256 is not None and result_id is None):
                raise error('invalid_request',400)
            if artifact_sha256 is not None and (not isinstance(artifact_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',artifact_sha256)):
                raise error('invalid_request',400)
            coordinator=MediaJobs(self.hosted,store=store,values=self.values)
            if result_id is not None:
                result_id=ident(result_id)
            elif job_id is not None:
                job_id=ident(job_id)
                cur.execute('SELECT kind FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s',('workspace:'+workspace_id,job_id))
                found=cur.fetchone()
                if not found or found[0]!=KIND:
                    raise error('not_found',404)
            else:
                if not isinstance(payload,dict) or set(payload)!={'clips','idempotency_key'}:
                    raise error('invalid_request',400)
                return envelope(coordinator.enqueue(workspace_id,actor,payload['clips'],idempotency_key=payload['idempotency_key'],cursor=cur),self.clock())
        # Authenticated principal is rechecked by the coordinator immediately before
        # each read/transport/decoder and before the independently fenced commit.
        try:
            if result_id is not None:
                result=coordinator.read(workspace_id,actor,result_id)
                artifacts=result.get('artifacts')
                if not isinstance(artifacts,dict): raise error('evidence_unavailable',410)
                if len(artifacts)>12: raise error('source_unavailable',413)
                def artifact(key):
                    if key not in artifacts: raise error('not_found',404)
                    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key): raise error('evidence_unavailable',410)
                    encoded=artifacts[key]
                    if not isinstance(encoded,str): raise error('evidence_unavailable',410)
                    if len(encoded)>4*1024*1024: raise error('source_unavailable',413)
                    try: raw=base64.b64decode(encoded,validate=True)
                    except (ValueError,TypeError): raise error('evidence_unavailable',410) from None
                    if len(raw)>=3*1024*1024: raise error('source_unavailable',413)
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(raw).hexdigest()!=key:
                        raise error('evidence_unavailable',410)
                    return raw
                if artifact_sha256 is not None:
                    return artifact(artifact_sha256)
                refs=[]
                for key in sorted(artifacts):
                    raw=artifact(key)
                    refs.append({'sha256':key,'mime_type':'image/png','byte_length':len(raw),
                        'url':f'/api/workspaces/{workspace_id}/coworker/trends/media/results/{result_id}/artifacts/{key}'})
                # The digest identifies the complete sealed document; the wire
                # projection carries references instead of its encoded PNG map.
                result={'result_id':result_id,'manifest_digest':result['manifest_digest'],
                        'extraction':result['extraction'],'pattern':result['pattern'],'artifact_refs':refs}
            else:
                result=coordinator.run('workspace:'+workspace_id,job_id,deadline=deadline)
            response=envelope(result,self.clock(),limitations=['Local extraction; no semantic modality qualification.'])
            if len(json.dumps(response,ensure_ascii=False,allow_nan=False).encode('utf-8'))>4_500_000:
                raise error('source_unavailable',413)
            return response
        except contracts.ContractError:
            raise error('evidence_unavailable',410) from None

    def dismiss(self, workspace_id, token, opportunity_id, payload):
        return exposure_events.dismiss(self, ident(workspace_id), token, ident(opportunity_id), payload)

    @staticmethod
    def _watch(row):
        if row is None:
            raise error("not_found", 404)
        p = row["payload"]
        return {"id": row["watch_id"], "revision": row.get("revision", 1), "trend_id": p["trend_id"],
                "platforms": p["platforms"], "threshold": p["threshold"], "notification_policy": "in_app", "active": row["enabled"]}

    def watches(self, workspace_id, token, *, payload=None, watch_id=None, delete=False):
        now = self.clock()
        with self.transaction(workspace_id, token, "edit" if payload is not None or delete else "read") as (store, cur, _row, actor, _state, _scopes):
            if delete:
                if not isinstance(payload, dict) or set(payload) != {"expected_revision", "idempotency_key"}:
                    raise error("invalid_request", 400)
                revision = payload["expected_revision"]
                if isinstance(revision, str) and revision.isdecimal():
                    revision = int(revision)
                if type(revision) is not int or revision < 1 or not isinstance(payload["idempotency_key"], str) or not 1 <= len(payload["idempotency_key"]) <= 200:
                    raise error("invalid_request", 400)
                data = self._watch(store.delete_watch(workspace_id, actor, ident(watch_id), expected_revision=revision,
                                                      idempotency_key=payload["idempotency_key"], cursor=cur))
            elif payload is None:
                data = [self._watch(r) for r in store.list_watches(workspace_id, actor, cursor=cur)]
            else:
                if watch_id is not None:
                    # Storage currently supports immutable create and revisioned
                    # delete. Never turn a PATCH into creation of a second watch.
                    raise error("source_unavailable", 503)
                allowed = {"trend_id", "platforms", "threshold", "notification_policy", "idempotency_key"}
                if not isinstance(payload, dict) or set(payload) != allowed:
                    raise error("invalid_request", 400)
                ident(payload["trend_id"])
                if not isinstance(payload["platforms"], list) or not 1 <= len(payload["platforms"]) <= 12 or any(p not in PLATFORMS for p in payload["platforms"]):
                    raise error("invalid_request", 400)
                if payload["threshold"] not in ("stage_change", "coverage_change") or payload["notification_policy"] != "in_app":
                    raise error("invalid_request", 400)
                if not isinstance(payload["idempotency_key"], str) or not 1 <= len(payload["idempotency_key"]) <= 200:
                    raise error("invalid_request", 400)
                self._get(store, cur, workspace_id, actor, "trend", payload["trend_id"], now)
                data = self._watch(store.put_watch(workspace_id, actor, {k:v for k,v in payload.items() if k != "idempotency_key"},
                                                   idempotency_key=payload["idempotency_key"], cursor=cur))
            return envelope(data, now)

    def gated_mutation(self, workspace_id, token, feature=None):
        with self.transaction(workspace_id, token, "edit"):
            if feature and not self._enabled(feature):
                raise error("forbidden", 403)
            # A route is not paid authority. Admission/reservations must be supplied by
            # the durable worker integration before requests can enqueue real work.
            raise error("source_unavailable", 503)

    def _lab_project(self,store,cur,workspace_id,actor,state,saved,inputs):
        from .opportunity_lab import project_run
        frozen=copy.deepcopy(saved['payload']['frozen_run'])
        if saved['payload'].get('model_result_id'):
            from .lab_enrichment import TrendLabEnrichment
            evaluator=TrendLabEnrichment(self.hosted,store=store,values=self.values)
            result=evaluator.current_result(cur,workspace_id,actor,saved['object_id'],state) if evaluator.enabled(workspace_id) else None
            if result is None:
                frozen.update(state='stale',diagnostics=[],failure_reason='stale_dependencies')
            else:
                frozen['diagnostics']=copy.deepcopy(result['diagnostics'])
        return project_advanced('lab',project_run({**inputs,'run':frozen}))

    def _queue_lab_semantic(self,store,cur,workspace_id,actor,state,run_id,key):
        if not self._enabled('MODEL_ENRICHMENT'):
            return 'Semantic review is disabled; these are deterministic diagnostics.'
        from .lab_enrichment import TrendLabEnrichment
        try:
            # A missing reviewed permission/budget cannot roll back a successful
            # cheap pass. No model is called inside this authenticated transaction.
            with cur.connection.transaction():
                queued=TrendLabEnrichment(self.hosted,store=store,values=self.values).enqueue_stored(
                    cur,workspace_id,actor,run_id,state,idempotency_key='semantic:'+key)
            return 'A bounded advisory semantic review is '+queued['status']+'. Native evaluation is not empirical calibration.'
        except (contracts.ContractError,AlphaError,KeyError,ValueError,TypeError):
            return 'Semantic review is unavailable under current reviewed rights, configuration or budget.'

    def lab_create(self, workspace_id, token, payload, *, model_visible=False):
        required = {"draft_id", "draft_revision", "opportunity_id", "opportunity_revision", "target_platform", "idempotency_key"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise error("invalid_request", 400)
        if any(type(payload[k]) is not int or payload[k] < 1 for k in ("draft_revision", "opportunity_revision")):
            raise error("invalid_request", 400)
        if any(not isinstance(payload[k], str) or not 1 <= len(payload[k]) <= 200 for k in required - {"draft_revision", "opportunity_revision"}):
            raise error("invalid_request", 400)
        now = self.clock()
        with self.transaction(workspace_id, token, "edit") as (store, cur, _row, actor, state, _scopes):
            if not self._enabled("OPPORTUNITY_LAB"):
                raise error("forbidden", 403)
            row = self._get(store, cur, workspace_id, actor, "opportunity", payload["opportunity_id"], now)
            op, trend = self._opportunity_read(store, cur, workspace_id, actor, row, state, now, model_visible=model_visible)
            draft = next((v for v in state.get("variants", []) if v["id"] == payload["draft_id"]), None)
            if draft is None or op["draft_id"] != draft["id"]:
                raise error("not_found", 404)
            if op["revision"] != payload["opportunity_revision"] or draft["revision"] != payload["draft_revision"] or draft["platform"].lower() != payload["target_platform"].lower():
                raise error("revision_conflict", 409)
            if trend["verification_state"] != "verified":
                raise error("evidence_unavailable", 410)
            from . import opportunity_lab
            from .jobs import TrendJobs
            store.lock_dependencies(workspace_id, actor, [{"kind": "opportunity", "object_id": op["id"], "revision": op["revision"]},
                {"kind": "receipt", "object_id": op["trust_receipt_id"]}, {"kind": "trend", "object_id": op["trend_id"]}], cursor=cur)
            now = self.clock()
            receipt_row = self._get(store, cur, workspace_id, actor, "receipt", op["trust_receipt_id"], now)
            run_id = str(uuid.uuid5(uuid.UUID(workspace_id), "trend-lab:" + payload["idempotency_key"]))
            inputs = self._lab_inputs(workspace_id, state, op, row, receipt_row, draft, trend, now, cursor=cur)
            inputs.update(request={**copy.deepcopy(payload), "target_platform": payload["target_platform"].lower()}, idempotency_key=payload["idempotency_key"], run_id=run_id)
            existing = store.get_projection(workspace_id, actor, "lab_run", run_id, cursor=cur)
            if existing:
                self._current(existing, now)
                if existing["payload"].get("request_digest") != contracts.digest(payload):
                    raise error("revision_conflict", 409)
                projected = self._lab_project(store,cur,workspace_id,actor,state,existing,inputs)
                queued=self._queue_lab_semantic(store,cur,workspace_id,actor,state,run_id,payload['idempotency_key'])
                return envelope(projected, now, cov=trend["coverage"], limitations=[queued])
            # A real durable, fenced local job, with zero provider/model dispatch or
            # cost reservation. Request text is never accepted from the browser.
            jobs = (self.jobs_factory or TrendJobs)(store)
            scope_key = "workspace:" + workspace_id
            store.ensure_scope(scope_key, cursor=cur)
            job = jobs.enqueue(scope_key, "trend.opportunity_lab.local", {"run_id": run_id, "request_digest": contracts.digest(payload)},
                               idempotency_key="lab:" + payload["idempotency_key"], cursor=cur)
            claim = jobs.claim("trend-service-local", scope_key=scope_key, kind="trend.opportunity_lab.local", job_id=job["job_id"],
                               lease_seconds=60, amount_micro_usd=0, cursor=cur)
            if claim is None:
                raise error("revision_conflict", 409)
            jobs.start(claim, cursor=cur)
            frozen = opportunity_lab.freeze_run(inputs)
            result = opportunity_lab.evaluate_run({**inputs, "run": frozen})
            # Never label a frozen input, stale dependency or missing evidence as a
            # completed diagnostic. The pure evaluator declares the actual state.
            wire = opportunity_lab.to_stored_projection(result)["payload"]
            import inspect
            from . import context as lab_context
            implementation = contracts.digest({"lab": inspect.getsource(opportunity_lab), "context": inspect.getsource(lab_context)})
            version = "local-" + implementation[:16]
            store.put_method("trend.lab.local", version, implementation, {"execution": "pure_deterministic", "semantic_qualification": "unqualified"}, cursor=cur)
            refs = [{"scope_key": r["scope_key"], "node_id": r["projection_id"]} for r in (row, receipt_row)]
            manifest = store.put_manifest(scope_key, refs, decision_cutoff=opportunities.iso(now), available_at=opportunities.iso(now),
                                          retention_until=wire["expires_at"], recipe={"request_digest": contracts.digest(payload), "inputs": inputs}, cursor=cur)
            store.put_projection({"scope_key": scope_key, "kind": "lab_run", "object_id": run_id, "revision": 1,
                "manifest_id": manifest["manifest_id"], "method_id": "trend.lab.local", "method_version": version,
                "decision_cutoff": opportunities.iso(now), "available_at": opportunities.iso(now), "retention_until": wire["expires_at"],
                "context_digest": op["context_digest"], "draft_id": draft["id"], "draft_revision": draft["revision"],
                "payload": {**wire, "frozen_run": result, "request_digest": contracts.digest(payload)}}, cursor=cur)
            jobs.finish_local(claim, cursor=cur)
            from ...hosted import audit
            audit(cur, workspace_id, actor, "trend.lab_completed", run_id, {"draftRevision": draft["revision"], "state": wire["state"], "modelCalls": 0})
            queued=self._queue_lab_semantic(store,cur,workspace_id,actor,state,run_id,payload['idempotency_key'])
            return envelope(wire, now, cov=trend["coverage"], limitations=[queued])

    @staticmethod
    def _lab_inputs(workspace_id, state, op, op_row, receipt_row, draft, trend, now, *, cursor=None):
        """Adapt trusted current store capabilities into the pure evaluator's inputs.

        These booleans are internal computed capabilities, never client/source
        rights grants. Full original structured grants remain in the bound DAG.
        """
        scope_key = receipt_row["scope_key"]
        at = opportunities.iso(now)
        expiry = op["expires_at"]
        platform = draft["platform"].lower()
        rid = receipt_row["object_id"]
        source = {"source_id": rid, "scope_key": scope_key, "available_at": receipt_row["available_at"],
                  "event_at": receipt_row["available_at"], "expires_at": expiry, "platform": platform,
                  "original": False, "rights": {"analysis": receipt_row["policy"].get("derive_metrics") is True,
                                                "creative": receipt_row["policy"].get("display_excerpt") is True}}
        refs = [rid]
        common = {"available_at": op_row["available_at"], "expires_at": expiry, "evidence_refs": refs}
        sources = [source]
        for evidence in trend["evidence"]:
            if evidence["display_state"] == "displayable" and evidence.get("excerpt"):
                sources.append({"source_id": evidence["id"], "scope_key": scope_key, "available_at": receipt_row["available_at"],
                    "event_at": evidence["observed_at"], "expires_at": evidence["expires_at"], "platform": evidence["platform"],
                    "original": False, "text": evidence["excerpt"], "rights": {"analysis": True, "creative": True}})
        facts = [f["id"] for s in state.get("sources", []) if s.get("active") for f in s.get("facts", []) if f.get("approved")][:100]
        bound = next((b for b in draft.get("trendLineage", []) if b["opportunity_id"] == op["id"]), None)
        findings = []
        for evidence in sources[1:]:
            phrase = evidence["text"].strip()
            if len(phrase) >= 20 and draft["text"].count(phrase) == 1:
                edit = None
                if draft["text"].replace(phrase, "", 1).strip():
                    edit = {"id": contracts.digest({"draft": draft["id"], "source": evidence["source_id"], "phrase": phrase})[:32],
                            "before": phrase, "after": "", "reason": "Remove the exact repeated evidence passage; review the remaining draft."}
                findings.append({"dimension": "originality", "assessment": "concern", "available_at": evidence["available_at"],
                    "expires_at": evidence["expires_at"], "evidence_refs": [evidence["source_id"]],
                    "claim": "A passage exactly repeats a permitted evidence excerpt.", "comparison_frame": "Exact text comparison within the stored evidence sample.",
                    "uncertainty": "Text overlap alone does not establish broader originality or attribution.", "requires_user_fact": False, "suggested_edit": edit})
                break
        history = {"workspace_id": workspace_id, "comparable": False, "published_count": 0, "observations": [],
                   "reason": "No eligible owned measurements in the frozen comparison frame."}
        jobs = [j for j in (state.get("phase2") or {}).get("jobs", []) if j.get("state") == "verified"][-120:]
        if jobs and cursor is not None:
            from ... import insights
            posts = insights.summary(cursor, workspace_id, jobs, now, basis="24h")["posts"]
            # These are owned native metric receipts, kept separate from shared
            # social evidence. No semantic historical claim or causal score follows.
            for post in posts[:30]:
                if (post.get("publishedState") != "verified" or str(post.get("platform", "")).lower() != platform
                        or post.get("connectionId") != (bound or {}).get("channel_id")):
                    continue
                measured = {k: {f: v.get(f) for f in ("value", "unit", "nativeName", "readOffset", "observedAt")}
                            for k, v in list(post.get("metrics", {}).items())[:12] if v.get("availability") == "available" and v.get("observedAt", now+1) <= now}
                if measured and post.get("freshness", {}).get("ingestedAt", now+1) <= now:
                    history["observations"].append({"job_id": post["jobId"], "cohort": post["cohort"], "metrics": measured, "basis": "24h"})
            history["observations"].sort(key=lambda v: v["job_id"])
            history["published_count"] = len(history["observations"])
            if history["observations"]:
                history["reason"] = "Owned native measurements retained; semantic historical comparison remains unqualified."
        return {"workspace_id": workspace_id, "scope_key": scope_key, "decision_cutoff": at, "enabled": True,
                "sources": sources, "draft": {"id": draft["id"], "revision": draft["revision"], "text": draft["text"],
                    "workspace_id": workspace_id, "saved": True, "allowed_platforms": [platform]},
                "opportunity": {**op, **common, "workspace_id": workspace_id, "allowed_platforms": [p.lower() for p in op["platform_targets"]]},
                "receipt": {"id": rid, "scope_key": scope_key, "verification_state": receipt_row["verification_state"], **common},
                "context": {"workspace_id": workspace_id, "revision": op["context_revision"], "approved_user_fact_refs": facts},
                "selected_angle": copy.deepcopy(bound.get("angle")) if bound else None,
                "own_history": history,
                "comparison_sample": {"coverage": trend["coverage"], "evidence_ids": [e["source_id"] for e in sources]},
                "target_platform": platform, "findings": findings}



def validate_stored_bindings(connection_factory, cursor, workspace_id, actor, state, bindings, now, *, model_visible=False, store_factory=None, read_only=False):
    """Same-transaction gate for existing Ideas completion/apply and queue lineage.

    No trend records means no new migration read. This gate is deliberately not a
    UI feature flag: previously accepted evidence can still expire or be revoked.
    """
    if not bindings:
        return
    opportunities.validate_lineage(state, bindings, now)
    if store_factory is None:
        from .store import TrendStore
        store_factory = TrendStore
    store = store_factory(connection_factory)
    locked = [{"kind": kind, "object_id": b[field], **({"revision": b["opportunity_revision"]} if kind == "opportunity" else {})}
              for b in bindings for kind, field in (("opportunity", "opportunity_id"), ("receipt", "trust_receipt_id"), ("trend", "trend_id"))]
    try:
        if read_only:
            store.authorized_scopes(workspace_id,actor,cursor=cursor)
        else:
            store.lock_dependencies(workspace_id, actor, locked, cursor=cursor)
    except contracts.ContractError as exc:
        if str(exc) == "projection_revision_conflict":
            raise error("revision_conflict", 409) from None
        raise error("evidence_unavailable", 410) from None
    for binding in bindings:
        for kind, object_id in (("opportunity", binding["opportunity_id"]), ("receipt", binding["trust_receipt_id"]), ("trend", binding["trend_id"])):
            row = store.get_projection(workspace_id, actor, kind, object_id, cursor=cursor)
            TrendService._current(row, now)
            if kind == "opportunity":
                from .whitespace_admission import validate_opportunity
                validate_opportunity(store,cursor=cursor,workspace_id=workspace_id,actor_id=actor,
                    opportunity={**row['payload'],'workspace_id':workspace_id,'expires_at':opportunities.iso(row['expires_at'])},state=state,mutation=not read_only)
                if row["scope_key"] != "workspace:" + workspace_id or row["revision"] != binding["opportunity_revision"] or row["payload"].get("context_digest") != binding["context_digest"]:
                    raise error("revision_conflict", 409)
            if kind == "receipt" and (row["verification_state"] != "verified" or row["payload"].get("trend_id") != binding["trend_id"]):
                raise error("evidence_unavailable", 410)
            if model_visible and row.get("policy", {}).get("llm_process") is not True:
                raise error("forbidden", 403)


def queue_bindings_current(connection_factory, state, bindings, now):
    """A queue recheck uses the frozen acceptance actor, never client-supplied identity."""
    if not bindings:
        return True
    try:
        with connection_factory() as db, db.cursor() as cur:
            for actor in {b["accepted_by"] for b in bindings}:
                validate_stored_bindings(connection_factory, cur, state["workspace"]["id"], actor, state,
                                        [b for b in bindings if b["accepted_by"] == actor], now)
        return True
    except Exception:
        # Missing migrations, revoked access and database failure cannot authorize a post.
        return False


def validate_changed_variants(connection_factory, cur, workspace_id, before, state, actor, now):
    """Atomic existing variant_edit gate, including Opportunity Lab editor changes."""
    previous = {v["id"]: v for v in before.get("variants", [])}
    for variant in state.get("variants", []):
        bindings = variant.get("trendLineage", [])
        old = previous.get(variant["id"], {})
        if bindings and any(variant.get(k) != old.get(k) for k in ("text", "revision", "trendLineage", "proposedUpdate")):
            validate_stored_bindings(connection_factory, cur, workspace_id, actor, state, bindings, now)

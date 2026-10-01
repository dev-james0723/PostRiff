"""ProofService: versioned Growth Loop proofs and the next-week strategy loop (PRD R-PROOF-01/02).

Extends the existing Growth Loop proof instead of adding a dashboard: the proof id is the Growth Loop formula (the
same id as the existing recap for a UTC workspace), and each recomputation whose material figures changed appends a
revision in ``pr_proof_revisions`` with a correction note. Nothing here starts paid work: every figure is read from
stored application records (Queue receipts, the weekly plan, the Time Back and usage ledgers, and — when those
slices are present — result events and visual-pack exports). An absent or unreadable source is ``unavailable`` with a
reason, never zero.

Strategy decisions (accept / edit / reject / revoke) are owner decisions, versioned in ``pr_strategy_decisions`` and
mirrored into the bounded in-effect projection Weekly planning reads (``proof.strategy``). They never touch identity,
voice, brand, learned preferences or publishing authority.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import logging
import re
import time
from datetime import datetime

from postriff_alpha.domain import AlphaError

from .. import growth_events
from ..permissions import Membership, require
from . import model, require as require_enabled, strategy

KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
PROOF_ID = re.compile(r"^gp_[0-9a-f]{20}$")
DECISION_ID = re.compile(r"^sd_[0-9a-f]{20}$")
PAGE_DEFAULT, PAGE_MAX = 25, 50
RECHECK_SECONDS = 6 * 3600
MAX_HISTORY_DAYS = 400
DECIDE_FIELDS = {"action", "idempotencyKey", "expectedRevision", "statement", "scope"}
REVISION_COLUMNS = ("id::text, proof_id, revision, frequency, extract(epoch from period_start), extract(epoch from period_end), time_zone, time_zone_source, "
                    "definition_version, extract(epoch from as_of), source_watermark, data_state, counts, digest, reason, correction, trigger, extract(epoch from created_at)")
DECISION_COLUMNS = ("id::text, decision_id, revision, status, kind, statement, scope, basis, proof_revision_id::text, extract(epoch from applies_from), "
                    "decided_by::text, idempotency_key, request_digest, extract(epoch from created_at)")
log = logging.getLogger("postriff.proof")


def _member(row):
    return Membership.from_row(*row[2:7])


def _state(row):
    return json.loads(row[1]) if isinstance(row[1], str) else row[1]


def _j(value):
    return json.loads(value) if isinstance(value, str) else value


def _f(value):
    return float(value) if value is not None else None


def _revision(r):
    return {"id": r[0], "proofId": r[1], "revision": r[2], "frequency": r[3], "periodStart": float(r[4]), "periodEnd": float(r[5]), "timeZone": r[6],
            "timeZoneSource": r[7], "definitionVersion": r[8], "asOf": float(r[9]), "sourceWatermark": _j(r[10]), "dataState": r[11], "counts": _j(r[12]),
            "digest": r[13], "reason": r[14], "correction": _j(r[15]), "trigger": r[16], "createdAt": float(r[17])}


def _decision(r):
    return {"id": r[1], "rowId": r[0], "revision": r[2], "status": r[3], "kind": r[4], "statement": r[5], "scope": _j(r[6]) or {}, "basis": _j(r[7]) or {},
            "proofRevisionId": r[8], "appliesFrom": _f(r[9]), "decidedBy": r[10], "idempotencyKey": r[11], "requestDigest": r[12], "createdAt": float(r[13])}


def encode_cursor(at, ident):
    """[exact timestamp, id]: PostgreSQL's own timestamp in ISO form, so no float rounding can skip or repeat a row
    at a page boundary."""
    return base64.urlsafe_b64encode(json.dumps([at.isoformat(), ident]).encode()).decode().rstrip("=")


def decode_cursor(cursor, pattern):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 300:
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str) or not pattern.match(str(value[1])):
            raise ValueError()
        if datetime.fromisoformat(value[0]).tzinfo is None:
            raise ValueError()
        return value[0], str(value[1])
    except (ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error):
        raise AlphaError("This page cursor is invalid.", 400, code="invalid_cursor") from None


def page_limit(value):
    if value is None or value == "":
        return PAGE_DEFAULT
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AlphaError(f"Choose a page size from 1 to {PAGE_MAX}.", 400) from None
    if not 1 <= number <= PAGE_MAX:
        raise AlphaError(f"Choose a page size from 1 to {PAGE_MAX}.", 400)
    return number


def _scope_label(scope):
    scope = scope or {}
    return "format" if scope.get("contentType") else "language" if scope.get("language") else "account" if scope.get("channelId") else "goal" if scope.get("goalId") else "workspace"


class ProofService:
    def __init__(self, hosted):
        self.hosted = hosted
        self.clock = getattr(hosted, "clock", None) or time.time
        self._modules = {}

    @property
    def repository(self):
        return self.hosted.repository

    @staticmethod
    def _session(token):
        if str(token).startswith("prt_"):
            raise AlphaError("API tokens can't use Rafii proof routes.", 403)

    def _optional(self, name):
        """A sibling slice's module, or None while that slice is not in this build."""
        if name not in self._modules:
            try:
                self._modules[name] = importlib.import_module(name)
            except ModuleNotFoundError as error:
                if error.name and name.startswith(error.name):
                    self._modules[name] = None
                else:
                    raise
        return self._modules[name]

    # --- zone and period ----------------------------------------------------------------------------------------------
    def _zone(self, cur, workspace_id, state):
        from ..notifications import planner, store
        cur.execute("""SELECT m.user_id::text, coalesce(p.time_zone,'') FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
                       WHERE m.workspace_id=%s AND m.role='owner' AND m.status='active' AND p.deleted_at IS NULL ORDER BY m.user_id LIMIT 1""", (workspace_id,))
        owner = cur.fetchone()
        preference = profile = None
        if owner:
            preference = planner.effective_preferences(store.preference_rows(cur, owner[0]), workspace_id, "analytics").get("time_zone")
            profile = owner[1] or None
        return model.workspace_zone(state, preference, profile)

    # --- figures ------------------------------------------------------------------------------------------------------
    def _savepoint(self, cur, name, read, fallback):
        cur.execute(f"SAVEPOINT {name}")
        try:
            value = read()
            cur.execute(f"RELEASE SAVEPOINT {name}")
            return value
        except Exception as error:  # noqa: BLE001 - one unreadable source never fails the proof or hides the others
            cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
            log.warning(json.dumps({"event": "proof.source_unreadable", "source": name, "reason": type(error).__name__}))
            return fallback

    def _assisted(self, cur, workspace_id, start, end):
        definition = "Assisted exports (export ready, downloaded, confirmed used), counted apart from verified publications and never added to them."
        module = self._optional("postriff_phase2.visual_pack.service")
        if module is None or not hasattr(module, "handoff_counts"):
            return model.unavailable(definition, "visual_pack_unavailable")

        def read():
            raw = module.handoff_counts(cur, workspace_id, start, end) or {}
            value = {k: int(raw[k]) for k in ("exportReady", "downloaded", "userConfirmedUsed") if isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool)}
            if not value:
                return model.unavailable(definition, "visual_pack_no_counts")
            evidence = {"packIds": raw.get("packIds") or raw.get("evidenceIds") or []}
            return model.figure(value, definition=definition, evidence=evidence, data_state=raw.get("dataState") if raw.get("dataState") in ("available", "partial") else "available",
                                evidenceQuery={"resource": "visual-packs", "from": start, "to": end})
        return self._savepoint(cur, "proof_assisted", read, model.unavailable(definition, "visual_pack_unreadable"))

    def _outcomes(self, cur, workspace_id, start, end):
        definition = "Qualified results by provenance (provider-native, first-party reported, user declared); never one blended number, unavailable is not zero."
        module = self._optional("postriff_phase2.results.service")
        if module is None or not hasattr(module, "period_summary"):
            return model.unavailable(definition, "results_unavailable")

        def read():
            raw = module.period_summary(cur, workspace_id, start, end) or {}
            value = {p: model.jsonable(raw.get(p)) for p in ("provider_native", "first_party_reported", "user_declared")}
            state = raw.get("dataState") if raw.get("dataState") in ("available", "partial", "unavailable") else "partial"
            return model.figure(value, definition=raw.get("definition") and f"{definition} Association: {raw['definition']}." or definition,
                                evidence={"resultIds": raw.get("evidenceIds") or raw.get("resultIds") or []}, data_state=state,
                                asOf=model.jsonable(raw.get("asOf")), evidenceQuery={"resource": "results", "from": start, "to": end})
        return self._savepoint(cur, "proof_outcomes", read, model.unavailable(definition, "results_unreadable"))

    def _time_back(self, cur, workspace_id, start, end):
        definition = "Time Back by its existing confidence classes; estimated, personalized and measured are never added into one measured figure."

        window = "workspace_id=%s AND occurred_at>=to_timestamp(%s) AND occurred_at<to_timestamp(%s)"

        def read():
            cur.execute(f"""SELECT confidence, count(*), coalesce(sum(saved_seconds),0), extract(epoch from max(created_at)) FROM public.pr_time_savings_ledger
                            WHERE {window} GROUP BY confidence""", (workspace_id, start, end))
            rows = cur.fetchall()
            classes = {c: {"confidence": c, "outcomes": int(n), "savedSeconds": int(seconds)} for c, n, seconds, _latest in rows}
            evidence = {}
            for confidence in classes:   # totals are exact; the evidence ids shown are bounded and flagged when truncated
                cur.execute(f"SELECT id::text FROM public.pr_time_savings_ledger WHERE {window} AND confidence=%s ORDER BY occurred_at, id LIMIT %s",
                            (workspace_id, start, end, confidence, model.EVIDENCE_LIMIT + 1))
                evidence[f"{confidence}LedgerIds"] = [r[0] for r in cur.fetchall()]
            out = model.figure([classes[c] for c in ("estimated", "personalized", "measured") if c in classes], definition=definition, evidence=evidence)
            out["watermark"] = max((float(r[3]) for r in rows if r[3] is not None), default=None)
            return out
        return self._savepoint(cur, "proof_time_back", read, model.unavailable(definition, "time_back_unreadable"))

    def _cost(self, cur, workspace_id, start, end):
        definition = ("What AI and data services cost for this period: the actual amount where the charge is settled; charges whose amount is "
                      "unknown are listed separately at their reserved estimate and never counted as zero. Owners only.")

        window = "workspace_id=%s AND at>=to_timestamp(%s) AND at<to_timestamp(%s) AND cost_state IN ('actual','estimated_unknown')"
        kind = "CASE WHEN cost_state='actual' AND actual_usd_micro IS NOT NULL THEN 'actual' ELSE 'unknown' END"

        def read():
            cur.execute(f"""SELECT {kind}, count(*), coalesce(sum(actual_usd_micro),0), coalesce(sum(estimated_usd_micro),0), extract(epoch from max(at))
                            FROM public.pr_usage_ledger WHERE {window} GROUP BY 1""", (workspace_id, start, end))
            totals = {r[0]: r for r in cur.fetchall()}
            evidence = {}
            for name in ("actual", "unknown"):   # exact totals; bounded, flagged evidence ids
                cur.execute(f"SELECT id::text FROM public.pr_usage_ledger WHERE {window} AND {kind}=%s ORDER BY at, id LIMIT %s",
                            (workspace_id, start, end, name, model.EVIDENCE_LIMIT + 1))
                evidence[f"{name}LedgerIds"] = [r[0] for r in cur.fetchall()]
            actual, unknown = totals.get("actual"), totals.get("unknown")
            value = {"actualUsdMicro": int(actual[2]) if actual else 0, "actualEntries": int(actual[1]) if actual else 0,
                     "unknownEntries": int(unknown[1]) if unknown else 0, "unknownReservedEstimateUsdMicro": int(unknown[3]) if unknown else 0}
            out = model.figure(value, definition=definition, evidence=evidence, data_state="partial" if unknown else "available", visibility="owner")
            out["watermark"] = max((float(r[4]) for r in totals.values() if r[4] is not None), default=None)
            return out
        return self._savepoint(cur, "proof_cost", read, model.unavailable(definition, "usage_ledger_unreadable"))

    def compute(self, cur, workspace_id, state, frequency, start, end, zone_name, zone_source, now):
        from ..coworker import growth_loop
        legacy = growth_loop.proof_counts(state, start, end)
        jobs = [j for j in (state.get("phase2") or {}).get("jobs") or [] if j.get("id") in set(legacy["evidence"]["jobIds"])]
        verified_times = [growth_loop.verified_at(j) for j in jobs if growth_loop.verified_at(j)]
        figures = {
            "acceptedWork": model.figure(legacy["preparedPosts"], evidence={"variantIds": legacy["evidence"]["variantIds"]}, approved=legacy["approvedPosts"],
                                         definition="Drafts accepted into a weekly plan or approved for Queue in this period; unused drafts and failed publishes are excluded."),
            "verifiedPublications": model.figure(legacy["verifiedPublishedPosts"], evidence={"jobIds": legacy["evidence"]["jobIds"]},
                                                 definition="Posts the platform confirmed as published (read back through Queue) in this period. An export, a download or an accepted request is not a verified publication."),
            "assistedExports": self._assisted(cur, workspace_id, start, end),
            "unresolvedSlots": model.unresolved_slots(state, start, end),
            "outcomes": self._outcomes(cur, workspace_id, start, end),
            "timeBack": self._time_back(cur, workspace_id, start, end),
            "providerCost": self._cost(cur, workspace_id, start, end),
        }
        watermark = {"queue": max(verified_times) if verified_times else None, "timeBack": figures["timeBack"].pop("watermark", None),
                     "usage": figures["providerCost"].pop("watermark", None), "results": figures["outcomes"].get("asOf")}
        mature = model.maturity(end, now)
        return {"definitionVersion": model.DEFINITION_VERSION, "frequency": frequency,
                "period": {"start": start, "end": end, "timeZone": zone_name, "timeZoneSource": zone_source,
                           "label": f"{model.local_date(start, zone_name)}/{model.local_date(end - 1, zone_name)}"},
                "asOf": now, "sourceWatermark": watermark, "maturity": mature, "dataState": model.overall_state(figures, mature["mature"]),
                "figures": figures, "coverage": [{"figure": name, "dataState": f["dataState"], "reason": f.get("reason")} for name, f in figures.items()],
                "limitations": list(model.LIMITATIONS)}

    # --- revisions ----------------------------------------------------------------------------------------------------
    def _revisions(self, cur, workspace_id, proof_id, limit=50):
        cur.execute(f"SELECT {REVISION_COLUMNS} FROM public.pr_proof_revisions WHERE workspace_id=%s AND proof_id=%s ORDER BY revision DESC LIMIT %s",
                    (workspace_id, proof_id, limit))
        return [_revision(r) for r in cur.fetchall()]

    def append(self, cur, workspace_id, counts, trigger, now):
        """Append a revision when the material figures differ from the latest one; (revision, appended)."""
        proof = model.proof_id(workspace_id, counts["frequency"], counts["period"]["start"])
        latest = (self._revisions(cur, workspace_id, proof, 1) or [None])[0]
        digest = model.digest(counts)
        if latest and latest["digest"] == digest:
            return latest, False
        reason = "initial" if latest is None else "definition_change" if latest["definitionVersion"] != counts["definitionVersion"] else "late_data"
        correction = model.corrections(latest["counts"], counts) if latest else []
        cur.execute(f"""INSERT INTO public.pr_proof_revisions(workspace_id,proof_id,revision,frequency,period_start,period_end,time_zone,time_zone_source,
                                   definition_version,as_of,source_watermark,data_state,counts,digest,reason,correction,trigger,created_at)
                        VALUES(%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),%s,%s,%s,to_timestamp(%s),%s::jsonb,%s,%s::jsonb,%s,%s,%s::jsonb,%s,to_timestamp(%s))
                        RETURNING {REVISION_COLUMNS}""",
                    (workspace_id, proof, (latest["revision"] + 1) if latest else 1, counts["frequency"], counts["period"]["start"], counts["period"]["end"],
                     counts["period"]["timeZone"], counts["period"]["timeZoneSource"], counts["definitionVersion"], now, json.dumps(counts["sourceWatermark"]),
                     counts["dataState"], json.dumps(counts), digest, reason, json.dumps(correction), trigger, now))
        revision = _revision(cur.fetchone())
        growth_events.emit(cur, workspace_id=workspace_id, event="proof.revised", entity_id=proof, revision=revision["revision"], user_id=None,
                           values={"frequency": counts["frequency"], "reason": reason, "revision": revision["revision"]})
        return revision, True

    # --- strategy proposals -------------------------------------------------------------------------------------------
    def _brief_actions(self, cur, workspace_id, start, end):
        cur.execute("""SELECT id::text, item_id, action, outcome_refs FROM public.pr_brief_actions WHERE workspace_id=%s AND action IN ('accept','save_idea')
                       AND created_at>=to_timestamp(%s) AND created_at<to_timestamp(%s) ORDER BY created_at, id LIMIT 50""", (workspace_id, start, end))
        out = []
        for ident, item, action, refs in cur.fetchall():
            refs = _j(refs) or []
            out.append({"id": ident, "itemId": item, "action": action, "outcomeRefs": refs,
                        "channelId": next((r.get("id") for r in refs if r.get("type") == "channel"), None)})
        return out

    def ensure_proposals(self, cur, workspace_id, state, revision, now):
        """Store this proof's proposals as `proposed` version 1 rows; an id that already exists (in any status — a
        rejected or revoked one included) is never offered again."""
        actions = self._savepoint(cur, "proof_brief_actions", lambda: self._brief_actions(cur, workspace_id, revision["periodStart"], revision["periodEnd"]), [])
        created = []
        for proposal in strategy.proposals(state, workspace_id, actions, now):
            cur.execute("""INSERT INTO public.pr_strategy_decisions(workspace_id,decision_id,revision,status,kind,statement,scope,basis,proof_revision_id,created_at)
                           SELECT %s,%s,1,'proposed',%s,%s,%s::jsonb,%s::jsonb,%s,to_timestamp(%s)
                           WHERE NOT EXISTS (SELECT 1 FROM public.pr_strategy_decisions WHERE workspace_id=%s AND decision_id=%s)
                           ON CONFLICT (workspace_id,decision_id,revision) DO NOTHING RETURNING decision_id""",
                        (workspace_id, proposal["id"], proposal["kind"], proposal["statement"], json.dumps(proposal["scope"]),
                         json.dumps({**proposal["basis"], "proofId": revision["proofId"]}), revision["id"], now, workspace_id, proposal["id"]))
            if cur.fetchone():
                created.append(proposal["id"])
        return created

    def _latest_decisions(self, cur, workspace_id, decision_ids=None, proof_revision_ids=None):
        sql = f"SELECT DISTINCT ON (decision_id) {DECISION_COLUMNS} FROM public.pr_strategy_decisions WHERE workspace_id=%s"
        params = [workspace_id]
        if decision_ids is not None:
            sql += " AND decision_id = ANY(%s)"
            params.append(list(decision_ids))
        if proof_revision_ids is not None:
            sql += " AND decision_id IN (SELECT decision_id FROM public.pr_strategy_decisions WHERE workspace_id=%s AND revision=1 AND proof_revision_id = ANY(%s::uuid[]))"
            params += [workspace_id, list(proof_revision_ids)]
        cur.execute(sql + " ORDER BY decision_id, revision DESC", params)
        return [_decision(r) for r in cur.fetchall()]

    # --- presentation -------------------------------------------------------------------------------------------------
    @staticmethod
    def _redact(counts, owner):
        counts = copy.deepcopy(counts)
        if not owner and "providerCost" in counts.get("figures", {}):
            counts["figures"]["providerCost"] = {"value": None, "dataState": "restricted", "reason": "owner_only",
                                                 "definition": "Provider cost is visible to workspace owners.", "evidence": {}, "evidenceTruncated": False}
        return counts

    def _decision_view(self, decision):
        return {k: decision[k] for k in ("id", "revision", "status", "kind", "statement", "scope", "appliesFrom", "createdAt")} | {
            "basis": {k: v for k, v in decision["basis"].items() if k in ("experimentId", "sourceId", "briefActionId", "proofId", "supportedFactor", "dimension")},
            "inEffect": decision["status"] in strategy.IN_EFFECT,
            "actions": sorted(strategy.TRANSITIONS.get(decision["status"], {}))}

    def _proof_view(self, cur, workspace_id, revisions, member, now, legacy_ids):
        latest = revisions[0]
        owner = member.role == "owner"
        decisions = self._latest_decisions(cur, workspace_id, proof_revision_ids=[r["id"] for r in revisions])
        return {"proofId": latest["proofId"], "frequency": latest["frequency"], "periodStart": latest["periodStart"], "periodEnd": latest["periodEnd"],
                "timeZone": latest["timeZone"], "timeZoneSource": latest["timeZoneSource"], "legacyRecap": latest["proofId"] in legacy_ids,
                "maturity": model.maturity(latest["periodEnd"], now), "href": f"/app/analytics?proof={latest['proofId']}#proof-history",
                "latest": {**{k: latest[k] for k in ("id", "revision", "definitionVersion", "asOf", "sourceWatermark", "dataState", "reason", "correction", "createdAt")},
                           "counts": self._redact(latest["counts"], owner)},
                "revisions": [{k: r[k] for k in ("id", "revision", "asOf", "dataState", "reason", "correction", "createdAt", "definitionVersion")} for r in revisions],
                "nextStep": {"proposals": [self._decision_view(d) for d in sorted(decisions, key=lambda d: (d["createdAt"], d["id"]))],
                             "rule": "Deterministic proposals from measured experiments and ideas saved from your brief; no model call. Rejected or revoked proposals do not return."}}

    @staticmethod
    def _legacy_ids(state):
        return {p.get("id") for p in ((state.get("coworker") or {}).get("growthLoop") or {}).get("proofs") or []}

    def list(self, workspace_id, token, frequency=None, cursor=None, limit=None):
        require_enabled()
        self._session(token)
        if frequency not in (None, "", "weekly", "monthly"):
            raise AlphaError("Choose weekly or monthly.", 400)
        size, before = page_limit(limit), decode_cursor(cursor, PROOF_ID)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, _principal):
            member = _member(row)
            require(member, "read")
            sql = """SELECT proof_id, period_start FROM (SELECT DISTINCT ON (proof_id) proof_id, period_start, frequency
                     FROM public.pr_proof_revisions WHERE workspace_id=%s ORDER BY proof_id, revision DESC) latest WHERE (%s::text IS NULL OR frequency=%s)"""
            params = [workspace_id, frequency or None, frequency or None]
            if before:
                sql += " AND (period_start, proof_id) < (%s::timestamptz, %s)"
                params += list(before)
            cur.execute(sql + " ORDER BY period_start DESC, proof_id DESC LIMIT %s", params + [size + 1])
            found = cur.fetchall()
            page, more = found[:size], len(found) > size
            legacy = self._legacy_ids(_state(row))
            proofs = [self._proof_view(cur, workspace_id, self._revisions(cur, workspace_id, proof_id, 20), member, now, legacy) for proof_id, _start in page]
            return {"proofs": proofs, "definitionVersion": model.DEFINITION_VERSION, "asOf": now,
                    "nextCursor": encode_cursor(page[-1][1], page[-1][0]) if more and page else None}

    def get(self, workspace_id, token, proof_id):
        require_enabled()
        self._session(token)
        if not isinstance(proof_id, str) or not PROOF_ID.match(proof_id):
            raise AlphaError("Proof unavailable.", 404)
        with self.repository.transaction(token, workspace_id) as (cur, row, _principal):
            member = _member(row)
            require(member, "read")
            revisions = self._revisions(cur, workspace_id, proof_id)
            if not revisions:
                raise AlphaError("Proof unavailable.", 404)
            return {"proof": self._proof_view(cur, workspace_id, revisions, member, self.clock(), self._legacy_ids(_state(row)))}

    def revision(self, workspace_id, token, proof_id, number):
        require_enabled()
        self._session(token)
        if not isinstance(proof_id, str) or not PROOF_ID.match(proof_id) or not str(number).isdigit():
            raise AlphaError("Proof revision unavailable.", 404)
        with self.repository.transaction(token, workspace_id) as (cur, row, _principal):
            member = _member(row)
            require(member, "read")
            cur.execute(f"SELECT {REVISION_COLUMNS} FROM public.pr_proof_revisions WHERE workspace_id=%s AND proof_id=%s AND revision=%s",
                        (workspace_id, proof_id, int(number)))
            found = cur.fetchone()
            if not found:
                raise AlphaError("Proof revision unavailable.", 404)
            revision = _revision(found)
            return {"revision": {**{k: v for k, v in revision.items() if k not in ("counts", "digest")}, "counts": self._redact(revision["counts"], member.role == "owner")}}

    def refresh(self, workspace_id, token, payload):
        """Owner: recompute one completed period (the latest by default) from stored records; append a revision only
        when material figures changed. A period still in progress is unavailable, not a provisional proof."""
        require_enabled()
        self._session(token)
        payload = payload if isinstance(payload, dict) else {}
        if set(payload) - {"frequency", "periodStart"}:
            raise AlphaError("Refresh takes a frequency and an optional period start.", 400)
        frequency = payload.get("frequency", "weekly")
        if frequency not in model.FREQUENCIES:
            raise AlphaError("Choose weekly or monthly.", 400)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = _member(row)
            require(member, "owner")
            state = _state(row)
            zone_name, zone_source = self._zone(cur, workspace_id, state)
            if payload.get("periodStart") is not None:
                bounds = model.period_for(payload["periodStart"], frequency, zone_name)
                if bounds is None:
                    raise AlphaError("Choose the local start date of a period (a Monday, or the 1st of a month).", 400)
            else:
                bounds = model.latest_completed(now, frequency, zone_name)
            start, end = bounds
            if end > now:
                return {"proof": None, "appended": False, "dataState": "unavailable", "reason": "period_in_progress",
                        "period": {"start": start, "end": end, "timeZone": zone_name}, "verified": True}
            if start < now - MAX_HISTORY_DAYS * 86400:
                raise AlphaError("That period is older than the records a proof can use.", 409, code="source_unavailable")
            counts = self.compute(cur, workspace_id, state, frequency, start, end, zone_name, zone_source, now)
            revision, appended = self.append(cur, workspace_id, counts, "user", now)
            self.ensure_proposals(cur, workspace_id, state, revision, now)
            if appended:
                from ..hosted import audit
                audit(cur, workspace_id, principal, "proof.revised", revision["proofId"], {"revision": revision["revision"], "reason": revision["reason"], "frequency": frequency})
            revisions = self._revisions(cur, workspace_id, revision["proofId"], 20)
            view = self._proof_view(cur, workspace_id, revisions, member, now, self._legacy_ids(state))
            return {"proof": view, "appended": appended, "revision": revision["revision"], "verified": view["latest"]["id"] == revision["id"]}

    # --- strategy decisions -------------------------------------------------------------------------------------------
    def strategy(self, workspace_id, token, status=None, cursor=None, limit=None):
        require_enabled()
        self._session(token)
        if status not in (None, "", *strategy.STATUSES):
            raise AlphaError("Choose a decision status.", 400)
        size, before = page_limit(limit), decode_cursor(cursor, DECISION_ID)
        with self.repository.transaction(token, workspace_id) as (cur, row, _principal):
            member = _member(row)
            require(member, "read")
            sql = f"""SELECT * FROM (SELECT DISTINCT ON (decision_id) {DECISION_COLUMNS}, created_at AS latest_at FROM public.pr_strategy_decisions
                      WHERE workspace_id=%s ORDER BY decision_id, revision DESC) latest WHERE (%s::text IS NULL OR status=%s)"""
            params = [workspace_id, status or None, status or None]
            if before:
                sql += " AND (latest_at, decision_id) < (%s::timestamptz, %s)"
                params += list(before)
            cur.execute(sql + " ORDER BY latest_at DESC, decision_id DESC LIMIT %s", params + [size + 1])
            found = cur.fetchall()
            rows = [_decision(r[:14]) for r in found]
            page, more = rows[:size], len(rows) > size
            last_at = found[len(page) - 1][14] if page else None
            history = {}
            if page:
                cur.execute("""SELECT decision_id, revision, status, decided_by::text, extract(epoch from created_at) FROM public.pr_strategy_decisions
                               WHERE workspace_id=%s AND decision_id = ANY(%s) ORDER BY decision_id, revision""", (workspace_id, [d["id"] for d in page]))
                for decision_id, number, state_name, decided_by, at in cur.fetchall():
                    history.setdefault(decision_id, []).append({"revision": number, "status": state_name, "decidedBy": decided_by, "at": float(at)})
            projection = strategy.active(_state(row))
            return {"decisions": [{**self._decision_view(d), "versions": history.get(d["id"], [])[-20:]} for d in page],
                    "inEffect": [{k: d.get(k) for k in ("id", "revision", "kind", "statement", "scope", "appliesFromDate")} for d in projection],
                    "canDecide": member.role == "owner",
                    "nextCursor": encode_cursor(last_at, page[-1]["id"]) if more and page else None}

    @staticmethod
    def _decide_request(decision_id, payload):
        if not isinstance(decision_id, str) or not DECISION_ID.match(decision_id):
            raise AlphaError("Decision unavailable.", 404)
        if not isinstance(payload, dict) or set(payload) - DECIDE_FIELDS:
            raise AlphaError("This decision has unknown fields.", 400)
        action = payload.get("action")
        if action not in ("accept", "edit", "reject", "revoke"):
            raise AlphaError("Choose accept, edit, reject or revoke.", 400)
        key = payload.get("idempotencyKey")
        if not isinstance(key, str) or not KEY.match(key):
            raise AlphaError("An idempotency key of 8–80 letters, numbers, underscores or hyphens is required.", 400)
        expected = payload.get("expectedRevision")
        if type(expected) is not int or expected < 1:
            raise AlphaError("Send the decision revision you reviewed.", 400)
        if action != "edit" and (payload.get("statement") is not None or payload.get("scope") is not None):
            raise AlphaError("Only an edit changes the wording or scope.", 400)
        request = {"decisionId": decision_id, "action": action, "key": key, "expectedRevision": expected,
                   "statement": strategy.clean_statement(payload["statement"]) if payload.get("statement") is not None else None,
                   "scope": payload.get("scope")}
        request["requestDigest"] = hashlib.sha256(json.dumps({k: v for k, v in request.items() if k != "key"}, sort_keys=True).encode()).hexdigest()
        return request

    def decide(self, workspace_id, token, decision_id, payload):
        """Owner: accept / edit / reject / revoke one next-week decision. Appends a version, updates the in-effect
        projection in the same transaction, and never touches identity, voice or publishing."""
        require_enabled()
        self._session(token)
        request = self._decide_request(decision_id, payload)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "owner")
            cur.execute(f"SELECT {DECISION_COLUMNS} FROM public.pr_strategy_decisions WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, request["key"]))
            prior = cur.fetchone()
            if prior:
                prior = _decision(prior)
                if prior["decidedBy"] != principal or prior["requestDigest"] != request["requestDigest"]:
                    raise AlphaError("This request key already belongs to a different decision.", 409, code="idempotency_conflict")
                return {"decision": self._decision_view(prior), "replayed": True, "verified": True}
            latest = (self._latest_decisions(cur, workspace_id, [decision_id]) or [None])[0]
            if latest is None:
                raise AlphaError("Decision unavailable.", 404)
            if latest["revision"] != request["expectedRevision"]:
                raise AlphaError("This decision changed since you reviewed it. Review the current version.", 409, code="revision_conflict")
            target = strategy.transition(latest["status"], request["action"])
            state = _state(row)
            statement, scope = latest["statement"], latest["scope"]
            if request["action"] == "edit":
                statement = request["statement"] or latest["statement"]
                scope = strategy.narrow(latest["scope"], request["scope"], state)
                if statement == latest["statement"] and scope == latest["scope"]:
                    raise AlphaError("Change the wording or narrow the scope, or accept it as it is.", 400)
            applies_from = latest["appliesFrom"]
            applies_date = None
            if target in strategy.IN_EFFECT:
                zone_name, _source = self._zone(cur, workspace_id, state)
                if latest["status"] == "proposed" or applies_from is None:
                    applies_from, applies_date = strategy.next_week_start(now, zone_name)
                else:
                    applies_date = model.local_date(applies_from, zone_name)
            cur.execute(f"""INSERT INTO public.pr_strategy_decisions(workspace_id,decision_id,revision,status,kind,statement,scope,basis,proof_revision_id,
                                       applies_from,decided_by,idempotency_key,request_digest,created_at)
                            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,to_timestamp(%s),%s,%s,%s,to_timestamp(%s)) RETURNING {DECISION_COLUMNS}""",
                        (workspace_id, decision_id, latest["revision"] + 1, target, latest["kind"], statement, json.dumps(scope), json.dumps(latest["basis"]),
                         latest["proofRevisionId"], applies_from, principal, request["key"], request["requestDigest"], now))
            record = _decision(cur.fetchone())
            before = copy.deepcopy(state)
            strategy.project(state, {**record, "appliesFromDate": applies_date, "decidedAt": now})
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            for effect in getattr(self.repository, "effects", []):
                effect(cur, workspace_id, before, state, principal)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "strategy.decided", decision_id, {"decision": request["action"], "status": target, "revision": record["revision"],
                                                                                 "scope": _scope_label(scope)})
            growth_events.emit(cur, workspace_id=workspace_id, event="strategy.decided", entity_id=decision_id, revision=record["revision"], user_id=principal,
                               values={"decision": request["action"], "scope": _scope_label(scope)})
            projected = next((d for d in strategy.active(state) if d["id"] == decision_id), None)
        verified = (projected is not None) == (target in strategy.IN_EFFECT) and (projected is None or projected["revision"] == record["revision"])
        return {"decision": self._decision_view(record), "replayed": False, "verified": verified,
                "planning": {"inEffect": projected is not None, "appliesFromDate": applies_date,
                             "note": "Applies to weekly plans from that week on; it never changes your voice or approves anything."}}

    # --- cron ---------------------------------------------------------------------------------------------------------
    def cron(self, deadline, max_workspaces=10):
        """Recompute recent periods for workspaces that use the Growth Loop (bounded; system trigger; no paid I/O)."""
        now = self.clock()
        summary = {"status": "ok", "workspaces": 0, "appended": 0, "proposals": 0, "skipped": {}}
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT w.id::text FROM public.pr_workspaces w LEFT JOIN public.pr_proof_schedule s ON s.workspace_id=w.id
                           WHERE w.state->'coworker'->'growthLoop' IS NOT NULL AND NOT w.state ? 'accountDeletion'
                             AND coalesce(w.state->'workspace'->>'sample','false')<>'true'
                             AND (s.checked_at IS NULL OR s.checked_at < to_timestamp(%s))
                           ORDER BY s.checked_at NULLS FIRST, w.id LIMIT %s""", (now - RECHECK_SECONDS, max_workspaces))
            workspaces = [r[0] for r in cur.fetchall()]
        for workspace_id in workspaces:
            if time.monotonic() >= deadline:
                summary["status"] = "deferred"
                break
            try:
                outcome = self.recompute_workspace(workspace_id, now)
            except Exception as error:  # noqa: BLE001 - one workspace never stops the others; reason codes only
                reason = getattr(error, "code", None) or type(error).__name__
                summary["skipped"][reason] = summary["skipped"].get(reason, 0) + 1
                log.warning(json.dumps({"event": "proof.workspace_failed", "reason": str(reason)[:60]}))
                continue
            summary["workspaces"] += 1
            summary["appended"] += outcome["appended"]
            summary["proposals"] += outcome["proposals"]
        return summary

    def recompute_workspace(self, workspace_id, now):
        appended = proposals = 0
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
            found = cur.fetchone()
            state = _j(found[0]) if found else None
            if isinstance(state, dict) and not state.get("accountDeletion"):
                from ..coworker import growth_loop
                loop = growth_loop.view(state)
                activations = [r.get("createdAt") for name in ("goals", "experiments") for r in loop.get(name) or [] if isinstance(r.get("createdAt"), (int, float))]
                zone_name, zone_source = self._zone(cur, workspace_id, state)
                periods = []
                week = model.latest_completed(now, "weekly", zone_name)
                periods.append(("weekly", week))
                previous = model.latest_completed(week[0], "weekly", zone_name)
                if now < previous[1] + model.MATURITY_SECONDS + 7 * 86400:   # late data for last week's predecessor still lands
                    periods.append(("weekly", previous))
                periods.append(("monthly", model.latest_completed(now, "monthly", zone_name)))
                for frequency, (start, end) in periods:
                    if not activations or min(activations) >= end:
                        continue   # no recap about a period before the Growth Loop was used
                    counts = self.compute(cur, workspace_id, state, frequency, start, end, zone_name, zone_source, now)
                    revision, added = self.append(cur, workspace_id, counts, "system", now)
                    appended += int(added)
                    if frequency == "weekly" and (start, end) == week:
                        proposals += len(self.ensure_proposals(cur, workspace_id, state, revision, now))
            cur.execute("""INSERT INTO public.pr_proof_schedule(workspace_id,checked_at) VALUES(%s,to_timestamp(%s))
                           ON CONFLICT (workspace_id) DO UPDATE SET checked_at=excluded.checked_at""", (workspace_id, now))
            db.commit()
        return {"appended": appended, "proposals": proposals}

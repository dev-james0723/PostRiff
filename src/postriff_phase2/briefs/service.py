"""BriefService: compose, store, deliver and act on opportunity briefs (PRD R-BRF-01/02).

* ``current`` (GET) composes this person's brief from stored evidence only and writes nothing: no edition, no
  research, no provider or model call, no Radar quote/start/advance. When the same material is already stored, the
  stored edition (with its id, revision and delivery receipt) is returned; otherwise the composition is transient.
* ``action`` records accept / save_idea / dismiss / not_relevant / restore for one item, persisting the shown
  edition snapshot first when it was transient. Accepting a trend opportunity and saving a Radar idea go through
  those features' own (idempotent, free) services; saving a listening opportunity creates an idea source in the same
  transaction. Each action keeps its reason code and outcome references (the created source), not just an open.
* ``cron`` (bounded) stores each recipient's weekly edition and alerts at most once per edition and per local day,
  through the existing notification outbox and its preferences (quiet hours, DST, digest, mute, unsubscribe).

Every authenticated operation runs in the repository transaction (workspace + member re-checked); API tokens never
reach these routes.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import datetime

from postriff_alpha.domain import AlphaError

from .. import growth_events
from ..permissions import Membership, require
from . import composer, enabled as _flag_enabled, require as require_enabled, sources

KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ITEM = re.compile(r"^bi_[0-9a-f]{20}$")
PAGE_DEFAULT, PAGE_MAX = 25, 50
EVENT_TYPE = "opportunity.brief_ready"
ENTITY_TYPE = "brief_edition"
HREF = "/app/weekly?brief=1#opportunity-brief"
CADENCE = "weekly"
RECHECK_SECONDS = 6 * 3600
RECIPIENT_ROLES = ("owner", "admin", "editor")
ACTION_FIELDS = {"action", "idempotencyKey", "editionId", "materialDigest", "reasonCode", "angleId", "channelId", "goal"}
EDITION_COLUMNS = ("id::text, edition_key, revision, cadence, extract(epoch from period_start), extract(epoch from period_end), time_zone, "
                   "material_digest, data_state, coverage, items, extract(epoch from delivered_at), extract(epoch from created_at), recipient_user_id::text")
ACTION_COLUMNS = ("id::text, edition_id::text, item_id, source, source_ref, action, reason_code, effort, outcome_refs, actor_user_id::text, "
                  "request_digest, extract(epoch from created_at)")
log = logging.getLogger("postriff.briefs")


def enabled(values=None):
    """Whether the opportunity brief is on (RAFII_OPPORTUNITY_BRIEF_ENABLED, default off; true only for
    1/true/yes/on). `values` when given; otherwise the process environment as the hosted app sees it (its isolated
    environment once attached), exactly as every route and the cron step read it."""
    return _flag_enabled(values)


def _member(row):
    return Membership.from_row(*row[2:7])


def _state(row):
    return json.loads(row[1]) if isinstance(row[1], str) else row[1]


def _f(value):
    return float(value) if value is not None else None


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def encode_cursor(at, ident):
    """[exact timestamp, id]: PostgreSQL's own timestamp in ISO form, so no float rounding skips or repeats a row."""
    return base64.urlsafe_b64encode(json.dumps([at.isoformat(), ident]).encode()).decode().rstrip("=")


def decode_cursor(cursor):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 300:
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str) or not UUID.match(str(value[1])):
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


def _edition(r):
    return {"id": r[0], "editionKey": r[1], "revision": r[2], "cadence": r[3], "periodStart": float(r[4]), "periodEnd": float(r[5]),
            "timeZone": r[6], "materialDigest": r[7], "dataState": r[8], "coverage": _json(r[9]), "items": _json(r[10]),
            "deliveredAt": _f(r[11]), "createdAt": float(r[12]), "recipient": r[13]}


def _action(r):
    return {"id": r[0], "editionId": r[1], "itemId": r[2], "source": r[3], "sourceRef": r[4], "action": r[5], "reasonCode": r[6],
            "effort": r[7], "outcomeRefs": _json(r[8]) or [], "actor": r[9], "requestDigest": r[10], "createdAt": float(r[11])}


def recipient_zone(cur, workspace_id, user_id):
    """The recipient's zone for editions and the daily cap: their notification preference zone (this workspace, then
    their defaults), else their profile zone, else UTC — the same order the notification planner uses."""
    from ..notifications import planner, store
    zone = planner.effective_preferences(store.preference_rows(cur, user_id), workspace_id, "opportunities").get("time_zone")
    if not zone:
        cur.execute("SELECT coalesce(time_zone,'') FROM public.pr_profiles WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        zone = row[0] if row and row[0] else "UTC"
    return composer.zone(zone).key


class BriefService:
    def __init__(self, hosted):
        self.hosted = hosted
        self.clock = getattr(hosted, "clock", None) or time.time

    @property
    def repository(self):
        return self.hosted.repository

    @staticmethod
    def _session(token):
        if str(token).startswith("prt_"):
            raise AlphaError("API tokens can't use Rafii briefs.", 403)

    def _growth_env(self):
        env = getattr(getattr(self.hosted, "growth", None), "env", None)
        return env if isinstance(env, dict) else dict(os.environ)

    # --- reads ------------------------------------------------------------------------------------------------------------
    def _history(self, cur, workspace_id, user_id, now):
        cur.execute("""SELECT id::text, source, source_ref, action, extract(epoch from created_at), seq FROM public.pr_brief_actions
                       WHERE workspace_id=%s AND actor_user_id=%s AND created_at>to_timestamp(%s)
                       ORDER BY created_at DESC, seq DESC LIMIT 500""", (workspace_id, user_id, now - 400 * 86400))
        return [{"id": r[0], "source": r[1], "sourceRef": r[2], "action": r[3], "at": float(r[4]), "seq": int(r[5])} for r in cur.fetchall()]

    def _compose(self, cur, workspace_id, user_id, state, trends, now):
        from ..coworker import flags
        zone = recipient_zone(cur, workspace_id, user_id)
        key, start, end = composer.edition_window(now, zone)
        listening, listening_cov = sources.listening_candidates(state, flags.enabled("RAFII_LISTENING_ENABLED"))
        radar, radar_cov = sources.radar_candidates(cur, workspace_id, state, now, self._growth_env())
        trend_items, trend_cov = trends
        result = composer.compose(list(trend_items) + listening + radar, sources.context(state), self._history(cur, workspace_id, user_id, now), now)
        chosen = Counter(i["source"] for i in result["items"])
        coverage = [{**c, "selected": chosen.get(c["source"], 0)} for c in (trend_cov, listening_cov, radar_cov)]
        return {"editionKey": key, "periodStart": start, "periodEnd": end, "timeZone": zone, "cadence": CADENCE, "items": result["items"],
                "coverage": coverage, "dataState": composer.data_state(coverage), "materialDigest": composer.material_digest(result["items"]),
                "considered": result["considered"], "excluded": result["excluded"]}

    def _trends(self, workspace_id, token, repository=None):
        return sources.read_trends(self.hosted, workspace_id, token, repository=repository)

    def _find(self, cur, workspace_id, user_id, key, digest):
        cur.execute(f"SELECT {EDITION_COLUMNS} FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s AND edition_key=%s AND material_digest=%s",
                    (workspace_id, user_id, key, digest))
        row = cur.fetchone()
        return _edition(row) if row else None

    def _by_id(self, cur, workspace_id, user_id, edition_id):
        if not isinstance(edition_id, str) or not UUID.match(edition_id):
            return None
        cur.execute(f"SELECT {EDITION_COLUMNS} FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s AND id=%s",
                    (workspace_id, user_id, edition_id))
        row = cur.fetchone()
        return _edition(row) if row else None

    def _decisions(self, cur, workspace_id, user_id, refs):
        """The latest action of this person on each (source, ref)."""
        if not refs:
            return {}
        cur.execute(f"""SELECT DISTINCT ON (source, source_ref) {ACTION_COLUMNS} FROM public.pr_brief_actions
                        WHERE workspace_id=%s AND actor_user_id=%s AND source_ref = ANY(%s)
                        ORDER BY source, source_ref, created_at DESC, seq DESC""", (workspace_id, user_id, sorted({r for _s, r in refs})))
        return {(a["source"], a["sourceRef"]): a for a in map(_action, cur.fetchall())}

    @staticmethod
    def _decision_view(row):
        return {k: row[k] for k in ("action", "reasonCode", "outcomeRefs", "createdAt")} if row else None

    def _handled(self, cur, workspace_id, user_id, edition_key, shown, now):
        """Items the person already decided on, outside the open list: this week's (any decision still in force) and
        recent "not relevant" ones, each with the stored edition it came from, so the outcome link and Restore stay
        reachable after the item leaves the composition. Bounded; never part of the material digest."""
        cur.execute("""SELECT id::text, edition_key, items FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s
                       AND created_at>to_timestamp(%s) ORDER BY created_at DESC, revision DESC LIMIT 50""", (workspace_id, user_id, now - 28 * 86400))
        seen = {}
        for edition_id, key, raw in cur.fetchall():
            for item in _json(raw) or []:
                if item.get("id") not in shown and item.get("id") not in seen:
                    seen[item["id"]] = (edition_id, key, item)
        decisions = self._decisions(cur, workspace_id, user_id, [(i["source"], i["sourceRef"]) for _e, _k, i in seen.values()])
        handled = []
        for edition_id, key, item in seen.values():
            active = composer.active_decision(decisions.get((item["source"], item["sourceRef"])), now)
            if active and (key == edition_key or active["action"] == "not_relevant"):
                handled.append({**item, "editionId": edition_id, "decision": self._decision_view(active)})
        return sorted(handled, key=lambda i: -i["decision"]["createdAt"])[:10]

    def _present(self, cur, workspace_id, user_id, composed, stored, member, now):
        items = copy.deepcopy(stored["items"] if stored else composed["items"])
        decisions = self._decisions(cur, workspace_id, user_id, [(i["source"], i["sourceRef"]) for i in items])
        for item in items:
            item["decision"] = self._decision_view(composer.active_decision(decisions.get((item["source"], item["sourceRef"])), now))
        handled = self._handled(cur, workspace_id, user_id, composed["editionKey"], {i["id"] for i in items}, now)
        limitations = ["Stored results only: nothing here is today's research, and absence from a source is not absence everywhere.",
                       "Relevance comes from your goals, your own material and what you asked Rafii to watch; it is not a prediction of results."]
        return {"definitionVersion": composer.DEFINITION_VERSION, "asOf": now, "dataMode": "stored", "dataState": composer.data_state(composed["coverage"]),
                "coverage": composed["coverage"], "excluded": composed["excluded"], "considered": composed["considered"],
                "edition": {"id": stored["id"] if stored else None, "persisted": stored is not None, "editionKey": composed["editionKey"],
                            "revision": stored["revision"] if stored else None, "periodStart": composed["periodStart"], "periodEnd": composed["periodEnd"],
                            "timeZone": composed["timeZone"], "cadence": composed["cadence"], "materialDigest": composed["materialDigest"],
                            "deliveredAt": stored["deliveredAt"] if stored else None, "items": items, "handled": handled},
                "canAct": member.allows("edit"), "limitations": limitations, "reasons": composer.REASONS}

    def current(self, workspace_id, token):
        """GET: compose from stored evidence; writes nothing."""
        require_enabled()
        self._session(token)
        trends = self._trends(workspace_id, token)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = _member(row)
            require(member, "read")
            composed = self._compose(cur, workspace_id, principal, _state(row), trends, now)
            stored = self._find(cur, workspace_id, principal, composed["editionKey"], composed["materialDigest"])
            return self._present(cur, workspace_id, principal, composed, stored, member, now)

    def history(self, workspace_id, token, cursor=None, limit=None):
        require_enabled()
        self._session(token)
        size, before = page_limit(limit), decode_cursor(cursor)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "read")
            sql = f"SELECT {EDITION_COLUMNS}, created_at FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s"
            params = [workspace_id, principal]
            if before:
                sql += " AND (created_at, id) < (%s::timestamptz, %s::uuid)"
                params += list(before)
            cur.execute(sql + " ORDER BY created_at DESC, id DESC LIMIT %s", params + [size + 1])
            found = cur.fetchall()
            rows = [_edition(r) for r in found]
            page, more = rows[:size], len(rows) > size
            ids = [e["id"] for e in page]
            counts = {}
            if ids:
                cur.execute("SELECT edition_id::text, action, count(*) FROM public.pr_brief_actions WHERE workspace_id=%s AND edition_id = ANY(%s::uuid[]) GROUP BY 1, 2",
                            (workspace_id, ids))
                for edition_id, action, n in cur.fetchall():
                    counts.setdefault(edition_id, {})[action] = n
            return {"editions": [{**{k: e[k] for k in ("id", "editionKey", "revision", "cadence", "periodStart", "periodEnd", "timeZone", "dataState",
                                                          "deliveredAt", "createdAt", "materialDigest")},
                                  "items": len(e["items"]), "sources": sorted({i["source"] for i in e["items"]}), "actions": counts.get(e["id"], {})} for e in page],
                    "nextCursor": encode_cursor(found[len(page) - 1][14], page[-1]["id"]) if more and page else None}

    def edition(self, workspace_id, token, edition_id):
        require_enabled()
        self._session(token)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "read")
            stored = self._by_id(cur, workspace_id, principal, edition_id)
            if stored is None:
                raise AlphaError("Brief unavailable.", 404)
            cur.execute(f"SELECT {ACTION_COLUMNS} FROM public.pr_brief_actions WHERE workspace_id=%s AND edition_id=%s ORDER BY created_at, seq LIMIT 50",
                        (workspace_id, stored["id"]))
            actions = [{k: a[k] for k in ("id", "itemId", "action", "reasonCode", "outcomeRefs", "createdAt")} for a in map(_action, cur.fetchall())]
            return {"edition": {k: v for k, v in stored.items() if k != "recipient"}, "actions": actions, "definitionVersion": composer.DEFINITION_VERSION}

    # --- storage ----------------------------------------------------------------------------------------------------------
    def _persist(self, cur, workspace_id, user_id, composed, now):
        """Insert this material revision (or return the stored one with the same digest). The caller holds the
        workspace row lock, so revisions are numbered without races."""
        stored = self._find(cur, workspace_id, user_id, composed["editionKey"], composed["materialDigest"])
        if stored:
            return stored, False
        cur.execute("""INSERT INTO public.pr_brief_editions(workspace_id,recipient_user_id,edition_key,revision,cadence,period_start,period_end,time_zone,
                                  material_digest,data_state,coverage,items,created_at)
                       SELECT %s,%s,%s,coalesce(max(revision),0)+1,%s,to_timestamp(%s),to_timestamp(%s),%s,%s,%s,%s::jsonb,%s::jsonb,to_timestamp(%s)
                       FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s AND edition_key=%s
                       ON CONFLICT (workspace_id,recipient_user_id,edition_key,material_digest) DO NOTHING RETURNING id::text""",
                    (workspace_id, user_id, composed["editionKey"], composed["cadence"], composed["periodStart"], composed["periodEnd"], composed["timeZone"],
                     composed["materialDigest"], composed["dataState"], json.dumps(composed["coverage"]), json.dumps(composed["items"]), now,
                     workspace_id, user_id, composed["editionKey"]))
        inserted = cur.fetchone()
        stored = self._find(cur, workspace_id, user_id, composed["editionKey"], composed["materialDigest"])
        return stored, inserted is not None

    # --- actions ----------------------------------------------------------------------------------------------------------
    @staticmethod
    def _request(item_id, payload):
        if not isinstance(item_id, str) or not ITEM.match(item_id):
            raise AlphaError("Brief item unavailable.", 404)
        if not isinstance(payload, dict) or set(payload) - ACTION_FIELDS:
            raise AlphaError("This brief action has unknown fields.", 400)
        action = payload.get("action")
        if action not in composer.ACTIONS:
            raise AlphaError("Choose accept, save idea, dismiss, not relevant or restore.", 400)
        key = payload.get("idempotencyKey")
        if not isinstance(key, str) or not KEY.match(key):
            raise AlphaError("An idempotency key of 8–80 letters, numbers, underscores or hyphens is required.", 400)
        edition_id, digest = payload.get("editionId"), payload.get("materialDigest")
        if edition_id is not None and (not isinstance(edition_id, str) or not UUID.match(edition_id)):
            raise AlphaError("Brief unavailable.", 404)
        if edition_id is None and (not isinstance(digest, str) or not DIGEST.match(digest)):
            raise AlphaError("Send the brief's material digest so Rafii acts on the version you saw.", 400)
        reason = payload.get("reasonCode")
        if action in composer.REASONS:
            if reason not in composer.REASONS[action]:
                raise AlphaError("Choose a reason.", 400, code="reason_required")
        elif reason is not None:
            raise AlphaError("Only dismiss and not relevant take a reason.", 400)
        request = {"itemId": item_id, "action": action, "key": key, "editionId": edition_id, "materialDigest": digest, "reasonCode": reason}
        if action == "accept":
            for name in ("angleId", "channelId"):
                value = payload.get(name)
                if not isinstance(value, str) or not 1 <= len(value) <= 200:
                    raise AlphaError("Choose an angle and an account for this opportunity.", 400)
                request[name] = value
            goal = payload.get("goal")
            if goal is not None and (not isinstance(goal, str) or len(goal) > 300):
                raise AlphaError("Keep the goal to 300 characters.", 400)
            request["goal"] = " ".join(goal.split()) if isinstance(goal, str) else None
        elif any(payload.get(name) is not None for name in ("angleId", "channelId", "goal")):
            raise AlphaError("Only accepting an opportunity takes an angle, account or goal.", 400)
        digest_input = {k: v for k, v in request.items() if k != "key"}
        request["requestDigest"] = hashlib.sha256(json.dumps(digest_input, sort_keys=True).encode()).hexdigest()
        return request

    def _by_key(self, cur, workspace_id, key):
        cur.execute(f"SELECT {ACTION_COLUMNS} FROM public.pr_brief_actions WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
        row = cur.fetchone()
        return _action(row) if row else None

    def _result(self, action, edition, replayed=False):
        source_id = next((r.get("id") for r in action["outcomeRefs"] if r.get("type") == "source"), None)
        return {"action": {k: action[k] for k in ("id", "itemId", "action", "reasonCode", "outcomeRefs", "createdAt", "effort")},
                "edition": {"id": edition["id"], "revision": edition["revision"], "editionKey": edition["editionKey"]},
                "outcome": {"sourceId": source_id, "href": f"/app/ideas?source={source_id}"} if source_id else None,
                "replayed": replayed, "verified": True}

    def _replay(self, cur, workspace_id, principal, prior, request):
        if prior["actor"] != principal or prior["requestDigest"] != request["requestDigest"]:
            raise AlphaError("This request key already belongs to a different brief action.", 409, code="idempotency_conflict")
        edition = self._by_id(cur, workspace_id, principal, prior["editionId"])
        return self._result(prior, edition, replayed=True)

    def _resolve(self, cur, workspace_id, principal, state, request, trends, now):
        """The edition the person acted on and the item in it. A transient edition is recomputed on the server and
        must still have the digest the person saw; it is then stored before the action references it."""
        if request["editionId"]:
            edition = self._by_id(cur, workspace_id, principal, request["editionId"])
            if edition is None:
                raise AlphaError("Brief unavailable.", 404)
        else:
            composed = self._compose(cur, workspace_id, principal, state, trends, now)
            if composed["materialDigest"] != request["materialDigest"]:
                raise AlphaError("The brief changed since you opened it. Review the current version.", 409, code="revision_conflict")
            edition, _created = self._persist(cur, workspace_id, principal, composed, now)
        item = next((i for i in edition["items"] if i["id"] == request["itemId"]), None)
        if item is None:
            raise AlphaError("Brief item unavailable.", 404)
        # The decision still in force: a restore clears it and a lapsed dismissal no longer blocks anything.
        latest = composer.active_decision(self._decisions(cur, workspace_id, principal, [(item["source"], item["sourceRef"])]).get((item["source"], item["sourceRef"])), now)
        action = request["action"]
        if latest and latest["action"] in composer.OPEN_ACTIONS:
            raise AlphaError("This opportunity was already acted on.", 409, code="already_acted")
        if action == "restore":
            if not latest or latest["action"] not in ("dismiss", "not_relevant"):
                raise AlphaError("Only a dismissed or not-relevant item can be restored.", 409, code="nothing_to_restore")
        elif latest and latest["action"] in ("dismiss", "not_relevant"):
            raise AlphaError("Restore this item before acting on it again.", 409, code="restore_first")
        if action in composer.OPEN_ACTIONS and item["action"].get("kind") != action:
            raise AlphaError("This item supports a different action.", 409, code="unsupported_action")
        return edition, item

    def _record(self, cur, workspace_id, principal, edition, item, request, refs, now):
        cur.execute(f"""INSERT INTO public.pr_brief_actions(workspace_id,edition_id,item_id,source,source_ref,action,reason_code,effort,outcome_refs,
                                   actor_user_id,idempotency_key,request_digest,created_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,to_timestamp(%s)) RETURNING {ACTION_COLUMNS}""",
                    (workspace_id, edition["id"], item["id"], item["source"], item["sourceRef"], request["action"], request["reasonCode"], item.get("effort"),
                     json.dumps(refs), principal, request["key"], request["requestDigest"], now))
        action = _action(cur.fetchone())
        from ..hosted import audit
        audit(cur, workspace_id, principal, "brief.item_action", item["id"], {"action": request["action"], "source": item["source"],
                                                                              **({"reason": request["reasonCode"]} if request["reasonCode"] else {})})
        growth_events.emit(cur, workspace_id=workspace_id, event="brief.action", entity_id=action["id"], revision=0, user_id=principal,
                           values={"action": request["action"], "reason": request["reasonCode"] or "none", "effort": item.get("effort") or "unknown"})
        return action

    def _save_listening(self, cur, workspace_id, principal, state, item, edition):
        """One idea source from a stored listening opportunity, in the action's own transaction. The source carries
        its lineage; public references stay leads, never approved facts."""
        listening = ((state.get("coworker") or {}).get("listening") or {}).get("opportunities") or []
        op = next((o for o in listening if o.get("id") == item["sourceRef"]), None)
        if op is None or op.get("status") != "open":
            raise AlphaError("This opportunity is no longer open.", 409, code="source_unavailable")
        before = copy.deepcopy(state)
        links = [e.get("url") for e in item.get("evidence") or [] if e.get("url")]
        text = ("Topic to investigate: " + item["title"] + "\nA possible angle: " + (item.get("angle") or {}).get("text", "") +
                "\nAdd your own verified example. Public references are leads, not approved facts.")
        known = {s.get("id") for s in state.get("sources") or []}
        try:
            self.hosted.commands(state, principal, "source", {"kind": "idea", "title": item["title"][:200], "text": text})
        except AlphaError as error:
            raise AlphaError(str(error), 409, code="source_unavailable") from None
        source = next(s for s in state["sources"] if s.get("id") not in known)
        source["needsFactCheck"] = True
        source["origin"] = {"kind": "opportunity_brief", "editionId": edition["id"], "itemId": item["id"], "listeningOpportunityId": op["id"], "links": links[:3]}
        op.update({"status": "acted", "decidedAt": self.clock(), "decidedBy": principal, "sourceId": source["id"]})
        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
        for effect in getattr(self.repository, "effects", []):
            effect(cur, workspace_id, before, state, principal)
        return source["id"]

    def _external(self, workspace_id, token, item, request):
        """Trend accept and Radar save-idea run through their own services (each idempotent and free; no research)."""
        if item["source"] == "trends" and request["action"] == "accept":
            if request["angleId"] not in (item["action"].get("angleIds") or []):
                raise AlphaError("Choose one of this opportunity's angles.", 400)
            from ..coworker import runtime
            trends = runtime.ensure(self.hosted).coworker.trends
            state = self.repository.get(workspace_id, token)["state"]
            goal = request.get("goal") or next((g["name"] for g in ((state.get("coworker") or {}).get("growthLoop") or {}).get("goals") or [] if g.get("status") == "active"), None) or item["title"]
            envelope = trends.accept(workspace_id, token, item["sourceRef"], {"revision": int(item["sourceRevision"]), "angle_id": request["angleId"],
                                                                            "channel_id": request["channelId"], "goal": goal[:1000],
                                                                            "idempotency_key": ("brief-" + request["key"])[:200]})
            source_id = (envelope.get("data") or {}).get("source_id")
        elif item["source"] == "radar" and request["action"] == "save_idea":
            from ..growth.http import ensure
            radar = ensure(self.hosted).radar
            payload = {"scanId": item["action"].get("scanId"), "opportunityId": item["action"].get("opportunityId"), "confirmed": True}
            for attempt in range(2):
                try:
                    result = radar.action(workspace_id, token, self.repository.get(workspace_id, token)["revision"], "radar_save_idea", payload)
                    break
                except AlphaError as error:
                    if getattr(error, "code", None) != "workspace_revision_conflict" or attempt:
                        raise
            source_id = result.get("sourceId")
        else:
            raise AlphaError("This item supports a different action.", 409, code="unsupported_action")
        if not source_id:
            raise AlphaError("The opportunity could not be saved. Nothing was recorded.", 409, code="delivery_uncertain")
        refs = [{"type": "source", "id": str(source_id)}]
        if item["source"] == "trends":   # the account the person chose scopes any next-week proposal built on it
            refs.append({"type": "channel", "id": request["channelId"]})
        return refs

    def action(self, workspace_id, token, item_id, payload):
        require_enabled()
        self._session(token)
        request = self._request(item_id, payload)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "edit")
            prior = self._by_key(cur, workspace_id, request["key"])
            if prior is not None:
                return self._replay(cur, workspace_id, principal, prior, request)
        trends = self._trends(workspace_id, token) if request["editionId"] is None else None
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "edit")
            prior = self._by_key(cur, workspace_id, request["key"])   # a concurrent retry may have recorded it meanwhile
            if prior is not None:
                return self._replay(cur, workspace_id, principal, prior, request)
            state = _state(row)
            edition, item = self._resolve(cur, workspace_id, principal, state, request, trends, now)
            if request["action"] in ("dismiss", "not_relevant", "restore"):
                return self._result(self._record(cur, workspace_id, principal, edition, item, request, [], now), edition)
            if item["source"] == "listening":
                source_id = self._save_listening(cur, workspace_id, principal, state, item, edition)
                return self._result(self._record(cur, workspace_id, principal, edition, item, request, [{"type": "source", "id": source_id}], now), edition)
        # The edition snapshot is now stored; the trend/Radar service runs in its own transaction, then the action is
        # recorded. A retry with the same key converges: both services return the source they already created.
        refs = self._external(workspace_id, token, item, request)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_member(row), "edit")
            prior = self._by_key(cur, workspace_id, request["key"])
            if prior is not None:
                return self._replay(cur, workspace_id, principal, prior, request)
            edition = self._by_id(cur, workspace_id, principal, edition["id"])
            latest = self._decisions(cur, workspace_id, principal, [(item["source"], item["sourceRef"])]).get((item["source"], item["sourceRef"]))
            if latest and latest["action"] in composer.OPEN_ACTIONS:   # a parallel request already recorded the same outcome
                return self._result(latest, edition, replayed=True)
            return self._result(self._record(cur, workspace_id, principal, edition, item, request, refs, self.clock()), edition)

    # --- delivery and cron ------------------------------------------------------------------------------------------------
    def _deliver(self, cur, workspace_id, user_id, edition, now):
        if edition["deliveredAt"] is not None:
            return {"delivered": False, "reason": "already_delivered"}
        cur.execute("""SELECT items FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s AND edition_key=%s AND delivered_at IS NOT NULL""",
                    (workspace_id, user_id, edition["editionKey"]))
        told = {item["id"] for (items,) in cur.fetchall() for item in _json(items)}
        start, end = composer.local_day(now, edition["timeZone"])
        cur.execute("SELECT 1 FROM public.pr_brief_editions WHERE recipient_user_id=%s AND delivered_at>=to_timestamp(%s) AND delivered_at<to_timestamp(%s) LIMIT 1",
                    (user_id, start, end))
        reason = composer.delivery_decision(items=len(edition["items"]), new_items=sum(1 for i in edition["items"] if i["id"] not in told),
                                            cadence=edition["cadence"], edition_delivered=bool(told), delivered_today=cur.fetchone() is not None)
        if reason:
            return {"delivered": False, "reason": reason}
        notifications = getattr(self.hosted, "notifications", None)
        if notifications is None or not notifications.enabled():
            return {"delivered": False, "reason": "notifications_disabled"}
        cur.execute("SELECT coalesce(locale,'') FROM public.pr_profiles WHERE user_id=%s", (user_id,))
        found = cur.fetchone()
        text = composer.notification_copy(found[0] if found else None, len(edition["items"]))
        cur.execute("SAVEPOINT brief_delivery")
        try:
            result = notifications.emit(cur, workspace_id=workspace_id, event_type=EVENT_TYPE, dedupe_key=f"brief:{user_id}:{edition['editionKey']}:{edition['materialDigest'][:16]}",
                                        entity_type=ENTITY_TYPE, entity_id=edition["id"], actor=user_id, occurred_at=now, expires_at=edition["periodEnd"],
                                        payload={"title": text["title"], "why": text["why"], "count": len(edition["items"]), "href": HREF})
            cur.execute("RELEASE SAVEPOINT brief_delivery")
        except Exception as error:  # noqa: BLE001 - a notification problem never loses the stored edition
            cur.execute("ROLLBACK TO SAVEPOINT brief_delivery")
            log.warning(json.dumps({"event": "briefs.delivery_failed", "reason": type(error).__name__}))
            return {"delivered": False, "reason": "notification_unavailable"}
        if not result.get("created"):
            return {"delivered": False, "reason": "duplicate" if not result.get("disabled") else "notifications_disabled"}
        cur.execute("UPDATE public.pr_brief_editions SET delivered_at=to_timestamp(%s), notification_event_id=%s WHERE workspace_id=%s AND id=%s AND delivered_at IS NULL",
                    (now, result["eventId"], workspace_id, edition["id"]))
        growth_events.emit(cur, workspace_id=workspace_id, event="brief.delivered", entity_id=edition["id"], revision=edition["revision"], user_id=None,
                           values={"coverage": edition["dataState"], "channel": "in_app", "items": len(edition["items"])})
        return {"delivered": True, "eventId": result["eventId"], "channels": sorted({f"{d['channel']}:{d['status']}" for d in result.get("deliveries") or []})}

    def run_recipient(self, workspace_id, user_id, trends, now):
        """Compose, store and (when allowed) alert one recipient, under the workspace row lock."""
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
            found = cur.fetchone()
            state = _json(found[0]) if found else None
            cur.execute("""SELECT m.role FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
                           WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL""", (workspace_id, user_id))
            role = cur.fetchone()
            if not isinstance(state, dict) or state.get("accountDeletion") or (state.get("workspace") or {}).get("sample"):
                outcome = {"skipped": "workspace_unavailable"}
            elif not role or role[0] not in RECIPIENT_ROLES:
                outcome = {"skipped": "not_a_recipient"}
            else:
                composed = self._compose(cur, workspace_id, user_id, state, trends, now)
                edition, created = self._persist(cur, workspace_id, user_id, composed, now)
                outcome = {"persisted": created, "items": len(edition["items"]), **self._deliver(cur, workspace_id, user_id, edition, now)}
            if found and role:   # without either, `due` no longer selects this pair, so there is nothing to space out
                self._checked(cur, workspace_id, user_id, now)
            db.commit()
        return outcome

    @staticmethod
    def _checked(cur, workspace_id, user_id, now):
        cur.execute("""INSERT INTO public.pr_brief_schedule(workspace_id,recipient_user_id,checked_at) VALUES(%s,%s,to_timestamp(%s))
                       ON CONFLICT (workspace_id,recipient_user_id) DO UPDATE SET checked_at=excluded.checked_at""", (workspace_id, user_id, now))

    def _mark_failed(self, workspace_id, user_id, now):
        """A recipient whose run failed waits the normal re-check interval like everyone else (no retry storm at the
        head of the queue). Best effort, in its own transaction."""
        try:
            with self.hosted.connection_factory() as db, db.cursor() as cur:
                self._checked(cur, workspace_id, user_id, now)
                db.commit()
        except Exception as error:  # noqa: BLE001 - bookkeeping never breaks the cron step
            log.warning(json.dumps({"event": "briefs.schedule_unwritable", "reason": type(error).__name__}))

    def due(self, now, limit):
        from ..growth.trends import config
        from ..coworker import flags
        allowed = []
        for part in str(flags._source().get("RAFII_TREND_WORKSPACE_ALLOWLIST", "")).split(","):
            if UUID.match(part.strip().lower()):
                allowed.append(part.strip().lower())
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT w.id::text, m.user_id::text FROM public.pr_workspaces w
                           JOIN public.pr_memberships m ON m.workspace_id=w.id AND m.status='active' AND m.role = ANY(%s)
                           JOIN public.pr_profiles p ON p.user_id=m.user_id AND p.deleted_at IS NULL
                           LEFT JOIN public.pr_brief_schedule s ON s.workspace_id=w.id AND s.recipient_user_id=m.user_id
                           WHERE NOT w.state ? 'accountDeletion' AND coalesce(w.state->'workspace'->>'sample','false')<>'true'
                             AND (s.checked_at IS NULL OR s.checked_at < to_timestamp(%s))
                             AND (jsonb_typeof(w.state->'coworker'->'listening'->'opportunities')='array'
                                  OR EXISTS (SELECT 1 FROM public.pr_radar_runs r WHERE r.workspace_id=w.id AND r.status IN ('completed','partial') AND r.expires_at>to_timestamp(%s))
                                  OR w.id = ANY(%s::uuid[]))
                           ORDER BY s.checked_at NULLS FIRST, w.id, m.user_id LIMIT %s""",
                        (list(RECIPIENT_ROLES), now - RECHECK_SECONDS, now, allowed if config.enabled("INTELLIGENCE") else [], limit))
            return cur.fetchall()

    def cron(self, deadline, max_recipients=10):
        """Bounded and isolated: one recipient failing never stops the others; the summary holds counts and reason
        codes only (no ids, text or exception messages)."""
        from ..automation_runs import principal_repository
        from ..coworker import runtime
        try:
            runtime.ensure(self.hosted)
        except Exception as error:  # noqa: BLE001 - without the coworker attachments there is nothing to deliver through
            return {"status": "unavailable", "reason": type(error).__name__}
        now = self.clock()
        summary = {"status": "ok", "recipients": 0, "persisted": 0, "delivered": 0, "skipped": {}}
        for workspace_id, user_id in self.due(now, max_recipients):
            if time.monotonic() >= deadline:
                summary["status"] = "deferred"
                break
            try:
                repository, capability = principal_repository(self.hosted, workspace_id, user_id, "edit")
                outcome = self.run_recipient(workspace_id, user_id, self._trends(workspace_id, capability, repository), now)
            except Exception as error:  # noqa: BLE001
                reason = getattr(error, "code", None) or type(error).__name__
                summary["skipped"][reason] = summary["skipped"].get(reason, 0) + 1
                log.warning(json.dumps({"event": "briefs.recipient_failed", "reason": str(reason)[:60]}))
                self._mark_failed(workspace_id, user_id, now)
                continue
            summary["recipients"] += 1
            summary["persisted"] += int(bool(outcome.get("persisted")))
            summary["delivered"] += int(bool(outcome.get("delivered")))
            reason = outcome.get("skipped") or outcome.get("reason")
            if reason:
                summary["skipped"][reason] = summary["skipped"].get(reason, 0) + 1
        return summary

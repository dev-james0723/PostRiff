"""SeriesService: authority, revision and idempotency around the pure series logic (PRD R-SER, R-ENG-02).

Every call derives workspace and actor from the session through ``repository.transaction``/``repository.command``;
the workspace id in the path only selects. Reads need ``read``; changes need ``edit`` (a decision kept in workspace
memory needs ``owner``, the overlay store's own rule). Mutations take an ``idempotencyKey`` (a replay returns the
current series, a different request under the same key is ``idempotency_conflict``) and, for an existing series, its
``expectedRevision`` (``revision_conflict`` when stale). Nothing here calls a model, a provider or the network: plans
are deterministic and drafting stays on the existing writer path with its own credit authorization.
"""
from __future__ import annotations

import base64
import json
import time

from postriff_alpha.domain import AlphaError

from .. import growth_events
from ..contracts import digest
from ..permissions import Membership, require
from . import commands, model as m, views

DEFAULT_LIMIT, MAX_LIMIT = 25, 50
AUDIT = {"create": "series.created", "plan": "series.planned", "decide": "series.angle_decided", "revoke": "series.decision_revoked",
         "approve": "series.episode_approved", "claim": "series.fact_reviewed", "link": "series.draft_linked", "unlink": "series.draft_unlinked",
         "status": "series.status_changed"}


class _Replay(Exception):
    def __init__(self, series_id):
        super().__init__(series_id)
        self.series_id = series_id


def ensure(hosted):
    if not hasattr(hosted, "series"):
        hosted.series = SeriesService(hosted)
    return hosted.series


def _state(row):
    return row[1] if isinstance(row[1], dict) else json.loads(row[1])


def page_args(limit, cursor):
    if limit is None:
        limit = DEFAULT_LIMIT
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise AlphaError(f"Choose a page size from 1 to {MAX_LIMIT}.", 400)
    before = None
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 200:
                raise ValueError()
            decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if not isinstance(decoded, list) or len(decoded) != 2 or not isinstance(decoded[1], str) or not m._ID.match(decoded[1]):
                raise ValueError()
            before = (float(decoded[0]), decoded[1])
        except (ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error):
            raise AlphaError("This page cursor is invalid.", 400) from None
    return limit, before


def paginate(items, key, limit, before):
    """Deterministic (key DESC, id DESC) pages with an opaque cursor (as the Inbox list)."""
    ordered = sorted(items, key=lambda item: (key(item), item["id"]), reverse=True)
    if before is not None:
        ordered = [item for item in ordered if (key(item), item["id"]) < before]
    page, more = ordered[:limit], len(ordered) > limit
    cursor = base64.urlsafe_b64encode(json.dumps([key(page[-1]), page[-1]["id"]]).encode()).decode().rstrip("=") if more and page else None
    return page, cursor


class SeriesService:
    def __init__(self, hosted, clock=None):
        self.hosted = hosted
        self.clock = clock or getattr(hosted, "clock", None) or time.time

    @property
    def repository(self):
        return self.hosted.repository

    # --- reads --------------------------------------------------------------------------------------------------------
    def _read(self, workspace_id, token, fn):
        m.require_enabled()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = Membership.from_row(*row[2:7])
            require(member, "read")
            return fn(cur, _state(row), principal, member)

    def list(self, workspace_id, token, *, limit=None, cursor=None, archived=False):
        limit, before = page_args(limit, cursor)
        now = self.clock()

        def read(_cur, state, _principal, member):
            items = [c for c in m.all_series(state) if archived or c["series"].get("status") != "archived"]
            page, next_cursor = paginate(items, lambda c: float(c.get("createdAt") or 0), limit, before)
            return {"items": [views.summary(state, c, now) for c in page], "nextCursor": next_cursor, "limit": limit,
                    "canEdit": member.allows("edit"), "definitionVersion": m.SCHEMA, "asOf": now, "dataState": "available"}
        return self._read(workspace_id, token, read)

    def get(self, workspace_id, token, series_id):
        now = self.clock()

        def read(_cur, state, _principal, member):
            return {"series": views.detail(state, m.find(state, series_id), now, member), "canEdit": member.allows("edit"), "isOwner": member.allows("owner")}
        return self._read(workspace_id, token, read)

    def candidates(self, workspace_id, token, *, kind="post", limit=None, cursor=None, min_age_days=None):
        """Eligible originals: published posts at least `min_age_days` old (Evergreen eligibility) with any earlier
        reuse named, or active sources with approved facts. A post's conversation metric is shown only against at
        least three comparable posts (same provider, account, language, content type, window), as an observation."""
        if kind not in ("post", "source"):
            raise AlphaError("Choose posts or sources.", 400)
        limit, before = page_args(limit, cursor)
        min_age = commands.bounded_int(min_age_days, m.DEFAULT_MIN_AGE, m.MIN_AGE_DAYS, m.MAX_AGE_DAYS, f"Reuse posts between {m.MIN_AGE_DAYS} and {m.MAX_AGE_DAYS} days old.")
        now = self.clock()

        def read(cur, state, _principal, _member):
            if kind == "source":
                sources = [s for s in state.get("sources") or [] if s.get("active") and s.get("kind") != "voice_sample" and m.approved_facts(s)]
                page, next_cursor = paginate(sources, lambda s: m._epoch(s.get("createdAt")), limit, before)
                items = [{"kind": "source", "id": s["id"], "title": " ".join(str(s.get("title") or "").split())[:120], "approvedFacts": len(m.approved_facts(s)),
                          "excerpt": str(m.approved_facts(s)[0].get("text") or "")[:280], "createdAt": m._epoch(s.get("createdAt"))} for s in page]
                return {"items": items, "nextCursor": next_cursor, "limit": limit, "dataState": "available", "asOf": now}
            jobs = [j for j in m._jobs(state) if m.verified_at(j) is not None and m.job_text(j) and m.verified_at(j) <= now - min_age * m.DAY]
            page, next_cursor = paginate(jobs, m.verified_at, limit, before)
            observed, observed_state = self._observations(cur, workspace_id, state, now)
            prior = m.prior_use(state)
            items = [{"kind": "post", "id": j["id"], "platform": (j.get("manifest") or {}).get("platform"),
                      "language": ((j.get("manifest") or {}).get("payload") or {}).get("language"),
                      "publishedAt": m._day(m.verified_at(j)).isoformat(), "excerpt": m.job_text(j)[:280],
                      "priorUse": prior.get(j["id"], []), "observed": observed.get(j.get("providerReference"))} for j in page]
            return {"items": items, "nextCursor": next_cursor, "limit": limit, "minAgeDays": min_age, "observedState": observed_state,
                    "dataState": "available", "asOf": now}
        return self._read(workspace_id, token, read)

    def _observations(self, cur, workspace_id, state, now):
        """{providerPostId: {metric, value, typical, sampleSize, causal: False}} for cohorts of >= 3 measured posts."""
        import statistics
        from .. import campaigns, insights
        try:
            posts = insights.summary(cur, workspace_id, m._jobs(state), now, basis=insights.COMPARISON_BASIS)["posts"]
        except Exception:  # noqa: BLE001 - a metrics read failure is shown as unavailable, never as zero
            return {}, "unavailable"
        cohorts = {}
        for post in posts:
            metric, value = campaigns._conversation(post)
            if value is not None:
                cohorts.setdefault(tuple(sorted((post.get("cohort") or {}).items())), []).append((post, metric, value))
        out = {}
        for members in cohorts.values():
            if len(members) < campaigns.MIN_COMPARABLE:
                continue
            typical = statistics.median(value for _, _, value in members)
            for post, metric, value in members:
                out[post.get("providerPostId")] = {"metric": metric, "value": value, "typical": typical, "sampleSize": len(members), "causal": False}
        return out, "available" if posts else "unavailable"

    def draft_check(self, workspace_id, token, series_id, episode_id, variant_id):
        """What linking this draft would do: a refusal (exact duplicate) or the warnings to acknowledge. No change."""
        def read(_cur, state, _principal, _member):
            campaign = m.find(state, series_id)
            episode = m.episode_of(campaign["series"], episode_id)
            checks = m.draft_checks(state, campaign, episode, variant_id)
            return {"variantId": variant_id, "episodeId": episode_id, **checks}
        return self._read(workspace_id, token, read)

    # --- changes ------------------------------------------------------------------------------------------------------
    def _decision_storage(self, workspace_id, token):
        """Workspace memory (overlays) when it is on and the person may write it; otherwise the series record."""
        from ..coworker import flags
        if not flags.enabled("RAFII_ADAPTIVE_SKILLS_ENABLED"):
            return {"kind": "series", "reason": "overlays_disabled"}, "edit"
        with self.repository.transaction(token, workspace_id) as (_cur, row, _principal):
            member = Membership.from_row(*row[2:7])
        if member.allows("owner"):
            return {"kind": "overlay"}, "owner"
        return {"kind": "series", "reason": "owner_required"}, "edit"

    def _invalidate(self, state):
        engine = getattr(getattr(self.hosted, "commands", None), "engine", None)
        phase2 = state.get("phase2")
        if engine is not None and isinstance(phase2, dict) and "reviews" in phase2 and "jobs" in phase2:
            engine.invalidate(state)

    def _mutate(self, workspace_id, token, payload, op, series_id, apply, *, requirement="edit", event=None, target=None):
        m.require_enabled()
        if not isinstance(payload, dict):
            raise AlphaError("Send a JSON object.", 400)
        key = m.check_key(payload.get("idempotencyKey"))
        # The path ids are part of the request: one key can never approve a second episode as a replay of the first.
        request = digest({"op": op, "series": series_id, "target": target or {},
                          "payload": {k: v for k, v in payload.items() if k not in ("idempotencyKey", "expectedRevision")}})
        box = {}

        def trusted(state, principal):
            m.require_enabled()
            now = self.clock()
            if series_id is None:
                existing = next((c for c in m.all_series(state) if c["series"].get("createdKey") == key), None)
                if existing is not None:
                    if existing["series"].get("createdRequest") != request:
                        raise AlphaError("This idempotency key was already used for a different request.", 409, code="idempotency_conflict")
                    raise _Replay(existing["id"])
                campaign = apply(state, principal, None, now)
                campaign["series"].update(createdKey=key, createdRequest=request)
                box["result"] = {"seriesId": campaign["id"]}
            else:
                campaign = m.find(state, series_id)
                if m.replay(campaign["series"], key, request):
                    raise _Replay(series_id)
                m.check_revision(campaign["series"], payload.get("expectedRevision"))
                box["result"] = apply(state, principal, campaign, now)
                m.remember(campaign["series"], key, request, op, now)
                m.touch(campaign, principal, now)
            box["gated"] = m.refresh(state, campaign, now)
            if box["gated"]:
                self._invalidate(state)
            box.update(seriesId=campaign["id"], revision=campaign["series"]["revision"])
            return state

        def audit(_state_after):
            result = box.get("result") if isinstance(box.get("result"), dict) else {}
            meta = {"revision": box.get("revision"), "gatedDrafts": box.get("gated", 0)}
            meta.update({k: result[k] for k in ("decision", "level", "role", "storage", "status", "action") if isinstance(result.get(k), str)})
            return AUDIT[op], box.get("seriesId", "")[:200], meta

        def after(cur, _state_after, principal):
            if event and event.get("episodeId"):
                # One semantic event per accepted episode (dedupe: event, episode id, revision 1).
                growth_events.emit(cur, workspace_id=workspace_id, event="series.episode_accepted", entity_id=event["episodeId"], revision=1,
                                   user_id=principal, values={"role": event["role"], "episode": event["index"]})

        for attempt in range(2):
            revision = self.repository.get(workspace_id, token)["revision"]
            try:
                self.repository.command(workspace_id, token, revision, trusted, requirement=requirement, audit_event=audit, after=after)
                break
            except _Replay as replayed:
                return {**self.get(workspace_id, token, replayed.series_id), "result": None, "replayed": True, "verified": True}
            except AlphaError as error:
                if getattr(error, "code", None) == "workspace_revision_conflict" and attempt == 0:
                    box.clear()
                    continue
                raise
        view = self.get(workspace_id, token, box["seriesId"])
        # Read back: the saved series carries the revision this change produced.
        return {**view, "result": box.get("result"), "replayed": False, "verified": view["series"]["revision"] == box["revision"]}

    def create(self, workspace_id, token, payload):
        return self._mutate(workspace_id, token, payload, "create", None, lambda state, actor, _c, now: commands.create(state, payload, actor, now))

    def plan(self, workspace_id, token, series_id, payload):
        return self._mutate(workspace_id, token, payload, "plan", series_id, lambda state, _actor, campaign, now: commands.replan(state, campaign, payload, now))

    def decide(self, workspace_id, token, series_id, episode_id, payload):
        storage, requirement = self._decision_storage(workspace_id, token)

        def apply(state, actor, campaign, now):
            record = commands.decide(state, campaign, episode_id, payload, actor, now, storage)
            return {k: record[k] for k in ("id", "decision", "level", "role", "storage", "reason", "overlayId")}
        return self._mutate(workspace_id, token, payload, "decide", series_id, apply, requirement=requirement, target={"episodeId": episode_id})

    def revoke(self, workspace_id, token, series_id, decision_id, payload):
        requirement = "edit"

        def check(_cur, state, _principal, _member):
            record = next((d for d in m.find(state, series_id)["series"].get("decisions") or [] if d.get("id") == decision_id), None)
            return (record or {}).get("storage")
        if self._read(workspace_id, token, check) == "overlay":
            requirement = "owner"   # workspace memory: only an owner changes it (as overlay_status)

        def apply(state, actor, campaign, now):
            record = commands.revoke(state, campaign, decision_id, actor, now)
            return {"id": record["id"], "status": record["status"], "storage": record["storage"]}
        return self._mutate(workspace_id, token, payload, "revoke", series_id, apply, requirement=requirement, target={"decisionId": decision_id})

    def approve(self, workspace_id, token, series_id, episode_id, payload):
        event = {}

        def apply(state, actor, campaign, now):
            episode = commands.approve(state, campaign, episode_id, actor, now)
            event.update(episodeId=episode["id"], role=episode["role"], index=int(episode.get("index") or 0))
            return {"episodeId": episode["id"], "state": episode["state"]}
        return self._mutate(workspace_id, token, payload, "approve", series_id, apply, event=event, target={"episodeId": episode_id})

    def claim(self, workspace_id, token, series_id, claim_id, payload):
        def apply(state, actor, campaign, now):
            item = commands.claim(state, campaign, claim_id, payload, actor, now)
            return {"claimId": item["id"], "status": item["status"], "reviewBy": item.get("reviewBy"), "action": payload.get("action")}
        return self._mutate(workspace_id, token, payload, "claim", series_id, apply, target={"claimId": claim_id})

    def link(self, workspace_id, token, series_id, episode_id, payload):
        return self._mutate(workspace_id, token, payload, "link", series_id,
                            lambda state, actor, campaign, now: commands.link_draft(state, campaign, episode_id, payload, actor, now), target={"episodeId": episode_id})

    def unlink(self, workspace_id, token, series_id, episode_id, variant_id, payload):
        return self._mutate(workspace_id, token, payload, "unlink", series_id,
                            lambda state, actor, campaign, now: commands.unlink_draft(state, campaign, episode_id, variant_id, actor, now),
                            target={"episodeId": episode_id, "variantId": variant_id})

    def set_status(self, workspace_id, token, series_id, payload):
        return self._mutate(workspace_id, token, payload, "status", series_id,
                            lambda state, actor, campaign, now: commands.set_status(state, campaign, payload, actor, now))


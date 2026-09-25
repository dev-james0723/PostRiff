"""Compound requests: "Shorten this draft, add it to the launch campaign and schedule it for Thursday at 6 PM".

Every step runs, is proposed, or is reported on its own, in the order a person would do them:

1. find the campaign and read what it is missing (reads);
2. revise the selected draft or create a post (the writing pipeline, IdeasService.turn);
3. save the result (IdeasService.apply): a rework is a proposed update on that draft, a new post is a new draft;
4. link the saved draft to the campaign (the campaign's own `raffi_campaign_link` action);
5. schedule: never done by Rafii. It is a proposal the person applies (proposals.build_schedule), and even then the
   post waits for a separate approval of that exact review.

A writing run on a local CLI finishes after the turn: `advance` runs again (POST site-agent/compound/continue) and
finishes steps 3-5 once the run has. Each step's state is stored on the answer, so the report is always the real one.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics

from postriff_alpha.domain import AlphaError

from .. import campaigns
from . import proposals, routes, timeframe

STEP_LABELS = {"find": "Find the campaign", "gaps": "What is missing", "revise": "Revise the draft", "create": "Create the post", "save": "Save the draft",
               "link": "Link it to the campaign", "schedule": "Schedule it"}
# "the next suitable slot", "whenever", "a good time": the person leaves the slot to Rafii (still a proposal).
DELEGATED_SLOT = re.compile(r"\b(?:next|first|earliest)\s+(?:suitable\s+|empty\s+|free\s+|open\s+|good\s+|available\s+)?(?:slot|day|time)\b|\bwhenever\b|\bany\s*time\b"
                            r"|\ba\s+good\s+time\b|\bsuitable\s+(?:slot|time)\b|\bempty\s+slot\b|\bfree\s+slot\b", re.I)
_CAMPAIGN_NAME = re.compile(r"\b(?:find|look\s+up|locate|pull\s+up|open)\s+(?:(?:my|our|the)\s+)?([^,.;?!\n]{1,60}?)\s+campaigns?\b"
                            r"|\b(?:to|into|in|under|for|from)\s+(?:the\s+|my\s+|our\s+)?([^,.;?!\n]{1,60}?)\s+campaigns?\b"
                            r"|\b(?:my|our|the)\s+([^,.;?!\n]{1,60}?)\s+campaigns?\b", re.I)
_REFERENCE_WORDS = {"this", "that", "current", "same", "a", "its", "it"}


def status(state: str, detail: str, href: str | None = None) -> dict:
    return {"state": state, "detail": detail, "href": href}


def campaign_name(text: str) -> str | None:
    match = _CAMPAIGN_NAME.search(text or "")
    name = next((g for g in match.groups() if g), None) if match else None
    return None if not name or name.strip().lower() in _REFERENCE_WORDS else name.strip()


def resolve_campaign(state: dict, text: str, focus: dict | None, history_refs: list[list[dict]] | None = None) -> dict:
    """{"campaign"} | {"candidates"} | {"none"}: the campaign a message names, points at, or the only one there is."""
    from . import reads, tools
    root = campaigns._root(state)
    live = [c for c in root["campaigns"] if c.get("status") != "cancelled"]
    if focus and focus.get("type") in ("campaign", "automation"):
        task = next((t for t in root["recurringTasks"] if t.get("id") == focus["id"]), None)
        found = next((c for c in live if c["id"] in (focus["id"], (task or {}).get("campaignId"))), None)
        if found:
            return {"campaign": found}
    if re.search(r"\b(?:that|the)\s+campaign\s+(?:we|i)\b|\bthat\s+campaign\b", text or "", re.I):
        for refs in history_refs or []:
            ref = next((r for r in refs if isinstance(r, dict) and r.get("type") == "campaign"), None)
            found = next((c for c in live if ref and c["id"] == ref.get("id")), None)
            if found:
                return {"campaign": found}
    name = campaign_name(text)
    if name:
        ctx = tools.Context(state=state, membership=_READER, principal="", workspace_id="")
        listing = reads.campaign_list(ctx, query=name)["data"]
        if listing.get("matched") and listing["total"] == 1:
            return {"campaign": next(c for c in live if c["id"] == listing["campaigns"][0]["campaignId"])}
        if listing.get("matched"):
            return {"candidates": [{"type": "campaign", "id": c["campaignId"], "title": (c.get("goal") or "")[:80]} for c in listing["campaigns"]][:5]}
        return {"none": name, "candidates": [{"type": "campaign", "id": c["id"], "title": (c.get("goal") or "")[:80]} for c in live][:5]}
    if len(live) == 1:
        return {"campaign": live[0]}
    return {"candidates": [{"type": "campaign", "id": c["id"], "title": (c.get("goal") or "")[:80]} for c in live][:5]}


class _Reader:
    """A read-only membership for resolving names inside the caller's already-checked transaction."""
    role = "viewer"

    @staticmethod
    def allows(requirement):
        return requirement == "read"


_READER = _Reader()


def usual_time(state: dict, platform: str | None, channel_id: str | None, zone: str) -> tuple[str, bool]:
    """The median local time of this account's (else platform's) posts, or 09:00 when there are none."""
    jobs = [j for j in (state.get("phase2") or {}).get("jobs", []) if isinstance(j, dict)]
    for pick in ([j for j in jobs if (j.get("manifest") or {}).get("channelId") == channel_id] if channel_id else [],
                 [j for j in jobs if (j.get("manifest") or {}).get("platform") == platform]):
        minutes = []
        for job in pick:
            local = ((job.get("manifest") or {}).get("timing") or {}).get("local") or ""
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", local):
                minutes.append(int(local[11:13]) * 60 + int(local[14:16]))
        if minutes:
            value = int(statistics.median(minutes))
            return f"{value // 60:02d}:{value % 60:02d}", True
    return "09:00", False


def resolve_time(state: dict, text: str, now: float, zone: str, *, platform: str | None, channel_id: str | None) -> dict:
    """{"local", "picked"} or {"ask"}. An exact day and time is used as said. A slot left to Rafii, or a week, is the
    first day in that range with nothing on this account, at the account's usual time. A day without a time is asked."""
    from .. import workflow_parse
    frame = timeframe.parse(text, now, zone)
    clock = workflow_parse._time_in(text)
    one_day = frame is not None and frame["end"] - frame["start"] <= 25 * 3600
    if one_day and clock:
        return {"local": f"{frame['startDate']}T{clock}", "picked": None}
    delegated = bool(DELEGATED_SLOT.search(text or ""))
    if one_day and not delegated:
        return {"ask": f"Tell me the time for {frame['label']}, for example “Schedule it for {frame['label']} at 18:00”."}
    if not delegated and frame is None:
        return {"ask": "Tell me the day and time, for example “Schedule it for Tuesday at 18:00”, or say “the next free slot”."}
    tz = timeframe._zone(zone)
    start = max(now, frame["start"]) if frame else now
    end = frame["end"] if frame and not one_day else start + 8 * 86400
    at, usual = usual_time(state, platform, channel_id, zone)
    if clock:
        at, usual = clock, True
    busy = set()
    for item in (state.get("phase2") or {}).get("jobs", []) + (state.get("phase2") or {}).get("reviews", []):
        manifest = item.get("manifest") or {}
        if item.get("state") in ("canceled", "failed") or (channel_id and manifest.get("channelId") != channel_id):
            continue
        local = (manifest.get("timing") or {}).get("local") or ""
        busy.add(local[:10])
    day = dt.datetime.fromtimestamp(start, tz).date()
    last = dt.datetime.fromtimestamp(end - 1, tz).date()
    while day <= last:
        candidate = dt.datetime.fromisoformat(f"{day.isoformat()}T{at}").replace(tzinfo=tz)
        if candidate.timestamp() > now + 900 and day.isoformat() not in busy:
            rule = (f"the first day {('in ' + frame['label']) if frame and not one_day else 'from now'} with nothing else on this account, at "
                    + (f"your usual {at} posting time" if usual else f"{at} (no earlier posts to learn a usual time from)"))
            return {"local": f"{day.isoformat()}T{at}", "picked": rule}
        day += dt.timedelta(days=1)
    return {"ask": "Every day in that range already has a post on this account. Tell me the day and time you want."}


def draft_channel(state: dict, variant: dict) -> dict | None:
    channels = [c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and not c.get("revoked")]
    channel = next((c for c in channels if c.get("id") == variant.get("channelId")), None)
    if channel is None:
        same = [c for c in channels if c.get("platform") == variant.get("platform")]
        channel = same[0] if len(same) == 1 else None
    return channel


def schedule_proposal(service, state: dict, variant: dict, text: str, *, actor: str, now: float, zone: str, accept_update: bool) -> dict:
    """A scheduling proposal for one saved draft: {"proposal"} or {"needs": reason}."""
    channel = draft_channel(state, variant)
    if channel is None:
        return {"needs": f"choose the {variant.get('platform')} account for this draft in Queue → Drafts; I won't pick one for you."}
    when = resolve_time(state, text, now, zone, platform=variant.get("platform"), channel_id=channel.get("id"))
    if "ask" in when:
        return {"needs": when["ask"]}
    built = proposals.build_schedule(state, variant=variant, channel=channel, local_time=when["local"], zone=zone, actor=actor, now=now,
                                     commands=service.commands, accept_update=accept_update and bool(variant.get("proposedUpdate")), picked=when["picked"])
    if "refuse" in built:
        return {"needs": f"the app can't prepare it yet: {built['refuse']}"}
    return {"proposal": built["proposal"], "when": when}


def link(service, workspace_id: str, token: str, campaign_id: str, draft_ids: list[str]) -> dict:
    """The campaign's own action, as the person, with the edit permission re-checked at execution."""
    from ..hosted import audit
    result = {}

    def command(state, actor):
        result.update(campaigns.apply_action(state, "raffi_campaign_link", {"campaignId": campaign_id, "draftIds": draft_ids}, actor, service.clock()) or {})
        return state

    def after(cur, state, actor):
        audit(cur, workspace_id, actor, "campaign.items_linked_by_agent", campaign_id, {"added": len(result.get("added") or []), "already": result.get("alreadyLinked", 0)})

    for attempt in range(2):
        try:
            saved = service.repository.command(workspace_id, token, service.get(workspace_id, token)["revision"], command, requirement="edit", after=after)
            return {**result, "revision": saved["revision"]}
        except AlphaError as error:
            if error.code != "workspace_revision_conflict" or attempt:
                raise
    return result


def _stored_state(site, workspace_id: str, token: str) -> dict:
    """The workspace state as stored (what the app's commands run on), not the presented snapshot."""
    with site.repository.transaction(token, workspace_id) as (_cur, row, _principal):
        return site.ideas._state(row)


def advance(site, workspace_id: str, token: str, compound: dict, *, principal: str, now: float, zone: str, text: str) -> dict:
    """Run every step that can run now; return the compound with its statuses and any new proposals."""
    service = site.service
    compound = {**compound, "status": dict(compound.get("status") or {}), "proposals": list(compound.get("proposals") or [])}
    steps = compound["steps"]
    writing = "revise" if "revise" in steps else ("create" if "create" in steps else None)
    run_id = compound.get("runId")
    if writing and run_id and not compound.get("saved"):
        events = site.ideas.events(workspace_id, token, run_id)
        state_now = events.get("status")
        if state_now in ("running", "queued"):
            compound["status"][writing] = status("running", "the writer is working on it", routes.href("conversation", params={"conversationId": compound["conversationId"]}))
            compound["pending"] = True
            return compound
        if state_now not in ("completed", "applied"):
            message = next((e.get("message") for e in reversed(events.get("events") or []) if e.get("type") == "run.failed"), None) or f"the run ended {state_now}"
            compound["status"][writing] = status("failed", message)
            for later in ("link", "schedule"):
                if later in steps:
                    compound["status"][later] = status("not_done", "there is no draft to use")
            compound["pending"] = False
            return compound
        compound["status"][writing] = status("done", "the writer finished" + (" (a rewrite of your draft)" if writing == "revise" else ""))
        if state_now == "completed":
            applied = site.ideas.apply(workspace_id, token, service.get(workspace_id, token)["revision"], run_id, events.get("artifactHash"))
            made = applied.get("variantIds") or []
            compound["savedInto"] = applied.get("campaignId")
        else:
            made = [{"variantId": v["id"], "proposedUpdate": bool((v.get("proposedUpdate") or {}).get("runId") == run_id)}
                    for v in _stored_state(site, workspace_id, token).get("variants", []) if (v.get("proposedUpdate") or {}).get("runId") == run_id or v.get("runId") == run_id]
        compound["drafts"] = [{"id": m["variantId"], "update": bool(m.get("proposedUpdate"))} for m in made]
        compound["saved"] = True
        detail = ("saved as a proposed update to your draft (the current text stays until it is used)" if any(d["update"] for d in compound["drafts"])
                  else f"saved {len(compound['drafts'])} new draft(s)")
        compound["status"]["save"] = status("done", detail, routes.href("queue", query={"view": "drafts", "draft": compound["drafts"][0]["id"]}) if compound["drafts"] else None)
    compound["pending"] = False
    draft_ids = [d["id"] for d in compound.get("drafts") or []]
    if not writing and compound.get("focusDraftId"):
        draft_ids = [compound["focusDraftId"]]
    campaign_id = compound.get("campaignId")
    if ("link" in steps or compound.get("linkImplied")) and "link" not in compound.get("done", []):
        if not campaign_id:
            compound["status"]["link"] = status("needs_you", compound.get("campaignProblem") or "tell me which campaign")
        elif not draft_ids:
            compound["status"]["link"] = status("not_done", "there is no draft to link")
        elif compound.get("savedInto") == campaign_id:
            # Written for this campaign: saving it put it there (IdeasService.apply, the same command).
            compound["status"]["link"] = status("done", f"added to “{compound.get('campaignTitle') or 'the campaign'}” when it was saved",
                                                routes.href("automations", query={"campaign": campaign_id}))
        else:
            try:
                result = link(service, workspace_id, token, campaign_id, draft_ids)
                compound["status"]["link"] = status("done", f"linked to “{compound.get('campaignTitle') or 'the campaign'}”" + (" (it was already there)" if not result.get("added") else ""),
                                                    routes.href("automations", query={"campaign": campaign_id}))
            except AlphaError as error:
                compound["status"]["link"] = status("failed" if error.status != 403 else "needs_you", str(error))
        compound.setdefault("done", []).append("link")
    if "schedule" in steps and "schedule" not in compound.get("done", []):
        state = _stored_state(site, workspace_id, token)
        drafts = [v for v in state.get("variants", []) if v.get("id") in draft_ids]
        if not drafts:
            compound["status"]["schedule"] = status("not_done", "there is no saved draft to schedule")
        else:
            outcomes = []
            for variant in drafts[:3]:
                built = schedule_proposal(service, state, variant, text, actor=principal, now=now, zone=zone, accept_update=any(d["update"] and d["id"] == variant["id"] for d in compound.get("drafts") or []))
                outcomes.append((variant, built))
                if "proposal" in built:
                    compound["proposals"].append(built["proposal"])
            ready = [(v, b) for v, b in outcomes if "proposal" in b]
            if ready:
                when = ready[0][1]["when"]
                compound["status"]["schedule"] = status("waiting", f"for {when['local'].replace('T', ' ')} — waiting for your approval" + (f" (picked: {when['picked']})" if when["picked"] else ""))
            else:
                compound["status"]["schedule"] = status("needs_you", outcomes[0][1]["needs"])
        compound.setdefault("done", []).append("schedule")
    return compound

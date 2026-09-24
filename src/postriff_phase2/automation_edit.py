"""Change an existing automation by asking in chat (orchestration §7, spec §10).

"Actually move it to Friday at 6", "Stop posting this to X", "Use Reuters instead of BBC", "Make these auto-publish
from now on", "Pause this for two weeks", "Delete the motivational quote automation": the edit names its target (or
the conversation does), the change is applied to the automation's full definition and saved on the same task
(`raffi_recurrence_save` with its id), so nothing is duplicated. Drafted posts that have not published follow the
new plan (campaigns.retime_open_runs). An owner's change is turned on again straight away; the reply says what
now happens and when.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import zoneinfo

from postriff_alpha.domain import AlphaError, clean

from . import automation_chat, automation_plan, campaigns, workflow as workflows
from .agent_runtime import PLATFORMS

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "my", "this", "that", "automation", "automations", "post", "posts", "one", "it", "about", "for", "on"}


def live_tasks(state: dict) -> list[dict]:
    return [task for task in campaigns._root(state)["recurringTasks"] if task.get("status") != "cancelled" and not task.get("deletedAt")]


def summaries(state: dict) -> list[dict]:
    """What a model may see to name a target: names, schedule words, platforms and status (never ids or accounts)."""
    return [{"name": task.get("name") or "Automation", "schedule": automation_plan.describe(task["schedule"]),
             "platforms": list(dict.fromkeys(d["platform"] for d in task.get("destinations") or [])), "status": task["status"]}
            for task in live_tasks(state)][:30]


def resolve(state: dict, name: str | None, conversation_task_id: str | None, text: str = "") -> tuple[dict | None, list[dict]]:
    """(target, candidates): a named automation first, then the one this conversation is about, then the only one."""
    tasks = live_tasks(state)
    words = {w for w in _WORD.findall((name or "").lower()) if w not in _STOP}
    if words:
        scored = []
        for task in tasks:
            campaign = next((c for c in campaigns._root(state)["campaigns"] if c["id"] == task["campaignId"]), {})
            haystack = set(_WORD.findall(" ".join([task.get("name") or "", task.get("intent") or "", campaign.get("goal") or ""]).lower()))
            overlap = len(words & haystack)
            if overlap:
                scored.append((overlap, task.get("updatedAt") or 0, task))
        if scored:
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            if len(scored) == 1 or scored[0][0] > scored[1][0]:
                return scored[0][2], []
            return None, [item[2] for item in scored[:4]]
    current = next((task for task in tasks if task["id"] == conversation_task_id), None)
    if current is not None:
        return current, []
    active = [task for task in tasks if task["status"] in ("active", "paused", "draft")]
    if len(active) == 1:
        return active[0], []
    return None, active[:4]


def _payload(state: dict, task: dict) -> dict:
    """The automation's full definition as a save payload, so an edit changes only what was asked."""
    campaign = next(c for c in campaigns._root(state)["campaigns"] if c["id"] == task["campaignId"])
    content = task.get("contentType")
    return {"taskId": task["id"], "name": task.get("name") or "Automation", "goal": campaign["goal"], "audience": campaign["audience"], "facts": campaign.get("facts") or {},
            "schedule": copy.deepcopy(task["schedule"]), "destinations": copy.deepcopy(task["destinations"]),
            "contentType": ({"contentTypeId": content["contentTypeId"], "formatId": content.get("formatId"), "label": task.get("contentLabel"), "library": task.get("contentLibrary")} if content else None),
            "route": task["route"], "reasoning": task.get("reasoning", "quick"), "maxCostUsdMicro": task.get("maxCostUsdMicro", 0),
            "sourceIds": list(task.get("contextSourceIds") or []), "include": task.get("include"), "voiceMode": task.get("voiceMode", "neutral"),
            "workflow": copy.deepcopy(task.get("workflow")), "intent": task.get("intent")}


def _default_workflow(task: dict, policy: str) -> dict:
    schedule = task["schedule"]
    reading = {"policy": policy, "stages": {}, "timeRole": "publish"}
    stages, _ = automation_plan.stages_for(reading, schedule, policy)
    if policy == "review" and stages.get("generate") == {"minutesOffset": -120}:
        stages["review"] = {"at": "generate"}
    return {"policy": policy, "stages": stages, "research": None, "content": {"task": "post", "instructions": ""}, "platformNotes": {}}


def _move(payload: dict, change: dict, zone: str, now: float) -> str:
    """Apply a move; returns what moved, in words. A publish time of its own moves first (that's what "it" posts)."""
    workflow = payload.get("workflow")
    schedule = payload["schedule"]
    days, local, date = change.get("weekdays") or [], change.get("localTime"), change.get("date")
    stage = change.get("stage", "auto")
    stages = (workflow or {}).get("stages") or {}
    if stage in ("review", "generate") and workflow:
        current = stages.get(stage) or {}
        spec = {"weekday": days[0], "localTime": local or current.get("localTime") or "09:00"} if days else {**current, "localTime": local} if "localTime" in current else {"dayOffset": 0, "localTime": local or "09:00"}
        if stage == "generate" and "weekday" in spec:
            spec = automation_plan._anchor_relative(spec, schedule)
        stages[stage] = spec
        if stage == "generate":
            stages["review"] = {"at": "generate"} if workflow.get("policy") == "review" else stages.get("review")
        return f"the {stage} time"
    publish = stages.get("publish")
    if workflow and stage in ("auto", "publish") and automation_plan._is_separate(publish):
        spec = dict(publish)
        if days:
            spec = {"weekday": days[0], "localTime": local or spec.get("localTime") or schedule.get("localTime", "09:00")}
        elif local:
            spec = {**spec, "localTime": local} if "localTime" in spec else {"dayOffset": 0, "localTime": local}
        stages["publish"] = spec
        return "the publish time"
    if schedule.get("kind") == "once":
        if date:
            schedule["date"] = date
        elif days:
            today = dt.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(zone)).date()
            target = workflows.WEEKDAY_NAMES.index(days[0])
            ahead = (target - today.weekday()) % 7 or 7
            schedule["date"] = (today + dt.timedelta(days=ahead)).isoformat()
        if local:
            schedule["localTime"] = local
        return "the date and time"
    if schedule.get("kind") == "monthly":
        if local:
            schedule["localTime"] = local
        return "the time"
    if days:
        times = {slot["localTime"] for slot in schedule.get("slots") or []} or {schedule.get("localTime")}
        base = local or (next(iter(times)) if len(times) == 1 else schedule.get("localTime"))
        payload["schedule"] = {"weekdays": days, "localTime": base, "timeZone": schedule["timeZone"]}
    elif local:
        payload["schedule"] = {"weekdays": schedule["weekdays"], "localTime": local, "timeZone": schedule["timeZone"]}
    return "the schedule"


def apply(state: dict, actor: str, now: float, edit: dict, *, conversation_task_id: str | None, owner: bool, paid: bool, zone: str) -> dict:
    """Apply one Edit reading. Returns {"view", "summary", "task"} or {"ask": text, "candidates": [...]}."""
    target, candidates = resolve(state, (edit.get("target") or {}).get("name"), conversation_task_id)
    if target is None:
        names = [task.get("name") or "Automation" for task in candidates]
        if not names:
            raise AlphaError("You don't have an automation to change yet.")
        return {"ask": "Which automation do you mean?", "candidates": names}
    changes = edit.get("changes") or []
    if not changes:
        raise AlphaError("Tell me what to change: the day or time, platforms, sources, whether it publishes automatically, or pause/delete it.")
    done = []
    control = next((c for c in changes if c["op"] in ("delete", "pause", "resume")), None)
    if control is not None:
        if not owner:
            raise AlphaError("Only an owner of this workspace can pause, resume or delete an automation.", 403)
        if control["op"] == "delete":
            campaigns.apply_action(state, "raffi_recurrence_cancel", {"taskId": target["id"], "confirmed": True, "delete": True}, actor, now)
            done.append("deleted it; posts it had not published yet won't go out")
        elif control["op"] == "pause":
            until = None
            if control.get("days"):
                until = now + int(control["days"]) * 86400
            elif control.get("until"):
                day = dt.date.fromisoformat(control["until"])
                until = dt.datetime(day.year, day.month, day.day, 0, 0, tzinfo=zoneinfo.ZoneInfo(target["schedule"]["timeZone"])).timestamp()
            campaigns.apply_action(state, "raffi_recurrence_pause", {"taskId": target["id"], **({"until": until} if until else {})}, actor, now)
            done.append(f"paused it until {automation_plan._local_label(dt.datetime.fromtimestamp(until, zoneinfo.ZoneInfo(target['schedule']['timeZone'])).isoformat())}" if until else "paused it")
        else:
            campaigns.apply_action(state, "raffi_recurrence_resume", {"taskId": target["id"], "confirmed": True}, actor, now)
            done.append("turned it back on")
        view = automation_plan.card(state, target["id"], [], [])
        return {"view": view, "summary": done, "task": target["id"]}
    was_status = target["status"]
    previous_grant = dict(target.get("publishAuthority") or {})
    grant = None
    if previous_grant.get("grantedBy") == actor and was_status == "active":
        # The same owner's standing authority for this automation continues, never widened by the edit.
        grant = {"confirmed": True, "sourceUse": previous_grant.get("sourceUse") is True}
    payload = _payload(state, target)
    zone = target["schedule"]["timeZone"]
    for change in changes:
        op = change["op"]
        workflow = payload.get("workflow")
        if op == "move":
            done.append(f"moved {_move(payload, change, zone, now)}")
        elif op == "remove_platform":
            kept = [d for d in payload["destinations"] if d["platform"] != change["platform"]]
            if not kept:
                raise AlphaError(f"{change['platform']} is its only platform. Delete the automation instead, or add another platform first.")
            if len(kept) != len(payload["destinations"]):
                payload["destinations"] = kept
                done.append(f"stopped posting to {change['platform']}")
        elif op == "add_platform":
            if change["platform"] not in PLATFORMS:
                raise AlphaError(f"Rafii can't prepare {change['platform']} posts yet.")
            if not any(d["platform"] == change["platform"] for d in payload["destinations"]):
                destination = {"platform": change["platform"], "language": payload["destinations"][0]["language"]}
                accounts = [c for c in (state.get("phase2") or {}).get("channels", []) if c.get("platform") == change["platform"] and not c.get("revoked")]
                if len(accounts) == 1:
                    destination["channelId"] = accounts[0]["id"]
                payload["destinations"].append(destination)
                done.append(f"added {change['platform']}")
        elif op == "sources":
            workflow = payload["workflow"] = workflow or _default_workflow(target, "drafts")
            research = dict(workflow.get("research") or {"query": clean(payload["goal"], 300), "about": "", "onNothing": "skip", "recencyDays": 7})
            research.update(domains=change.get("domains") or [], publications=change.get("publications") or "")
            workflow["research"] = research
            done.append(f"switched the source to {change.get('publications') or ', '.join(change.get('domains') or [])}")
        elif op == "policy":
            if change["policy"] == "auto" and not owner:
                raise AlphaError("Only an owner can let Rafii publish without approval.", 403)
            workflow = payload["workflow"] = workflow or _default_workflow(target, change["policy"])
            workflow["policy"] = change["policy"]
            if change["policy"] == "auto":
                # The owner asked for it in this message: the grant covers publishing from sources Rafii finds only
                # if an earlier grant did, or the automation researches and the owner asked now.
                grant = {"confirmed": True, "sourceUse": previous_grant.get("sourceUse", True) is True and bool(workflow.get("research"))}
            stages, _ = automation_plan.stages_for({"policy": change["policy"], "stages": {k: v for k, v in (workflow.get("stages") or {}).items() if k == "publish" or (k == "generate" and change["policy"] != "auto")}, "timeRole": "publish"}, payload["schedule"], change["policy"])
            workflow["stages"] = stages
            done.append({"auto": "set it to publish automatically", "review": "set it to wait for your approval", "drafts": "set it to prepare drafts only"}[change["policy"]])
        elif op == "topic":
            payload["goal"] = clean(f"{payload['goal'].split(' about ')[0]} about {change['topic']}.", 1200)
            if workflow and workflow.get("research"):
                workflow["research"]["about"] = clean(change["topic"], 160)
            done.append(f"changed the topic to {change['topic']}")
        elif op == "instructions" and workflow:
            workflow.setdefault("content", {})["instructions"] = clean(change.get("text") or "", 600)
            done.append("updated the writing instructions")
        elif op == "voice":
            payload["voiceMode"] = "personalized" if change.get("voice") else "neutral"
            done.append("switched to your voice" if change.get("voice") else "switched to a neutral voice")
    if not done:
        raise AlphaError("That already matches this automation.")
    saved = campaigns.apply_action(state, "raffi_recurrence_save", payload, actor, now)
    task = next(t for t in campaigns._root(state)["recurringTasks"] if t["id"] == saved["taskId"])
    # An automation that was on stays on (the owner is the one changing it); a paused one stays paused.
    needs = automation_plan.activate(state, task["id"], actor, now, owner=owner, paid=paid, question=None, grant=grant) if was_status in ("active", "draft") else []
    if was_status == "paused" and task["status"] == "draft":
        needs.append({"code": "paused", "text": "It was paused, so it stays off until you turn it back on."})
    view = automation_plan.card(state, task["id"], needs, [])
    return {"view": view, "summary": done, "task": task["id"]}


def reply(result: dict) -> str:
    if "ask" in result:
        return f"{result['ask']} " + ("You have: " + automation_chat._join([f"“{name}”" for name in result["candidates"]]) + "." if result.get("candidates") else "")
    view = result["view"]
    what = automation_chat._join(result["summary"])
    if view.get("status") == "cancelled":
        return f"Done — I {what}. Its run history stays in Automations."
    text = f"Done — I {what}."
    if view.get("workflow") and view["status"] == "active":
        plan = automation_plan.reply(view)
        text += " " + plan.removeprefix("Done. ")
    elif view["status"] == "paused":
        text += " Nothing runs or publishes until it's back on."
    elif view["status"] != "active":
        text += " It's waiting for you before it runs; the card below says what's left."
    return text

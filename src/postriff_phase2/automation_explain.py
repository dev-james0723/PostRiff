"""Answer "why?" about an automation from its run history (orchestration §7, spec §15).

"Why did Rafii post this?", "Where did this article come from?", "Why wasn't yesterday's post published?" are answered
from what the runs recorded: what triggered them, which source was chosen and how it scored, which skills ran, who or
what approved each post, when it was due to publish and what happened. Nothing here is generated: every sentence is
read from the stored run, so the answer cannot claim something that did not happen.
"""
from __future__ import annotations

import datetime as dt
import re
import zoneinfo

from . import automation_chat, automation_edit, automation_plan, campaigns, lifecycle


def _when(at: float | None, zone: str) -> str:
    if not at:
        return "an unknown time"
    local = dt.datetime.fromtimestamp(at, zoneinfo.ZoneInfo(zone))
    return f"{local.strftime('%A')} {local.day} {local.strftime('%B')} at {local.strftime('%H:%M')}"


def _runs(state: dict, task: dict) -> list[dict]:
    return sorted([o for o in campaigns._root(state)["occurrences"] if o["taskId"] == task["id"]], key=lambda o: o.get("anchorAt") or o["scheduledFor"], reverse=True)


def _pick_run(runs: list[dict], about: str, text: str, zone: str, now: float) -> dict | None:
    if not runs:
        return None
    lowered = text.lower()
    today = dt.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(zone)).date()
    wanted_day = today - dt.timedelta(days=1) if "yesterday" in lowered else today if "today" in lowered else None
    if wanted_day is not None:
        for run in runs:
            publish = (run.get("stages") or {}).get("publishAt") or run.get("anchorAt") or run["scheduledFor"]
            if dt.datetime.fromtimestamp(publish, zoneinfo.ZoneInfo(zone)).date() == wanted_day:
                return run
    if about == "source":
        return next((run for run in runs if (run.get("research") or {}).get("chosen")), runs[0])
    if about == "why_posted":
        return next((run for run in runs if any(i.get("state") == "published" for i in run.get("items") or [])), runs[0])
    if about == "not_published":
        return next((run for run in runs if run.get("lifecycle") in ("skipped", "source_unavailable", "failed") or any(i.get("state") in ("approval_expired", "failed", "platform_disconnected", "rejected", "skipped") for i in run.get("items") or [])), runs[0])
    return runs[0]


def _item_line(item: dict, task: dict, zone: str) -> str:
    where = item["platform"] + (f" ({item['account']})" if item.get("account") else "")
    state = item.get("state")
    decision = item.get("decision") or {}
    if state == "published":
        via = "under the automatic-publishing permission you gave" if item.get("approvedVia") == "owner_preauthorization" else "after you approved it" if decision.get("decision") == "approve" else ""
        return f"{where}: published {via}".rstrip() + (f" — {item['url']}" if item.get("url") else "") + "."
    label = lifecycle.LABELS.get(state, state)
    reason = item.get("reason") or (item.get("capability") or {}).get("reason") if state in ("ready_for_review",) and item.get("publishAt") is None else item.get("reason")
    line = f"{where}: {label.lower()}"
    if state in ("scheduled", "approved") and item.get("publishAt"):
        line += f" for {_when(item['publishAt'], zone)}"
    if reason:
        line += f" — {reason}"
    return line + ("" if line.endswith(".") else ".")


def answer(state: dict, text: str, explain: dict, *, conversation_task_id: str | None, now: float) -> dict:
    """{"text": reply, "lines": [...], "taskId"} built only from stored runs."""
    task, candidates = automation_edit.resolve(state, (explain.get("target") or {}).get("name"), conversation_task_id)
    if task is None:
        tasks = [t for t in campaigns._root(state)["recurringTasks"] if not t.get("deletedAt")]
        with_runs = [t for t in tasks if any(o["taskId"] == t["id"] for o in campaigns._root(state)["occurrences"])]
        task = max(with_runs, key=lambda t: max(o["scheduledFor"] for o in campaigns._root(state)["occurrences"] if o["taskId"] == t["id"]), default=None)
    if task is None:
        return {"text": "None of your automations has run yet, so there's nothing to explain.", "lines": [], "taskId": None}
    zone = task["schedule"]["timeZone"]
    about = explain.get("about") or "status"
    run = _pick_run(_runs(state, task), about, text, zone, now)
    name = task.get("name") or "your automation"
    lines = []
    if run is None:
        nxt = task.get("nextOccurrence")
        text_out = f"“{name}” hasn't run yet." + (f" Its first run is {automation_plan._local_label(nxt['local'])}." if nxt else "")
        return {"text": text_out, "lines": [], "taskId": task["id"]}
    trigger = run.get("event") or {}
    if trigger:
        lines.append(f"Trigger: {'new material in Ideas' if trigger.get('kind') == 'new_source' else 'a strong recent post'}.")
    else:
        lines.append(f"Trigger: the schedule ({automation_plan.describe(task['schedule'])}); this run was for {_when(run.get('anchorAt') or run['scheduledFor'], zone)}.")
    research = run.get("research") or {}
    if research:
        chosen = research.get("chosen") or {}
        if chosen.get("url"):
            published = f", published {chosen['published'][:10]}" if chosen.get("published") else ""
            score = f"; it scored {chosen['score']:.2f} on relevance and quality" if isinstance(chosen.get("score"), (int, float)) else ""
            lines.append(f"Source: “{chosen.get('title') or chosen['url']}” from {chosen.get('host') or 'the web'}{published} — {chosen['url']}{score}. Rafii searched {', '.join(research.get('domains') or []) or 'the web'} for “{research.get('query')}”.")
        elif research.get("reason"):
            lines.append(f"Source: {research['reason']}")
        quote = research.get("quote") or {}
        if quote.get("text"):
            lines.append(f"Quote: “{quote['text']}” — {quote.get('author') or 'unknown'}; " + ("attribution confirmed on " + ", ".join(quote.get("hosts", [])) if quote.get("verified") else "attribution not confirmed, so it wasn't presented as verified") + ".")
    skills = [s for s in run.get("skills") or [] if s.get("status") in ("done", "failed")]
    if skills:
        lines.append("Steps: " + ", ".join(dict.fromkeys(s.get("label") or s["skill"] for s in skills)) + ".")
    policy = run.get("policy") or (task.get("workflow") or {}).get("policy")
    lines.append({"auto": "Approval: publishes automatically when a post passes every safety check; otherwise it waits for you.",
                  "review": "Approval: required — nothing publishes without it.", "drafts": "Approval: drafts only; nothing is published."}.get(policy, "Approval: drafts only."))
    stage = run.get("lifecycle")
    if stage in ("skipped", "source_unavailable", "failed"):
        last = next((h for h in reversed(run.get("history") or []) if h.get("event") in (stage, "missed", "cancelled", "stopped")), None)
        lines.append(f"Outcome: {lifecycle.LABELS.get(stage, stage)} — {(last or {}).get('detail') or run.get('reason') or ''}".rstrip(" —") + ".")
    for item in run.get("items") or []:
        lines.append(_item_line(item, task, zone))
    lead = {"why_posted": f"Here's why “{name}” posted this:", "source": f"Here's where “{name}” got its source:",
            "not_published": f"Here's what happened with “{name}”:", "next": f"Here's what's next for “{name}”:"}.get(about, f"Here's the latest from “{name}”:")
    if about == "next":
        nxt = task.get("nextOccurrence")
        lines.insert(0, f"Next run: {automation_plan._local_label(nxt['local'])}" + (f"; it publishes {automation_plan._local_label(task.get('nextPublish'))}" if task.get("nextPublish") else "") + "." if nxt else "No further runs are scheduled.")
    return {"text": lead + "\n" + "\n".join(f"• {line}" for line in lines), "lines": lines, "taskId": task["id"], "occurrenceId": run["id"], "about": about}

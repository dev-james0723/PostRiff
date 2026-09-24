"""From a reading of a chat message to a staged automation Raffi can run (orchestration §7).

A Reading (request_model or workflow_parse) says what the person asked for; this module completes it into an
automation the engine accepts: the schedule, when drafting, review and publication happen, the publish policy,
research and source limits, per-platform notes, and the destinations with their accounts. It asks only what
materially blocks running it (how posts publish, and for posts that wait for approval, when drafts should be
ready), saves the automation with the Automations checks (`raffi_recurrence_save`, same task on every answer or
edit, so nothing is duplicated), and turns it on when an owner asked and nothing is left to decide.

Everything the person reads is plain words: no cron, ids or JSON. What cannot publish is said, never promised.
"""
from __future__ import annotations

import datetime as dt
import re
import zoneinfo

from postriff_alpha.domain import AlphaError, clean

from . import automation_chat, campaigns, capabilities, research as web_research, workflow as workflows, workflow_parse
from .agent_runtime import PLATFORMS

POLICY_REPLIES = ("Publish automatically", "Send them to me for approval first", "Just prepare drafts")
POLICY_QUESTION = "Should I publish these automatically, or send them to you for approval first?"
REVIEW_QUESTION = "When would you like the drafts ready for your review?"
AUTO_LEAD = {"minutesOffset": -workflows.AUTO_LEAD_MINUTES}
CONTENT_WORDS = {"post": "a post", "reflection": "a personal reflection", "quote": "a quote post", "summary": "a summary", "update": "a status update",
                 "announcement": "an announcement", "promotion": "a promotional post", "education": "an educational post", "thread": "a thread",
                 "recap": "a recap", "tip": "a tip", "story": "a story", "question": "a question for your audience"}


def needs_workflow(reading: dict, text: str) -> bool:
    """A staged automation (v3) when the request involves publishing, stages, research, a one-time date or
    per-platform notes; a request only to keep drafting on a schedule stays a drafts automation (v2)."""
    schedule = reading.get("schedule") or {}
    stages = reading.get("stages") or {}
    return bool(schedule.get("kind") == "once" or any(stages.get(key) for key in ("generate", "review", "publish"))
                or reading.get("policy") in ("auto", "review") or reading.get("research") or reading.get("platformNotes")
                or workflow_parse.wants_publishing(text) or len({slot.get("localTime") for slot in schedule.get("slots") or []}) > 1)


def _schedule(reading: dict, zone: str, now: float, notes: list) -> dict:
    raw = reading.get("schedule") or {}
    kind = raw.get("kind")
    default = workflow_parse.DEFAULT_TIME
    if kind == "once":
        local_now = dt.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(zone))
        date = raw.get("date") or local_now.date().isoformat()
        if not raw.get("localTime"):
            notes.append(f"No time was named, so it's planned for {default}.")
        return {"kind": "once", "date": date, "localTime": raw.get("localTime") or default, "timeZone": zone}
    if kind == "monthly":
        if not raw.get("localTime"):
            notes.append(f"No time was named, so each run starts at {default}.")
        return {"kind": "monthly", "monthDays": raw.get("monthDays") or [1], "localTime": raw.get("localTime") or default, "timeZone": zone}
    slots = [slot for slot in raw.get("slots") or [] if isinstance(slot, dict) and slot.get("weekday")]
    if not slots and reading.get("weekdays"):
        slots = [{"weekday": day, "localTime": reading.get("localTime")} for day in reading["weekdays"]]
    if not slots:
        raise AlphaError("Say when this should run, like “every Wednesday at 5 PM” or “today at 2 PM”.")
    if any(not slot.get("localTime") for slot in slots) and not any("time was named" in note for note in notes):
        notes.append(f"No time was named, so each run starts at {default}.")
    return campaigns.normalize_schedule({"weekdays": [slot["weekday"] for slot in slots], "localTime": slots[0].get("localTime") or default,
                                         "slots": [{"weekday": slot["weekday"], "localTime": slot.get("localTime") or default} for slot in slots], "timeZone": zone})


def _is_separate(when: dict | None) -> bool:
    """A publish instant of its own (another day, or after the anchor), as opposed to "at the scheduled time"."""
    if not when or when.get("at") == "anchor":
        return False
    return "weekday" in when or when.get("dayOffset", 0) > 0 or when.get("minutesOffset", 0) > 0


def _anchor_relative(review: dict, schedule: dict) -> dict:
    """A review named by weekday ("Thursday at 5 PM") before an anchor that publishes: as a day offset from the
    anchor, so drafting can happen before it (a weekday spec resolves after drafting)."""
    if "weekday" not in review:
        return review
    if schedule.get("kind") == "once":
        anchor = dt.date.fromisoformat(schedule["date"])
        target = workflows.WEEKDAY_NAMES.index(review["weekday"])
        offset = -((anchor.weekday() - target) % 7) or 0
        return {"dayOffset": offset, "localTime": review["localTime"]}
    days = campaigns.slots_of(schedule)
    target = workflows.WEEKDAY_NAMES.index(review["weekday"])
    offset = -((days[0][0] - target) % 7)
    return {"dayOffset": offset, "localTime": review["localTime"]}


def stages_for(reading: dict, schedule: dict, policy: str | None) -> tuple[dict, str | None]:
    """(stages, question) — the question is "review_time" when approval is wanted and nothing says when."""
    given = reading.get("stages") or {}
    publish, review, generate = given.get("publish"), given.get("review"), given.get("generate")
    if policy == "drafts":
        return {"generate": generate or ({"asap": True} if schedule.get("kind") == "once" else {"at": "anchor"}), "review": None, "publish": None}, None
    publish = publish or {"at": "anchor"}
    question = None
    if generate is None:
        if schedule.get("kind") == "once":
            generate = {"asap": True}
        elif _is_separate(publish):
            generate = {"at": "anchor"}
        elif policy == "auto":
            generate = AUTO_LEAD if reading.get("timeRole", "publish") == "publish" else {"at": "anchor"}
        elif policy == "review":
            if review is not None and "weekday" in review and schedule.get("kind") == "monthly":
                # A weekday isn't a fixed distance from a monthly date: ask how long before instead.
                generate, review, question = {"minutesOffset": -120}, None, "review_time"
            elif review is not None:
                generate = _anchor_relative(review, schedule) if "weekday" in review else review if ("dayOffset" in review or "minutesOffset" in review) else {"minutesOffset": -120}
                review = {"at": "generate"}
            else:
                generate, question = {"minutesOffset": -120}, "review_time"
        else:
            generate = {"at": "anchor"}
    if policy == "review" and review is None and question is None:
        review = {"at": "generate"}
        if not _is_separate(publish) and schedule.get("kind") != "once" and generate.get("at") == "anchor":
            question = "review_time"
    if policy == "auto":
        review = None
    return {"generate": generate, "review": review, "publish": publish}, question


def review_replies(schedule: dict) -> list[str]:
    """Quick replies for "when should drafts be ready?" that make sense for this schedule."""
    hour = int((schedule.get("localTime") or "09:00")[:2]) if schedule.get("kind") != "once" else None
    replies = ["The day before at 17:00"]
    if hour is None or hour >= 11:
        replies.append("The same day at 09:00")
    replies.append("2 hours before")
    return replies


def answer_review_time(text: str, schedule: dict) -> dict | None:
    """The drafting instant a reply to "when should the drafts be ready?" names, or None."""
    if workflow_parse.is_drafting_request(text) or len(text.split()) > 12:
        return None
    anchor_time = schedule.get("localTime")
    relative = workflow_parse._offset_when(text, anchor_time)
    if relative is not None:
        return relative
    days = workflow_parse._days_in(text)
    local = workflow_parse._time_in(text)
    if days:
        return _anchor_relative({"weekday": days[0], "localTime": local or "09:00"}, schedule) if schedule.get("kind") != "monthly" else None
    if re.search(r"\bsame\s+(?:day|morning)\b|\bthat\s+morning\b|\bmorning\s+of\b", text, re.I):
        return {"dayOffset": 0, "localTime": local or "09:00"}
    return None


def answer_policy(text: str) -> str | None:
    """The publishing decision in a reply to Rafii's question. Automatic publishing needs the button or explicit,
    non-negated wording; anything mentioning approval or review means review; unclear replies answer nothing."""
    lowered = text.strip().lower()
    for policy, reply in zip(("auto", "review", "drafts"), POLICY_REPLIES):
        if lowered == reply.lower():
            return policy
    if workflow_parse.is_drafting_request(text) or len(lowered.split()) > 14:
        return None
    if re.search(r"\bapprov\w*|\breview\w*|\bcheck\s+(?:it|them)\s+first\b|\bme\s+first\b|\bask\s+me\b|\bdon'?t\s+(?:publish|post)\s+automatically\b", lowered):
        return "review"
    found = workflow_parse._policy(text)
    if found:
        return found
    if re.search(r"\bdrafts?\b|\bdon'?t\s+publish\b|\bmyself\b", lowered):
        return "drafts"
    return None


def destinations_for(state: dict, reading: dict, fallback: list[dict], notes: list) -> list[dict]:
    """The platforms the person named (their languages as Home would choose), else Home's destinations; each
    platform gets its connected account when the workspace has exactly one there."""
    named = list(dict.fromkeys(reading.get("platforms") or []))
    unsupported = [name for name in named if name not in PLATFORMS]
    if unsupported:
        notes.append(f"Rafii can't prepare {automation_chat._join(unsupported)} posts yet, so {'it was' if len(unsupported) == 1 else 'they were'} left out.")
    wanted = [name for name in named if name in PLATFORMS]
    by_platform = {}
    for destination in fallback:
        by_platform.setdefault(destination["platform"], []).append(destination)
    language = (fallback[0]["language"] if fallback else None) or "en"
    out = []
    for platform in wanted or [d["platform"] for d in fallback]:
        chosen = by_platform.get(platform) or [{"platform": platform, "language": language}]
        out += [{key: d[key] for key in ("platform", "language", "channelId") if d.get(key)} for d in chosen]
    if not out:
        out = [{"platform": "LinkedIn", "language": language}]
    channels = [c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and not c.get("revoked")]
    for destination in out:
        if not destination.get("channelId"):
            accounts = [c for c in channels if c.get("platform") == destination["platform"]]
            if len(accounts) == 1:
                destination["channelId"] = accounts[0]["id"]
    return campaigns.normalize_destinations(state, out)


def research_for(reading: dict, notes: list) -> dict | None:
    raw = reading.get("research")
    if not raw:
        return None
    try:
        return workflows.normalize_research({key: value for key, value in raw.items() if key in ("query", "about", "domains", "publications", "urls", "recencyDays", "minScore", "onNothing", "quote")})
    except AlphaError as error:
        notes.append(f"Part of the research request couldn't be used ({error}).")
        try:
            return workflows.normalize_research({**{k: v for k, v in raw.items() if k in ("query", "about", "publications", "onNothing", "quote")}, "domains": [], "urls": []})
        except AlphaError:
            return None


def build(state: dict, actor: str, now: float, text: str, zone: str, reading: dict, *, destinations: list[dict], route: str, reasoning: str,
          voice: bool, voice_route: str, source_ids: list[str], task_id: str | None = None, policy_override: str | None = None,
          generate_override: dict | None = None) -> tuple[dict, str | None, list[str]]:
    """(save payload, pending question or None, notes) for a reading. Overrides come from answers to questions."""
    notes = list(reading.get("assumptions") or [])
    schedule = _schedule(reading, zone, now, notes)
    policy = policy_override or reading.get("policy")
    if policy is None and not workflow_parse.wants_publishing(text) and not (reading.get("stages") or {}).get("publish"):
        policy = "drafts"
    stages, question = stages_for({**reading, "policy": policy}, schedule, policy)
    if generate_override is not None:
        stages = {**stages, "generate": generate_override, "review": {"at": "generate"}}
        question = None
    if policy is None:
        question = "policy"
    chosen = destinations_for(state, reading, destinations, notes)
    research = research_for(reading, notes)
    if research and not web_research.allowed(state):
        # Never promise a step that can't run: say what is missing now, while the automation is still saved.
        notes.append("Web research is off for this workspace, so runs can't look for sources until an owner turns it on under Memory → Web research.")
    content = reading.get("content") or {}
    topic = clean(reading.get("topic") or "", 160)
    task_word = CONTENT_WORDS.get(content.get("task") or "post", "a post")
    quote = (research or {}).get("quote")
    if reading.get("goal"):
        goal = clean(reading["goal"], 1200)
    elif topic:
        goal = f"{task_word[0].upper()}{task_word[1:]} about {topic}."
    elif quote:
        phrase = automation_chat._phrase(text)
        goal = f"{automation_chat._upper_first(automation_chat._with_article(phrase)) if phrase != 'post' else 'A quote post'} built around a quote by {_with_article(quote['about'])}."
    else:
        goal = clean(text, 1200)
    name = clean(reading.get("name") or (f"{topic} · {task_word.split(' ', 1)[1]}" if topic else automation_chat._upper_first(task_word.split(" ", 1)[1])), 120)
    personalized = voice or bool(reading.get("voice"))
    if personalized and not automation_chat.voice_available(state, voice_route):
        notes.append("No writing sample is allowed for this writer yet, so drafts stay neutral until you allow one on the Brand page.")
    content_type = automation_chat.content_by_id(state, actor, now, reading["contentTypeId"], reading.get("formatId")) if reading.get("contentTypeId") else None
    workflow = {"policy": policy, "stages": stages, "research": research,
                "content": {"task": content.get("task") or "post", "instructions": content.get("instructions") or ""},
                "platformNotes": reading.get("platformNotes") or {}}
    audience = clean((state.get("brandHub") or {}).get("audience") or "", 800) or automation_chat.DEFAULT_AUDIENCE
    payload = {"name": name, "goal": goal, "audience": audience, "facts": {}, "schedule": schedule, "destinations": chosen,
               "contentType": content_type, "route": route, "reasoning": reasoning if reasoning in campaigns.REASONING else "quick",
               "maxCostUsdMicro": 0, "sourceIds": source_ids, "include": None, "voiceMode": "personalized" if personalized else "neutral",
               "workflow": workflow, "intent": clean(text, 600)}
    if task_id:
        payload["taskId"] = task_id
    return payload, question, notes


def activate(state: dict, task_id: str, actor: str, now: float, *, owner: bool, paid: bool, question: str | None, grant: dict | None = None) -> list[dict]:
    """Turn the automation on when nothing is left to decide; else say what is left (the card lists it). An
    auto-publish automation turns on only with `grant`: the owner's explicit request in this turn (or their own
    earlier grant for this automation, carried over unchanged), never implied by another change."""
    root = campaigns._root(state)
    task = next(item for item in root["recurringTasks"] if item["id"] == task_id)
    campaign = next(item for item in root["campaigns"] if item["id"] == task["campaignId"])
    needs = []
    if question:
        return needs
    if not owner:
        needs.append({"code": "owner", "text": "An owner of this workspace turns it on."})
    if paid:
        needs.append({"code": "spend", "text": "This writer charges per run, so choose how much each run may spend, then turn it on."})
    if campaign.get("missingFacts"):
        needs.append({"code": "facts", "text": f"Add the {automation_chat._join(campaign['missingFacts'])} first, then turn it on."})
    if needs or task["status"] == "active":
        return needs
    policy = (task.get("workflow") or {}).get("policy")
    payload = {"taskId": task_id, "confirmed": True}
    if policy == "auto":
        if not grant or grant.get("confirmed") is not True:
            needs.append({"code": "auto_publish", "text": "Confirm that Rafii may publish these without asking you each time, or choose approval first."})
            return needs
        # The owner's explicit request: the standing authority for this exact definition (and, when it researches,
        # for publishing from the sources Rafii finds for it, unless an earlier grant said otherwise).
        payload["publishAuthority"] = {"confirmed": True, "sourceUse": grant.get("sourceUse") is True}
    try:
        campaigns.apply_action(state, "raffi_recurrence_activate", payload, actor, now)
    except AlphaError as error:
        needs.append({"code": "review", "text": str(error)})
    return needs


def _local_label(iso: str | None) -> str | None:
    if not iso:
        return None
    local = dt.datetime.fromisoformat(iso)
    return f"{local.strftime('%A')} {local.day} {local.strftime('%B')} at {local.strftime('%H:%M')}"


def plan_lines(task: dict) -> list[dict]:
    """Plain-language steps with when each happens, for the card and the confirmation."""
    workflow = task.get("workflow") or {}
    schedule = task["schedule"]
    stages = workflow.get("stages") or {}
    lines = []
    if schedule.get("kind") == "once":
        start = "Now" if (stages.get("generate") or {}).get("asap") else workflows.describe_when(stages.get("generate"), schedule, "generate")
    else:
        start = describe(schedule)
        generate = stages.get("generate") or {"at": "anchor"}
        if generate.get("at") != "anchor":
            start = f"{start} ({workflows.describe_when(generate, schedule, 'generate')})"
    research = workflow.get("research")
    if research:
        named = research.get("publications") or ", ".join(research.get("domains") or [])
        where = f"from {named}" if named else "on the web"
        look = f"a quote by {_with_article(research['quote']['about'])}" if research.get("quote") else f"something about {research.get('about') or research.get('query')}"
        lines.append({"step": "research", "when": start, "text": f"Look for {look} {where}" + (" (skipped if nothing is worth posting)" if research.get("onNothing") == "skip" else "")})
    platforms = automation_chat._join(list(dict.fromkeys(d["platform"] for d in task["destinations"])))
    task_word = CONTENT_WORDS.get((workflow.get("content") or {}).get("task") or "post", "a post")
    voice = " in your voice" if task.get("voiceMode") == "personalized" else ""
    lines.append({"step": "draft", "when": start, "text": f"Write {task_word}{voice} for {platforms}"})
    policy = workflow.get("policy")
    if policy == "review":
        review = stages.get("review") or {"at": "generate"}
        lines.append({"step": "review", "when": "When drafted" if review.get("at") == "generate" else workflows.describe_when(review, schedule, "review"),
                      "text": "Ready for your approval — nothing publishes without it"})
    if policy in ("review", "auto"):
        publish = stages.get("publish") or {"at": "anchor"}
        when = (_once_label(schedule) if schedule.get("kind") == "once" else describe(schedule)) if publish.get("at") == "anchor" else workflows.describe_when(publish, schedule, "publish")
        lines.append({"step": "publish", "when": when, "text": "Publish automatically" if policy == "auto" else "Publish once approved"})
    elif policy == "drafts":
        lines.append({"step": "drafts", "when": None, "text": "Kept as drafts for you to schedule"})
    return lines


def _with_article(words: str) -> str:
    """"famous scientist" → "a famous scientist"; names and phrases that already have one are kept."""
    words = (words or "").strip()
    if not words or words[:1].isupper() or re.match(r"(?:a|an|the|my|our|one|some)\s", words, re.I):
        return words
    return ("an " if words[:1].lower() in "aeiou" else "a ") + words


def _once_label(schedule: dict) -> str:
    date = dt.date.fromisoformat(schedule["date"])
    return f"{date.strftime('%A')} {date.day} {date.strftime('%B')} at {schedule['localTime']}"


def describe(schedule: dict) -> str:
    if schedule.get("kind") == "once":
        return f"On {_once_label(schedule)} ({schedule.get('timeZone', 'UTC')})"
    if schedule.get("slots"):
        return "Every " + automation_chat._join([f"{slot['weekday']} at {slot['localTime']}" for slot in schedule["slots"]]) + f" ({schedule.get('timeZone', 'UTC')})"
    return automation_chat.describe(schedule)


def card(state: dict, task_id: str, needs: list[dict], notes: list[str], *, question: str | None = None, providers=None, live: bool = False, tier: str | None = None) -> dict:
    """The chat card: today's fields plus the plan, the policy, what can publish where, and any question."""
    view = automation_chat.card(state, task_id, needs, notes)
    root = campaigns._root(state)
    task = next(item for item in root["recurringTasks"] if item["id"] == task_id)
    view["scheduleText"] = describe(task["schedule"])
    workflow = task.get("workflow")
    if not workflow:
        return view
    platforms = capabilities.summary(state, task["destinations"], providers=providers, live=live)
    policy = workflow.get("policy")
    runs = [o for o in root["occurrences"] if o["taskId"] == task_id][-3:]
    view.update({
        "workflow": workflow, "policy": policy, "plan": plan_lines(task), "platforms": platforms,
        "skills": workflows.compose(task), "nextPublish": _local_label(task.get("nextPublish")),
        "firstRun": _local_label((task.get("nextOccurrence") or {}).get("local")) if task.get("nextOccurrence") else None,
        "pending": {"taskId": task_id, "question": question} if question else None,
        "question": POLICY_QUESTION if question == "policy" else REVIEW_QUESTION if question == "review_time" else None,
        "quickReplies": list(POLICY_REPLIES) if question == "policy" else review_replies(task["schedule"]) if question == "review_time" else [],
        "runs": [{"occurrenceId": o["id"], "lifecycle": o.get("lifecycle"), "state": o["state"]} for o in runs],
        "tier": tier,
    })
    return view


def reply(view: dict | None, failure: str | None = None) -> str:
    """Raffi's confirmation in plain words: what runs when, what publishes where, what cannot, what is left."""
    if view is None:
        return f"I couldn't set that up: {failure or 'something in the request is not available.'} Tell me what to change, or build it in Automations."
    if not view.get("workflow"):
        return automation_chat.reply(view)
    if view.get("pending"):
        lead = "I've drafted the plan below." if view["pending"]["question"] == "policy" else "Almost set."
        return f"{lead} {view['question']}"
    lines = {line["step"]: line for line in view["plan"]}
    parts = []
    first = next(iter(view["plan"]), None)
    when = (first or {}).get("when") or ""
    research = lines.get("research")
    draft = lines.get("draft")
    stages = (view.get("workflow") or {}).get("stages") or {}
    generate = stages.get("generate") or {"at": "anchor"}
    if when and " (" in when and generate.get("at") != "anchor" and not generate.get("asap"):
        # Drafting ahead of the schedule: say when the drafts are written, then when the posts are for.
        schedule_words = when.rsplit(" (", 1)[0]
        ahead = workflows.describe_when(generate, view["schedule"], "generate")
        when = f"{ahead[0].upper()}{ahead[1:]}, for posts {schedule_words[0].lower()}{schedule_words[1:]}"
    sentence = f"{when}, Rafii will " if when and when != "Now" else "Rafii will now "
    actions = []
    if research:
        actions.append(research["text"][0].lower() + research["text"][1:].replace(" (skipped if nothing is worth posting)", ""))
    if draft:
        actions.append(draft["text"][0].lower() + draft["text"][1:])
    policy = view.get("policy")
    if policy == "review":
        review = lines.get("review")
        actions.append("have it ready for your approval" + (f" {review['when']}" if review and review.get("when") and review["when"] != "When drafted" else ""))
    parts.append(sentence + automation_chat._join(actions) + ".")
    publishable = [p for p in view.get("platforms") or [] if p["canPublish"]]
    blocked = [p for p in view.get("platforms") or [] if not p["canPublish"]]
    publish = lines.get("publish")
    if policy == "review" and publish:
        if publishable:
            parts.append(f"Once you approve, it publishes {publish['when'][0].lower() + publish['when'][1:] if publish['when'].startswith(('Every', 'On')) else publish['when']} to {automation_chat._join([p['platform'] for p in publishable])}. Nothing publishes without your approval.")
        else:
            parts.append("Nothing publishes without your approval.")
    elif policy == "auto" and publish:
        if publishable:
            parts.append(f"It publishes automatically to {automation_chat._join([p['platform'] for p in publishable])} {publish['when'][0].lower() + publish['when'][1:] if publish['when'].startswith(('Every', 'On')) else publish['when']}; anything that fails a safety check waits for your approval instead.")
    elif policy == "drafts":
        parts.append("The drafts wait for you; nothing is published.")
    for item in blocked:
        if policy in ("review", "auto"):
            parts.append(item["reason"])
    if research and "skipped" in research["text"]:
        parts.append("If nothing is genuinely worth posting, that run is skipped.")
    text = ("Done. " if view["status"] == "active" else "I've set this up. ") + " ".join(parts)
    if view["status"] != "active":
        text += " It's waiting for you before it runs; the card below says what's left."
    return text

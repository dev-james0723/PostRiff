"""The structured workflow an automation runs (Raffi orchestration).

An automation is a campaign brief plus a recurring task (campaigns.py). Its `workflow` says what happens at
each anchor of the task's schedule, as separate stages:

    generate  when research and drafting run         {"at": "anchor"} | {"minutesOffset": -60} |
                                                       {"dayOffset": -1, "localTime": "09:00"} | {"asap": true}
    review    when the drafts should be ready for     {"at": "generate"} | {"weekday": "Thursday", "localTime": "09:00"} |
              the person (review policy only)          {"dayOffset": 1, "localTime": "09:00"} | {"minutesOffset": 120}
    publish   when an approved or eligible draft is    {"at": "anchor"} | {"weekday": "Saturday", "localTime": "18:00"} |
              published (never for policy "drafts")    {"dayOffset": 3, "localTime": "18:00"} | {"minutesOffset": 90}

The anchor is the schedule's own instant (a weekly slot, a monthly day, a one-time date). A weekday stage is the
first such local time strictly after generation, so "every Wednesday … publish Saturday at 6 PM" stays one run with
three instants instead of collapsing into one cron entry. The publish policy is part of the definition:

    auto     drafts that pass every safety check publish at the publish time under the owner's standing authority
    review   nothing publishes until a person with approval rights approves that exact draft (silence never approves)
    drafts   drafts only; the person schedules them

Research (optional) names what to look for and where: publisher domains, supplied URLs, how recent, the bar a
candidate must clear, and whether to skip the run when nothing clears it (the default: no filler). A quote step asks
for the attribution to be verified before a quote is presented as verified.

Everything here is pure: it validates definitions and computes instants. The worker executes them.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from postriff_alpha.domain import AlphaError, clean

POLICIES = ("auto", "review", "drafts")
CONTENT_TASKS = ("post", "reflection", "quote", "summary", "update", "announcement", "promotion", "education", "thread", "recap", "tip", "story", "question")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAX_SPAN_SECONDS = 14 * 86400            # generate → publish must fit inside two weeks
MAX_LEAD_MINUTES = 14 * 24 * 60
AUTO_LEAD_MINUTES = 60                   # auto-publish: draft an hour before the slot unless told otherwise
MAX_DOMAINS = 12
MAX_URLS = 5
_HOST = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_URL = re.compile(r"^https?://[^\s<>\"']{3,490}$")


def fit(value: Any, limit: int) -> str:
    """Plain text trimmed to `limit` (clean() refuses over-long text instead of trimming)."""
    text = value if isinstance(value, str) else ""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return clean(text, limit) if text else ""


def _local_time(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _TIME.fullmatch(value.strip().zfill(5)):
        raise AlphaError(f"Choose a time of day for the {name} step, like 09:00.")
    return value.strip().zfill(5)


def normalize_when(value: Any, name: str, *, allow_asap: bool = False, allow_generate: bool = False, sign: int = 0) -> dict:
    """One stage instant relative to the anchor (or to generation for weekday and "at generate" specs).
    sign -1: the stage may only come at or before the anchor; +1: at or after; 0: either."""
    if not isinstance(value, dict) or not value:
        raise AlphaError(f"Say when the {name} step happens.")
    if value.get("at") == "anchor" and len(value) == 1:
        return {"at": "anchor"}
    if allow_generate and value.get("at") == "generate" and len(value) == 1:
        return {"at": "generate"}
    if allow_asap and value.get("asap") is True and len(value) == 1:
        return {"asap": True}
    if "weekday" in value:
        if sign < 0:
            raise AlphaError(f"The {name} step cannot be a later weekday.")
        day = value.get("weekday")
        day = day.capitalize() if isinstance(day, str) else day
        if day not in WEEKDAY_NAMES or set(value) - {"weekday", "localTime"}:
            raise AlphaError(f"Choose a weekday for the {name} step.")
        return {"weekday": day, "localTime": _local_time(value.get("localTime"), name)}
    if "dayOffset" in value:
        offset = value.get("dayOffset")
        if type(offset) is not int or not -14 <= offset <= 14 or set(value) - {"dayOffset", "localTime"}:
            raise AlphaError(f"The {name} step must be within two weeks of the schedule.")
        if (sign < 0 and offset > 0) or (sign > 0 and offset < 0):
            raise AlphaError(f"The {name} step is on the wrong side of the scheduled time.")
        return {"dayOffset": offset, "localTime": _local_time(value.get("localTime"), name)}
    if "minutesOffset" in value:
        minutes = value.get("minutesOffset")
        if type(minutes) is not int or not -MAX_LEAD_MINUTES <= minutes <= MAX_LEAD_MINUTES or set(value) != {"minutesOffset"}:
            raise AlphaError(f"The {name} step must be within two weeks of the schedule.")
        if (sign < 0 and minutes > 0) or (sign > 0 and minutes < 0):
            raise AlphaError(f"The {name} step is on the wrong side of the scheduled time.")
        return {"minutesOffset": minutes}
    raise AlphaError(f"Say when the {name} step happens.")


def normalize_research(value: Any) -> dict | None:
    if value in (None, False, {}):
        return None
    if not isinstance(value, dict):
        raise AlphaError("Research settings must be structured.")
    quote = value.get("quote")
    if quote not in (None, False, {}):
        if not isinstance(quote, dict):
            raise AlphaError("Quote settings must be structured.")
        quote = {"about": fit(quote.get("about") or "", 120) or "a notable person"}
    else:
        quote = None
    query = fit(value.get("query") or "", 300)
    about = fit(value.get("about") or "", 160)
    if not (query or about or quote):
        raise AlphaError("Say what Rafii should look for.")
    domains = []
    for item in value.get("domains") or []:
        host = item.strip().lower() if isinstance(item, str) else ""
        host = host.removeprefix("https://").removeprefix("http://").split("/")[0].removeprefix("www.")
        if not _HOST.fullmatch(host):
            raise AlphaError("Name publishers by their web address, like bbc.co.uk.")
        if host not in domains:
            domains.append(host)
    if len(domains) > MAX_DOMAINS:
        raise AlphaError(f"Choose up to {MAX_DOMAINS} publishers.")
    urls = []
    for item in value.get("urls") or []:
        if not isinstance(item, str) or not _URL.fullmatch(item.strip()):
            raise AlphaError("Supplied links must be complete web addresses.")
        if item.strip() not in urls:
            urls.append(item.strip())
    if len(urls) > MAX_URLS:
        raise AlphaError(f"Supply up to {MAX_URLS} links.")
    recency = value.get("recencyDays", 7)
    if type(recency) is not int or not 1 <= recency <= 60:
        raise AlphaError("Look back between 1 and 60 days.")
    min_score = value.get("minScore", 0.55)
    if type(min_score) not in (int, float) or not 0.3 <= float(min_score) <= 0.9:
        raise AlphaError("Choose a quality bar between 0.3 and 0.9.")
    on_nothing = value.get("onNothing", "skip")
    if on_nothing not in ("skip", "draft_without"):
        raise AlphaError("Choose whether to skip a run when nothing is worth posting.")
    return {"query": query, "about": about, "domains": domains, "publications": fit(value.get("publications") or "", 200),
            "urls": urls, "recencyDays": recency, "minScore": round(float(min_score), 2), "onNothing": on_nothing, "quote": quote}


def normalize_content(value: Any) -> dict:
    value = value if isinstance(value, dict) else {}
    task = value.get("task") or "post"
    if task not in CONTENT_TASKS:
        task = "post"
    return {"task": task, "instructions": fit(value.get("instructions") or "", 600)}


def normalize_platform_notes(value: Any, platforms) -> dict:
    notes = {}
    for platform, note in (value or {}).items() if isinstance(value, dict) else ():
        if platform in platforms and isinstance(note, str) and note.strip():
            notes[platform] = fit(note, 200)
    return notes


def normalize_workflow(value: Any, schedule: dict, platforms=()) -> dict | None:
    """The authorized workflow of a v3 automation, or None for a drafts-only automation built in the Automations
    builder (generation at each anchor, nothing published). `policy` may be None only while the person has not yet
    chosen how posts are published: such an automation is saved but cannot be activated (campaigns.activate)."""
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise AlphaError("The workflow must be structured.")
    from . import campaigns
    kind = campaigns.schedule_kind(schedule)
    if kind in campaigns.EVENT_KINDS:
        raise AlphaError("Staged publishing needs a clock schedule: weekly, monthly, a countdown or a date.")
    policy = value.get("policy")
    if policy is not None and policy not in POLICIES:
        raise AlphaError("Choose auto-publish, review first, or drafts only.")
    stages = value.get("stages") if isinstance(value.get("stages"), dict) else {}
    generate = normalize_when(stages.get("generate") or {"at": "anchor"}, "drafting", allow_asap=kind == "once", sign=-1)
    publish = stages.get("publish")
    review = stages.get("review")
    if policy == "drafts":
        publish = review = None
    else:
        publish = normalize_when(publish or {"at": "anchor"}, "publishing", sign=1)
        if policy == "review" or policy is None:
            # A review can be before the scheduled time ("the evening before") or after it; the order checks below
            # keep it between drafting and publication.
            review = normalize_when(review or {"at": "generate"}, "review", allow_generate=True, sign=0)
        else:
            review = None
    workflow = {
        "version": 1,
        "policy": policy,
        "stages": {"generate": generate, "review": review, "publish": publish},
        "research": normalize_research(value.get("research")),
        "content": normalize_content(value.get("content")),
        "platformNotes": normalize_platform_notes(value.get("platformNotes"), platforms),
    }
    _check_span(workflow, schedule)
    return workflow


def _check_span(workflow: dict, schedule: dict) -> None:
    """The stage order must hold on every kind of anchor the schedule has (each weekly slot, a year of monthly
    dates, every countdown day): generate ≤ publish, review ≤ publish, within two weeks (an hour of slack for DST)."""
    from . import campaigns
    kind = schedule.get("kind", "weekly")
    count = 1 if kind == "once" else 8 if kind == "countdown" else 48 if kind == "monthly" else max(1, len(campaigns.slots_of(schedule)))
    start = 0 if kind in ("once", "countdown") else dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
    for probe in campaigns.upcoming(schedule, start, min(count, 14)) if count <= 14 else _many(schedule, start, count):
        times = stage_times(workflow, schedule, probe["scheduledFor"], claimed_at=probe["scheduledFor"])
        generate, review, publish = times["generateAt"], times["reviewAt"], times["publishAt"]
        if publish is not None and publish < generate:
            raise AlphaError("Publishing has to come after the drafts are written.")
        if review is not None and publish is not None and review > publish:
            raise AlphaError("The review has to happen before the post is published on every scheduled date.")
        if publish is not None and publish - generate > MAX_SPAN_SECONDS + 3600:
            raise AlphaError("Publishing must happen within two weeks of drafting.")


def _many(schedule: dict, start: float, count: int) -> list[dict]:
    from . import campaigns
    items, cursor = [], start
    for _ in range(count):
        found = campaigns.next_occurrence(schedule, cursor)
        if found is None:
            break
        items.append(found)
        cursor = found["scheduledFor"] + 1
    return items


def _zone(schedule: dict):
    from . import campaigns
    return campaigns._zone(schedule)


def _at_local(date: dt.date, local_time: str, zone) -> float:
    from . import campaigns
    hour, minute = (int(part) for part in local_time.split(":"))
    local = campaigns._valid_local(dt.datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone), zone)
    return local.astimezone(dt.timezone.utc).timestamp()


def _resolve(when: dict, anchor: float, base: float, zone, claimed_at: float | None) -> float:
    """`base` is the generation instant (for weekday and "at generate" specs); `anchor` for the rest."""
    if when.get("at") == "anchor":
        return anchor
    if when.get("at") == "generate":
        return base
    if when.get("asap"):
        return min(anchor, claimed_at if claimed_at is not None else anchor)
    if "minutesOffset" in when:
        return anchor + when["minutesOffset"] * 60
    if "dayOffset" in when:
        local_anchor = dt.datetime.fromtimestamp(anchor, dt.timezone.utc).astimezone(zone)
        return _at_local(local_anchor.date() + dt.timedelta(days=when["dayOffset"]), when["localTime"], zone)
    if "weekday" in when:
        from . import campaigns
        found = campaigns.next_occurrence({"weekdays": [when["weekday"]], "localTime": when["localTime"], "timeZone": zone.key}, base)
        return found["scheduledFor"]
    raise AlphaError("Unknown stage time.", 500)


def stage_times(workflow: dict | None, schedule: dict, anchor: float, claimed_at: float | None = None) -> dict:
    """{generateAt, reviewAt, publishAt, local:{…}} for one anchor. Without a workflow: generate at the anchor only."""
    zone = _zone(schedule)
    stages = (workflow or {}).get("stages") or {}
    generate = _resolve(stages.get("generate") or {"at": "anchor"}, anchor, anchor, zone, claimed_at)
    publish = _resolve(stages["publish"], anchor, generate, zone, claimed_at) if stages.get("publish") else None
    review = _resolve(stages["review"], anchor, generate, zone, claimed_at) if stages.get("review") else None

    def local(at):
        return None if at is None else dt.datetime.fromtimestamp(at, dt.timezone.utc).astimezone(zone).isoformat()
    return {"generateAt": generate, "reviewAt": review, "publishAt": publish,
            "local": {"generate": local(generate), "review": local(review), "publish": local(publish)}}


def generation_lead(workflow: dict | None) -> int:
    """How many seconds before its anchor a run can start (negative generate offsets)."""
    generate = ((workflow or {}).get("stages") or {}).get("generate") or {}
    if "minutesOffset" in generate:
        return max(0, -generate["minutesOffset"] * 60)
    if "dayOffset" in generate:
        return max(0, -generate["dayOffset"]) * 86400 + 86400
    return 0


def next_run(task: dict, after: float) -> dict | None:
    """The next generation instant of a clock-scheduled task: {scheduledFor, anchorAt, local, utc, offset, fold}.
    Anchors already claimed (task.lastAnchorAt) are skipped. A generation time that already passed while the
    anchor's publication is still ahead runs now instead of being skipped (late, never silently dropped)."""
    from . import campaigns
    schedule, workflow = task["schedule"], task.get("workflow")
    if campaigns.is_event(schedule):
        return None
    last = float(task.get("lastAnchorAt") or 0)
    # Once an automation has run, a window missed while PostRiff was down is still drafted late if its post is ahead;
    # a new automation starts at its next drafting time.
    cursor = after - generation_lead(workflow) - 1 - (MAX_SPAN_SECONDS if last else 0)
    cursor = max(cursor, last) if last else cursor
    for _ in range(64):
        anchor = campaigns.next_occurrence(schedule, cursor)
        if anchor is None:
            return None
        cursor = anchor["scheduledFor"] + 1
        if anchor["scheduledFor"] <= last:
            continue
        times = stage_times(workflow, schedule, anchor["scheduledFor"], claimed_at=after)
        latest_useful = times["publishAt"] if times["publishAt"] is not None else anchor["scheduledFor"]
        if latest_useful <= after and times["generateAt"] <= after:
            continue  # this anchor's window has fully passed
        due = max(times["generateAt"], after) if times["generateAt"] < after else times["generateAt"]
        item = campaigns._due(due, schedule)
        item["anchorAt"] = anchor["scheduledFor"]
        return item
    return None


def describe_when(when: dict | None, schedule: dict, role: str) -> str:
    """Plain words for one stage spec ("at the scheduled time", "the day before at 09:00", "Saturday at 18:00")."""
    if not when:
        return ""
    if when.get("at") == "anchor":
        return "at the scheduled time"
    if when.get("at") == "generate":
        return "as soon as the drafts are written"
    if when.get("asap"):
        return "right away"
    if "weekday" in when:
        return f"{when['weekday']} at {when['localTime']}"
    if "dayOffset" in when:
        days = when["dayOffset"]
        if days == 0:
            return f"the same day at {when['localTime']}"
        if days == -1:
            return f"the day before at {when['localTime']}"
        if days == 1:
            return f"the day after at {when['localTime']}"
        return f"{abs(days)} days {'before' if days < 0 else 'after'} at {when['localTime']}"
    minutes = when.get("minutesOffset", 0)
    span = f"{abs(minutes) // 60} hour{'s' if abs(minutes) // 60 != 1 else ''}" if abs(minutes) % 60 == 0 and abs(minutes) >= 60 else f"{abs(minutes)} minutes"
    return f"{span} {'before' if minutes < 0 else 'after'}"


SKILL_LABELS = {
    "schedule_trigger": "Schedule", "read_url": "Read the supplied link", "research": "Research", "source_validation": "Check the source",
    "relevance": "Pick what's worth posting", "quote_verification": "Verify the quote", "brand_brain": "Brand Brain", "voice": "Write like you",
    "write": "Write", "platform_adaptation": "Adapt for each platform", "quality_check": "Quality check", "approval_gate": "Your approval",
    "auto_publish_check": "Safety check before auto-publishing", "schedule": "Schedule", "publish": "Publish", "notify": "Notify you",
}


def compose(task: dict) -> list[dict]:
    """The skills a run of this automation uses, in order, composed from its definition (never a fixed template):
    research steps only when it researches, quote verification only for a quote, the voice only when personalized,
    platform adaptation when it writes for several platforms or was told how they differ, and an approval gate or
    an auto-publish safety check by policy."""
    workflow = task.get("workflow") or {}
    research = workflow.get("research") or None
    platforms = list(dict.fromkeys(d.get("platform") for d in task.get("destinations") or []))
    content = (workflow.get("content") or {}).get("task") or "post"
    policy = workflow.get("policy")
    steps = [("schedule_trigger", "Starts at the scheduled time")]
    if research:
        where = ", ".join(research.get("domains") or []) or research.get("publications") or "the web"
        if research.get("urls"):
            steps.append(("read_url", "Reads the link you supplied"))
        topic = research.get("about") or research.get("query") or "the topic"
        steps.append(("research", f"Looks for {'a quote about ' + research['quote']['about'] if research.get('quote') else topic} in {where}"))
        steps.append(("source_validation", f"Keeps only {where} from the last {research.get('recencyDays', 7)} days"))
        steps.append(("relevance", "Skips the run if nothing is genuinely worth posting" if research.get("onNothing", "skip") == "skip" else "Writes without a source if nothing is worth using"))
        if research.get("quote"):
            steps.append(("quote_verification", "Confirms the attribution on two independent sites"))
    steps.append(("brand_brain", "Uses your Brand Brain"))
    if task.get("voiceMode") == "personalized":
        steps.append(("voice", "Writes in your voice"))
    steps.append(("write", f"Writes the {content}"))
    if len(platforms) > 1 or workflow.get("platformNotes"):
        steps.append(("platform_adaptation", "Makes a version for each of " + ", ".join(platforms)))
    steps.append(("quality_check", "Checks length, sources and facts"))
    if policy == "review":
        steps.append(("approval_gate", "Waits for your approval; nothing publishes without it"))
    elif policy == "auto":
        steps.append(("auto_publish_check", "Holds any post that fails a safety check for your approval"))
    if policy in ("review", "auto"):
        steps.append(("schedule", "Schedules approved posts"))
        steps.append(("publish", "Publishes where an account is connected"))
    steps.append(("notify", "Tells you when something needs you"))
    return [{"skill": skill, "label": SKILL_LABELS[skill], "detail": detail} for skill, detail in steps]

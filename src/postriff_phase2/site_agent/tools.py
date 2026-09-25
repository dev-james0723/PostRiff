"""The site agent's typed tools: read, client and proposal (site agent §9).

Each tool has an id, a version, an effect class, a cost class, bounds, an input schema and a release id (the sha256
of its definition), like the product tool registry in `postriff_phase2/tools.py`. Publishing, replying, connecting,
buying, deleting and reading secrets are not tools: those effects stay on their own pages behind their own
approvals, and nothing here can reach them.

Tools run inside the turn's single workspace transaction (one row lock per turn) on the member's own snapshot. They
return redacted, stable views: states, counts, times, reasons, labels. Never a token, a secret, another workspace's
data or a raw database row. An unknown tool id or malformed input fails closed and is recorded as blocked.
"""
from __future__ import annotations

import re
import time

from postriff_alpha.domain import AlphaError

from .. import automation_edit, automation_explain, automation_plan, capabilities, memory, research
from ..channels import assisted_matrix, customer_view, unsupported_matrix
from ..contracts import digest
from . import contracts, knowledge, routes

EFFECTS = ("read", "client_action", "workspace_mutation")
FORBIDDEN_EFFECTS = ("external_representation", "destructive", "paid_generation", "secret")
BOUNDS = {"maxSeconds": 5, "maxInputBytes": 8000, "maxOutputBytes": 30000, "network": "internal-only", "files": "none"}
MAX_TOOLS_PER_TURN = 6
_ID = r"^[A-Za-z0-9_.:-]{1,120}$"

_DEFINITIONS = (
    ("help.search", "read", "Search Rafii's versioned help for passages that answer a question.",
     {"query": {"type": "string", "maxLength": 400}, "routeFamily": {"type": "string", "maxLength": 40}, "documents": {"type": "array"}}, ("query",)),
    ("help.get", "read", "Read one help article by id.", {"documentId": {"type": "string", "pattern": _ID}}, ("documentId",)),
    ("route.describe", "read", "What a Rafii page is for, and whether this member may open it.", {"routeId": {"type": "string", "pattern": _ID}}, ("routeId",)),
    ("workspace.summary", "read", "Role, permissions and live counts for this workspace.", {}, ()),
    ("channels.capabilities", "read", "Connected accounts, their verified capability levels and whether a post can publish there.",
     {"platform": {"type": "string", "maxLength": 40}, "connectionId": {"type": "string", "pattern": _ID}}, ()),
    ("queue.summary", "read", "Reviews waiting for approval, upcoming jobs and jobs that need attention.", {}, ()),
    ("job.get", "read", "One publishing job: state, timeline and next safe step.", {"jobId": {"type": "string", "pattern": _ID}}, ("jobId",)),
    ("draft.get", "read", "One draft: platform, account, language, state, unknowns and warnings.", {"draftId": {"type": "string", "pattern": _ID}}, ("draftId",)),
    ("automation.list", "read", "The workspace's automations with status and next run.", {}, ()),
    ("automation.get", "read", "One automation: plan, policy, platforms and latest runs.", {"automationId": {"type": "string", "pattern": _ID}}, ("automationId",)),
    ("automation.explain", "read", "Why an automation's post was (not) published, from its stored run history.",
     {"question": {"type": "string", "maxLength": 400}, "automationId": {"type": "string", "pattern": _ID}}, ("question",)),
    ("memory.summary", "read", "The Brand Brain files, learned preferences waiting for a decision, and the cloud memory setting.", {}, ()),
    ("privacy.egress_state", "read", "What may leave Rafii: cloud memory, web research and the chosen writer's class.", {}, ()),
    ("entitlements.summary", "read", "Plan, allowances left and whether publishing is included.", {}, ()),
    ("models.summary", "read", "Which writers are available here and why others are not.", {}, ()),
    ("ui.navigate", "client_action", "Open an allowlisted Rafii page.",
     {"routeId": {"type": "string", "pattern": _ID}, "params": {"type": "object"}, "query": {"type": "object"}}, ("routeId",)),
    ("ui.show_help", "client_action", "Open a help article.", {"documentId": {"type": "string", "pattern": _ID}, "anchor": {"type": "string", "maxLength": 80}}, ("documentId",)),
    ("automation.patch_propose", "workspace_mutation", "Propose a change to an automation; nothing changes until a person applies it.",
     {"automationId": {"type": "string", "pattern": _ID}, "changes": {"type": "array"}}, ("automationId", "changes")),
    ("brand.summary", "read", "The Brand Brain as stored: identity, audience, voice, boundaries and learned preferences.", {}, ()),
    ("voice.profile", "read", "The approved voice profile and the preferences learned per platform.", {"platform": {"type": "string", "maxLength": 40}}, ()),
    ("content.search", "read", "Find drafts, sources, campaigns, automations and posts by words or a quoted phrase.",
     {"query": {"type": "string", "maxLength": 400}, "kinds": {"type": "array"}, "platform": {"type": "string", "maxLength": 40},
      "since": {"type": "number"}, "until": {"type": "number"}, "label": {"type": "string", "maxLength": 60}}, ("query",)),
    ("calendar.range", "read", "What is scheduled, waiting or planned in a date range, with empty days and posts close together.",
     {"start": {"type": "number"}, "end": {"type": "number"}, "label": {"type": "string", "maxLength": 60}, "platform": {"type": "string", "maxLength": 40}}, ()),
    ("campaign.list", "read", "Campaign briefs, optionally matching words.", {"query": {"type": "string", "maxLength": 400}}, ()),
    ("campaign.get", "read", "One campaign: goal, audience, automations, drafts, posts, last week's runs and derived gaps.", {"campaignId": {"type": "string", "pattern": _ID}}, ("campaignId",)),
    ("reviews.list", "read", "What waits for approval or review, what was returned and why, and reviewer notes.", {}, ()),
    ("publishing.summary", "read", "What published (verified), what is scheduled, in flight, failed, uncertain or held.",
     {"start": {"type": "number"}, "end": {"type": "number"}, "label": {"type": "string", "maxLength": 60}}, ()),
    ("attention.summary", "read", "What needs attention: stored facts and derived observations, each traceable.", {}, ()),
    ("entity.status", "read", "The status of the item selected on the page and what it still needs.",
     {"type": {"type": "string", "maxLength": 40}, "id": {"type": "string", "pattern": _ID}}, ("type", "id")),
    ("voice.check", "read", "Compare a draft or a sentence with the stored voice profile and learned preferences: measured, heuristic or needs a writer.",
     {"draftId": {"type": "string", "pattern": _ID}, "text": {"type": "string", "maxLength": 3000}, "platform": {"type": "string", "maxLength": 40}}, ()),
    ("member.activity", "read", "What a member (or everyone) did, from records that name the person; says what is not attributed.",
     {"member": {"type": "string", "maxLength": 60}, "since": {"type": "number"}, "until": {"type": "number"}, "label": {"type": "string", "maxLength": 60},
      "only": {"type": "string", "maxLength": 20}}, ()),
    ("record.attribution", "read", "Who acted on one post, draft or automation, from its stored records.",
     {"type": {"type": "string", "maxLength": 40}, "id": {"type": "string", "pattern": _ID}}, ("type", "id")),
    ("campaign.membership", "read", "The campaigns a draft or post belongs to: linked by a person, or made by the campaign's automation.",
     {"type": {"type": "string", "maxLength": 40}, "id": {"type": "string", "pattern": _ID}}, ("type", "id")),
)
REQUIREMENT = {"automation.patch_propose": "edit"}


def _definition(tool_id, effect, purpose, properties, required):
    body = {"id": tool_id, "version": "1.0.0", "effect": effect, "cost": "none", "purpose": purpose,
            "input": {"type": "object", "required": list(required), "properties": properties, "additionalProperties": False}, "bounds": BOUNDS}
    return {**body, "releaseId": digest(body), "state": "released"}


CATALOG = {item[0]: _definition(*item) for item in _DEFINITIONS}
assert not any(tool["effect"] in FORBIDDEN_EFFECTS for tool in CATALOG.values())
RELEASE = digest(sorted(tool["releaseId"] for tool in CATALOG.values()))


def catalogue() -> list[dict]:
    return [{k: tool[k] for k in ("id", "version", "effect", "cost", "purpose", "releaseId")} for tool in CATALOG.values()]


def validate(tool_id: str, args) -> dict:
    """The tool definition when `args` fit its schema exactly; AlphaError otherwise (fail closed)."""
    tool = CATALOG.get(tool_id)
    if tool is None:
        raise AlphaError("Unknown tool.", 400, code="tool_unknown")
    if not isinstance(args, dict):
        raise AlphaError("Tool input must be an object.", 400, code="tool_input")
    schema = tool["input"]
    extra = set(args) - set(schema["properties"])
    if extra:
        raise AlphaError("Unexpected tool input.", 400, code="tool_input")
    for key in schema["required"]:
        if key not in args:
            raise AlphaError("Missing tool input.", 400, code="tool_input")
    for key, value in args.items():
        spec = schema["properties"][key]
        kind = spec["type"]
        if kind == "string":
            if not isinstance(value, str) or len(value) > spec.get("maxLength", 120) or ("pattern" in spec and not re.match(spec["pattern"], value)):
                raise AlphaError("Invalid tool input.", 400, code="tool_input")
        elif kind == "object" and not isinstance(value, dict):
            raise AlphaError("Invalid tool input.", 400, code="tool_input")
        elif kind == "array" and not isinstance(value, list):
            raise AlphaError("Invalid tool input.", 400, code="tool_input")
        elif kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 10**11):
            raise AlphaError("Invalid tool input.", 400, code="tool_input")
    return tool


class Context:
    """What a tool may see: this member's snapshot of this workspace, read inside the turn's transaction."""

    def __init__(self, *, state, membership, principal, workspace_id, cur=None, service=None, now=None, page=None, model_id=None, zone="UTC"):
        self.state, self.membership, self.principal, self.workspace_id = state, membership, principal, workspace_id
        self.cur, self.service, self.now, self.page, self.model_id = cur, service, now if now is not None else time.time(), page or {}, model_id
        self.zone = zone or "UTC"

    @property
    def providers(self):
        oauth = getattr(self.service, "oauth", None)
        return getattr(oauth, "providers", None) or {}

    @property
    def live(self):
        return bool(getattr(self.service, "publishing_live", False))


def run(tool_id: str, args: dict, ctx: Context) -> tuple[dict, dict]:
    """(record, result). A blocked or failed tool still returns a record, so the answer can say what it could not read."""
    started = time.monotonic()
    record = {"id": tool_id, "version": "1.0.0", "effect": None, "status": "blocked", "latencyMs": 0, "label": LABELS.get(tool_id, tool_id)}
    try:
        tool = validate(tool_id, args)
        record["effect"] = tool["effect"]
        requirement = REQUIREMENT.get(tool_id, "read")
        if not ctx.membership.allows(requirement):
            raise AlphaError("Your role can't do this.", 403, code="tool_forbidden")
        result = EXECUTORS[tool_id](ctx, **args)
        record["status"] = "verified" if result["verified"] else ("unverified" if result["ok"] else "failed")
    except AlphaError as error:
        record["status"] = "blocked" if error.code in ("tool_unknown", "tool_input", "tool_forbidden") else "failed"
        record["code"] = error.code or ("not_found" if error.status == 404 else "failed")
        result = contracts.result(None, now=ctx.now, ok=False, verified=False, warnings=[str(error)])
    record["latencyMs"] = round((time.monotonic() - started) * 1000, 1)
    return record, result


LABELS = {
    "help.search": "Searched Rafii help", "help.get": "Read a help article", "route.describe": "Checked this page",
    "workspace.summary": "Read your workspace summary", "channels.capabilities": "Checked your connected accounts",
    "queue.summary": "Checked the queue", "job.get": "Read the post's publishing record", "draft.get": "Read the draft",
    "automation.list": "Listed your automations", "automation.get": "Read the automation", "automation.explain": "Read the automation's run history",
    "memory.summary": "Read what Rafii remembers", "privacy.egress_state": "Checked what may leave Rafii",
    "entitlements.summary": "Checked your plan and allowances", "models.summary": "Checked the available writers",
    "ui.navigate": "Prepared a link", "ui.show_help": "Prepared a help link", "automation.patch_propose": "Prepared a proposed change",
    "brand.summary": "Read your Brand Brain", "voice.profile": "Read your voice profile", "content.search": "Searched your workspace",
    "calendar.range": "Read the calendar", "campaign.list": "Listed your campaigns", "campaign.get": "Read the campaign", "reviews.list": "Checked reviews and returns",
    "publishing.summary": "Checked publishing results", "attention.summary": "Checked what needs attention", "entity.status": "Read the selected item",
    "voice.check": "Compared the text with your voice", "member.activity": "Read who did what", "record.attribution": "Read who acted on this",
    "campaign.membership": "Checked which campaigns it belongs to",
}

# --- redaction ---------------------------------------------------------------------------------------------------------
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact(value, limit: int = 300):
    """Provider and worker messages may carry anything: strip credential-looking strings and email addresses."""
    if not isinstance(value, str):
        return None
    text = value
    for pattern in knowledge.SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = _EMAIL.sub("[email]", text)
    return " ".join(text.split())[:limit]


# --- plain-language states ------------------------------------------------------------------------------------------------
JOB_STATES = {
    "approved": ("Approved and waiting for its time", "The post is approved and waits for the worker at its publish time.", ["It can still be cancelled from the Queue before the provider has it."]),
    "scheduled": ("Approved and waiting for its time", "The post is approved and waits for the worker at its publish time.", ["It can still be cancelled from the Queue before the provider has it."]),
    "claimed": ("Being picked up", "The worker has picked the post up and is about to hand it to the provider.", []),
    "submitting": ("With the provider", "Rafii handed the post to the provider and is waiting for confirmation.", ["A cancel can no longer recall it; wait for the result."]),
    "processing": ("With the provider", "The provider is processing the post.", ["A cancel can no longer recall it; wait for the result."]),
    "provider_accepted": ("With the provider", "The provider accepted the post; Rafii is waiting for it to be confirmed.", []),
    "published": ("Published, confirming", "The provider says the post is published; Rafii is confirming it.", []),
    "verified": ("Published and verified", "The provider confirmed the post is live.", ["Open the job for the provider's reference."]),
    "uncertain": ("Uncertain", "The provider did not confirm what happened. Rafii reconciles before any retry, so nothing is posted twice.",
                  ["Don't post it again by hand yet.", "Check the account on the platform itself.", "If it stays uncertain, contact support with this job."]),
    "held": ("Held", "Something changed after approval, so nothing publishes from this job.",
             ["Read the last event for the reason.", "Fix the cause, prepare the draft again for a new review, then cancel this held job."]),
    "failed": ("Failed", "The job stopped without publishing.", ["Read the reason in its timeline.", "Prepare the draft again if you still want it to go out."]),
    "canceled": ("Cancelled", "The job was cancelled before publishing.", []),
}
WAITING = ("approved", "scheduled", "claimed")
IN_FLIGHT = ("submitting", "processing", "provider_accepted", "published")
ATTENTION = ("held", "failed", "uncertain")


def _phase2(ctx):
    return ctx.state.get("phase2") or {}


def _local(timing):
    return (timing or {}).get("local")


def _channels(ctx):
    return [c for c in _phase2(ctx).get("channels", []) if isinstance(c, dict)]


def _account(ctx, channel_id):
    channel = next((c for c in _channels(ctx) if c.get("id") == channel_id), None)
    return channel.get("account") if channel else None


def _review_expired(review, now):
    expires = (review.get("manifest") or {}).get("expiresAt")
    return isinstance(expires, (int, float)) and expires <= now


def _job_view(ctx, job, *, timeline=False):
    manifest = job.get("manifest") or {}
    title, meaning, steps = JOB_STATES.get(job.get("state"), (str(job.get("state") or "unknown").replace("_", " "), "Rafii does not recognise this state yet; it is shown as it is.", []))
    view = {"jobId": job.get("id"), "state": job.get("state"), "title": title, "meaning": meaning, "steps": steps,
            "platform": manifest.get("platform"), "account": manifest.get("account"), "publishAt": _local(manifest.get("timing")),
            "timeZone": (manifest.get("timing") or {}).get("timeZone"), "attempts": len(job.get("attempts") or []),
            "demo": manifest.get("execution") == "synthetic", "fromAutomation": bool(job.get("automation")),
            "verified": job.get("state") == "verified", "providerReference": bool(job.get("providerReference")),
            "lastEvent": None}
    events = [e for e in job.get("events") or [] if isinstance(e, dict)]
    if events:
        last = events[-1]
        view["lastEvent"] = {"state": last.get("state"), "message": redact(last.get("message")), "at": contracts.iso(last["at"]) if isinstance(last.get("at"), (int, float)) else None}
    if timeline:
        view["timeline"] = [{"state": e.get("state"), "message": redact(e.get("message"), 200), "at": contracts.iso(e["at"]) if isinstance(e.get("at"), (int, float)) else None} for e in events[-8:]]
        view["excerpt"] = redact(((manifest.get("payload") or {}).get("text") or ""), 160)
    return view


# --- executors ---------------------------------------------------------------------------------------------------------
def help_search(ctx, query, routeFamily=None, documents=None):
    preferred = tuple(d for d in (documents or [])[:6] if isinstance(d, str) and len(d) <= 80)
    found = knowledge.search(query, route_family=routeFamily or ctx.page.get("routeFamily"), k=5, documents=preferred)
    passages = [{**p, "ref": f"H{i + 1}"} for i, p in enumerate(found["passages"])]
    return contracts.result({"snapshot": found["snapshot"], "retrieval": found["retrieval"], "sufficient": found["sufficient"], "passages": passages},
                            now=ctx.now, verified=found["sufficient"], warnings=[] if found["sufficient"] else ["Rafii's help has no clear answer for this."])


def help_get(ctx, documentId):
    doc = knowledge.get(documentId)
    if doc is None:
        raise AlphaError("Help article unavailable.", 404, code="not_found")
    return contracts.result(doc, now=ctx.now)


def _can_open(ctx, route):
    access = route.get("access") or {}
    if access.get("permission") and not ctx.membership.allows(access["permission"]):
        return False, f"Your role can't open {route['title']}."
    if access.get("role") == "admin" and ctx.membership.role not in ("owner", "admin"):
        return False, f"Only an owner or admin can open {route['title']}."
    return True, None


# Pages that exist in every build but show their content only when a coworker feature is on.
_ROUTE_FLAGS = {"weekly": "RAFII_WEEKLY_OPERATOR_ENABLED", "personalization": "RAFII_ADAPTIVE_SKILLS_ENABLED"}


def route_describe(ctx, routeId):
    route = routes.by_id(routeId)
    if route is None:
        raise AlphaError("Unknown page.", 404, code="not_found")
    flag = _ROUTE_FLAGS.get(routeId)
    if flag:
        from ..coworker import flags as coworker_flags
        if not coworker_flags.enabled(flag):
            off = f"{route['title']} isn't turned on yet."
            return contracts.result({**routes.describe(routeId), "summary": off, "canOpen": False, "reason": off}, now=ctx.now)
    allowed, reason = _can_open(ctx, route)
    return contracts.result({**routes.describe(routeId), "canOpen": allowed, "reason": reason}, now=ctx.now)


def workspace_summary(ctx):
    p2 = _phase2(ctx)
    jobs = [j for j in p2.get("jobs", []) if isinstance(j, dict)]
    reviews = [r for r in p2.get("reviews", []) if isinstance(r, dict)]
    variants = [v for v in ctx.state.get("variants", []) if isinstance(v, dict) and not v.get("rejected")]
    scheduled_variants = {(j.get("manifest") or {}).get("variantId") for j in jobs if j.get("state") not in ("failed", "canceled")}
    tasks = automation_edit.live_tasks(ctx.state)
    channels = _channels(ctx)
    counts = {
        "draftsUnscheduled": sum(1 for v in variants if v.get("id") not in scheduled_variants),
        "draftsNeedingReview": sum(1 for v in variants if v.get("needsReview") or v.get("unknowns")),
        "reviewsWaiting": sum(1 for r in reviews if r.get("status") == "needs_review" and not _review_expired(r, ctx.now)),
        "reviewsExpired": sum(1 for r in reviews if r.get("status") == "needs_review" and _review_expired(r, ctx.now)),
        "jobsWaiting": sum(1 for j in jobs if j.get("state") in WAITING), "jobsInFlight": sum(1 for j in jobs if j.get("state") in IN_FLIGHT),
        "jobsHeld": sum(1 for j in jobs if j.get("state") == "held"), "jobsFailed": sum(1 for j in jobs if j.get("state") == "failed"),
        "jobsUncertain": sum(1 for j in jobs if j.get("state") == "uncertain"), "jobsVerified": sum(1 for j in jobs if j.get("state") == "verified"),
        "accountsConnected": sum(1 for c in channels if c.get("configured") and not c.get("revoked")),
        "automationsActive": sum(1 for t in tasks if t.get("status") == "active"), "automationsPaused": sum(1 for t in tasks if t.get("status") == "paused"),
        "automationsDraft": sum(1 for t in tasks if t.get("status") == "draft"),
    }
    workspace = ctx.state.get("workspace") or {}
    data = {"workspace": {"name": workspace.get("name"), "role": ctx.membership.role}, "permissions": ctx.membership.summary(), "counts": counts}
    return contracts.result(data, now=ctx.now)


def _matrices(ctx):
    if ctx.cur is None:
        return {}
    ctx.cur.execute("SELECT connection_id,capability,level,evidence,capability_version,extract(epoch from verified_at) FROM public.pr_channel_capabilities WHERE workspace_id=%s", (ctx.workspace_id,))
    matrices = {}
    for connection_id, capability, level, evidence, version, verified in ctx.cur.fetchall():
        matrices.setdefault(connection_id, unsupported_matrix())[capability] = {"level": level, "evidence": evidence, "capabilityVersion": version, "verifiedAt": float(verified) if verified else None}
    return matrices


def _can_publish(ctx):
    billing = getattr(ctx.service, "billing", None)
    if ctx.cur is None or billing is None:
        return None
    try:
        ctx.cur.execute("SAVEPOINT site_agent_lifecycle")
        answer = billing.lifecycle(ctx.cur, ctx.workspace_id, ctx.now).get("canPublish")
        # A read never changes subscription rows: the lifecycle helper may normalise a status; keep that out of a question.
        ctx.cur.execute("ROLLBACK TO SAVEPOINT site_agent_lifecycle")
        return answer
    except Exception:  # noqa: BLE001 — capability explanations stay available without billing
        ctx.cur.execute("ROLLBACK TO SAVEPOINT site_agent_lifecycle")
        return None


def channels_capabilities(ctx, platform=None, connectionId=None):
    matrices = _matrices(ctx)
    can_publish = _can_publish(ctx)
    engine = getattr(getattr(ctx.service, "commands", None), "engine", None)
    rows = []
    for channel in _channels(ctx):
        if connectionId and channel.get("id") != connectionId:
            continue
        if platform and channel.get("platform", "").lower() != platform.lower():
            continue
        view = customer_view(channel, matrices.get(channel["id"], assisted_matrix()), ctx.now)
        route = capabilities.publish_route(ctx.state, {"platform": channel["platform"], "channelId": channel["id"]}, providers=ctx.providers, live=ctx.live, can_publish=can_publish)
        try:
            state = engine.channel_state(channel) if engine is not None else None
        except (KeyError, TypeError):
            state = None
        rows.append({"connectionId": channel["id"], "platform": channel["platform"], "account": channel.get("account"), "connectionState": view["connectionState"],
                     "readiness": state, "demo": channel.get("evidenceSource", "synthetic") == "synthetic", "revoked": bool(channel.get("revoked")),
                     "levels": {name: (value or {}).get("level") for name, value in view["capabilities"].items() if name in ("identity", "publish", "schedule", "analytics", "comments_read", "reply")},
                     "canPublish": route["publish"], "publishCode": route["code"], "publishReason": route["reason"]})
    if connectionId and not rows:
        raise AlphaError("That account is not connected to this workspace.", 404, code="not_found")
    unconnected = None
    if platform and not rows:
        route = capabilities.publish_route(ctx.state, {"platform": _canonical_platform(platform)}, providers=ctx.providers, live=ctx.live, can_publish=can_publish)
        unconnected = {"platform": _canonical_platform(platform), "canPublish": route["publish"], "publishCode": route["code"], "publishReason": route["reason"]}
    return contracts.result({"accounts": rows, "unconnected": unconnected, "publishingLive": ctx.live}, now=ctx.now)


def _canonical_platform(value):
    for name in ("LinkedIn", "Instagram", "Threads", "X", "Xiaohongshu", "Facebook", "TikTok", "YouTube", "Bluesky", "Pinterest"):
        if value.lower() in (name.lower(), "twitter" if name == "X" else name.lower()):
            return name
    return value


def queue_summary(ctx):
    p2 = _phase2(ctx)
    reviews = [r for r in p2.get("reviews", []) if isinstance(r, dict) and r.get("status") == "needs_review"]
    jobs = [j for j in p2.get("jobs", []) if isinstance(j, dict)]
    waiting = [{"reviewId": r.get("id"), "platform": (r.get("manifest") or {}).get("platform"), "account": (r.get("manifest") or {}).get("account"),
                "publishAt": _local((r.get("manifest") or {}).get("timing")), "expired": _review_expired(r, ctx.now)} for r in reviews][:6]
    upcoming = sorted((j for j in jobs if j.get("state") in WAITING), key=lambda j: ((j.get("manifest") or {}).get("timing") or {}).get("timestamp") or 0)[:5]
    attention = sorted((j for j in jobs if j.get("state") in ATTENTION), key=lambda j: -(j.get("events") or [{}])[-1].get("at", 0) if j.get("events") else 0)[:5]
    recent = sorted((j for j in jobs if j.get("state") in ("verified",) + IN_FLIGHT), key=lambda j: -(j.get("approvedAt") or 0))[:3]
    drafts = [v for v in ctx.state.get("variants", []) if isinstance(v, dict) and not v.get("rejected")]
    scheduled = {(j.get("manifest") or {}).get("variantId") for j in jobs if j.get("state") not in ("failed", "canceled")}
    data = {"waitingApproval": waiting, "upcoming": [_job_view(ctx, j) for j in upcoming], "attention": [_job_view(ctx, j) for j in attention],
            "recent": [_job_view(ctx, j) for j in recent], "draftsUnscheduled": sum(1 for v in drafts if v.get("id") not in scheduled)}
    return contracts.result(data, now=ctx.now)


def job_get(ctx, jobId):
    job = next((j for j in _phase2(ctx).get("jobs", []) if isinstance(j, dict) and j.get("id") == jobId), None)
    if job is None:
        review = next((r for r in _phase2(ctx).get("reviews", []) if isinstance(r, dict) and r.get("id") == jobId), None)
        if review is None:
            raise AlphaError("That post is not in this workspace's queue.", 404, code="not_found")
        manifest = review.get("manifest") or {}
        expired = _review_expired(review, ctx.now)
        status = "expired" if review.get("status") == "needs_review" and expired else review.get("status")
        meaning = {"needs_review": "It is waiting for someone with the approve permission. Nothing publishes until that exact post is approved.",
                   "expired": "Its publish time passed before anyone approved it, so the review window closed.",
                   "stale": "Something changed after it was prepared (the draft, its sources, the voice or the account), so it went out of date.",
                   "approved": "It was approved and became a publishing job."}.get(status, "")
        steps = {"needs_review": ["Open it in the Queue and approve the exact post, or change the draft first."],
                 "expired": ["Prepare the draft again with a new time from Queue → Drafts."],
                 "stale": ["Prepare the draft again for a new review."]}.get(status, [])
        data = {"reviewId": review.get("id"), "kind": "review", "state": status, "meaning": meaning, "steps": steps, "platform": manifest.get("platform"),
                "account": manifest.get("account"), "publishAt": _local(manifest.get("timing")), "jobId": review.get("jobId")}
        return contracts.result(data, now=ctx.now)
    return contracts.result({**_job_view(ctx, job, timeline=True), "kind": "job"}, now=ctx.now)


def draft_get(ctx, draftId):
    variant = next((v for v in ctx.state.get("variants", []) if isinstance(v, dict) and v.get("id") == draftId), None)
    if variant is None:
        raise AlphaError("That draft is not in this workspace.", 404, code="not_found")
    jobs = [j for j in _phase2(ctx).get("jobs", []) if (j.get("manifest") or {}).get("variantId") == draftId and j.get("state") not in ("failed", "canceled")]
    from ..contracts import LIMITS
    limit = (LIMITS.get(variant.get("platform")) or {}).get("characters")
    text = variant.get("text") or ""
    data = {"draftId": draftId, "platform": variant.get("platform"), "language": variant.get("language"), "account": _account(ctx, variant.get("channelId")),
            "revision": variant.get("revision"), "characters": len(text), "limit": limit, "overLimit": bool(limit and len(text) > limit),
            "unknowns": [redact(u, 160) for u in variant.get("unknowns") or []][:6], "warnings": [redact(w, 200) for w in variant.get("warnings") or []][:6],
            "needsReview": bool(variant.get("needsReview")), "blockedByRetraction": bool(variant.get("blockedByRetraction")), "setAside": bool(variant.get("rejected")),
            "hasProposedUpdate": bool(variant.get("proposedUpdate")), "scheduled": [_job_view(ctx, j) for j in jobs][:3],
            "fromAutomation": bool(variant.get("automation")), "text": text[:1500]}
    return contracts.result(data, now=ctx.now)


def _task(ctx, automation_id):
    task = next((t for t in automation_edit.live_tasks(ctx.state) if t.get("id") == automation_id), None)
    if task is None:
        raise AlphaError("That automation is not in this workspace.", 404, code="not_found")
    return task


def automation_list(ctx):
    items = []
    for task in automation_edit.live_tasks(ctx.state):
        items.append({"automationId": task["id"], "name": task.get("name") or "Automation", "status": task.get("status"),
                      "schedule": automation_plan.describe(task["schedule"]) if task.get("schedule") else None,
                      "policy": (task.get("workflow") or {}).get("policy") or ("drafts" if not task.get("workflow") else None),
                      "platforms": list(dict.fromkeys(d.get("platform") for d in task.get("destinations") or [])),
                      "nextRun": ((task.get("nextOccurrence") or {}).get("scheduledFor")), "nextPublish": task.get("nextPublish")})
    return contracts.result({"automations": items[:20]}, now=ctx.now)


def automation_get(ctx, automationId):
    task = _task(ctx, automationId)
    view = automation_plan.card(ctx.state, task["id"], [], [], providers=ctx.providers, live=ctx.live)
    keep = ("taskId", "name", "status", "scheduleText", "nextOccurrence", "nextPublish", "policy", "plan", "platforms", "runs", "needs", "contentLabel", "voiceMode")
    return contracts.result({k: view.get(k) for k in keep}, now=ctx.now)


def automation_explain_tool(ctx, question, automationId=None):
    from .. import workflow_parse
    explain = workflow_parse.read_explain(question)
    answer = automation_explain.answer(ctx.state, question, explain, conversation_task_id=automationId, now=ctx.now)
    return contracts.result({"text": answer.get("text"), "lines": answer.get("lines") or [], "about": answer.get("about"),
                             "automationId": answer.get("taskId"), "runId": answer.get("occurrenceId")}, now=ctx.now, verified=bool(answer.get("taskId")))


def memory_summary(ctx):
    files = memory.render_files(ctx.state)
    pending = []
    if ctx.cur is not None:
        from ..learning_service import pending_proposals
        pending = pending_proposals(ctx.cur, ctx.workspace_id)
    data = {"files": [{"name": f.get("name"), "purpose": f.get("purpose"), "characters": len(f.get("body") or ""), "editHref": f.get("editHref")} for f in files],
            "bodies": {f.get("name"): (f.get("body") or "")[:1200] for f in files},
            "pendingPreferences": len(pending), "egress": memory.egress_summary(ctx.state)}
    return contracts.result(data, now=ctx.now)


def privacy_egress_state(ctx):
    egress = memory.egress_summary(ctx.state)
    research_state = research.consent_summary(ctx.state)
    data = {"cloudMemory": egress.get("cloud"), "withheldBoundaries": egress.get("withheldBoundaries"), "sharedFiles": egress.get("sharedFiles"),
            "webResearch": research_state.get("web"), "researchOnDeployment": research_state.get("enabled"),
            "writer": _writer_class(ctx)}
    return contracts.result(data, now=ctx.now)


def _writer_class(ctx):
    ideas = getattr(ctx.service, "ideas", None)
    if ideas is None or not ctx.model_id:
        return {"modelId": ctx.model_id, "class": "none" if not ctx.model_id else None}
    try:
        runtime = ideas._select_runtime(ctx.model_id)
    except AlphaError as error:
        return {"modelId": ctx.model_id, "class": None, "unavailable": str(error)}
    return {"modelId": ctx.model_id, "class": "none" if runtime.cost_class == "none" else getattr(runtime, "provider_class", "local"), "costClass": runtime.cost_class}


def entitlements_summary(ctx):
    ledger = getattr(ctx.service, "ledger", None)
    if ctx.cur is None or ledger is None:
        return contracts.result(None, now=ctx.now, ok=False, verified=False, warnings=["Plan details are not available here."])
    ctx.cur.execute("SAVEPOINT site_agent_usage")
    try:
        view = ledger.usage_view(ctx.cur, ctx.workspace_id)
        can_publish = ctx.service.billing.lifecycle(ctx.cur, ctx.workspace_id, ctx.now).get("canPublish") if getattr(ctx.service, "billing", None) else None
    finally:
        # Reading never changes billing rows (the usage view may create first-use rows; the owner's page does that).
        ctx.cur.execute("ROLLBACK TO SAVEPOINT site_agent_usage")
    entitlement = view.get("entitlement") or {}
    owner = ctx.membership.allows("owner")
    budget = view.get("budget") or {}
    subscription = view.get("subscription") or {}
    data = {"plan": subscription.get("label") or subscription.get("plan") or entitlement.get("planTermsId"), "subscriptionStatus": subscription.get("status"),
            "writingBatchesRemaining": entitlement.get("writingBatchesRemaining"), "mediaCreditsRemaining": entitlement.get("mediaCreditsRemaining"),
            "resetsAt": entitlement.get("resetsAt"), "canPublish": can_publish, "budgetStatus": budget.get("status"),
            "spentUsdMicro": budget.get("spentUsdMicro") if owner else None, "stopUsdMicro": budget.get("stopUsdMicro") if owner else None, "costsVisible": owner}
    return contracts.result(data, now=ctx.now)


def models_summary(ctx):
    ideas = getattr(ctx.service, "ideas", None)
    if ideas is None:
        return contracts.result(None, now=ctx.now, ok=False, verified=False, warnings=["The writer list is not available here."])
    catalog = ideas.model_catalog()
    models = [{"id": m.get("id"), "label": m.get("label"), "qualified": bool(m.get("qualified")), "costClass": m.get("costClass"), "route": m.get("route"),
               "detail": redact(m.get("detail"), 220)} for m in catalog.get("models", [])][:16]
    return contracts.result({"models": models, "selected": ctx.model_id}, now=ctx.now)


def ui_navigate(ctx, routeId, params=None, query=None):
    route = routes.by_id(routeId)
    if route is None:
        raise AlphaError("Unknown page.", 400, code="tool_input")
    href = routes.href(routeId, params=params, query=query)
    if href is None:
        raise AlphaError("That link is not allowed.", 400, code="tool_input")
    allowed, reason = _can_open(ctx, route)
    return contracts.result({"href": href, "routeId": routeId, "title": route["title"], "canOpen": allowed, "reason": reason}, now=ctx.now, source="client")


def ui_show_help(ctx, documentId, anchor=None):
    doc = knowledge.get(documentId)
    if doc is None:
        raise AlphaError("Help article unavailable.", 404, code="not_found")
    anchors = {s["anchor"] for s in doc["sections"]}
    href = f"/app/help/{documentId}" + (f"#{anchor}" if anchor in anchors else "")
    return contracts.result({"href": href, "title": doc["title"]}, now=ctx.now, source="client")


def automation_patch_propose(ctx, automationId, changes):
    # Proposals are built by proposals.build (they need the conversation); the executor only validates the target.
    task = _task(ctx, automationId)
    return contracts.result({"automationId": task["id"], "changes": changes}, now=ctx.now)


EXECUTORS = {
    "help.search": help_search, "help.get": help_get, "route.describe": route_describe, "workspace.summary": workspace_summary,
    "channels.capabilities": channels_capabilities, "queue.summary": queue_summary, "job.get": job_get, "draft.get": draft_get,
    "automation.list": automation_list, "automation.get": automation_get, "automation.explain": automation_explain_tool,
    "memory.summary": memory_summary, "privacy.egress_state": privacy_egress_state, "entitlements.summary": entitlements_summary,
    "models.summary": models_summary, "ui.navigate": ui_navigate, "ui.show_help": ui_show_help, "automation.patch_propose": automation_patch_propose,
}
from . import reads  # noqa: E402 — reads builds on the helpers above

EXECUTORS.update({
    "brand.summary": reads.brand_summary, "voice.profile": reads.voice_profile, "content.search": reads.content_search, "calendar.range": reads.calendar_range,
    "campaign.list": reads.campaign_list, "campaign.get": reads.campaign_get, "reviews.list": reads.reviews_list, "publishing.summary": reads.publishing_summary,
    "attention.summary": reads.attention_summary, "entity.status": reads.entity_status, "voice.check": reads.voice_check, "member.activity": reads.member_activity,
    "record.attribution": reads.record_attribution, "campaign.membership": reads.campaign_membership,
})
assert set(EXECUTORS) == set(CATALOG)

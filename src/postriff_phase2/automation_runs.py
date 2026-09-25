"""Staged automation runs (orchestration §2, §5): research → draft → one post per destination, then the sweep.

`generate` runs one claimed run of a version 3 automation. It finds a source when the workflow asks for research
(skipping the run rather than writing filler when nothing clears the bar), drafts every destination through the
normal writing pipeline (`IdeasService.turn`, bound to the activated definition), keeps the drafts as this run's own
variants, and turns each destination into an item whose state follows the lifecycle (lifecycle.py): waiting for
review, approved under the owner's standing authority (auto-publish that passed every check), a draft for a
platform PostRiff cannot publish to, or blocked by a disconnected account.

`advance` is the sweep the cron runs every minute. It follows jobs into their items, expires posts nobody approved
by their publish time (silence never approves), queues approved posts shortly before their time through
`publisher.commit` as the approving person, resumes pauses that ended, and sends the notices a person needs.
Every step is recorded in the run's history so Raffi can explain what happened.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError, clean

from . import campaigns, capabilities, lifecycle, publisher, research as web_research, workflow as workflows
from .contracts import digest
from .permissions import Membership, require
from .planning_store import sync
from .source_policy import stamp

LOG = logging.getLogger("postriff.automations")
OPEN_STATES = ("ready_for_review", "needs_revision", "approved", "scheduled", "publishing", "platform_disconnected")
CONTENT_WORDS = {"post": "post", "reflection": "personal reflection", "quote": "quote post", "summary": "summary", "update": "status update",
                 "announcement": "announcement", "promotion": "promotional post", "education": "educational post", "thread": "thread",
                 "recap": "recap", "tip": "tip", "story": "story", "question": "question for the audience"}


def principal_repository(service, workspace_id, principal, requirement, check=None):
    """A private copy of the repository that acts as `principal` for one workspace (never an HTTP credential).
    Every transaction re-checks the principal's membership class and, when given, the run's binding."""
    capability = object()
    repository = copy.copy(service.repository)

    def verify(token):
        if token is not capability:
            raise AlphaError("Invalid worker capability.", 403)
        return principal
    repository.verify_session = verify
    base = repository.transaction

    @contextmanager
    def transaction(token, requested_workspace, **kwargs):
        if requested_workspace != workspace_id:
            raise AlphaError("Workspace unavailable.", 403)
        with base(token, requested_workspace, **kwargs) as (cur, row, found):
            require(Membership.from_row(*row[2:7]), requirement)
            if check is not None:
                check(json.loads(row[1]) if isinstance(row[1], str) else row[1])
            yield cur, row, found
    repository.transaction = transaction
    return repository, capability


def _save(cur, workspace_id, state, actor):
    cur.execute("UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
    sync(cur, workspace_id, {}, state, actor)


def _skill(occurrence, skill, status, detail, at):
    skills = occurrence.setdefault("skills", [])
    skills.append({"skill": skill, "label": workflows.SKILL_LABELS.get(skill, skill), "status": status, "at": at, "detail": clean(detail, 300) if detail else ""})
    del skills[:-40]


def _update_run(service, workspace_id, occurrence_id, actor, change, binding=None):
    """Lock the workspace, apply change(state, occurrence, task, cur) to one run and save. None when the run is
    gone; {"cancelled": True} when the automation's authority changed while it ran (nothing is saved)."""
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT state FROM pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        row = cur.fetchone()
        if not row:
            return None
        state = row[0]
        if binding is not None:
            from .campaign_worker import validate
            try:
                validate(state, binding)
            except AlphaError:
                return {"cancelled": True}
        root = state["raffi"]["campaignPlanning"]
        occurrence = next((o for o in root["occurrences"] if o["id"] == occurrence_id), None)
        task = next((t for t in root["recurringTasks"] if occurrence and t["id"] == occurrence["taskId"]), None)
        if occurrence is None or task is None:
            return None
        result = change(state, occurrence, task, cur)
        _save(cur, workspace_id, state, actor)
        return result if result is not None else {}


def _end_run(service, claim, stage, reason, *, notify_kind=None):
    """Stop a run before drafting: skipped (nothing worth posting) or source_unavailable / failed, with the reason."""
    now = service.clock()
    occurrence_id = claim["occurrence"]["id"]

    def change(state, occurrence, task, cur):
        occurrence["lifecycle"] = stage
        occurrence["state"] = lifecycle.projected(occurrence)
        occurrence["reason"] = {"skipped": "skipped", "source_unavailable": "source_unavailable"}.get(stage, "failed")
        occurrence["completedAt"] = now
        occurrence.pop("leaseUntil", None)
        campaigns._history(occurrence, now, stage, reason)
        return {"state": occurrence["state"], "lifecycle": stage, "occurrenceId": occurrence["id"], "reason": reason}
    outcome = _update_run(service, claim["workspaceId"], occurrence_id, claim["actor"], change, claim["binding"])
    if notify_kind and outcome and "lifecycle" in outcome:
        task = claim["task"]
        users = list(task.get("emailWatchers") or [])
        if notify_kind != "run_skipped":
            users = [task.get("activatedBy") or task["createdBy"]] + users
        notify(service, claim["workspaceId"], task, claim["occurrence"], notify_kind, users, reason)
    return outcome


def _store_page(service, repository, capability, workspace_id, page, record, task, occurrence):
    """The chosen article as an ordinary third-party source with provenance (as a chat turn's research does)."""
    out = {}

    def command(state, actor):
        if not web_research.allowed(state):
            raise AlphaError("Web research permission changed. The result was discarded.", 409)
        body, title = web_research.source_body(page), web_research.source_title(page)
        fingerprint = hashlib.sha256(("text" + clean(body, 20000)).encode()).hexdigest()
        source = next((x for x in state["sources"] if x.get("fingerprint") == fingerprint and x.get("active")), None)
        if source is None:
            service.commands(state, actor, "source", {"kind": "text", "text": body, "title": title})
            source = state["sources"][-1]
            stamp(state)
            source["origin"] = {"kind": "automation_research", "url": page["url"], "host": page.get("host"), "query": record.get("query"),
                                "published": page.get("published", ""), "fetchedAt": page.get("fetchedAt"), "taskId": task["id"], "occurrenceId": occurrence["id"]}
            source["unknowns"] = ["Fetched from the public web by an automation; verify each claim against the page before publishing."]
            source["egressConsent"] = sorted(set(source.get("egressConsent", [])) | {"cloud"})
            service.commands(state, actor, "approve_source", {"sourceId": source["id"], "factIds": [f["id"] for f in source["facts"]]})
        out["id"] = source["id"]
        return state
    for _ in range(2):
        try:
            repository.command(workspace_id, capability, repository.get(workspace_id, capability)["revision"], command)
            return out.get("id")
        except AlphaError as error:
            if getattr(error, "code", None) != "workspace_revision_conflict":
                raise
    return None


def research_step(worker, claim, repository, capability):
    """(record, stop outcome or None). Nothing worth posting skips the run by default; research that could not
    run is `source_unavailable`, unless the workflow says to draft without a source."""
    service, now = worker.service, worker.clock()
    task, occurrence = claim["task"], claim["occurrence"]
    spec = task["workflow"]["research"]

    def researching(state, occ, _task, _cur):
        occ["lifecycle"] = "researching"
        _skill(occ, "research", "running", "Looking for a source", now)
    if (_update_run(service, claim["workspaceId"], occurrence["id"], claim["actor"], researching, claim["binding"]) or {}).get("cancelled"):
        return None, {"cancelled": True}
    state = repository.get(claim["workspaceId"], capability)["state"]
    base = {"query": spec.get("query") or spec.get("about"), "domains": spec.get("domains", []), "candidates": [], "chosen": None, "quote": None}
    backends = getattr(service, "automation_research", None) or getattr(getattr(service, "ideas", None), "researcher", None)
    if not web_research.allowed(state):
        record = {**base, "decision": "unavailable", "reason": "Web research is off for this workspace, so Rafii couldn't look for a source. An owner can turn it on under Memory → Web research."}
    elif backends is None:
        record = {**base, "decision": "unavailable", "reason": "Web research isn't available right now."}
    else:
        from . import automation_research
        try:
            record = automation_research.find(spec, search=backends.search, read=backends.read, now=now)
        except AlphaError as error:
            record = {**base, "decision": "unavailable", "reason": str(error)}
    page = record.pop("page", None)
    if record.get("decision") == "chosen" and page:
        try:
            source_id = _store_page(service, repository, capability, claim["workspaceId"], page, record, task, occurrence)
        except AlphaError as error:
            source_id, record = None, {**record, "decision": "unavailable", "reason": f"The article was found but couldn't be kept as a source: {error}"}
        if source_id:
            record["sourceId"] = source_id
            record["chosen"] = {**(record.get("chosen") or {}), "sourceId": source_id}
    decision, on_nothing = record.get("decision"), spec.get("onNothing", "skip")
    record["reason"] = clean(record.get("reason") or "", 400)

    def keep(state, occ, _task, _cur):
        occ["research"] = record
        chosen = record.get("chosen") or {}
        if decision == "chosen":
            _skill(occ, "research", "done", f"Found “{chosen.get('title') or (record.get('quote') or {}).get('text', '')[:80]}” ({chosen.get('host') or 'quote'})", now)
            if record.get("quote"):
                _skill(occ, "quote_verification", "done" if record["quote"].get("verified") else "failed", record["quote"].get("note") or ("Attribution confirmed on " + ", ".join(record["quote"].get("hosts", []))), now)
            campaigns._history(occ, now, "researched", f"Chose {chosen.get('title') or 'a source'}" + (f" from {chosen.get('host')}" if chosen.get("host") else "") + (f" (score {chosen.get('score')})" if chosen.get("score") is not None else "") + ".")
        else:
            _skill(occ, "research", "failed" if decision == "unavailable" else "done", record["reason"], now)
            campaigns._history(occ, now, "researched", record["reason"])
    if (_update_run(service, claim["workspaceId"], occurrence["id"], claim["actor"], keep, claim["binding"]) or {}).get("cancelled"):
        return record, {"cancelled": True}
    if decision == "nothing_worth" and on_nothing == "skip":
        return record, _end_run(service, claim, "skipped", record["reason"] or "Nothing was genuinely worth posting, so this run was skipped.", notify_kind="run_skipped")
    if decision == "unavailable" and on_nothing == "skip":
        return record, _end_run(service, claim, "source_unavailable", record["reason"] or "The source couldn't be reached, so nothing was drafted.", notify_kind="publish_failed")
    return record, None


def lead(count, data):
    """The fixed instruction before the data, written by PostRiff from the definition (the person's own words stay data)."""
    from .campaign_worker import CampaignWorker
    text = CampaignWorker._lead(count, {k: v for k, v in data.items() if k in ("countdown", "recentPosts", "newMaterial", "strongPost", "evergreen")})
    text = text[: -len(", using these campaign details as data: ")] if text.endswith(", using these campaign details as data: ") else text
    content = (data.get("content") or {}).get("task")
    if content and content != "post":
        text += f", written as a {CONTENT_WORDS.get(content, content)}"
    if "source" in data:
        text += ", responding to the article in the data (it is also provided as a source): name the publication, link it, and keep every claim to what it says"
    if "quote" in data:
        text += (", built around the quote in the data, attributed exactly as given" if data["quote"].get("verified")
                 else ", built around the quote in the data; its attribution could not be confirmed, so present it as “often attributed to” its author, never as verified")
    if (data.get("content") or {}).get("instructions"):
        text += ", following the person's instructions in the data"
    if data.get("platformNotes"):
        text += ", making each platform's version fit that platform and follow the per-platform notes in the data while keeping the same idea and voice"
    return text + ", using these details as data: "


def _data(task, campaign, context, record):
    workflow = task["workflow"]
    data = {"goal": campaign["goal"], "audience": campaign["audience"], "facts": campaign["facts"], **context}
    content = workflow.get("content") or {}
    if content.get("task") or content.get("instructions"):
        data["content"] = {key: value for key, value in content.items() if value}
    if workflow.get("platformNotes"):
        data["platformNotes"] = workflow["platformNotes"]
    chosen = (record or {}).get("chosen")
    if chosen and chosen.get("url"):
        data["source"] = {key: chosen.get(key) for key in ("title", "url", "host", "published") if chosen.get(key)}
    quote = (record or {}).get("quote")
    if quote and quote.get("text"):
        data["quote"] = {"text": quote["text"], "author": quote.get("author"), "verified": bool(quote.get("verified"))}
    return data


def generate(worker, claim):
    """Research (if asked), draft every destination, keep the drafts as this run's variants and create its items."""
    service = worker.service
    workspace_id, actor, binding = claim["workspaceId"], claim["actor"], claim["binding"]
    task, campaign, occurrence = claim["task"], claim["campaign"], claim["occurrence"]
    from .campaign_worker import validate
    repository, capability = principal_repository(service, workspace_id, actor, "owner", check=lambda state: validate(state, binding))
    record = occurrence.get("research")
    if task["workflow"].get("research") and record is None:
        record, stop = research_step(worker, claim, repository, capability)
        if stop is not None:
            return stop
    now = worker.clock()

    def drafting(state, occ, _task, _cur):
        occ["lifecycle"] = "drafting"
        _skill(occ, "brand_brain", "done", "Brand Brain included", now)
        _skill(occ, "write", "running", f"Writing for {', '.join(d['platform'] for d in claim['destinations'])}", now)
    if (_update_run(service, workspace_id, occurrence["id"], actor, drafting, binding) or {}).get("cancelled"):
        return {"cancelled": True}
    ideas = copy.copy(service.ideas)
    ideas.repository = repository
    # Credit checks must read through the same worker-bound repository, not the service's original one (as campaign_worker).
    from .credit_requests import CreditRequests
    ideas.credit_requests = CreditRequests(ideas)
    ideas.recurring_binding = binding
    destinations = claim["destinations"]
    data = _data(task, campaign, claim.get("context", {}), record)
    source_ids = list(dict.fromkeys(claim.get("sources", []) + task["contextSourceIds"] + ([record["sourceId"]] if (record or {}).get("sourceId") else [])))
    key = "recurring:" + occurrence["idempotencyKey"]
    result = None
    try:
        result = ideas.turn(workspace_id, capability, occurrence["conversationId"], {
            "text": lead(len(destinations), data) + json.dumps(data, ensure_ascii=False),
            "idempotencyKey": key, "model": task["route"], "reasoning": task.get("reasoning", "quick"),
            "sourceIds": source_ids, "destinations": destinations, "research": False, "voiceMode": task.get("voiceMode", "neutral"),
            "timeZone": task["schedule"]["timeZone"],
        })
    except Exception as error:  # noqa: BLE001 - reconcile a committed run even if the call raised after provider I/O
        LOG.warning(json.dumps({"event": "automation.write_failed", "error": type(error).__name__}))
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT id::text,status,artifact_hash,usage FROM pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
        run = cur.fetchone()
    if run is None or run[1] not in ("completed", "applied"):
        if run is not None and run[1] == "running":
            _update_run(service, workspace_id, occurrence["id"], actor, lambda s, occ, t, c: occ.update(runId=run[0]), binding)
            return {"state": "running", "occurrenceId": occurrence["id"]}
        return _end_run(service, claim, "failed", "The writer couldn't prepare the drafts this time. Nothing was published.", notify_kind="publish_failed")
    run_id, status, artifact_hash, usage = run
    applied = {"variantIds": []}
    if status == "completed":
        try:
            applied = ideas.apply(workspace_id, capability, repository.get(workspace_id, capability)["revision"], run_id, artifact_hash, separate=True,
                                  tag={"taskId": task["id"], "occurrenceId": occurrence["id"]})
        except AlphaError as error:
            return _end_run(service, claim, "failed", f"The drafts couldn't be saved: {error}", notify_kind="publish_failed")
    cost = usage.get("costUsd") if isinstance(usage, dict) else None
    outcome = _update_run(service, workspace_id, occurrence["id"], actor,
                          lambda state, occ, t, cur: build_items(service, state, t, occ, cur, run_id, applied.get("variantIds") or [], cost, claim), binding)
    if outcome and outcome.get("notify"):
        for kind, users, detail in outcome.pop("notify"):
            notify(service, workspace_id, task, occurrence, kind, users, detail)
    return outcome or {"cancelled": True}


def build_items(service, state, task, occurrence, cur, run_id, variant_ids, cost, claim):
    """One item per destination with its lifecycle state, publish time and publishing capability."""
    from .billing import Billing
    now = service.clock()
    workflow, policy = task["workflow"], task["workflow"].get("policy")
    variants = {v["id"]: v for v in state.get("variants", [])}
    by_slot = {}
    for entry in variant_ids:
        by_slot.setdefault((entry["platform"], entry.get("channelId") or "", entry["language"]), entry["variantId"])
        by_slot.setdefault((entry["platform"], "*", entry["language"]), entry["variantId"])
    labels = task.get("accountLabels") or {}
    providers = getattr(getattr(service, "oauth", None), "providers", None) or {}
    live = bool(getattr(service, "publishing_live", False))
    can_publish = Billing().lifecycle(cur, claim["workspaceId"], now).get("canPublish")
    authority = task.get("publishAuthority") or {}
    if authority:
        # The grant is an owner's; if its owner is no longer an owner here, posts wait for approval instead.
        cur.execute("SELECT role FROM pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active'", (claim["workspaceId"], authority.get("grantedBy")))
        role = (cur.fetchone() or [None])[0]
        if role != "owner":
            authority = {}
            task = {**task, "publishAuthority": None}
    items, notices = [], []
    for destination in task["destinations"]:
        key = f"{destination['platform']}|{destination.get('channelId') or ''}|{destination['language']}"
        variant_id = by_slot.get((destination["platform"], destination.get("channelId") or "", destination["language"])) or by_slot.get((destination["platform"], "*", destination["language"]))
        variant = variants.get(variant_id)
        route = capabilities.publish_route(state, destination, providers=providers, live=live, can_publish=can_publish)
        item = {"key": key, "platform": destination["platform"], "channelId": destination.get("channelId"), "account": labels.get(destination.get("channelId")) or "",
                "language": destination["language"], "variantId": variant_id, "variantRevision": (variant or {}).get("revision"),
                "textDigest": digest(variant.get("text", "")) if variant else None, "state": "ready_for_review", "reason": None,
                "publishAt": occurrence["stages"].get("publishAt"), "capability": {"publish": route["publish"], "code": route["code"], "reason": route["reason"]},
                "decision": None, "approvedVia": None, "reviewId": None, "jobId": None, "attempts": 0, "lastError": None, "changedAt": now}
        if variant is None:
            item.update(state="failed", reason="The writer didn't return a draft for this platform.", publishAt=None)
        elif policy == "drafts":
            item["publishAt"] = None
        elif not route["publish"] and route["code"] in ("disconnected", "reauthorize"):
            item.update(state="platform_disconnected", reason=route["reason"])
        elif not route["publish"]:
            # No route to publish here (the platform, the server or the plan): a draft for the person, never a promise.
            item.update(publishAt=None, reason=route["reason"])
        elif policy == "auto":
            blockers = publisher.auto_blockers(state, task, occurrence, item, variant)
            if blockers:
                item["reason"] = "Held for your approval: " + blockers[0]
            else:
                item.update(state="approved", approvedVia="owner_preauthorization",
                            decision={"decision": "approve", "by": authority.get("grantedBy"), "at": now, "standing": True,
                                      "variantRevision": variant["revision"], "textDigest": item["textDigest"]})
        if variant is not None and policy != "drafts":
            limit_issue = publisher.text_blockers(variant, destination["platform"])
            if limit_issue and item["state"] == "ready_for_review" and not item["reason"]:
                item["reason"] = limit_issue[0] + " Edit it before approving."
        items.append(item)
    occurrence.update(items=items, lifecycle="drafted", runId=run_id, generatedAt=now, completedAt=now, draftCount=sum(1 for i in items if i["variantId"]),
                      costUsdMicro=round(float(cost) * 1_000_000) if isinstance(cost, (int, float)) else 0)
    occurrence["state"] = lifecycle.projected(occurrence)
    occurrence.pop("leaseUntil", None)
    _skill(occurrence, "write", "done", f"Drafted {occurrence['draftCount']} version{'s' if occurrence['draftCount'] != 1 else ''}", now)
    if len(items) > 1 or workflow.get("platformNotes"):
        _skill(occurrence, "platform_adaptation", "done", "One version per platform: " + ", ".join(i["platform"] for i in items), now)
    _skill(occurrence, "quality_check", "done", "; ".join(i["reason"] for i in items if i["reason"]) or "Length, sources and facts checked", now)
    held = [i for i in items if i["state"] == "ready_for_review" and i["publishAt"]]
    approved = [i for i in items if i["state"] == "approved"]
    if policy == "review" or held:
        _skill(occurrence, "approval_gate", "waiting", f"{len(held)} post{'s' if len(held) != 1 else ''} waiting for approval", now)
    if approved:
        _skill(occurrence, "auto_publish_check", "done", f"{len(approved)} post{'s' if len(approved) != 1 else ''} cleared to publish automatically", now)
    campaigns._history(occurrence, now, "drafted", summary_line(items, policy))
    campaign = next((c for c in state["raffi"]["campaignPlanning"]["campaigns"] if c["id"] == task["campaignId"]), None)
    if campaign is not None and not any(i.get("occurrenceId") == occurrence["id"] for i in campaign["items"]):
        campaign["items"].append({"id": occurrence["id"], "occurrenceId": occurrence["id"], "runId": run_id, "conversationId": occurrence.get("conversationId"), "status": "draft", "needsReview": bool(held)})
    disconnected = [i for i in items if i["state"] == "platform_disconnected"]
    owner = task.get("activatedBy") or task["createdBy"]
    watchers = list(task.get("emailWatchers") or [])
    if disconnected and not (occurrence.get("notices") or {}).get("disconnectedSentAt"):
        occurrence.setdefault("notices", {})["disconnectedSentAt"] = now
        notices.append(("platform_disconnected", [owner] + watchers, disconnected[0]["reason"]))
    return {"state": occurrence["state"], "lifecycle": "drafted", "occurrenceId": occurrence["id"], "items": [{k: i[k] for k in ("key", "state", "reason")} for i in items], "notify": notices}


def summary_line(items, policy):
    parts = []
    for item in items:
        where = item["platform"] + (f" ({item['account']})" if item.get("account") else "")
        if item["state"] == "approved":
            parts.append(f"{where}: cleared to publish automatically")
        elif item["state"] == "platform_disconnected":
            parts.append(f"{where}: account disconnected")
        elif item["state"] == "failed":
            parts.append(f"{where}: {item['reason']}")
        elif item["publishAt"] is None:
            parts.append(f"{where}: draft only")
        else:
            parts.append(f"{where}: waiting for approval")
    return "Drafted. " + "; ".join(parts) + "."


def notify(service, workspace_id, task, occurrence, kind, users, detail, again=""):
    """One email per person, kind and run (deduped in pr_notifications). A failure never changes the run."""
    mailer, lookup, base = getattr(service, "mailer", None), getattr(service, "_email_for", None), getattr(service, "public_base_url", "")
    results = []
    try:
        with service.connection_factory() as db, db.cursor() as cur:
            for user_id in dict.fromkeys(user for user in users if user):
                cur.execute("SELECT 1 FROM pr_memberships m JOIN pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, user_id))
                if not cur.fetchone():
                    continue
                cur.execute("INSERT INTO public.pr_notifications(workspace_id,user_id,kind,dedupe_key,meta) VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id::text",
                            (workspace_id, user_id, kind, f"{kind}:{occurrence['id']}:{again + ':' if again else ''}{user_id}", json.dumps({"taskId": task["id"], "occurrenceId": occurrence["id"]})))
                inserted = cur.fetchone()
                if not inserted:
                    continue
                sent = False
                if mailer and lookup and base:
                    address = lookup(user_id)
                    url = f"{base}/app/automations?task={task['id']}"
                    sent = bool(address) and bool(mailer.automation_notice(address, kind, task.get("name") or "Your automation", detail, url).get("sent"))
                    if sent:
                        cur.execute("UPDATE public.pr_notifications SET sent=true WHERE id=%s", (inserted[0],))
                results.append({"userId": user_id, "kind": kind, "sent": sent})
    except Exception as error:  # noqa: BLE001
        LOG.warning(json.dumps({"event": "automation.notice_failed", "kind": kind, "error": type(error).__name__}))
    return results


# --- the sweep ---------------------------------------------------------------------------------------------------

def _follow(item, target, reason, now):
    """Mirror a job's state into its item. The job is the ground truth, so an out-of-order state is recorded as is."""
    if item["state"] == target:
        return False
    if lifecycle.can_move(item["state"], target):
        lifecycle.move(item, target, reason=reason, at=now)
    else:
        item.update(state=target, reason=reason, changedAt=now)
    return True


def advance(worker, max_workspaces=20, max_commits=10):
    service, now = worker.service, worker.clock()
    engine = service.commands.engine
    commits, notices, changed_total = [], [], 0
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("""SELECT id::text,state FROM pr_workspaces WHERE NOT state ? 'accountDeletion' AND (
            EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,occurrences}','[]'::jsonb)) o
                    WHERE o->>'lifecycle'='drafted' AND EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(o->'items','[]'::jsonb)) i
                        WHERE i->>'state' = ANY(%s) AND (i->>'publishAt' IS NOT NULL OR i->>'jobId' IS NOT NULL OR i->>'state' = 'needs_revision')))
            OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,recurringTasks}','[]'::jsonb)) t
                    WHERE t->>'status'='paused' AND (t->>'pausedUntil')::double precision <= %s))
            ORDER BY random() LIMIT %s FOR UPDATE SKIP LOCKED""", (list(OPEN_STATES), now, max_workspaces))
        for workspace_id, state in cur.fetchall():
            changed = False
            root = state["raffi"]["campaignPlanning"]
            tasks = {t["id"]: t for t in root["recurringTasks"]}
            channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels", [])}
            jobs = {j["id"]: j for j in (state.get("phase2") or {}).get("jobs", [])}
            variants = {v["id"]: v for v in state.get("variants", [])}
            for task in root["recurringTasks"]:
                if task["status"] == "paused" and task.get("pausedUntil") and task["pausedUntil"] <= now and task.get("activatedBy"):
                    task.update(status="active", resumedAt=now, resumedBy="raffi")
                    task.pop("pausedUntil", None)
                    campaigns.refresh_next(task, now)
                    changed = True
            for occurrence in root["occurrences"]:
                task = tasks.get(occurrence["taskId"])
                if task is None or occurrence.get("lifecycle") != "drafted" or not campaigns.open_items(occurrence):
                    continue
                owner = task.get("activatedBy") or task["createdBy"]
                watchers = list(task.get("emailWatchers") or [])
                for item in campaigns.open_items(occurrence):
                    channel = channels.get(item.get("channelId"))
                    ready = bool(channel) and engine.channel_state(channel) == "Ready for posting"
                    if item.get("jobId") and item["state"] == "platform_disconnected" and (jobs.get(item["jobId"]) or {}).get("state") == "held":
                        publish_at = item.get("publishAt") or 0
                        if ready and now < publish_at - 120:
                            # Reconnected in time: the held job is cancelled and the approved post is queued again.
                            campaigns._cancel_job(state, item["jobId"], now, "Replaced after the account was reconnected")
                            item["jobId"] = None
                            lifecycle.move(item, "approved", reason=None, at=now)
                            campaigns._history(occurrence, now, "reconnected", f"{item['platform']} account reconnected; the post will be queued again.")
                            changed = True
                        elif now >= publish_at:
                            lifecycle.move(item, "failed", reason="The account was disconnected at the publish time, so it was not published. The draft is kept.", at=now)
                            campaigns._history(occurrence, now, "failed", f"{item['platform']} post not published: account disconnected.")
                            changed = True
                        continue
                    if item.get("jobId"):
                        job = jobs.get(item["jobId"])
                        target = lifecycle.job_item_state(job["state"], ready) if job else "failed"
                        if target and target != item["state"]:
                            last = ((job or {}).get("events") or [{}])[-1].get("message") if job else "The queued post disappeared."
                            reason = None if target in ("scheduled", "publishing", "published") else clean(last or "", 300)
                            if target == "published":
                                item["url"] = (job or {}).get("url")
                                reason = None
                            _follow(item, target, reason, now)
                            campaigns._history(occurrence, now, target, f"{item['platform']}: {lifecycle.LABELS.get(target, target)}" + (f" — {reason}" if reason else "") + ".")
                            if target in ("failed", "platform_disconnected"):
                                notices.append((workspace_id, task, occurrence, "platform_disconnected" if target == "platform_disconnected" else "publish_failed", [owner] + watchers, reason or ""))
                            changed = True
                        continue
                    if item["state"] == "needs_revision":
                        variant = variants.get(item.get("variantId"))
                        if variant and variant.get("revision") != item.get("revisionFrom", item.get("variantRevision")):
                            item.update(variantRevision=variant["revision"], textDigest=digest(variant.get("text", "")))
                            lifecycle.move(item, "ready_for_review", reason="Draft updated after your comments.", at=now)
                            campaigns._history(occurrence, now, "revised", f"{item['platform']} draft updated; ready for review again.")
                            changed = True
                    publish_at = item.get("publishAt")
                    if publish_at is None:
                        continue
                    if item["state"] in ("ready_for_review", "needs_revision") and now >= publish_at:
                        lifecycle.move(item, "approval_expired", reason="Nobody approved it before its publish time, so it was not published. The draft is kept.", at=now)
                        campaigns._history(occurrence, now, "approval_expired", f"{item['platform']} post not published: no approval before its time.")
                        notices.append((workspace_id, task, occurrence, "approval_expired", [owner] + watchers, f"{item['platform']} post planned for {occurrence['stages']['local'].get('publish', '')[:16].replace('T', ' ')}."))
                        changed = True
                        continue
                    if item["state"] == "platform_disconnected":
                        if now >= publish_at:
                            # Auto-publish or approved: it failed for the account; waiting for review: nobody approved it either.
                            target = "failed" if (item.get("decision") or {}).get("decision") == "approve" or occurrence.get("policy") == "auto" else "approval_expired"
                            lifecycle.move(item, target, reason="The account was still disconnected at the publish time, so it was not published. The draft is kept.", at=now)
                            campaigns._history(occurrence, now, target, f"{item['platform']} post not published: account disconnected.")
                            changed = True
                        elif ready:
                            lifecycle.move(item, "approved" if (item.get("decision") or {}).get("decision") == "approve" else "ready_for_review", reason=None, at=now)
                            campaigns._history(occurrence, now, "reconnected", f"{item['platform']} account reconnected.")
                            changed = True
                        continue
                    if item["state"] == "approved":
                        if task["status"] != "active":
                            if now >= publish_at:
                                lifecycle.move(item, "skipped", reason="The automation was paused at this post's time, so it was not published.", at=now)
                                campaigns._history(occurrence, now, "skipped", f"{item['platform']} post skipped: automation paused.")
                                changed = True
                            continue
                        if now >= publish_at + 3600:
                            lifecycle.move(item, "failed", reason=item.get("lastError") or "It couldn't be queued in time, so it was not published. The draft is kept.", at=now)
                            campaigns._history(occurrence, now, "failed", f"{item['platform']} post not published: {item['reason']}")
                            notices.append((workspace_id, task, occurrence, "publish_failed", [owner] + watchers, item["reason"]))
                            changed = True
                        elif now >= publish_at - publisher.COMMIT_LEAD and len(commits) < max_commits:
                            commits.append((workspace_id, occurrence["id"], item["key"], publisher.expected_principal(task, item), dict(item), task))
                # Posts waiting for approval: tell the person once, at the review time (or as soon as they are drafted).
                waiting = [i for i in occurrence.get("items") or [] if i["state"] == "ready_for_review" and i.get("publishAt")]
                review_at = (occurrence.get("stages") or {}).get("reviewAt")
                if waiting and not (occurrence.get("notices") or {}).get("reviewSentAt") and (review_at is None or now >= review_at):
                    occurrence.setdefault("notices", {})["reviewSentAt"] = now
                    _skill(occurrence, "notify", "done", "Asked for your approval", now)
                    campaigns._history(occurrence, now, "review_requested", f"Asked for approval of {len(waiting)} post{'s' if len(waiting) != 1 else ''}.")
                    reviewers = [owner] + watchers
                    notices.append((workspace_id, task, occurrence, "review_ready", reviewers, "Publishes " + (occurrence["stages"]["local"].get("publish") or "")[:16].replace("T", " ") + " if approved."))
                    changed = True
            if changed:
                _save(cur, workspace_id, state, "raffi")
                changed_total += 1
    committed = [commit_item(worker, *entry) for entry in commits]
    for workspace_id, task, occurrence, kind, users, detail in notices:
        notify(service, workspace_id, task, occurrence, kind, users, detail)
    return {"workspaces": changed_total, "commits": committed, "notices": len(notices)}


def _item_update(service, workspace_id, occurrence_id, item_key, change):
    def apply(state, occurrence, task, cur):
        item = next((i for i in occurrence.get("items") or [] if i["key"] == item_key), None)
        if item is not None:
            change(state, occurrence, task, item)
        return {"state": item["state"] if item else None}
    return _update_run(service, workspace_id, occurrence_id, "raffi", apply)


def commit_item(worker, workspace_id, occurrence_id, item_key, principal, item, task):
    """Queue one approved post: capability and plan, a server-side account check, then `raffi_run_commit` as the
    approving person. Problems move the item to the state that says what happened, never to a false success."""
    from .billing import Billing
    service, now = worker.service, worker.clock()
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT state FROM pr_workspaces WHERE id=%s", (workspace_id,))
        row = cur.fetchone()
        can_publish = Billing().lifecycle(cur, workspace_id, now).get("canPublish")
    if not row:
        return {"itemKey": item_key, "state": "gone"}
    state = row[0]
    providers = getattr(getattr(service, "oauth", None), "providers", None) or {}
    route = capabilities.publish_route(state, {"platform": item["platform"], "channelId": item.get("channelId")}, providers=providers,
                                       live=bool(getattr(service, "publishing_live", False)), can_publish=can_publish)
    if not route["publish"]:
        return _blocked(service, workspace_id, occurrence_id, item_key, task, route)
    reverify = getattr(getattr(service, "oauth", None), "reverify_for_worker", None)
    if reverify is not None:
        try:
            checked = reverify(workspace_id, item["channelId"])
        except AlphaError:
            checked = {"ready": False, "state": "reauthorization_required"}
        if not checked.get("ready"):
            return _blocked(service, workspace_id, occurrence_id, item_key, task, {"code": "disconnected", "reason": f"{item.get('account') or item['platform']} couldn't be verified just now. Reconnect it to publish; the draft is kept."}, transient=checked.get("state") == "verification_unavailable")
    if not principal:
        # Automatic publishing was turned off (or the approval is gone): the post waits for a person again.
        return _commit_failed(service, workspace_id, occurrence_id, item_key, task, AlphaError("Automatic publishing is off for this automation now, so this post needs your approval.", 409, code="publish_authority_required"))
    # A standing auto-publish grant is an owner's: it is re-checked as owner, a human approval as approve.
    repository, capability = principal_repository(service, workspace_id, principal, "owner" if item.get("approvedVia") == "owner_preauthorization" else "approve")
    try:
        for _ in range(2):
            try:
                saved = repository.mutate(workspace_id, capability, repository.get(workspace_id, capability)["revision"], "raffi_run_commit", {"occurrenceId": occurrence_id, "itemKey": item_key})
                break
            except AlphaError as error:
                if getattr(error, "code", None) != "workspace_revision_conflict":
                    raise
        else:
            raise AlphaError("The workspace kept changing; trying again shortly.", 409)
        run = next(o for o in saved["state"]["raffi"]["campaignPlanning"]["occurrences"] if o["id"] == occurrence_id)
        done = next(i for i in run["items"] if i["key"] == item_key)
        return {"itemKey": item_key, "state": done["state"], "jobId": done.get("jobId")}
    except AlphaError as error:
        return _commit_failed(service, workspace_id, occurrence_id, item_key, task, error)


def _blocked(service, workspace_id, occurrence_id, item_key, task, route, transient=False):
    now = service.clock()
    notice = []

    def change(state, occurrence, _task, item):
        if item["state"] != "approved":
            return
        if transient:
            item["attempts"] = item.get("attempts", 0) + 1
            item["lastError"] = route["reason"]
            if item["attempts"] < publisher.MAX_ATTEMPTS:
                return
        target = "platform_disconnected" if route.get("code") in ("disconnected", "reauthorize", "not_connected") else "failed"
        lifecycle.move(item, target, reason=route["reason"], at=now)
        campaigns._history(occurrence, now, target, f"{item['platform']} post not queued: {route['reason']}")
        notice.append((occurrence, target))
    result = _item_update(service, workspace_id, occurrence_id, item_key, change)
    for occurrence, target in notice:
        notify(service, workspace_id, task, occurrence, "platform_disconnected" if target == "platform_disconnected" else "publish_failed",
               [task.get("activatedBy") or task["createdBy"]] + list(task.get("emailWatchers") or []), route["reason"])
    return {"itemKey": item_key, **(result or {}), "blocked": route.get("code")}


def _commit_failed(service, workspace_id, occurrence_id, item_key, task, error):
    now = service.clock()
    code, status, message = getattr(error, "code", None), getattr(error, "status", 400), str(error)
    notice = []

    def change(state, occurrence, _task, item):
        if item["state"] != "approved":
            return
        if code in ("draft_changed", "publish_authority_required", "source_use_required", "auto_blocked") or status == 403:
            item["decision"], item["approvedVia"] = None, None
            reason = message if status != 403 else "The person who approved this post can no longer approve posts here. Approve it again."
            lifecycle.move(item, "ready_for_review", reason=reason, at=now)
            campaigns._history(occurrence, now, "needs_approval", f"{item['platform']}: {reason}")
            notice.append(("review_ready", reason))
        elif status == 402:
            lifecycle.move(item, "failed", reason="Your plan doesn't include publishing right now, so this post was not published. The draft is kept.", at=now)
            campaigns._history(occurrence, now, "failed", f"{item['platform']}: plan doesn't include publishing.")
            notice.append(("publish_failed", item["reason"]))
        elif code in ("automation_inactive", "not_due"):
            return
        else:
            item["attempts"] = item.get("attempts", 0) + 1
            item["lastError"] = clean(message, 300)
            campaigns._history(occurrence, now, "retry", f"{item['platform']}: couldn't queue ({item['lastError']}); attempt {item['attempts']} of {publisher.MAX_ATTEMPTS}.")
            if item["attempts"] >= publisher.MAX_ATTEMPTS:
                lifecycle.move(item, "failed", reason=f"It couldn't be queued: {item['lastError']} The approved draft is kept.", at=now)
                notice.append(("publish_failed", item["reason"]))
    result = _item_update(service, workspace_id, occurrence_id, item_key, change)
    if notice:
        run = {"id": occurrence_id}
        for kind, detail in notice:
            # A fresh request for approval after one was voided is its own notice, never swallowed by the first.
            notify(service, workspace_id, task, run, kind, [task.get("activatedBy") or task["createdBy"]] + list(task.get("emailWatchers") or []), detail, again=f"{item_key}:{int(now)}")
    return {"itemKey": item_key, **(result or {}), "error": message}

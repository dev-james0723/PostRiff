"""Who did what in a workspace, from records that name the person ("What did Alex post?", "Who approved this?").

Only stored attributions are used, and each event says which record it came from:

- post records: who prepared a review (its manifest's actor) and who approved it (`approvedBy`);
- automation and campaign records: who created, activated, paused, resumed, cancelled or deleted an automation,
  updated a brief, linked or unlinked a draft, or decided on an automation's post;
- writing runs: who started the run a draft came from (drafts don't record who typed them);
- the audit log and the edit signals preference learning keeps: owners and admins only, as on the Audit page.

Nothing is inferred: a draft is never credited to the person who happened to schedule it, and a post is "approved by",
never "posted by" (Rafii's publisher sends it after approval). Pure reads inside the caller's transaction.
"""
from __future__ import annotations

from .. import campaigns
from . import routes, timeframe

AUDIT_ROLES = ("owner", "admin")
_POST_KINDS = ("post.approved", "post.prepared", "post.cancelled")
_AUTOMATION_ACTS = (("createdBy", "createdAt", "created the automation"), ("activatedBy", "activatedAt", "turned the automation on"),
                    ("pausedBy", "pausedAt", "paused the automation"), ("resumedBy", "resumedAt", "resumed the automation"),
                    ("cancelledBy", "cancelledAt", "cancelled the automation"), ("deletedBy", "deletedAt", "deleted the automation"))
_AUDIT_LABELS = {"channel.connected": "connected an account", "channel.disconnected": "disconnected an account", "channel.verified": "re-verified an account",
                 "member.updated": "changed a member's role", "member.removed": "removed a member", "member.left": "left the workspace",
                 "automation.changed_by_proposal": "changed an automation through Rafii", "post.review_prepared_by_proposal": "prepared a post through Rafii",
                 "campaign.items_linked_by_agent": "linked drafts or posts to a campaign through Rafii", "campaign.items_unlinked_by_agent": "unlinked drafts or posts from a campaign through Rafii",
                 "api_token.created": "created an API token", "api_token.revoked": "revoked an API token", "memory.egress_decided": "changed who may read memory",
                 "research.egress_decided": "changed web research", "billing.checkout_started": "opened billing checkout", "workspace.created": "created the workspace"}
_SIGNAL_LABELS = {"draft.edited": "edited a draft", "draft.update_accepted": "accepted a proposed update to a draft", "draft.rejected": "set a draft aside",
                  "job.cancelled": "cancelled a waiting post", "proposal.decided": "decided on a learned preference"}
NOT_ATTRIBUTED = ["Drafts don't record who typed them; a draft from a writing run is credited to the person who started that run.",
                  "Posts go out through Rafii's publisher after approval: the record names who approved them, not who \"posted\"."]


def members(cur, workspace_id: str) -> list[dict]:
    cur.execute("SELECT m.user_id::text, m.role, m.status, coalesce(p.display_name,'') FROM public.pr_memberships m LEFT JOIN public.pr_profiles p ON p.user_id=m.user_id "
                "WHERE m.workspace_id=%s ORDER BY m.role, m.user_id", (workspace_id,))
    return [{"userId": row[0], "role": row[1], "status": row[2], "name": row[3].strip()} for row in cur.fetchall()]


def label(member: dict | None, principal: str | None = None) -> str:
    if not member:
        return "someone no longer in this workspace"
    if principal and member["userId"] == principal:
        return "you"
    return member["name"] or f"a teammate without a display name ({member['role']})"


def match(people: list[dict], query: str | None, principal: str) -> dict:
    """The member a message names: "me", a display name, or its first word. Never a guess between two people."""
    wanted = " ".join((query or "").lower().split())
    if not wanted:
        return {"member": None}
    if wanted in ("i", "me", "myself"):
        return {"member": next((m for m in people if m["userId"] == principal), None)}
    exact = [m for m in people if m["name"] and m["name"].lower() == wanted]
    first = [m for m in people if m["name"] and m["name"].lower().split()[0] == wanted]
    prefix = [m for m in people if m["name"] and m["name"].lower().startswith(wanted)]
    for found in (exact, first, prefix):
        if len(found) == 1:
            return {"member": found[0]}
        if len(found) > 1:
            return {"ambiguous": [m["name"] for m in found][:5]}
    return {"none": True, "known": [m["name"] for m in people if m["name"]][:10]}


def _dedupe(events: list[dict]) -> list[dict]:
    """One line per act: an audit entry about something a record already shows (same person, same item) is dropped,
    and identical entries are collapsed into one with a count."""
    recorded = {(e["actor"], e["subject"]) for e in events if e["source"] != "audit log" and e["subject"]}
    out, seen = [], {}
    for e in sorted(events, key=lambda e: -e["at"]):
        if e["source"] == "audit log" and (e["actor"], e["subject"]) in recorded:
            continue
        key = (e["actor"], e["kind"], e["summary"], e["source"])
        if key in seen:
            seen[key]["times"] = seen[key].get("times", 1) + 1
            continue
        seen[key] = e
        out.append(e)
    for e in out:
        if e.get("times", 1) > 1:
            e["summary"] += f" ({e['times']} times)"
    return out


def _event(kind, at, actor, summary, href, source, subject=None):
    return {"kind": kind, "at": float(at), "actor": actor, "summary": summary, "href": href, "source": source, "subject": subject}


def _account(state, channel_id):
    channel = next((c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and c.get("id") == channel_id), None)
    return (channel or {}).get("account")


def _state_events(state: dict) -> list[dict]:
    """Every attributed event the workspace records in its own state (visible to every member)."""
    events = []
    p2 = state.get("phase2") or {}
    for job in p2.get("jobs", []):
        m = job.get("manifest") or {}
        what = f"a {m.get('platform')} post for {m.get('account')}" + (f" ({(m.get('timing') or {}).get('local', '').replace('T', ' ')})" if (m.get("timing") or {}).get("local") else "")
        if job.get("approvedBy") and isinstance(job.get("approvedAt"), (int, float)):
            events.append(_event("post.approved", job["approvedAt"], job["approvedBy"], f"approved {what}; it is now {job.get('state')}", routes.href("queue", query={"job": job["id"]}), "post record", job["id"]))
    for review in p2.get("reviews", []):
        m = review.get("manifest") or {}
        if m.get("actor") and isinstance(review.get("createdAt"), (int, float)):
            what = f"a {m.get('platform')} post for {m.get('account')} at {(m.get('timing') or {}).get('local', '').replace('T', ' ')}"
            events.append(_event("post.prepared", review["createdAt"], m["actor"], f"prepared {what} for approval", routes.href("queue"), "review record", review.get("id")))
    root = campaigns._root(state)
    for task in root.get("recurringTasks", []):
        name = task.get("name") or "an automation"
        for by, at, verb in _AUTOMATION_ACTS:
            if task.get(by) and isinstance(task.get(at), (int, float)):
                events.append(_event(f"automation.{verb.split()[0]}", task[at], task[by], f"{verb.replace('the automation', f'“{name}”')}",
                                     routes.href("automations", query={"edit": task["id"]}), "automation record", task["id"]))
        grant = task.get("publishAuthority") or {}
        if grant.get("grantedBy") and isinstance(grant.get("grantedAt"), (int, float)):
            events.append(_event("automation.granted", grant["grantedAt"], grant["grantedBy"], f"let “{name}” publish without asking each time",
                                 routes.href("automations", query={"edit": task["id"]}), "automation record", task["id"]))
    for campaign in root.get("campaigns", []):
        title = (campaign.get("goal") or "a campaign")[:60]
        href = routes.href("automations", query={"campaign": campaign["id"]})
        if campaign.get("createdBy") and isinstance(campaign.get("createdAt"), (int, float)):
            events.append(_event("campaign.created", campaign["createdAt"], campaign["createdBy"], f"created the campaign “{title}”", href, "campaign record", campaign["id"]))
        if campaign.get("updatedBy") and isinstance(campaign.get("updatedAt"), (int, float)):
            events.append(_event("campaign.updated", campaign["updatedAt"], campaign["updatedBy"], f"updated the brief of “{title}”", href, "campaign record", campaign["id"]))
        for entry in campaign.get("itemLog") or []:
            if entry.get("by") and isinstance(entry.get("at"), (int, float)):
                verb = "added" if entry.get("op") == "link" else "removed"
                events.append(_event(f"campaign.{entry.get('op')}", entry["at"], entry["by"], f"{verb} a {entry.get('kind')} {'to' if verb == 'added' else 'from'} “{title}”", href,
                                     "campaign record", entry.get("id")))
    for occurrence in root.get("occurrences", []):
        for item in occurrence.get("items") or []:
            decision = item.get("decision") or {}
            if decision.get("by") and isinstance(decision.get("at"), (int, float)):
                events.append(_event(f"automation_post.{decision.get('decision')}", decision["at"], decision["by"],
                                     f"{ {'approve': 'approved', 'reject': 'rejected', 'revise': 'sent back'}.get(decision.get('decision'), 'decided on')} an automation post for {item.get('platform')}",
                                     routes.href("automations", query={"edit": occurrence.get("taskId")}) if occurrence.get("taskId") else routes.href("automations"),
                                     "automation run record", occurrence.get("id")))
    return events


def _run_events(cur, workspace_id: str, state: dict, actor: str | None, since: float, until: float) -> list[dict]:
    """Writing runs someone started, with the drafts they produced (Rafii's own answers are not counted)."""
    cur.execute("SELECT id::text, actor::text, extract(epoch from created_at), status FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key NOT LIKE 'site:%%' "
                "AND created_at >= to_timestamp(%s) AND created_at < to_timestamp(%s)" + (" AND actor=%s" if actor else "") + " ORDER BY created_at DESC LIMIT 50",
                (workspace_id, since, until, actor) if actor else (workspace_id, since, until))
    drafts: dict[str, list[dict]] = {}
    for v in state.get("variants", []):
        run = (v.get("provenance") or {}).get("runId") or v.get("runId")
        if run:
            drafts.setdefault(run, []).append(v)
    events = []
    for run_id, run_actor, at, status in cur.fetchall():
        made = drafts.get(run_id) or []
        if made:
            what = ", ".join(f"{v.get('platform')}" + (f" · {_account(state, v.get('channelId'))}" if v.get("channelId") else "") for v in made[:4])
            summary, href = f"started a writing run that made {len(made)} draft(s): {what}", routes.href("queue", query={"view": "drafts", "draft": made[0]["id"]})
        else:
            summary, href = f"started a writing run ({status}; none of its drafts were saved)", routes.href("queue", query={"view": "drafts"})
        events.append(_event("draft.run", at, run_actor, summary, href, "writing run", run_id))
    return events


def _audit_events(cur, workspace_id: str, actor: str | None, since: float, until: float) -> list[dict]:
    cur.execute("SELECT actor::text, kind, subject, extract(epoch from at) FROM public.pr_audit_events WHERE workspace_id=%s AND at >= to_timestamp(%s) AND at < to_timestamp(%s)"
                + (" AND actor=%s" if actor else "") + " ORDER BY at DESC LIMIT 100", (workspace_id, since, until, actor) if actor else (workspace_id, since, until))
    return [_event(kind, at, who, _AUDIT_LABELS.get(kind, kind.replace("_", " ").replace(".", ": ")), routes.href("audit"), "audit log", subject)
            for who, kind, subject, at in cur.fetchall() if who]


def _signal_events(cur, workspace_id: str, actor: str | None, since: float, until: float) -> list[dict]:
    # A learning event's subject is an object ({"variantId", "jobId", ...}); the draft (else the post) is what it is about.
    cur.execute("SELECT actor::text, kind, coalesce(subject->>'variantId', subject->>'jobId'), extract(epoch from created_at) FROM public.pr_learning_events WHERE workspace_id=%s AND kind = ANY(%s) "
                "AND created_at >= to_timestamp(%s) AND created_at < to_timestamp(%s)" + (" AND actor=%s" if actor else "") + " ORDER BY created_at DESC LIMIT 100",
                (workspace_id, list(_SIGNAL_LABELS), since, until, actor) if actor else (workspace_id, list(_SIGNAL_LABELS), since, until))
    out = []
    for who, kind, subject, at in cur.fetchall():
        href = routes.href("queue", query={"view": "drafts", "draft": subject}) if kind.startswith("draft.") and subject and routes.ID_VALUE.match(subject) else routes.href("queue")
        out.append(_event(kind, at, who, _SIGNAL_LABELS[kind], href, "edit signals", subject))
    return out


def read(cur, workspace_id: str, state: dict, *, role: str, principal: str, member: str | None = None, since: float | None = None, until: float | None = None,
         now: float, zone: str = "UTC", only: str | None = None, window: str | None = None) -> dict:
    """{"member", "range", "events", "notAttributed", "restricted", "match"}. `only="posts"` keeps post events."""
    people = members(cur, workspace_id)
    found = match(people, member, principal) if member else {"member": None}
    if member and not found.get("member"):
        return {"match": found, "member": None, "events": [], "notAttributed": NOT_ATTRIBUTED, "restricted": role not in AUDIT_ROLES, "people": len(people)}
    person = found.get("member")
    until = until if until is not None else now + 60
    since = since if since is not None else now - 30 * 86400
    who = person["userId"] if person else None
    events = [e for e in _state_events(state) if since <= e["at"] < until and (who is None or e["actor"] == who)]
    events += _run_events(cur, workspace_id, state, who, since, until)
    restricted = role not in AUDIT_ROLES
    if not restricted:
        events += _audit_events(cur, workspace_id, who, since, until)
        events += _signal_events(cur, workspace_id, who, since, until)
    if only == "posts":
        events = [e for e in events if e["kind"] in _POST_KINDS or e["kind"].startswith("automation_post.")]
    events = _dedupe(events)
    names = {p["userId"]: p for p in people}
    events.sort(key=lambda e: -e["at"])
    shown = [{**e, "who": label(names.get(e["actor"]), principal), "when": timeframe.local(e["at"], zone)} for e in events[:40]]
    notes = list(NOT_ATTRIBUTED) + (["The audit log and edit history are visible to owners and admins only, so they are not included here."] if restricted else
                                    ["Edits and set-asides are recorded only while preference learning is on, and only for its retention period."])
    return {"match": found, "member": {"userId": person["userId"], "name": label(person, principal), "role": person["role"]} if person else None,
            "range": {"label": window or "the last 30 days", "since": since, "until": until}, "events": shown, "total": len(events),
            "notAttributed": notes, "restricted": restricted, "people": len(people)}


def attribution(cur, workspace_id: str, state: dict, kind: str, target: str, *, role: str, principal: str, zone: str = "UTC") -> dict:
    """Who acted on one item ("Who approved this?", "Who changed this automation?"), newest first."""
    people = {p["userId"]: p for p in members(cur, workspace_id)}
    subjects = {target}
    if kind in ("job", "review"):
        p2 = state.get("phase2") or {}
        item = next((i for i in p2.get("jobs", []) + p2.get("reviews", []) if i.get("id") == target), None)
        if item is None:
            return {"found": False, "events": []}
        subjects.add((item.get("manifest") or {}).get("variantId"))
        # The review this post was approved from (same digest): who prepared it.
        subjects |= {r["id"] for r in p2.get("reviews", []) if item.get("approvalDigest") and r.get("digest") == item["approvalDigest"]}
    elif kind == "automation":
        task = next((t for t in campaigns._root(state).get("recurringTasks", []) if t.get("id") == target), None)
        if task is None:
            return {"found": False, "events": []}
        subjects.add(task.get("campaignId"))
    elif kind == "draft":
        if not any(v.get("id") == target for v in state.get("variants", [])):
            return {"found": False, "events": []}
        # The reviews and posts made from this draft (who prepared and approved them).
        p2 = state.get("phase2") or {}
        subjects |= {i["id"] for i in p2.get("jobs", []) + p2.get("reviews", []) if (i.get("manifest") or {}).get("variantId") == target}
    events = [e for e in _state_events(state) if e["subject"] in subjects]
    if kind == "draft":
        variant = next(v for v in state["variants"] if v.get("id") == target)
        run = (variant.get("provenance") or {}).get("runId") or variant.get("runId")
        if run:
            cur.execute("SELECT actor::text, extract(epoch from created_at), status FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s", (workspace_id, run))
            row = cur.fetchone()
            if row and row[0]:
                events.append(_event("draft.run", row[1], row[0], "started the writing run that made this draft", routes.href("queue", query={"view": "drafts", "draft": target}), "writing run", run))
    restricted = role not in AUDIT_ROLES
    if not restricted:
        subject_list = [s for s in subjects if s]
        cur.execute("SELECT actor::text, kind, subject, extract(epoch from at) FROM public.pr_audit_events WHERE workspace_id=%s AND subject = ANY(%s) ORDER BY at DESC LIMIT 50",
                    (workspace_id, subject_list))
        events += [_event(k, at, who, _AUDIT_LABELS.get(k, k), routes.href("audit"), "audit log", subj) for who, k, subj, at in cur.fetchall() if who]
        cur.execute("SELECT actor::text, kind, coalesce(subject->>'variantId', subject->>'jobId'), extract(epoch from created_at) FROM public.pr_learning_events "
                    "WHERE workspace_id=%s AND (subject->>'variantId' = ANY(%s) OR subject->>'jobId' = ANY(%s)) AND kind = ANY(%s) ORDER BY created_at DESC LIMIT 50",
                    (workspace_id, subject_list, subject_list, list(_SIGNAL_LABELS)))
        events += [_event(k, at, who, _SIGNAL_LABELS[k], routes.href("queue"), "edit signals", subj) for who, k, subj, at in cur.fetchall()]
    events = _dedupe(events)
    events.sort(key=lambda e: -e["at"])
    shown = [{**e, "who": label(people.get(e["actor"]), principal), "when": timeframe.local(e["at"], zone)} for e in events[:20]]
    return {"found": True, "kind": kind, "events": shown, "restricted": restricted,
            "notAttributed": ([] if shown else ["Nothing stored names a person for this item."]) + (["The audit log is visible to owners and admins only."] if restricted else [])}

"""J01 — Draft and platform studio: paged draft lists for comparison, one draft's full current text and revision (for an
edit form, never the 1,500-character `draft.get` excerpt), its evidence and lineage, its revisions, the available
writers, and the guarded edit of an unscheduled draft through the normal author-edit command (`variant_edit`, draft
revision CAS, audited, leaves the draft needing review, invalidates open reviews).

Rewriting/adapting is not an action here: it is a paid writer run, so the generated control continues the conversation
with an explicit follow-up turn (the Manager's `draft_rewrite`, metered by the turn's own admission, with the writer and
voice the person chose). Selecting drafts is interaction context, never approval or publication.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import Receipt, action, common, query

ALL_PLATFORMS = ("LinkedIn", "Instagram", "Threads", "Xiaohongshu", "X", "Bluesky", "Mastodon", "Telegram", "Discord", "Facebook", "YouTube", "TikTok", "Pinterest",
                 "Weibo", "Bilibili", "Douyin", "Kuaishou", "Google Business Profile", "LINE Official Account", "Reddit", "Zhihu", "Pixelfed")
_DRAFT_ID = r"^[A-Za-z0-9_.:-]{1,120}$"
STATUSES = ("all", "unscheduled", "scheduled", "needs_review", "set_aside")
INVALIDATES = ["drafts_list", "draft_read", "draft_evidence", "draft_revisions", "calendar_agenda", "queue_status"]


def _variants(state):
    return [v for v in state.get("variants", []) if isinstance(v, dict) and v.get("id")]


def _jobs(state):
    return [j for j in (state.get("phase2") or {}).get("jobs", []) if isinstance(j, dict)]


def _committed(state, draft_id):
    return [j for j in _jobs(state) if (j.get("manifest") or {}).get("variantId") == draft_id and j.get("state") not in ("canceled", "failed")]


def _channel(state, channel_id):
    return next((c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and c.get("id") == channel_id), None) or {}


def _limit(platform):
    from ...contracts import LIMITS
    return (LIMITS.get(platform) or {}).get("characters")


def _variant(state, draft_id):
    variant = next((v for v in _variants(state) if v.get("id") == draft_id), None)
    if variant is None:
        raise AlphaError("That draft is not in this workspace.", 404, code="not_found")
    return variant


def _created_at(dctx, variants):
    from ...site_agent import reads
    times = reads._run_times(dctx.site_context(), [(v.get("provenance") or {}).get("runId") for v in variants])
    out = {}
    for v in variants:
        at = times.get((v.get("provenance") or {}).get("runId"))
        if at is None:
            first = next((r.get("at") for r in v.get("revisions") or [] if isinstance(r, dict) and isinstance(r.get("at"), (int, float))), None)
            at = first
        out[v["id"]] = at
    return out


def _row(dctx, v, created):
    text = v.get("text") or ""
    jobs = _committed(dctx.state, v["id"])
    limit = _limit(v.get("platform"))
    return {"draftId": v["id"], "ref": common.ref("draft", v["id"]), "platform": v.get("platform"), "language": v.get("language"),
            "account": _channel(dctx.state, v.get("channelId")).get("account"), "channelId": v.get("channelId"), "revision": v.get("revision"),
            "characters": len(text), "limit": limit, "overLimit": bool(limit and len(text) > limit), "needsReview": bool(v.get("needsReview")),
            "hasProposedUpdate": bool(v.get("proposedUpdate")), "committed": bool(jobs), "committedJobState": jobs[-1].get("state") if jobs else None,
            "setAside": bool(v.get("rejected")), "sourceCount": len(v.get("sourceIds") or []), "warningsCount": len(v.get("warnings") or []),
            "unknownsCount": len(v.get("unknowns") or []), "writerModel": (v.get("provenance") or {}).get("model"),
            "voice": "personalized" if v.get("voiceSourceIds") else "neutral", "fromAutomation": bool(v.get("automation")),
            "createdAt": common.iso(created), "excerpt": common.excerpt(text, 160), "href": f"/app/queue?view=drafts&draft={v['id']}"}


def drafts_list(dctx, inputs, cursor):
    variants = _variants(dctx.state)
    ids = inputs.get("ids")
    status = inputs.get("status") or "all"
    if ids is not None:   # present-but-empty ids select nothing (never "all drafts")
        order = {i: n for n, i in enumerate(ids)}
        variants = sorted((v for v in variants if v["id"] in order), key=lambda v: order[v["id"]])
    else:
        if status == "set_aside":
            variants = [v for v in variants if v.get("rejected")]
        else:
            variants = [v for v in variants if not v.get("rejected")]
            if status == "unscheduled":
                variants = [v for v in variants if not _committed(dctx.state, v["id"])]
            elif status == "scheduled":
                variants = [v for v in variants if _committed(dctx.state, v["id"])]
            elif status == "needs_review":
                variants = [v for v in variants if v.get("needsReview") or v.get("unknowns")]
    if inputs.get("platform"):
        variants = [v for v in variants if v.get("platform") == inputs["platform"]]
    if inputs.get("language"):
        variants = [v for v in variants if (v.get("language") or "").lower() == inputs["language"].lower()]
    if inputs.get("q"):
        words = [w for w in inputs["q"].casefold().split() if w]
        variants = [v for v in variants if all(w in " ".join([v.get("text") or "", v.get("platform") or "", v.get("language") or ""]).casefold() for w in words)]
    created = _created_at(dctx, variants)
    if ids is None:
        newest = (inputs.get("sort") or "newest") == "newest"
        variants = sorted(variants, key=lambda v: (created.get(v["id"]) or 0, v["id"]), reverse=newest)
    page, next_cursor, start = common.paginate("drafts_list", inputs, cursor, variants, default=50)
    rows = [_row(dctx, v, created.get(v["id"])) for v in page]
    missing = [i for i in ids or [] if i not in {v["id"] for v in variants}]
    state = "empty" if not variants else ("partial" if missing else "available")
    return ui_contracts.query_result(state, {"drafts": rows, "offset": start, "missingIds": missing}, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(variants), total=len(variants),
                                     note="Set-aside drafts are listed only when asked for." if status != "set_aside" and ids is None else None,
                                     warnings=["Some requested drafts are not in this workspace."] if missing else [])


def draft_read(dctx, inputs, _cursor):
    v = _variant(dctx.state, inputs["draftId"])
    text = v.get("text") or ""
    jobs = _committed(dctx.state, v["id"])
    from ...site_agent.tools import _job_view
    created = _created_at(dctx, [v])
    update = v.get("proposedUpdate") or None
    data = {**_row(dctx, v, created.get(v["id"])), "text": text, "openings": [str(o)[:400] for o in v.get("openings") or []][:3],
            "selectedOpening": v.get("selectedOpening"), "unknowns": [str(u)[:200] for u in v.get("unknowns") or []][:10],
            "warnings": [str(w)[:240] for w in v.get("warnings") or []][:10], "blockedByRetraction": bool(v.get("blockedByRetraction")),
            "proposedUpdate": ({"characters": len(update.get("text") or ""), "text": (update.get("text") or "")[:20000], "baseRevision": update.get("baseVariantRevision"),
                                "runId": update.get("runId")} if isinstance(update, dict) else None),
            "scheduled": [_job_view(dctx.site_context(), j) for j in jobs][:5], "editable": not jobs and not v.get("rejected"),
            "editBlockedReason": "This draft is already in the publishing queue; prepare a new draft instead." if jobs else None,
            "voiceSourceCount": len(v.get("voiceSourceIds") or []), "revisionsCount": len(v.get("revisions") or [])}
    return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("draft", v["id"])], revision=str(v.get("revision")),
                                     known=1, total=1)


def draft_evidence(dctx, inputs, _cursor):
    from .. import graph
    from ... import evidence
    from ...site_agent import reads
    v = _variant(dctx.state, inputs["draftId"])
    edges = graph.neighbours(dctx.state, "draft", v["id"])
    sources = []
    by_id = {s.get("id"): s for s in dctx.state.get("sources", []) if isinstance(s, dict)}
    for source_id in v.get("sourceIds") or []:
        source = by_id.get(source_id)
        if source is None:
            sources.append({"sourceId": source_id, "ref": None, "available": False, "kind": None, "title": None, "active": False, "retracted": None, "approvedFacts": None,
                            "facts": None, "origin": None, "host": None, "published": None, "fetchedAt": None})
            continue
        facts = [f for f in source.get("facts") or [] if isinstance(f, dict)]
        origin = source.get("origin") or {}
        sources.append({"sourceId": source_id, "ref": common.ref("source", source_id), "available": True, "kind": source.get("kind"), "title": str(source.get("title") or "")[:200],
                        "active": bool(source.get("active")), "retracted": bool(source.get("retracted")), "approvedFacts": sum(1 for f in facts if f.get("approved")),
                        "facts": len(facts), "origin": origin.get("kind"), "host": origin.get("host"), "published": origin.get("published") or None,
                        "fetchedAt": origin.get("fetchedAt")})
    claim_budget = 30
    claims_truncated = False
    for item in sources:
        stored = by_id.get(item["sourceId"])
        item["evidence"] = evidence.source(dctx.workspace_id, stored or {"id": item["sourceId"], "available": False})
        item["claims"] = []
        if stored and stored.get("active", True) and not stored.get("retracted"):
            for campaign in (dctx.state.get("coworker") or {}).get("sourceCampaigns") or []:
                if campaign.get("sourceId") != item["sourceId"] or not campaign.get("factPack") or not campaign.get("source"):
                    continue
                item["claims"].extend(evidence.fact_pack(dctx.workspace_id, campaign["factPack"], [campaign["source"]]))
            claims_truncated = claims_truncated or len(item["claims"]) > claim_budget
            item["claims"] = item["claims"][:claim_budget]
            claim_budget -= len(item["claims"])
    try:
        check = reads.voice_check(dctx.site_context(), draftId=v["id"])["data"]
        voice = {k: check.get(k) for k in ("empty", "findings", "basis", "summary", "platform") if k in check}
    except AlphaError:
        voice = None
    missing = [s["sourceId"] for s in sources if not s.get("available")]
    return ui_contracts.query_result("partial" if missing else "available", {"workspaceId": dctx.workspace_id, "claimsTruncated": claims_truncated, "draftId": v["id"], "edges": edges.get("edges") or [], "sources": sources, "voiceFit": voice},
                                     as_of=common.iso(dctx.now), source_refs=[common.ref("draft", v["id"])] + [s["ref"] for s in sources if s.get("ref")],
                                     revision=str(v.get("revision")), known=len(sources) - len(missing), total=len(sources),
                                     note="Each relationship names the stored field it comes from." if edges.get("edges") else None,
                                     warnings=["A source this draft used is no longer in the workspace."] if missing else [])


def draft_revisions(dctx, inputs, cursor):
    v = _variant(dctx.state, inputs["draftId"])
    revisions = [r for r in reversed(v.get("revisions") or []) if isinstance(r, dict)]
    page, next_cursor, start = common.paginate("draft_revisions", inputs, cursor, revisions, default=10)
    rows = [{"revision": r.get("revision"), "origin": r.get("origin"), "at": common.iso(r.get("at")), "characters": len(r.get("text") or ""),
             "text": (r.get("text") or "")[:4000], "textTruncated": len(r.get("text") or "") > 4000} for r in page]
    return ui_contracts.query_result("available" if revisions else "empty", {"draftId": v["id"], "current": v.get("revision"), "revisions": rows, "offset": start},
                                     as_of=common.iso(dctx.now), source_refs=[common.ref("draft", v["id"])], revision=str(v.get("revision")), next_cursor=next_cursor,
                                     known=len(revisions), total=len(revisions))


def writers_list(dctx, _inputs, _cursor):
    from ...site_agent import tools
    result = tools.models_summary(dctx.site_context())
    if not result.get("ok"):
        return ui_contracts.query_result("unavailable", as_of=result.get("observedAt"), note="The writer list isn't available here.", warnings=list(result.get("warnings") or []))
    from ... import writer_defaults
    data = {**(result.get("data") or {}), "workspaceDefault": writer_defaults.settings(dctx.state).get("model")}
    return ui_contracts.query_result("available", data, as_of=result.get("observedAt"), known=len(data.get("models") or []), total=len(data.get("models") or []))


# --- the edit action ----------------------------------------------------------------------------------------------------
def _edit_checks(dctx, inputs):
    v = _variant(dctx.state, inputs["draftId"])
    if _committed(dctx.state, v["id"]):
        raise AlphaError("This draft is already in the publishing queue. Prepare a new draft instead.", 409, code="draft_committed")
    if inputs["revision"] != v.get("revision"):
        raise AlphaError("This draft changed since you opened it. Reload it before saving your edit.", 409, code="draft_revision_conflict")
    if not inputs["text"].strip():
        raise AlphaError("Keep some draft text.", 400, code="ui_input")
    return v


def edit_confirm(dctx, inputs):
    v = _edit_checks(dctx, inputs)
    account = _channel(dctx.state, v.get("channelId")).get("account")
    target = f"{v.get('platform')} draft" + (f" · {account}" if account else "")
    lines = [f"Save your edited text to this {v.get('platform')} draft (revision {v.get('revision')} → {int(v.get('revision') or 0) + 1}), {len(inputs['text'].strip())} characters.",
             "It will need review again before it can be scheduled. Nothing is scheduled or published."]
    if v.get("proposedUpdate"):
        lines.append("The rewrite Rafii prepared for this draft will be discarded (your edit replaces it).")
    limit = _limit(v.get("platform"))
    if limit and len(inputs["text"].strip()) > limit:
        lines.append(f"It is over {v.get('platform')}'s {limit}-character limit.")
    return {"title": "Save draft edit", "summary": lines, "target": target, "timeZone": None, "cost": "No AI cost"}


def edit_execute(dctx, inputs, _key):
    expected = inputs["text"].strip()
    _edit_checks(dctx, inputs)
    service = dctx.service

    def change(state, principal):
        variant = _variant(state, inputs["draftId"])
        if _committed(state, variant["id"]):
            raise AlphaError("This draft is already in the publishing queue. Prepare a new draft instead.", 409, code="draft_committed")
        return service.commands(state, principal, "variant_edit", {"variantId": variant["id"], "variantRevision": inputs["revision"], "text": expected})

    service.repository.command(dctx.workspace_id, None, dctx.revision, change, requirement="edit",
                               audit_event=lambda _s: ("agent.draft_edited", inputs["draftId"], {"via": "rafii_genui", "artifactId": dctx.artifact["id"]}))
    saved = _variant(dctx.refresh_state(), inputs["draftId"])
    verified = saved.get("text") == expected and saved.get("revision") == inputs["revision"] + 1 and bool(saved.get("needsReview"))
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"draft:{saved['id']}@{saved.get('revision')}", changed_refs=[common.ref("draft", saved["id"])],
                   invalidation_keys=INVALIDATES, next_context={"draft": {"draftId": saved["id"], "revision": saved.get("revision"), "needsReview": True}},
                   message="Saved. The draft needs review again before it can be scheduled." if verified else "Saved, but the re-read didn't match; reload the draft.")


ID = {"type": "string", "maxLength": 120, "pattern": _DRAFT_ID}
query("drafts_list", "J01", "Drafts in this workspace (newest first) with platform, language, account, revision, length vs limit, review/committed state and a short "
      "excerpt; filter by words, platform, language or status, or list specific ids in the given order to compare them.",
      {"q": {"type": "string", "maxLength": 120}, "platform": {"type": "string", "enum": list(ALL_PLATFORMS)}, "language": {"type": "string", "maxLength": 20},
       "status": {"type": "string", "enum": list(STATUSES)}, "ids": {"type": "array", "maxItems": 10, "items": ID, "uniqueItems": True},
       "sort": {"type": "string", "enum": ["newest", "oldest"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
      drafts_list, page=50, search=True, tool="content.search", invalidated_by=("drafts_list",))
query("draft_read", "J01", "One draft's full current text, revision, openings, unknowns, warnings, waiting rewrite and publishing state (the edit form's source).",
      {"draftId": ID}, draft_read, required=("draftId",), refresh=None, tool="draft.get", invalidated_by=("draft_read",))
query("draft_evidence", "J01", "Where a draft came from: its sources (approved facts per source), reworks, campaign, automation, reviews and posts, and how it fits the voice.",
      {"draftId": ID}, draft_evidence, required=("draftId",), refresh=None, tool="relationships")
query("draft_revisions", "J01", "A draft's saved revisions, newest first, with origin and time.",
      {"draftId": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, draft_revisions, required=("draftId",), refresh=None, page=10)
query("writers_list", "J01", "The writers available in this workspace and the workspace default.", {}, writers_list, refresh=None, tool="models.summary")
action("draft_edit", "J01", "Save edit", "Saves your edited text to this unscheduled draft. It needs review again; nothing is scheduled or published.",
       "MUTATE_REVERSIBLE", "edit", {"draftId": ID, "revision": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
                                     "text": {"type": "string", "minLength": 1, "maxLength": 20000}},
       edit_confirm, edit_execute, required=("draftId", "revision", "text"), tool="draft_edit")

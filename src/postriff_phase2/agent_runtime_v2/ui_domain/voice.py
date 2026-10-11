"""J04 — Brand Brain / Learn My Voice from the real services: writing samples with their exact per-purpose/route consent and
eligibility (`voice_sources.project`), the approved vs proposed voice profile with evidence levels, learned vs proposed
preferences (`HostedLearning.proposals`), every consent layer separately, and the learning status as it really is
(derived from events and proposals, labelled; Rafii trains no model, so nothing here ever says "trained").

Actions go through the original workspace commands (`repository.mutate`, so permission class, audit and effects hooks
are the app's own):
- direct (edit, reversible): select / exclude a sample, local-rules analysis (no model, no cost), pasted import;
- native confirmation (owner): a sample's exact use grant, approving the proposed profile (bound to the proposal the
  person saw), deciding a learned-preference proposal, and AI voice analysis (managed model, writing credit; run outside
  the workspace lock by the original HostedVoiceAnalysis with the request id derived from the action's idempotency key,
  so a retry can never charge twice).
Revoking samples, rejecting the profile, resets, cloud-memory and extraction settings stay on their native pages.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import Receipt, action, common, query

ID = {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:-]{1,120}$"}
ROUTE = {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:/*@+-]{1,120}$"}
PURPOSE = {"type": "string", "enum": ["analysis", "generation"]}
INVALIDATES = ["voice_sources", "voice_profile_state", "voice_preferences", "voice_learning_status", "voice_consent"]


def _samples(state):
    return [s for s in state.get("sources") or [] if isinstance(s, dict) and s.get("kind") == "voice_sample"]


def _sample(state, source_id):
    sample = next((s for s in _samples(state) if s.get("id") == source_id), None)
    if sample is None:
        raise AlphaError("That voice sample is not in this workspace.", 404, code="not_found")
    return sample


def _sample_row(s):
    return {"sourceId": s.get("id"), "ref": common.ref("voice_sample", s.get("id")), "title": str(s.get("title") or "")[:200] or None, "platform": s.get("platform"),
            "language": s.get("language"), "label": s.get("label"), "origin": s.get("voiceOrigin"), "active": bool(s.get("active")), "selected": bool(s.get("selected")),
            "revision": s.get("revision"), "characters": len(s.get("text") or ""), "excerpt": common.excerpt(s.get("text"), 160),
            "useGrants": [{"purpose": g.get("purpose"), "route": g.get("route")} for g in s.get("useGrants") or [] if isinstance(g, dict)][:12],
            "grantRevision": s.get("grantRevision"), "partialCoverage": bool(s.get("partialCoverage")), "publishedAt": s.get("publishedAt"),
            "retainedAt": common.iso(s.get("retainedAt")), "permalink": s.get("permalink") if isinstance(s.get("permalink"), str) and s["permalink"].startswith("https://") else None,
            "revoked": not s.get("active")}


def voice_sources(dctx, inputs, cursor):
    from ... import voice_sources as samples_service
    samples = _samples(dctx.state)
    if inputs.get("activeOnly", True):
        samples = [s for s in samples if s.get("active")]
    samples.sort(key=lambda s: (-(s.get("retainedAt") or 0), s.get("id")))
    eligibility = None
    if inputs.get("purpose") and inputs.get("route"):
        projection = samples_service.project(dctx.state, [s["id"] for s in samples][:50], inputs["purpose"], inputs["route"])
        eligibility = {"purpose": inputs["purpose"], "route": inputs["route"], "allowed": [x["id"] for x in projection["samples"]],
                       "excluded": [{"sourceId": x["id"], "reason": x["reason"]} for x in projection["excluded"]], "digest": projection["digest"],
                       "rule": "a sample counts only when active, selected and granted for this exact purpose and route"}
    page, next_cursor, start = common.paginate("voice_sources", inputs, cursor, samples, default=50)
    rows = [_sample_row(s) for s in page]
    return ui_contracts.query_result("available" if samples else "empty", {"samples": rows, "offset": start, "eligibility": eligibility}, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(samples), total=len(samples),
                                     note="Writing samples are style evidence only, never approved facts.")


def _dimensions(profile):
    out = []
    for d in profile.get("dimensions") or []:
        if isinstance(d, dict):
            out.append({"id": d.get("id"), "observation": str(d.get("observation") or "")[:240], "evidenceLevel": d.get("evidenceLevel"),
                        "support": len(d.get("support") or []), "counterEvidence": len(d.get("counterEvidence") or []),
                        "quotes": [{"sourceId": q.get("sourceId"), "text": str(q.get("text") or "")[:240]} for q in d.get("quotes") or [] if isinstance(q, dict)][:3]})
    return out[:30]


def voice_profile_state(dctx, _inputs, _cursor):
    from ... import memory
    state = dctx.state
    speaker = state.get("speaker") or {}
    active = memory.active_profile(state)
    profile = (active or {}).get("profile") or {}
    provisional = speaker.get("provisional") if isinstance(speaker.get("provisional"), dict) else None
    variants = [v for v in state.get("variants") or [] if isinstance(v, dict) and not v.get("rejected")]
    jobs = [j for j in (state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict)]
    on_voice = {v.get("id") for v in variants if v.get("voiceRevision")}
    bound = [j for j in jobs if j.get("state") in ("approved", "scheduled", "claimed") and (j.get("manifest") or {}).get("variantId") in on_voice]
    data = {"approved": ({"revision": active.get("revision"), "approvedAt": common.iso(active.get("approvedAt")) if isinstance(active.get("approvedAt"), (int, float)) else active.get("approvedAt"),
                          "reason": active.get("reason"), "stale": bool(active.get("stale") or profile.get("status") == "stale"), "staleReason": active.get("staleReason"),
                          "tone": profile.get("tone"), "observations": [str(o)[:240] for o in profile.get("observations") or []][:12],
                          "dimensions": _dimensions(profile), "unknowns": [str(u)[:200] for u in profile.get("unknowns") or []][:8]} if active else None),
            "proposed": ({"status": provisional.get("status"), "method": provisional.get("analysisMethod"), "route": provisional.get("analysisRoute"),
                          "model": provisional.get("analysisModel"), "proposedAt": common.iso(provisional.get("proposedAt")) if isinstance(provisional.get("proposedAt"), (int, float)) else provisional.get("proposedAt"),
                          "proposalKey": ui_contracts.sha256_text(ui_contracts.canonical_json({"at": provisional.get("proposedAt"), "digest": provisional.get("analysisDigest") or provisional.get("contextDigest")}))[:24],
                          "coverage": provisional.get("coverage"), "dimensions": _dimensions(provisional), "unknowns": [str(u)[:200] for u in provisional.get("unknowns") or []][:8],
                          "sources": len(provisional.get("sourceBindings") or provisional.get("evidenceSourceIds") or [])} if provisional else None),
            "revisions": len(speaker.get("revisions") or []),
            "derived": {"draftsOnVoice": len(on_voice), "scheduledPostsOnVoice": len(bound),
                        "rule": "drafts that carry a voice revision, and approved posts waiting on them; approving a new profile marks those drafts for review"},
            "note": "No model was trained. A proposed profile is not in effect until an owner approves it.", "href": "/app/brand"}
    state_name = "available" if (active or provisional) else "empty"
    return ui_contracts.query_result(state_name, data, as_of=common.iso(dctx.now), source_refs=[common.ref("voice_profile", str((active or {}).get("revision")))] if active else [],
                                     revision=str(dctx.revision), known=1 if (active or provisional) else 0, total=1)


def voice_preferences(dctx, _inputs, _cursor):
    learning = getattr(dctx.service, "learning", None)
    if learning is None:
        return ui_contracts.query_result("unavailable", as_of=common.iso(dctx.now), note="Learned preferences aren't available here.", warnings=["learning_unavailable"])
    from postriff_alpha import learning as alpha_learning
    data = learning.proposals(dctx.service.repository, dctx.workspace_id, None)
    learned = []
    for item in alpha_learning.summary(dctx.state).get("items") or []:
        if isinstance(item, dict):
            learned.append({k: item.get(k) for k in ("id", "type", "ruleKey", "polarity", "scope", "statement", "applyWhen", "evidenceState", "evidenceSummary", "source", "status")}
                           | {"since": common.iso(item.get("since")) if isinstance(item.get("since"), (int, float)) else item.get("since")})
    out = {"pending": data.get("pending") or [], "recent": data.get("recent") or [], "recentTotal": data.get("recentTotal"), "learned": learned[:100],
           "versions": len(data.get("versions") or []), "settings": {k: (data.get("learning") or {}).get(k) for k in ("enabled", "teamEdits", "cloudExtraction", "revision", "extractor")},
           "stats": data.get("stats"), "rule": "learned = in effect (paused items are listed, not applied); proposed = waiting for an owner's decision"}
    return ui_contracts.query_result("available" if (out["pending"] or learned) else "empty", out, as_of=common.iso(dctx.now), revision=str(dctx.revision),
                                     source_refs=[common.ref("memory_proposal", p.get("id")) for p in out["pending"]][:50], known=len(out["pending"]) + len(learned),
                                     total=len(out["pending"]) + len(learned))


def voice_consent(dctx, _inputs, _cursor):
    from ... import media_consent, memory, research
    state = dctx.state
    settings = state.get("learning") if isinstance(state.get("learning"), dict) else {}
    learning = getattr(dctx.service, "learning", None)
    samples = [s for s in _samples(state) if s.get("active")]
    data = {"cloudMemory": memory.egress_summary(state),
            "samples": {"total": len(samples), "grantedForAnalysis": sum(1 for s in samples if "analysis" in (s.get("purposeGrants") or [])),
                        "grantedForGeneration": sum(1 for s in samples if "generation" in (s.get("purposeGrants") or []))},
            "learning": {"enabled": settings.get("enabled"), "teamEdits": settings.get("teamEdits"), "cloudExtraction": settings.get("cloudExtraction"),
                         "modelExtractionAllowed": bool(learning.model_allowed(state)) if learning is not None else None},
            "media": {"cloud": bool(media_consent.decision(state).get("cloud"))}, "webResearch": research.consent_summary(state),
            "owner": dctx.member.allows("owner"),
            "rule": "each layer is a separate owner decision: per-sample use grants, cloud memory, cloud preference extraction, photo processing, web research",
            "href": "/app/memory"}
    return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), revision=str(dctx.revision), known=5, total=5)


def voice_learning_status(dctx, _inputs, _cursor):
    cur = dctx.cur
    try:
        cur.execute("SAVEPOINT ui_learning_status")
        cur.execute("SELECT count(*) FROM public.pr_learning_events WHERE workspace_id=%s AND consumed_by IS NULL", (dctx.workspace_id,))
        unconsumed = int(cur.fetchone()[0])
        cur.execute("SELECT count(*), extract(epoch from max(created_at)) FROM public.pr_memory_proposals WHERE workspace_id=%s AND status='pending'", (dctx.workspace_id,))
        pending, newest = cur.fetchone()
        cur.execute("RELEASE SAVEPOINT ui_learning_status")
    except Exception:  # noqa: BLE001 — learning tables absent here: say so, never zero
        cur.execute("ROLLBACK TO SAVEPOINT ui_learning_status")
        return ui_contracts.query_result("unavailable", as_of=common.iso(dctx.now), note="Learning records aren't available here.", warnings=["learning_tables_unavailable"])
    learning = getattr(dctx.service, "learning", None)
    extractor = learning.summary(dctx.state).get("extractor") if learning is not None else None
    settings = dctx.state.get("learning") if isinstance(dctx.state.get("learning"), dict) else {}
    data = {"enabled": settings.get("enabled"), "eventsWaiting": unconsumed, "pendingProposals": int(pending or 0),
            "newestProposalAt": common.iso(float(newest)) if newest is not None else None, "extractor": extractor,
            "lastRun": None, "lastRunNote": "Rafii does not record when preference extraction last ran; this status is derived from waiting events and proposals.",
            "rule": "derived: events not yet read by the nightly extraction, and proposals waiting for an owner. No model is trained."}
    return ui_contracts.query_result("partial", data, as_of=common.iso(dctx.now), known=2, total=3, note="The last extraction time isn't recorded.")


# --- actions ------------------------------------------------------------------------------------------------------------
def _mutate(dctx, name, payload, *, audit=None):
    """The original workspace command path (permission class, step-up flag, audit and effects), on this transaction."""
    return dctx.service.repository.mutate(dctx.workspace_id, None, dctx.revision, name, payload)


def _done(dctx, source_id, message, verified, invalidates=INVALIDATES):
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"voice_sample:{source_id}", changed_refs=[common.ref("voice_sample", source_id)],
                   invalidation_keys=list(invalidates), next_context={"references": [{"type": "voice_sample", "id": source_id}]}, message=message)


def select_confirm(dctx, inputs):
    sample = _sample(dctx.state, inputs["sourceId"])
    if not sample.get("active"):
        raise AlphaError("This voice sample was revoked.", 409, code="sample_revoked")
    verb = "Use" if inputs["selected"] else "Stop using"
    return {"title": f"{verb} this sample", "summary": [f"{verb} this writing sample in voice analysis."], "target": str(sample.get("title") or "Writing sample")[:200],
            "timeZone": None, "cost": None}


def select_execute(dctx, inputs, _key):
    select_confirm(dctx, inputs)
    _mutate(dctx, "voice_sample_select", {"sourceId": inputs["sourceId"], "selected": inputs["selected"]})
    saved = _sample(dctx.refresh_state(), inputs["sourceId"])
    return _done(dctx, saved["id"], "Updated.", saved.get("selected") is inputs["selected"])


def exclude_confirm(dctx, inputs):
    sample = _sample(dctx.state, inputs["sourceId"])
    return {"title": "Exclude this sample", "summary": ["Exclude this writing sample from analysis. It stays retained; revoking is on the Brand page."],
            "target": str(sample.get("title") or "Writing sample")[:200], "timeZone": None, "cost": None}


def exclude_execute(dctx, inputs, _key):
    exclude_confirm(dctx, inputs)
    _mutate(dctx, "voice_sample_exclude", {"sourceId": inputs["sourceId"]})
    saved = _sample(dctx.refresh_state(), inputs["sourceId"])
    return _done(dctx, saved["id"], "Excluded from analysis.", saved.get("selected") is False)


def _eligible(dctx, ids, purpose, route):
    from ... import voice_sources as samples_service
    projection = samples_service.project(dctx.state, ids, purpose, route)
    if projection["excluded"]:
        reasons = sorted({x["reason"] for x in projection["excluded"]})
        raise AlphaError("Some samples can't be used for this: " + ", ".join(reasons) + ".", 409, code="samples_not_eligible")
    return projection


def analyze_local_confirm(dctx, inputs):
    _eligible(dctx, inputs["sourceIds"], "analysis", "local-rules")
    provisional = (dctx.state.get("speaker") or {}).get("provisional")
    lines = [f"Analyse {len(inputs['sourceIds'])} sample(s) with Rafii's local rules (no AI model, no cost).",
             "The result is a proposed profile; it is not in effect until an owner approves it."]
    if provisional:
        lines.append("It replaces the profile currently waiting for approval.")
    return {"title": "Analyse my voice (local)", "summary": lines, "target": "Voice profile", "timeZone": None, "cost": "No AI cost"}


def analyze_local_execute(dctx, inputs, _key):
    analyze_local_confirm(dctx, inputs)
    _mutate(dctx, "voice_profile_analyze", {"sourceIds": list(inputs["sourceIds"]), "route": "local-rules"})
    provisional = (dctx.refresh_state().get("speaker") or {}).get("provisional") or {}
    verified = provisional.get("status") == "proposed" and provisional.get("analysisMethod") == "local-rules"
    return Receipt(outcome="applied", verified=verified, receipt_ref="voice_profile:proposed", changed_refs=["voice_profile:proposed"], invalidation_keys=INVALIDATES,
                   next_context={"profile": {"status": provisional.get("status"), "method": provisional.get("analysisMethod")}},
                   message="A proposed profile is ready for an owner's review. No model was trained." if verified else "The analysis ran but its result couldn't be confirmed; reload.")


def import_confirm(dctx, inputs):
    if inputs.get("confirmed") is not True:
        raise AlphaError("Confirm that you wrote these samples and want Rafii to keep them.", 400, code="ui_input")
    return {"title": "Keep writing samples", "summary": [f"Keep {len(inputs['text'])} characters of pasted writing as a private voice sample in this workspace.",
                                                          "It is style evidence only (never facts) and is used only where you grant it."],
            "target": str(inputs.get("title") or "Pasted sample")[:200], "timeZone": None, "cost": "No AI cost"}


def import_execute(dctx, inputs, _key):
    import_confirm(dctx, inputs)
    payload = {"format": "pasted", "text": inputs["text"], **{k: inputs[k] for k in ("title", "platform", "language", "label") if inputs.get(k)}}
    before = {s.get("id") for s in _samples(dctx.state)}
    _mutate(dctx, "voice_samples_import", payload)
    after = _samples(dctx.refresh_state())
    created = [s for s in after if s.get("id") not in before]
    sample = created[0] if created else None
    message = "Kept as a writing sample." if sample else "This exact text was already kept; nothing changed."
    return Receipt(outcome="applied", verified=True, receipt_ref=f"voice_sample:{sample['id']}" if sample else None,
                   changed_refs=[common.ref("voice_sample", sample["id"])] if sample else [], invalidation_keys=INVALIDATES,
                   next_context={"references": [{"type": "voice_sample", "id": sample["id"]}]} if sample else {}, message=message)


def _grants(sample, purpose, route):
    current = [(g.get("purpose"), g.get("route")) for g in sample.get("useGrants") or [] if isinstance(g, dict)]
    return [{"purpose": p, "route": r} for p, r in sorted(set(current) | {(purpose, route)})]


def grant_confirm(dctx, inputs):
    sample = _sample(dctx.state, inputs["sourceId"])
    if not sample.get("active"):
        raise AlphaError("This voice sample was revoked.", 409, code="sample_revoked")
    grants = _grants(sample, inputs["purpose"], inputs["route"])
    use = "AI voice analysis" if inputs["purpose"] == "analysis" else "writing new drafts"
    return {"title": "Allow this sample's use", "summary": [f"Allow this sample for {use} on the writer route {inputs['route']}.",
                                                             "Its text may then be sent to that provider for that purpose only.",
                                                             "All grants after this change: " + "; ".join(f"{g['purpose']} → {g['route']}" for g in grants)[:600]],
            "target": str(sample.get("title") or "Writing sample")[:200], "timeZone": None, "cost": None}


def grant_execute(dctx, inputs, _key):
    grant_confirm(dctx, inputs)
    sample = _sample(dctx.state, inputs["sourceId"])
    grants = _grants(sample, inputs["purpose"], inputs["route"])
    _mutate(dctx, "voice_sample_grant", {"sourceId": inputs["sourceId"], "grants": grants, "confirmed": True})
    saved = _sample(dctx.refresh_state(), inputs["sourceId"])
    verified = {"purpose": inputs["purpose"], "route": inputs["route"]} in [{"purpose": g.get("purpose"), "route": g.get("route")} for g in saved.get("useGrants") or []]
    return _done(dctx, saved["id"], "Allowed for that exact use.", verified)


def _proposal_key(provisional):
    return ui_contracts.sha256_text(ui_contracts.canonical_json({"at": provisional.get("proposedAt"), "digest": provisional.get("analysisDigest") or provisional.get("contextDigest")}))[:24]


def approve_confirm(dctx, inputs):
    provisional = (dctx.state.get("speaker") or {}).get("provisional")
    if not isinstance(provisional, dict) or provisional.get("status") != "proposed":
        raise AlphaError("There is no proposed profile to approve.", 409, code="no_proposal")
    if _proposal_key(provisional) != inputs["proposalKey"]:
        raise AlphaError("The proposed profile changed since you opened it. Reload before approving.", 409, code="proposal_stale")
    variants = [v for v in dctx.state.get("variants") or [] if isinstance(v, dict) and not v.get("rejected")]
    jobs = [j for j in (dctx.state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict) and j.get("state") in ("approved", "scheduled", "claimed")]
    lines = ["Approve this proposed voice profile; it becomes the voice Rafii writes in.",
             f"{len(variants)} draft(s) will be marked for review, and {len(jobs)} approved post(s) bound to the old voice may be held until reviewed."]
    return {"title": "Approve voice profile", "summary": lines, "target": "Voice profile", "timeZone": None, "cost": None}


def approve_execute(dctx, inputs, _key):
    approve_confirm(dctx, inputs)
    before = (dctx.state.get("speaker") or {}).get("activeRevision")
    _mutate(dctx, "profile_decide", {"decision": "approve"})
    speaker = dctx.refresh_state().get("speaker") or {}
    verified = speaker.get("activeRevision") not in (None, before) and not speaker.get("provisional")
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"voice_profile:{speaker.get('activeRevision')}", changed_refs=["voice_profile:active"],
                   invalidation_keys=INVALIDATES + ["drafts_list", "queue_status"], next_context={"profile": {"activeRevision": speaker.get("activeRevision")}},
                   message="Approved. Drafts on the old voice need review." if verified else "The approval couldn't be confirmed by re-reading; reload.")


def preference_confirm(dctx, inputs):
    from ...learning_service import load_proposal
    proposal = load_proposal(dctx.cur, dctx.workspace_id, inputs["proposalId"])
    if proposal.get("status") != "pending":
        raise AlphaError("This proposal was already decided.", 409, code="proposal_closed")
    words = {"remember": "Remember this preference", "edit": "Remember it with your wording", "dismiss": "Dismiss it (quiet for 90 days)",
             "post_only": "Keep it for that post only"}
    statement = (proposal.get("body") or {}).get("statement")
    lines = [words[inputs["decision"]] + ".", f"Preference: {str(inputs.get('statement') or statement or '')[:240]}"]
    return {"title": "Decide learned preference", "summary": lines, "target": "Learned preferences", "timeZone": None, "cost": None}


def preference_execute(dctx, inputs, _key):
    preference_confirm(dctx, inputs)
    learning = getattr(dctx.service, "learning", None)
    if learning is None:
        raise AlphaError("Learned preferences aren't available here.", 503, code="learning_unavailable")
    if inputs["decision"] == "edit" and not (inputs.get("statement") or "").strip():
        raise AlphaError("Write the preference in your words.", 400, code="ui_input")
    learning.decide(dctx.service.repository, dctx.workspace_id, None, dctx.revision, inputs["proposalId"], inputs["decision"], inputs.get("statement"))
    from ...learning_service import load_proposal
    stored = load_proposal(dctx.cur, dctx.workspace_id, inputs["proposalId"])
    expected = {"remember": "remembered", "edit": "edited", "dismiss": "dismissed", "post_only": "post_only"}[inputs["decision"]]
    verified = stored.get("status") == expected
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"memory_proposal:{inputs['proposalId']}", changed_refs=[common.ref("memory_proposal", inputs["proposalId"])],
                   invalidation_keys=INVALIDATES, next_context={"proposal": {"proposalId": inputs["proposalId"], "status": stored.get("status")}},
                   message="Decided." if verified else "The decision couldn't be confirmed by re-reading; reload.")


# --- AI voice analysis (two-phase: the paid call never runs under the workspace lock) ------------------------------------
def _ai_estimate(dctx, inputs):
    runtime = dctx.service.ideas._select_runtime(inputs["model"])
    if not callable(getattr(runtime, "analyze_voice", None)) or not callable(getattr(runtime, "quote_voice_analysis", None)):
        raise AlphaError("This writer does not offer AI voice analysis. Choose a managed analysis model.", 409, code="no_analysis_model")
    projection = _eligible(dctx, inputs["sourceIds"], "analysis", inputs["route"])
    return int(runtime.quote_voice_analysis(projection, inputs["model"], inputs.get("instructions") or "")), projection


def analyze_ai_confirm(dctx, inputs):
    if not dctx.member.allows("owner"):
        raise AlphaError("Only an owner can run AI voice analysis.", 403, code="tool_forbidden")
    estimate, projection = _ai_estimate(dctx, inputs)
    dollars = f"${estimate / 1_000_000:.2f}" if estimate else "an amount Rafii can't estimate"
    return {"title": "Analyse my voice with AI", "summary": [f"Send {len(projection['samples'])} granted sample(s) to {inputs['model']} for voice analysis.",
                                                              "The result is a proposed profile, not in effect until an owner approves it. No model is trained.",
                                                              "If the workspace changes during the analysis, the cost is still charged and the profile isn't saved."],
            "target": "Voice profile", "timeZone": None, "cost": f"Up to {dollars} of writing credit, settled after the analysis"}


def analyze_ai_execute_outside(runtime, token, auth, inputs, key):
    """Phase 2 (outside every lock): the original HostedVoiceAnalysis path with the person's own session. The request id is
    the action's idempotency key, so the ledger refuses a second reservation for it (no double charge)."""
    service = runtime.service
    revision = service.repository.get(auth.workspace_id, token)["revision"]
    payload = {"sourceIds": list(inputs["sourceIds"]), "route": inputs["route"], "model": inputs["model"], "instructions": inputs.get("instructions") or "",
               "confirmed": True, "requestId": key}
    service.mutate(auth.workspace_id, token, revision, "voice_profile_analyze", payload)
    provisional = (service.repository.get(auth.workspace_id, token)["state"].get("speaker") or {}).get("provisional") or {}
    verified = provisional.get("analysisMethod") == "ai" and provisional.get("status") == "proposed"
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"ledger:voice:{key}", changed_refs=["voice_profile:proposed"], invalidation_keys=INVALIDATES,
                   next_context={"profile": {"status": provisional.get("status"), "method": provisional.get("analysisMethod")}},
                   message="A proposed profile is ready for an owner's review. No model was trained." if verified else "The analysis finished but its result couldn't be confirmed; reload.")


def analyze_ai_reconcile(runtime, token, auth, inputs, key):
    """After a lost reply: read the ledger reservation `voice:<key>` and the proposed profile; never call the model again."""
    service = runtime.service
    with service.repository.transaction(token, auth.workspace_id) as (cur, row, _principal):
        cur.execute("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s ORDER BY created_at DESC LIMIT 1",
                    (auth.workspace_id, "voice:" + key))
        found = cur.fetchone()
        import json
        state = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
    provisional = (state.get("speaker") or {}).get("provisional") or {}
    if found is None:
        return Receipt(outcome="failed", message="The analysis never started. Nothing was charged; you can try again.")
    if provisional.get("analysisMethod") == "ai" and provisional.get("status") == "proposed":
        return Receipt(outcome="applied", verified=True, receipt_ref=f"ledger:voice:{key}", changed_refs=["voice_profile:proposed"], invalidation_keys=INVALIDATES,
                       message="A proposed profile is ready for an owner's review.")
    return Receipt(outcome="pending", message="The analysis was submitted; its result isn't confirmed yet. Reload the profile and usage before trying again.")


query("voice_sources", "J04", "Writing samples (no full text): origin, platform, language, label, selected/active, exact use grants and, for a purpose + writer route, which "
      "samples are eligible and why the others are not.",
      {"purpose": PURPOSE, "route": ROUTE, "activeOnly": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
      voice_sources, page=50, refresh=60)
query("voice_profile_state", "J04", "The approved voice profile vs the proposed one: method, evidence level per dimension, unknowns, and how many drafts/posts an approval affects.",
      {}, voice_profile_state, refresh=60, tool="voice.profile")
query("voice_preferences", "J04", "Learned preferences in effect vs proposals waiting for an owner, with evidence and scope.", {}, voice_preferences, refresh=60, tool="memory.summary")
query("voice_consent", "J04", "Every consent layer separately: per-sample grants, cloud memory, cloud preference extraction, photo processing and web research.",
      {}, voice_consent, refresh=60, tool="privacy.egress_state", also=("J07",))
query("voice_learning_status", "J04", "What Rafii's learning is doing now, derived from waiting events and proposals (no training exists).", {}, voice_learning_status, refresh=60)
action("voice_sample_select", "J04", "Use in analysis", "Includes or leaves out this writing sample in voice analysis.", "MUTATE_REVERSIBLE", "edit",
       {"sourceId": ID, "selected": {"type": "boolean"}}, select_confirm, select_execute, required=("sourceId", "selected"), requires_confirmation=False, dedupe="natural")
action("voice_sample_exclude", "J04", "Exclude", "Excludes this writing sample from analysis (it stays retained).", "MUTATE_REVERSIBLE", "edit", {"sourceId": ID},
       exclude_confirm, exclude_execute, required=("sourceId",), requires_confirmation=False, dedupe="natural")
action("voice_profile_analyze_local", "J04", "Analyse locally", "Analyses the selected samples with Rafii's local rules (no AI, no cost) into a proposed profile.",
       "MUTATE_REVERSIBLE", "edit", {"sourceIds": {"type": "array", "minItems": 1, "maxItems": 50, "items": ID, "uniqueItems": True}},
       analyze_local_confirm, analyze_local_execute, required=("sourceIds",), dedupe="intent")
action("voice_samples_import", "J04", "Keep sample", "Keeps pasted writing as a private voice sample (style evidence only).", "MUTATE_REVERSIBLE", "edit",
       {"text": {"type": "string", "minLength": 20, "maxLength": 8000}, "title": {"type": "string", "maxLength": 160}, "platform": {"type": "string", "maxLength": 40},
        "language": {"type": "string", "maxLength": 20}, "label": {"type": "string", "enum": ["representative", "outdated", "sponsored", "guest", "ai_generated"]},
        "confirmed": {"type": "boolean"}}, import_confirm, import_execute, required=("text", "confirmed"), dedupe="natural")
action("voice_sample_grant", "J04", "Allow use", "Allows this sample for one exact purpose and writer route (owner decision).", "MUTATE_REVERSIBLE", "owner",
       {"sourceId": ID, "purpose": PURPOSE, "route": ROUTE}, grant_confirm, grant_execute, required=("sourceId", "purpose", "route"), dedupe="natural")
action("voice_profile_approve", "J04", "Approve profile", "Approves the proposed voice profile you are looking at (owner decision). Drafts on the old voice need review.",
       "MUTATE_REVERSIBLE", "owner", {"proposalKey": {"type": "string", "maxLength": 24, "pattern": r"^[0-9a-f]{24}$"}}, approve_confirm, approve_execute,
       required=("proposalKey",), dedupe="cas")
action("preference_decide", "J04", "Decide", "Remembers, edits, dismisses or keeps-for-one-post a learned preference proposal (owner decision).", "MUTATE_REVERSIBLE", "owner",
       {"proposalId": {"type": "string", "maxLength": 40, "pattern": r"^[0-9a-fA-F-]{36}$"}, "decision": {"type": "string", "enum": ["remember", "edit", "dismiss", "post_only"]},
        "statement": {"type": "string", "maxLength": 400}}, preference_confirm, preference_execute, required=("proposalId", "decision"), dedupe="cas")
action("voice_profile_analyze_ai", "J04", "Analyse with AI", "Sends the granted samples to a managed model for a proposed profile (owner decision; uses writing credit).",
       "MUTATE_REVERSIBLE", "owner", {"sourceIds": {"type": "array", "minItems": 1, "maxItems": 50, "items": ID, "uniqueItems": True}, "route": ROUTE,
                                      "model": {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:/@+-]{1,120}$"}, "instructions": {"type": "string", "maxLength": 1500}},
       analyze_ai_confirm, analyze_ai_execute_outside, required=("sourceIds", "route", "model"), two_phase=True, dedupe="intent")
ACTION_RECONCILERS = {"voice_profile_analyze_ai": analyze_ai_reconcile}

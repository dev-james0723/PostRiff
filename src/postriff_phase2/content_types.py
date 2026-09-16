"""Workspace-specific content types, formats, interviews, and private templates."""
import copy
import hashlib
import re

from postriff_alpha.domain import AlphaError, clean, uid
from .contracts import digest

# A tutorial teaches a method the person actually uses. Without approved facts the steps must come
# from the person's own message: two ordered steps (a numbered or bulleted line each, or sequence words).
_STEP_LINE = re.compile(r"^\s*(?:\d{1,2}[.)、．]|[-*•·]|[①-⑳]|step\s*\d+|第[一二三四五六七八九十\d]+步)", re.I | re.M)
_SEQUENCE = re.compile(r"\b(?:first|second|third|then|next|after that|finally|lastly)\b|首先|其次|然後|然后|接著|接着|之後|之后|最後|最后|第[一二三四五六七八九十\d]+步", re.I)
TUTORIAL_NEEDS = "the steps you actually teach, in order (one per line in your message) or an approved source that describes the method"


def tutorial_steps_supplied(text):
    text = text if isinstance(text, str) else ""
    return len(_STEP_LINE.findall(text)) >= 2 or len(_SEQUENCE.findall(text)) >= 2


def missing_tutorial_input(content_type_id, idea, context):
    """What a how-to still needs before it can be written honestly; "" when nothing is missing."""
    if content_type_id != "tutorial_how_to":
        return ""
    if any(source.get("facts") for source in (context or {}).get("sources", [])) or tutorial_steps_supplied(idea):
        return ""
    return TUTORIAL_NEEDS


CATALOG_VERSION = "postriff-content-catalog-2026.09.14.1"
CREATOR_PACK_ID = "pack.creator"
CREATOR_PACK_VERSION = "1.0.0"
TYPE_ID = re.compile(r"(?:postriff|pack\.[a-z0-9_]+|workspace_[a-z0-9]+):[a-z0-9_]+")
FORMATS = (
    ("short_text", "Short text"), ("image_caption", "Image + caption"),
    ("quote_card", "Quote card"), ("carousel", "Carousel"),
    ("article", "Article"), ("short_video", "Short video"),
    ("long_video", "Long video"), ("story", "Story"),
    ("community_post", "Community Post"), ("poll", "Poll"),
)
FORMAT_IDS = {item[0] for item in FORMATS}
TEMPLATE_OVERRIDE_KEYS = {"pillarIds", "formatId", "languageIds", "accountIds", "toneProfileId", "sourcePolicy", "ctaPolicy", "visualDirection"}


def _type(identifier, label, description, formats, checks, *, origin="postriff", platforms=(), inputs=("idea",), structure=("Context", "Main point", "Next step"), skills=("postriff.editorial-craft",)):
    return {
        "id": identifier, "version": "1.0.0", "origin": origin,
        "originId": CREATOR_PACK_ID if origin == "starter_pack" else None,
        "visibility": "catalog", "label": label, "shortLabel": label.split(" /")[0],
        "description": description, "defaultStructure": list(structure),
        "recommendedFormatIds": list(formats), "recommendedPlatformIds": list(platforms),
        "requiredInputKinds": list(inputs), "optionalInputKinds": ["source", "media"],
        "skillRouteIds": list(skills), "preflightRuleIds": list(checks), "status": "active",
    }


CORE_TYPES = (
    _type("postriff:update", "Update", "Share what changed and what it means.", ("short_text", "image_caption"), ("result_state",)),
    _type("postriff:teach", "Practical tip", "Teach one useful method or lesson.", ("short_text", "carousel", "short_video"), ("tested_steps", "prerequisites")),
    _type("postriff:story", "Story", "Tell a concrete moment and its meaning.", ("image_caption", "short_text", "short_video"), ("privacy", "invented_experience")),
    _type("postriff:promote", "Offer or announcement", "Explain an available offer, event, or release.", ("image_caption", "short_text"), ("availability", "claim_evidence")),
    _type("postriff:engage", "Question or discussion", "Invite a specific, useful response.", ("community_post", "poll", "short_text"), ("community_context", "engagement_bait")),
)


CREATOR_ROWS = (
    ("quick_thought_quote", "Quick thought / Original quote", "Express one concise observation, tension, question, realization, or owned line.", ("short_text", "quote_card", "image_caption", "community_post"), ("quote_attribution", "unsupported_claim")),
    ("personal_reflection", "Personal reflection / Life moment", "Tell a true personal moment without pretending complete resolution.", ("image_caption", "short_text", "short_video", "story"), ("privacy", "invented_experience", "named_person")),
    ("article_news_commentary", "Article/news summary + my view", "Explain what happened, why it matters, and your view or open question.", ("short_text", "article", "carousel", "image_caption"), ("source_freshness", "citation", "source_pov_separation", "quote_length")),
    ("deep_point_of_view", "Deep point of view", "Develop a defensible thesis with evidence and counterpoint.", ("article", "carousel", "long_video"), ("thesis", "evidence", "counterpoint", "invented_authority")),
    ("building_in_public", "Building in public", "Share progress, decisions, experiments, failures, and tradeoffs truthfully.", ("image_caption", "carousel", "short_video", "short_text"), ("preview_vs_release", "confidential_data", "result_evidence")),
    ("tutorial_how_to", "Tutorial / How-to / Use case", "Teach a tested workflow, feature, practice, or repeatable method.", ("carousel", "short_video", "long_video", "article"), ("tested_steps", "prerequisites", "risk_cost")),
    ("product_feature_launch", "Product / Feature launch", "Explain why a release exists, what is available, and the evidence.", ("image_caption", "carousel", "short_video", "short_text"), ("availability", "claim_evidence", "pricing_link")),
    ("music_performance_teaching", "Music / Performance / Teaching", "Share practice, interpretation, performance, teaching, or musical meaning.", ("short_video", "long_video", "image_caption", "article"), ("music_rights", "credits", "student_privacy")),
    ("youtube_derivative", "YouTube extension", "Extend a long video into native entry points and follow-up discussion.", ("community_post", "short_video", "quote_card", "short_text"), ("source_video_state", "timestamp_fidelity", "clip_rights")),
    ("community_q_and_a", "Community Q&A / Discussion", "Answer a real question, seek feedback, or open a useful discussion.", ("community_post", "poll", "short_text", "short_video"), ("community_context", "community_rules", "advice_risk")),
    ("event_service_institutional_update", "Event / Service / Institutional update", "Communicate a confirmed event, service, collaboration, or institutional update.", ("image_caption", "short_text", "story", "community_post"), ("event_datetime", "place_link", "availability", "collaborator_approval")),
)
CREATOR_TYPES = tuple(_type(f"pack.creator:{identifier}", label, description, formats, checks, origin="starter_pack") for identifier, label, description, formats, checks in CREATOR_ROWS)


ROLE_PACKS = {
    "restaurant": ("Menu spotlight", "Chef story", "Customer moment", "Event or promotion", "Behind the scenes"),
    "realtor": ("Listing story", "Neighborhood guide", "Market explanation", "Client education", "Success story"),
    "nonprofit": ("Impact story", "Campaign update", "Volunteer spotlight", "Event", "Transparent progress report"),
    "coach": ("Teaching insight", "Client-safe case pattern", "Exercise", "Personal reflection", "Offer explanation"),
    "saas": ("Product education", "Use case", "Release update", "Customer story", "Building in public"),
    "musician": ("Practice note", "Performance moment", "Teaching insight", "Repertoire story", "Event update"),
}


INTERVIEW_QUESTIONS = (
    ("recurringJob", "What kind of post do you want to make repeatedly?"),
    ("audienceOutcome", "Who is it for, and what should they understand, feel, or do?"),
    ("sourceMaterial", "What source material do you usually start with?"),
    ("requiredElements", "What must every post include?"),
    ("avoid", "What should it avoid or never claim?"),
    ("formatsDestinations", "Which formats and destinations are common?"),
    ("evidenceApproval", "What evidence, approval, or media is required before publishing?"),
)


def ensure_content_state(state):
    if "contentSystem" not in state:
        state["contentSystem"] = {
            "schema": "postriff.content-system.v1", "catalogVersion": CATALOG_VERSION,
            "installedPacks": [], "workspaceTypes": [], "templates": [],
            "recommendationContext": {"role": "general", "goals": [], "audience": "", "sources": [], "channels": []},
            "suggestions": [], "interview": None, "proposal": None,
            "selection": {"contentTypeId": "unclassified", "contentTypeVersion": "legacy", "formatId": None, "pillarIds": [], "changedAt": None},
            "migration": {"legacyDraftsPreserved": len(state.get("variants", [])), "classification": "unclassified"},
        }
    system = state["contentSystem"]
    for item in system.get("workspaceTypes", []):
        if item.get("skillRouteIds") == ["james-au-content-craft"]:
            item["skillRouteIds"] = ["postriff.editorial-craft"]
    proposal = system.get("proposal")
    if proposal and proposal.get("skillRouteIds") == ["james-au-content-craft"]:
        proposal["skillRouteIds"] = ["postriff.editorial-craft"]
    for variant in state.get("variants", []):
        variant.setdefault("contentTypeId", "unclassified")
        variant.setdefault("contentTypeVersion", "legacy")
        variant.setdefault("formatId", None)
        if variant.get("contentSkillRouteIds") == ["james-au-content-craft"]:
            variant["contentSkillRouteIds"] = ["postriff.editorial-craft"]
    return system


def _role_types(role):
    labels = ROLE_PACKS.get(role, ROLE_PACKS["saas"] if role in ("founder", "software") else ("Update", "Practical tip", "Story"))
    return [
        _type(f"pack.{role}:{re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')}", label, f"A {role} starter for {label.lower()}.", ("short_text", "image_caption"), ("source_truth",), origin="starter_pack")
        for label in labels
    ]


def public_packs():
    return [
        {"id": CREATOR_PACK_ID, "version": CREATOR_PACK_VERSION, "label": "Creator Starter Pack", "entryCount": 11, "installedByDefault": False},
        *({"id": f"pack.{role}", "version": "1.0.0", "label": role.title() + " Starter Pack", "entryCount": len(labels), "installedByDefault": False} for role, labels in ROLE_PACKS.items()),
    ]


def formats():
    return [{"id": identifier, "version": "1.0.0", "label": label} for identifier, label in FORMATS]


def public_catalog():
    """Safe product metadata; no workspace configuration or private instructions."""
    return [copy.deepcopy(item) for item in (*CORE_TYPES, *CREATOR_TYPES)]


def resolve_catalog(state):
    system = ensure_content_state(state)
    items = [copy.deepcopy(item) for item in CORE_TYPES]
    for installed in system["installedPacks"]:
        pack_id = installed["id"]
        if pack_id == CREATOR_PACK_ID:
            items.extend(copy.deepcopy(CREATOR_TYPES))
        elif pack_id.startswith("pack."):
            items.extend(_role_types(pack_id[5:]))
    items.extend(copy.deepcopy(system["workspaceTypes"]))
    unique = {}
    for item in items:
        if not TYPE_ID.fullmatch(item["id"]):
            raise AlphaError("A content type has an invalid namespace.", 500)
        key = (item["id"], item["version"])
        if key in unique and unique[key] != item:
            raise AlphaError("A content type namespace collision was detected.", 409)
        unique[key] = item
    origin_rank = {"postriff": 0, "starter_pack": 1, "workspace": 2}
    return sorted(unique.values(), key=lambda item: (origin_rank[item["origin"]], item["label"].casefold(), item["id"], item["version"]))


def recommendations(state):
    system = ensure_content_state(state)
    role = system["recommendationContext"].get("role", "general").strip().lower()
    available = resolve_catalog(state)
    if role in ROLE_PACKS and not any(item["id"] == f"pack.{role}" for item in system["installedPacks"]):
        candidates = _role_types(role)
    else:
        preferred = {"founder": ("postriff:update", "postriff:teach", "postriff:story", "postriff:engage"), "general": ("postriff:update", "postriff:teach", "postriff:story")}.get(role, ())
        candidates = [item for identifier in preferred for item in available if item["id"] == identifier] or available[:4]
    return [{"contentTypeId": item["id"], "version": item["version"], "label": item["label"], "reason": f"Recommended for the {role or 'general'} workspace context."} for item in candidates[:4]]


def definition(state, content_type_id, version=None):
    found = [item for item in resolve_catalog(state) if item["id"] == content_type_id and (version is None or item["version"] == version)]
    if not found:
        raise AlphaError("Choose a content type available in this workspace.", 404)
    return found[-1]


def content_preflight(state):
    from .source_policy import publication_issues  # local import: source_policy has no content dependency
    system = ensure_content_state(state)
    selected = system["selection"]
    policy_checks = publication_issues(state, list(state.get("brief", {}).get("sourceIds", [])))
    if selected["contentTypeId"] == "unclassified":
        return [{"severity": "warning", "ruleId": "unclassified", "message": "This legacy draft has no content type. Review a suggestion before reusing it as a template."}] + policy_checks
    item = definition(state, selected["contentTypeId"], selected["contentTypeVersion"])
    approved_facts = [fact for source in state.get("sources", []) if source.get("active") for fact in source.get("facts", []) if fact.get("approved")]
    checks = list(policy_checks)
    if "quote_attribution" in item["preflightRuleIds"] and not approved_facts:
        checks.append({"severity": "blocker", "ruleId": "quote_attribution", "message": "Use your own confirmed line or add a clearly attributed approved source."})
    if "source_pov_separation" in item["preflightRuleIds"]:
        if not approved_facts:
            checks.append({"severity": "blocker", "ruleId": "source_required", "message": "Add and review the article or news source."})
        if not state.get("brandHub", {}).get("purpose"):
            checks.append({"severity": "warning", "ruleId": "viewpoint_required", "message": "Keep the source summary separate from your own view or open question."})
    return checks


def _proposal(answers, path, base=None):
    recurring = clean(answers.get("recurringJob", base.get("label", "A recurring post") if base else "A recurring post"), 120)
    label = recurring[:60].strip().title()
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "custom_type"
    required = [value for key in ("sourceMaterial", "requiredElements") if (value := answers.get(key))]
    avoid = answers.get("avoid", "Unsupported claims")
    return {
        "id": uid(), "path": path, "status": "needs_review", "name": label,
        "slug": slug, "purpose": clean(answers.get("audienceOutcome", base.get("description", "A reusable editorial job.") if base else "A reusable editorial job."), 400),
        "whenToUse": recurring, "whenNotToUse": avoid, "requiredInputs": required or ["A confirmed idea"],
        "optionalInputs": ["Source", "Media"], "defaultStructure": ["Context", "Main point", "Evidence or example", "Next step"],
        "recommendedFormatIds": list((base or {}).get("recommendedFormatIds", ["short_text", "image_caption"]))[:4],
        "recommendedPlatformIds": list((base or {}).get("recommendedPlatformIds", []))[:8],
        "skillRouteIds": list((base or {}).get("skillRouteIds", ["postriff.editorial-craft"])),
        "preflightRuleIds": list((base or {}).get("preflightRuleIds", ["source_truth", "unsupported_claim"])),
        "fixtureExamples": [f"Synthetic example: {label} for a fictional neighborhood workshop.", f"Synthetic example: {label} for a fictional small studio."],
        "answersDigest": digest(answers), "tested": False,
    }


def _template_overrides(value):
    if not isinstance(value, dict) or set(value) - TEMPLATE_OVERRIDE_KEYS:
        raise AlphaError("Template overrides contain unsupported fields.")
    if value.get("formatId") and value["formatId"] not in FORMAT_IDS:
        raise AlphaError("Template format is unavailable.")
    return copy.deepcopy(value)


def _template_version(template, clock, actor):
    return {
        "revision": template["revision"], "name": template["name"],
        "description": template["description"], "visibility": template["visibility"],
        "contentTypeId": template["contentTypeId"],
        "contentTypeVersion": template["contentTypeVersion"],
        "overrides": copy.deepcopy(template["overrides"]), "archived": template["archived"],
        "recordedAt": clock, "recordedBy": actor,
    }


def export_template(state, template_id, actor):
    system = ensure_content_state(state)
    template = next((item for item in system["templates"] if item["id"] == template_id and (item["ownerUserId"] == actor or item["visibility"] == "workspace")), None)
    if not template:
        raise AlphaError("This template is unavailable.", 404)
    item = definition(state, template["contentTypeId"], template["contentTypeVersion"])
    return {
        "schema": "postriff.post-template-export.v1", "catalogVersion": CATALOG_VERSION,
        "template": {key: copy.deepcopy(template[key]) for key in ("id", "name", "description", "contentTypeId", "contentTypeVersion", "visibility", "overrides", "revision", "archived")},
        "contentType": {key: copy.deepcopy(item[key]) for key in ("id", "version", "origin", "originId", "label", "description", "defaultStructure", "recommendedFormatIds", "recommendedPlatformIds", "requiredInputKinds", "optionalInputKinds", "skillRouteIds", "preflightRuleIds")},
    }


def apply_content_action(state, action, payload, actor, clock):
    system = ensure_content_state(state)
    if action == "content_context":
        role = clean(payload.get("role", "general"), 40).lower()
        if role not in {*ROLE_PACKS, "general", "founder", "software"}:
            raise AlphaError("Choose a supported starter context.")
        system["recommendationContext"] = {"role": role, "goals": list(payload.get("goals", []))[:6], "audience": clean(payload.get("audience", ""), 300), "sources": list(payload.get("sources", []))[:6], "channels": list(payload.get("channels", []))[:10]}
        system["suggestions"] = recommendations(state)
    elif action == "content_install_pack":
        pack_id = payload.get("packId")
        pack = next((item for item in public_packs() if item["id"] == pack_id), None)
        if not pack or payload.get("version") != pack["version"]:
            raise AlphaError("Choose an exact released starter pack version.")
        if not any(item["id"] == pack_id for item in system["installedPacks"]):
            system["installedPacks"].append({"id": pack_id, "version": pack["version"], "installedAt": clock, "installedBy": actor})
    elif action == "content_select":
        item = definition(state, payload.get("contentTypeId"), payload.get("contentTypeVersion"))
        format_id = payload.get("formatId", system["selection"].get("formatId") or item["recommendedFormatIds"][0])
        if format_id not in FORMAT_IDS:
            raise AlphaError("Choose one of the ten supported format families.")
        previous = copy.deepcopy(system["selection"])
        system["selection"].update({"contentTypeId": item["id"], "contentTypeVersion": item["version"], "formatId": format_id, "changedAt": clock})
        if previous["contentTypeId"] != item["id"]:
            system["selection"]["transformation"] = {"from": previous["contentTypeId"], "to": item["id"], "preservedSourceIds": list(state["brief"]["sourceIds"]), "preservedVariantIds": [variant["id"] for variant in state["variants"] if variant.get("customized")]}
    elif action == "content_format":
        if payload.get("formatId") not in FORMAT_IDS:
            raise AlphaError("Choose one of the ten supported format families.")
        system["selection"]["formatId"] = payload["formatId"]
        system["selection"]["changedAt"] = clock
    elif action == "content_suggest":
        system["suggestions"] = recommendations(state)[:3]
    elif action == "content_interview_start":
        path = payload.get("path")
        if path not in ("guided", "example", "adapt", "manual"):
            raise AlphaError("Choose a supported type-creation path.")
        base = definition(state, payload.get("baseTypeId")) if path == "adapt" else None
        system["interview"] = {"id": uid(), "path": path, "index": 0, "answers": {}, "base": base, "status": "active", "createdAt": clock}
        system["proposal"] = None
        if path in ("example", "adapt", "manual"):
            sample = clean(payload.get("example", ""), 6000) if path == "example" else ""
            manual = payload.get("definition", {}) if path == "manual" else {}
            if path == "example" and not sample:
                raise AlphaError("Add an example post to analyze locally.")
            answers = {"recurringJob": manual.get("name", base["label"] + " adaptation" if base else "Pattern from example"), "audienceOutcome": manual.get("purpose", base["description"] if base else "Reuse the visible structure without copying private wording."), "sourceMaterial": "User supplied example" if sample else manual.get("sourceMaterial", "")}
            system["proposal"] = _proposal(answers, path, base)
            system["interview"]["status"] = "proposal_ready"
    elif action == "content_interview_answer":
        interview = system.get("interview")
        if not interview or interview["status"] != "active":
            raise AlphaError("Start a guided type interview first.")
        key, _ = INTERVIEW_QUESTIONS[interview["index"]]
        if payload.get("questionKey") != key:
            raise AlphaError("Answer the current interview question only.", 409)
        answer = clean(payload.get("answer", ""), 1000)
        if not answer:
            raise AlphaError("Add an answer before continuing.")
        interview["answers"][key] = answer
        interview["index"] += 1
        if interview["index"] >= len(INTERVIEW_QUESTIONS) or payload.get("finish") is True and interview["index"] >= 3:
            interview["status"] = "proposal_ready"
            system["proposal"] = _proposal(interview["answers"], interview["path"], interview.get("base"))
    elif action == "content_proposal_edit":
        proposal = system.get("proposal")
        if not proposal or proposal["status"] != "needs_review":
            raise AlphaError("Create a reviewable proposal first.")
        for key, limit in (("name", 80), ("purpose", 500), ("whenToUse", 500), ("whenNotToUse", 500)):
            if key in payload:
                proposal[key] = clean(payload[key], limit)
        if "recommendedFormatIds" in payload:
            values = payload["recommendedFormatIds"]
            if not isinstance(values, list) or not values or any(value not in FORMAT_IDS for value in values):
                raise AlphaError("Proposal formats must use the released format catalog.")
            proposal["recommendedFormatIds"] = list(dict.fromkeys(values))
    elif action == "content_proposal_test":
        proposal = system.get("proposal")
        if not proposal or payload.get("idea") is None:
            raise AlphaError("Review a proposal and supply a synthetic test idea.")
        proposal["tested"] = True
        proposal["testResult"] = {"execution": "synthetic", "idea": clean(payload["idea"], 500), "withType": proposal["fixtureExamples"][0], "startBlank": "Synthetic blank draft for comparison."}
    elif action == "content_proposal_save":
        proposal = system.get("proposal")
        if not proposal or proposal["status"] != "needs_review" or payload.get("confirmed") is not True or payload.get("proposalDigest") != digest(proposal):
            raise AlphaError("Review and confirm this exact content-type proposal.", 409)
        namespace = "workspace_" + re.sub(r"[^a-z0-9]", "", state["workspace"]["id"].lower())[:12]
        identifier = f"{namespace}:{proposal['slug']}"
        if any(item["id"] == identifier for item in system["workspaceTypes"]):
            identifier += "_" + hashlib.sha256(proposal["id"].encode()).hexdigest()[:6]
        item = _type(identifier, proposal["name"], proposal["purpose"], proposal["recommendedFormatIds"], proposal["preflightRuleIds"], origin="workspace", platforms=proposal["recommendedPlatformIds"], inputs=tuple(proposal["requiredInputs"]), structure=tuple(proposal["defaultStructure"]), skills=tuple(proposal["skillRouteIds"]))
        item.update({"workspaceId": state["workspace"]["id"], "visibility": "workspace", "createdBy": actor, "version": "1.0.0", "createdAt": clock})
        system["workspaceTypes"].append(item)
        proposal["status"] = "saved"
        proposal["savedTypeId"] = identifier
    elif action == "template_create":
        item = definition(state, payload.get("contentTypeId"), payload.get("contentTypeVersion"))
        visibility = payload.get("visibility", "private")
        if visibility not in ("private", "workspace") or visibility == "workspace" and state.get("membership", {}).get("role") not in ("owner", "editor"):
            raise AlphaError("Workspace sharing requires edit permission.", 403)
        overrides = _template_overrides(payload.get("overrides", {}))
        template = {"id": uid(), "workspaceId": state["workspace"]["id"], "name": clean(payload.get("name", ""), 80), "description": clean(payload.get("description", ""), 300), "contentTypeId": item["id"], "contentTypeVersion": item["version"], "ownerUserId": actor, "visibility": visibility, "overrides": overrides, "revision": 1, "archived": False, "createdAt": clock, "versions": []}
        if not template["name"]:
            raise AlphaError("Name the private template.")
        template["versions"].append(_template_version(template, clock, actor))
        system["templates"].append(template)
    elif action == "template_edit":
        template = next((item for item in system["templates"] if item["id"] == payload.get("templateId")), None)
        if not template or template["ownerUserId"] != actor:
            raise AlphaError("This private template is unavailable.", 404)
        if payload.get("expectedTemplateRevision") != template["revision"]:
            raise AlphaError("This template changed. Reload it before editing.", 409)
        if "name" in payload:
            template["name"] = clean(payload["name"], 80)
            if not template["name"]:
                raise AlphaError("Name the private template.")
        if "description" in payload:
            template["description"] = clean(payload["description"], 300)
        if "visibility" in payload:
            if payload["visibility"] not in ("private", "workspace") or payload["visibility"] == "workspace" and state.get("membership", {}).get("role") not in ("owner", "editor"):
                raise AlphaError("Workspace sharing requires edit permission.", 403)
            template["visibility"] = payload["visibility"]
        if "overrides" in payload:
            template["overrides"] = _template_overrides(payload["overrides"])
        template["revision"] += 1
        template.setdefault("versions", []).append(_template_version(template, clock, actor))
    elif action == "template_archive":
        template = next((item for item in system["templates"] if item["id"] == payload.get("templateId")), None)
        if not template or template["ownerUserId"] != actor:
            raise AlphaError("This private template is unavailable.", 404)
        if payload.get("expectedTemplateRevision") not in (None, template["revision"]):
            raise AlphaError("This template changed. Reload it before archiving.", 409)
        template["archived"] = bool(payload.get("archived", True)); template["revision"] += 1
        template.setdefault("versions", []).append(_template_version(template, clock, actor))
    elif action == "template_duplicate":
        template = next((item for item in system["templates"] if item["id"] == payload.get("templateId") and (item["ownerUserId"] == actor or item["visibility"] == "workspace")), None)
        if not template:
            raise AlphaError("This template is unavailable.", 404)
        duplicate = copy.deepcopy(template); duplicate.update({"id": uid(), "name": clean(payload.get("name", template["name"] + " copy"), 80), "ownerUserId": actor, "visibility": "private", "revision": 1, "archived": False, "createdAt": clock, "versions": []})
        duplicate["versions"].append(_template_version(duplicate, clock, actor))
        system["templates"].append(duplicate)
    else:
        return False
    return True


def interview_view(state):
    system = ensure_content_state(state)
    interview = system.get("interview")
    if not interview or interview["status"] != "active":
        return None
    key, question = INTERVIEW_QUESTIONS[interview["index"]]
    return {"id": interview["id"], "path": interview["path"], "questionKey": key, "question": question, "index": interview["index"], "maximum": len(INTERVIEW_QUESTIONS)}


def projection(state):
    system = ensure_content_state(state)
    proposal = copy.deepcopy(system.get("proposal"))
    if proposal:
        proposal["proposalDigest"] = digest(system["proposal"])
    return {
        "catalogVersion": CATALOG_VERSION, "formats": formats(), "packs": public_packs(),
        "catalog": resolve_catalog(state), "suggestions": system.get("suggestions") or recommendations(state),
        "selection": copy.deepcopy(system["selection"]), "interview": interview_view(state),
        "proposal": proposal, "templates": copy.deepcopy(system["templates"]),
        "preflight": content_preflight(state), "installedPacks": copy.deepcopy(system["installedPacks"]),
    }

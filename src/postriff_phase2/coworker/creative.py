"""Creative Agent planning (adaptive coworker spec §12 Creative Agent; architecture lock C1).

Deterministic creative planning that needs no model: which asset each platform needs (aspect ratio, pixel size,
safe area), what kind of source fits (real photo, screenshot, frame, generated editorial, designed graphic,
composite), carousel and thumbnail structure, CTA hierarchy, alt-text requirement and a brand-fit checklist from
the workspace's Brand Brain. The visual-craft knowledge (`postriff-social-graphics`) is compiled for the Creative
specialist and travels with any image-generation or edit request as its method, recorded in provenance.

Generation, editing and vision critique use the existing asset pipeline (private staging, `add_asset`, audit,
usage ledger) and the runtime's non-destructive lineage; originals are never overwritten (`lineage_record`).
"""
from __future__ import annotations

import re

from .. import skill_compiler

# Current-format planning defaults (platform guidance changes; the adapter's live constraint record wins).
PLATFORM_SPECS = {
    ("Instagram", "image"): {"ratio": "4:5", "size": [1080, 1350], "safe": {"top": 0.06, "bottom": 0.10, "sides": 0.05}},
    ("Instagram", "carousel"): {"ratio": "4:5", "size": [1080, 1350], "safe": {"top": 0.06, "bottom": 0.10, "sides": 0.05}, "maxSlides": 20},
    ("Instagram", "story"): {"ratio": "9:16", "size": [1080, 1920], "safe": {"top": 0.14, "bottom": 0.20, "sides": 0.06}},
    ("Instagram", "short_video"): {"ratio": "9:16", "size": [1080, 1920], "safe": {"top": 0.14, "bottom": 0.22, "sides": 0.06}, "cover": [1080, 1920]},
    ("LinkedIn", "image"): {"ratio": "1.91:1", "size": [1200, 627], "safe": {"top": 0.05, "bottom": 0.05, "sides": 0.05}},
    ("LinkedIn", "carousel"): {"ratio": "4:5", "size": [1080, 1350], "safe": {"top": 0.06, "bottom": 0.08, "sides": 0.06}, "document": True, "maxSlides": 20},
    ("X", "image"): {"ratio": "16:9", "size": [1600, 900], "safe": {"top": 0.05, "bottom": 0.05, "sides": 0.05}},
    ("Threads", "image"): {"ratio": "4:5", "size": [1080, 1350], "safe": {"top": 0.05, "bottom": 0.08, "sides": 0.05}},
    ("Threads", "carousel"): {"ratio": "4:5", "size": [1080, 1350], "safe": {"top": 0.05, "bottom": 0.08, "sides": 0.05}, "maxSlides": 20},
    ("Facebook", "image"): {"ratio": "4:5", "size": [1080, 1350], "safe": {"top": 0.05, "bottom": 0.08, "sides": 0.05}},
    ("YouTube", "thumbnail"): {"ratio": "16:9", "size": [1280, 720], "safe": {"top": 0.06, "bottom": 0.16, "sides": 0.06}, "note": "The duration badge covers the bottom-right corner."},
    ("TikTok", "short_video"): {"ratio": "9:16", "size": [1080, 1920], "safe": {"top": 0.12, "bottom": 0.25, "sides": 0.08}, "cover": [1080, 1920]},
    ("Pinterest", "image"): {"ratio": "2:3", "size": [1000, 1500], "safe": {"top": 0.05, "bottom": 0.08, "sides": 0.05}},
    ("Xiaohongshu", "image"): {"ratio": "3:4", "size": [1242, 1660], "safe": {"top": 0.06, "bottom": 0.10, "sides": 0.05}},
    ("Xiaohongshu", "carousel"): {"ratio": "3:4", "size": [1242, 1660], "safe": {"top": 0.06, "bottom": 0.10, "sides": 0.05}, "maxSlides": 18},
}
SOURCE_TYPES = ("real_photo", "screenshot", "video_frame", "generated_editorial", "designed_graphic", "composite")
VISUAL_FORMATS = {"image", "carousel", "story", "short_video", "thumbnail", "image_caption", "quote_card", "long_video"}
_NUMBERS = re.compile(r"\d[\d,.%]*")


def spec_for(platform, fmt):
    fmt = {"image_caption": "image", "quote_card": "image", "long_video": "thumbnail"}.get(fmt, fmt)
    return PLATFORM_SPECS.get((platform, fmt)) or PLATFORM_SPECS.get((platform, "image")) or {"ratio": "1:1", "size": [1080, 1080], "safe": {"top": 0.05, "bottom": 0.05, "sides": 0.05}}


def choose_source_type(brief, assets):
    """Documentary claims need real material; a concept may be generated, and says so."""
    text = " ".join(str(brief.get(k) or "") for k in ("message", "claim", "angle")).lower()
    if any(a.get("kind") == "screenshot" for a in assets) and any(w in text for w in ("app", "feature", "screen", "product", "update", "dashboard")):
        return "screenshot", "A product claim is shown with the real screen."
    if any(a.get("kind") in ("photo", "image") for a in assets) and brief.get("documentary", True):
        return "real_photo", "A real, approved photo documents what the post says."
    if brief.get("data"):
        return "designed_graphic", "Numbers are shown as a designed graphic from the approved figures."
    return "generated_editorial", "No approved real material exists; a generated editorial image is labelled as generated and never presented as evidence."


def cta_hierarchy(copy_text, cta):
    """One primary action; a second competing call is flagged."""
    calls = re.findall(r"\b(sign up|subscribe|buy|book|register|download|learn more|read more|join|follow|shop|try|order|link in bio)\b", copy_text or "", re.I)
    unique = list(dict.fromkeys(c.lower() for c in calls))
    findings = []
    if len(unique) > 1:
        findings.append({"code": "competing_ctas", "detail": f"{len(unique)} different calls to action: {', '.join(unique)}. Keep one primary action."})
    if cta and unique and cta.lower() not in unique:
        findings.append({"code": "cta_mismatch", "detail": f"The brief's action is “{cta}”, the copy asks for “{unique[0]}”."})
    return {"primary": cta or (unique[0] if unique else None), "findings": findings}


def brand_fit(state, brief):
    """A checklist from the Brand Brain; each item says what it checked and why it matters."""
    hub = state.get("brandHub") or {}
    checks = []
    if hub.get("audience"):
        checks.append({"check": "audience", "expect": hub["audience"], "why": "The image should read as made for this audience."})
    if hub.get("purpose"):
        checks.append({"check": "purpose", "expect": hub["purpose"], "why": "The visual message supports the brand's stated purpose."})
    boundaries = [l for l in hub.get("layers") or [] if isinstance(l, dict) and l.get("kind") in ("boundary", "avoid")]
    for boundary in boundaries[:5]:
        checks.append({"check": "boundary", "expect": boundary.get("text") or boundary.get("label"), "why": "Stored brand boundary."})
    if not checks:
        checks.append({"check": "brand_brain", "expect": None, "why": "No Brand Brain is stored, so brand fit cannot be checked beyond the brief."})
    return checks


def alt_text_requirement(brief, platform):
    message = (brief.get("message") or "").strip()
    return {"required": True, "maxChars": 1000 if platform != "X" else 1000, "mustDescribe": ["the subject", "any text shown in the image", "the one message it carries"],
            "draft": (f"Image: {message[:180]}" if message else None), "note": "Alt text describes what is visible; it adds no claim the image does not show."}


def plan_assets(state, brief, platforms, fmt="image", assets=None, task=None):
    """Creative briefs for each platform plus the compiled visual-craft method for the Creative specialist or an
    image request. Deterministic apart from what the brief says; nothing is generated here."""
    assets = assets or []
    compiled = skill_compiler.compile({"agent": "creative", "intent": "creative_brief", "platforms": list(platforms), **(task or {})})
    source_type, why = choose_source_type(brief, assets)
    plans = []
    for platform in platforms:
        spec = spec_for(platform, fmt)
        plan = {"platform": platform, "format": fmt, "ratio": spec["ratio"], "size": spec["size"], "safeArea": spec["safe"], "sourceType": source_type, "sourceWhy": why,
                "message": brief.get("message"), "cta": cta_hierarchy(brief.get("copy") or "", brief.get("cta")), "altText": alt_text_requirement(brief, platform),
                "brandFit": brand_fit(state, brief), "generatedLabel": source_type == "generated_editorial"}
        if fmt == "carousel":
            slides = max(3, min(int(brief.get("slides") or 6), spec.get("maxSlides", 10)))
            plan["carousel"] = {"slides": slides, "structure": ["hook: the one promise"] + [f"point {i}" for i in range(1, slides - 1)] + ["close: the single action"],
                                "rule": "One idea per slide; the first slide works alone in the feed."}
        if fmt in ("thumbnail", "long_video", "short_video"):
            plan["thumbnail"] = {"textMaxWords": 5, "rule": "The cover adds to the title rather than repeating it; keep text out of the bottom safe area."}
        if spec.get("note"):
            plan["note"] = spec["note"]
        plans.append(plan)
    numbers_in_copy = sorted(set(_NUMBERS.findall(brief.get("copy") or "")))
    return {"schema": "rafii.creative-plan.v1", "plans": plans, "instructions": compiled["text"], "compiled": {**{k: compiled[k] for k in ("registryRelease", "selections", "omitted")}, "methodApplied": False,
                                                                                    "note": "The plan is deterministic; the method is attached for an image route and is applied only if one is called."},
            "numbersToVerify": numbers_in_copy, "missingAssets": [] if assets or source_type == "generated_editorial" else [{"need": source_type, "why": why}]}


def lineage_record(*, operation, parent_asset_id=None, source_asset_ids=(), model=None, route=None, prompt_summary=None, run_id=None, trace_id=None):
    """The non-destructive lineage every generated or edited asset carries (runtime ADR-I1)."""
    if operation not in ("generate", "edit", "variant", "resize", "crop", "adapt"):
        raise ValueError(operation)
    if operation in ("edit", "variant", "resize", "crop", "adapt") and not parent_asset_id:
        raise ValueError("an edit keeps its parent; originals are never overwritten")
    return {"operation": operation, "parentAssetId": parent_asset_id, "sourceAssetIds": list(source_asset_ids), "model": model, "route": route,
            "promptSummary": (prompt_summary or "")[:200] or None, "runId": run_id, "traceId": trace_id}


def image_request(state, plan_bundle, platform, *, prompt, parent_asset_id=None):
    """The request a generation/edit route receives: the brief's plan, the compiled method (as method, not data),
    the user's prompt as data. Recorded so provenance shows which visual-craft version shaped the image."""
    plan = next(p for p in plan_bundle["plans"] if p["platform"] == platform)
    return {"method": plan_bundle["instructions"], "plan": {k: plan[k] for k in ("ratio", "size", "safeArea", "sourceType", "message", "generatedLabel")},
            "prompt": {"kind": "USER_INSTRUCTION", "text": (prompt or "")[:2000]}, "parentAssetId": parent_asset_id,
            "provenance": skill_compiler.provenance_for_run({"selections": plan_bundle["compiled"]["selections"]}, state=state)}

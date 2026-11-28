"""Creative decisions for a Rafii video project. Input footage is evidence, never composition material."""
from __future__ import annotations

import copy
import math
import re
import uuid

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError

from . import memory
from .video_uploads import ASSET_ID

VIDEO_ROUTE = "cloud:vertex:veo-3.1-fast-generate-001"
MAX_SCENES = 32
MAX_DURATION_MS = 90000
MIN_BEAT_MS = 42
MAX_BEAT_MS = 8000


def text_field(value, label, limit, *, empty=False):
    if (not isinstance(value, str) or len(value.strip()) > limit or (not empty and not value.strip())
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise AlphaError(f"Enter a valid {label} of up to {limit} characters.")
    return value.strip()


def validate_brief(body):
    required = {"requestId", "title", "brief", "referenceAssetId", "rightsConfirmed", "aspectRatio", "platform"}
    if not isinstance(body, dict) or not required <= body.keys() <= required | {"referenceLink", "speechTimingLanguage"}:
        raise AlphaError("Supply a campaign brief and choose whether to analyze a reference.")
    if body["rightsConfirmed"] is not (body["referenceAssetId"] is not None):
        raise AlphaError("Confirm that you may analyze the selected reference.")
    if body["referenceAssetId"] is not None and (not isinstance(body["referenceAssetId"], str) or not ASSET_ID.fullmatch(body["referenceAssetId"])):
        raise AlphaError("Choose a video from this workspace's Library.")
    if not isinstance(body["requestId"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", body["requestId"]):
        raise AlphaError("A unique project request is required.")
    if body["platform"] not in ("Instagram", "TikTok", "YouTube") or body["aspectRatio"] not in ("9:16", "16:9", "1:1"):
        raise AlphaError("Choose a supported video platform and aspect ratio.")
    result = {**body, "title": text_field(body["title"], "title", 120), "brief": text_field(body["brief"], "brief", 1200)}
    if "referenceLink" in body:
        from .creative_video_performance import youtube_video_id
        if not body["referenceAssetId"]:
            raise AlphaError("Confirm the resolved Library video before using its link.")
        result["referenceLink"] = "https://youtu.be/" + youtube_video_id(body["referenceLink"])
    if "speechTimingLanguage" in body and (not body["referenceAssetId"] or body["speechTimingLanguage"] not in ("en", "zh", "auto")):
        raise AlphaError("Choose a reference video and a supported speech language.")
    return result


def brief_analysis():
    return {"source": "brief", "durationMs": 12000, "scenes": [], "unavailable": ["No reference media supplied."]}


def project_context(state, platform, *, route=VIDEO_ROUTE, local=False):
    """Pin the canonical consent, active voice and scoped, approved learning used to adapt this brief."""
    cloud = memory.egress(state).get("cloud") is True
    destinations = [{"platform": platform}]
    shared, receipt = memory.prepare_writer(state, "cloud" if cloud and not local else "local", route, destinations=destinations)
    hub = state.get("brandHub") or {}
    voice = memory.active_profile(state) or {}
    approved = receipt["effectiveVoiceMode"] == "approved"
    approved_items = {item["id"]: item for item in learning.active_items(state)
                      if item.get("confirmedBy") or item.get("evidenceState") == "user_confirmed"}
    preferences = [approved_items[key] for key in shared["learned"]["used"] if key in approved_items]
    context = {
        "brand": hub.get("speaker") or (state.get("speaker") or {}).get("label") or "",
        "subject": hub.get("subject") or "", "audience": hub.get("audience") or "", "purpose": hub.get("purpose") or "",
        "tone": (voice.get("profile") or {}).get("tone", "") if approved else "",
        "voiceRevision": voice.get("revision") if approved else None,
        "preferences": [item["statement"] for item in preferences], "preferenceIds": [item["id"] for item in preferences],
        "styleRevision": learning.revision(state), "cloudAllowed": cloud,
    }
    return context, receipt


def _beats(analysis):
    duration = analysis["durationMs"]
    if not MIN_BEAT_MS <= duration <= MAX_DURATION_MS:
        raise AlphaError("Use a reference between one frame and 90 seconds.")
    starts = [0]
    for shot in analysis["scenes"][1:]:
        at = shot["startMs"]
        if at - starts[-1] >= MIN_BEAT_MS and duration - at >= MIN_BEAT_MS:
            starts.append(at)
    starts.append(duration)
    # Preserve the measured cut inventory. Combine the closest beats only in the editable plan.
    while sum(math.ceil((b-a) / MAX_BEAT_MS) for a, b in zip(starts, starts[1:])) > MAX_SCENES:
        i = min(range(1, len(starts)-1), key=lambda j: starts[j+1] - starts[j-1])
        starts.pop(i)
    for a, b in zip(starts, starts[1:]):
        count = math.ceil((b-a) / MAX_BEAT_MS)
        for i in range(count):
            yield a + (b-a)*i//count, a + (b-a)*(i+1)//count


def adapt(brief, analysis, context):
    measured = analysis["scenes"]
    spans = list(_beats(analysis)) if measured else [(0, 4000), (4000, 8000), (8000, 12000)]
    subject = context["subject"][:90] or "the subject of the brief"
    brand = context["brand"][:70] or "your brand"
    audience = f" for {context['audience'][:70]}" if context["audience"] else ""
    objective = " ".join(brief["brief"].split())
    if len(objective) > 142:
        objective = objective[:140].rsplit(" ", 1)[0] + "…"
    shots = []
    overlays = (analysis.get("overlaySignals") or {}).get("frames", [])
    rhythm = analysis.get("measured", {}).get("audioRhythm", {})
    audio_onsets = rhythm.get("onsetMs", []) if rhythm.get("state") == "measured" else []
    for i, (start, end) in enumerate(spans):
        source_index = next((n for n, shot in enumerate(measured) if shot["startMs"] <= start < shot["endMs"]), None)
        source = measured[source_index] if source_index is not None else {}
        pace = source.get("pacing", "steady")
        if i == 0:
            purpose = "Opening hook"
            action = f"Open on {subject} in use. Start the action immediately."
            caption = f"Meet {subject}." if context["subject"] else (context["brand"] or "A closer look")
        elif i == len(spans)-1:
            purpose = "Call to action"
            action = f"Finish on {subject}. Leave room for the campaign's invitation."
            caption = f"Explore more from {brand}." if context["brand"] else "Take a closer look."
        else:
            purpose = "Demonstration"
            action = f"Show step {i} from a new angle with {subject} in motion."
            caption = "A closer look." if i == 1 else ""
        lighting = ""
        luma = source.get("measurements", {}).get("meanLuma")
        if luma is not None:
            lighting = " Use a bright setting." if luma >= 0.65 else " Try low-key lighting." if luma <= 0.35 else " Use balanced lighting."
        styling = f" Set a {context['tone'][:45]} tone." if context.get("tone") else ""
        if context.get("preferences"):
            styling += " " + context["preferences"][i % len(context["preferences"])][:85]
        when = end if i > 0 and i == len(spans)-1 else start
        overlay = min((f for f in overlays if f["sceneIndex"] == source_index),
                      key=lambda f: abs(f["timeMs"] - when), default={})
        clues = overlay.get("interpretiveClues", [])
        if i == 0 and "question" in clues:
            action = f"Frame an original opening question about {subject}. Show it in use."
        if i == len(spans)-1 and "call_to_action" in clues and i > 0:
            action = f"Show {subject} at the end of the action. Leave space for your own written invitation."
        first_onset = next((at for at in audio_onsets if start <= at < end), None)
        if first_onset is not None:
            action += f" Time a visual accent {(first_onset - start) / 1000:.2f} s into this shot."
        direction = f"{action} Campaign brief — {objective.rstrip('.')}. Create an original {pace}-paced shot for {brand}{audience}.{lighting}{styling}"
        shots.append({"sceneId": f"scene-{i+1}", "take": uuid.uuid4().hex, "purpose": purpose,
                      "direction": direction[:600], "caption": caption[:120], "durationMs": end-start, "sourceStartMs": start,
                      "sourceEndMs": end, "evidence": source.get("interpretation", ""), "clipId": None})
    return shots


def edit_scenes(scenes, patches, reference_id, resolve, *, order=None, generated_clips=None):
    if not isinstance(patches, list) or len(patches) > MAX_SCENES or (not patches and order is None):
        raise AlphaError("Choose the scenes to edit.")
    result = copy.deepcopy(scenes)
    by_id = {scene["sceneId"]: scene for scene in result}
    if order is not None:
        if (not isinstance(order, list) or len(order) != len(result) or
                not all(isinstance(key, str) for key in order) or set(order) != set(by_id)):
            raise AlphaError("Include every scene from this revision exactly once in the timeline.")
        result = [by_id[key] for key in order]
    seen = set()
    for patch in patches:
        if (not isinstance(patch, dict) or not set(patch) <= {"sceneId", "direction", "caption", "durationMs", "clipId", "clipRightsConfirmed", "retake", "trimStartMs"}
                or not isinstance(patch.get("sceneId"), str) or patch["sceneId"] not in by_id or patch["sceneId"] in seen):
            raise AlphaError("Choose each scene from this revision once.")
        scene = by_id[patch["sceneId"]]
        seen.add(patch["sceneId"])
        old_direction = scene["direction"]
        old_duration = scene["durationMs"]
        old_clip = scene["clipId"]
        if "retake" in patch:
            if patch["retake"] is not True or "clipId" in patch:
                raise AlphaError("Choose a replacement take or a Library clip for this scene.")
            scene["clipId"] = None
        if "direction" in patch:
            scene["direction"] = text_field(patch["direction"], "shot direction", 600)
        if "caption" in patch:
            scene["caption"] = text_field(patch["caption"], "caption", 120, empty=True)
        if "durationMs" in patch:
            value = patch["durationMs"]
            if type(value) is not int or not MIN_BEAT_MS <= value <= MAX_BEAT_MS:
                raise AlphaError("Choose a scene duration between 0.042 and 8 seconds.")
            scene["durationMs"] = value
        if "clipId" in patch:
            clip_id = patch["clipId"]
            if clip_id is not None and (patch.get("clipRightsConfirmed") is not True or not isinstance(clip_id, str)
                                        or not ASSET_ID.fullmatch(clip_id) or clip_id == reference_id):
                raise AlphaError("Choose a different, authorized original clip from this Library.")
            scene["clipId"] = clip_id
        trim = patch.get("trimStartMs", scene.get("trimStartMs", 0))
        if type(trim) is not int or not 0 <= trim < MAX_DURATION_MS:
            raise AlphaError("Choose a source start from zero to 89.999 seconds.")
        replace_take = (old_direction != scene["direction"] or old_clip != scene["clipId"]
                        or patch.get("retake") or ("clipId" in patch and patch["clipId"] is None))
        if not replace_take and not scene["clipId"] and old_duration < scene["durationMs"]:
            generated_id = (generated_clips or {}).get(scene["take"])
            replace_take = not generated_id or resolve(generated_id)["duration"] * 1000 + 1 < trim + scene["durationMs"]
        if replace_take:
            scene["take"] = uuid.uuid4().hex
            if not scene["clipId"] or old_clip != scene["clipId"]:
                scene.pop("trimStartMs", None)
        if "trimStartMs" in patch:
            if trim:
                scene["trimStartMs"] = trim
            else:
                scene.pop("trimStartMs", None)
        clip_id = scene["clipId"] or (generated_clips or {}).get(scene["take"])
        trim = scene.get("trimStartMs", 0)
        if trim and not clip_id:
            raise AlphaError("Choose footage before setting its start time.")
        if clip_id and (scene["clipId"] or trim):
            clip = resolve(clip_id)
            if clip["duration"] * 1000 + 1 < trim + scene["durationMs"]:
                raise AlphaError("This cut runs past the end of its clip. Shorten the scene or choose an earlier start.")
    if sum(s["durationMs"] for s in result) > MAX_DURATION_MS:
        raise AlphaError("Keep the composition within 90 seconds.")
    return result


def generation_prompt(project, scene, state, *, route=VIDEO_ROUTE, local=False):
    context, current = project_context(state, project["platform"])
    if not local and not context["cloudAllowed"]:
        raise AlphaError("The workspace owner must enable cloud Brand Brain use before generating.", 403)
    memory.validate_receipt(state, project["memoryReceipt"])
    if context != project["context"]:
        raise AlphaError("Brand knowledge changed. Create a project with the current Brand Brain.", 409)
    if route != VIDEO_ROUTE or local:
        scoped, current = project_context(state, project["platform"], route=route, local=local)
        # The saved direction can itself contain approved voice or preferences. It can travel to
        # another vendor only if every piece used by the blueprint is eligible for that route.
        if not local and scoped != context:
            raise AlphaError("The saved brand direction is not cleared for this model. Choose an authorized model.", 403)
        context = scoped
    permitted = memory.projection(state, "local" if local else "cloud", [{"platform": project["platform"]}], voice_route=route)
    boundaries = next((f["body"] for f in permitted["files"] if f["name"] == "BOUNDARIES.md"), "")
    sections = ["Create original moving footage for this one shot. Show the described action over time. "
                "Use only supplied facts. Avoid invented product markings, third-party likenesses or music. "
                "Leave captions for composition.", project["brief"], scene["direction"],
                f"Brand: {context['brand']}. Subject: {context['subject']}. Audience: {context['audience']}.",
                f"Purpose: {context['purpose']}. Approved tone: {context['tone']}.", *context["preferences"], boundaries]
    prompt = "\n".join(s for s in sections if s)
    if len(prompt) > 4000:
        raise AlphaError("Shorten the brief or scoped brand material before generation.")
    return prompt

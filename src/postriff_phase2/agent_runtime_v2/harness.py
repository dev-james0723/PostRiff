"""LOCAL QA HARNESS ONLY: deterministic reasoning and providers for browser QA of the Agent Runtime.

Enabled only when RAFII_AGENT_HARNESS=1 and never on Vercel (VERCEL=1 refuses it). It replaces what an external
provider owns — the reasoning model, GPT-Live's session endpoint, image generation and vision — with deterministic
stand-ins, so a browser test drives the REAL API, tools, database, proposals, approvals and verification. The Manager
and specialists here are Agents SDK `ScriptedModel`s whose steps are computed from the request and the tool outputs
already in the run (`ModelStep.respond`); they choose tools, the runtime and application do everything else.

This is labelled wherever it runs ("harness model"); it is never evidence of live model quality.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import uuid

HARNESS_ENV = "RAFII_AGENT_HARNESS"


def enabled() -> bool:
    if os.environ.get(HARNESS_ENV) != "1":
        return False
    if os.environ.get("VERCEL") == "1":
        raise RuntimeError("The agent QA harness must never run on a deployment.")
    return True


def _png(colour=(34, 96, 150), size=768) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def provider_transport(method, url, headers=None, body=None, timeout=None):
    """Image generation/editing and vision stand-ins (OpenAI Responses shapes)."""
    body = body or {}
    if (body.get("tools") or [{}])[0].get("type") == "image_generation":
        return {"status": 200, "body": {"id": "resp_harness", "output": [{"type": "image_generation_call", "id": "ig_harness", "status": "completed",
                                                                           "revised_prompt": "harness image", "result": base64.b64encode(_png()).decode()}],
                                        "usage": {"input_tokens": 0, "output_tokens": 0}}}
    findings = {"description": "Harness vision: a flat colour field (the QA harness does not look at pixels).", "visibleText": [], "composition": ["Centered"],
                "issues": ["No call to action"], "aspect": "1:1", "cta": "missing", "brandFit": [], "confidence": "low"}
    return {"status": 200, "body": {"id": "resp_harness_v", "output_text": json.dumps(findings), "usage": {}}}


def live_transport(method, url, headers=None, body=None, timeout=None):
    """GPT-Live session endpoint stand-in: accepts the offer and answers with a placeholder SDP."""
    return {"status": 201, "body": {"session": {"id": "live_harness_" + uuid.uuid4().hex[:8]}, "transport": {"type": "webrtc", "sdp": "v=0\r\no=- harness answer\r\n"}}}


# --- deterministic reasoning ----------------------------------------------------------------------------------------------
def _items(call):
    return call.input if isinstance(call.input, list) else [{"role": "user", "content": call.input}]


def _text_of(item):
    content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


def _request(call) -> tuple[str, dict]:
    for item in reversed(_items(call)):
        if (item.get("role") if isinstance(item, dict) else None) == "user":
            text = _text_of(item)
            match = re.search(r"<request[^>]*>\n(.*?)\n</request>", text, re.S)
            state = re.search(r"<context kind=\"APP_STATE\">\n(.*?)\n</context>", text, re.S)
            try:
                app = json.loads(state.group(1)) if state else {}
            except ValueError:
                app = {}
            return (match.group(1) if match else text), app
    return "", {}


def _outputs(call) -> list[tuple[str, str]]:
    """(tool name, output text) of the calls already made in this run, in order."""
    names, outputs = {}, []
    for item in _items(call):
        data = item if isinstance(item, dict) else getattr(item, "__dict__", {})
        if data.get("type") == "function_call":
            names[data.get("call_id")] = data.get("name")
        elif data.get("type") == "function_call_output":
            outputs.append((names.get(data.get("call_id"), "?"), str(data.get("output") or "")))
    return outputs


def _ids(text: str, key: str) -> list[str]:
    found = re.findall(rf'"{key}"\s*:\s*"([A-Za-z0-9_.:-]+)"', text) + re.findall(rf"{key}=([A-Za-z0-9_:-]+(?:\.[A-Za-z0-9_:-]+)*)", text)
    return list(dict.fromkeys(item.rstrip(".") for item in found if item and item != "None"))


def _arg(text: str, key: str) -> str | None:
    return next(iter(_ids(text, key)), None)


def _call(name, arguments):
    from agents.testing import function_call
    return [function_call(name, arguments, call_id=f"call_{uuid.uuid4().hex[:10]}")]


def _reply(answer, speakable=None):
    from agents.testing import assistant_message
    return [assistant_message(json.dumps({"answer": answer, "speakable": speakable or answer, "language": "en", "follow_ups": []}))]


def _say(text):
    from agents.testing import assistant_message
    return [assistant_message(text)]


def manager_step(call):
    request, app = _request(call)
    lower = request.lower()
    done = _outputs(call)
    called = [name for name, _ in done]
    blob = " ".join(out for _, out in done)
    campaign = next(iter(_ids(blob, "campaignId")), None)
    compound = ("schedule" in lower and ("generate" in lower or "make" in lower)) or ("asset" in lower and "copy" in lower)
    platform = next((name for name in ("LinkedIn", "Threads", "Instagram") if name.lower() in lower), "Instagram")
    if compound:
        if "task_plan" not in called:
            return _call("task_plan", {"title": f"{platform} launch post", "steps": [{"label": "Generate the matching image"}, {"label": f"Write the {platform} copy"},
                                                                                    {"label": "Add the draft and the image to the campaign", "dependsOn": ["s1", "s2"]},
                                                                                    {"label": "Schedule Thursday 18:00", "dependsOn": ["s1", "s2"]}]})
        if "campaign_list" not in called:
            return _call("campaign_list", {})
        if "ask_creative" not in called:
            images = [i["assetId"] for i in app.get("conversationImages") or []]
            return _call("ask_creative", {"input": f"Generate a matching {platform} image in the brand style. Step s1. references={','.join(images[-1:])}"}) + \
                _call("ask_content", {"input": f"Write the {platform} post for campaign campaignId={campaign} platform={platform} . Step s2."})
        asset = next(iter(_ids(blob, "asset")), None)
        draft = next(iter(_ids(blob, "draft")), None)
        if "ask_campaign" not in called and asset and draft:
            return _call("ask_campaign", {"input": f"Link draft={draft} asset={asset} to campaignId={campaign}. Step s3."})
        if "schedule_propose" not in called and draft:
            when = re.search(r"((?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)\s+(?:at\s+)?\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)", request, re.I)
            return _call("schedule_propose", {"draftId": draft, "when": when.group(1) if when else "Thursday 18:00",
                                              **({"assetId": asset, "alt": "Harness image for the launch post"} if asset else {}), "stepId": "s4"})
        return _reply("Here is where each step stands; the scheduling proposal is below for you to apply or leave.",
                      "The image and copy are ready and linked. The Thursday post is waiting for your go-ahead — shall I apply it?")
    if any(word in lower for word in ("image", "picture", "photo", "reference", "look at", "圖")) and not called:
        index = (app.get("conversationImages") or [{}])[-1].get("index")
        return _call("ask_creative", {"input": f"Critique image index={index} for an Instagram post."})
    if "missing" in lower or "campaign" in lower:
        if not called:
            return _call("ask_campaign", {"input": "What is missing in the campaign?"})
        return _reply("I checked the campaign. What it still needs is listed below.", "I checked the campaign; what's missing is in the panel.")
    if "left" in lower or "status" in lower or "what" in lower:
        if not called:
            return _call("pending_approvals", {})
        return _reply("Here is what is still open in this conversation.", "Here's what's still open; it's in the panel.")
    if not called:
        return _call("workspace_summary", {})
    return _reply("Here's what I found in your workspace.")


def specialist_step(name):
    def step(call):
        request, _app = _request(call)
        done = _outputs(call)
        called = [n for n, _ in done]
        blob = " ".join(out for _, out in done)
        if name == "creative":
            if "Critique" in request and not called:
                index = next(iter(re.findall(r"index=(-?\d+)", request)), None)
                return _call("image_analyze", {"question": "Critique this for an Instagram post", **({"index": int(index)} if index and index != "None" else {})})
            if "Generate" in request and not called:
                refs = [r for r in re.findall(r"references=([A-Za-z0-9_,.-]*)", request)[0].split(",") if r] if "references=" in request else []
                return _call("image_generate", {"prompt": "Warm overhead piano keyboard with the practice journal, brand colours", "quality": "quality",
                                                "referenceAssetIds": refs[:1], "stepId": "s1"})
            asset = next(iter(_ids(blob, "assetId")), None)
            return _say(f"asset={asset}" if asset else "Looked at the image; findings are in the tool result.")
        if name == "content":
            if not called:
                campaign = _arg(request, "campaignId")
                platform = _arg(request, "platform") or "Instagram"
                return _call("draft_create", {"brief": "Launch post for the practice journal: slow practice, one step to try today.", "platforms": [platform],
                                              **({"campaignId": campaign} if campaign else {}), "stepId": "s2"})
            draft = next(iter(_ids(blob, "draftId")), None)
            return _say(f"draft={draft}" if draft else "The writer didn't save a draft.")
        if name == "campaign":
            if "Link" in request and not called:
                draft, asset, campaign = _arg(request, "draft"), _arg(request, "asset"), _arg(request, "campaignId")
                return _call("campaign_link", {"campaignId": campaign, "draftIds": [draft] if draft else [], **({"assetIds": [asset]} if asset else {}), "stepId": "s3"})
            if not called:
                return _call("campaign_list", {})
            if "campaign_get" not in called:
                campaign = next(iter(_ids(blob, "campaignId")), None)
                if campaign:
                    return _call("campaign_get", {"campaignId": campaign})
            return _say("Checked the campaign.")
        return _say("Nothing to do.")
    return step


def model_factory():
    """model_factory(workload, agent_name) for AgentRuntimeService: a fresh responder per build."""
    from agents.testing import ModelStep, ScriptedModel

    def factory(_workload, name):
        responder = manager_step if name == "rafii_manager" else specialist_step(name)
        # Enough steps for any harness flow; unused steps are fine outside tests.
        return ScriptedModel([ModelStep.respond(responder) for _ in range(12)])
    return factory

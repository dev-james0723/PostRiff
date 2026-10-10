"""Compensation records and undo for reversible steps (CF-3 §13, EX-27).

For a completed R1 effect whose capability has a registered inverse, `capture` stores a pointer (target, inverse inputs and
a digest of the target as Rafii left it) — never a copy of content. Undo is creator-only, within `undo_until` (default 24 h,
DP-13; the DDL ceiling is 7 days), and refuses when the target changed since (its digest no longer matches), so an undo never
overwrites someone else's later edit. R2/R3 effects are never "undone" by Rafii. Everything else records
`compensation.available=false` with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import model, store, targets


@dataclass(frozen=True)
class Inverse:
    inverse_capability_id: str
    target: Callable[[dict, dict], tuple[str, str] | None]       # (inputs, result) -> (target_type, target_id)
    inverse_inputs: Callable[[dict, dict], dict]                  # (inputs, result) -> inputs of the inverse capability
    image: Callable[[dict, str, str], object]                     # (workspace state, target_type, target_id) -> what the digest covers


INVERSES: dict[str, Inverse] = {}


def register(capability_id: str, inverse: Inverse) -> None:
    INVERSES[capability_id] = inverse


def _campaign_items(state: dict, _kind: str, campaign_id: str):
    root = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    campaign = next((c for c in root.get("campaigns") or [] if isinstance(c, dict) and c.get("id") == campaign_id), None)
    return None if campaign is None else sorted((model.canonical(i) for i in campaign.get("items") or []))


def _link_inputs(inputs: dict, _result: dict) -> dict:
    return {k: v for k, v in {"campaignId": inputs.get("campaignId"), "draftIds": list(inputs.get("draftIds") or []),
                              "jobIds": list(inputs.get("jobIds") or [])}.items() if v}


register("campaign_link", Inverse("campaign_unlink", lambda inputs, _r: ("campaign", inputs["campaignId"]) if inputs.get("campaignId") else None,
                                  _link_inputs, _campaign_items))


register("campaign_unlink", Inverse("campaign_link", lambda inputs, _r: ("campaign", inputs["campaignId"]) if inputs.get("campaignId") else None,
                                    _link_inputs, _campaign_items))


def _draft_image(state, _kind, ident):
    item = next((v for v in state.get("variants", []) if v.get("id") == ident), None)
    return None if item is None else {"text": item.get("text"), "revision": item.get("revision")}


register("draft_edit", Inverse("draft_edit", lambda inputs, _r: ("draft", inputs["draftId"]),
                               lambda inputs, _r: {"draftId": inputs["draftId"], "restoreRevision": inputs["revision"]}, _draft_image))

def digest_of(state: dict, inverse: Inverse, target_type: str, target_id: str) -> str | None:
    image = inverse.image(state, target_type, target_id)
    return None if image is None else model.sha256({"target": [target_type, target_id], "image": image})


def capture(cur, task: dict, step: dict, result: dict, refs: list) -> dict:
    """Inside the finishing transaction of a completed effect: store the compensation pointer, or say why there is none."""
    inverse = INVERSES.get(step["capabilityId"] or "")
    if step["riskClass"] != "R1":
        return {"available": False, "reason": "not_reversible_by_rafii"}
    if inverse is None:
        return {"available": False, "reason": "no_inverse"}
    inputs = step["inputs"] or {}
    inverse_inputs = result.get("_inverseInputs")
    if inverse_inputs is not None and step["capabilityId"] in ("campaign_link", "campaign_unlink") and not (inverse_inputs.get("draftIds") or inverse_inputs.get("jobIds")):
        return {"available": False, "reason": "nothing_changed"}
    target = inverse.target(inputs, result)
    if target is None:
        return {"available": False, "reason": "no_target"}
    state = targets.workspace_state(cur, task["workspaceId"])
    image = digest_of(state, inverse, target[0], target[1])
    if image is None:
        return {"available": False, "reason": "target_unreadable"}
    compensation_id = store.insert_compensation(cur, task=task, step=step, effect_key=step["effectKey"], inverse_capability_id=inverse.inverse_capability_id,
                                                target_type=target[0], target_id=target[1], post_image_digest=image,
                                                inverse_inputs=result.get("_inverseInputs") or inverse.inverse_inputs(inputs, result))
    if not compensation_id:
        return {"available": False, "reason": "already_recorded"}
    cur.execute("SELECT extract(epoch from undo_until) FROM public.pr_agent_compensations WHERE id::text=%s", (compensation_id,))
    return {"available": True, "compensationId": compensation_id, "undoUntil": float(cur.fetchone()[0])}


def current_digest(cur, workspace_id: str, record: dict, capability_id: str) -> str | None:
    inverse = INVERSES.get(capability_id or "")
    if inverse is None or inverse.inverse_capability_id != record["inverseCapabilityId"]:
        return None
    return digest_of(targets.workspace_state(cur, workspace_id), inverse, record["targetType"], record["targetId"])

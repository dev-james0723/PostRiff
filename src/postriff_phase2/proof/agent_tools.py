"""Typed agent tools for proof and the strategy loop (PRD R-ENG-02 ``proof_read`` / ``strategy_decide``).

``proof_read`` is READ: stored proof revisions only (it never recomputes, appends or calls a provider; provider
cost is shown to owners only, exactly as on the page). ``strategy_decide`` is MUTATE_REVERSIBLE with the ``owner``
class: accept / edit / reject / revoke one next-week decision through ProofService, which re-checks the member,
the expected revision and the idempotency key. A decision never changes identity or voice and never approves or
publishes anything. Voice and text are identical; the coordinator wires ``register`` into the tool registry.
"""
from __future__ import annotations

import hashlib

from . import FLAG, enabled

TOOL_SCOPES = {"proof_read": ["rafii_manager", "analytics"], "strategy_decide": ["rafii_manager", "analytics"]}


def _disabled():
    return {"ok": False, "verified": False, "code": "feature_disabled", "message": f"{FLAG} is off, so this tool is unavailable."}


def _error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def register():
    from ..agent_runtime_v2 import contracts, tool_adapter
    from postriff_alpha.domain import AlphaError
    if "proof_read" in tool_adapter.REGISTRY:
        return

    @tool_adapter.register(contracts.ToolSpec("proof_read", contracts.READ, "read",
                                              "Read the Growth Loop proof: accepted work, verified publications, assisted exports (separate), unresolved slots, "
                                              "outcomes by provenance, Time Back by confidence class and (owners) provider cost, each with its evidence ids, "
                                              "revision history and the next-week proposals.", voice=True),
                           {"proofId": {"type": "string"}, "frequency": {"type": "string"}}, "Read the proof")
    def proof_read(ctx, args):
        if not enabled():
            return _disabled()
        from .http import ensure
        try:
            service = ensure(ctx.service)
            if args.get("proofId"):
                proofs = [service.get(ctx.workspace_id, ctx.token, str(args["proofId"]))["proof"]]
            else:
                proofs = service.list(ctx.workspace_id, ctx.token, args.get("frequency"), None, 3)["proofs"]
        except AlphaError as error:
            return _error(error)
        for proof in proofs:
            ctx.ledger.reference("proof", proof["proofId"], f"{proof['frequency']} proof revision {proof['latest']['revision']}")
        return {"ok": True, "verified": True, "proofs": proofs,
                "note": "Delivery is not growth; unavailable figures are unavailable, not zero; time classes are separate."}

    @tool_adapter.register(contracts.ToolSpec("strategy_decide", contracts.MUTATE_REVERSIBLE, "owner",
                                              "Accept, edit (wording or a narrower scope), reject or revoke one proposed next-week action. It only adds context "
                                              "to next week's plan; it never changes the voice, approves or publishes anything.", voice=True),
                           {"decisionId": {"type": "string", "required": True}, "action": {"type": "string", "required": True},
                            "expectedRevision": {"type": "integer", "required": True}, "statement": {"type": "string"}, "scope": {"type": "object"}},
                           "Decided a next-week action")
    def strategy_decide(ctx, args):
        if not enabled():
            return _disabled()
        from .http import ensure
        seed = ":".join(str(p) for p in (ctx.run_id or ctx.trace_id, ctx.workspace_id, args.get("decisionId"), args.get("action"), args.get("expectedRevision")))
        payload = {k: args[k] for k in ("action", "expectedRevision", "statement", "scope") if args.get(k) is not None}
        payload["idempotencyKey"] = "agent-" + hashlib.sha256(seed.encode()).hexdigest()[:40]
        try:
            result = ensure(ctx.service).decide(ctx.workspace_id, ctx.token, str(args.get("decisionId") or ""), payload)
        except AlphaError as error:
            return _error(error)
        decision = result["decision"]
        if not result.get("replayed"):
            ctx.ledger.changed.append({"type": "strategy_decision", "id": decision["id"], "change": f"next-week action {decision['status']}",
                                       "expected": decision["status"], "actual": decision["status"], "verified": bool(result["verified"])})
        return {"ok": True, "verified": bool(result["verified"]), "decision": decision, "planning": result.get("planning"), "replayed": result.get("replayed", False)}

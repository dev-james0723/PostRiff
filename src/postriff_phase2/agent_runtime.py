"""Product-owned AgentRuntime interface (architecture §10.2) and safe event contract (§10.4).

Only the events in SAFE_EVENTS reach a client. Adapter-native events are translated;
anything unknown is dropped and replaced by a warning. Source text is data: the runtime
never interprets it as an instruction and never emits `action.proposed` on its own.
"""
from postriff_alpha.domain import AlphaError, clean
from postriff_alpha.generation import FixtureAdapter
from .contracts import digest

SAFE_EVENTS = ("run.started", "progress.updated", "source.added", "artifact.created", "message.delta", "message.completed", "warning.created", "action.proposed", "run.completed", "run.failed", "run.cancelled")
REASONING = ("quick", "standard", "deep")
DESTINATIONS = (("LinkedIn", "English"), ("Instagram", "繁體中文"), ("Threads", "English"), ("LinkedIn", "繁體中文"), ("Instagram", "English"), ("Threads", "繁體中文"))

# Phase-3 adapter kinds → safe families. Never forwarded raw.
TRANSLATION = {"waiting": "progress.updated", "running": "progress.updated", "text": "message.delta", "completed": "run.completed", "interrupted": "run.cancelled", "expired": "run.failed", "revoked": "run.failed", "failed": "run.failed", "permission_denied": "warning.created", "uncertain": "warning.created", "applied": "artifact.created"}


def safe_event(kind, **body):
    if kind not in SAFE_EVENTS:
        raise AlphaError("Unsupported client event.", 500)
    out = {"type": kind}
    for key, value in body.items():
        if key in ("text", "message"):
            value = clean(value, 12000)
        out[key] = value
    return out


def translate(native):
    """Map an adapter-native event to the safe contract; unknown → warning, no payload."""
    kind = TRANSLATION.get(native.get("type") if isinstance(native, dict) else None)
    if kind is None:
        return safe_event("warning.created", message="An unrecognized runtime event was dropped.")
    if kind == "message.delta":
        return safe_event(kind, text=native.get("text", ""))
    if kind in ("run.failed", "run.cancelled", "warning.created"):
        return safe_event(kind, message=native.get("text") or "The runtime reported an issue.")
    return safe_event(kind)


class AgentRuntime:
    """Stable interface. Concrete runtimes must not expose prompts, keys, or paths."""
    def start_conversation(self, workspace_id, actor): raise NotImplementedError
    def resume_conversation(self, conversation): raise NotImplementedError
    def start_turn(self, request, emit): raise NotImplementedError
    def cancel_run(self, run): raise NotImplementedError
    def stream_safe_events(self, events, cursor): return [e for e in events if e["seq"] > cursor]
    def list_supported_models(self): raise NotImplementedError
    def list_supported_reasoning(self): raise NotImplementedError


class FixtureAgentRuntime(AgentRuntime):
    """Deterministic, zero-network runtime. The only qualified route in this round."""
    model = "deterministic-preview"

    def start_conversation(self, workspace_id, actor):
        return {"runtime": self.model, "resumable": True}

    def resume_conversation(self, conversation):
        return {"runtime": self.model, "resumed": True}

    def list_supported_models(self):
        return [
            {"id": self.model, "label": "Deterministic preview", "qualified": True, "costClass": "none", "detail": "Local authored templates and approved source quotations; no model request."},
            {"id": "server-openai", "label": "PostRiff managed model", "qualified": False, "costClass": "paid", "detail": "Server-side production runtime identity is not yet qualified (account, key, cost authorization)."},
        ]

    def list_supported_reasoning(self):
        return [
            {"id": "quick", "available": True, "detail": "Deterministic preview only."},
            {"id": "standard", "available": False, "detail": "Requires a qualified model route."},
            {"id": "deep", "available": False, "detail": "Requires a qualified model route."},
        ]

    def cancel_run(self, run):
        return {"status": "completed" if run.get("status") == "completed" else "cancelled"}

    def start_turn(self, request, emit):
        context = request["context"]
        destinations = request.get("destinations") or [{"platform": "LinkedIn", "language": "English"}, {"platform": "Instagram", "language": "繁體中文"}]
        for d in destinations:
            if (d.get("platform"), d.get("language")) not in DESTINATIONS:
                raise AlphaError("Choose supported destinations.", 400)
        if request.get("reasoning", "quick") not in REASONING:
            raise AlphaError("Choose a reasoning level.", 400)
        if request.get("reasoning", "quick") != "quick":
            emit(safe_event("warning.created", message="Only Quick is available on the deterministic preview; Standard and Deep need a qualified model route."))
        emit(safe_event("run.started", model=self.model, reasoning="quick", contextDigest=digest(context)))
        for source in context["sources"]:
            emit(safe_event("source.added", sourceId=source["id"], policy=source["policy"], candidateOnly=source["candidateOnly"], facts=len(source["facts"])))
        for item in context["excluded"]:
            emit(safe_event("warning.created", sourceId=item["id"], message=f"Source excluded: {item['reason']}."))
        emit(safe_event("progress.updated", stage="drafting", percent=25))
        facts = [f for s in context["sources"] for f in s["facts"]]
        variants = []
        for index, d in enumerate(destinations):
            result = FixtureAdapter().generate({**d, "facts": facts, "idea": request.get("idea", ""), "tone": request.get("tone", "warm"), "shortOpenings": request.get("shortOpenings", False)})
            text = result["text"]
            # Deliver text as bounded deltas, then the completed message for this destination.
            for start in range(0, len(text), 400):
                emit(safe_event("message.delta", destination=index, text=text[start:start + 400]))
            emit(safe_event("message.completed", destination=index))
            variants.append({**d, "text": text, "sourceIds": result["sourceIds"], "unknowns": result["unknowns"], "warnings": result["warnings"], "candidateOnly": context["candidateOnly"]})
            emit(safe_event("progress.updated", stage="drafting", percent=25 + int(70 * (index + 1) / len(destinations))))
        artifact = {"variants": variants}
        emit(safe_event("artifact.created", artifactHash=digest(artifact), variants=len(variants)))
        emit(safe_event("run.completed", usage={"provenance": "measured_locally", "modelRequests": 0}))
        return {"artifact": artifact, "usage": {"provenance": "measured_locally", "modelRequests": 0, "costUsd": 0}}

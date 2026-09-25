"""Product-owned AgentRuntime interface (architecture §10.2) and safe event contract (§10.4).

Only the events in SAFE_EVENTS reach a client. Adapter-native events are translated;
anything unknown is dropped and replaced by a warning. Source text is data: the runtime
never interprets it as an instruction and never emits `action.proposed` on its own.
"""
from postriff_alpha.domain import AlphaError, clean
from postriff_alpha.generation import FixtureAdapter
from .contracts import digest
from . import locale_lint, locales

SAFE_EVENTS = ("run.started", "progress.updated", "source.added", "artifact.created", "message.delta", "message.completed", "warning.created", "action.proposed", "run.completed", "run.failed", "run.cancelled")
REASONING = ("quick", "standard", "deep")
# Platforms every drafting route can write for. Any language PostRiff knows (locales.is_valid) goes with any of them,
# and a platform may appear several times in one request, once per language. Draftable is not publishable: X and
# Xiaohongshu have no hosted publisher (hosted_social maps LinkedIn, Threads and Instagram only), so their drafts are
# for review, copy and export, and the capability check reports them as having no publishing route.
PLATFORMS = ("LinkedIn", "Instagram", "Threads", "X", "Xiaohongshu")
DEFAULT_REQUEST_DESTINATIONS = ({"platform": "LinkedIn", "language": "en"}, {"platform": "Instagram", "language": "zh-Hant"})


def check_destinations(destinations):
    """Every destination is a supported platform with a known language; the key that must be unique is
    (platform, language, account): two accounts on one platform are two destinations, the same account
    in the same language twice is a client error."""
    seen = set()
    for d in destinations:
        platform, tag = d.get("platform"), locales.canonical(d.get("language"))
        channel_id = d.get("channelId") if isinstance(d.get("channelId"), str) else None
        if platform not in PLATFORMS or tag is None or (platform, tag, channel_id) in seen:
            raise AlphaError("Choose supported destinations.", 400)
        seen.add((platform, tag, channel_id))


def identity_fields(destination):
    """The account identity a variant carries forward from its destination (never credentials)."""
    out = {}
    if isinstance(destination.get("channelId"), str) and destination["channelId"]:
        out["channelId"] = destination["channelId"]
    if isinstance(destination.get("account"), str) and destination["account"]:
        out["account"] = destination["account"]
    return out

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
    provider = "fixture"          # ledger provider label
    cost_class = "none"           # none | subscription | paid — what PostRiff itself pays
    asynchronous = False          # True: `dispatch(run_id, request, sink)` finishes the run later
    def start_conversation(self, workspace_id, actor): raise NotImplementedError
    def resume_conversation(self, conversation): raise NotImplementedError
    def start_turn(self, request, emit): raise NotImplementedError
    def cancel_run(self, run): raise NotImplementedError
    def stream_safe_events(self, events, cursor): return [e for e in events if e["seq"] > cursor]
    def list_supported_models(self): raise NotImplementedError
    def list_supported_reasoning(self): raise NotImplementedError
    def supported_platforms(self): return ()  # platforms this runtime can draft for; () = unknown, no filtering
    def owns(self, model_id): return any(m["id"] == model_id and m.get("qualified") for m in self.list_supported_models())
    def describe(self): return None           # CLI/device runtimes describe the agent they drive
    def dispatch(self, run_id, request, sink): raise NotImplementedError


class FixtureAgentRuntime(AgentRuntime):
    """Deterministic, zero-network runtime. The only qualified route in this round."""
    model = "deterministic-preview"

    def start_conversation(self, workspace_id, actor):
        return {"runtime": self.model, "resumable": True}

    def resume_conversation(self, conversation):
        return {"runtime": self.model, "resumed": True}

    def list_supported_models(self):
        return [
            {"id": self.model, "label": "Deterministic preview", "qualified": True, "costClass": "none", "detail": "Writes from templates and your approved sources. No AI model."},
            {"id": "server-openai", "label": "Rafii managed model", "qualified": False, "costClass": "paid", "detail": "Not available yet."},
        ]

    def list_supported_reasoning(self):
        return [
            {"id": "quick", "available": True, "detail": "One quick pass."},
            {"id": "standard", "available": False, "detail": "Needs an AI writer."},
            {"id": "deep", "available": False, "detail": "Needs an AI writer."},
        ]

    def cancel_run(self, run):
        return {"status": "completed" if run.get("status") == "completed" else "cancelled"}

    def supported_platforms(self):
        return PLATFORMS

    def start_turn(self, request, emit):
        context = request["context"]
        destinations = request.get("destinations") or [dict(d) for d in DEFAULT_REQUEST_DESTINATIONS]
        check_destinations(destinations)
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
        style = request.get("styleDirectives") or {}
        variants = []
        for index, d in enumerate(destinations):
            result = FixtureAdapter().generate({**d, "facts": facts, "idea": request.get("idea", ""), "tone": request.get("tone", "warm"), "shortOpenings": style.get("shortOpenings", False), "styleDirectives": style})
            text = result["text"]
            # Deliver text as bounded deltas, then the completed message for this destination.
            for start in range(0, len(text), 400):
                emit(safe_event("message.delta", destination=index, text=text[start:start + 400]))
            emit(safe_event("message.completed", destination=index))
            warnings = result["warnings"] + locale_lint.reminders(text, d["language"], d["platform"])
            variants.append({**d, "text": text, "sourceIds": result["sourceIds"], "unknowns": result["unknowns"], "warnings": warnings, "candidateOnly": context["candidateOnly"]})
            emit(safe_event("progress.updated", stage="drafting", percent=25 + int(70 * (index + 1) / len(destinations))))
        voice = request.get("voiceContext") or {"mode": "neutral", "bindings": [], "digest": None, "route": None}
        artifact = {"variants": variants, "voiceContext": {key: voice.get(key) for key in ("mode", "bindings", "digest", "route")}}
        emit(safe_event("artifact.created", artifactHash=digest(artifact), variants=len(variants)))
        emit(safe_event("run.completed", usage={"provenance": "measured_locally", "modelRequests": 0}))
        return {"artifact": artifact, "usage": {"provenance": "measured_locally", "modelRequests": 0, "costUsd": 0}}

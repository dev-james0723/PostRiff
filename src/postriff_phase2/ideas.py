"""Hosted Ideas conversation service: durable conversations, runs, safe events, apply.

Every call runs inside the workspace membership transaction. Runs execute the
AgentRuntime against a policy projection only; artifacts are candidates until an explicit
`apply`, which re-checks the projection so stale candidates are never applied silently.
"""
import copy
import base64
import hashlib
import inspect
import json
import time
import math
import uuid
import binascii
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError, clean, uid
from postriff_alpha.generation import MATERIAL_LABEL  # noqa: F401 (legacy callers import it from here)
from .contracts import digest
from .permissions import require
from .source_policy import project_context, stamp
from .agent_runtime import SAFE_EVENTS, FixtureAgentRuntime, safe_event
from .cli_runtime import ClaudeCliRuntime
from .model_runtime import REQUEST_SECONDS, ProviderFailure, ServerModelRuntime, check_level_ceiling
from .codex_runtime import CodexCliRuntime
from .skills import SkillLibrary, budget_for
from . import ai_call_events, attachment_rows, content_types, intent, locales, memory, research, turn_references, voice_sources, writer_defaults

VOICE_FALLBACK_NOTE = "Your writing samples were not available to this writer, so this draft is in a neutral voice. Allow a sample for it on the Brand page to write like you again."

MAX_TEXT = 6000
IDEA_LIMIT = 3000
MAX_EVENTS = 2000
DEFAULT_DESTINATIONS = ({"platform": "LinkedIn", "language": "en"}, {"platform": "Instagram", "language": "zh-Hant"})



def checked_context_ids(state, raw):
    if not isinstance(raw, list) or len(raw) > 20 or any(not isinstance(v, str) or not v for v in raw):
        raise AlphaError("Choose at most 20 valid context sources.", 400)
    allowed = {s["id"] for s in state.get("sources", []) if s.get("active") and s.get("kind") != "voice_sample" and s.get("sourcePolicy") != "prohibited"}
    if any(value not in allowed for value in raw):
        raise AlphaError("A selected context source is unavailable in this workspace.", 409)
    return list(dict.fromkeys(raw))


def same_slot(variant, candidate):
    """A draft refreshes in place only when it is the same account (or platform-level draft) in the
    same language: two accounts on one platform never overwrite each other's drafts."""
    return (variant.get("platform") == candidate.get("platform") and locales.same(variant.get("language"), candidate.get("language"))
            and (variant.get("channelId") or None) == (candidate.get("channelId") or None)
            # Two native formats on one platform (a Page post and a Reel) are two drafts; a draft without a format is
            # the platform's default format, so older drafts still refresh in place.
            and _native_format(variant) == _native_format(candidate))


def _native_format(item):
    from .creation_capabilities import DEFAULT_FORMATS
    return item.get("format") or DEFAULT_FORMATS.get(item.get("platform"))


def usd_micro(cost_usd):
    """Provider cost in whole micro-dollars, rounded up so a reported cost is never under-recorded."""
    from decimal import ROUND_CEILING, Decimal
    return int((Decimal(repr(float(cost_usd))) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


IDEMPOTENCY_IGNORED = frozenset({"creditQuoteId", "expectedRevision", "idempotencyKey"})
AUTO = "auto"
LEVEL_REFUSAL = "Choose a reasoning level this writer supports."
# Web research can add at most this much prompt after the level check a turn makes before it (research.py limits).
RESEARCH_ALLOWANCE_BYTES = research.MAX_PAGES * research.MAX_FACTS * (research.MAX_FACT_CHARS * 3 + 100)


def _workspace_asset_id(state, stored):
    """Return a stored UUID using the workspace asset's exact public ID spelling.

    PostgreSQL UUID columns render with hyphens, while existing video assets use uuid4().hex.
    Moments must round-trip the same asset ID that the media and attachment APIs use.
    """
    raw = str(stored)
    try:
        target = uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return raw
    for asset in (state.get("phase2") or {}).get("assets", []):
        candidate = asset.get("id") if isinstance(asset, dict) else None
        if not isinstance(candidate, str):
            continue
        try:
            if uuid.UUID(candidate) == target:
                return candidate
        except ValueError:
            continue
    return raw


def _warnings(note):
    """A message body's `warnings` for a turn that runs no writer (automation, memory): the Auto fallback note."""
    return {"warnings": [note]} if note else {}


def requested_level(payload):
    """The reasoning level a request asked for: its `reasoning` when given, else Auto. Legacy quick/standard/deep stay
    accepted everywhere they were."""
    value = (payload or {}).get("reasoning")
    return value if isinstance(value, str) and value else AUTO


def per_model_reasoning(runtime):
    """Whether this runtime lists reasoning per model (its list_supported_reasoning takes a `model` parameter)."""
    method = getattr(runtime, "list_supported_reasoning", None)
    try:
        return method is not None and "model" in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


def translate_reasoning(runtime, model_id, level):
    """(reasoning, level) the chosen writer receives for a requested level; `reasoning` is also what pr_agent_runs
    stores. The managed writer gets its legacy pass (quick; deep for Thorough; standard otherwise, the self-check) plus
    the level itself; the fixture and other per-writer lists only know the passes; a local CLI gets its own effort.
    An explicit level the writer does not offer is refused (400) before anything is stored or sent."""
    if isinstance(runtime, ClaudeCliRuntime):
        return runtime.effort({AUTO: "low", "thorough": "high"}.get(level, level)), None
    if per_model_reasoning(runtime):
        mode = "quick" if level == "quick" else "deep" if level in ("deep", "thorough") else "standard"
        normal = {"quick": AUTO, "standard": AUTO, "deep": "thorough"}.get(level, level)
        if normal not in (AUTO, "thorough"):
            offered = runtime.offered_levels(model_id) if hasattr(runtime, "offered_levels") else [
                item["id"] for item in runtime.list_supported_reasoning(model=model_id) if item.get("kind") == "effort"]
            if normal not in offered:
                raise AlphaError(LEVEL_REFUSAL, 400)
        return mode, normal
    mode = {AUTO: "quick", "thorough": "deep"}.get(level, level)
    if mode not in ("quick", "standard", "deep"):
        raise AlphaError(LEVEL_REFUSAL, 400)
    return mode, None


def request_fingerprint(operation, payload, conversation_id=None):
    """Binds a client request key to the request it named: an exact resend matches, another request does not."""
    return digest({"operation": operation, "conversationId": conversation_id, "request": {k: v for k, v in (payload or {}).items() if k not in IDEMPOTENCY_IGNORED}})


class RunSink:
    """Completion channel for asynchronous runtimes (a local CLI now, a paired device later).

    Every call is its own transaction on a fresh connection, so a run finishes correctly long
    after the request that started it returned. A run that is no longer `running` (cancelled,
    failed elsewhere) silently absorbs late events: nothing is applied twice.
    """
    def __init__(self, service, workspace_id, conversation_id, run_id, outcome):
        self.service, self.workspace_id, self.conversation_id, self.run_id, self.outcome = service, workspace_id, conversation_id, run_id, outcome

    def _open(self):
        return self.service.repository.connection_factory()

    def _running(self, cur, lock=False):
        cur.execute("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s" + (" FOR UPDATE" if lock else ""), (self.run_id, self.workspace_id))
        row = cur.fetchone()
        return bool(row) and row[0] == "running"

    def cancelled(self):
        with self._open() as db, db.cursor() as cur:
            return not self._running(cur)

    def emit(self, event):
        with self._open() as db, db.cursor() as cur:
            # Lock first, then look: a status read taken before the locks could be stale by the time
            # the event is written (a cancel committing in between would be followed by a late event).
            self.service._lock_run_events(cur, self.workspace_id, self.run_id)
            if not self._running(cur):
                return False
            self.service._insert_event(cur, self.workspace_id, self.run_id, event)
            return True

    def complete(self, artifact, usage):
        with self._open() as db, db.cursor() as cur:
            self.service._lock_run_events(cur, self.workspace_id, self.run_id)
            if not self._running(cur, lock=True):
                # Cancellation wins for content; late provider usage still settles
                # once so a cancelled billable request is never recorded as free.
                self.service.ledger.settle(cur, self.workspace_id, self.outcome["reservationId"], "failed" if usage.get("costUsd") is not None else "unknown", usd_micro(usage["costUsd"]) if usage.get("costUsd") is not None else None)
                return False
            try:
                self.service._finish(cur, self.workspace_id, self.conversation_id, self.run_id, artifact, usage, self.outcome)
            except AlphaError as error:
                self.service._insert_event(cur, self.workspace_id, self.run_id, safe_event("run.failed", message=str(error)))
                cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (self.run_id,))
                self.service.ledger.settle(cur, self.workspace_id, self.outcome["reservationId"], "failed" if usage.get("costUsd") is not None else "unknown", usd_micro(usage["costUsd"]) if usage.get("costUsd") is not None else None)
                self.service._settle_message(cur, self.workspace_id, self.conversation_id, self.run_id, {"text": str(error), "runId": self.run_id, "failed": True, "intent": self.outcome["parsed"]["intent"], "destinations": self.outcome["destinations"], "plan": None, "model": self.outcome["model"], **({"references": self.outcome["references"]} if self.outcome.get("references") is not None else {})})
                return True
            self.service._insert_event(cur, self.workspace_id, self.run_id, safe_event("run.completed", usage={k: usage.get(k) for k in ("provenance", "modelRequests", "costUsd", "cliCostUsd", "billing", "reasoning") if k in usage}))
            return True

    def fail(self, message, known_cost_usd=None, usage=None):
        """`known_cost_usd` is the provider cost proven for this failed run (0.0 when nothing was sent);
        None leaves a paid run's cost unknown until it is reconciled. `usage` (what the runtime recorded before it
        failed, such as its reasoning block) is merged into the run's usage on every branch."""
        with self._open() as db, db.cursor() as cur:
            self.service._lock_run_events(cur, self.workspace_id, self.run_id)
            if usage:
                cur.execute("UPDATE public.pr_agent_runs SET usage=usage || %s::jsonb WHERE id::text=%s AND workspace_id=%s", (json.dumps(usage), self.run_id, self.workspace_id))
            if not self._running(cur, lock=True):
                # Cancelled or finished elsewhere: a cost proven afterwards still settles the hold once.
                if known_cost_usd is not None:
                    self.service.ledger.settle(cur, self.workspace_id, self.outcome["reservationId"], "failed", usd_micro(known_cost_usd))
                return False
            self.service._insert_event(cur, self.workspace_id, self.run_id, safe_event("run.failed", message=message))
            cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (self.run_id,))
            if known_cost_usd is not None:
                self.service.ledger.settle(cur, self.workspace_id, self.outcome["reservationId"], "failed", usd_micro(known_cost_usd))
            else:
                self.service.ledger.settle(cur, self.workspace_id, self.outcome["reservationId"], "unknown" if self.outcome.get("paid") else "failed", None if self.outcome.get("paid") else 0)
            self.service._settle_message(cur, self.workspace_id, self.conversation_id, self.run_id, {"text": message, "runId": self.run_id, "failed": True, "intent": self.outcome["parsed"]["intent"], "destinations": self.outcome["destinations"], "plan": None, "model": self.outcome["model"], **({"references": self.outcome["references"]} if self.outcome.get("references") is not None else {})})
            return True


class IdeasService:
    def __init__(self, repository, commands, runtime=None, clock=None, ledger=None, runtimes=None, skill_library=None, researcher=None, image_runtime=None, assets=None,
                 media_notes=None, video_policy=None, attachments_enabled=False, notes_enabled=False, video_enabled=False):
        from .billing import Ledger
        self.repository = repository
        self.commands = commands
        self.runtime = runtime or FixtureAgentRuntime()
        self.clock = clock or __import__("time").time
        self.ledger = ledger or Ledger()
        from .credit_requests import CreditRequests
        self.credit_requests = CreditRequests(self)
        self._discover_cli = runtimes is None
        self._catalog_lock = __import__("threading").Lock()
        if runtimes is None:
            # Local CLI routes exist only where the CLI is installed and enabled (never on a hosted function).
            runtimes = [self.runtime]
            for cli in (ClaudeCliRuntime, CodexCliRuntime):
                if cli.available():
                    runtimes.append(cli(clock=self.clock))
        self.runtimes = list(runtimes)
        self.skills = skill_library or SkillLibrary()
        # Image generation is deliberately separate from every writing runtime. Selecting a hosted
        # model, Claude CLI, Codex CLI, or the fixture writer never changes this media route.
        self.image_runtime = image_runtime
        self.assets = assets
        # The hosted service sets this to its HostedLearning; without it a memory instruction is answered but not kept.
        self.learning = None
        # Web research runs before drafting when a turn needs facts the workspace lacks (research.py); False disables it.
        self.researcher = None if researcher is False else (researcher or (research.Researcher() if research.enabled() else None))
        # Chat attachments (chat-context SPEC §14.2): every part is off unless its flag is on.
        self.media_notes = media_notes
        self.video_policy = video_policy
        self.attachments_enabled = bool(attachments_enabled)
        self.notes_enabled = bool(notes_enabled)
        self.video_enabled = bool(video_enabled)
        if media_notes is not None:
            media_notes.credit_requests = self.credit_requests

    # --- routes and models ---------------------------------------------------------
    @staticmethod
    def _voice_route(runtime, model_id):
        """The exact writer route voice-sample consent is checked against (and recorded on each draft)."""
        return f"cloud:{runtime.provider}:{model_id}" if getattr(runtime, "provider_class", "local") == "cloud" else "local-cli"

    def model_catalog(self, *, actor=None):
        """Every model a client may name in a turn, with the agent (CLI) behind each route."""
        models, agents = [], []
        for runtime in self.runtimes:
            # A runtime that lists reasoning per model (the managed writer) gets asked per model; the others keep one list.
            per_model = per_model_reasoning(runtime)
            models.extend({**model, "voiceAnalysisAvailable": callable(getattr(runtime, 'analyze_voice', None)), "provider": runtime.provider, "egress": getattr(runtime, "provider_class", "local"), "voiceRoute": self._voice_route(runtime, model["id"]), "voiceRouteClass": voice_sources.route_class(self._voice_route(runtime, model["id"])),
                           "reasoning": runtime.list_supported_reasoning(model=model["id"], **({"actor": actor} if isinstance(runtime, ServerModelRuntime) else {})) if per_model else runtime.list_supported_reasoning()} for model in runtime.list_supported_models())
            info = runtime.describe()
            if info:
                agents.append(info)
        if any(m.get("qualified") and m.get("costClass") == "paid" and m.get("id") != "server-openai" for m in models):
            # The fixture lists a "Rafii managed model · not available yet" placeholder; next to a real managed writer
            # it only confuses the choice.
            models = [m for m in models if m.get("id") != "server-openai"]
        image_available = self.image_runtime is not None and self.assets is not None
        managed = self._managed_writer()
        listed = {m["id"] for m in models}
        return {
            "models": models,
            "reasoning": self.default_runtime().list_supported_reasoning(),
            # What "Auto" falls back to on this deployment (a workspace default, when set, lives in workspace state).
            "defaultModel": getattr(managed, "model", None),
            "featured": [m for m in managed.featured_models() if m in listed] if managed is not None and hasattr(managed, "featured_models") else [],
            "agents": agents,
            "imageGeneration": {
                "available": image_available,
                "model": self.image_runtime.model if self.image_runtime is not None else None,
                "provider": self.image_runtime.provider if self.image_runtime is not None else None,
                "costClass": "paid",
                "independentOfWritingModel": True,
                "detail": "Uses one managed media credit and the approved image budget, independently of the selected writing model or local CLI." if image_available else "Configure the managed image route and private media storage to generate images in chat.",
            },
            "attachments": self.attachments_catalog(),
            "creation": self.creation_catalog(),
        }

    @staticmethod
    def creation_catalog():
        """The versioned creation-capability facet (creation_capabilities.SCHEMA): which platforms and native formats the
        composer may offer, with independent draft/media/export/connect/publish/analytics/learning states. The server
        validates every turn against the same projection; this facet never authorizes anything by itself."""
        from .creation_capabilities import projection
        try:
            return projection().public()
        except Exception:  # noqa: BLE001 - a failed load offers the original five only (client fallback), never more
            return None

    def attachments_catalog(self):
        """Chat attachments (chat-context SPEC §5.11): every limit and number the UI shows, and which parts are on."""
        from .media_notes import MAX_FRAMES
        reader = getattr(self.media_notes, "reader", None)
        notes_available = bool(self.notes_enabled and reader is not None and reader.available)
        uploads = getattr(self, "video_uploads", None)
        video = uploads.catalog() if uploads is not None else (self.video_policy.catalog(None) if self.video_policy is not None else {"enabled": False, "mimes": ["video/mp4", "video/quicktime"], "maxBytes": 100_000_000, "maxSeconds": 180, "frames": MAX_FRAMES})
        video = {**video, "enabled": bool(self.video_enabled and video.get("enabled"))}
        estimate = (lambda kind, frames: self.media_notes.estimate(kind, frames)) if notes_available else (lambda kind, frames: None)
        photo, clip = estimate("photo", 1), estimate("video_frames", video.get("frames") or MAX_FRAMES)
        return {
            "enabled": self.attachments_enabled,
            "limits": {"references": turn_references.MAX_REFERENCES, "posts": turn_references.MAX_POSTS, "attachments": turn_references.MAX_ATTACHMENTS, "videos": 1},
            "photo": {"accept": ["image/jpeg", "image/png"], "convertFrom": ["image/*"], "maxPickBytes": 30 * 1024 * 1024, "maxSendBytes": 3 * 1024 * 1024},
            "video": video,
            "notes": {"available": notes_available, "processor": reader.processor() if notes_available else None,
                      "photo": {"typicalMilliCredits": photo["typicalMilliCredits"], "ceilingMilliCredits": photo["ceilingMilliCredits"]} if photo else None,
                      "video": {"typicalMilliCredits": clip["typicalMilliCredits"], "ceilingMilliCredits": clip["ceilingMilliCredits"]} if clip else None,
                      "consentAction": "media_egress"},
            "skills": self.skills.eligible(),
        }

    def media_consent_current(self):
        """{vision, image}: the processors a photo or frame would go to now (their consent is bound to these)."""
        from . import media_consent
        reader = getattr(self.media_notes, "reader", None)
        vision = reader.processor() if reader is not None and self.notes_enabled else None
        image = media_consent.processor(getattr(self.image_runtime, "provider", None), getattr(self.image_runtime, "model", None)) if self.image_runtime is not None else None
        return {"vision": vision, "image": image}

    def rescan_models(self, workspace_id, token):
        """An editor may refresh installation and sign-in probes; no model generation runs."""
        with self.repository.transaction(token, workspace_id) as (_, row, actor):
            require(self._member(row), "edit")
        with self._catalog_lock:
            if self._discover_cli:
                for cli in (ClaudeCliRuntime, CodexCliRuntime):
                    if not any(type(runtime) is cli for runtime in self.runtimes) and cli.available():
                        self.runtimes.append(cli(clock=self.clock))
            for runtime in self.runtimes:
                if isinstance(runtime, ClaudeCliRuntime):
                    runtime.detect(force=True)
            return self.model_catalog(actor=actor)

    @staticmethod
    def _automation_selection(state, chosen):
        """(selection, preflight rule ids, note) for an automation's own content type. None = general writing.
        A type that is no longer offered falls back to general writing with a note, never a failed run."""
        return IdeasService._content_selection(state, chosen, note="This automation's content type is no longer available, so these drafts use general writing. Edit the automation to choose another type.")

    @staticmethod
    def _content_selection(state, chosen, *, note):
        """(selection, preflight rule ids, note) for a content type chosen by an automation or a template chip."""
        general = {"contentTypeId": "unclassified", "contentTypeVersion": None, "formatId": None}
        if not chosen:
            return general, (), None
        try:
            item = content_types.definition(state, chosen["contentTypeId"], chosen.get("contentTypeVersion"))
        except (AlphaError, KeyError, TypeError):
            return general, (), note
        return {"contentTypeId": item["id"], "contentTypeVersion": item["version"], "formatId": chosen.get("formatId")}, tuple(item.get("preflightRuleIds", ())), None

    def default_runtime(self):
        """The writer for a request that names no model. When a managed cloud writer is mounted, that one: the owner's
        rule is that no draft comes from templates unless the person chose them ("Templates (no AI model)" is the
        fixture's own id, so an explicit choice still reaches it). Otherwise the local default. This is a default for an
        absent choice, never a fallback: an unknown or refused model still raises, and a paid gate that refuses is
        never answered with template text."""
        return next((r for r in self.runtimes if getattr(r, "cost_class", None) == "paid" and getattr(r, "provider_class", None) == "cloud"), self.runtime)

    def _managed_writer(self):
        """The mounted managed paid cloud writer, or None."""
        runtime = self.default_runtime()
        return runtime if getattr(runtime, "cost_class", None) == "paid" and getattr(runtime, "provider_class", None) == "cloud" else None

    def resolve_writer(self, state, requested_model):
        """(runtime, model id, note|None) for the writer a request named. No model, "" or "auto" is Auto: the managed
        writer with the workspace default (writer_defaults.resolve, which says in `note` when a stored default is no
        longer offered), else the local default. An explicit id is today's choice, never substituted. `state` may be a
        callable, read only when Auto needs it. The resolved model is never written back into the caller's payload."""
        if requested_model in (None, "", AUTO):
            runtime = self.default_runtime()
            if runtime is self._managed_writer():
                model_id, _source, note = writer_defaults.resolve(state() if callable(state) else state, runtime)
                return runtime, model_id, note
            return runtime, runtime.model, None
        return self._select_runtime(requested_model), requested_model, None

    def _select_runtime(self, model_id):
        if not model_id or model_id == AUTO:
            return self.default_runtime()
        for runtime in self.runtimes:
            if runtime.owns(model_id):
                listed = next((m for m in runtime.list_supported_models() if m["id"] == model_id), None)
                if listed and listed.get("qualified"):
                    return runtime
                raise AlphaError(listed["detail"] if listed else "This model is not available right now.", 409)
        raise AlphaError("Choose a model listed for this workspace.", 400)

    def memory_files(self, workspace_id, token):
        from .learning_service import pending_proposals
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            state = self._state(row)
            learned = {**(self.learning.summary(state) if self.learning else learning.summary(state)), "pendingProposals": len(pending_proposals(cur, workspace_id))}
            from . import media_consent
            return {"files": memory.render_files(state), "egress": memory.egress_summary(state), "research": research.consent_summary(state), "learning": learned,
                    "media": media_consent.summary(state, self.media_consent_current())}

    def _read_request(self, workspace_id, token, text, zone, runtime):
        """Rafii's model reading of a message that may create, change or ask about an automation or a scheduled post
        (request_model); None when no model may read it or its answer is unusable, so the deterministic reading decides.
        A short, plain request goes to the light model; several stages, conditions, sources, platforms or an edit go to
        the strong one (request_model.tier; never shown to the person). A managed call's cost is reserved before the
        message leaves and settled after; a stop-line skips the reading, never the request."""
        from . import automation_edit, request_model, workflow_parse
        reservation = None
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            state = self._state(row)
            automations = automation_edit.summaries(state)
            # Changing an existing automation's plan is reasoning work (spec §12): it goes to the strong model.
            editing = bool(automations) and (bool(request_model._EDIT.search(text)) or workflow_parse.names_automation(text, [a["name"] for a in automations]))
            tier = request_model.tier(text, editing=editing)
            call = request_model.call_for(runtime, getattr(self, "understanding", None), tier)
            if call is None:
                return None
            user = request_model.user_prompt(text, zone, self.clock(), state, automations=automations or None)
            if not getattr(call, "local", False):
                cur.execute("SAVEPOINT understanding_reserve")
                try:
                    reservation = self.ledger.reserve(cur, workspace_id, principal, "text_model", request_model.price_quote_micro(state, user, tier), f"understanding:{uid()}",
                                                      charge_batch=False, provider="understanding", model=getattr(call, "model", "") or "")
                    cur.execute("RELEASE SAVEPOINT understanding_reserve")
                except AlphaError:
                    cur.execute("ROLLBACK TO SAVEPOINT understanding_reserve")
                    return None
        answer, actual = None, None
        try:
            result = call(request_model.SYSTEM_PROMPT, user, request_model.schema(state, tier))
            actual = getattr(result, "cost_usd_micro", None)
            answer = request_model.reading(result, state, tier, text=text)
        except Exception:  # noqa: BLE001 — a failed reading never blocks the request; the deterministic reading decides
            answer = None
        if reservation is not None:
            with self.repository.transaction(token, workspace_id) as (cur, _, _):
                self.ledger.settle(cur, workspace_id, reservation["reservationId"], "completed" if actual is not None else "unknown", actual)
        return answer

    def _understand(self, workspace_id, token, text, zone, runtime, parsed):
        """(parsed, reading): the model's decision wins over the deterministic one where a model may read."""
        from . import automation_edit, request_model, workflow_parse
        wanted = bool(text) and request_model.wants_reading(text)
        if text and not wanted:
            # A message that names one of the person's automations ("the Gramophone one") may be changing it.
            names = [item["name"] for item in automation_edit.summaries(self.repository.get(workspace_id, token)["state"])]
            wanted = workflow_parse.names_automation(text, names)
        understood = self._read_request(workspace_id, token, text, zone, runtime) if wanted else None
        if understood and understood["action"] == "draft" and parsed["intent"] == "automation":
            parsed = {**parsed, "intent": "schedule" if parsed["hasTimes"] else "draft"}
        if understood and understood["action"] == "automation":
            parsed = {**parsed, "intent": "automation"}
        return parsed, understood

    def _automation_turn(self, workspace_id, token, conversation_id, text, destinations, runtime, model_id, payload, revision=None, understood=None, writer_note=None):
        """A request to keep preparing drafts on a schedule: no run, no model, no charge. It becomes an automation with
        the Automations builder's checks (automation_chat); an owner's request is turned on when nothing is left for the
        owner to decide. The reply carries it as a card. Drafts only: nothing here schedules or publishes a post."""
        from . import automation_chat
        zone = intent.safe_zone(payload.get("timeZone"))
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            require(member, "edit")
            self._conversation(cur, workspace_id, conversation_id)
            current = row[0]
        provider_class = getattr(runtime, "provider_class", "local")
        voice_route = "local-cli" if provider_class == "local" else f"cloud:{runtime.provider}:{model_id}"
        # Attached references (Rafii v9 Context Pocket) are read on every run; voice samples never count as sources.
        source_ids = [item for item in dict.fromkeys(payload.get("sourceIds") or []) if isinstance(item, str) and item][:20]
        outcome, failure = {}, None

        def command(state, actor):
            outcome["view"] = automation_chat.create(
                state, actor, now, text, zone, destinations=destinations, route=model_id, voice_route=voice_route,
                reasoning=requested_level(payload), paid=runtime.cost_class == "paid",
                voice=payload.get("voiceMode") == "personalized", source_ids=source_ids, owner=member.allows("owner"), understood=understood)
            return state

        try:
            saved = self.repository.command(workspace_id, token, current if revision is None else revision, command)
            current = saved["revision"]
        except AlphaError as error:
            if getattr(error, "code", None) == "workspace_revision_conflict":
                raise
            failure = str(error)
        view = outcome.get("view") if failure is None else None
        reply = automation_chat.reply(view, failure)
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit")
            self._append_message(cur, workspace_id, conversation_id, "user", {"text": text, "sourceIds": source_ids, "intent": "automation"})
            message = self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": reply, "intent": "automation", "automation": view, "destinations": destinations, "plan": None, "model": model_id, "runId": None, **_warnings(writer_note)})
        return {"runId": None, "conversationId": conversation_id, "status": "automation", "artifactHash": None, "artifact": None,
                "usage": {"provenance": "none", "modelRequests": 0, "costUsd": 0}, "model": model_id, "reasoning": requested_level(payload),
                "events": [], "cursor": 0, "automation": view, "reply": reply, "messageId": message["messageId"], "revision": current}

    def _conversation_automation(self, workspace_id, token, conversation_id):
        """The automation this conversation is about and Rafii's open question, from the latest assistant replies."""
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT body FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND role='assistant' ORDER BY seq DESC LIMIT 6", (conversation_id, workspace_id))
            rows = [row[0] for row in cur.fetchall()]
        latest = rows[0] if rows else {}
        card = next(((body or {}).get("automation") for body in rows if isinstance((body or {}).get("automation"), dict)), None) or {}
        pending = (latest or {}).get("automation", {}).get("pending") if isinstance((latest or {}).get("automation"), dict) else None
        return {"taskId": card.get("taskId"), "pending": pending}

    def _publishing_context(self):
        service = getattr(self, "service_ref", None)
        providers = getattr(getattr(service, "oauth", None), "providers", None) or {}
        return providers, bool(getattr(service, "publishing_live", False))

    def _may_orchestrate(self, workspace_id, token, text, parsed, reading):
        """Whether a Home message could be an automation request, an edit or a question about one (cheap checks only)."""
        from . import automation_edit, workflow_parse
        if (reading or {}).get("action") in ("automation", "edit", "explain") or parsed["intent"] == "automation" or workflow_parse.is_scheduled_post(text) or workflow_parse.is_recurring_request(text):
            return True
        if (workflow_parse.is_edit(text) or workflow_parse.is_explain(text)) and not workflow_parse.is_drafting_request(text):
            state = self.repository.get(workspace_id, token)["state"]
            names = [item["name"] for item in automation_edit.summaries(state)]
            return bool(names) and workflow_parse.refers_to_automation(text, names, False)
        return False

    def _orchestration_turn(self, workspace_id, token, conversation_id, text, parsed, reading, destinations, runtime, model_id, payload, writer_note=None):
        """Route a chat message that answers Rafii's question, changes or asks about an automation, or asks for a staged
        automation (publishing, stages, research, a one-time post). None leaves it to the drafting or drafts-automation path."""
        from . import automation_edit, automation_plan, workflow_parse
        zone = intent.safe_zone(payload.get("timeZone"))
        now = self.clock()
        context = self._conversation_automation(workspace_id, token, conversation_id)
        state = self.repository.get(workspace_id, token)["state"]
        has_automations = bool(automation_edit.live_tasks(state))
        pending = context.get("pending")
        if pending and pending.get("taskId") and not workflow_parse.is_drafting_request(text) and len(text.split()) <= 14 and any(t["id"] == pending["taskId"] for t in automation_edit.live_tasks(state)):
            task = next(t for t in automation_edit.live_tasks(state) if t["id"] == pending["taskId"])
            if pending.get("question") == "policy":
                policy = automation_plan.answer_policy(text)
                if policy:
                    return self._orchestrate(workspace_id, token, conversation_id, text, "answer", runtime, model_id, payload, {"pending": pending, "policy": policy}, reading, writer_note)
            elif pending.get("question") == "review_time":
                try:
                    spec = automation_plan.answer_review_time(text, task["schedule"])
                except AlphaError:
                    spec = None
                if spec:
                    return self._orchestrate(workspace_id, token, conversation_id, text, "answer", runtime, model_id, payload, {"pending": pending, "generate": spec}, reading, writer_note)
        action = (reading or {}).get("action")
        if len({d.get("localTime") for d in parsed.get("destinations") or [] if d.get("localTime")}) > 1 and not intent._RECUR.search(text):
            # Different times for different channels in one message: the per-channel scheduling plan handles it.
            return None
        if action is None:
            # Without a model reading, a message is about an automation only when it names one (or says
            # "automation"), or points at the one this conversation is about; a request to write something now is
            # always drafted ("pause before the chorus — write a post about that").
            names = [item["name"] for item in automation_edit.summaries(state)]
            about = has_automations and not workflow_parse.is_drafting_request(text) and workflow_parse.refers_to_automation(text, names, bool(context.get("taskId")))
            if about and workflow_parse.is_explain(text):
                action = "explain"
            elif about and workflow_parse.is_edit(text) and not intent.is_automation_request(text):
                action = "edit"
            elif parsed["intent"] == "automation" or workflow_parse.is_scheduled_post(text) or workflow_parse.is_recurring_request(text):
                action = "automation"
        if action == "explain" and has_automations:
            explain = (reading or {}).get("explain") or workflow_parse.read_explain(text)
            return self._orchestrate(workspace_id, token, conversation_id, text, "explain", runtime, model_id, payload, {"explain": explain, "taskId": context.get("taskId")}, reading, writer_note)
        if action == "edit" and has_automations:
            edit = (reading or {}).get("edit") or workflow_parse.read_edit(text, now, zone)
            if edit.get("changes"):
                return self._orchestrate(workspace_id, token, conversation_id, text, "edit", runtime, model_id, payload, {"edit": edit, "taskId": context.get("taskId")}, reading, writer_note)
        if action == "automation":
            automation = (reading or {}).get("automation") if (reading or {}).get("action") == "automation" else None
            automation = automation or workflow_parse.read_automation(text, now, zone)
            if automation.get("schedule") and automation_plan.needs_workflow(automation, text):
                return self._orchestrate(workspace_id, token, conversation_id, text, "create", runtime, model_id, payload, {"automation": automation, "destinations": destinations}, reading, writer_note)
        return None

    def _orchestrate(self, workspace_id, token, conversation_id, text, kind, runtime, model_id, payload, detail, reading, writer_note=None):
        """Create, answer, edit or explain an automation in one workspace command, then record both turns."""
        from . import automation_edit, automation_explain, automation_plan, campaigns, workflow_parse
        zone = intent.safe_zone(payload.get("timeZone"))
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            require(member, "edit" if kind != "explain" else "read")
            self._conversation(cur, workspace_id, conversation_id)
            current = row[0]
        provider_class = getattr(runtime, "provider_class", "local")
        voice_route = "local-cli" if provider_class == "local" else f"cloud:{runtime.provider}:{model_id}"
        source_ids = [item for item in dict.fromkeys(payload.get("sourceIds") or []) if isinstance(item, str) and item][:20]
        providers, live = self._publishing_context()
        tier = (reading or {}).get("tier")
        owner, paid = member.allows("owner"), runtime.cost_class == "paid"
        outcome, failure = {}, None

        def command(state, actor):
            if kind == "create":
                automation = detail["automation"]
                built, question, notes = automation_plan.build(state, actor, now, text, zone, automation, destinations=detail["destinations"], route=model_id,
                                                               reasoning=requested_level(payload), voice=payload.get("voiceMode") == "personalized",
                                                               voice_route=voice_route, source_ids=source_ids)
                saved = campaigns.apply_action(state, "raffi_recurrence_save", built, actor, now)
                explicit = built["workflow"].get("policy") == "auto" and workflow_parse.explicit_auto(text)
                grant = {"confirmed": True, "sourceUse": bool(built["workflow"].get("research"))} if explicit else None
                needs = automation_plan.activate(state, saved["taskId"], actor, now, owner=owner, paid=paid, question=question, grant=grant)
                outcome["view"] = automation_plan.card(state, saved["taskId"], needs, notes, question=question, providers=providers, live=live, tier=tier)
                if question:
                    outcome["view"]["pending"].update(stages=(automation.get("stages") or {}), timeRole=automation.get("timeRole"))
            elif kind == "answer":
                pending = detail["pending"]
                task = next(t for t in campaigns._root(state)["recurringTasks"] if t["id"] == pending["taskId"])
                built = automation_edit._payload(state, task)
                workflow = built["workflow"] or {}
                given = {"policy": detail.get("policy") or workflow.get("policy"), "stages": pending.get("stages") or {}, "timeRole": pending.get("timeRole") or "publish"}
                stages, question = automation_plan.stages_for(given, built["schedule"], given["policy"])
                if detail.get("generate"):
                    stages, question = {**stages, "generate": detail["generate"], "review": {"at": "generate"}}, None
                workflow.update(policy=given["policy"], stages=stages)
                built["workflow"] = workflow
                campaigns.apply_action(state, "raffi_recurrence_save", built, actor, now)
                # "Publish automatically" (the button or the owner's explicit words) is the standing authority.
                grant = {"confirmed": True, "sourceUse": bool(workflow.get("research"))} if given["policy"] == "auto" and detail.get("policy") == "auto" else None
                needs = automation_plan.activate(state, task["id"], actor, now, owner=owner, paid=paid, question=question, grant=grant)
                outcome["view"] = automation_plan.card(state, task["id"], needs, [], question=question, providers=providers, live=live, tier=tier)
                if question:
                    outcome["view"]["pending"].update(stages=pending.get("stages") or {}, timeRole=pending.get("timeRole"))
            elif kind == "edit":
                result = automation_edit.apply(state, actor, now, detail["edit"], conversation_task_id=detail.get("taskId"), owner=owner, paid=paid, zone=zone)
                outcome["edit"] = result
                if "view" in result:
                    result["view"] = automation_plan.card(state, result["task"], result["view"].get("needs") or [], [], providers=providers, live=live, tier=tier)
            return state

        if kind == "explain":
            snapshot = self.repository.get(workspace_id, token)
            explained = automation_explain.answer(snapshot["state"], text, detail["explain"], conversation_task_id=detail.get("taskId"), now=now)
            view, reply = None, explained["text"]
            body_extra = {"explain": {k: explained.get(k) for k in ("lines", "about", "taskId", "occurrenceId")}}
        else:
            try:
                saved = self.repository.command(workspace_id, token, current, command)
                current = saved["revision"]
            except AlphaError as error:
                if getattr(error, "code", None) == "workspace_revision_conflict":
                    raise
                failure = str(error)
            body_extra = {}
            if kind == "edit" and failure is None:
                result = outcome["edit"]
                view = result.get("view")
                reply = automation_edit.reply(result)
            else:
                view = outcome.get("view") if failure is None else None
                reply = automation_plan.reply(view, failure) if kind != "edit" else f"I couldn't change that: {failure}"
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit" if kind != "explain" else "read")
            self._append_message(cur, workspace_id, conversation_id, "user", {"text": text, "sourceIds": source_ids, "intent": "automation"})
            message = self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": reply, "intent": "automation", "automation": view, "destinations": [], "plan": None, "model": model_id, "runId": None, "understanding": tier, **body_extra, **_warnings(writer_note)})
        return {"runId": None, "conversationId": conversation_id, "status": "automation", "artifactHash": None, "artifact": None,
                "usage": {"provenance": "none", "modelRequests": 0, "costUsd": 0}, "model": model_id, "reasoning": requested_level(payload),
                "events": [], "cursor": 0, "automation": view, "reply": reply, "messageId": message["messageId"], "revision": current, **body_extra}

    def _memory_turn(self, workspace_id, token, conversation_id, text, parsed, destinations, model_id, writer_note=None):
        """A standing instruction about how to write: no run, no model, no charge. The instruction becomes a
        proposal the owner decides (preference-learning design §5.5); the reply carries it as a card."""
        from .learning_chat import instruction_to_proposal
        from .learning_service import proposal_view
        hosted = self.learning
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            self._append_message(cur, workspace_id, conversation_id, "user", {"text": text, "sourceIds": [], "intent": "memory"})
            proposal = instruction_to_proposal(text, parsed.get("language"))
            created, refusal = None, None
            if hosted is None:
                refusal = "Preference learning isn't available yet, so nothing was kept."
            else:
                try:
                    created = hosted.propose_from_chat(cur, workspace_id, state, proposal, principal, self.clock())
                except ValueError as error:
                    refusal = str(error)
            if created is not None:
                view = proposal_view(created)
                reply = f"Remember this for {view['scopeLabel']}? “{view['statement']}” It only shapes future drafts once you accept it."
            elif refusal:
                view, reply = None, refusal
            else:
                view, reply = None, "That is already how Rafii writes for you, or a matching suggestion is waiting on the Memory page."
            body = {"text": reply, "intent": "memory", "memoryProposal": view, "destinations": destinations, "plan": None, "model": model_id, "runId": None, **_warnings(writer_note)}
            message = self._append_message(cur, workspace_id, conversation_id, "assistant", body)
        return {"runId": None, "conversationId": conversation_id, "status": "memory", "artifactHash": None, "artifact": None, "usage": {"provenance": "none", "modelRequests": 0, "costUsd": 0},
                "model": model_id, "reasoning": "quick", "events": [], "cursor": 0, "memoryProposal": view, "messageId": message["messageId"]}

    # --- helpers -------------------------------------------------------------------
    @staticmethod
    def _state(row):
        return json.loads(row[1]) if isinstance(row[1], str) else row[1]

    @staticmethod
    def _member(row):
        from .permissions import Membership
        return Membership.from_row(*row[2:7])

    def _conversation(self, cur, workspace_id, conversation_id):
        cur.execute("SELECT id::text,title,created_by::text,extract(epoch from created_at),extract(epoch from updated_at),archived_at IS NOT NULL FROM public.pr_conversations WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (conversation_id, workspace_id))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Conversation unavailable.", 404)
        return {"conversationId": row[0], "title": row[1], "createdBy": row[2], "createdAt": float(row[3]), "updatedAt": float(row[4]), "archived": bool(row[5])}

    def _append_message(self, cur, workspace_id, conversation_id, role, body, run_id=None):
        cur.execute("SELECT coalesce(max(seq),0)+1 FROM public.pr_messages WHERE conversation_id::text=%s", (conversation_id,))
        seq = cur.fetchone()[0]
        cur.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body,run_id) VALUES(%s,%s,%s,%s,%s::jsonb,%s) RETURNING id::text", (conversation_id, workspace_id, seq, role, json.dumps(body), run_id))
        message_id = cur.fetchone()[0]
        cur.execute("UPDATE public.pr_conversations SET updated_at=now() WHERE id::text=%s", (conversation_id,))
        return {"messageId": message_id, "seq": seq, "role": role, "body": body}

    # --- conversations -------------------------------------------------------------
    def conversations(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT id::text,title,created_by::text,extract(epoch from created_at),extract(epoch from updated_at),archived_at IS NOT NULL FROM public.pr_conversations WHERE workspace_id=%s ORDER BY updated_at DESC LIMIT 100", (workspace_id,))
            return {"conversations": [{"conversationId": r[0], "title": r[1], "createdBy": r[2], "createdAt": float(r[3]), "updatedAt": float(r[4]), "archived": bool(r[5])} for r in cur.fetchall()]}

    def navigation_conversations(self, workspace_id, token, cursor=None, limit=40):
        """Keyset page of real conversation activity; no message bodies leave this route."""
        if type(limit) is not int or not 1 <= limit <= 60:
            raise AlphaError("Invalid navigation limit.", 400)
        after = None
        if cursor:
            try:
                after = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if not (isinstance(after, list) and len(after) == 2 and isinstance(after[0], str)):
                    raise ValueError()
                uuid.UUID(after[1])
            except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as error:
                raise AlphaError("Invalid conversation cursor.", 400) from error
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("""SELECT c.id::text,c.title,extract(epoch from c.updated_at),c.updated_at::text,
                                  c.archived_at IS NOT NULL,
                                  (SELECT count(*) FROM public.pr_messages m WHERE m.workspace_id=c.workspace_id AND m.conversation_id=c.id),
                                  (SELECT left(m.body->>'text',180) FROM public.pr_messages m
                                   WHERE m.workspace_id=c.workspace_id AND m.conversation_id=c.id AND length(trim(m.body->>'text'))>0
                                   ORDER BY m.seq DESC LIMIT 1)
                           FROM public.pr_conversations c WHERE c.workspace_id=%s
                             AND (%s::timestamptz IS NULL OR (c.updated_at,c.id)<(%s::timestamptz,%s::uuid))
                           ORDER BY c.updated_at DESC,c.id DESC LIMIT %s""",
                        (workspace_id, after[0] if after else None, after[0] if after else None,
                         after[1] if after else None, limit + 1))
            rows = cur.fetchall()
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page:
            next_cursor = base64.urlsafe_b64encode(json.dumps([page[-1][3], page[-1][0]]).encode()).decode().rstrip("=")
        return {"conversations": [{"conversationId": r[0], "title": r[1], "updatedAt": float(r[2]),
                                   "archived": bool(r[4]), "messageCount": r[5], "excerpt": r[6] or ""} for r in page],
                "nextCursor": next_cursor}

    def navigation_search(self, workspace_id, token, query):
        if not isinstance(query, str) or len(query.strip()) < 2 or len(query) > 100:
            raise AlphaError("Search for at least two characters.", 400)
        term = "%" + query.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            # Trigram GIN indexes in 041 cover substring searches (including CJK). The workspace predicate is mandatory.
            cur.execute("""SELECT c.id::text,c.title,extract(epoch from c.updated_at)
                           FROM public.pr_conversations c WHERE c.workspace_id=%s
                             AND c.title ILIKE %s ESCAPE '!'
                           ORDER BY c.updated_at DESC LIMIT 15""", (workspace_id, term))
            titles = [{"kind": "conversation", "conversationId": r[0], "title": r[1], "at": float(r[2])} for r in cur.fetchall()]
            cur.execute("""SELECT m.id::text,m.conversation_id::text,c.title,m.seq,left(m.body->>'text',180),extract(epoch from m.created_at)
                           FROM public.pr_messages m JOIN public.pr_conversations c
                             ON c.id=m.conversation_id AND c.workspace_id=m.workspace_id
                           WHERE m.workspace_id=%s AND m.body->>'text' ILIKE %s ESCAPE '!'
                           ORDER BY m.created_at DESC LIMIT 30""", (workspace_id, term))
            turns = [{"kind": "turn", "messageId": r[0], "conversationId": r[1], "title": r[2],
                      "seq": r[3], "excerpt": r[4] or "", "at": float(r[5])} for r in cur.fetchall()]
        return {"results": titles + turns}

    def navigation(self, workspace_id, token, conversation_id, cursor=0, limit=100):
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise AlphaError("Invalid navigation cursor or limit.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            state = self._state(row)
            self._conversation(cur, workspace_id, conversation_id)
            cur.execute("""SELECT id::text,seq,role,left(coalesce(body->>'text',''),180),extract(epoch from created_at),
                                  body->>'intent',body->'plan' IS NOT NULL AND body->'plan'<>'null'::jsonb,
                                  body->'automation' IS NOT NULL AND body->'automation'<>'null'::jsonb,
                                  body ? 'images',body ? 'attachments',body->'siteAgent'->>'status',
                                  body->'memoryProposal' IS NOT NULL AND body->'memoryProposal'<>'null'::jsonb,
                                  body->>'failed',body->>'pending',
                                  body->'research' IS NOT NULL AND body->'research'<>'null'::jsonb,
                                  body ? 'artifactHash',body->'siteAgent'->>'intent'
                           FROM public.pr_messages WHERE workspace_id=%s AND conversation_id::text=%s AND seq>%s
                           ORDER BY seq LIMIT %s""", (workspace_id, conversation_id, cursor, limit + 1))
            rows = cur.fetchall()
            page = rows[:limit]
            end = page[-1][1] if page else cursor
            cur.execute("""SELECT id::text,after_seq,title,seconds,created_at,asset_id::text
                           FROM public.pr_media_moments WHERE workspace_id=%s AND conversation_id::text=%s
                             AND after_seq>%s AND after_seq<=%s ORDER BY after_seq,created_at""",
                        (workspace_id, conversation_id, cursor, end))
            moments = cur.fetchall()
            cur.execute("SELECT count(*) FROM public.pr_messages WHERE workspace_id=%s AND conversation_id::text=%s",
                        (workspace_id, conversation_id))
            total = cur.fetchone()[0]
        def kind(r):
            if r[2] == "user": return "user_request"
            if r[12] == "true" or r[10] == "failed": return "error"
            if r[7] or r[5] == "automation": return "automation"
            if r[6] or r[11] or r[10] == "approval_required": return "approval_required"
            if r[8] or r[9]: return "media"
            if r[14] or r[5] == "research": return "research"
            if r[5] in ("published", "scheduled") or r[16] in ("published", "scheduled"): return "completion"
            if r[15] or r[5] in ("draft", "image_generation"): return "draft"
            return "rafii_decision"
        items = [{"kind": kind(r), "messageId": r[0], "seq": r[1], "role": r[2], "excerpt": r[3],
                  "at": float(r[4]), "intent": r[5]} for r in page]
        items += [{"kind": "moment", "momentId": r[0], "seq": r[1], "excerpt": r[2],
                   "seconds": float(r[3]), "at": r[4].timestamp(), "assetId": _workspace_asset_id(state, r[5])} for r in moments]
        return {"items": items, "nextCursor": end if len(rows) > limit else None, "totalMessages": total}

    def message_window(self, workspace_id, token, conversation_id, anchor=None, before=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100 or (before is not None and (type(before) is not int or before < 1)):
            raise AlphaError("Invalid message window.", 400)
        if anchor:
            try: uuid.UUID(anchor)
            except ValueError as error: raise AlphaError("Invalid turn link.", 400) from error
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            state = self._state(row)
            conversation = self._conversation(cur, workspace_id, conversation_id)
            if anchor:
                cur.execute("SELECT seq FROM public.pr_messages WHERE id::text=%s AND conversation_id::text=%s AND workspace_id=%s",
                            (anchor, conversation_id, workspace_id))
                found = cur.fetchone()
                if not found:
                    cur.execute("SELECT after_seq FROM public.pr_media_moments WHERE id::text=%s AND conversation_id::text=%s AND workspace_id=%s",
                                (anchor, conversation_id, workspace_id))
                    found = cur.fetchone()
                if not found: raise AlphaError("Turn unavailable.", 404)
                center = found[0]
                lower, upper = max(0, center - limit // 2 - 1), center + limit // 2
            elif before:
                lower, upper = max(0, before - limit - 1), before - 1
            else:
                cur.execute("SELECT coalesce(max(seq),0) FROM public.pr_messages WHERE workspace_id=%s AND conversation_id::text=%s", (workspace_id, conversation_id))
                upper = cur.fetchone()[0]
                lower = max(0, upper - limit)
            cur.execute("""SELECT id::text,seq,role,body,run_id::text,extract(epoch from created_at)
                           FROM public.pr_messages WHERE workspace_id=%s AND conversation_id::text=%s AND seq>%s AND seq<=%s
                           ORDER BY seq LIMIT %s""", (workspace_id, conversation_id, lower, upper, limit))
            rows = cur.fetchall()
            first = rows[0][1] if rows else None
            last = rows[-1][1] if rows else None
            cur.execute("""SELECT id::text,after_seq,source,title,asset_id::text,seconds,timestamp_label,
                                  extract(epoch from created_at)
                           FROM public.pr_media_moments WHERE workspace_id=%s AND conversation_id::text=%s
                             AND after_seq>=%s AND after_seq<=%s ORDER BY after_seq,created_at""",
                        (workspace_id, conversation_id, first or 0, last or 0))
            moments = cur.fetchall()
            cur.execute("SELECT coalesce(max(seq),0) FROM public.pr_messages WHERE workspace_id=%s AND conversation_id::text=%s", (workspace_id, conversation_id))
            max_seq = cur.fetchone()[0]
        return {**conversation, "messages": [{"messageId": r[0], "seq": r[1], "role": r[2], "body": r[3], "runId": r[4], "at": float(r[5])} for r in rows],
                "moments": [{"momentId": r[0], "afterSeq": r[1], "source": r[2], "title": r[3],
                             "assetId": _workspace_asset_id(state, r[4]), "seconds": float(r[5]), "timestamp": r[6], "createdAt": float(r[7])} for r in moments],
                "hasOlder": bool(first and first > 1), "hasNewer": bool(last and last < max_seq)}

    def save_moment(self, workspace_id, token, conversation_id, payload):
        from . import asset_kinds
        asset_id = payload.get("assetId")
        seconds = payload.get("seconds")
        if not isinstance(asset_id, str) or not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or not 0 <= seconds < 86400:
            raise AlphaError("Choose a valid video moment.", 400)
        try: uuid.UUID(asset_id)
        except ValueError as error: raise AlphaError("Choose a valid video moment.", 400) from error
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            asset = next((a for a in state.get("phase2", {}).get("assets", []) if a.get("id") == asset_id and asset_kinds.kind_of(a) == "video" and asset_kinds.is_ready(a)), None)
            if not asset or (asset.get("duration") and seconds > float(asset["duration"]) + 1):
                raise AlphaError("This video is unavailable in the workspace.", 404)
            title = clean(payload.get("title") or "Saved video", 200)
            timestamp = f"{int(seconds) // 3600:02d}:{(int(seconds) // 60) % 60:02d}:{int(seconds) % 60:02d}" if seconds >= 3600 else f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
            cur.execute("SELECT coalesce(max(seq),0) FROM public.pr_messages WHERE workspace_id=%s AND conversation_id::text=%s", (workspace_id, conversation_id))
            after_seq = cur.fetchone()[0]
            cur.execute("""INSERT INTO public.pr_media_moments(workspace_id,conversation_id,created_by,after_seq,source,title,asset_id,seconds,timestamp_label)
                           VALUES(%s,%s,%s,%s,'rafii_asset',%s,%s,%s,%s)
                           RETURNING id::text,extract(epoch from created_at)""",
                        (workspace_id, conversation_id, principal, after_seq, title, asset_id, seconds, timestamp))
            moment_id, created_at = cur.fetchone()
            cur.execute("UPDATE public.pr_conversations SET updated_at=now() WHERE id::text=%s AND workspace_id=%s", (conversation_id, workspace_id))
        return {"momentId": moment_id, "conversationId": conversation_id, "workspaceId": workspace_id,
                "afterSeq": after_seq, "source": "rafii_asset", "title": title, "assetId": asset_id,
                "seconds": seconds, "timestamp": timestamp, "createdAt": float(created_at)}

    def create_conversation(self, workspace_id, token, title=""):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text", (workspace_id, principal, clean(title or "New idea", 200)))
            conversation_id = cur.fetchone()[0]
            self.runtime.start_conversation(workspace_id, principal)
            return {"conversationId": conversation_id, "title": clean(title or "New idea", 200)}

    def messages(self, workspace_id, token, conversation_id, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise AlphaError("Invalid message cursor.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            conversation = self._conversation(cur, workspace_id, conversation_id)
            cur.execute("SELECT id::text,seq,role,body,run_id::text,extract(epoch from created_at) FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND seq>%s ORDER BY seq LIMIT 500", (conversation_id, workspace_id, cursor))
            return {**conversation, "messages": [{"messageId": r[0], "seq": r[1], "role": r[2], "body": r[3], "runId": r[4], "at": float(r[5])} for r in cur.fetchall()]}

    def attach(self, workspace_id, token, conversation_id, payload):
        """Attach a permitted source (text/markdown ≤ 20 KB), an existing private asset, or a link."""
        kind = payload.get("kind")
        if kind not in ("source", "asset", "link"):
            raise AlphaError("Attach a text/markdown source, an uploaded image, or a link.")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            if kind == "asset":
                asset = next((a for a in state.get("phase2", {}).get("assets", []) if a["id"] == payload.get("assetId") and not a.get("deleted")), None)
                if not asset:
                    raise AlphaError("Upload the image to this workspace first.", 404)
                ref = {"assetId": asset["id"], "hash": asset["hash"], "mime": asset["mime"]}
            else:
                ref = {"sourceId": payload.get("sourceId")} if kind == "source" else {"url": clean(payload.get("url", ""), 2000)}
                if kind == "source" and not any(s["id"] == ref["sourceId"] and s.get("active") for s in state.get("sources", [])):
                    raise AlphaError("Add the source to this workspace first.", 404)
            cur.execute("INSERT INTO public.pr_attachments(conversation_id,workspace_id,kind,ref,created_by) VALUES(%s,%s,%s,%s::jsonb,%s) RETURNING id::text", (conversation_id, workspace_id, kind, json.dumps(ref), principal))
            return {"attachmentId": cur.fetchone()[0], "kind": kind, "ref": ref}

    # --- runs ----------------------------------------------------------------------
    @staticmethod
    def _lock_run_events(cur, workspace_id, run_id):
        """One event writer per run at a time, in a fixed order so a background sink and a request
        never deadlock: first the workspace update lock (matching request transactions), then the
        per-run advisory lock, and only after both any FOR UPDATE on the run row itself."""
        cur.execute("SELECT 1 FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("pr_agent_events:" + run_id,))

    def _insert_event(self, cur, workspace_id, run_id, event):
        if event["type"] not in SAFE_EVENTS:
            raise AlphaError("Unsupported client event.", 500)
        self._lock_run_events(cur, workspace_id, run_id)
        cur.execute("SELECT coalesce(max(seq),0)+1 FROM public.pr_agent_events WHERE run_id::text=%s", (run_id,))
        seq = cur.fetchone()[0]
        if seq > MAX_EVENTS:
            raise AlphaError("Event limit reached.", 413)
        body = {k: v for k, v in event.items() if k != "type"}
        cur.execute("INSERT INTO public.pr_agent_events(run_id,workspace_id,seq,kind,body) VALUES(%s,%s,%s,%s,%s::jsonb)", (run_id, workspace_id, seq, event["type"], json.dumps(body, ensure_ascii=False)))
        return seq

    def _finish(self, cur, workspace_id, conversation_id, run_id, artifact, usage, outcome):
        """Settle, attach the plan, hash and store the candidate, and tell the conversation. Shared by every route."""
        cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        state_row = cur.fetchone()
        if not state_row:
            raise AlphaError("Workspace unavailable.", 404)
        current_state = json.loads(state_row[0]) if isinstance(state_row[0], str) else state_row[0]
        if outcome.get('recurringBinding'):
            from .campaign_worker import validate
            validate(current_state, outcome['recurringBinding'])
        if outcome.get("actor"):
            cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, outcome['actor']))
            member = cur.fetchone()
            if not member:
                raise AlphaError("Workspace access was revoked while writing.", 403)
            require(self._member((None, None, *member)), "owner" if outcome.get('recurringBinding') else "edit")
        if outcome.get('apiTokenId'):
            cur.execute("SELECT scopes FROM public.pr_api_tokens WHERE id::text=%s AND workspace_id=%s AND created_by=%s AND revoked_at IS NULL AND expires_at>to_timestamp(%s) FOR SHARE", (outcome['apiTokenId'], workspace_id, outcome['actor'], self.clock()))
            grant = cur.fetchone()
            if not grant or 'draft' not in grant[0]:
                raise AlphaError('The API token was revoked or expired while writing.', 403)
        if outcome.get('sessionId'):
            cur.execute("SELECT 1 FROM public.pr_session_revocations WHERE user_id=%s AND session_id=%s", (outcome['actor'], outcome['sessionId']))
            if cur.fetchone():
                raise AlphaError('The session was revoked while writing.', 403)
        previous = outcome['context']
        current = project_context(current_state, previous['operation'], previous['providerClass'], [s['id'] for s in previous['sources']])
        if current['sources'] != previous['sources']:
            raise AlphaError("Selected sources or their permissions changed while writing. Review a new candidate.", 409)
        voice_sources.validate_bindings(current_state, outcome.get("voiceContext") or {})
        cost_known = "costUsd" in usage and usage.get("costUsd") is not None
        settlement = self.ledger.settle(
            cur,
            workspace_id,
            outcome["reservationId"],
            "completed" if cost_known or not usage.get("modelRequests") else "unknown",
            usd_micro(usage["costUsd"]) if cost_known else None,
        )
        if outcome["plan"]:
            artifact["plan"] = outcome["plan"]  # a proposal; approval still runs the review → approve chain
        researched = outcome.get("research") or {}
        web_pages = researched.get("pages") or []
        if web_pages:
            hosts = ", ".join(dict.fromkeys(research.host_of(p["url"]) or p["url"] for p in web_pages))
            for variant in artifact["variants"]:
                variant.setdefault("warnings", []).append(f"Some facts came from web research ({hosts}); check them against the pages before scheduling.")
        if outcome.get("reworkOf"):
            artifact["reworkOf"] = outcome["reworkOf"]
        if outcome.get("forCampaign"):
            artifact["forCampaign"] = outcome["forCampaign"]
        if outcome.get("scoutLineage"):
            from .growth.scout import validate_lineage
            validate_lineage(current_state, outcome["scoutLineage"])
            artifact["scoutLineage"] = outcome["scoutLineage"]
        if outcome.get("trendLineage"):
            from .growth.trends.service import validate_stored_bindings
            validate_stored_bindings(self.repository.connection_factory, cur, workspace_id, outcome["actor"], current_state,
                                     outcome["trendLineage"], self.clock())
            artifact["trendLineage"] = copy.deepcopy(outcome["trendLineage"])
        artifact["sourceBindings"] = [{"id": item["id"], "hash": item["hash"]} for item in outcome["context"]["sources"]]
        references = outcome.get("references")
        if references is not None:
            # Chat-context SPEC §5.10: post media and the per-message content type travel with the artifact and every
            # variant, so "Save as drafts" keeps them; derived provenance ids make retraction and policy checks see them.
            media = list(outcome.get("media") or [])
            artifact["media"] = media
            if outcome.get("contentType"):
                artifact["contentType"] = outcome["contentType"]
            artifact["derivedSourceIds"] = list(outcome.get("derivedSourceIds") or [])
            for variant in artifact["variants"]:
                variant["media"] = media
                if outcome.get("contentType"):
                    variant.update({k: outcome["contentType"].get(k) for k in ("contentTypeId", "contentTypeVersion", "formatId")})
        artifact["voiceContext"] = {key: (outcome.get("voiceContext") or {}).get(key) for key in ("mode", "bindings", "digest", "route")}
        # Structured native drafts (creation projection): public fields in their own slots, bindings and private notes
        # apart, media and constraint states explicit. `text` is untouched, so every existing reader sees the same copy.
        from .creation_capabilities import attach_native
        attach_native(artifact["variants"], bindings=outcome.get("skillBindings") or [], omissions=outcome.get("skillOmissions") or [])
        artifact_hash = digest(artifact)
        usage = {**usage, "billing": usage.get("billing") or settlement.get("state"), "ledgerCostState": settlement.get("state"), "skillBindings": outcome.get("skillBindings", []), "skillOmissions": outcome.get("skillOmissions", []), "memoryBindings": outcome.get("memoryBindings"), "voiceBindings": artifact["voiceContext"].get("bindings", [])}
        if references is not None:
            usage.update({"references": references, "media": artifact.get("media", [])})
        cur.execute("UPDATE public.pr_agent_runs SET status='completed',artifact=%s::jsonb,artifact_hash=%s,usage=usage || %s::jsonb,updated_at=now() WHERE id::text=%s", (json.dumps(artifact, ensure_ascii=False), artifact_hash, json.dumps(usage), run_id))
        context = outcome["context"]
        found = f", {len(web_pages)} found on the web" if web_pages else ""
        total = len(references["used"]) + len(references["unused"]) if references else 0
        attached = f", using {len(references['used'])} of {total} attached items" if total else ""
        summary = {"text": f"Drafted {len(artifact['variants'])} candidate variants from {len(context['sources'])} approved sources{found}{attached}.", "runId": run_id, "research": researched or None, "artifactHash": artifact_hash, "excluded": context["excluded"], "candidateOnly": context["candidateOnly"], "intent": outcome["parsed"]["intent"], "destinations": outcome["destinations"], "plan": outcome["plan"], "model": outcome["model"], "skills": [b["id"] for b in outcome.get("skillBindings", [])], "memory": outcome.get("memoryBindings")}
        if references is not None:
            summary["references"] = references
        self._settle_message(cur, workspace_id, conversation_id, run_id, summary)
        return artifact_hash

    def _settle_message(self, cur, workspace_id, conversation_id, run_id, body):
        """Fill the assistant turn for this run: update the pending placeholder if one exists, else append."""
        cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE conversation_id::text=%s AND workspace_id=%s AND run_id::text=%s AND role='assistant' RETURNING id::text", (json.dumps(body, ensure_ascii=False), conversation_id, workspace_id, run_id))
        if cur.fetchone() is None:
            self._append_message(cur, workspace_id, conversation_id, "assistant", body, run_id)
        else:
            cur.execute("UPDATE public.pr_conversations SET updated_at=now() WHERE id::text=%s", (conversation_id,))

    def _research(self, workspace_id, token, payload, text, parsed, key, conversation_id, *, reworking=False):
        """Step ①b: when the turn needs facts the workspace does not hold, look them up on the web before
        drafting (design §11 Phase 5). Runs outside the run's transaction because it is network I/O; the
        pages become ordinary third-party sources (use still needs the person's approval to publish) with
        provenance, so every claim in the draft traces to a page. Returns (new source ids, record)."""
        if self.researcher is None or payload.get("research") is False:
            return [], None
        message = text or clean(payload.get("intentText", ""), MAX_TEXT)
        if reworking and not research.urls_in(message):
            # A turn that reworks material (a handed-in draft or campaign brief, or a post chip in the rework role) writes
            # from it: its instruction ("Shorten this draft", "Adapt this for Instagram") is not a topic to look up.
            return [], None
        snapshot = self.repository.get(workspace_id, token)
        state = snapshot["state"]
        stamp(state)
        # Material the person supplied for this turn (explicit sources with approved facts, other than
        # the idea text itself) is used as is; the workspace's other sources say nothing about this topic.
        if not research.allowed(state):
            wants = research.needs_research(message, parsed["intent"], False)
            return [], (research.off_record(research.query_for(message)) if wants else None)
        selected = payload.get("sourceIds") if isinstance(payload.get("sourceIds"), list) else []
        has_facts = any(f.get("approved") for s in state.get("sources", []) if s.get("active") and s["id"] in selected and s.get("kind") != "idea" for f in s.get("facts", []))
        explicit = bool(research.urls_in(message)) or parsed["intent"] == "research"
        # A type that promises the person's own tested method is not served by general steps from the web.
        own_method = "tested_steps" in (content_types.selected_rule_ids(state) or ())
        if not research.needs_research(message, parsed["intent"], has_facts) or (own_method and not explicit):
            return [], None
        request_digest = digest({'message':message, 'intent':parsed['intent'], 'conversationId':conversation_id, 'sourceIds':selected})
        # Persist the claim before external I/O. A crashed/uncertain lookup cannot replay its key.
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), 'edit')
            self._conversation(cur, workspace_id, conversation_id)
            if not research.allowed(self._state(row)):
                return [], research.off_record(research.query_for(message))
            cur.execute("SELECT request_digest,status,result FROM public.pr_research_requests WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id,key))
            prior = cur.fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise AlphaError('This request key belongs to different research.',409)
                if prior[1] != 'completed':
                    raise AlphaError('Research for this request is pending or interrupted. It will not repeat automatically.',409)
                return prior[2].get('sourceIds',[]), prior[2]
            cur.execute("INSERT INTO public.pr_research_requests(workspace_id,idempotency_key,request_digest,status) VALUES(%s,%s,%s,'pending')", (workspace_id,key,request_digest))
        result = self.researcher.run(message, parsed["intent"])
        record = research.summary(result)
        record["sourceIds"] = []
        added = []

        def command(state, actor):
            if not research.allowed(state):
                raise AlphaError('Web research permission changed. The result was discarded.',409)
            for page in result["pages"]:
                body, title = research.source_body(page), research.source_title(page)
                fingerprint = hashlib.sha256(("text" + clean(body, 20000)).encode()).hexdigest()
                source = next((x for x in state["sources"] if x.get("fingerprint") == fingerprint and x.get("active")), None)
                if source is None:
                    self.commands(state, actor, "source", {"kind": "text", "text": body, "title": title})
                    source = state["sources"][-1]
                    stamp(state)
                    source["origin"] = {"kind": "web_research", "url": page["url"], "host": page["host"], "query": result["query"], "published": page.get("published", ""), "fetchedAt": page["fetchedAt"]}
                    source["unknowns"] = ["Fetched from the public web by Rafii research; verify each claim against the page before publishing."]
                    # Public web pages may travel to any route; publishing their words still needs the person's use approval.
                    source["egressConsent"] = sorted(set(source.get("egressConsent", [])) | {"cloud"})
                    self.commands(state, actor, "approve_source", {"sourceId": source["id"], "factIds": [f["id"] for f in source["facts"]]})
                if source["id"] not in added:
                    added.append(source["id"])
            return state

        def save_record(cur, state, actor):
            record['sourceIds'] = added
            cur.execute("UPDATE public.pr_research_requests SET status='completed',result=%s::jsonb WHERE workspace_id=%s AND idempotency_key=%s AND status='pending'", (json.dumps(record),workspace_id,key))
            from . import product_events
            # Product taxonomy (PRD §8.6): an opaque request id, never the key or the query; behind its own savepoint.
            product_events.record(cur, workspace_id, actor, "research.completed", product_events.request_entity(workspace_id, key), 1,
                                  {"source": "web", "outcome": "found" if added else "empty"})

        try:
            self.repository.command(workspace_id, token, snapshot["revision"], command, after=save_record)
        except AlphaError as error:
            if error.status != 409:
                raise
            self.repository.command(workspace_id, token, self.repository.get(workspace_id, token)["revision"], command, after=save_record)
        record["sourceIds"] = added
        return added, record

    @staticmethod
    def _wants_image(payload):
        request = payload.get("imageGeneration")
        return request is True or isinstance(request, dict) and request.get("enabled") is True

    def _fail_image_run(self, workspace_id, token, conversation_id, run_id, reservation_id, message, *, usage=None, uncertain=False):
        """Persist a failed media run once; a possibly billed request is never recorded as free."""
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            self._lock_run_events(cur, workspace_id, run_id)
            cur.execute("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (run_id, workspace_id))
            row = cur.fetchone()
            if not row or row[0] != "running":
                return
            cost = (usage or {}).get("costUsd")
            known = type(cost) in (int, float) and cost >= 0
            self.ledger.settle(
                cur,
                workspace_id,
                reservation_id,
                "failed" if known or not uncertain else "unknown",
                usd_micro(cost) if known else 0 if not uncertain else None,
            )
            self._insert_event(cur, workspace_id, run_id, safe_event("run.failed", message=message))
            cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (run_id,))
            self._settle_message(cur, workspace_id, conversation_id, run_id, {"text": message, "runId": run_id, "failed": True, "pending": False, "intent": "image_generation", "images": []})

    def _image_turn(self, workspace_id, token, conversation_id, payload, text, selected_model, fingerprint=None, refs=None):
        """Generate and privately store one image without delegating the capability to the writer. Chips on the
        message are reported unused (`image_generation_turn`) on the run and its messages (SPEC §6.10)."""
        if self.image_runtime is None:
            raise AlphaError("Image generation isn't available yet.", 503, code="image_generation_not_configured")
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        request = payload.get("imageGeneration")
        if request is not True and (not isinstance(request, dict) or set(request) - {"enabled", "count"}):
            raise AlphaError("Choose a supported image-generation request.", 400)
        count = request.get("count", 1) if isinstance(request, dict) else 1
        if count != 1:
            raise AlphaError("This chat generates one reviewable image candidate at a time.", 400)
        prompt = clean(text or payload.get("intentText", ""), 4000)
        if not prompt:
            raise AlphaError("Describe the image you want to generate.", 400)
        key = clean(payload.get("idempotencyKey", ""), 100) or uid()

        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            stamp(state)
            context = project_context(state, "draft", "cloud", [])
            from .api_tokens import is_api_token
            if is_api_token(token):
                grant = self.repository.api_tokens.validate(cur, token, workspace_id)
                if "draft" not in grant["scopes"]:
                    raise AlphaError("This API token does not allow drafting.", 403)
            prior = self._keyed_run(cur, workspace_id, key, fingerprint)
            if prior:
                return self._events_for(cur, workspace_id, prior, 0)
            chips_report = turn_references.unused_all(state, refs, "image_generation_turn") if turn_references.present(refs) else None
            reported = {"references": chips_report} if chips_report else {}
            self._append_message(cur, workspace_id, conversation_id, "user", {"text": prompt, "sourceIds": [], "intent": "image_generation", **(turn_references.sent_ids(refs, chips_report) if chips_report else {})})
            cur.execute(
                "INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,usage) VALUES(%s,%s,%s,'running',%s,'quick',%s,%s,%s,%s::jsonb) RETURNING id::text",
                (conversation_id, workspace_id, principal, selected_model, digest(context), context["policyEpoch"], key, json.dumps({"request": fingerprint} if fingerprint else {})),
            )
            run_id = cur.fetchone()[0]
            reservation = self.ledger.reserve(
                cur,
                workspace_id,
                principal,
                "image_generation",
                self.image_runtime.estimate_usd_micro,
                f"image:{run_id}",
                charge_batch=True,
                provider=self.image_runtime.provider,
                model=self.image_runtime.model,
                run_id=run_id,
            )
            self._insert_event(cur, workspace_id, run_id, safe_event("run.started", model=selected_model, imageModel=self.image_runtime.model, reasoning="image"))
            self._insert_event(cur, workspace_id, run_id, safe_event("progress.updated", stage="image_generation", percent=5))
            cur.execute(
                "UPDATE public.pr_agent_runs SET usage=usage || %s::jsonb WHERE id::text=%s",
                (json.dumps({"provenance": "pending", "reservationId": reservation["reservationId"], "imageModel": self.image_runtime.model, **reported}), run_id),
            )
            for item in (chips_report or {}).get("unused", []):
                self._insert_event(cur, workspace_id, run_id, safe_event("warning.created", message=f"{item['label']} wasn't used. {item['message']}", reference={"kind": item["kind"], "id": item["id"], "reason": item["reason"]}))
            self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": "", "pending": True, "runId": run_id, "intent": "image_generation", "images": [], "model": selected_model, **reported}, run_id)

        staged = None
        result = None
        queued_events = []
        try:
            # The provider attempt becomes one pr_ai_call_events row (Founder Admin §8.B), written when the call returns.
            with ai_call_events.scope(feature="image", workspace_id=workspace_id, user_id=principal, run_id=run_id, reservation_id=reservation["reservationId"],
                                      connect=getattr(self.repository, "connection_factory", None)):
                result = self.image_runtime.generate(prompt, count=1, emit=queued_events.append)
            raw = result["images"][0]
            staged = self.assets.stage_upload(workspace_id, {"data": base64.b64encode(raw).decode()})
            public_asset = {key: staged.get(key) for key in ("id", "hash", "mime", "width", "height", "bytes")}
            public_asset["alt"] = clean(prompt, 300)
            artifact = {"variants": [], "images": [public_asset], "imageModel": self.image_runtime.model}
            artifact_hash = digest(artifact)

            def add_asset(state, actor):
                return self.commands.add_asset(state, actor, staged)

            def finish(cur, _state, _principal):
                self._lock_run_events(cur, workspace_id, run_id)
                cur.execute("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (run_id, workspace_id))
                row = cur.fetchone()
                if not row or row[0] != "running":
                    raise AlphaError("This image run is no longer active.", 409)
                for event in queued_events:
                    self._insert_event(cur, workspace_id, run_id, event)
                self._insert_event(cur, workspace_id, run_id, safe_event("artifact.created", artifactHash=artifact_hash, images=1))
                cost = result["usage"].get("costUsd")
                known = type(cost) in (int, float) and cost >= 0
                settlement = self.ledger.settle(cur, workspace_id, reservation["reservationId"], "completed" if known else "unknown", usd_micro(cost) if known else None)
                usage = {**result["usage"], "billing": settlement.get("state"), "ledgerCostState": settlement.get("state"), "selectedWritingModel": selected_model}
                cur.execute("UPDATE public.pr_agent_runs SET status='completed',artifact=%s::jsonb,artifact_hash=%s,usage=usage || %s::jsonb,updated_at=now() WHERE id::text=%s", (json.dumps(artifact), artifact_hash, json.dumps(usage), run_id))
                self._settle_message(cur, workspace_id, conversation_id, run_id, {"text": "Generated one private image candidate for review.", "runId": run_id, "artifactHash": artifact_hash, "intent": "image_generation", "images": artifact["images"], "model": selected_model, **reported})
                self._insert_event(cur, workspace_id, run_id, safe_event("run.completed", usage={"provenance": usage["provenance"], "modelRequests": 1, "costUsd": cost, "billing": settlement.get("state")}))

            # The asset metadata and completed run commit together. A concurrent workspace edit is
            # retried against the current revision; the provider call is never repeated.
            for attempt in range(2):
                snapshot = self.repository.get(workspace_id, token)
                try:
                    self.repository.command(
                        workspace_id,
                        token,
                        snapshot["revision"],
                        add_asset,
                        audit_event=lambda _state: ("media.generated", public_asset["id"], {"model": self.image_runtime.model}),
                        after=finish,
                    )
                    break
                except AlphaError as error:
                    if error.status != 409 or attempt:
                        raise
            # Ownership has moved to workspace state; later response-shaping failures must not
            # delete bytes that now back a committed asset.
            staged = None
            return self.events(workspace_id, token, run_id)
        except Exception as error:
            if staged is not None:
                try:
                    self.assets.remove(workspace_id, staged)
                except Exception:
                    pass
            from .image_runtime import ImageGenerationError
            uncertain = isinstance(error, ImageGenerationError) and error.uncertain or result is not None
            usage = (result or {}).get("usage")
            if usage is None and isinstance(error, ImageGenerationError) and error.cost_usd is not None:
                usage = {"costUsd": error.cost_usd}
            self._fail_image_run(workspace_id, token, conversation_id, run_id, reservation["reservationId"], str(error), usage=usage, uncertain=uncertain)
            raise

    def _state_reader(self, workspace_id, token, seen=None):
        """The workspace state a turn resolves Auto against: the state it already read, else a fresh read on demand."""
        return seen if seen is not None else (lambda: self.repository.get(workspace_id, token)["state"])

    def turn(self, workspace_id, token, conversation_id, payload, *, _credit_authority=None, _request_fingerprint=None, _run_meta=None, _started=None):
        # The request's own clock: every writer call must be able to finish inside it (model_runtime.REQUEST_SECONDS).
        started = _started if _started is not None else time.monotonic()
        client_key = clean(payload.get("idempotencyKey", ""), 100)
        fingerprint = _request_fingerprint or request_fingerprint("turn", payload, conversation_id)
        seen = None
        if client_key and _credit_authority is None:
            # A resend is answered from its original run before any new approval or charge is checked.
            with self.repository.transaction(token, workspace_id) as (cur, row, _):
                require(self._member(row), "edit")
                self._conversation(cur, workspace_id, conversation_id)
                prior = self._keyed_run(cur, workspace_id, client_key, fingerprint)
                if prior:
                    return self._events_for(cur, workspace_id, prior, 0)
                seen = self._state(row)
        credit_authority = _credit_authority or self.credit_requests.authorize(workspace_id, token, payload.get("expectedRevision"), payload, "turn", conversation_id)
        text = clean(payload.get("text", ""), MAX_TEXT)
        key = client_key or uid()
        # Chips are checked for shape before anything else (400), including on an image turn, which reports them unused.
        refs = turn_references.parse(payload)
        chips = turn_references.present(refs)
        # Auto (no model, or "auto") is resolved here, never written back into the payload: the idempotency and credit
        # fingerprints stay on what the caller sent.
        runtime, model_id, writer_note = self.resolve_writer(self._state_reader(workspace_id, token, seen), payload.get("model"))
        auto = payload.get("model") in (None, "", AUTO)
        quoted = (credit_authority or {}).get("model") if isinstance(credit_authority, dict) else None
        quoted_writer = auto and bool(quoted) and quoted != model_id and runtime.owns(quoted) and (not hasattr(runtime, "priced") or runtime.priced(quoted))
        if quoted_writer:
            # The credit limit was approved for this writer; the run uses it (prepare() still re-checks the match).
            model_id, writer_note = quoted, None
        if self._wants_image(payload):
            return self._image_turn(workspace_id, token, conversation_id, {**payload, "idempotencyKey": key}, text, model_id, fingerprint, refs=refs)
        reasoning, level = translate_reasoning(runtime, model_id, requested_level(payload))
        # Step ① of the agent pipeline: channels and times named in the message become the
        # destinations and a candidate plan. Parsed text never gains any authority of its own.
        zone = intent.safe_zone(payload.get("timeZone"))
        parsed = intent.parse_request(text or clean(payload.get("intentText", ""), MAX_TEXT), self.clock(), zone, runtime.supported_platforms() or None)
        recurring = getattr(self, 'recurring_binding', None)
        if recurring:
            # An automation drafts exactly the destinations its owner activated. Channels, languages, times or
            # instructions inside its brief are data: they never re-route, schedule or become memory.
            parsed = {**parsed, "intent": "draft", "languages": [], "destinations": [], "unattachedTimes": [], "unsupported": [], "warnings": [], "hasTimes": False}
        # Reworking handed-in material (a draft to adapt, a campaign brief) is a drafting request its caller already
        # classified: days or times in the instruction ("Turn Thursday's post into…") never make it an automation,
        # a schedule or a memory.
        # SPEC §6.1 step 4: chips or a handed-in reference read the workspace once, to validate `materialRef`, pick the
        # single rework post and compute account/folder destinations.
        ahead = None
        if chips or isinstance(payload.get("materialRef"), dict):
            ahead = turn_references.early(self.repository.get(workspace_id, token)["state"], refs, text, payload,
                                          platforms=tuple(runtime.supported_platforms() or ()))
        reworking = ((isinstance(payload.get("material"), str) and bool(payload["material"].strip())) or bool(ahead and ahead["rework"])) and not recurring
        if reworking:
            parsed = {**parsed, "intent": "draft", "unattachedTimes": [], "hasTimes": False,
                      "destinations": [{**d, "localTime": None} for d in parsed.get("destinations") or []]}
        # Step 6: a message with chips always drafts (or schedules), so no branch below silently drops them.
        forced_draft = False
        if chips and not recurring:
            forced_draft = parsed["intent"] in ("automation", "memory")
            parsed = {**parsed, "intent": "schedule" if parsed["hasTimes"] and not reworking else "draft"}
        understood = reading = None
        if text and not recurring and not reworking and not chips:
            parsed, reading = self._understand(workspace_id, token, text, zone, runtime, parsed)
            understood = (reading or {}).get("automation")
        elif parsed["intent"] == "automation":
            # Quick start already decided to draft this message now.
            parsed = {**parsed, "intent": "schedule" if parsed["hasTimes"] else "draft"}
        # Each (channel, language) pair is one destination; the workspace's remembered languages fill any channel the request left open.
        # Account and folder chips add theirs (SPEC §6.1 step 7), the same way estimate_request prices them.
        chip_destinations = ahead["destinations"] if ahead else []
        destinations = intent.resolve_destinations(parsed, self._with_chip_destinations(payload.get("destinations"), chip_destinations), payload.get("language"), DEFAULT_DESTINATIONS,
                                                   settings=lambda: self.repository.get(workspace_id, token)["state"])
        self._check_capability_revision(payload, destinations)
        plan = intent.build_plan(parsed, destinations)
        if text and not recurring and not reworking and not chips:
            # Staged automations, answers to Rafii's questions, edits and "why?" questions (orchestration §7).
            routed = self._orchestration_turn(workspace_id, token, conversation_id, text, parsed, reading, destinations, runtime, model_id, payload, writer_note=writer_note)
            if routed is not None:
                return routed
        if parsed["intent"] == "automation" and text and not recurring:
            return self._automation_turn(workspace_id, token, conversation_id, text, destinations, runtime, model_id, payload, understood=understood, writer_note=writer_note)
        if parsed["intent"] == "memory" and text:
            return self._memory_turn(workspace_id, token, conversation_id, text, parsed, destinations, model_id, writer_note=writer_note)
        # A completed or in-flight writing run must not repeat research on HTTP replay.
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), 'edit')
            self._conversation(cur, workspace_id, conversation_id)
            prior = self._keyed_run(cur, workspace_id, key, fingerprint)
            if prior:
                return self._events_for(cur, workspace_id, prior, 0)
            if level not in (None, AUTO) and not recurring:
                # An explicit level over the per-request limit is refused before paid web research runs, allowing for
                # the pages research could still add; the check after projection below is the authoritative one.
                current = self._state(row)
                can_research = self.researcher is not None and payload.get("research") is not False and not reworking and research.allowed(current)
                self.estimate_request(current, payload, "turn", principal, research_bytes=RESEARCH_ALLOWANCE_BYTES if can_research else 0)
        research_ids, researched = self._research(workspace_id, token, payload, text, parsed, key, conversation_id, reworking=reworking)
        # A connector chip is an opaque, short-lived receipt. Re-fetch its remote item now,
        # after the request fingerprint is fixed and before the writer transaction projects it.
        connector_ids = [ref["id"] for ref in refs.get("references", []) if ref.get("kind") == "connector_item"]
        connector_items = {}
        connector_service = getattr(self, "productivity_connectors", None)
        if connector_ids and connector_service is not None:
            connector_items = connector_service.turn_refetch(
                workspace_id, token, connector_ids, fingerprint,
                provider_class=getattr(runtime, "provider_class", "local"),
            )
        dispatch = None
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            stamp(state)
            existing = self._keyed_run(cur, workspace_id, key, fingerprint)
            if existing:
                return self._events_for(cur, workspace_id, existing, 0)
            if auto and not quoted_writer and self.resolve_writer(state, payload.get("model"))[1] != model_id:
                # An owner changed the workspace default while this request was being prepared: nothing is spent on a
                # writer the person did not see.
                raise AlphaError("The workspace default writer changed while this draft was being prepared. Send it again.", 409, code="writer_default_changed")
            projected = self._project(state, payload, runtime, model_id, reasoning, destinations, text, parsed, research_ids, level=level, refs=refs,
                                      notes=self._reference_notes(cur, workspace_id, state, refs), run_sources=lambda ids: self._run_sources(cur, workspace_id, ids), actor=principal,
                                      connector_items=connector_items)
            destinations, source_ids, context = projected["destinations"], projected["sourceIds"], projected["context"]
            from .growth.trends.opportunities import lineage as trend_lineage
            from .growth.trends.service import validate_stored_bindings
            trend_bindings = trend_lineage(state, source_ids)
            if trend_bindings:
                validate_stored_bindings(self.repository.connection_factory, cur, workspace_id, principal, state,
                                         trend_bindings, self.clock(), model_visible=getattr(runtime, "provider_class", "cloud") != "local")
            shared, voice_context, request, bound, reminders = projected["shared"], projected["voiceContext"], projected["request"], projected["bound"], projected["reminders"]
            # Authoritative: the prompt is final here (research included), so an explicit level over the limit is refused
            # before the run exists or anything is reserved.
            check_level_ceiling(runtime, model_id, request, actor=principal)
            if not runtime.asynchronous:
                # Monotonic seconds; never part of a digest, fingerprint or the priced prompt (model_runtime._messages).
                request["deadline"] = started + REQUEST_SECONDS
            # Writing material handed in with a request (an existing draft to rework, a campaign brief): the writer reads it
            # (_project), but it is never parsed for channels, times or instructions, and it is not stored as a source.
            # Only a server-validated reference counts (turn_references.early): a forged or stale one is dropped with a reminder.
            material_ref = projected.get("materialRef")
            if forced_draft and "references" in projected:
                routed = turn_references.REMINDERS["routing_forced_draft"]
                projected["references"]["reminders"] = list(dict.fromkeys(projected["references"]["reminders"] + [routed]))
                reminders = list(dict.fromkeys(reminders + [routed]))
            if chips:
                # One presence row per asset and conversation (runtime v2 lists them as "the second image").
                live = {a.get("id"): a for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and not a.get("deleted") and not a.get("deletionPending")}
                for item in refs["attachments"]:
                    if item["assetId"] in live:
                        attachment_rows.record(cur, workspace_id, conversation_id, principal, live[item["assetId"]], now=self.clock())
            sent = turn_references.sent_ids(refs, projected.get("references")) if chips else {}
            if text:
                # A caller that hands the writer one step of a longer request records the person's own words.
                said = clean(payload["messageText"], MAX_TEXT) if isinstance(payload.get("messageText"), str) and payload["messageText"].strip() else text
                self._append_message(cur, workspace_id, conversation_id, "user", {"text": said, "sourceIds": source_ids, "intent": parsed["intent"], **sent,
                                                                                   **({"material": {k: str(v)[:120] for k, v in material_ref.items() if k in ("type", "id", "title")}} if material_ref else {})})
            skill_ids = [b["id"] for b in bound["bindings"]]
            cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,usage) VALUES(%s,%s,%s,'running',%s,%s,%s,%s,%s,%s::jsonb) RETURNING id::text", (conversation_id, workspace_id, principal, model_id, reasoning, digest(context), context["policyEpoch"], key, json.dumps({"request": fingerprint, **(_run_meta or {})})))
            run_id = cur.fetchone()[0]
            # Credits gate before execution (§17): only a paid route reserves money or a writing batch.
            paid = runtime.cost_class == "paid"
            estimate = __import__('math').ceil(runtime.price_quote(request, model_id) * 1_000_000) if paid and hasattr(runtime, 'price_quote') else 500_000 if paid else 0
            recurring = getattr(self, 'recurring_binding', None)
            if recurring and estimate > recurring['maxCostUsdMicro']:
                raise AlphaError(f"This run could cost up to US${estimate / 1_000_000:.2f}, over this automation's US${recurring['maxCostUsdMicro'] / 1_000_000:.2f} limit per run. "
                                 f"Raise the limit to at least US${estimate / 1_000_000:.2f} to let it write.", 402, code="automation_cost_limit")
            reservation = self.ledger.reserve(cur, workspace_id, principal, "text_model", estimate, f"run:{run_id}", charge_batch=paid, provider=runtime.provider, model=model_id, run_id=run_id, credit_authority=credit_authority)
            outcome = {"parsed": parsed, "plan": plan, "destinations": destinations, "context": context, "reservationId": reservation["reservationId"], "model": model_id, "skillBindings": bound["bindings"], "skillOmissions": bound.get("omitted", []), "research": researched, "memoryBindings": shared.get("learned"), "voiceContext": voice_context, "paid": paid, "actor": principal}
            if "references" in projected:
                # What the chips did, the post media and the per-message content type (chat-context SPEC §5.10).
                outcome.update({"references": projected["references"], "media": projected["media"], "contentType": projected["contentType"], "derivedSourceIds": projected["derivedSourceIds"]})
            from .coworker import flags as coworker_flags
            if coworker_flags.enabled("RAFII_OPPORTUNITY_FLIPPER_ENABLED"):
                from .growth.scout import lineage
                outcome["scoutLineage"] = lineage(state, source_ids)
            if trend_bindings:
                outcome["trendLineage"] = trend_bindings
            if projected.get("reworkOf"):
                # A rework of one draft (handed in, or a post chip in the rework role): applying it updates that
                # draft, not whichever draft shares its slot.
                outcome["reworkOf"] = projected["reworkOf"]
            elif material_ref and material_ref.get("type") == "draft" and isinstance(material_ref.get("id"), str):
                outcome["reworkOf"] = material_ref["id"]
            if material_ref and material_ref.get("type") == "campaign" and isinstance(material_ref.get("id"), str):
                # A post written for a campaign joins that campaign when it is saved.
                outcome["forCampaign"] = material_ref["id"]
            from .api_tokens import is_api_token
            if is_api_token(token):
                grant = self.repository.api_tokens.validate(cur, token, workspace_id)
                if 'draft' not in grant['scopes']:
                    raise AlphaError('This API token does not allow drafting.', 403)
                outcome['apiTokenId'] = grant['tokenId']
            elif not recurring:
                session_id = getattr(self.repository.verify_session, 'session_id', None)
                if session_id:
                    outcome['sessionId'] = session_id(token, principal)
            if recurring:
                outcome['recurringBinding'] = recurring

            def emit(event):
                self._insert_event(cur, workspace_id, run_id, event)

            # Context notes (unsupported channels, assumed times, the proposed plan) follow run.started
            # so the stream keeps its shape: run.started first, run.completed last.
            context_events = [safe_event("warning.created", message=f"{platform} is not available for drafting yet, so it was left out.") for platform in parsed["unsupported"]]
            context_events += [safe_event("warning.created", message=note) for note in ([writer_note] if writer_note else []) + parsed["warnings"] + bound["warnings"] + self._memory_notes(shared) + reminders]
            excluded_ids = {item["id"] for item in context.get("excluded", [])}
            for item in (projected.get("references") or {}).get("unused", []):
                # A chip source excluded by policy is already warned about by the writer (with its reason); one warning each.
                if item["kind"] == "source" and item["id"] in excluded_ids:
                    continue
                context_events.append(safe_event("warning.created", message=f"{item['label']} wasn't used. {item['message']}",
                                                 reference={"kind": item["kind"], "id": item["id"], "reason": item["reason"]}))
            if researched:
                if not researched.get("off"):
                    context_events.append(safe_event("progress.updated", stage="researched", percent=8, pages=len(researched["pages"]), query=researched["query"]))
                context_events += [safe_event("warning.created", message=note) for note in researched.get("warnings", [])]
            if plan:
                context_events.append(safe_event("action.proposed", action="schedule_plan", destinations=len(plan["destinations"]), timeZone=plan["timeZone"]))

            if runtime.asynchronous or paid:
                emit(safe_event("run.started", model=model_id, reasoning=reasoning, contextDigest=digest(context)))
                for pending in context_events:
                    emit(pending)
                emit(safe_event("progress.updated", stage="queued", percent=5))
                reported = {"references": outcome["references"], "media": outcome.get("media", [])} if outcome.get("references") is not None else {}
                cur.execute("UPDATE public.pr_agent_runs SET usage=usage || %s::jsonb WHERE id::text=%s", (json.dumps({"provenance": "pending", "reservationId": reservation["reservationId"], "skillBindings": bound["bindings"], "skillOmissions": bound.get("omitted", []), **reported}), run_id))
                # The assistant turn exists from the start so the conversation can follow the run; the sink fills it in.
                self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": "", "pending": True, "runId": run_id, "intent": parsed["intent"], "destinations": destinations, "plan": plan, "model": model_id, "skills": skill_ids, "research": researched,
                                                                                        **({"references": outcome["references"]} if outcome.get("references") is not None else {})}, run_id)
                dispatch = (runtime, run_id, request, RunSink(self, workspace_id, conversation_id, run_id, outcome))
                response = self._events_for(cur, workspace_id, run_id, 0)
            else:
                def emit_with_context(event):
                    emit(event)
                    if event["type"] == "run.started" and context_events:
                        for pending in context_events:
                            emit(pending)
                        context_events.clear()

                try:
                    result = runtime.start_turn(request, emit_with_context)
                except AlphaError as error:
                    emit({"type": "run.failed", "message": str(error)})
                    cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (run_id,))
                    self.ledger.settle(cur, workspace_id, reservation["reservationId"], "failed", 0)
                    raise
                self._finish(cur, workspace_id, conversation_id, run_id, result["artifact"], result["usage"], outcome)
                response = self._events_for(cur, workspace_id, run_id, 0)
        if dispatch:
            # Only after the run row is committed can a background thread or device see it.
            runtime, run_id, request, sink = dispatch
            if runtime.asynchronous:
                runtime.dispatch(run_id, request, sink)
            else:
                # Persist the idempotency key and reservation before any billable I/O.
                # The request stays synchronous on hosted functions; no background thread
                # can be frozen after the HTTP response. An interrupted run is never retried.
                try:
                    result = runtime.start_turn(request, sink.emit)
                    sink.complete(result["artifact"], result["usage"])
                except ProviderFailure as error:
                    if not error.dispatched:
                        # Refused before any provider request: nothing was spent, the hold is released.
                        sink.fail(str(error), known_cost_usd=0.0, usage=error.usage)
                        raise AlphaError(str(error), error.status, code=error.code)
                    if error.cost_usd is not None:
                        sink.fail("The writer did not finish. This failed attempt was not charged.", known_cost_usd=error.cost_usd, usage=error.usage)
                        if error.status == 409:
                            raise AlphaError(str(error), 409, code=error.code)
                        raise AlphaError("The writer did not finish. This failed attempt was not charged; you can try again.", 502)
                    sink.fail("The writer did not finish. Usage may be pending; this run will not retry automatically.", usage=error.usage)
                    raise AlphaError("The writer did not finish. Check this run before starting another request.", 502)
                except Exception:
                    sink.fail("The writer did not finish. Usage may be pending; this run will not retry automatically.")
                    raise AlphaError("The writer did not finish. Check this run before starting another request.", 502)
                response = self.events(workspace_id, token, run_id)
        return response

    @staticmethod
    def _memory_notes(shared):
        """What the person should know when a cloud route could not read all of their memory files."""
        if not shared["shared"]:
            return ["Your voice profile, identity and boundaries were not shared with this cloud model, so the draft may not sound like you or respect your boundaries. Allow sharing on the Memory page."]
        withheld = shared["withheldBoundaries"]
        if withheld:
            return [f"{withheld} boundar{'y' if withheld == 1 else 'ies'} marked private or local-only {'was' if withheld == 1 else 'were'} not shared with this cloud model. Check the draft against {'it' if withheld == 1 else 'them'} before approving."]
        return []

    @staticmethod
    def _tone(state):
        active = state.get("speaker", {}).get("activeRevision")
        revision = next((r for r in state.get("speaker", {}).get("revisions", []) if r.get("revision") == active), None)
        return (revision or {}).get("profile", {}).get("tone", "warm")

    def _project(self, state, payload, runtime, model_id, reasoning, destinations, text, parsed, research_ids=(), level=None, *, refs=None, notes=None, run_sources=None, actor=None, connector_items=None):
        """Everything a writer route will receive for one drafting turn, computed from `state` alone.

        Chips on the message (`references`/`attachments`) and handed-in material go through turn_references
        (chat-context SPEC §6): they reach the writer as data fields, never inside the idea, and every item is reported.
        `notes` is media_notes.lookup's output for runs, or turn_references.PRICING for estimates (padded, untrimmed)."""
        # Account identity is verified against this workspace's connections (v9 §4).
        destinations = intent.bind_accounts(destinations, state)
        source_ids = payload.get("sourceIds") if isinstance(payload.get("sourceIds"), list) else [s["id"] for s in state.get("sources", []) if s.get("active") and s.get("kind") != "voice_sample"][:20]
        source_ids = [source_id for source_id in source_ids if not any(s.get("id") == source_id and s.get("kind") == "voice_sample" for s in state.get("sources", []))]
        # A cloud route only receives sources whose egress the person consented to; local routes see local consent.
        provider_class = getattr(runtime, "provider_class", "local")
        refs = turn_references.parse(payload) if refs is None else refs
        eligible_skills = self.skills.eligible()
        # Connector fetches are authenticated and re-fetched before this projection. Their
        # document sources are injected only for this request; persisted copies are created by
        # the connector service and remain subject to ordinary source-policy approval.
        connector_items = connector_items if isinstance(connector_items, dict) else {}
        connector_sources = [item["source"] for item in connector_items.values()
                             if isinstance(item, dict) and isinstance(item.get("source"), dict)]
        if connector_sources:
            state = copy.deepcopy(state)
            known = {source.get("id") for source in state.get("sources") or [] if isinstance(source, dict)}
            state.setdefault("sources", []).extend(source for source in connector_sources if source.get("id") not in known)
        handed_in = (isinstance(payload.get("material"), str) and bool(payload["material"].strip())) or isinstance(payload.get("materialRef"), dict)
        # The thought typed for this turn is the idea; quick-start passes it as intentText.
        # An explicit sourceIds field is authoritative context for this request, so an empty follow-up must not
        # silently re-introduce an older workspace brief (which may now be private/internal-only material).
        # The writer's `idea` field is bounded (IDEA_LIMIT); long text still reaches it whole as the message or source.
        saved_brief = "" if isinstance(payload.get("sourceIds"), list) else state.get("brief", {}).get("idea", "")
        raw_idea = text or str(payload.get("intentText") or "") or saved_brief
        idea = clean(raw_idea[:IDEA_LIMIT], IDEA_LIMIT)
        resolved = None
        if turn_references.present(refs) or handed_in:
            material_text = clean(payload["material"], MAX_TEXT) if isinstance(payload.get("material"), str) else None
            resolved = turn_references.resolve(
                state, refs, actor=actor, provider_class=provider_class, route_kind="fixture" if isinstance(runtime, FixtureAgentRuntime) else provider_class,
                text=raw_idea, payload_material=material_text, material_ref=payload.get("materialRef") if isinstance(payload.get("materialRef"), dict) else None,
                notes=notes, run_sources=run_sources, source_ids=list(dict.fromkeys(list(source_ids) + list(research_ids))),
                platforms=tuple(runtime.supported_platforms() or ()), skills=eligible_skills, connector_items=connector_items)
            source_ids = resolved["sourceIds"]
        else:
            source_ids = list(dict.fromkeys(list(source_ids) + list(research_ids)))
        context = project_context(state, "draft", provider_class, source_ids)
        selection = ((state.get("contentSystem") or {}).get("selection") or {})
        rule_ids = content_types.selected_rule_ids(state)
        recurring = getattr(self, 'recurring_binding', None)
        automation_notes = list((recurring or {}).get("notes") or [])
        if recurring and "contentType" in recurring:
            # An automation writes with the content type that was activated, not whatever Home has selected now.
            selection, rule_ids, note = self._automation_selection(state, recurring["contentType"])
            automation_notes += [note] if note else []
        elif resolved and resolved["contentType"]:
            # A template chip chooses this message's content type (recurring > template > workspace selection, SPEC §6.4).
            selection, rule_ids, note = self._content_selection(state, resolved["contentType"], note=turn_references.REMINDERS["template_fallback"])
            automation_notes += [note] if note else []
        content_type_id = selection.get("contentTypeId")
        # A how-to that names no steps still drafts; the person gets a reminder next to it, never a block.
        reminders = [content_types.TUTORIAL_REMINDER] if content_types.missing_tutorial_input(rule_ids, idea, context) else []
        reminders += automation_notes
        # Step ②: everything a route may see is assembled here; adapters only ever receive this request.
        # Memory files follow the route: a cloud route reads them only with the workspace's consent (memory.projection).
        # Learned preferences arrive as the slice that applies to these destinations (design §5.7), recorded on the run.
        voice_mode = payload.get("voiceMode", "neutral")
        if voice_mode not in ("neutral", "personalized"):
            raise AlphaError("Choose neutral or personalized writing.")
        voice_route = "local-cli" if provider_class == "local" else f"cloud:{runtime.provider}:{model_id}"
        voice_projection = None
        if voice_mode == "personalized":
            requested_voice = payload.get("voiceSourceIds") if isinstance(payload.get("voiceSourceIds"), list) else [s["id"] for s in state.get("sources", []) if s.get("kind") == "voice_sample" and s.get("active") and s.get("selected")]
            try:
                voice_projection = voice_sources.retrieve(state, requested_voice, "generation", voice_route, query=idea)
            except AlphaError as error:
                if not recurring and error.status not in (404, 409):
                    raise   # a malformed request, not a missing or disallowed sample
            if not (voice_projection or {}).get("samples"):
                # No chosen sample may be used by this writer right now (none selected, removed, or not allowed for
                # this route): every caller (Home, a conversation, Rafii, an automation) still gets its draft, in a
                # neutral voice that says so, never a refusal.
                voice_mode, voice_projection = "neutral", None
                reminders.append(VOICE_FALLBACK_NOTE)
        shared = memory.projection(state, provider_class, destinations, content_type_id if content_type_id != "unclassified" else None, voice_route=voice_route if voice_mode == 'personalized' else None)
        if voice_projection:
            voice_context = {"mode": "personalized", "route": voice_route, "bindings": voice_projection["bindings"], "digest": voice_projection["digest"]}
            style_directives = voice_sources.style_directives(voice_projection)
        else:
            voice_context = {"mode": "neutral", "route": None, "bindings": [], "digest": None}
            style_directives = {}
        request = {"context": context, "idea": idea, "tone": self._tone(state), "destinations": destinations, "reasoning": reasoning, "model": model_id, "memory": shared["files"], "voiceContext": voice_context, "styleDirectives": style_directives}
        if level is not None:
            request["level"] = level   # the managed writer's reasoning level (translate_reasoning); `reasoning` keeps the pass
        report = None
        if resolved:
            # Chat-context SPEC §6.8: the typed instruction is the idea; material and notes are their own data fields.
            if resolved["material"]:
                request["material"] = resolved["material"]
            if resolved["referenceNotes"]:
                request["referenceNotes"] = resolved["referenceNotes"]
            report = resolved["report"]
            if turn_references.REMINDERS["template_fallback"] in automation_notes:
                report = {**report, "reminders": list(dict.fromkeys(report["reminders"] + [turn_references.REMINDERS["template_fallback"]]))}
                resolved = {**resolved, "report": report}
            measure = getattr(runtime, "_user_payload", None)
            if notes is not turn_references.PRICING and callable(measure):
                # Runs only (an estimate stays an upper bound): chip-added text is trimmed so the writer's 60 kB is never hit.
                trimmed = turn_references.trim_to_budget(request, lambda r: len(json.dumps(measure(r), ensure_ascii=False).encode()), resolved=resolved)
                request, report = trimmed["request"], trimmed["report"]
                context = request["context"]
                source_ids = [item for item in source_ids if any(s["id"] == item for s in context["sources"]) or any(e["id"] == item for e in context["excluded"])]
            reminders = list(dict.fromkeys(reminders + list(report["reminders"])))
        # Step ③: skills are bound by destination, format, intent and content type, and recorded
        # by id/version/sha256 (design §7). The voice contract carries only the parts this turn uses.
        from contextlib import nullcontext
        from .skill_compiler import workflow_context
        trend_selected = any(s.get("id") in source_ids and (s.get("origin") or {}).get("trendLineage") for s in state.get("sources", []))
        with workflow_context("rafii-trend-intelligence") if trend_selected else nullcontext():
            bound = self.skills.bind(destinations, selection.get("formatId"), parsed["intent"],
                                     content_type_id if content_type_id != "unclassified" else None,
                                     max_chars=budget_for(runtime.cost_class), explicit=(resolved or {}).get("skillIds") or ())
        request["skills"] = bound
        projected = {"destinations": destinations, "sourceIds": source_ids, "context": context, "shared": shared, "voiceContext": voice_context, "request": request, "bound": bound, "reminders": reminders}
        if resolved:
            used_types = selection if resolved["contentType"] and selection.get("contentTypeId") != "unclassified" else None
            projected.update({"references": report, "media": resolved["media"], "materialRef": resolved["materialRef"], "reworkOf": resolved["reworkOf"],
                              "connectorSourceIds": resolved.get("connectorSourceIds") or [],
                              # Only sources the writer actually received: apply re-checks every id it copies onto a draft.
                              "derivedSourceIds": [i for i in resolved["derivedSourceIds"] if any(src["id"] == i for src in context["sources"])],
                              "contentType": {**used_types, "contentSkillRouteIds": resolved["contentType"].get("contentSkillRouteIds", [])} if used_types else None})
        return projected

    def _reference_notes(self, cur, workspace_id, state, refs):
        """media_notes.lookup for this message's attachments at their current hashes; None when reading isn't configured."""
        attachments = (refs or {}).get("attachments") or []
        if not attachments:
            return {}
        if self.media_notes is None or not getattr(self.media_notes.reader, "available", False):
            return None
        from . import media_notes
        assets = {a.get("id"): a for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict)}
        pairs = [(item["assetId"], str((assets.get(item["assetId"]) or {}).get("hash") or "")) for item in attachments if item["assetId"] in assets]
        return media_notes.lookup(cur, workspace_id, pairs)

    @staticmethod
    def _run_sources(cur, workspace_id, run_ids):
        """{run id: the source ids its writer was given} from each run's recorded bindings (a post's provenance, SPEC §6.2)."""
        ids = [run_id for run_id in run_ids if isinstance(run_id, str)]
        if not ids:
            return {}
        cur.execute("SELECT id::text, artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text = ANY(%s)", (workspace_id, ids))
        return {run_id: [b.get("id") for b in (artifact or {}).get("sourceBindings", []) if isinstance(b, dict)] for run_id, artifact in cur.fetchall()}

    def estimate_request(self, state, payload, operation, actor, research_bytes=0):
        """The writer request a quick-start or turn would send now, for a credit estimate (no side effects): the same
        writer (Auto resolved against `state`), pass and level the turn would use. An explicit level whose ceiling is
        over the per-request limit is refused here, so a credit limit is never issued for it; `research_bytes` allows
        for web research a turn may still add. A stale workspace default's note travels in request["writerNote"]."""
        runtime, model_id, note = self.resolve_writer(state, payload.get("model"))
        reasoning, level = translate_reasoning(runtime, model_id, requested_level(payload))
        zone = intent.safe_zone(payload.get("timeZone"))
        state = copy.deepcopy(state)
        stamp(state)
        if operation == "quick-start":
            text = clean(payload.get("text", ""), 20000)
            url = clean(payload.get("url", ""), 2000)
            if not text and not url:
                raise AlphaError("Paste a thought or text, or add a link, to estimate.", 400)
            parsed = intent.parse_request(text, self.clock(), zone, runtime.supported_platforms() or None)
            language = locales.canonical(payload.get("language"))
            destinations = intent.resolve_destinations(parsed, payload.get("destinations"), language, [{"platform": "LinkedIn", "language": language or parsed["language"]}], settings=lambda: state)
            # The same source step quick_start takes (links are saved as unverified references, never fetched).
            source = self._quick_start_source(state, actor, payload, text, url, payload.get("ownContent") is True)
            ids = list(dict.fromkeys([source["id"]] + checked_context_ids(state, payload.get("sourceIds", []))))
            turn_payload = {**payload, "sourceIds": ids, "intentText": text}
            refs = turn_references.parse(payload)
            chip_destinations = turn_references.early(state, refs, text, payload, platforms=tuple(runtime.supported_platforms() or ()))["destinations"]
            destinations = intent.resolve_destinations(parsed, self._with_chip_destinations(payload.get("destinations"), chip_destinations), language,
                                                       [{"platform": "LinkedIn", "language": language or parsed["language"]}], settings=lambda: state)
            projected = self._project(state, turn_payload, runtime, model_id, reasoning, destinations, "", parsed, level=level, refs=refs, notes=turn_references.PRICING,
                                      run_sources=self._estimate_run_sources(state), actor=actor)
        else:
            text = clean(payload.get("text", ""), MAX_TEXT)
            parsed = intent.parse_request(text, self.clock(), zone, runtime.supported_platforms() or None)
            refs = turn_references.parse(payload)
            chip_destinations = turn_references.early(state, refs, text, payload, platforms=tuple(runtime.supported_platforms() or ()))["destinations"]
            destinations = intent.resolve_destinations(parsed, self._with_chip_destinations(payload.get("destinations"), chip_destinations), payload.get("language"),
                                                       DEFAULT_DESTINATIONS, settings=lambda: state)
            # Estimates pad every eligible note to its full length and skip trimming, so they bound any run of this body.
            projected = self._project(state, payload, runtime, model_id, reasoning, destinations, text, parsed, level=level, refs=refs, notes=turn_references.PRICING,
                                      run_sources=self._estimate_run_sources(state), actor=actor)
        request = projected["request"]
        check_level_ceiling(runtime, model_id, request, extra_bytes=research_bytes, actor=actor)
        if note:
            request["writerNote"] = note
        return runtime, model_id, request

    @staticmethod
    def _check_capability_revision(payload, destinations):
        """Every route's destinations are checked against the live creation projection before any writing or spending
        (CLI and subscription routes included); a composer that sent its facet revision gets a stale or forged list
        refused with `schema_revision_mismatch`. The browser never decides what is draftable."""
        from .creation_capabilities import validate_destinations
        validate_destinations(destinations, revision=payload["capabilityRevision"] if isinstance(payload.get("capabilityRevision"), str) else None)

    @staticmethod
    def _with_chip_destinations(requested, chip_destinations):
        """The payload's destinations, joined by chip destinations when there are any (a chip-less request is unchanged)."""
        return (turn_references.merge_destinations(requested, chip_destinations) or None) if chip_destinations else requested

    def _estimate_run_sources(self, state):
        """Run provenance for an estimate, read over a short read-only connection (completed runs never change)."""
        workspace_id = (state.get("workspace") or {}).get("id")
        factory = getattr(self.repository, "connection_factory", None)
        if not workspace_id or factory is None:
            return None

        def read(run_ids):
            with factory() as db, db.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                return self._run_sources(cur, workspace_id, run_ids)
        return read

    def _keyed_run(self, cur, workspace_id, key, fingerprint):
        cur.execute("SELECT id::text,usage FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
        row = cur.fetchone()
        if not row:
            return None
        stored = (row[1] or {}).get("request")
        if stored and fingerprint and stored != fingerprint:
            raise AlphaError("This request key was already used for a different request. Start a new request.", 409, code="idempotency_conflict")
        return row[0]

    def _events_for(self, cur, workspace_id, run_id, cursor):
        cur.execute("SELECT status,artifact_hash,usage,conversation_id::text,model,reasoning,artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        run = cur.fetchone()
        if not run:
            raise AlphaError("Run unavailable.", 404)
        cur.execute("SELECT seq,kind,body,extract(epoch from at) FROM public.pr_agent_events WHERE run_id::text=%s AND workspace_id=%s AND seq>%s ORDER BY seq LIMIT 500", (run_id, workspace_id, cursor))
        events = [{"id": f"{run_id}:{r[0]}", "seq": r[0], "type": r[1], **r[2], "at": float(r[3])} for r in cur.fetchall()]
        # The candidate artifact is the customer's own draft text; it is safe to show and required for preview.
        return {"runId": run_id, "conversationId": run[3], "status": run[0], "artifactHash": run[1], "usage": run[2], "model": run[4], "reasoning": run[5], "artifact": run[6] if run[0] in ("completed", "applied") else None, "events": events, "cursor": events[-1]["seq"] if events else cursor}

    def events(self, workspace_id, token, run_id, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise AlphaError("Invalid event cursor.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            return self._events_for(cur, workspace_id, run_id, cursor)

    def recover_stalled(self, max_runs=25):
        """Bounded cron recovery: hold uncertain spend, never repeat provider I/O."""
        recovered = 0
        with self.repository.connection_factory() as db, db.cursor() as cur:
            # The Rafii Agent Runtime's rows (agent:/task:/voice:) are not writing runs: a task waiting for an approval or a live
            # voice call is not stalled, and the runtime closes its own dead turns and sessions with their reservations.
            cur.execute("SELECT w.id::text FROM public.pr_workspaces w WHERE EXISTS (SELECT 1 FROM public.pr_agent_runs r WHERE r.workspace_id=w.id AND r.status='running' AND r.updated_at<to_timestamp(%s) AND r.idempotency_key NOT LIKE 'agent:%%' AND r.idempotency_key NOT LIKE 'task:%%' AND r.idempotency_key NOT LIKE 'voice:%%') ORDER BY w.id FOR UPDATE SKIP LOCKED LIMIT %s", (self.clock()-600, max_runs))
            for (wid,) in cur.fetchall():
                cur.execute("SELECT id::text,conversation_id::text,usage FROM public.pr_agent_runs WHERE workspace_id=%s AND status='running' AND updated_at<to_timestamp(%s) AND idempotency_key NOT LIKE 'agent:%%' AND idempotency_key NOT LIKE 'task:%%' AND idempotency_key NOT LIKE 'voice:%%' ORDER BY created_at LIMIT %s", (wid, self.clock()-600, max_runs-recovered))
                for run_id, cid, usage in cur.fetchall():
                    self._lock_run_events(cur, wid, run_id)
                    reservation = (usage or {}).get('reservationId')
                    if reservation:
                        self.ledger.settle(cur, wid, reservation, 'unknown')
                    self._insert_event(cur, wid, run_id, safe_event('run.failed', message='Writer interrupted; usage needs reconciliation. No automatic retry.'))
                    cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (run_id,))
                    self._settle_message(cur, wid, cid, run_id, {'text':'Writer interrupted. Review usage before starting another request.','runId':run_id,'failed':True,'pending':False,
                                                                 **({'references': usage['references']} if isinstance((usage or {}).get('references'), dict) else {})})
                    recovered += 1
        return {'recovered': recovered, 'providerRequests': 0}

    def cancel(self, workspace_id, token, run_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit")
            self._lock_run_events(cur, workspace_id, run_id)
            cur.execute("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (run_id, workspace_id))
            run = cur.fetchone()
            if not run:
                raise AlphaError("Run unavailable.", 404)
            if run[0] == "running":
                cur.execute("SELECT id::text,estimated_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND run_id::text=%s AND kind='reserve'", (workspace_id, run_id))
                reservation = cur.fetchone()
                if reservation:
                    self.ledger.settle(cur, workspace_id, reservation[0], 'unknown' if reservation[1] else 'failed', None if reservation[1] else 0)
                self._insert_event(cur, workspace_id, run_id, safe_event("run.cancelled", message="Cancelled. Partial text retained; no automatic retry."))
                cur.execute("UPDATE public.pr_agent_runs SET status='cancelled',updated_at=now() WHERE id::text=%s", (run_id,))
                cur.execute("UPDATE public.pr_messages SET body=body || '{\"pending\": false, \"cancelled\": true, \"text\": \"Cancelled before the draft finished.\"}'::jsonb WHERE workspace_id=%s AND run_id::text=%s AND role='assistant' AND (body->>'pending')='true'", (workspace_id, run_id))
                return {"runId": run_id, "status": "cancelled"}
            return {"runId": run_id, "status": run[0], "note": "Already finished; nothing to cancel."}

    def apply(self, workspace_id, token, revision, run_id, artifact_hash, separate=False, tag=None):
        """Turn a completed candidate into reviewable workspace variants. Never publishes. `separate` (an automation
        run) always adds new variants instead of refreshing an earlier unscheduled draft, so each run keeps its own
        drafts; `tag` records which automation run they belong to."""
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit")
            cur.execute("SELECT status,artifact,artifact_hash,policy_epoch,context_digest,model FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
            run = cur.fetchone()
        if not run:
            raise AlphaError("Run unavailable.", 404)
        status, artifact, stored_hash, epoch, context_digest, run_model = run
        if status == "applied":
            return {"runId": run_id, "status": "applied", "note": "Already applied."}
        if status != "completed" or not artifact:
            raise AlphaError("No completed candidate to review.", 409)
        if artifact_hash != stored_hash:
            raise AlphaError("Review the exact candidate.", 409)

        from . import campaigns

        def command(state, actor):
            stamp(state)
            # Every source the writer was given is re-checked, not only the ones it cited: a writer cites the subset it
            # used (so comparing only those with all its bindings refused every such candidate), and it may still
            # have leaned on a source it did not cite.
            source_ids = sorted({item["id"] for item in artifact.get("sourceBindings", [])} | {sid for v in artifact["variants"] for sid in v["sourceIds"]} | set(artifact.get("derivedSourceIds") or []))
            current = project_context(state, "draft", "local", source_ids)
            current_bindings = sorted(({"id": item["id"], "hash": item["hash"]} for item in current["sources"]), key=lambda item: item["id"])
            original_bindings = sorted(artifact.get("sourceBindings", []), key=lambda item: item["id"])
            if current["policyEpoch"] != epoch or current_bindings != original_bindings or current["excluded"]:
                raise AlphaError("Sources or their policies changed. Preserve the candidate and draft again from current context.", 409)
            voice_sources.validate_bindings(state, artifact.get("voiceContext") or {})
            if artifact.get("trendLineage"):
                from .growth.trends.opportunities import validate_lineage as validate_trend_lineage
                validate_trend_lineage(state, artifact["trendLineage"], self.clock())
            if artifact.get("scoutLineage"):
                from .growth.scout import validate_lineage
                validate_lineage(state, artifact["scoutLineage"])
            # A variant that has ever entered the queue (approved, published, verified, in flight) is a
            # record of what went out; a new candidate never becomes an "update" to it. Only a draft that
            # is still unscheduled in the same platform/language slot is refreshed in place.
            committed = {job["manifest"]["variantId"] for job in state.get("phase2", {}).get("jobs", []) if job.get("state") not in ("canceled", "failed")}
            created.clear()
            rework = artifact.get("reworkOf")
            original = next((v for v in state["variants"] if v.get("id") == rework), None) if rework else None
            for candidate in artifact["variants"]:
                if separate or artifact.get("forCampaign"):
                    # An automation run, or a post written for a campaign: new content, never an update to an unrelated draft.
                    drafts = []
                elif rework:
                    # A rework updates exactly the draft it was asked for (same account and language, still
                    # unscheduled); for another platform, or once that draft is scheduled, it is a new draft.
                    drafts = [original] if original and same_slot(original, candidate) and original["id"] not in committed else []
                else:
                    drafts = [v for v in state["variants"] if same_slot(v, candidate) and v["id"] not in committed]
                old = drafts[-1] if drafts else None
                # Chat-context SPEC §5.10: post media and the per-message content type survive "Save as drafts";
                # derived provenance ids join the draft's sources so retraction and policy checks still see them.
                live_assets = {a.get("id") for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and not a.get("deleted")}
                media = [m for m in candidate.get("media") or artifact.get("media") or [] if m.get("assetId") in live_assets]
                media_lost = len(candidate.get("media") or artifact.get("media") or []) > len(media)
                content = {k: candidate[k] for k in ("contentTypeId", "contentTypeVersion", "formatId", "format", "native", "nativeFields") if candidate.get(k) is not None}
                values = {"text": candidate["text"], "sourceIds": list(dict.fromkeys(list(candidate["sourceIds"]) + list(artifact.get("derivedSourceIds") or []))), "voiceSourceIds": [item["id"] for item in (artifact.get("voiceContext") or {}).get("bindings", [])], "voiceBindings": (artifact.get("voiceContext") or {}).get("bindings", []), "unknowns": candidate["unknowns"], "warnings": candidate.get("warnings", []) + (["Rewritten-source candidate: approve public use before publishing."] if candidate.get("candidateOnly") else []), "openings": [], "voiceRevision": state["speaker"].get("activeRevision"), "styleRevision": learning.revision(state), "briefRevision": state["brief"]["revision"], "runId": run_id}
                if media or media_lost or "media" in candidate:
                    values["media"] = media
                if media_lost:
                    values["warnings"] = values["warnings"] + ["A photo attached to this draft was deleted."]
                values.update(content)
                # The server-owned accepted selection is destination-specific and frozen
                # through candidate, variant, approval manifest and observed outcomes.
                values["trendLineage"] = [copy.deepcopy(b) for b in artifact.get("trendLineage", [])
                                           if b["platform"] == candidate["platform"] and b["channel_id"] == candidate.get("channelId")]
                if old:
                    if artifact.get("scoutLineage"):
                        values["scoutLineage"] = [b for b in artifact["scoutLineage"] if b["executionPlan"]["platform"] == candidate["platform"] and b["executionPlan"]["account"] == candidate.get("channelId")]
                    old["proposedUpdate"] = {**values, "baseVariantRevision": old["revision"]}
                    old["needsReview"] = True
                    # Keeps the link to this run after the proposal is accepted or edited, so reopening the
                    # run shows the text that is actually saved (bounded).
                    old["runRefs"] = ([ref for ref in old.get("runRefs") or [] if ref != run_id] + [run_id])[-10:]
                    created.append({"platform": candidate["platform"], "language": candidate["language"], "channelId": candidate.get("channelId"), "variantId": old["id"], "proposedUpdate": True})
                else:
                    if artifact.get("scoutLineage"):
                        values["scoutLineage"] = [b for b in artifact["scoutLineage"] if b["executionPlan"]["platform"] == candidate["platform"] and b["executionPlan"]["account"] == candidate.get("channelId")]
                    variant = {**values, "id": uid(), "revision": 1, "platform": candidate["platform"], "language": candidate["language"], **({"channelId": candidate["channelId"]} if candidate.get("channelId") else {}), "speakerId": state["speaker"].get("id"), "customized": False, "needsReview": True, "blockedByRetraction": False, "selectedOpening": 0, "localPreferences": {}, "revisions": [{"revision": 1, "text": candidate["text"], "origin": "ideas-candidate"}], "provenance": {"runId": run_id, "contextDigest": context_digest, "policyEpoch": epoch, "model": run_model}}
                    if tag:
                        variant["automation"] = dict(tag)
                    if rework:
                        variant["provenance"]["derivedFrom"] = rework
                    state["variants"].append(variant)
                    created.append({"platform": candidate["platform"], "language": candidate["language"], "channelId": candidate.get("channelId"), "variantId": variant["id"]})
            campaign_id = artifact.get("forCampaign")
            fresh = [item["variantId"] for item in created if not item.get("proposedUpdate")]
            live = campaign_id and any(c.get("id") == campaign_id and c.get("status") != "cancelled" for c in campaigns._root(state)["campaigns"])
            if live and fresh:
                # Saved in the same command as the drafts: the campaign lists them from the moment they exist.
                campaigns.apply_action(state, "raffi_campaign_link", {"campaignId": campaign_id, "draftIds": fresh}, actor, self.clock())
                linked.append(campaign_id)
            return state

        created, linked = [], []
        def current_trend_evidence(cur, state, actor):
            if artifact.get("trendLineage"):
                from .growth.trends.service import validate_stored_bindings
                validate_stored_bindings(self.repository.connection_factory, cur, workspace_id, actor, state,
                                         artifact["trendLineage"], self.clock())
        saved = self.repository.command(workspace_id, token, revision, command, after=current_trend_evidence)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("UPDATE public.pr_agent_runs SET status='applied',updated_at=now() WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        return {"runId": run_id, "status": "applied", "revision": saved["revision"], "variants": len(artifact["variants"]), "variantIds": list(created),
                "campaignId": linked[0] if linked else None}

    # --- source-first activation --------------------------------------------------
    def quick_start(self, workspace_id, token, revision, payload):
        """Thought/text/URL → one useful preview without connecting a channel."""
        started = time.monotonic()
        key = clean(payload.get("idempotencyKey", ""), 100)
        fingerprint = request_fingerprint("quick-start", payload)
        if key:
            replay = self._quick_start_replay(workspace_id, token, key, fingerprint)
            if replay:
                return replay
        credit_authority = self.credit_requests.authorize(workspace_id, token, revision, payload, "quick-start")
        text = clean(payload.get("text", ""), 20000)
        url = clean(payload.get("url", ""), 2000)
        if not text and not url:
            raise AlphaError("Paste a thought or text, or add a link, to start.")
        if payload.get("confirmUse") is not True:
            raise AlphaError("Confirm that you want Rafii to use this content for a draft.")
        own = payload.get("ownContent") is True
        # Refuse an unknown model or a reasoning level the writer does not offer before any source is stored.
        runtime, model_id, writer_note = self.resolve_writer(self._state_reader(workspace_id, token), payload.get("model"))
        _, level = translate_reasoning(runtime, model_id, requested_level(payload))
        zone = intent.safe_zone(payload.get("timeZone"))
        parsed = intent.parse_request(text, self.clock(), zone, runtime.supported_platforms() or None)
        # Chips (SPEC §6.1 quick_start): checked for shape now, and a message with chips always drafts, so neither
        # understanding nor the automation branches run; account/folder chips add destinations through the shared merge.
        refs = turn_references.parse(payload)
        chips = turn_references.present(refs)
        chip_destinations = []
        if chips:
            reading = None
            chip_destinations = turn_references.early(self.repository.get(workspace_id, token)["state"], refs, text, payload,
                                                      platforms=tuple(runtime.supported_platforms() or ()))["destinations"]
        else:
            parsed, reading = self._understand(workspace_id, token, text, zone, runtime, parsed)
        understood = (reading or {}).get("automation")
        language = locales.canonical(payload.get("language"))
        destinations = intent.resolve_destinations(parsed, self._with_chip_destinations(payload.get("destinations"), chip_destinations), language, [{"platform": "LinkedIn", "language": language or parsed["language"]}],
                                                   settings=lambda: self.repository.get(workspace_id, token)["state"])
        self._check_capability_revision(payload, destinations)
        if text and not chips and self._may_orchestrate(workspace_id, token, text, parsed, reading):
            # Home is the primary place to create, change or ask about automations (orchestration §7).
            conversation = self.create_conversation(workspace_id, token, clean(text[:60], 60))
            routed = self._orchestration_turn(workspace_id, token, conversation["conversationId"], text, parsed, reading, destinations, runtime, model_id, {**payload, "timeZone": zone}, writer_note=writer_note)
            if routed is not None:
                return {"conversationId": conversation["conversationId"], "sourceId": None, "sourcePolicy": None, **routed}
            if parsed["intent"] == "automation":
                run = self._automation_turn(workspace_id, token, conversation["conversationId"], text, destinations, runtime, model_id,
                                            {**payload, "timeZone": zone}, understood=understood, writer_note=writer_note)
                return {"conversationId": conversation["conversationId"], "sourceId": None, "sourcePolicy": None, **run}
            # Not an automation after all: drop the empty conversation; the draft gets its own below.
            with self.repository.transaction(token, workspace_id) as (cur, _, _):
                cur.execute("DELETE FROM public.pr_conversations c WHERE c.id::text=%s AND c.workspace_id=%s AND NOT EXISTS (SELECT 1 FROM public.pr_messages m WHERE m.conversation_id=c.id)", (conversation["conversationId"], workspace_id))

        if parsed["intent"] == "automation" and text and not chips:
            conversation = self.create_conversation(workspace_id, token, clean(text[:60], 60))
            run = self._automation_turn(workspace_id, token, conversation["conversationId"], text, destinations, runtime,
                                        model_id, {**payload, "timeZone": zone}, revision=revision, understood=understood, writer_note=writer_note)
            return {"conversationId": conversation["conversationId"], "sourceId": None, "sourcePolicy": None, **run}

        if level not in (None, AUTO):
            # An explicit level whose ceiling is over the per-request limit is refused before the source is stored.
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(self._member(row), "edit")
                self.estimate_request(self._state(row), payload, "quick-start", principal)

        chosen = {}

        def command(state, actor):
            checked_context_ids(state, payload.get("sourceIds", []))
            chosen["id"] = self._quick_start_source(state, actor, payload, text, url, own)["id"]
            if payload.get("audience"):
                state["brandHub"]["audience"] = clean(payload["audience"], 1500)
            if payload.get("goal"):
                state["brandHub"]["purpose"] = clean(payload["goal"], 1500)
            return state

        saved = self.repository.command(workspace_id, token, revision, command)
        source = next(item for item in saved["state"]["sources"] if item["id"] == chosen["id"])
        conversation = self.create_conversation(workspace_id, token, clean(text[:60] or url, 60))
        run = self.turn(workspace_id, token, conversation["conversationId"], {"text": "", "sourceIds": list(dict.fromkeys([source["id"]] + checked_context_ids(saved["state"], payload.get("sourceIds", [])))), "destinations": destinations, **({"reasoning": payload["reasoning"]} if "reasoning" in payload else {}), "timeZone": zone, "language": language, "intentText": text, "model": payload.get("model"), "voiceMode": payload.get("voiceMode", "neutral"), "voiceSourceIds": payload.get("voiceSourceIds"), "imageGeneration": payload.get("imageGeneration"), "research": payload.get("research"), "idempotencyKey": key,
                                                                    **{name: payload[name] for name in ("references", "attachments") if name in payload}}, _credit_authority=credit_authority, _request_fingerprint=fingerprint, _run_meta={"quickStart": {"sourceId": source["id"]}}, _started=started)
        return {"conversationId": conversation["conversationId"], "sourceId": source["id"], "sourcePolicy": source.get("sourcePolicy"), "revision": saved["revision"], **run}

    def _quick_start_source(self, state, actor, payload, text, url, own):
        """The source a quick-start drafts from, in `state`: reused when identical, else added."""
        kind = "idea" if (own and text and len(text) <= 500 and "\n" not in text) else ("text" if text else "link")
        # Drafting the same idea again (Rafii v9 "Generate again") reuses its active source instead of
        # refusing it as a duplicate. The fingerprint is the one the `source` command stores.
        fingerprint = hashlib.sha256((kind + clean(text or url, 20000)).encode()).hexdigest()
        source = next((s for s in state.get("sources", []) if s.get("active") and s.get("fingerprint") == fingerprint), None)
        if source is None:
            # Keep the stored title generic unless the caller explicitly supplied one. The source title can
            # become the workspace brief, so deriving it from third-party text would bypass source policy.
            self.commands(state, actor, "source", {"kind": kind, "text": text or url, "title": clean(payload.get("title", "Pasted source" if text else "Link"), 200)})
            source = state["sources"][-1]
            # A Home prompt needs a durable source for run provenance, but it is not reusable Context
            # Pocket material unless the person explicitly saves/captures it as a source.
            source["origin"] = {"kind": "quick_start"}
        stamp(state)
        # Own writing is quotable. A reused source is re-approved only when this changes its policy, so
        # drafts from the earlier run are not marked stale; an existing policy is never downgraded here.
        if own and source.get("sourcePolicy") != "public_quote":
            source["sourcePolicy"] = "public_quote"
            self.commands(state, actor, "approve_source", {"sourceId": source["id"], "factIds": [f["id"] for f in source["facts"]]})
        return source

    def _quick_start_replay(self, workspace_id, token, key, fingerprint):
        """The original quick-start answer for an exact resend; a different request under the key is refused."""
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit")
            prior = self._keyed_run(cur, workspace_id, key, fingerprint)
            if not prior:
                return None
            run = self._events_for(cur, workspace_id, prior, 0)
            revision, state = row[0], self._state(row)
        source_id = ((run.get("usage") or {}).get("quickStart") or {}).get("sourceId")
        source = next((s for s in state.get("sources", []) if s.get("id") == source_id), {})
        return {"conversationId": run["conversationId"], "sourceId": source_id, "sourcePolicy": source.get("sourcePolicy"), "revision": revision, **run}

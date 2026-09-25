"""Hosted Ideas conversation service: durable conversations, runs, safe events, apply.

Every call runs inside the workspace membership transaction. Runs execute the
AgentRuntime against a policy projection only; artifacts are candidates until an explicit
`apply`, which re-checks the projection so stale candidates are never applied silently.
"""
import copy
import base64
import hashlib
import json
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError, clean, uid
from postriff_alpha.generation import MATERIAL_LABEL
from .contracts import digest
from .permissions import require
from .source_policy import project_context, stamp
from .agent_runtime import SAFE_EVENTS, FixtureAgentRuntime, safe_event
from .cli_runtime import ClaudeCliRuntime
from .model_runtime import ProviderFailure
from .codex_runtime import CodexCliRuntime
from .skills import SkillLibrary, budget_for
from . import content_types, intent, locales, memory, research, voice_sources

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
            and (variant.get("channelId") or None) == (candidate.get("channelId") or None))


def usd_micro(cost_usd):
    """Provider cost in whole micro-dollars, rounded up so a reported cost is never under-recorded."""
    from decimal import ROUND_CEILING, Decimal
    return int((Decimal(repr(float(cost_usd))) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


IDEMPOTENCY_IGNORED = frozenset({"creditQuoteId", "expectedRevision", "idempotencyKey"})


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
                self.service._settle_message(cur, self.workspace_id, self.conversation_id, self.run_id, {"text": str(error), "runId": self.run_id, "failed": True, "intent": self.outcome["parsed"]["intent"], "destinations": self.outcome["destinations"], "plan": None, "model": self.outcome["model"]})
                return True
            self.service._insert_event(cur, self.workspace_id, self.run_id, safe_event("run.completed", usage={k: usage.get(k) for k in ("provenance", "modelRequests", "costUsd", "cliCostUsd", "billing") if k in usage}))
            return True

    def fail(self, message, known_cost_usd=None):
        """`known_cost_usd` is the provider cost proven for this failed run (0.0 when nothing was sent);
        None leaves a paid run's cost unknown until it is reconciled."""
        with self._open() as db, db.cursor() as cur:
            self.service._lock_run_events(cur, self.workspace_id, self.run_id)
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
            self.service._settle_message(cur, self.workspace_id, self.conversation_id, self.run_id, {"text": message, "runId": self.run_id, "failed": True, "intent": self.outcome["parsed"]["intent"], "destinations": self.outcome["destinations"], "plan": None, "model": self.outcome["model"]})
            return True


class IdeasService:
    def __init__(self, repository, commands, runtime=None, clock=None, ledger=None, runtimes=None, skill_library=None, researcher=None, image_runtime=None, assets=None):
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

    # --- routes and models ---------------------------------------------------------
    def model_catalog(self):
        """Every model a client may name in a turn, with the agent (CLI) behind each route."""
        models, agents = [], []
        for runtime in self.runtimes:
            models.extend({**model, "voiceAnalysisAvailable": callable(getattr(runtime, 'analyze_voice', None)), "provider": runtime.provider, "egress": getattr(runtime, "provider_class", "local"), "voiceRoute": (f"cloud:{runtime.provider}:{model['id']}" if getattr(runtime, "provider_class", "local") == "cloud" else "local-cli"), "reasoning": runtime.list_supported_reasoning()} for model in runtime.list_supported_models())
            info = runtime.describe()
            if info:
                agents.append(info)
        if any(m.get("qualified") and m.get("costClass") == "paid" and m.get("id") != "server-openai" for m in models):
            # The fixture lists a "Rafii managed model · not available yet" placeholder; next to a real managed writer
            # it only confuses the choice.
            models = [m for m in models if m.get("id") != "server-openai"]
        image_available = self.image_runtime is not None and self.assets is not None
        return {
            "models": models,
            "reasoning": self.default_runtime().list_supported_reasoning(),
            "agents": agents,
            "imageGeneration": {
                "available": image_available,
                "model": self.image_runtime.model if self.image_runtime is not None else None,
                "provider": self.image_runtime.provider if self.image_runtime is not None else None,
                "costClass": "paid",
                "independentOfWritingModel": True,
                "detail": "Uses one managed media credit and the approved image budget, independently of the selected writing model or local CLI." if image_available else "Configure the managed image route and private media storage to generate images in chat.",
            },
        }

    def rescan_models(self, workspace_id, token):
        """An editor may refresh installation and sign-in probes; no model generation runs."""
        with self.repository.transaction(token, workspace_id) as (_, row, _):
            require(self._member(row), "edit")
        with self._catalog_lock:
            if self._discover_cli:
                for cli in (ClaudeCliRuntime, CodexCliRuntime):
                    if not any(type(runtime) is cli for runtime in self.runtimes) and cli.available():
                        self.runtimes.append(cli(clock=self.clock))
            for runtime in self.runtimes:
                if isinstance(runtime, ClaudeCliRuntime):
                    runtime.detect(force=True)
            return self.model_catalog()

    @staticmethod
    def _automation_selection(state, chosen):
        """(selection, preflight rule ids, note) for an automation's own content type. None = general writing.
        A type that is no longer offered falls back to general writing with a note, never a failed run."""
        general = {"contentTypeId": "unclassified", "contentTypeVersion": None, "formatId": None}
        if not chosen:
            return general, (), None
        try:
            item = content_types.definition(state, chosen["contentTypeId"], chosen.get("contentTypeVersion"))
        except (AlphaError, KeyError, TypeError):
            return general, (), "This automation's content type is no longer available, so these drafts use general writing. Edit the automation to choose another type."
        return {"contentTypeId": item["id"], "contentTypeVersion": item["version"], "formatId": chosen.get("formatId")}, tuple(item.get("preflightRuleIds", ())), None

    def default_runtime(self):
        """The writer for a request that names no model. When a managed cloud writer is mounted, that one: the owner's
        rule is that no draft comes from templates unless the person chose them ("Templates (no AI model)" is the
        fixture's own id, so an explicit choice still reaches it). Otherwise the local default. This is a default for an
        absent choice, never a fallback: an unknown or refused model still raises, and a paid gate that refuses is
        never answered with template text."""
        return next((r for r in self.runtimes if getattr(r, "cost_class", None) == "paid" and getattr(r, "provider_class", None) == "cloud"), self.runtime)

    def _select_runtime(self, model_id):
        if not model_id:
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
            return {"files": memory.render_files(state), "egress": memory.egress_summary(state), "research": research.consent_summary(state), "learning": learned}

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

    def _automation_turn(self, workspace_id, token, conversation_id, text, destinations, runtime, model_id, payload, revision=None, understood=None):
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
                reasoning=payload.get("reasoning", "quick"), paid=runtime.cost_class == "paid",
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
            message = self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": reply, "intent": "automation", "automation": view, "destinations": destinations, "plan": None, "model": model_id, "runId": None})
        return {"runId": None, "conversationId": conversation_id, "status": "automation", "artifactHash": None, "artifact": None,
                "usage": {"provenance": "none", "modelRequests": 0, "costUsd": 0}, "model": model_id, "reasoning": payload.get("reasoning", "quick"),
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

    def _orchestration_turn(self, workspace_id, token, conversation_id, text, parsed, reading, destinations, runtime, model_id, payload):
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
                    return self._orchestrate(workspace_id, token, conversation_id, text, "answer", runtime, model_id, payload, {"pending": pending, "policy": policy}, reading)
            elif pending.get("question") == "review_time":
                try:
                    spec = automation_plan.answer_review_time(text, task["schedule"])
                except AlphaError:
                    spec = None
                if spec:
                    return self._orchestrate(workspace_id, token, conversation_id, text, "answer", runtime, model_id, payload, {"pending": pending, "generate": spec}, reading)
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
            return self._orchestrate(workspace_id, token, conversation_id, text, "explain", runtime, model_id, payload, {"explain": explain, "taskId": context.get("taskId")}, reading)
        if action == "edit" and has_automations:
            edit = (reading or {}).get("edit") or workflow_parse.read_edit(text, now, zone)
            if edit.get("changes"):
                return self._orchestrate(workspace_id, token, conversation_id, text, "edit", runtime, model_id, payload, {"edit": edit, "taskId": context.get("taskId")}, reading)
        if action == "automation":
            automation = (reading or {}).get("automation") if (reading or {}).get("action") == "automation" else None
            automation = automation or workflow_parse.read_automation(text, now, zone)
            if automation.get("schedule") and automation_plan.needs_workflow(automation, text):
                return self._orchestrate(workspace_id, token, conversation_id, text, "create", runtime, model_id, payload, {"automation": automation, "destinations": destinations}, reading)
        return None

    def _orchestrate(self, workspace_id, token, conversation_id, text, kind, runtime, model_id, payload, detail, reading):
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
                                                               reasoning=payload.get("reasoning", "quick"), voice=payload.get("voiceMode") == "personalized",
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
            message = self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": reply, "intent": "automation", "automation": view, "destinations": [], "plan": None, "model": model_id, "runId": None, "understanding": tier, **body_extra})
        return {"runId": None, "conversationId": conversation_id, "status": "automation", "artifactHash": None, "artifact": None,
                "usage": {"provenance": "none", "modelRequests": 0, "costUsd": 0}, "model": model_id, "reasoning": payload.get("reasoning", "quick"),
                "events": [], "cursor": 0, "automation": view, "reply": reply, "messageId": message["messageId"], "revision": current, **body_extra}

    def _memory_turn(self, workspace_id, token, conversation_id, text, parsed, destinations, model_id):
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
            body = {"text": reply, "intent": "memory", "memoryProposal": view, "destinations": destinations, "plan": None, "model": model_id, "runId": None}
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
        artifact["sourceBindings"] = [{"id": item["id"], "hash": item["hash"]} for item in outcome["context"]["sources"]]
        artifact["voiceContext"] = {key: (outcome.get("voiceContext") or {}).get(key) for key in ("mode", "bindings", "digest", "route")}
        artifact_hash = digest(artifact)
        usage = {**usage, "billing": usage.get("billing") or settlement.get("state"), "ledgerCostState": settlement.get("state"), "skillBindings": outcome.get("skillBindings", []), "skillOmissions": outcome.get("skillOmissions", []), "memoryBindings": outcome.get("memoryBindings"), "voiceBindings": artifact["voiceContext"].get("bindings", [])}
        cur.execute("UPDATE public.pr_agent_runs SET status='completed',artifact=%s::jsonb,artifact_hash=%s,usage=usage || %s::jsonb,updated_at=now() WHERE id::text=%s", (json.dumps(artifact, ensure_ascii=False), artifact_hash, json.dumps(usage), run_id))
        context = outcome["context"]
        found = f", {len(web_pages)} found on the web" if web_pages else ""
        summary = {"text": f"Drafted {len(artifact['variants'])} candidate variants from {len(context['sources'])} approved sources{found}.", "runId": run_id, "research": researched or None, "artifactHash": artifact_hash, "excluded": context["excluded"], "candidateOnly": context["candidateOnly"], "intent": outcome["parsed"]["intent"], "destinations": outcome["destinations"], "plan": outcome["plan"], "model": outcome["model"], "skills": [b["id"] for b in outcome.get("skillBindings", [])], "memory": outcome.get("memoryBindings")}
        self._settle_message(cur, workspace_id, conversation_id, run_id, summary)
        return artifact_hash

    def _settle_message(self, cur, workspace_id, conversation_id, run_id, body):
        """Fill the assistant turn for this run: update the pending placeholder if one exists, else append."""
        cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE conversation_id::text=%s AND workspace_id=%s AND run_id::text=%s AND role='assistant' RETURNING id::text", (json.dumps(body, ensure_ascii=False), conversation_id, workspace_id, run_id))
        if cur.fetchone() is None:
            self._append_message(cur, workspace_id, conversation_id, "assistant", body, run_id)
        else:
            cur.execute("UPDATE public.pr_conversations SET updated_at=now() WHERE id::text=%s", (conversation_id,))

    def _research(self, workspace_id, token, payload, text, parsed, key, conversation_id):
        """Step ①b: when the turn needs facts the workspace does not hold, look them up on the web before
        drafting (design §11 Phase 5). Runs outside the run's transaction because it is network I/O; the
        pages become ordinary third-party sources (use still needs the person's approval to publish) with
        provenance, so every claim in the draft traces to a page. Returns (new source ids, record)."""
        if self.researcher is None or payload.get("research") is False:
            return [], None
        message = text or clean(payload.get("intentText", ""), MAX_TEXT)
        if isinstance(payload.get("material"), str) and payload["material"].strip() and not research.urls_in(message):
            # A turn that hands in material (a draft to rework, a campaign brief) writes from that material: its
            # instruction ("Shorten this draft", "Adapt this for Instagram") is not a topic to look up on the web.
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

    def _image_turn(self, workspace_id, token, conversation_id, payload, text, selected_model, fingerprint=None):
        """Generate and privately store one image without delegating the capability to the writer."""
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
            self._append_message(cur, workspace_id, conversation_id, "user", {"text": prompt, "sourceIds": [], "intent": "image_generation"})
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
                (json.dumps({"provenance": "pending", "reservationId": reservation["reservationId"], "imageModel": self.image_runtime.model}), run_id),
            )
            self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": "", "pending": True, "runId": run_id, "intent": "image_generation", "images": [], "model": selected_model}, run_id)

        staged = None
        result = None
        queued_events = []
        try:
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
                self._settle_message(cur, workspace_id, conversation_id, run_id, {"text": "Generated one private image candidate for review.", "runId": run_id, "artifactHash": artifact_hash, "intent": "image_generation", "images": artifact["images"], "model": selected_model})
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

    def turn(self, workspace_id, token, conversation_id, payload, *, _credit_authority=None, _request_fingerprint=None, _run_meta=None):
        client_key = clean(payload.get("idempotencyKey", ""), 100)
        fingerprint = _request_fingerprint or request_fingerprint("turn", payload, conversation_id)
        if client_key and _credit_authority is None:
            # A resend is answered from its original run before any new approval or charge is checked.
            with self.repository.transaction(token, workspace_id) as (cur, row, _):
                require(self._member(row), "edit")
                self._conversation(cur, workspace_id, conversation_id)
                prior = self._keyed_run(cur, workspace_id, client_key, fingerprint)
                if prior:
                    return self._events_for(cur, workspace_id, prior, 0)
        credit_authority = _credit_authority or self.credit_requests.authorize(workspace_id, token, payload.get("expectedRevision"), payload, "turn", conversation_id)
        text = clean(payload.get("text", ""), MAX_TEXT)
        reasoning = payload.get("reasoning", "quick")
        key = client_key or uid()
        runtime = self._select_runtime(payload.get("model"))
        model_id = payload["model"] if isinstance(payload.get("model"), str) and payload.get("model") else runtime.model
        if self._wants_image(payload):
            return self._image_turn(workspace_id, token, conversation_id, {**payload, "idempotencyKey": key}, text, model_id, fingerprint)
        if isinstance(runtime, ClaudeCliRuntime):
            reasoning = runtime.effort(reasoning)
        elif reasoning not in ("quick", "standard", "deep"):
            raise AlphaError("Choose a reasoning level supported by this writer.", 400)
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
        reworking = isinstance(payload.get("material"), str) and bool(payload["material"].strip()) and not recurring
        if reworking:
            parsed = {**parsed, "intent": "draft", "unattachedTimes": [], "hasTimes": False,
                      "destinations": [{**d, "localTime": None} for d in parsed.get("destinations") or []]}
        understood = reading = None
        if text and not recurring and not reworking:
            parsed, reading = self._understand(workspace_id, token, text, zone, runtime, parsed)
            understood = (reading or {}).get("automation")
        elif parsed["intent"] == "automation":
            # Quick start already decided to draft this message now.
            parsed = {**parsed, "intent": "schedule" if parsed["hasTimes"] else "draft"}
        # Each (channel, language) pair is one destination; the workspace's remembered languages fill any channel the request left open.
        destinations = intent.resolve_destinations(parsed, payload.get("destinations"), payload.get("language"), DEFAULT_DESTINATIONS,
                                                   settings=lambda: self.repository.get(workspace_id, token)["state"])
        plan = intent.build_plan(parsed, destinations)
        if text and not recurring and not reworking:
            # Staged automations, answers to Rafii's questions, edits and "why?" questions (orchestration §7).
            routed = self._orchestration_turn(workspace_id, token, conversation_id, text, parsed, reading, destinations, runtime, model_id, payload)
            if routed is not None:
                return routed
        if parsed["intent"] == "automation" and text and not recurring:
            return self._automation_turn(workspace_id, token, conversation_id, text, destinations, runtime, model_id, payload, understood=understood)
        if parsed["intent"] == "memory" and text:
            return self._memory_turn(workspace_id, token, conversation_id, text, parsed, destinations, model_id)
        # A completed or in-flight writing run must not repeat research on HTTP replay.
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), 'edit')
            self._conversation(cur, workspace_id, conversation_id)
            prior = self._keyed_run(cur, workspace_id, key, fingerprint)
            if prior:
                return self._events_for(cur, workspace_id, prior, 0)
        research_ids, researched = self._research(workspace_id, token, payload, text, parsed, key, conversation_id)
        dispatch = None
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            stamp(state)
            existing = self._keyed_run(cur, workspace_id, key, fingerprint)
            if existing:
                return self._events_for(cur, workspace_id, existing, 0)
            projected = self._project(state, payload, runtime, model_id, reasoning, destinations, text, parsed, research_ids)
            destinations, source_ids, context = projected["destinations"], projected["sourceIds"], projected["context"]
            shared, voice_context, request, bound, reminders = projected["shared"], projected["voiceContext"], projected["request"], projected["bound"], projected["reminders"]
            # Writing material handed in with a request (an existing draft to rework, a campaign brief): the writer reads it
            # (_project), but it is never parsed for channels, times or instructions, and it is not stored as a source.
            material_ref = payload.get("materialRef") if isinstance(payload.get("materialRef"), dict) else None
            if text:
                # A caller that hands the writer one step of a longer request records the person's own words.
                said = clean(payload["messageText"], MAX_TEXT) if isinstance(payload.get("messageText"), str) and payload["messageText"].strip() else text
                self._append_message(cur, workspace_id, conversation_id, "user", {"text": said, "sourceIds": source_ids, "intent": parsed["intent"],
                                                                                   **({"material": {k: str(v)[:120] for k, v in material_ref.items() if k in ("type", "id", "title")}} if material_ref else {})})
            skill_ids = [b["id"] for b in bound["bindings"]]
            cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,usage) VALUES(%s,%s,%s,'running',%s,%s,%s,%s,%s,%s::jsonb) RETURNING id::text", (conversation_id, workspace_id, principal, model_id, reasoning, digest(context), context["policyEpoch"], key, json.dumps({"request": fingerprint, **(_run_meta or {})})))
            run_id = cur.fetchone()[0]
            # Credits gate before execution (§17): only a paid route reserves money or a writing batch.
            paid = runtime.cost_class == "paid"
            estimate = __import__('math').ceil(runtime.price_quote(request, model_id) * 1_000_000) if paid and hasattr(runtime, 'price_quote') else 500_000 if paid else 0
            recurring = getattr(self, 'recurring_binding', None)
            if recurring and estimate > recurring['maxCostUsdMicro']:
                raise AlphaError('This writer exceeds the confirmed per-occurrence cost limit.', 402)
            reservation = self.ledger.reserve(cur, workspace_id, principal, "text_model", estimate, f"run:{run_id}", charge_batch=paid, provider=runtime.provider, model=model_id, run_id=run_id, credit_authority=credit_authority)
            outcome = {"parsed": parsed, "plan": plan, "destinations": destinations, "context": context, "reservationId": reservation["reservationId"], "model": model_id, "skillBindings": bound["bindings"], "skillOmissions": bound.get("omitted", []), "research": researched, "memoryBindings": shared.get("learned"), "voiceContext": voice_context, "paid": paid, "actor": principal}
            if material_ref and material_ref.get("type") == "draft" and isinstance(material_ref.get("id"), str):
                # A rework of one draft: applying it updates that draft, not whichever draft shares its slot.
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
            context_events += [safe_event("warning.created", message=note) for note in parsed["warnings"] + bound["warnings"] + self._memory_notes(shared) + reminders]
            if researched:
                if not researched.get("off"):
                    context_events.append(safe_event("progress.updated", stage="researched", percent=8, pages=len(researched["pages"]), query=researched["query"]))
                context_events += [safe_event("warning.created", message=note) for note in researched.get("warnings", [])]
            if plan:
                context_events.append(safe_event("action.proposed", action="schedule_plan", destinations=len(plan["destinations"]), timeZone=plan["timeZone"]))

            if runtime.asynchronous or paid:
                emit(safe_event("run.started", model=model_id, reasoning="quick", contextDigest=digest(context)))
                for pending in context_events:
                    emit(pending)
                emit(safe_event("progress.updated", stage="queued", percent=5))
                cur.execute("UPDATE public.pr_agent_runs SET usage=usage || %s::jsonb WHERE id::text=%s", (json.dumps({"provenance": "pending", "reservationId": reservation["reservationId"], "skillBindings": bound["bindings"], "skillOmissions": bound.get("omitted", [])}), run_id))
                # The assistant turn exists from the start so the conversation can follow the run; the sink fills it in.
                self._append_message(cur, workspace_id, conversation_id, "assistant", {"text": "", "pending": True, "runId": run_id, "intent": parsed["intent"], "destinations": destinations, "plan": plan, "model": model_id, "skills": skill_ids, "research": researched}, run_id)
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
                        sink.fail(str(error), known_cost_usd=0.0)
                        raise AlphaError(str(error), error.status, code=error.code)
                    if error.cost_usd is not None:
                        sink.fail("The writer did not finish. This failed attempt was not charged.", known_cost_usd=error.cost_usd)
                        if error.status == 409:
                            raise AlphaError(str(error), 409, code=error.code)
                        raise AlphaError("The writer did not finish. This failed attempt was not charged; you can try again.", 502)
                    sink.fail("The writer did not finish. Usage may be pending; this run will not retry automatically.")
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

    def _project(self, state, payload, runtime, model_id, reasoning, destinations, text, parsed, research_ids=()):
        """Everything a writer route will receive for one drafting turn, computed from `state` alone."""
        # Account identity is verified against this workspace's connections (v9 §4).
        destinations = intent.bind_accounts(destinations, state)
        source_ids = payload.get("sourceIds") if isinstance(payload.get("sourceIds"), list) else [s["id"] for s in state.get("sources", []) if s.get("active") and s.get("kind") != "voice_sample"][:20]
        source_ids = [source_id for source_id in source_ids if not any(s.get("id") == source_id and s.get("kind") == "voice_sample" for s in state.get("sources", []))]
        source_ids = list(dict.fromkeys(list(source_ids) + list(research_ids)))
        # A cloud route only receives sources whose egress the person consented to; local routes see local consent.
        provider_class = getattr(runtime, "provider_class", "local")
        context = project_context(state, "draft", provider_class, source_ids)
        # The thought typed for this turn is the idea; quick-start passes it as intentText. Only a turn
        # without any text falls back to the workspace's saved brief.
        # The writer's `idea` field is bounded (IDEA_LIMIT); long text still reaches it whole as the message or source.
        raw_idea = text or str(payload.get("intentText") or "") or state.get("brief", {}).get("idea", "")
        idea = clean(raw_idea[:IDEA_LIMIT], IDEA_LIMIT)
        material = clean(payload["material"], MAX_TEXT) if isinstance(payload.get("material"), str) else ""
        if material:
            # Handed-in material (a draft to rework, a campaign brief) follows the instruction as data the writer reads
            # (generation.MATERIAL_LABEL); IDEA_LIMIT bounds the typed instruction, MAX_TEXT the material.
            idea += f"\n\n{MATERIAL_LABEL}\n<<<\n{material}\n>>>"
        selection = ((state.get("contentSystem") or {}).get("selection") or {})
        rule_ids = content_types.selected_rule_ids(state)
        recurring = getattr(self, 'recurring_binding', None)
        automation_notes = list((recurring or {}).get("notes") or [])
        if recurring and "contentType" in recurring:
            # An automation writes with the content type that was activated, not whatever Home has selected now.
            selection, rule_ids, note = self._automation_selection(state, recurring["contentType"])
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
            except AlphaError:
                if not recurring:
                    raise
            if not (voice_projection or {}).get("samples"):
                if not recurring:
                    raise AlphaError("Select and allow at least one writing sample for this writer route.", 409)
                # An automation keeps preparing drafts when its writing samples are gone or not allowed for this
                # writer; this draft is neutral and says so, never a failed run.
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
        # Step ③: skills are bound by destination, format, intent and content type, and recorded
        # by id/version/sha256 (design §7). The voice contract carries only the parts this turn uses.
        bound = self.skills.bind(destinations, selection.get("formatId"), parsed["intent"],
                                 content_type_id if content_type_id != "unclassified" else None,
                                 max_chars=budget_for(runtime.cost_class))
        request["skills"] = bound
        return {"destinations": destinations, "sourceIds": source_ids, "context": context, "shared": shared, "voiceContext": voice_context, "request": request, "bound": bound, "reminders": reminders}

    def estimate_request(self, state, payload, operation, actor):
        """The writer request a quick-start or turn would send now, for a credit estimate (no side effects)."""
        runtime = self._select_runtime(payload.get("model"))
        model_id = payload["model"] if isinstance(payload.get("model"), str) and payload.get("model") else runtime.model
        reasoning = payload.get("reasoning", "quick")
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
            projected = self._project(state, turn_payload, runtime, model_id, reasoning, destinations, "", parsed)
        else:
            text = clean(payload.get("text", ""), MAX_TEXT)
            parsed = intent.parse_request(text, self.clock(), zone, runtime.supported_platforms() or None)
            destinations = intent.resolve_destinations(parsed, payload.get("destinations"), payload.get("language"), DEFAULT_DESTINATIONS, settings=lambda: state)
            projected = self._project(state, payload, runtime, model_id, reasoning, destinations, text, parsed)
        return runtime, model_id, projected["request"]

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
                    self._settle_message(cur, wid, cid, run_id, {'text':'Writer interrupted. Review usage before starting another request.','runId':run_id,'failed':True,'pending':False})
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
            source_ids = sorted({item["id"] for item in artifact.get("sourceBindings", [])} | {sid for v in artifact["variants"] for sid in v["sourceIds"]})
            current = project_context(state, "draft", "local", source_ids)
            current_bindings = sorted(({"id": item["id"], "hash": item["hash"]} for item in current["sources"]), key=lambda item: item["id"])
            original_bindings = sorted(artifact.get("sourceBindings", []), key=lambda item: item["id"])
            if current["policyEpoch"] != epoch or current_bindings != original_bindings or current["excluded"]:
                raise AlphaError("Sources or their policies changed. Preserve the candidate and draft again from current context.", 409)
            voice_sources.validate_bindings(state, artifact.get("voiceContext") or {})
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
                values = {"text": candidate["text"], "sourceIds": candidate["sourceIds"], "voiceSourceIds": [item["id"] for item in (artifact.get("voiceContext") or {}).get("bindings", [])], "voiceBindings": (artifact.get("voiceContext") or {}).get("bindings", []), "unknowns": candidate["unknowns"], "warnings": candidate.get("warnings", []) + (["Rewritten-source candidate: approve public use before publishing."] if candidate.get("candidateOnly") else []), "openings": [], "voiceRevision": state["speaker"].get("activeRevision"), "styleRevision": learning.revision(state), "briefRevision": state["brief"]["revision"], "runId": run_id}
                if old:
                    old["proposedUpdate"] = {**values, "baseVariantRevision": old["revision"]}
                    old["needsReview"] = True
                    # Keeps the link to this run after the proposal is accepted or edited, so reopening the
                    # run shows the text that is actually saved (bounded).
                    old["runRefs"] = ([ref for ref in old.get("runRefs") or [] if ref != run_id] + [run_id])[-10:]
                    created.append({"platform": candidate["platform"], "language": candidate["language"], "channelId": candidate.get("channelId"), "variantId": old["id"], "proposedUpdate": True})
                else:
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
        saved = self.repository.command(workspace_id, token, revision, command)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("UPDATE public.pr_agent_runs SET status='applied',updated_at=now() WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        return {"runId": run_id, "status": "applied", "revision": saved["revision"], "variants": len(artifact["variants"]), "variantIds": list(created),
                "campaignId": linked[0] if linked else None}

    # --- source-first activation --------------------------------------------------
    def quick_start(self, workspace_id, token, revision, payload):
        """Thought/text/URL → one useful preview without connecting a channel."""
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
        runtime = self._select_runtime(payload.get("model"))  # refuse an unknown model before any source is stored
        if isinstance(runtime, ClaudeCliRuntime):
            runtime.effort(payload.get("reasoning", "quick"))
        elif payload.get("reasoning", "quick") not in ("quick", "standard", "deep"):
            raise AlphaError("Choose a reasoning level supported by this writer.", 400)
        zone = intent.safe_zone(payload.get("timeZone"))
        parsed = intent.parse_request(text, self.clock(), zone, runtime.supported_platforms() or None)
        parsed, reading = self._understand(workspace_id, token, text, zone, runtime, parsed)
        understood = (reading or {}).get("automation")
        language = locales.canonical(payload.get("language"))
        destinations = intent.resolve_destinations(parsed, payload.get("destinations"), language, [{"platform": "LinkedIn", "language": language or parsed["language"]}],
                                                   settings=lambda: self.repository.get(workspace_id, token)["state"])
        model_id = payload["model"] if isinstance(payload.get("model"), str) and payload.get("model") else runtime.model
        if text and self._may_orchestrate(workspace_id, token, text, parsed, reading):
            # Home is the primary place to create, change or ask about automations (orchestration §7).
            conversation = self.create_conversation(workspace_id, token, clean(text[:60], 60))
            routed = self._orchestration_turn(workspace_id, token, conversation["conversationId"], text, parsed, reading, destinations, runtime, model_id, {**payload, "timeZone": zone})
            if routed is not None:
                return {"conversationId": conversation["conversationId"], "sourceId": None, "sourcePolicy": None, **routed}
            if parsed["intent"] == "automation":
                run = self._automation_turn(workspace_id, token, conversation["conversationId"], text, destinations, runtime, model_id,
                                            {**payload, "timeZone": zone}, understood=understood)
                return {"conversationId": conversation["conversationId"], "sourceId": None, "sourcePolicy": None, **run}
            # Not an automation after all: drop the empty conversation; the draft gets its own below.
            with self.repository.transaction(token, workspace_id) as (cur, _, _):
                cur.execute("DELETE FROM public.pr_conversations c WHERE c.id::text=%s AND c.workspace_id=%s AND NOT EXISTS (SELECT 1 FROM public.pr_messages m WHERE m.conversation_id=c.id)", (conversation["conversationId"], workspace_id))

        if parsed["intent"] == "automation" and text:
            conversation = self.create_conversation(workspace_id, token, clean(text[:60], 60))
            run = self._automation_turn(workspace_id, token, conversation["conversationId"], text, destinations, runtime,
                                        model_id, {**payload, "timeZone": zone}, revision=revision, understood=understood)
            return {"conversationId": conversation["conversationId"], "sourceId": None, "sourcePolicy": None, **run}

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
        run = self.turn(workspace_id, token, conversation["conversationId"], {"text": "", "sourceIds": list(dict.fromkeys([source["id"]] + checked_context_ids(saved["state"], payload.get("sourceIds", [])))), "destinations": destinations, "reasoning": payload.get("reasoning", "quick"), "timeZone": zone, "language": language, "intentText": text, "model": payload.get("model"), "voiceMode": payload.get("voiceMode", "neutral"), "voiceSourceIds": payload.get("voiceSourceIds"), "imageGeneration": payload.get("imageGeneration"), "research": payload.get("research"), "idempotencyKey": key}, _credit_authority=credit_authority, _request_fingerprint=fingerprint, _run_meta={"quickStart": {"sourceId": source["id"]}})
        return {"conversationId": conversation["conversationId"], "sourceId": source["id"], "sourcePolicy": source.get("sourcePolicy"), "revision": saved["revision"], **run}

    def _quick_start_source(self, state, actor, payload, text, url, own):
        """The source a quick-start drafts from, in `state`: reused when identical, else added."""
        kind = "idea" if (own and text and len(text) <= 500 and "\n" not in text) else ("text" if text else "link")
        # Drafting the same idea again (Rafii v9 "Generate again") reuses its active source instead of
        # refusing it as a duplicate. The fingerprint is the one the `source` command stores.
        fingerprint = hashlib.sha256((kind + clean(text or url, 20000)).encode()).hexdigest()
        source = next((s for s in state.get("sources", []) if s.get("active") and s.get("fingerprint") == fingerprint), None)
        if source is None:
            self.commands(state, actor, "source", {"kind": kind, "text": text or url, "title": clean(payload.get("title", "Pasted source" if text else "Link"), 200)})
            source = state["sources"][-1]
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

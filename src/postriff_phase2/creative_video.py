"""Workspace-owned reference-to-video editing, explicit per-scene generation and private MP4 export."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from threading import BoundedSemaphore

from postriff_alpha.domain import AlphaError

from . import creative_video_blueprint as blueprint
from . import creative_video_first_frame as frames
from . import creative_video_strategy as strategies
from . import memory
from .api_tokens import is_api_token
from .billing import ops_metadata
from .contracts import digest
from .creative_video_assets import OutputVideo, asset, identity, read_video, validate_generated_clip
from .creative_video_media import analyze_reference, picture_frame, render_composition
from .creative_video_media_provider import VideoProvider, output_profile
from .creative_video_store import ProjectStore
from .credit_meter import millicredits
from .developer_usage import ai_usage_exempt
from .hosted import _membership, active_workspace_row, audit
from .permissions import require


_MEDIA_WORKERS = BoundedSemaphore(2)


@contextmanager
def local_media_slot():
    if not _MEDIA_WORKERS.acquire(blocking=False):
        raise AlphaError("Both video workers are busy. Check again shortly.", 429, code="creative_video_worker_busy")
    try:
        yield
    finally:
        _MEDIA_WORKERS.release()


@dataclass(frozen=True)
class _SavedPoll:
    """Internal capability constructed only from the row claimed by the authenticated worker tick."""
    workspace: str
    project: str
    key: str
    actor: str
    operation: str

    @contextmanager
    def transaction(self, repository, workspace):
        if workspace != self.workspace:
            raise AlphaError("Generation unavailable.", 403)
        with repository._principal_transaction(workspace, self.actor) as result:
            cur = result[0]
            cur.execute("""SELECT 1 FROM public.pr_jobs WHERE workspace_id=%s AND body->>'kind'='creative_video_scene'
                AND body->>'projectId'=%s AND body->>'idempotencyKey'=%s AND body->>'actor'=%s AND body->>'operation'=%s""",
                (workspace, self.project, self.key, self.actor, self.operation))
            if not cur.fetchone():
                raise AlphaError("The saved generation is unavailable.", 409)
            yield result


class CreativeVideoService:
    def __init__(self, hosted, *, store=None, provider_factory=None, provider_environment=None):
        self.hosted = hosted
        self.store = store or ProjectStore()
        environment = provider_environment or {}
        self.environment = {key: val for key, val in environment.items()
                            if key == "VERCEL_ENV" or key.startswith("RAFII_CREATIVE_VIDEO_")}
        aliases = {"development":"local", "dev":"local", "test":"local", "preview":"staging"}
        scopes = {aliases.get(value, value) for name in ("RAFII_CONTROL_ENVIRONMENT","POSTRIFF_ENVIRONMENT","VERCEL_ENV")
                  if (value := environment.get(name))}
        scopes = scopes or {"local"}
        self.deployment = next(iter(scopes)) if len(scopes) == 1 and scopes <= {"local","staging","production"} else None
        self.provider_factory = provider_factory

    @contextmanager
    def access(self, workspace, token, permission, *, with_member=False):
        if is_api_token(token):
            raise AlphaError("Sign in to work on a creative project.", 403)
        repository = self.hosted.repository
        transaction = (token.transaction(repository, workspace) if isinstance(token, _SavedPoll)
                       else repository.transaction(token, workspace))
        with transaction as (cur, row, actor):
            member = _membership(row)
            if permission == "compose":
                if not member.allows("edit"):
                    require(member, "approve")
            else:
                require(member, permission)
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            if permission != "read" and (state.get("workspace") or {}).get("sample"):
                raise AlphaError("Sample workspaces are read-only.", 403)
            values = (cur, state, actor, row[0])
            yield (*values, member) if with_member else values

    def catalog(self, cur=None):
        models = strategies.model_catalog(self.environment)
        if self.provider_factory:
            double = self.provider_factory()
            models = [{**m, "available": True, "reason": None} if m["id"] == double.model else m for m in models]
        if self.deployment is None:
            models = [{**m, "available":False, "reason":"The worker environment requires administrator verification."}
                      if m["mediaKind"] == "generated" else m for m in models]
        elif cur is not None:
            paused = self.store.paused_models(cur, self.deployment)
            models = [{**m, "available": False, "reason": "Paused by a Rafii administrator."}
                      if m["id"] in paused else m for m in models]
        cloud = next((m for m in models if m["available"] and m["mediaKind"] == "generated"), None)
        return {"models": models, "available": bool(cloud), "model": cloud["id"] if cloud else None,
                "provider": cloud["provider"] if cloud else None,
                "reason": None if cloud else "Paid footage is unavailable. Use a Draft storyboard or assign Library clips."}

    def _adapter(self, model, *, recovery=False):
        if self.provider_factory:
            provider = self.provider_factory()
            if provider.model == model:
                return provider
        return strategies.adapter_for(model, self.environment, for_recovery=recovery)

    def list(self, workspace, token):
        with self.access(workspace, token, "read") as (cur, _, _, _):
            return {"projects": self.store.list(cur, workspace), "provider": self.catalog(cur)}

    @staticmethod
    def _current(project, body):
        if type(body.get("revision")) is not int or project["revision"] != body["revision"]:
            raise AlphaError("The project changed. Reload the current revision.", 409, code="creative_revision_conflict")

    @staticmethod
    def _scene(project, scene_id):
        for scene in project["scenes"]:
            if scene["sceneId"] == scene_id:
                return scene
        raise AlphaError("Scene unavailable.", 404)

    def _scenes(self, cur, workspace, project, state):
        jobs = self.store.jobs(cur, workspace, project["scenes"])
        assets = {a.get("id"):a for a in (state.get("phase2") or {}).get("assets", []) if not a.get("deleted")}
        source_kinds = {"generated_scene":"generated","storyboard_composition":"composed",
                        "composition_render":"composed","workspace_upload":"user-provided"}
        result = []
        for scene in project["scenes"]:
            job = jobs.get(self.store.key(scene))
            clip = scene["clipId"] or (job or {}).get("assetId")
            item = {k: v for k, v in scene.items() if k != "take"}
            item.update(clipId=clip, clipOrigin="library" if scene["clipId"] else (job.get("mediaKind", "generated") if clip else None),
                        estimatedUsdMicro=job.get("estimatedUsdMicro") if job else 0 if clip else None)
            origin = (assets.get(clip) or {}).get("provenance") or {}
            clip_seconds = (assets.get(clip) or {}).get("duration")
            item["clipDurationMs"] = round(clip_seconds * 1000) if type(clip_seconds) in (float, int) else None
            item["sourceMediaKind"] = source_kinds.get(origin.get("operation"), "unknown") if clip else None
            item["estimatedMilliCredits"] = millicredits(item["estimatedUsdMicro"]) if item["estimatedUsdMicro"] is not None else None
            if job:
                item["generation"] = {k: job.get(k) for k in ("state", "estimatedUsdMicro", "actualUsdMicro", "reason",
                    "model","provider","mediaKind","pricingVersion","estimatedMilliCredits","maxMilliCredits","settlementState","accepted")}
                item["generation"]["cancellable"] = (job["state"] == "pending" and bool(job.get("cancellable"))
                                                     and not job.get("cancelRequested"))
            result.append(item)
        return result

    def _view(self, cur, workspace, project, state):
        context = {**project["context"], "cloudAllowed": memory.egress(state).get("cloud") is True}
        public = {k: v for k, v in project.items() if k not in ("memoryReceipt", "referenceIdentity", "context", "scenes")}
        return {"project": {**public, "context": context, "scenes": self._scenes(cur, workspace, project, state),
                            "history": self.store.history(cur, workspace, project["id"])}, "provider": self.catalog(cur)}

    def get(self, workspace, token, pid, revision=None):
        with self.access(workspace, token, "read") as (cur, state, _, _):
            return self._view(cur, workspace, self.store.get(cur, workspace, pid, revision), state)

    def performance(self, workspace, token, pid, revision):
        from .creative_video_performance import revision_performance
        with self.access(workspace, token, "read") as (cur, state, actor, _):
            project = self.store.get(cur, workspace, pid, revision)
            return revision_performance(cur, workspace, project, state, self.hosted.oauth,
                                        token, actor, self.hosted.clock())

    def _reference_link(self, cur, workspace, state, token, actor, body):
        from .creative_video_performance import resolve_reference_link
        return resolve_reference_link(cur, workspace, state, self.hosted.oauth, token, actor, self.hosted.clock(), body)

    def reference_link(self, workspace, token, body):
        with self.access(workspace, token, "read") as (cur, state, actor, _):
            return self._reference_link(cur, workspace, state, token, actor, body)

    def create(self, workspace, token, body):
        brief = blueprint.validate_brief(body)
        key = brief["requestId"]
        fingerprint = digest(brief)
        def verify_link(cur, state, actor):
            if "referenceLink" in brief:
                match = self._reference_link(cur, workspace, state, token, actor, {"url": brief["referenceLink"]})
                if match["assetId"] != brief["referenceAssetId"]:
                    raise AlphaError("The linked Library video changed. Resolve the link again.", 409)

        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            verify_link(cur, state, actor)
            existing = self.store.request(cur, workspace, key, fingerprint)
            if existing:
                return self._view(cur, workspace, self.store.get(cur, workspace, existing), state)
            source = asset(state, brief["referenceAssetId"]) if brief["referenceAssetId"] else None
        analysis = blueprint.brief_analysis()
        if source:
            from .creative_video_reference_signals import reference_signals
            with local_media_slot():
                raw = read_video(self.hosted, workspace, source)
                analysis = analyze_reference(raw)
                analysis["overlaySignals"] = reference_signals(raw, analysis)
                if "speechTimingLanguage" in brief:
                    from .creative_video_speech import speech_timing
                    analysis["speechTiming"] = speech_timing(raw, analysis, brief["speechTimingLanguage"],
                                                             self.environment.get("RAFII_CREATIVE_VIDEO_WHISPER_MODEL"))
                del raw
        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            verify_link(cur, state, actor)
            if source and identity(asset(state, brief["referenceAssetId"])) != identity(source):
                raise AlphaError("The reference changed during analysis.", 409)
            existing = self.store.request(cur, workspace, key, fingerprint)
            if not existing:
                context, receipt = blueprint.project_context(state, brief["platform"])
                project = {k: brief[k] for k in ("title", "brief", "referenceAssetId", "platform", "aspectRatio")}
                project.update(analysis=analysis, context=context, memoryReceipt=receipt, referenceIdentity=list(identity(source)) if source else None,
                               rights={"confirmedBy": actor, "scope": "analyze-reference-only"} if source else None)
                existing = self.store.create(cur, workspace, actor, key, fingerprint, project, blueprint.adapt(brief, analysis, context))
                audit(cur, workspace, actor, "creative_video.created", existing, {"revision": 1})
            return self._view(cur, workspace, self.store.get(cur, workspace, existing), state)

    def edit(self, workspace, token, pid, body):
        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            project = self.store.get(cur, workspace, pid)
            self._current(project, body)
            self._recover_claims(cur, workspace)
            if set(body) not in ({"revision", "scenes"}, {"revision", "scenes", "sceneOrder"}) or ("sceneOrder" in body and body["sceneOrder"] is None):
                raise AlphaError("Submit scene edits for the current revision.")
            jobs = self.store.jobs(cur, workspace, project["scenes"])
            generated = {s["take"]: jobs[self.store.key(s)]["assetId"] for s in project["scenes"]
                         if jobs.get(self.store.key(s), {}).get("assetId")}
            scenes = blueprint.edit_scenes(project["scenes"], body["scenes"], project["referenceAssetId"],
                                           lambda key: asset(state, key), order=body.get("sceneOrder"), generated_clips=generated)
            if scenes != project["scenes"]:
                old = {s["sceneId"]: s for s in project["scenes"]}
                for after in scenes:
                    before = old[after["sceneId"]]
                    job = jobs.get(self.store.key(before), {})
                    if before["take"] != after["take"] and job.get("state") in ("pending", "submitting", "unknown", "cancelling"):
                        raise AlphaError("Reconcile the current generation before changing this shot.", 409)
                self.store.edit(cur, workspace, project, scenes, actor)
                audit(cur, workspace, actor, "creative_video.edited", pid, {"revision": project["revision"]+1})
            return self._view(cur, workspace, self.store.get(cur, workspace, pid), state)

    def variants(self, workspace, token, pid, body):
        """Create editable project copies in one workspace transaction, without generation or publishing."""
        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            if (set(body) != {"revision", "requestId", "targets", "reuseRightsConfirmed"}
                    or body["reuseRightsConfirmed"] is not True or type(body["revision"]) is not int
                    or not 1 <= body["revision"] <= 999_999_999
                    or not isinstance(body["targets"], list) or not 1 <= len(body["targets"]) <= 3):
                raise AlphaError("Choose one to three destinations and confirm the rights to reuse these shots.")
            source = self.store.get(cur, workspace, pid, body["revision"])
            destinations = []
            for target in body["targets"]:
                if not isinstance(target, dict) or set(target) != {"platform", "aspectRatio"}:
                    raise AlphaError("Choose a platform and frame for each version.")
                values = {"title": source["title"], "brief": source["brief"], "referenceAssetId": source["referenceAssetId"],
                          "requestId": body["requestId"], "rightsConfirmed": source["referenceAssetId"] is not None, **target}
                blueprint.validate_brief(values)
                if target in destinations:
                    raise AlphaError("Choose each destination and frame once.")
                destinations.append(target)
            binding = digest({"source": source["id"], "actor": actor, **body})
            projects = []
            prepared = None
            for index, target in enumerate(destinations):
                key = f"variant:{body['requestId']}:{index}"
                ident = self.store.request(cur, workspace, key, binding)
                if not ident:
                    if prepared is None:
                        self._reference(source, state)
                        memory.validate_receipt(state, source["memoryReceipt"])
                        prepared = self._variant_scenes(cur, workspace, source, state)
                    context, receipt = blueprint.project_context(state, target["platform"])
                    if context != source["context"]:
                        raise AlphaError("The approved brand context differs for this destination. Create a fresh blueprint.", 409)
                    title = f"{source['title'][:80]} · {target['platform']} {target['aspectRatio']}"
                    brief = {key: source[key] for key in ("brief", "referenceAssetId", "referenceIdentity", "analysis", "rights")}
                    brief.update(target, title=title, context=context, memoryReceipt=receipt,
                                 origin={"projectId": source["id"], "revision": source["revision"]})
                    scenes = [{**scene, "take": uuid.uuid4().hex} for scene in prepared]
                    ident = self.store.create(cur, workspace, actor, key, binding, brief, scenes)
                    audit(cur, workspace, actor, "creative_video.variant_created", ident, brief["origin"])
                projects.append({"id": ident, **target})
            return {"projects": projects}

    def _variant_scenes(self, cur, workspace, source, state):
        jobs = self.store.jobs(cur, workspace, source["scenes"])
        scenes = []
        for original in source["scenes"]:
            # Copy editorial fields only. Quotes, future provider inputs and job authority belong to the original project.
            scene = {key: original[key] for key in ("sceneId", "purpose", "direction", "caption", "durationMs",
                     "sourceStartMs", "sourceEndMs", "evidence") if key in original}
            job = jobs.get(self.store.key(original), {})
            clip = original["clipId"]
            if not clip and job.get("state") == "completed" and job.get("accepted") is True:
                clip = job.get("assetId")
            if clip:
                asset(state, clip)
                if "trimStartMs" in original:
                    scene["trimStartMs"] = original["trimStartMs"]
            scene["clipId"] = clip
            scenes.append(scene)
        return scenes

    def _credit_authority(self, cur, workspace, workspace_revision, approval, provider, body):
        actor = approval["actor"]
        if ops_metadata(cur, workspace) or ai_usage_exempt(actor):
            # Ledger.reserve enforces the server-created Founder identity and saved spending policy.
            # A server-allowlisted exemption still requires this scene's explicit USD approval.
            return None
        book = self.hosted.ledger.credits
        if not book or not book.policy(cur, workspace):
            raise AlphaError("This workspace needs an active credit plan to generate paid video.", 402,
                             code="creative_video_credit_policy_required")
        maximum = body.get("maxMilliCredits")
        if type(maximum) is not int or maximum < millicredits(approval["estimatedUsdMicro"]):
            raise AlphaError("Confirm the credit limit for this scene.", 402)
        binding = digest({**approval, "maxMilliCredits": maximum})
        quote = book.issue(cur, workspace, actor, workspace_revision, binding, provider.model, provider.provider, maximum)
        return book.authorize(cur, workspace, actor, workspace_revision, binding, quote["quoteId"])

    @staticmethod
    def _reference(project, state):
        if not project["referenceAssetId"]:
            return
        source = asset(state, project["referenceAssetId"])
        if list(identity(source)) != project.get("referenceIdentity"):
            raise AlphaError("The analyzed reference changed. Review the current reference.", 409)

    def _wallet(self, cur, workspace, actor):
        if ops_metadata(cur, workspace) or ai_usage_exempt(actor):
            return "internal", None
        book = self.hosted.ledger.credits
        if book and book.policy(cur, workspace):
            return "credits", book.view(cur, workspace)["availableMilliCredits"]
        return "allowance", None

    @staticmethod
    def _prompt(project, scene, state, strategy):
        if strategy["mediaKind"] == "composed":
            # These are the only strings the local renderer may put on a storyboard card.
            memory.validate_receipt(state, project["memoryReceipt"])
            return strategies.apply_direction(scene["direction"][:180], strategy)
        route = (blueprint.VIDEO_ROUTE if strategy["provider"] == VideoProvider.provider
                 else f"cloud:{strategy['provider']}:{strategy['model']}")
        base = blueprint.generation_prompt(project, scene, state, route=route)
        return strategies.apply_direction(base, strategy)

    def _proposal(self, cur, workspace, actor, project, scene, state, settings, models, *, wallet=None):
        self._reference(project, state)
        billing, balance = wallet if wallet is not None else self._wallet(cur, workspace, actor)
        available = [m for m in models if m["available"]]
        last_limitation = None
        while True:
            try:
                strategy = strategies.route_scene(settings, duration_ms=scene["durationMs"], aspect_ratio=project["aspectRatio"],
                    available_models=available, available_millicredits=balance, preview_over_budget=True)
            except AlphaError:
                if last_limitation:
                    raise last_limitation
                raise
            try:
                prompt = self._prompt(project, scene, state, strategy)
                break
            except AlphaError as error:
                if settings.get("mode") == "manual" or error.status not in (403, 422) or len(available) <= 1:
                    raise
                last_limitation = error
                available = [model for model in available if model["id"] != strategy["model"]]
        if strategy["settings"].get("firstFrameAssetId"):
            strategy["firstFrame"] = frames.manifest(state, workspace, strategy["settings"]["firstFrameAssetId"])
        maximum = strategy["settings"].get("maxMilliCredits")
        estimate = strategy["estimatedMilliCredits"]
        # Hold only the selected price. The search budget does not authorize extra takes.
        reason = None
        if estimate and billing == "allowance":
            reason = "This workspace needs an active AI Credits plan for paid footage."
        elif balance is not None and estimate > balance:
            reason = "Insufficient available credits. Choose a shorter scene, Draft storyboard or Library footage."
        elif maximum is not None and estimate > maximum:
            reason = "The selected route exceeds your maximum AI Credits."
        if scene["clipId"]:
            reason = "This scene already has assigned footage. Reuse it or prepare another take."
        binding = {"revision": project["revision"], "take": scene["take"], "billing": billing,
                   "promptDigest": hashlib.sha256(prompt.encode()).hexdigest(), "strategy": strategy}
        view = {**strategy, "id": None, "expiresAt": None, "availableMilliCredits": balance,
                "remainingMilliCredits": None if balance is None else balance - estimate,
                "maximumMilliCredits": estimate, "eligible": reason is None, "reason": reason,
                "expectedGenerationSeconds": strategies.observed_latency(models, strategy)}
        return binding, view, prompt

    def quote(self, workspace, token, pid, body):
        if not isinstance(body, dict) or set(body) != {"revision", "sceneId", "settings"} or not isinstance(body["settings"], dict):
            raise AlphaError("Choose generation settings for the current scene.")
        with self.access(workspace, token, "compose", with_member=True) as (cur, state, actor, _, member):
            project = self.store.get(cur, workspace, pid)
            self._current(project, body)
            scene = self._scene(project, body["sceneId"])
            settings = body["settings"]
            selects_local = (settings.get("model") == "storyboard-v1" if settings.get("mode") == "manual"
                             else settings.get("level") == "draft")
            if not selects_local or "firstFrameAssetId" in settings:
                require(member, "approve")
            models = self.catalog(cur)["models"]
            ranked = strategies.apply_observations(models, strategies.workspace_observations(cur, workspace))
            binding, view, _ = self._proposal(cur, workspace, actor, project, scene, state, settings, ranked)
            if self.store.jobs(cur, workspace, [scene]):
                view.update(eligible=False, reason="This take already has a generation. Open its status or prepare a new take.")
            if view["eligible"]:
                view["id"], view["expiresAt"] = self.store.issue_quote(cur, workspace, pid, actor, scene["sceneId"], binding)
            return {"quote": view, "models": models}

    def plan(self, workspace, token, pid, body):
        if (not isinstance(body, dict) or not {"revision","settings"} <= body.keys() <= {"revision","settings","sceneSettings"}
                or not isinstance(body["settings"], dict) or not isinstance(body.get("sceneSettings", {}), dict)):
            raise AlphaError("Choose settings for this project plan.")
        options, overrides = body["settings"], body.get("sceneSettings", {})
        if overrides and options.get("mode") != "hybrid":
            raise AlphaError("Use Hybrid planning to choose different settings for individual scenes.")
        with self.access(workspace, token, "compose", with_member=True) as (cur, state, actor, _, member):
            project = self.store.get(cur, workspace, pid)
            self._current(project, body)
            if not overrides.keys() <= {s["sceneId"] for s in project["scenes"]}:
                raise AlphaError("Choose scenes belonging to this project.")
            self._reference(project, state)
            models = strategies.apply_observations(self.catalog(cur)["models"], strategies.workspace_observations(cur, workspace))
            jobs = self.store.jobs(cur, workspace, project["scenes"])
            billing, balance = self._wallet(cur, workspace, actor)
            budget = options.get("maxMilliCredits")
            if budget is not None and (type(budget) is not int or not 0 <= budget <= 100_000_000):
                raise AlphaError("Choose a supported maximum AI Credits budget.")
            total, unpriced, rows = 0, 0, []
            for scene in project["scenes"]:
                ident = scene["sceneId"]
                job = jobs.get(self.store.key(scene), {})
                if scene["clipId"] or job.get("assetId") or job.get("state") in ("pending","submitting","unknown"):
                    label = "Reuse assigned footage" if scene["clipId"] or job.get("assetId") else "Resume the existing take"
                    rows.append({"sceneId": ident, "label": label, "estimatedMilliCredits": 0, "mediaKind":
                                 "library" if scene["clipId"] else job.get("mediaKind","generated")})
                    continue
                settings = overrides.get(ident, options)
                if not isinstance(settings, dict):
                    raise AlphaError("Choose valid Hybrid settings for this scene.")
                if "firstFrameAssetId" in settings:
                    require(member, "approve")
                if budget is not None:
                    cap = settings.get("maxMilliCredits", budget)
                    if type(cap) is not int or cap < 0:
                        raise AlphaError("Choose a supported scene budget.")
                    settings = {**settings, "maxMilliCredits": min(cap, max(0, budget-total))}
                try:
                    _, view, _ = self._proposal(cur, workspace, actor, project, scene, state, settings, models,
                                                wallet=(billing, None if balance is None else max(0, balance-total)))
                    if view["mediaKind"] != "composed":
                        require(member, "approve")
                    if not view["eligible"]:
                        raise AlphaError(view["reason"], 402)
                    total += view["estimatedMilliCredits"]
                    rows.append({k:view[k] for k in ("model","label","mediaKind","estimatedMilliCredits","recommendation")} | {"sceneId": ident})
                except AlphaError as error:
                    if error.status >= 500:
                        raise
                    unpriced += 1
                    rows.append({"sceneId":ident,"label":"Review this scene","mediaKind":None,
                                 "estimatedMilliCredits":None,"reason":str(error)})
            return {"scenes": rows, "totalMilliCredits": None if unpriced else total,
                    "pricedMilliCredits": total, "unpricedScenes": unpriced}

    def generate(self, workspace, token, pid, body):
        if (not isinstance(body, dict) or set(body) != {"confirmed", "revision", "sceneId", "quoteId"}
                or body["confirmed"] is not True):
            raise AlphaError("Review the current server quote and confirm this scene.", 400)
        try:
            quote_id = str(uuid.UUID(body["quoteId"]))
        except (AttributeError, ValueError, TypeError):
            raise AlphaError("Review a valid generation quote first.", 400) from None
        with self.access(workspace, token, "compose", with_member=True) as (cur, state, actor, workspace_revision, member):
            project = self.store.get(cur, workspace, pid)
            self._current(project, body)
            self._recover_claims(cur, workspace)
            scene = self._scene(project, body.get("sceneId"))
            key = self.store.key(scene)
            existing = self.store.jobs(cur, workspace, [scene]).get(key)
            if existing:
                if existing.get("mediaKind") != "composed":
                    require(member, "approve")
                if existing.get("quoteId") != quote_id or existing.get("actor") != actor:
                    raise AlphaError("This scene already has a take. Open the existing generation.", 409)
                return self._view(cur, workspace, project, state)
            saved = self.store.reviewed_quote(cur, workspace, pid, actor, scene["sceneId"], quote_id)
            if saved["strategy"]["mediaKind"] != "composed":
                require(member, "approve")
            models = [m for m in self.catalog(cur)["models"] if m["id"] == saved["strategy"]["model"]]
            binding, view, prompt = self._proposal(cur, workspace, actor, project, scene, state, saved["strategy"]["settings"], models)
            if not view["eligible"]:
                raise AlphaError(view["reason"], 402)
            if binding != saved:
                raise AlphaError("The quoted route, price, permissions or scene changed. Review a fresh quote.", 409)
            strategy = saved["strategy"]
            provider = self._adapter(strategy["model"])
            # A bounded private read checks the exact content-addressed rendition before reserving credits.
            image_args = {"first_frame": frames.read(self.hosted, workspace, strategy["firstFrame"])} if "firstFrame" in strategy else {}
            cost = strategy["estimatedUsdMicro"]
            maximum = view["maximumMilliCredits"]
            self.hosted.video_uploads._ready()
            self.store.admit_job(cur, workspace)
            approval = {"kind": "creative_video_generation", "idempotencyKey": key, "projectId": project["id"],
                        "sceneId": scene["sceneId"], "revision": project["revision"], "actor": actor,
                        "quoteId": quote_id, "strategy": strategy, "estimatedUsdMicro": cost, "maxUsdMicro": cost,
                        "estimatedMilliCredits": maximum, "maxMilliCredits": maximum, "model": provider.model,
                        "provider": provider.provider, "mediaKind": strategy["mediaKind"], "pricingVersion": strategy["pricingVersion"],
                        "durationMs": scene["durationMs"], "aspectRatio": project["aspectRatio"],
                        "outputProfile": strategy["outputProfile"], "promptDigest": saved["promptDigest"]}
            cur.execute("SELECT plan_terms_id FROM public.pr_entitlements WHERE workspace_id=%s", (workspace,))
            term = cur.fetchone()
            approval["planTerms"] = term[0] if term else "unassigned"
            reservation_id = None
            if strategy["mediaKind"] == "generated":
                authority = self._credit_authority(cur, workspace, workspace_revision, approval, provider, {"maxMilliCredits":maximum})
                if authority:
                    approval.update(creditQuoteId=authority["quoteId"], creditRequestDigest=authority["requestDigest"])
                reservation = self.hosted.ledger.reserve(cur, workspace, actor, "tool", cost, key, charge_batch=False,
                    model=provider.model, provider=provider.provider, job_id=key, credit_authority=authority,
                    meta={"via":"creative_video_generation","feature":"creative_video","projectRevision":project["revision"],
                          "videoQuoteId":quote_id,"pricingVersion":strategy["pricingVersion"]})
                if reservation["duplicate"]:
                    raise AlphaError("This generation already has a reservation. Reconciliation is required.", 409)
                reservation_id = reservation["reservationId"]
            job = {**approval, "kind": "creative_video_scene", "state": "submitting", "actualUsdMicro": None,
                   "cancellable": callable(getattr(provider, "cancel", None)), "reservationId": reservation_id}
            self.store.insert_job(cur, workspace, job, approval)
            audit(cur, workspace, actor, "creative_video.generation_approved", pid, {"revision": project["revision"], "sceneId": scene["sceneId"]})
        # Network I/O starts only after the transaction durably commits the claim.
        try:
            operation = provider.submit(prompt=prompt, duration_ms=scene["durationMs"], aspect_ratio=project["aspectRatio"],
                                        strategy=strategy, **image_args)
        except Exception as error:
            uncertain = getattr(error, "uncertain", not isinstance(error, AlphaError) or error.status >= 500)
            self._record(workspace, job, "unknown" if uncertain else "failed", reason="submission_unknown" if uncertain else "request_declined",
                         outcome="unknown" if uncertain else "failed", cost=None if uncertain else 0)
            raise
        self._record(workspace, job, "pending", operation=operation)
        return self.get(workspace, token, pid)

    def _transition(self, cur, workspace, job, state, *, outcome=None, cost=None, **fields):
        if (state in ("completed","failed","cancelled") and outcome and cost is None
                and job.get("provider") == "runway" and job.get("operation")):
            saved = self.store.locked_usage_job(cur, workspace, job)
            receipt = saved.get("providerUsage") or {}
            if saved.get("reason") != "provider_usage_disputed" and receipt.get("costSource") == "provider_task_usage":
                value = receipt.get("costUsdMicro")
                if type(value) is int and value >= 0:
                    cost, outcome = value, "completed" if state == "completed" else "failed"
        fields["state"] = state
        if state in ("completed", "failed", "cancelled") and job.get("strategy"):
            import time
            fields.setdefault("finishedAt", int(time.time()))
        if outcome:
            fields["actualUsdMicro"] = cost
        changed = self.store.update_job(cur, workspace, job["idempotencyKey"], job["state"], fields)
        if changed and outcome and job.get("reservationId"):
            self.hosted.ledger.settle(cur, workspace, job["reservationId"], outcome, cost)
        return changed

    def _recover_claims(self, cur, workspace):
        for job in self.store.stale_submissions(cur, workspace):
            if job.get("mediaKind") == "composed" and job.get("provider") == "rafii-local" and job.get("reservationId") is None:
                self._transition(cur, workspace, job, "failed", outcome="failed", cost=0, reason="storyboard_interrupted")
            else:
                self._transition(cur, workspace, job, "unknown", outcome="unknown", reason="submission_unknown")

    def _record(self, workspace, job, state, *, outcome=None, cost=None, **fields):
        # Internal recording preserves a known provider effect if the actor loses permission during I/O.
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace,))
            if not cur.fetchone():
                return
            changed = self._transition(cur, workspace, job, state, outcome=outcome, cost=cost, **fields)
            if not changed and job["state"] == "submitting" and state in ("pending", "failed"):
                # A very late acknowledgement can identify an orphaned claim while its invoice remains open.
                # No second submission is made. A completed native reconciliation has final authority.
                self._transition(cur, workspace, {**job, "state": "unknown"}, state, outcome=outcome, cost=cost,
                                 **{"reason": None, **fields})

    def _poll_inputs(self, cur, workspace, pid, body):
        project = self.store.get(cur, workspace, pid)
        self._current(project, body)
        scene = self._scene(project, body.get("sceneId"))
        job = self.store.jobs(cur, workspace, [scene]).get(self.store.key(scene))
        if not job:
            raise AlphaError("No generation exists for this shot.", 409)
        return project, scene, job

    def _authorized_result(self, cur, workspace, project, scene, job, state, *, cost=None, output=None):
        # Same operation and take can survive unrelated editorial changes. Re-evaluate precisely what
        # was authorized before any poll and before committing any returned bytes to the Library.
        active = self.store.jobs(cur, workspace, [scene]).get(job["idempotencyKey"])
        if not active or active["state"] != "pending" or active.get("operation") != job.get("operation"):
            if output and active and active.get("operation") == job.get("operation"):
                if active["state"] == "failed" or (active["state"] == "completed" and active.get("assetId") != output.id):
                    output.abort(cur, "another_poll_finished")
            return False
        current = next((s for s in project["scenes"] if s["take"] == scene["take"]), None)
        try:
            original = _membership(active_workspace_row(cur, workspace, job.get("actor")))
            if job.get("mediaKind") != "composed" or not original.allows("edit"):
                require(original, "approve")
            self._reference(project, state)
            prompt = (self._prompt(project, current, state, job["strategy"]) if "strategy" in job else
                      blueprint.generation_prompt(project, current, state)) if current else ""
            approved = bool(current) and hashlib.sha256(prompt.encode()).hexdigest() == job["promptDigest"]
            strategy = job.get("strategy", {})
            if "firstFrame" in strategy or strategy.get("settings", {}).get("firstFrameAssetId"):
                frame_id = strategy["settings"].get("firstFrameAssetId")
                approved = approved and strategy.get("firstFrame") == frames.manifest(state, workspace, frame_id)
        except AlphaError as error:
            if error.status >= 500:
                raise
            approved = False
        if not approved:
            changed = self._transition(cur, workspace, job, "failed", outcome="unknown" if cost is None else "failed",
                                       cost=cost, reason="authorization_changed")
            if changed and output:
                output.abort(cur, "authorization_changed")
        return approved

    def _receive(self, workspace, token, project, scene, job, result):
        raw, cost = result["video"], result.get("costUsdMicro")
        pid = project["id"]
        permission = "compose" if job.get("mediaKind") == "composed" else "approve"
        profile = job.get("outputProfile") or output_profile(job.get("durationMs", scene["durationMs"]), project["aspectRatio"])
        try:
            with local_media_slot():
                evidence = validate_generated_clip(raw, profile)
        except AlphaError as error:
            if error.code != "creative_video_provider_output_unusable":
                raise
            self._record(workspace, job, "failed", outcome="unknown" if cost is None else "failed",
                         cost=cost, reason="provider_output_unusable")
            return
        output = OutputVideo(self.hosted, workspace, self.store.key(scene), raw)
        limit = self.hosted.video_uploads._ready()
        with self.access(workspace, token, permission) as (cur, state, actor, _):
            current = self.store.get(cur, workspace, pid)
            if not self._authorized_result(cur, workspace, current, scene, job, state, cost=cost):
                return
            if len(raw) > limit or evidence["sha256"] == current["analysis"].get("sha256"):
                self._transition(cur, workspace, job, "failed", outcome="unknown" if cost is None else "failed",
                                 cost=cost, reason="provider_output_unusable")
                return
            output.reserve(cur, state, actor, limit)
        try:
            info = output.stage(limit)
        except AlphaError as error:
            if error.code != "creative_video_storage_output_unusable":
                raise  # A storage outage leaves the saved operation available to poll again.
            with self.access(workspace, token, permission) as (cur, _, _, _):
                if self._transition(cur, workspace, job, "failed", outcome="unknown" if cost is None else "failed",
                                    cost=cost, reason="provider_output_unusable"):
                    output.abort(cur, "provider_output_unusable")
            return
        with self.access(workspace, token, permission) as (cur, state, actor, _):
            current = self.store.get(cur, workspace, pid)
            if not self._authorized_result(cur, workspace, current, scene, job, state, cost=cost, output=output):
                return
            if self._transition(cur, workspace, job, "completed", outcome="completed", cost=cost, assetId=output.id):
                output.commit(cur, state, actor, info, {"title": current["title"] + " · " + scene["purpose"],
                              "operation": "storyboard_composition" if job.get("mediaKind") == "composed" else "generated_scene", "projectId": current["id"], "sceneId": scene["sceneId"],
                              "revision": job["revision"], "model": job["model"], "sha256": output.sha,
                              "decodedVideo": evidence})
                audit(cur, workspace, actor, "creative_video.scene_completed", current["id"],
                      {"sceneId": scene["sceneId"], "assetId": output.id})

    def poll(self, workspace, token, pid, body):
        with self.access(workspace, token, "compose", with_member=True) as (cur, state, _, _, member):
            self._recover_claims(cur, workspace)
            project, scene, job = self._poll_inputs(cur, workspace, pid, body)
            if isinstance(token, _SavedPoll) and (pid != token.project or self.store.key(scene) != token.key or job.get("operation") != token.operation):
                raise AlphaError("The worker claim no longer matches this operation.", 409)
            if job.get("mediaKind") != "composed":
                require(member, "approve")
            if job["state"] != "pending" or not self._authorized_result(cur, workspace, project, scene, job, state):
                return self._view(cur, workspace, project, state)
            provider = self._adapter(job["model"], recovery=True)
            prompt = self._prompt(project, scene, state, job["strategy"]) if job.get("mediaKind") == "composed" else None
        try:
            if prompt is not None:
                with local_media_slot():
                    result = provider.poll(job["operation"], strategy=job["strategy"], prompt=prompt)
            elif job["provider"] == "runway":
                result = provider.poll(job["operation"], verified_unit_usd_micro=(job.get("strategy") or {}).get("verifiedProviderUnitUsdMicro"))
            else:
                result = provider.poll(job["operation"])
        except AlphaError as error:
            reasons = {"creative_video_provider_output_invalid": "provider_output_unusable",
                       "creative_video_operation_unavailable": "provider_operation_unavailable"}
            if error.code not in reasons:
                raise
            result = {"state": "failed", "reason": reasons[error.code], "costUsdMicro": None}
        units = result.get("providerCredits")
        if job["provider"] == "runway" and result["state"] in ("completed","failed","cancelled") and type(units) is int and units >= 0:
            receipt = {"provider":"runway", "unit":"provider_credit", "quantity":units,
                       "verifiedUsdMicroPerUnit":(job.get("strategy") or {}).get("verifiedProviderUnitUsdMicro"),
                       "pricingVersion":job.get("pricingVersion"), "costUsdMicro":result.get("costUsdMicro"),
                       "costSource":"provider_task_usage" if result.get("costUsdMicro") is not None else "provider_invoice_pending"}
            with self.hosted.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace,))
                consistent = self.store.remember_usage(cur, workspace, job, receipt)
                if consistent and type(receipt["costUsdMicro"]) is int:
                    saved = self.store.locked_usage_job(cur, workspace, job)
                    if saved.get("state") in ("completed","failed","cancelled") and saved.get("actualUsdMicro") is None:
                        self._transition(cur, workspace, saved, saved["state"],
                                         outcome="completed" if saved["state"] == "completed" else "failed",
                                         cost=receipt["costUsdMicro"], finishedAt=saved.get("finishedAt"))
            if not consistent:
                self._record(workspace, job, "unknown", outcome="unknown", reason="provider_usage_disputed")
                return self.get(workspace, token, project["id"])
        if result["state"] in ("failed", "cancelled"):
            cost = result.get("costUsdMicro")
            self._record(workspace, job, result["state"], reason=result.get("reason"), outcome="unknown" if cost is None else "failed", cost=cost)
        elif result["state"] == "completed":
            self._receive(workspace, token, project, scene, job, result)
        return self.get(workspace, token, project["id"])

    def worker_tick(self):
        # One bounded unit per existing cron tick. The due marker commits before network I/O.
        # Polls may race a returning user; attachment and settlement both compare the original job.
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT j.id::text,j.workspace_id::text,j.body,p.revision
                FROM public.pr_jobs j JOIN public.pr_creative_video_projects p
                ON p.workspace_id=j.workspace_id AND p.id::text=j.body->>'projectId'
                WHERE j.body->>'kind'='creative_video_scene' AND
                    ((j.body->>'state'='pending' AND j.body ? 'operation') OR
                     (j.body->>'state'='submitting' AND j.created_at < now()-interval '5 minutes'))
                AND coalesce((j.body->>'nextPollAt')::bigint,0) <= extract(epoch from now())
                ORDER BY coalesce((j.body->>'nextPollAt')::bigint,0),j.created_at,j.id
                LIMIT 1 FOR UPDATE OF j SKIP LOCKED""")
            row = cur.fetchone()
            if not row:
                return {"state":"idle"}
            ident, workspace, job, revision = row
            cur.execute("""UPDATE public.pr_jobs SET body=body || jsonb_build_object('nextPollAt',
                extract(epoch from now())::bigint + 60), revision=revision+1 WHERE id=%s AND workspace_id=%s""", (ident, workspace))
        if job["state"] == "submitting":
            if job.get("provider") == "rafii-local" and job.get("mediaKind") == "composed" and job.get("reservationId") is None:
                self._record(workspace, job, "failed", outcome="failed", cost=0, reason="storyboard_interrupted")
            else:
                self._record(workspace, job, "unknown", outcome="unknown", reason="submission_unknown")
            return {"state":"recovered_claim"}
        claim = _SavedPoll(workspace, job["projectId"], job["idempotencyKey"], job["actor"], job["operation"])
        try:
            self.poll(workspace, claim, job["projectId"], {"revision":revision,"sceneId":job["sceneId"]})
        except AlphaError as error:
            if error.status == 403 or error.code in ("account_deletion_pending","account_blocked"):
                self._record(workspace, job, "failed", outcome="unknown" if job.get("reservationId") else "failed",
                             cost=None if job.get("reservationId") else 0, reason="authorization_changed")
                return {"state":"authorization_changed"}
            return {"state":"deferred"}
        return {"state":"polled"}

    def cancel(self, workspace, token, pid, body):
        if set(body) != {"sceneId", "revision"}:
            raise AlphaError("Choose the scene generation to cancel.")
        with self.access(workspace, token, "approve") as (cur, state, _, _):
            project, scene, job = self._poll_inputs(cur, workspace, pid, body)
            if job["state"] != "pending" or job.get("cancelRequested"):
                return self._view(cur, workspace, project, state)
            provider = self._adapter(job["model"], recovery=True)
            if not job.get("cancellable") or not callable(getattr(provider, "cancel", None)):
                raise AlphaError("This model does not support cancellation. Check the existing operation.", 409)
            # Persist intent before I/O. Even a lost cancellation response must not release the hold.
            self.store.update_job(cur, workspace, self.store.key(scene), "pending",
                                  {"cancelRequested": True, "reason": "cancellation_requested"})
        provider.cancel(job["operation"])
        return self.get(workspace, token, pid)

    def review(self, workspace, token, pid, body):
        if set(body) != {"revision", "sceneId", "accepted"} or type(body["accepted"]) is not bool:
            raise AlphaError("Choose whether to accept this completed take.")
        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            project, scene, job = self._poll_inputs(cur, workspace, pid, body)
            if job["state"] != "completed" or not job.get("assetId"):
                raise AlphaError("Review the completed scene before recording a decision.", 409)
            asset(state, job["assetId"])
            if job.get("accepted") is not body["accepted"]:
                self.store.update_job(cur, workspace, self.store.key(scene), "completed", {"accepted": body["accepted"]})
                audit(cur, workspace, actor, "creative_video.take_reviewed", pid,
                      {"sceneId": scene["sceneId"], "accepted": body["accepted"]})
            return self._view(cur, workspace, project, state)

    def _render_inputs(self, cur, workspace, project, state):
        scenes = self._scenes(cur, workspace, project, state)
        if any(not s["clipId"] for s in scenes):
            raise AlphaError("Assign or generate footage for every scene before rendering.", 409)
        assets = {s["clipId"]: asset(state, s["clipId"]) for s in scenes}
        if sum(a["bytes"] for a in assets.values()) > 128 * 1024 * 1024:
            raise AlphaError("The combined source clips exceed 128 MiB. Use shorter source files.", 413)
        return scenes, assets

    def contact_sheet(self, workspace, token, pid, revision, page):
        from . import creative_video_contact_sheet as sheet

        def authorized(cur, state):
            project = self.store.get(cur, workspace, pid, revision)
            rights = project.get("rights") or {}
            if (not project.get("referenceAssetId") or rights.get("scope") != "analyze-reference-only"
                    or not rights.get("confirmedBy")):
                raise AlphaError("This project has no authorized reference to inspect.", 403)
            self._reference(project, state)
            item = asset(state, project["referenceAssetId"])
            analysis = project.get("analysis") or {}
            shots, total = sheet.windows(analysis, page)
            return item, (identity(item), (rights["scope"], rights["confirmedBy"]), analysis.get("sha256"), shots, total)

        with self.access(workspace, token, "read") as (cur, state, _, _):
            item, approved = authorized(cur, state)
        _, _, sha, shots, total = approved
        with local_media_slot():
            raw = read_video(self.hosted, workspace, item)
            if hashlib.sha256(raw).hexdigest() != sha:
                raise AlphaError("The reference no longer matches the analyzed footage.", 409)
            images = sheet.decode(raw, shots)
        with self.access(workspace, token, "read") as (cur, state, _, _):
            if authorized(cur, state)[1] != approved:
                raise AlphaError("The reference changed while preparing these frames.", 409)
        return {"page": page, "pageCount": (total + sheet.PAGE_SIZE - 1) // sheet.PAGE_SIZE,
                "totalShots": total, "frames": images}

    def frame(self, workspace, token, pid, revision, index):
        def source(cur, state):
            project = self.store.get(cur, workspace, pid, revision)
            receipt = project.get("export") or {}
            manifest = receipt.get("manifest") or {}
            if receipt.get("revision") != revision or not manifest.get("sha256"):
                raise AlphaError("Render this revision before downloading a frame.", 409)
            if not 0 <= index < manifest.get("frameCount", 0):
                raise AlphaError("Choose a frame inside this revision.")
            return asset(state, receipt["assetId"]), manifest["sha256"]

        with self.access(workspace, token, "read") as (cur, state, _, _):
            item, expected = source(cur, state)
        with local_media_slot():
            raw = read_video(self.hosted, workspace, item)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise AlphaError("The export no longer matches this saved revision.", 409)
            png = picture_frame(raw, index)
        with self.access(workspace, token, "read") as (cur, state, _, _):
            latest, sha = source(cur, state)
            if sha != expected or identity(latest) != identity(item):
                raise AlphaError("The export changed while reading this frame.", 409)
        return png

    @staticmethod
    def _live_export(state, project):
        if not project["export"]:
            return False
        try:
            asset(state, project["export"]["assetId"])
        except AlphaError as error:
            if error.status != 404:
                raise
            return False
        return True

    def render(self, workspace, token, pid, body):
        with self.access(workspace, token, "edit") as (cur, state, _, _):
            project = self.store.get(cur, workspace, pid)
            self._current(project, body)
            if self._live_export(state, project):
                return self._view(cur, workspace, project, state)
            scenes, assets = self._render_inputs(cur, workspace, project, state)
        limit = self.hosted.video_uploads._ready()
        with local_media_slot():
            clips = {key: read_video(self.hosted, workspace, item) for key, item in assets.items()}
            if any(hashlib.sha256(data).hexdigest() == project["analysis"].get("sha256") for data in clips.values()):
                raise AlphaError("The analysis reference cannot also supply footage for this composition.", 409)
            raw, manifest = render_composition(scenes, clips, aspect_ratio=project["aspectRatio"])
            del clips
            kinds = {scene["sceneId"]:scene["sourceMediaKind"] for scene in scenes}
            for rendered in manifest["scenes"]:
                rendered["sourceMediaKind"] = kinds[rendered["sceneId"]]
        scope = f"{project['id']}:render:{project['revision']}"
        previous = project["export"]
        if previous:
            scope += ":replacing:" + previous["assetId"]
        output = OutputVideo(self.hosted, workspace, scope, raw)
        def validate(cur, state):
            current = self.store.get(cur, workspace, project["id"])
            self._current(current, body)
            _, active = self._render_inputs(cur, workspace, current, state)
            if {k:identity(v) for k,v in active.items()} != {k:identity(v) for k,v in assets.items()}:
                raise AlphaError("One of the selected clips changed during rendering.", 409)
            return current
        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            current = validate(cur, state)
            if self._live_export(state, current):
                return self._view(cur, workspace, current, state)
            if current["export"] != previous:
                raise AlphaError("The saved export changed. Reload this revision.", 409)
            output.reserve(cur, state, actor, limit)
        info = output.stage(limit)
        with self.access(workspace, token, "edit") as (cur, state, actor, _):
            current = validate(cur, state)
            if not self._live_export(state, current):
                if current["export"] != previous:
                    raise AlphaError("The saved export changed. Reload this revision.", 409)
                state = output.commit(cur, state, actor, info, {"title": project["title"], "operation": "composition_render",
                                      "projectId": project["id"], "revision": project["revision"],
                                      "sourceAssetIds": list(assets), "sha256": output.sha})
                receipt = {"revision": project["revision"], "assetId": output.id, "manifest": manifest}
                if previous:
                    receipt["replacesAssetId"] = previous["assetId"]
                self.store.export(cur, workspace, project["id"], project["revision"], receipt)
                audit(cur, workspace, actor, "creative_video.rendered", project["id"], {"assetId": output.id, "revision": project["revision"]})
            return self._view(cur, workspace, self.store.get(cur, workspace, pid), state)


def handle(app, environ, start_response, hosted, token, method, parts):
    from urllib.parse import parse_qs

    service = getattr(hosted, "creative_video", None) or CreativeVideoService(hosted)
    workspace = parts[2]
    if parts[4:] == ["reference-link"] and method == "POST":
        return app._json(start_response, 200, service.reference_link(workspace, token, app._body(environ)))
    if parts[4:5] == ["projects"]:
        if len(parts) == 5 and method == "GET":
            return app._json(start_response, 200, service.list(workspace, token))
        if len(parts) == 5 and method == "POST":
            return app._json(start_response, 201, service.create(workspace, token, app._body(environ)))
        if len(parts) == 6 and method == "GET":
            value = parse_qs(environ.get("QUERY_STRING", "")).get("revision", [None])[0]
            if value is not None and (not value.isascii() or not value.isdigit() or not 0 < len(value) <= 9):
                raise AlphaError("Choose a valid revision.")
            return app._json(start_response, 200, service.get(workspace, token, parts[5], int(value) if value else None))
        if len(parts) == 7 and parts[6] == "performance" and method == "GET":
            revisions = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True).get("revision", [])
            if len(revisions) != 1 or not re.fullmatch(r"[1-9][0-9]{0,8}", revisions[0]):
                raise AlphaError("Choose the saved revision to inspect.")
            return app._json(start_response, 200, service.performance(workspace, token, parts[5], int(revisions[0])))
        if len(parts) == 7 and parts[6] == "reference-frames" and method == "GET":
            params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
            if (set(params) != {"revision", "page"} or any(len(v) != 1 for v in params.values())
                    or not re.fullmatch(r"[1-9][0-9]{0,8}", params["revision"][0])
                    or not re.fullmatch(r"0|[1-9][0-9]{0,2}", params["page"][0])):
                raise AlphaError("Choose a saved revision and reference shot page.")
            return app._json(start_response, 200, service.contact_sheet(workspace, token, parts[5],
                int(params["revision"][0]), int(params["page"][0])))
        if len(parts) == 7 and parts[6] == "frame" and method == "GET":
            params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
            if (set(params) != {"revision", "frame"} or any(len(v) != 1 for v in params.values())
                    or not re.fullmatch(r"[1-9][0-9]{0,8}", params["revision"][0])
                    or not re.fullmatch(r"0|[1-9][0-9]{0,3}", params["frame"][0])):
                raise AlphaError("Choose a saved revision and frame number.")
            revision, index = int(params["revision"][0]), int(params["frame"][0])
            png = service.frame(workspace, token, parts[5], revision, index)
            start_response("200 OK", [("Content-Type", "image/png"), ("Content-Length", str(len(png))),
                ("Cache-Control", "private, no-store"), ("X-Content-Type-Options", "nosniff"),
                ("Content-Disposition", f'attachment; filename="revision-{revision}-frame-{index}.png"')])
            return [png]
        actions = {"edit": service.edit, "variants": service.variants, "plan": service.plan, "quote": service.quote, "generate": service.generate, "poll": service.poll, "cancel": service.cancel, "review": service.review, "render": service.render}
        if len(parts) == 7 and method == "POST" and parts[6] in actions:
            return app._json(start_response, 200, actions[parts[6]](workspace, token, parts[5], app._body(environ)))
    raise AlphaError("Creative video route unavailable.", 404)

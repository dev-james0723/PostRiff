"""Capability-first scene quotes. A quote never contacts a provider or places a charge."""
import hashlib
import os
from statistics import median

from postriff_alpha.domain import AlphaError
from .creative_video_media import MAX_SCENE_MS, MIN_SCENE_MS, SIZES
from .creative_video_media_provider import ProviderError, VideoProvider
from .creative_video_health import output_decoder_ready, worker_health
from .creative_video_first_frame import ASSET_ID
from .creative_video_models import MODELS, PRICE_VERSION, RUNWAY_CREDIT_USD_MICRO, STORYBOARD, VERTEX_FAST, metered_total
from .creative_video_runway import RunwayProvider
from .creative_video_storyboard import StoryboardProvider
from .credit_meter import millicredits


LEVELS = ("draft", "balanced", "professional", "cinematic")
MODES = ("auto", "manual", "budget", "hybrid")
PROMPT_TARGETS = {
    "referenceAdherence": ("Develop an independent rhythm.", "Follow the approved shot timing and structure."),
    "creativeFreedom": ("Keep the approved staging.", "Explore original staging within the approved facts."),
    "visualFidelity": ("Use simple visual detail.", "Resolve material, lighting and surface details."),
    "characterConsistency": ("Keep casting simple.", "Maintain the authorized character details across the shot."),
    "productFidelity": ("Keep product staging simple.", "Keep every approved product feature consistent and legible."),
    "motionQuality": ("Use a simple camera move.", "Stage one continuous camera move with physically coherent motion."),
    "brandConsistency": ("Use minimal branding and retain approved facts.", "Match the approved brand palette, voice and identity."),
}
LEVEL_DIRECTION = {
    "draft": "Block the framing and action clearly.",
    "balanced": "Stage one readable action.",
    "professional": "Plan a clear focal point and maintain visual continuity.",
    "cinematic": "Plan a motivated camera move, consistent screen direction and deliberate lighting.",
}


def _option(value, choices, label):
    if not isinstance(value, str) or value not in choices:
        raise AlphaError(f"Choose a supported {label}.", 422, code="creative_video_option_invalid")
    return value


def _registry_error(message):
    return ProviderError(message, status=503, code="creative_video_provider_unavailable")


def adapter_for(model, environment=None, *, for_recovery=False):
    """Build one configured adapter. Disabled cloud routes can read their existing operations only."""
    env = os.environ if environment is None else environment
    if not isinstance(model, str) or model not in MODELS:
        raise AlphaError("Choose a registered video model.", 422)
    if not for_recovery and not output_decoder_ready():
        raise _registry_error("This video worker cannot currently decode and verify the output.")
    if model == STORYBOARD:
        return StoryboardProvider.from_environment(env)
    if env.get("VERCEL_ENV") == "preview":
        raise _registry_error("Paid generation is disabled in this Preview environment.")
    configured = env.get("RAFII_CREATIVE_VIDEO_PROVIDERS", env.get("RAFII_CREATIVE_VIDEO_PROVIDER", ""))
    providers = {v.strip() for v in configured.split(",")} if isinstance(configured, str) else set()
    provider = MODELS[model].provider
    if provider not in providers and not for_recovery:
        raise _registry_error("This provider is disabled on the video worker.")
    if model == VERTEX_FAST:
        adapter = VideoProvider.from_environment({**env, "RAFII_CREATIVE_VIDEO_PROVIDER": provider})
    else:
        enabled = env.get("RAFII_CREATIVE_VIDEO_RUNWAY_MODELS", "")
        allowed_models = {v.strip() for v in enabled.split(",")} if isinstance(enabled, str) else set()
        if model not in allowed_models and not for_recovery:
            raise _registry_error("This model has not been enabled on the Runway worker.")
        adapter = RunwayProvider.from_environment(model, env)
    account_scope = (env.get("RAFII_CREATIVE_VIDEO_PROJECT", "") if provider == "vertex-veo" else
                     hashlib.sha256(env["RAFII_CREATIVE_VIDEO_RUNWAY_KEY"].encode()).hexdigest())
    adapter.health_scope = (provider, account_scope, model)
    if not for_recovery and worker_health.on_hold(adapter.health_scope):
        raise ProviderError("Recent provider responses paused new takes temporarily. Existing tasks can still be checked.",
                            status=503, code="creative_video_provider_cooldown")
    adapter.may_submit = not for_recovery
    return adapter


def model_catalog(environment=None):
    env = os.environ if environment is None else environment
    raw_unit = env.get("RAFII_CREATIVE_VIDEO_RUNWAY_VERIFIED_UNIT_USD_MICRO")
    unit = int(raw_unit) if isinstance(raw_unit, str) and raw_unit.isascii() and raw_unit.isdigit() and len(raw_unit) <= 5 else 0
    result = []
    for model in MODELS.values():
        reason = None
        health = "worker_ready" if model.id == STORYBOARD else "configured_unmeasured"
        try:
            adapter_for(model.id, environment)
        except AlphaError as error:
            reason = str(error)
            health = "temporary_hold" if error.code == "creative_video_provider_cooldown" else "disabled"
        result.append({"id": model.id, "provider": model.provider, "label": model.label,
                       "mediaKind": model.media_kind, "available": reason is None, "reason": reason,
                       "aspectRatios": list(model.ratios), "resolutions": sorted({x[0] for x in model.rates}),
                       "audioModes": sorted({x[1] for x in model.rates}), "supportsCancel": model.supports_cancel,
                       "pricingVersion": PRICE_VERSION, "priceSource": model.price_source,
                       "verifiedProviderUnitUsdMicro": unit if model.provider == "runway" and 0 < unit <= RUNWAY_CREDIT_USD_MICRO else None,
                       "health": health})
    return result


def workspace_observations(cur, workspace):
    """Aggregate workspace outcomes by input mode and output profile without returning asset identifiers."""
    cur.execute("""SELECT body->>'model',body #>> '{strategy,resolution}',body #>> '{strategy,audio}',
                          body->>'aspectRatio',body #>> '{strategy,billedSeconds}',
                          body->>'state',body->>'reason',body->>'accepted',
                          CASE WHEN body->>'finishedAt' ~ '^[0-9]{1,12}$'
                            THEN (body->>'finishedAt')::bigint - extract(epoch FROM created_at)::bigint END,
                          body #> '{strategy,firstFrame}' IS NOT NULL
                   FROM public.pr_jobs
                   WHERE workspace_id=%s AND body->>'kind'='creative_video_scene' AND body->>'mediaKind'='generated'
                     AND body->>'state' IN ('completed','failed') AND created_at >= now()-interval '30 days'
                   ORDER BY created_at DESC LIMIT 200""", (workspace,))
    groups = {}
    for model, resolution, audio, aspect, seconds, state, reason, accepted, elapsed, first_frame in cur.fetchall():
        if (model not in MODELS or MODELS[model].media_kind != "generated" or
                not all(isinstance(s, str) and s for s in (resolution, audio, aspect, seconds))):
            continue
        # Authorization changes, cancellations, uncertain submissions and refusals aren't evidence of model quality.
        if state == "failed" and reason not in ("provider_operation_failed", "provider_output_unusable"):
            continue
        key = "|".join((resolution, audio, aspect, seconds, "image" if first_frame else "text"))
        stats = groups.setdefault(model, {}).setdefault(key, {"done": 0, "total": 0, "accepted": 0, "reviewed": 0, "times": []})
        stats["total"] += 1
        if state == "completed":
            stats["done"] += 1
            if accepted in ("true", "false"):
                stats["reviewed"] += 1
                stats["accepted"] += accepted == "true"
            # Time to observed and validated output includes polling/user revisit time. It isn't provider execution time.
            if type(elapsed) is int and 0 <= elapsed <= 7 * 86400:
                stats["times"].append(elapsed)
    result = {}
    for model, profiles in groups.items():
        result[model] = {}
        for key, stats in profiles.items():
            if stats["total"] >= 5:
                result[model][key] = {
                    "success": stats["done"] * 10_000 // stats["total"],
                    "acceptance": stats["accepted"] * 10_000 // stats["reviewed"] if stats["reviewed"] >= 5 else None,
                    "latencySeconds": round(median(stats["times"])) if len(stats["times"]) >= 5 else None,
                }
    return result


def apply_observations(models, observations):
    return [{**model, "workspaceObservations": observations.get(model["id"], {})} for model in models]


def _observations(catalog_entry, strategy):
    mode = "image" if strategy["settings"].get("firstFrameAssetId") else "text"
    key = f"{strategy['resolution']}|{strategy['audio']}|{strategy['aspectRatio']}|{strategy['billedSeconds']}|{mode}"
    return catalog_entry.get("workspaceObservations", {}).get(key, {})


def observed_latency(models, strategy):
    """The typical observed wait for this model/profile, or None when there are fewer than five samples."""
    item = next((m for m in models if m["id"] == strategy["model"]), {})
    return _observations(item, strategy).get("latencySeconds")


def _settings(value):
    keys = {"level", "mode", "model", "audio", "resolution", "maxMilliCredits", "speed", "reliability",
            "variations", "requirements", "firstFrameAssetId", "firstFrameConsent", *PROMPT_TARGETS}
    if not isinstance(value, dict) or value.keys() - keys:
        raise AlphaError("The generation settings contain an unsupported field.", 422)
    normalized = {
        "level": _option(value.get("level", "balanced"), LEVELS, "intelligence level"),
        "mode": _option(value.get("mode", "auto"), MODES, "routing mode"),
        "audio": _option(value.get("audio", "auto"), ("auto", "generated", "silent"), "audio target"),
        "speed": _option(value.get("speed", "standard"), ("standard", "fast"), "speed preference"),
        "reliability": _option(value.get("reliability", "standard"), ("standard", "strict"), "validation level"),
    }
    if "resolution" in value:
        normalized["resolution"] = _option(value["resolution"], ("720p", "1080p"), "native resolution")
    if "firstFrameAssetId" in value or "firstFrameConsent" in value:
        asset_id = value.get("firstFrameAssetId")
        if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id) or value.get("firstFrameConsent") is not True:
            raise AlphaError("Select a private Library photo and confirm your rights to use it for this take.", 422)
        normalized.update(firstFrameAssetId=asset_id, firstFrameConsent=True)
    if "model" in value or normalized["mode"] == "manual":
        if normalized["mode"] != "manual":
            raise AlphaError("A named model requires Manual mode.", 422)
        normalized["model"] = _option(value.get("model"), MODELS, "video model")
    if "maxMilliCredits" in value or normalized["mode"] == "budget":
        cap = value.get("maxMilliCredits")
        if type(cap) is not int or not 0 <= cap <= 10**12:
            raise AlphaError("Set a nonnegative maximum AI Credit budget.", 422)
        normalized["maxMilliCredits"] = cap
    if type(value.get("variations", 1)) is not int or value.get("variations", 1) != 1:
        raise AlphaError("Authorize one candidate per scene take. Each additional variation needs its own quote.", 422)
    for key in PROMPT_TARGETS.keys() & value.keys():
        normalized[key] = _option(value[key], ("low", "standard", "high"), "creative priority")
    requirements = value.get("requirements", [])
    if not isinstance(requirements, list) or len(requirements) > 12 or any(
            not isinstance(item, str) or len(item) > 40 for item in requirements):
        raise AlphaError("Invalid required capabilities.", 422)
    if requirements:
        normalized["requirements"] = sorted(set(requirements))
    return normalized


def _candidate(model, settings, duration_ms, aspect_ratio):
    level = settings["level"]
    manual = settings["mode"] == "manual"
    if manual and model.id != settings["model"]:
        return None
    if settings.get("firstFrameAssetId") and model.id != VERTEX_FAST:
        return None
    if not manual and (level == "draft") != (model.id == STORYBOARD):
        return None
    if model.id == STORYBOARD and any(settings.get(key, "standard") != "standard" for key in PROMPT_TARGETS):
        return None
    if aspect_ratio not in model.ratios:
        return None
    sizes = {r for r, _, _ in model.rates}
    budget = settings["mode"] == "budget"
    prefer_native_detail = not budget and (level == "cinematic" or level == "professional" and settings.get("visualFidelity") == "high")
    resolution = settings.get("resolution") or ("1080p" if prefer_native_detail and "1080p" in sizes else "720p")
    available_audio = [a for r, a, _ in model.rates if r == resolution]
    audio = settings["audio"]
    if audio == "auto":
        if budget and available_audio:
            if "native-audio" in settings.get("requirements", ()):
                audio = "generated"
            else:
                audio = min(available_audio, key=lambda sound: model.rates_for(resolution, sound))
        else:
            audio = "generated" if "generated" in available_audio else "silent"
    if audio not in available_audio:
        return None
    capabilities = ({"image-to-video"} if settings.get("firstFrameAssetId") else
                    {"no-cloud", "programmatic"} if model.id == STORYBOARD else {"text-to-video"})
    if audio == "generated":
        capabilities.add("native-audio")
    if not set(settings.get("requirements", ())) <= capabilities:
        return None
    profile = model.profile(duration_ms, aspect_ratio, resolution, audio)
    profile["strictQuality"] = settings["reliability"] == "strict" or level == "cinematic"
    price_lines = model.price_lines(duration_ms, resolution, audio)
    cost = metered_total(price_lines)
    return {"model": model.id, "provider": model.provider, "label": model.label, "level": level, "mode": settings["mode"],
            "durationMs": duration_ms, "aspectRatio": aspect_ratio, "pricingVersion": PRICE_VERSION,
            "estimatedUsdMicro": cost, "estimatedMilliCredits": millicredits(cost), "resolution": resolution,
            "audio": audio, "outputProfile": profile, "billedSeconds": 0 if model.id == STORYBOARD else profile["durationMs"] // 1000,
            "mediaKind": model.media_kind, "settings": settings, "supportsCancel": model.supports_cancel,
            "priceItems": [line.record() for line in price_lines]}


def _rank(candidate, settings, evidence):
    # Price is a final tie-break outside Budget mode. No price-derived quality or latency scores.
    price = candidate["estimatedUsdMicro"]
    if settings["mode"] == "budget":
        return (price, candidate["model"])
    resolution_fit = settings["level"] == "cinematic" and candidate["resolution"] == "1080p"
    sound_fit = settings["audio"] == "auto" and candidate["audio"] == "generated"
    seconds = candidate["outputProfile"]["durationMs"] if settings["speed"] == "fast" else 0
    return (-resolution_fit, *evidence, seconds, -sound_fit, price, candidate["model"])


def route_scene(settings, *, duration_ms, aspect_ratio, available_models, available_millicredits=None,
                preview_over_budget=False):
    """The caller supplies current worker enablement, project scene duration and the authoritative wallet balance."""
    settings = _settings(settings)
    if (type(duration_ms) is not int or not MIN_SCENE_MS <= duration_ms <= MAX_SCENE_MS or
            not isinstance(aspect_ratio, str) or aspect_ratio not in SIZES):
        raise AlphaError("Choose a supported scene duration and aspect ratio.", 422)
    if available_millicredits is not None and (type(available_millicredits) is not int or available_millicredits < 0):
        raise AlphaError("The available AI Credit balance could not be verified.", 409)
    available = set()
    catalog = {}
    for entry in available_models:
        if isinstance(entry, str):
            available.add(entry)
        elif isinstance(entry, dict) and entry.get("available") is True:
            available.add(entry["id"])
            catalog[entry["id"]] = entry
    candidates = []
    for model in MODELS.values():
        if model.id in available:
            candidate = _candidate(model, settings, duration_ms, aspect_ratio)
            if candidate:
                candidates.append(candidate)
    if not candidates:
        raise AlphaError("No enabled model supports this combination. Review audio, resolution and required inputs, "
                         "or choose Draft for a composed storyboard.", 422, code="creative_video_no_model")
    limits = [x for x in (settings.get("maxMilliCredits"), available_millicredits) if x is not None]
    within_budget = [c for c in candidates if not limits or c["estimatedMilliCredits"] <= min(limits)]
    if not within_budget and not preview_over_budget:
        raise AlphaError("This take exceeds the available or approved AI Credits. Try a shorter scene, "
                         "a supported lower resolution, or a Library clip.", 402, code="creative_video_budget_exceeded")
    evidence = {c["model"]: _observations(catalog.get(c["model"], {}), c) for c in within_budget}
    criteria = [("success", -1)]
    if settings["level"] in ("professional", "cinematic"):
        criteria.append(("acceptance", -1))
    if settings["speed"] == "fast":
        criteria.append(("latencySeconds", 1))
    # Unknown rates are not failures. A measurement influences a comparison only when every contender has evidence.
    comparable = [(key, sign) for key, sign in criteria if all(e.get(key) is not None for e in evidence.values())]
    def score(candidate):
        measured = [sign * evidence[candidate["model"]][key] for key, sign in comparable]
        return _rank(candidate, settings, measured)

    result = (min(within_budget, key=score) if within_budget else
              min(candidates, key=lambda candidate: (candidate["estimatedMilliCredits"], candidate["model"])))
    result["budgetExceeded"] = not within_budget
    if result["model"] == STORYBOARD:
        recommendation = "Use a silent motion card to review this scene’s timing and direction at zero provider cost."
        limits_text = ["Programmatic shot card. It does not depict the described product or person."]
    else:
        sound = "with native audio" if result["audio"] == "generated" else "without an audio track"
        recommendation = f"{result['label']} supports this {result['resolution']} shot {sound}."
        if settings["mode"] == "budget":
            recommendation += " It has the lowest quoted cost among the eligible routes."
        if settings["speed"] == "fast":
            recommendation += " Comparable observed waits guide speed selection when available, then supported take length."
        limits_text = ["Planning uses approved text and timing. Source video, identity locks and guaranteed likeness are unavailable."]
        if settings.get("firstFrameAssetId"):
            limits_text = ["Google Cloud Veo animates the selected Library photo as the first frame. Review product appearance across the take."]
        if result["resolution"] == "1080p":
            limits_text.append("The scene is generated at 1080p. The current timeline export is 720p.")
        if result["provider"] == "runway":
            limits_text.append("Powered by Runway. This scene's authorized prompt is processed by Runway.")
    result.update(recommendation=recommendation, limitations=limits_text,
                  verifiedProviderUnitUsdMicro=catalog.get(result["model"], {}).get("verifiedProviderUnitUsdMicro"))
    return result


def apply_direction(prompt, strategy):
    if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
        raise AlphaError("Enter an authorized scene direction.", 422)
    model = MODELS[strategy["model"]]
    if model.id != STORYBOARD:
        directions = [LEVEL_DIRECTION[strategy["level"]]]
        for key, (low, high) in PROMPT_TARGETS.items():
            priority = strategy["settings"].get(key)
            if priority in ("low", "high"):
                directions.append(low if priority == "low" else high)
        prompt += "\n" + " ".join(directions)
    try:
        if model.provider == "runway":
            units = len(prompt.encode("utf-16-le")) // 2
        else:
            prompt.encode("utf-8")
            units = len(prompt)
    except UnicodeError:
        raise AlphaError("Use valid Unicode in the scene direction.", 422) from None
    if units > model.max_prompt_units:
        raise AlphaError(f"The complete direction exceeds {model.label}’s {model.max_prompt_units}-unit limit. "
                         "Shorten the scene brief or select a different eligible model.", 422, code="creative_video_prompt_limit")
    return prompt


def validate_quality_observations(analysis, profile):
    """Strict technical screening on the shared decoder's observations. No semantic acceptance score."""
    if not profile.get("strictQuality"):
        return
    observations = [scene["measurements"] for scene in analysis["scenes"]]
    if not any(.015 < m["meanLuma"] < .985 for m in observations):
        raise AlphaError("Strict validation found a near-black or near-white take throughout.", 422,
                         code="creative_video_provider_output_unusable")
    if profile["hasAudio"] and not any((m.get("audioRms") or 0) > .001 for m in observations):
        raise AlphaError("Strict validation found no audible signal in the requested soundtrack.", 422,
                         code="creative_video_provider_output_unusable")

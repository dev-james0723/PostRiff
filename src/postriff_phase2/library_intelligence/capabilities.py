"""Per-capability processing truth for Library intelligence (engineering spec §4 CapabilityState, §7; T02).

Stored or playable is never collapsed into "understood". Each capability of each content version has its own row in
pr_library_capabilities, keyed by the version's 32-hex key (a normalized row id, or a legacy photo/video id from the
workspace JSON). A capability with no row is `not_requested`. A percentage appears only when a processor reported a
measurable done/total; a queued or running state without one shows no progress at all.

Processors are registered by the workstream modules that own them (B: segments/media/understanding/ocr, C: index) by
calling `register(...)` at import. `PROCESSOR_MODULES` lists the modules imported on first use so the registry is
complete in any process (HTTP or cron) without importing them eagerly here.
"""
from __future__ import annotations

import importlib
import json
import re
import uuid

from . import contracts as c
from . import policy, versions

STATES = c.CAPABILITY_STATES
ACTIVE = ("queued", "processing")
TERMINAL = ("ready", "partial", "unsupported", "failed", "cancelled", "blocked_permission", "blocked_budget")
# Capabilities that can apply to each kind before any processor is registered. A generic binary has none: it stays a
# useful stored file and is never shown as waiting for analysis.
KIND_CAPABILITIES = {
    "document": ("preview", "extract", "embed_text", "understand"),
    "image": ("preview", "extract", "visual", "embed_text", "embed_visual", "understand"),
    "audio": ("preview", "transcribe", "embed_text", "understand"),
    "video": ("preview", "transcribe", "visual", "embed_text", "embed_visual", "understand"),
    "file": (),
}
PROGRESS_UNITS = ("pages", "slides", "sheets", "seconds", "segments", "frames", "items", "bytes")
VERSION = re.compile(r"^[A-Za-z0-9_.:/\-]{1,80}$")
REQUIRED = ("capability", "version", "location", "category", "applies", "run")
PROCESSOR_MODULES = ("segments", "media", "understanding", "ocr", "index")

# capability -> [processor, ...] in registration order (the last registered version of a location is preferred).
PROCESSORS: dict[str, list[dict]] = {}
_loaded = False


def register(processor: dict) -> dict:
    """Processor = {capability, version, location, category, applies(version)->bool, estimate(job)->usd_micro|None,
    run(job)->Outcome, name?, model?}. Re-registering the same (capability, version) replaces the earlier entry."""
    if not isinstance(processor, dict):
        raise ValueError("A processor is a dict.")
    missing = [k for k in REQUIRED if k not in processor]
    if missing:
        raise ValueError(f"Processor is missing {', '.join(missing)}.")
    if processor["capability"] not in c.CAPABILITIES:
        raise ValueError("Unknown capability.")
    if not isinstance(processor["version"], str) or not VERSION.fullmatch(processor["version"]):
        raise ValueError("Use a processor version of 1-80 safe characters.")
    if processor["location"] not in c.PROCESSING_LOCATIONS or processor["category"] not in c.PROVIDER_CATEGORIES:
        raise ValueError("Use a local or cloud location and a known provider category.")
    if not callable(processor["applies"]) or not callable(processor["run"]):
        raise ValueError("applies and run must be callable.")
    if processor.get("estimate") is not None and not callable(processor["estimate"]):
        raise ValueError("estimate must be callable.")
    entry = dict(processor)
    entry.setdefault("estimate", None)
    bucket = PROCESSORS.setdefault(entry["capability"], [])
    bucket[:] = [p for p in bucket if p["version"] != entry["version"]]
    bucket.append(entry)
    return entry


def _ensure_loaded():
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in PROCESSOR_MODULES:
        try:
            importlib.import_module(f"{__package__}.{name}")
        except ImportError:
            continue  # That workstream is not in this build; its capabilities stay unavailable, honestly.
        except Exception as error:  # a broken module must not take capability status down with it
            print(json.dumps({"event": "library_intelligence.processor_import_failed", "module": name, "error": type(error).__name__}), flush=True)


def is_local(processor: dict) -> bool:
    """Private processing inside Rafii's own runtime (policy.LOCAL_DEFAULTS); everything else needs a cloud grant."""
    return (processor["location"], processor["category"]) in policy.LOCAL_DEFAULTS


def applies(processor: dict, version: dict) -> bool:
    try:
        return bool(processor["applies"](version))
    except Exception:
        return False


def processor(capability: str, version: str) -> dict | None:
    _ensure_loaded()
    return next((p for p in PROCESSORS.get(capability, []) if p["version"] == version), None)


def processors_for(version: dict) -> list[dict]:
    """Every registered processor that applies to this version, in capability order then registration order."""
    _ensure_loaded()
    return [p for cap in c.CAPABILITIES for p in PROCESSORS.get(cap, []) if applies(p, version)]


def applicable(version: dict) -> list[str]:
    registered = {p["capability"] for p in processors_for(version)}
    wanted = set(KIND_CAPABILITIES.get(version.get("kind"), ())) | registered
    return [cap for cap in c.CAPABILITIES if cap in wanted]


def _progress(value) -> dict | None:
    """Only a measured done/total is shown; anything else (a guessed percent, a bare 'running') is dropped."""
    if not isinstance(value, dict):
        return None
    done, total, unit = value.get("done"), value.get("total"), value.get("unit", "items")
    if type(done) is not int or type(total) is not int or total <= 0 or not 0 <= done <= total or unit not in PROGRESS_UNITS:
        return None
    return {"done": done, "total": total, "unit": unit}


def _receipt(value) -> dict | None:
    """Content-free provider receipt kept with the state: provider, model, latency and cost class only."""
    if not isinstance(value, dict):
        return None
    cost = value.get("cost") if isinstance(value.get("cost"), dict) else {}
    out = {"provider": str(value.get("provider") or "")[:80] or None, "model": str(value.get("model") or "")[:120] or None,
           "latencyMs": value.get("latencyMs") if type(value.get("latencyMs")) is int else None,
           "costKind": cost.get("kind") if cost.get("kind") in ("actual", "estimated", "unknown") else "unknown",
           "usdMicro": cost.get("usdMicro") if type(cost.get("usdMicro")) is int else None}
    return {k: v for k, v in out.items() if v is not None}


def set_state(cur, workspace_id, asset_key, capability, state, **fields) -> bool:
    """Upsert one capability state. Fields: progress, error_code, detail, retryable, job_id, processor_version, provider,
    job_guard (only overwrite a row owned by this job or by none) and keep (states this write must not replace).
    Returns whether the row was written."""
    c.capability_state(capability, state)
    key = c.asset_key(asset_key)
    unknown = set(fields) - {"progress", "error_code", "detail", "retryable", "job_id", "processor_version", "provider", "job_guard", "keep"}
    if unknown:
        raise ValueError(f"Unknown capability fields: {sorted(unknown)}")
    progress = _progress(fields.get("progress")) if state == "processing" else None
    error_code = str(fields["error_code"])[:80] if fields.get("error_code") else None
    detail = str(fields["detail"])[:300] if fields.get("detail") else None
    job_id = uuid.UUID(hex=c.asset_key(fields["job_id"])) if fields.get("job_id") else None
    guard = uuid.UUID(hex=c.asset_key(fields["job_guard"])) if fields.get("job_guard") else None
    version = fields.get("processor_version")
    if version is not None and (not isinstance(version, str) or not VERSION.fullmatch(version)):
        raise ValueError("Invalid processor version.")
    provider = _receipt(fields.get("provider"))
    keep = [s for s in (fields.get("keep") or ()) if s in STATES] or ["-"]  # never an empty array parameter
    cur.execute(
        "/*lij:cap.set*/ INSERT INTO public.pr_library_capabilities(workspace_id,asset_key,capability,state,progress,error_code,detail,retryable,job_id,"
        "processor_version,provider,updated_at,completed_at) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s::jsonb,now(),CASE WHEN %s THEN now() END) "
        "ON CONFLICT(workspace_id,asset_key,capability) DO UPDATE SET state=excluded.state,progress=excluded.progress,error_code=excluded.error_code,"
        "detail=excluded.detail,retryable=excluded.retryable,job_id=coalesce(excluded.job_id,pr_library_capabilities.job_id),"
        "processor_version=coalesce(excluded.processor_version,pr_library_capabilities.processor_version),provider=excluded.provider,updated_at=now(),"
        "completed_at=excluded.completed_at WHERE (%s::uuid IS NULL OR pr_library_capabilities.job_id IS NULL OR pr_library_capabilities.job_id=%s::uuid) "
        "AND pr_library_capabilities.state <> ALL(%s::text[]) RETURNING state",
        (str(workspace_id), key, capability, state, json.dumps(progress) if progress else None, error_code, detail, bool(fields.get("retryable")),
         job_id, version, json.dumps(provider) if provider else None, state in TERMINAL, guard, guard, keep))
    return cur.fetchone() is not None


def _epoch(value):
    return float(value) if value is not None else None


def states_for(ctx, version: dict) -> list[dict]:
    """Every capability applicable to this version's kind (plus any with a recorded state), in contract order."""
    key = version["versionId"]
    ctx.cur.execute("/*lij:cap.list*/ SELECT capability,state,progress,error_code,detail,retryable,replace(job_id::text,'-',''),processor_version,provider,"
                    "extract(epoch from updated_at),extract(epoch from completed_at) FROM public.pr_library_capabilities WHERE workspace_id=%s AND asset_key=%s",
                    (ctx.workspace_id, key))
    rows = {r[0]: r for r in ctx.cur.fetchall() if r[0] in c.CAPABILITIES and r[1] in STATES}
    available = {p["capability"] for p in processors_for(version)}
    wanted = set(applicable(version)) | set(rows)
    out = []
    for cap in c.CAPABILITIES:
        if cap not in wanted:
            continue
        row = rows.get(cap)
        if row is None:
            out.append(c.capability_state(cap, "not_requested", available=cap in available))
            continue
        _, state, progress, error_code, detail, retryable, job_id, processor_version, provider, updated, completed = row
        receipt = provider if isinstance(provider, dict) else None
        out.append(c.capability_state(
            cap, state, available=cap in available, progress=_progress(progress) if state == "processing" else None,
            errorCode=error_code, detail=detail, retryable=bool(retryable) if state not in ("ready", "not_requested") else None,
            jobId=job_id, processorVersion=processor_version,
            provider={k: receipt[k] for k in ("provider", "model") if receipt.get(k)} or None if receipt else None,
            updatedAt=_epoch(updated), completedAt=_epoch(completed)))
    return out


def capabilities_http(ctx, request):
    """GET .../assets/{key}/capabilities. A foreign or missing key is the same 404 as everywhere else."""
    version = versions.get(ctx, request["params"]["key"])
    return {"assetRef": versions.ref(version), "kind": version["kind"],
            "original": {"status": version["status"], "stored": version["status"] in ("ready", "unsupported", "legacy"), "legacy": version["legacy"]},
            "enrichmentEnabled": policy.enabled("enrichment"), "capabilities": states_for(ctx, version)}

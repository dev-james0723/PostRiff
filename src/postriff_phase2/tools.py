"""Versioned structured tool registry (architecture §11.2–11.4).

Every tool has a stable ID/version, JSON input/output schema, effect class, cost class,
bounds, and a release hash. Unknown IDs fail closed. External representation
(publish/reply/moderate) is never a tool. The public invoke route stays blocked until a
real isolated runner exists: a Python function inside the request process is not isolation.
"""
import hashlib
import json
from postriff_alpha.domain import AlphaError

EFFECTS = ("read", "creative_write", "workspace_mutation", "paid_generation")
FORBIDDEN_EFFECTS = ("external_representation", "destructive")
COSTS = ("none", "metered", "paid")
BOUNDS = {"maxSeconds": 45, "maxInputBytes": 60000, "maxOutputBytes": 262144, "network": "none", "files": "attached-only"}

_DEFS = [
    {"id": "source.extract", "version": "1.0.0", "effect": "read", "cost": "none", "purpose": "Split approved text into reviewable fact statements.",
     "input": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string", "maxLength": 20000}}},
     "output": {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "array"}}}},
    {"id": "brief.create", "version": "1.0.0", "effect": "creative_write", "cost": "none", "purpose": "Build a canonical brief from approved facts and the author's viewpoint.",
     "input": {"type": "object", "required": ["idea", "sourceIds"], "properties": {"idea": {"type": "string"}, "sourceIds": {"type": "array"}}},
     "output": {"type": "object", "required": ["brief"]}},
    {"id": "variants.generate", "version": "1.0.0", "effect": "creative_write", "cost": "none", "purpose": "Produce platform-native candidate variants from a context projection.",
     "input": {"type": "object", "required": ["context", "destinations"]},
     "output": {"type": "object", "required": ["variants"]}},
    {"id": "post.preflight", "version": "1.0.0", "effect": "read", "cost": "none", "purpose": "Evaluate preflight rules for a variant and destination.",
     "input": {"type": "object", "required": ["variantId"]},
     "output": {"type": "object", "required": ["issues"]}},
    {"id": "media.generate_image", "version": "1.0.0", "effect": "paid_generation", "cost": "paid", "purpose": "Request an image candidate from a qualified provider after a credits check.",
     "input": {"type": "object", "required": ["briefHash", "count"]},
     "output": {"type": "object", "required": ["candidates"]}},
    {"id": "delivery.prepare_manifest", "version": "1.0.0", "effect": "workspace_mutation", "cost": "none", "purpose": "Prepare an exact approval manifest for human review. Never executes.",
     "input": {"type": "object", "required": ["variantId", "channelId"]},
     "output": {"type": "object", "required": ["reviewId", "digest"]}},
]


def _release_hash(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


REGISTRY = {}
for _d in _DEFS:
    assert _d["effect"] in EFFECTS and _d["effect"] not in FORBIDDEN_EFFECTS and _d["cost"] in COSTS
    REGISTRY[(_d["id"], _d["version"])] = {**_d, "bounds": dict(BOUNDS), "releaseId": _release_hash(_d), "state": "released"}


def isolation_status():
    """Honest runner status. Flip only after a real sandboxed runner is qualified."""
    return {"isolated": False, "runner": "request-process", "detail": "Tools run inside the API request process on the platform runtime; no per-job sandbox, network allowlist, or resource cap is enforced by the platform.", "publicInvokeEnabled": False}


def catalog():
    return [{key: value[key] for key in ("id", "version", "effect", "cost", "purpose", "input", "output", "bounds", "releaseId", "state")} for value in REGISTRY.values()]


def resolve(tool_id, version=None):
    if not isinstance(tool_id, str):
        raise AlphaError("Unknown tool.", 404)
    matches = [v for (tid, ver), v in REGISTRY.items() if tid == tool_id and (version is None or ver == version)]
    if not matches:
        raise AlphaError("Unknown tool.", 404)  # fail closed; never guess a version
    return matches[-1]


def validate_input(definition, payload):
    schema = definition["input"]
    if not isinstance(payload, dict):
        raise AlphaError("Tool input must be an object.", 400)
    for key in schema.get("required", []):
        if key not in payload:
            raise AlphaError(f"Tool input is missing '{key}'.", 400)
    if len(json.dumps(payload).encode()) > BOUNDS["maxInputBytes"]:
        raise AlphaError("Tool input exceeds the size bound.", 413)
    return True


def invoke(tool_id, version, payload, credits_ok=None):
    """Public invoke path. Blocked until isolation is qualified; paid tools also need credits."""
    definition = resolve(tool_id, version)
    validate_input(definition, payload)
    if definition["effect"] == "paid_generation" and not credits_ok:
        raise AlphaError("Paid generation requires an approved credit reservation first.", 402)
    status = isolation_status()
    if not status["publicInvokeEnabled"]:
        raise AlphaError("Running tools isn't available yet.", 503)
    raise AlphaError("No runner is mounted.", 503)

"""Library intelligence hooks on existing workspace events (coordinator wiring for T11, R14/R15).

- Repository effect (runs inside each workspace command, after the state is saved): a newly scheduled post that carries
  Library media records `post_scheduled` usage; a created or rewritten draft triggers a quiet, debounced suggestion pass
  when suggestions are switched on.
- Publish verification wrapper: a verified post records `post_published` usage for its media.

Both run under a savepoint and never raise into the command or the publish path. Ids and enums only; no draft text is
stored here (the suggestion builder reads the draft from state itself).
"""
from __future__ import annotations

import json
import re

KEY = re.compile(r"^[0-9a-f]{32}$")
MAX_JOBS = 20
MAX_DRAFTS = 5


def _media_ids(job) -> list[str]:
    media = ((job or {}).get("manifest") or {}).get("media") or []
    return [m["id"] for m in media if isinstance(m, dict) and isinstance(m.get("id"), str) and KEY.fullmatch(m["id"])][:20]


def _channel(job) -> str | None:
    platform = ((job or {}).get("manifest") or {}).get("platform")
    return str(platform)[:60] if isinstance(platform, str) and platform else None


def _jobs(state) -> dict:
    return {j.get("id"): j for j in ((state or {}).get("phase2") or {}).get("jobs", []) if isinstance(j, dict) and j.get("id")}


def _drafts(state) -> dict:
    out = {}
    for variant in (state or {}).get("variants", []) or []:
        if isinstance(variant, dict) and isinstance(variant.get("id"), str):
            out[variant["id"]] = (variant.get("text"), variant.get("sourceIds"), variant.get("updatedAt"))
    return out


def _record(cur, workspace_id, job, event_type, path):
    from . import usage
    recorded = 0
    for media_id in _media_ids(job):
        result = usage.record_usage(cur, workspace_id, media_id, media_id, event_type, post_id=str(job["id"])[:120], channel=_channel(job),
                                    dedup_key=f"{path}:{job['id']}:{media_id}"[:300], source={"path": path})
        recorded += int(bool(result.get("recorded")))
    return recorded


def capture(cur, workspace_id, before, after, principal):
    """Repository effect signature (cur, workspace_id, before, after, principal)."""
    try:
        cur.execute("SAVEPOINT library_intelligence_effects")
    except Exception:  # noqa: BLE001 — no transaction to protect; do nothing
        return
    try:
        old_jobs, new_jobs = _jobs(before), _jobs(after)
        for job_id in [j for j in new_jobs if j not in old_jobs][:MAX_JOBS]:
            _record(cur, workspace_id, new_jobs[job_id], "post_scheduled", "schedule")
        from . import policy
        if policy.enabled("suggestions"):
            old_drafts, new_drafts = _drafts(before), _drafts(after)
            changed = [d for d, value in new_drafts.items() if old_drafts.get(d) != value][:MAX_DRAFTS]
            if changed:
                from . import suggestions
                from .jobs import system_context
                ctx = system_context(cur, workspace_id, actor=principal)
                if ctx is not None:
                    for draft_id in changed:
                        suggestions.evaluate_suggestions(ctx, {"type": "draft_changed", "draftId": draft_id})
        cur.execute("RELEASE SAVEPOINT library_intelligence_effects")
    except Exception as error:  # noqa: BLE001 — intelligence is additive; the command must still succeed
        cur.execute("ROLLBACK TO SAVEPOINT library_intelligence_effects")
        print(json.dumps({"event": "library_intelligence.effect_failed", "error": type(error).__name__}), flush=True)


def on_published(on_verified):
    """Wrap the worker's on_verified hook: the original runs first; Library usage is recorded after, never raising."""
    def wrapped(cur, workspace_id, job):
        if on_verified is not None:
            on_verified(cur, workspace_id, job)
        try:
            cur.execute("SAVEPOINT library_intelligence_published")
            _record(cur, workspace_id, job, "post_published", "publish")
            cur.execute("RELEASE SAVEPOINT library_intelligence_published")
        except Exception as error:  # noqa: BLE001
            try:
                cur.execute("ROLLBACK TO SAVEPOINT library_intelligence_published")
            except Exception:  # noqa: BLE001
                pass
            print(json.dumps({"event": "library_intelligence.publish_usage_failed", "error": type(error).__name__}), flush=True)
    return wrapped

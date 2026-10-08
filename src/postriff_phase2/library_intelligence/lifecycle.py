"""Deletion and revocation propagation across derived Library data (engineering spec §6, §12; T12).

Runs inside the caller's transaction. Each step is bounded and content-free; the receipt counts what changed so the
UI and acceptance evidence can show propagation instead of assuming it.
"""
from __future__ import annotations


def _keys_for(ctx, scope: dict) -> list[str] | None:
    """None means the whole workspace."""
    if scope["kind"] == "workspace":
        return None
    if scope["kind"] == "asset":
        ctx.cur.execute("SELECT replace(id::text,'-','') FROM public.pr_library_assets WHERE workspace_id=%s AND (replace(id::text,'-','')=%s OR replace(lineage_id::text,'-','')=%s)",
                        (ctx.workspace_id, scope["key"], scope["key"]))
        keys = [r[0] for r in ctx.cur.fetchall()]
        return keys or [scope["key"]]
    return list(scope.get("members") or [])


def propagate_revocation(ctx, grant: dict) -> dict:
    keys = _keys_for(ctx, grant["scope"])
    where, args = ("", ()) if keys is None else (" AND asset_key=ANY(%s)", (keys,))
    receipt = {"jobsCancelled": 0, "embeddingsRevoked": 0, "voiceSpansWithdrawn": 0, "packsRevoked": 0, "suggestionsSuppressed": 0}
    if grant["grantType"] == "processing" and grant.get("location") == "cloud":
        capabilities = {"asr": ("transcribe",), "vision": ("visual", "embed_visual"), "embedding": ("embed_text", "embed_visual"),
                        "llm": ("understand",), "ocr": ("extract",)}.get(grant.get("category"), ())
        if capabilities:
            ctx.cur.execute("UPDATE public.pr_library_jobs SET status='cancelled',error_category='permission',error_code='grant_revoked',lease_token=null,"
                            "finished_at=now(),updated_at=now() WHERE workspace_id=%s AND status IN ('queued','processing') AND capability=ANY(%s)" + where,
                            (ctx.workspace_id, list(capabilities), *args))
            receipt["jobsCancelled"] = ctx.cur.rowcount or 0
            ctx.cur.execute("UPDATE public.pr_library_capabilities SET state='blocked_permission',error_code='grant_revoked',retryable=false,updated_at=now() "
                            "WHERE workspace_id=%s AND state IN ('queued','processing') AND capability=ANY(%s)" + where, (ctx.workspace_id, list(capabilities), *args))
        if grant.get("category") in ("embedding", "vision"):
            modality = ["text", "visual"] if grant["category"] == "embedding" else ["visual"]
            ctx.cur.execute("UPDATE public.pr_library_embeddings SET status='revoked' WHERE workspace_id=%s AND status='active' AND modality=ANY(%s) AND model_id NOT LIKE 'local/%%'" + where,
                            (ctx.workspace_id, modality, *args))
            receipt["embeddingsRevoked"] = ctx.cur.rowcount or 0
    if grant["grantType"] == "purpose" and grant.get("purpose") == "voice":
        from . import voice
        receipt["voiceSpansWithdrawn"] = voice.withdraw_for_keys(ctx, keys)
    if grant["grantType"] == "purpose" and grant.get("purpose") in ("answer", "memory", "voice"):
        ctx.cur.execute("UPDATE public.pr_library_source_packs SET status='revoked',updated_at=now() WHERE workspace_id=%s AND status IN ('draft','attached')"
                        + ("" if keys is None else " AND (evidence_refs::text ~ ANY(%s) OR style_refs::text ~ ANY(%s))"),
                        (ctx.workspace_id,) if keys is None else (ctx.workspace_id, keys, keys))
        receipt["packsRevoked"] = ctx.cur.rowcount or 0
    ctx.cur.execute("UPDATE public.pr_library_suggestions SET state='suppressed',updated_at=now() WHERE workspace_id=%s AND state IN ('new','seen','snoozed')"
                    + ("" if keys is None else " AND candidate_refs::text ~ ANY(%s)"), (ctx.workspace_id,) if keys is None else (ctx.workspace_id, keys))
    receipt["suggestionsSuppressed"] = ctx.cur.rowcount or 0
    ctx.caches.clear()
    return receipt

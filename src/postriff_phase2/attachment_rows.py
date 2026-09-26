"""Presence rows for media on a conversation (chat-context SPEC §6.1 step 9, §9): one `pr_attachments` row per asset
and conversation, shared by the Ideas turn and Agent Runtime v2 (`_attach`, `attach_upload`). A row records only that
the asset was on the conversation ("the second image" stays stable); the per-turn role lives on the user message.
"""
from __future__ import annotations

import json


def record(cur, workspace_id, conversation_id, principal, asset, *, now):
    """Insert the presence row for `asset` unless the conversation already has one. Returns True when inserted."""
    cur.execute("SELECT 1 FROM public.pr_attachments WHERE conversation_id::text=%s AND workspace_id=%s AND kind='asset' AND ref->>'assetId'=%s",
                (conversation_id, workspace_id, asset["id"]))
    if cur.fetchone():
        return False
    cur.execute("INSERT INTO public.pr_attachments(conversation_id,workspace_id,kind,ref,created_by) VALUES(%s,%s,'asset',%s::jsonb,%s)",
                (conversation_id, workspace_id, json.dumps({"assetId": asset["id"], "hash": asset["hash"], "mime": asset.get("mime"), "addedAt": now}), principal))
    return True

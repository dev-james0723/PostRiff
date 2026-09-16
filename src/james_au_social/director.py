"""Persistent one-blocking-question intake and immutable setup snapshots."""
from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .execution import payload_hash

CHANNEL_IDS = (
    "youtube", "instagram", "facebook", "linkedin", "x", "tiktok", "threads",
    "xiaohongshu", "douyin", "wechat-channels", "bilibili", "reddit", "pinterest",
    "bluesky", "telegram", "google-business-profile", "discord", "feishu-lark",
    "weibo", "zhihu", "tencent-qq", "pixelfed", "mastodon", "snapchat",
    "whatsapp-channels", "line-official-account", "note-jp", "sharechat", "moj",
    "kakaotalk-channel", "naver-blog", "kuaishou", "dcard",
)
CATALOG_VERSION = "v14-33/1"
SLOTS = {
    "intent": "Would you like a draft, a scheduled post, or immediate publication?",
    "source": "What topic, article, video, product fact sheet or personal note should we use?",
    "content_type": "Is this news, a launch, a video announcement, or a personal reflection?",
    "truth_state": "Research must verify the current claims before drafting. Which evidence record establishes them?",
    "james_angle": "What is your own observation or point of view on this?",
    "objective": "What should the reader understand or do after seeing this?",
    "targets": "Which exact channels and destinations should receive a draft?",
    "language": "Which language and audience should each target use?",
    "derivatives": "Which verified eligible Story, Reel or Short derivatives should we prepare?",
    "template": "Choose up to three eligible template options, or no template / decide for me.",
    "media": "Which approved source assets or visual direction should we use?",
    "timing": "What local publication time and IANA timezone should be bound to approval?",
    "identity": "Confirm the account identity for this exact setup batch.",
    "channels": "Select channels from the 33-channel catalog, select all, or clear selection.",
    "setup_review": "Review the exact setup manifest, scopes, costs and human handoffs.",
    "trigger": "What should trigger this workflow and in which timezone?",
    "source_policy": "Which reviewed sources and topic exclusions should the recipe use?",
    "cadence": "What posting windows, spacing and quality rules should apply?",
    "approval_mode": "Should this recipe prepare drafts only or request approval for each campaign?",
    "cost_limit": "What cost ceiling should stop this recipe before a paid action?",
    "notification": "What review reminders and quiet hours should apply?",
}
METADATA = {"eligible_derivatives", "required_media", "assumptions", "verified_identity_ref"}


def setup_selection(email, selected):
    if not isinstance(email, str) or "@" not in email:
        raise ValueError("identity_required")
    all_selected = selected == "all"
    selected = list(CHANNEL_IDS) if all_selected else list(selected)
    if any(channel not in CHANNEL_IDS for channel in selected):
        raise ValueError("unknown_channel")
    if len(set(selected)) != len(selected):
        raise ValueError("duplicate_channel")
    snapshot = {"identity": email, "catalog_version": CATALOG_VERSION,
                "selection_mode": "select_all_current_catalog" if all_selected else "explicit",
                "resolved_channel_ids": selected,
                "excluded_channel_ids": [c for c in CHANNEL_IDS if c not in selected]}
    snapshot["selection_hash"] = payload_hash(snapshot)
    return {**snapshot, "channel_states": {c: "not_checked" for c in selected},
            "external_actions": [], "setup_manifest_approval": "pending"}


def validate_slot(slot, value):
    if slot not in set(SLOTS) | METADATA:
        raise ValueError("unsupported_slot")
    if value is None or value == "" or value == []:
        if slot not in {"derivatives", "channels"}:
            raise ValueError("empty_answer")
    if slot == "intent" and value not in {"draft", "schedule", "publish_now", "setup", "analytics", "verify"}:
        raise ValueError("invalid_intent")
    if slot == "content_type" and value not in {"news", "launch", "youtube", "reflection", "article"}:
        raise ValueError("invalid_content_type")
    if slot == "channels":
        setup_selection("validation@example.invalid", value)


class ConversationStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, mode TEXT, state TEXT, revision INTEGER, slots TEXT)")
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, conversation_id, mode, slots=None):
        if mode not in {"guided", "express", "setup", "automation_builder"}:
            raise ValueError("invalid_mode")
        slots = copy.deepcopy(slots or {})
        for k, v in slots.items():
            validate_slot(k, v)
        with self.connection() as db:
            db.execute("INSERT INTO conversations VALUES(?,?,'intake',1,?)", (conversation_id, mode, json.dumps(slots)))

    def get(self, conversation_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            raise ValueError("conversation_not_found")
        return {**dict(row), "slots": json.loads(row["slots"])}

    def next(self, conversation_id):
        item = self.get(conversation_id)
        if item["state"] in {"cancelled", "complete"}:
            return None
        if item["state"] == "identity_mismatch":
            return {"slot": "identity_mismatch", "prompt": "The observed account differs from the selected identity. Resolve the account mismatch before setup.", "answer_type": "human_handoff", "secret_prohibited": True}
        slots = item["slots"]
        if item["mode"] == "setup":
            order = ["identity", "channels", "setup_review"]
        elif item["mode"] == "automation_builder":
            order = ["trigger", "source_policy", "targets", "language", "cadence", "approval_mode", "cost_limit", "notification"]
        else:
            order = ["intent", "source", "content_type"]
            if slots.get("content_type") in {"news", "launch", "youtube"}:
                order += ["truth_state"]
            order += ["james_angle"]
            if slots.get("content_type") in {"launch", "youtube"}:
                order += ["objective"]
            order += ["targets", "language"]
            if slots.get("eligible_derivatives"):
                order += ["derivatives"]
            order += ["template"]
            if slots.get("required_media"):
                order += ["media"]
            if slots.get("intent") == "schedule":
                order += ["timing"]
        for slot in order:
            if slot not in slots:
                return {"question_id": f"{conversation_id}:{item['revision']}:{slot}",
                        "slot": slot, "prompt": SLOTS[slot], "required": True,
                        "answer_type": "research" if slot == "truth_state" else "short_text",
                        "secret_prohibited": True}
        with self.connection() as db:
            db.execute("UPDATE conversations SET state='draft_review' WHERE id=?", (conversation_id,))
        return None

    def answer(self, conversation_id, slot, value):
        current = self.next(conversation_id)
        if current is None or current["slot"] != slot:
            raise ValueError("answer_not_current")
        self.revise(conversation_id, slot, value)

    def revise(self, conversation_id, slot, value):
        validate_slot(slot, value)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not row or row["state"] == "cancelled":
                raise ValueError("conversation_not_editable")
            slots = json.loads(row["slots"])
            slots[slot] = copy.deepcopy(value)
            if slot in {"source", "content_type"}:
                slots.pop("truth_state", None)
            db.execute("UPDATE conversations SET state='intake',revision=revision+1,slots=? WHERE id=?", (json.dumps(slots), conversation_id))

    def verify_identity(self, conversation_id, observed_email):
        expected = self.get(conversation_id)["slots"].get("identity")
        with self.connection() as db:
            db.execute("UPDATE conversations SET state=? WHERE id=?", ("intake" if expected == observed_email else "identity_mismatch", conversation_id))

    def cancel(self, conversation_id):
        with self.connection() as db:
            db.execute("UPDATE conversations SET state='cancelled' WHERE id=?", (conversation_id,))

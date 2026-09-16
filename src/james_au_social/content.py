"""Local two-stage news packaging. Authored copy is supplied by the operator.

Structural gates cannot judge factual entailment, translation quality or voice;
those require source/language/human review. No generated output is publishable
until the separate approval and qualified native-format pipeline accepts it.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .director import CHANNEL_IDS
from .execution import instant, payload_hash, wire

BLOCKED = {"correction_required", "retracted", "cancelled", "expired"}


class ContentStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS stories(id TEXT, version TEXT, title TEXT, state TEXT,
                detected_at TEXT, expires_at TEXT, facts TEXT, angle TEXT, reason TEXT,
                PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS content_outputs(hash TEXT PRIMARY KEY, story TEXT,
                version TEXT, kind TEXT, body TEXT, state TEXT);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def detect(self, story_id, version, *, title, detected_at, expires_at):
        if not all(isinstance(x, str) and x.strip() for x in (story_id, version, title)):
            raise ValueError("story_identity_required")
        if instant(expires_at) <= instant(detected_at):
            raise ValueError("story_expiry_invalid")
        with self.db() as db:
            db.execute("INSERT INTO stories VALUES(?,?,?,'detected',?,?,NULL,NULL,NULL)",
                       (story_id, version, title, detected_at, expires_at))

    @staticmethod
    def _story(db, story_id, version, now=None):
        row = db.execute("SELECT * FROM stories WHERE id=? AND version=?", (story_id, version)).fetchone()
        if not row:
            raise ValueError("story_not_found")
        body = dict(row)
        for key in ("facts", "angle"):
            body[key] = json.loads(body[key]) if body[key] else None
        if now is not None:
            if body["state"] in BLOCKED:
                raise ValueError("story_" + body["state"])
            if instant(now) >= instant(body["expires_at"]):
                raise ValueError("story_expired")
            if instant(now) < instant(body["detected_at"]):
                raise ValueError("story_time_invalid")
        return body

    def get(self, story_id, version):
        with self.db() as db:
            return self._story(db, story_id, version)

    def attach_facts(self, story_id, version, pack, *, now):
        if pack.get("fact_pack_hash") != payload_hash({"claims": pack.get("claims")}):
            raise ValueError("fact_pack_hash_mismatch")
        if not pack["claims"] or any(not c.get("usable_for_draft") or c.get("status") not in {"confirmed", "corroborated", "attributed"} for c in pack["claims"]):
            raise ValueError("claim_not_usable")
        ids = [c["claim_id"] for c in pack["claims"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_claim_identity")
        with self.db() as db:
            story = self._story(db, story_id, version, now)
            if story["facts"]:
                if story["facts"] == pack:
                    return
                raise ValueError("new_story_version_required")
            db.execute("UPDATE stories SET facts=?,state='awaiting_angle' WHERE id=? AND version=?", (wire(pack), story_id, version))

    def record_angle(self, story_id, version, text, *, user_message_ref, kind, now):
        if not user_message_ref or not isinstance(text, str) or not text.strip() or kind not in {"opinion", "observation", "question"}:
            raise ValueError("explicit_user_angle_required")
        with self.db() as db:
            story = self._story(db, story_id, version, now)
            if not story["facts"]:
                raise ValueError("fact_pack_required")
            angle = {"text": text, "kind": kind, "user_message_ref": user_message_ref}
            if story["angle"] and story["angle"] != angle:
                raise ValueError("new_story_version_required")
            db.execute("UPDATE stories SET angle=?,state='angle_ready' WHERE id=? AND version=?", (wire(angle), story_id, version))

    @staticmethod
    def _ready(story):
        if not story["facts"] or not story["angle"]:
            raise ValueError("fact_pack_and_real_angle_required")

    @staticmethod
    def _sources(claims):
        return sorted({e["observation_id"] for c in claims for e in c["evidence"] if e["relation"] == "supports"})

    @staticmethod
    def _save(db, story, kind, body):
        body = {"story_id": story["id"], "story_version": story["version"],
                "fact_pack_hash": story["facts"]["fact_pack_hash"], "james_angle": story["angle"],
                "publish_authorized": False, "execution_state": "local_draft", **body}
        digest = payload_hash(body)
        db.execute("INSERT OR IGNORE INTO content_outputs VALUES(?,?,?,?,?,'current')",
                   (digest, story["id"], story["version"], kind, wire(body)))
        return {**body, "draft_hash": digest}

    def rapid(self, story_id, version, *, selected_claim_ids, unknowns, now):
        with self.db() as db:
            story = self._story(db, story_id, version, now)
            self._ready(story)
            if not 2 <= len(selected_claim_ids) <= 4 or len(set(selected_claim_ids)) != len(selected_claim_ids):
                raise ValueError("rapid_requires_two_to_four_facts")
            claims = {c["claim_id"]: c for c in story["facts"]["claims"]}
            if any(key not in claims or claims[key]["status"] != "confirmed" for key in selected_claim_ids):
                raise ValueError("rapid_requires_primary_confirmed_facts")
            selected = [claims[key] for key in selected_claim_ids]
            if not isinstance(unknowns, list) or any(not isinstance(x, str) for x in unknowns):
                raise ValueError("unknowns_required")
            result = self._save(db, story, "rapid", {"state": "rapid_draft_ready", "headline": story["title"],
                "confirmed_facts": selected, "unknowns": unknowns, "source_refs": self._sources(selected), "last_updated_at": now})
            db.execute("UPDATE stories SET state='rapid_draft_ready' WHERE id=? AND version=?", (story_id, version))
            return result

    def article(self, story_id, version, sections, *, now):
        required = {"headline", "thesis", "event_account", "practical_relevance", "james_interpretation",
                    "unknowns", "conclusion", "correction_note", "claim_ids"}
        if set(sections) != required or any(not isinstance(sections[k], str) or not sections[k].strip()
                                           for k in required - {"unknowns", "claim_ids"}):
            raise ValueError("article_sections_required")
        if not isinstance(sections["unknowns"], list) or any(not isinstance(x, str) for x in sections["unknowns"]):
            raise ValueError("article_unknowns_required")
        with self.db() as db:
            story = self._story(db, story_id, version, now)
            self._ready(story)
            claims = {c["claim_id"]: c for c in story["facts"]["claims"]}
            if not sections["claim_ids"] or len(set(sections["claim_ids"])) != len(sections["claim_ids"]) or any(c not in claims for c in sections["claim_ids"]):
                raise ValueError("article_claim_binding_invalid")
            selected = [claims[c] for c in sections["claim_ids"]]
            result = self._save(db, story, "article", {"state": "full_content_pack_ready", "sections": sections,
                "qualifications": {c["claim_id"]: c["qualification"] for c in selected if c["qualification"]},
                "source_refs": self._sources(selected), "last_updated_at": now, "editorial_review": "required"})
            db.execute("UPDATE stories SET state='full_content_pack_ready' WHERE id=? AND version=?", (story_id, version))
            return result

    def adapt(self, story_id, version, target, *, authored_copy, qualification_bindings, template_selection, now):
        required = {"channel", "native_format_id", "language", "account_ref", "destination_ref"}
        if set(target) != required or any(not isinstance(v, str) or not v.strip() for v in target.values()):
            raise ValueError("exact_target_required")
        if target["channel"] not in CHANNEL_IDS or not target["native_format_id"].startswith(target["channel"] + "."):
            raise ValueError("native_target_mismatch")
        if not isinstance(authored_copy, str) or not authored_copy.strip():
            raise ValueError("platform_authored_copy_required")
        if template_selection is not None and not {"template_id", "template_version", "template_hash", "template_selection_id"} <= template_selection.keys():
            raise ValueError("exact_template_binding_required")
        with self.db() as db:
            story = self._story(db, story_id, version, now)
            self._ready(story)
            if story["state"] not in {"rapid_draft_ready", "full_content_pack_ready"}:
                raise ValueError("source_content_required")
            # This checks preservation of declared qualification spans, not
            # their translation quality or the semantic truth of supplied copy.
            needed = {c["claim_id"] for c in story["facts"]["claims"] if c["qualification"]}
            if set(qualification_bindings) != needed or any(not isinstance(v, str) or not v.strip() or v not in authored_copy for v in qualification_bindings.values()):
                raise ValueError("qualification_preservation_required")
            return self._save(db, story, "channel_draft", {"target": target, "caption_or_copy": authored_copy,
                "qualification_bindings": qualification_bindings, "template_selection": template_selection,
                "source_refs": self._sources(story["facts"]["claims"]), "route": "draft_only", "route_driver": "none",
                "approval": "pending_user", "platform_constraints_checked": False, "last_updated_at": now})

    def invalidate(self, story_id, version, *, reason, now):
        instant(now)
        if reason not in {"source_corrected", "source_retracted", "user_cancelled"}:
            raise ValueError("invalidation_reason_required")
        state = {"source_corrected": "correction_required", "source_retracted": "retracted", "user_cancelled": "cancelled"}[reason]
        with self.db() as db:
            self._story(db, story_id, version)
            db.execute("UPDATE stories SET state=?,reason=? WHERE id=? AND version=?", (state, reason, story_id, version))
            db.execute("UPDATE content_outputs SET state='invalidated' WHERE story=? AND version=?", (story_id, version))

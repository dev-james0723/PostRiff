"""Persistent, zero-side-effect first-run onboarding for the social suite."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .director import CATALOG_VERSION, CHANNEL_IDS, setup_selection
from .execution import payload_hash
from .setup_wizard import prepare_setup


DEFAULT_EMAIL = "jamesaucreates@gmail.com"
AUTOMATION_CHOICES = {
    "schedule_after_approval",
    "publish_after_approval",
    "drafts_and_reminders",
    "not_now",
}
OPERATION_CHOICES = {"full_publish", "draft_upload", "inventory_only"}


def _question(slot: str, prompt: str, **details: object) -> dict[str, object]:
    return {
        "slot": slot,
        "prompt": prompt,
        "required": True,
        "secret_prohibited": True,
        **details,
    }


class FirstRunOnboardingStore:
    """Keep first-run answers durable without connecting or mutating providers."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS onboarding_sessions(
                    id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    answers TEXT NOT NULL
                )
                """
            )
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

    def start(self, session_id: str) -> dict[str, object]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id_required")
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO onboarding_sessions VALUES(?,1,'{}')",
                (session_id,),
            )
        return self.status(session_id)

    def _get(self, session_id: str) -> dict[str, object]:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM onboarding_sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise ValueError("onboarding_session_not_found")
        return {
            "id": row["id"],
            "revision": row["revision"],
            "answers": json.loads(row["answers"]),
        }

    def answer(self, session_id: str, slot: str, value: object) -> dict[str, object]:
        current = self.status(session_id)
        questions = current.get("questions", [])
        if len(questions) != 1 or questions[0]["slot"] != slot:
            raise ValueError("answer_not_current")
        answers = copy.deepcopy(self._get(session_id)["answers"])
        if slot == "identity":
            prepare_setup(value, [], identity_confirmed=True)
            answers[slot] = value
        elif slot == "channels":
            snapshot = setup_selection(str(answers["identity"]), value)
            snapshot.update(
                {
                    "selection_scope": "setup_assessment_only",
                    "account_creation_authorized": False,
                    "oauth_authorized": False,
                    "publication_authorized": False,
                }
            )
            answers[slot] = value
            answers["channel_snapshot"] = snapshot
        elif slot == "channel_snapshot_confirmation":
            if not isinstance(value, bool):
                raise ValueError("boolean_confirmation_required")
            if value is False:
                answers.pop("channels", None)
                answers.pop("channel_snapshot", None)
                answers.pop(slot, None)
            else:
                answers[slot] = True
        elif slot == "automation":
            if value not in AUTOMATION_CHOICES:
                raise ValueError("invalid_automation_choice")
            answers[slot] = value
        elif slot == "operations":
            if value not in OPERATION_CHOICES:
                raise ValueError("invalid_operation_choice")
            answers[slot] = value
        else:
            raise ValueError("unsupported_onboarding_slot")
        with self.connection() as db:
            db.execute(
                "UPDATE onboarding_sessions SET revision=revision+1, answers=? WHERE id=?",
                (json.dumps(answers, sort_keys=True), session_id),
            )
        return self.status(session_id)

    def status(self, session_id: str) -> dict[str, object]:
        record = self._get(session_id)
        answers = record["answers"]
        base: dict[str, object] = {
            "session_id": session_id,
            "revision": record["revision"],
            "catalog_version": CATALOG_VERSION,
            "external_actions": [],
        }
        if "identity" not in answers:
            base.update(
                {
                    "state": "awaiting_answer",
                    "questions": [
                        _question(
                            "identity",
                            "Confirm the Google account/email for this exact setup batch.",
                            recommended_value=DEFAULT_EMAIL,
                            alternatives=[
                                "another_google_account",
                                "existing_or_platform_native_account",
                            ],
                            confirmation_scope="batch_only_no_account_or_oauth_authority",
                        )
                    ],
                }
            )
            return base
        if "channels" not in answers:
            base.update(
                {
                    "state": "awaiting_answer",
                    "questions": [
                        _question(
                            "channels",
                            "Select channels to assess/connect, select all 33, or clear the selection.",
                            answer_type="channel_multi_select",
                            channel_ids=list(CHANNEL_IDS),
                            actions=["select_all_33", "clear_all", "continue_selected"],
                        )
                    ],
                }
            )
            return base
        snapshot = copy.deepcopy(answers["channel_snapshot"])
        if "channel_snapshot_confirmation" not in answers:
            base.update(
                {
                    "state": "awaiting_answer",
                    "questions": [
                        _question(
                            "channel_snapshot_confirmation",
                            "Confirm this immutable channel snapshot for setup assessment only.",
                            answer_type="boolean",
                        )
                    ],
                    "channel_snapshot": snapshot,
                }
            )
            return base
        if "automation" not in answers:
            base.update(
                {
                    "state": "awaiting_answer",
                    "questions": [
                        _question(
                            "automation",
                            "Choose a Codex automation preference or Not now.",
                            answer_type="single_select",
                            choices=sorted(AUTOMATION_CHOICES),
                            consequence="preference_or_candidate_only_no_job_created",
                        )
                    ],
                    "channel_snapshot": snapshot,
                }
            )
            return base
        if "operations" not in answers:
            base.update(
                {
                    "state": "awaiting_answer",
                    "questions": [
                        _question(
                            "operations",
                            "Choose full publish capability, draft/upload only, or inventory only.",
                            answer_type="single_select",
                            choices=sorted(OPERATION_CHOICES),
                        )
                    ],
                    "channel_snapshot": snapshot,
                }
            )
            return base

        selected = snapshot["resolved_channel_ids"]
        setup_assessment = prepare_setup(
            answers["identity"], selected, identity_confirmed=True
        )
        assessment_body = {
            "identity": answers["identity"],
            "channel_snapshot_hash": snapshot["selection_hash"],
            "resolved_channel_ids": selected,
            "automation_choice": answers["automation"],
            "requested_operation_level": answers["operations"],
            "setup_assessment": setup_assessment,
        }
        base.update(
            {
                "state": "assessment_ready",
                "questions": [],
                "channel_snapshot": snapshot,
                "assessment_hash": payload_hash(assessment_body),
                "setup_assessment": setup_assessment,
                "setup_manifest_approved": False,
                "automation_state": (
                    "not_now"
                    if answers["automation"] == "not_now"
                    else "candidate_recipe_required"
                ),
                "automation_choice": answers["automation"],
                "automation_objects_created": [],
                "next_action": "inventory_selected_channels_read_only",
                "not_done": [
                    "no provider inventory executed",
                    "no exact setup manifest approved",
                    "no account created or connected",
                    "no OAuth consent submitted",
                    "no automation created",
                    "no test publish approved or executed",
                ],
            }
        )
        return base

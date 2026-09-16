"""Persistent, owner-triggered editorial generation; no publication authority.

The provider is a constrained text generator, not an authenticated Studio client.
Only the service can apply validated copy, and only on a separate owner request.
"""
from __future__ import annotations

import json
import re
import threading
import uuid

from .studio import DRAFT_DEFAULTS, ID_PATTERN, StudioError, _hash, _integer, _json, _now, _text, _timestamp

MAX_SOURCE_CHARS = 40000
MAX_TEMPLATE_CHARS = 32000
MAX_INPUT_BYTES = 192 * 1024
MAX_CANDIDATE_BYTES = 256 * 1024
SHUTDOWN_GRACE_SECONDS = 25
CONTENT_TYPES = {"article", "reflection", "news", "launch", "youtube"}
ACTIVE_STATES = {"queued", "running"}
RUN_STATES = ACTIVE_STATES | {"needs_review", "failed", "cancelled", "interrupted", "applied"}
CAUTION = "Source material is user-supplied and has not been independently verified. Review factual claims, attribution and personal viewpoints before using this candidate."
USAGE_NOTICE = "Generate sends only this reviewed input and bound editorial instructions to Codex using your existing account. It consumes model usage. Output remains an unverified local candidate; it does not approve, schedule or publish anything."
QUESTIONS = {
    "source": "Paste the source text or your own notes. A URL alone cannot be researched by this text-only bridge.",
    "angle": "What is your own angle? You can explicitly choose a neutral summary without a personal opinion.",
    "objective": "What should the reader understand or take away from this post?",
}
PROGRESS = {"queued": "Waiting to start this requested generation", "preparing": "Preparing the reviewed input",
            "generating": "Codex is preparing an editorial candidate", "validating": "Checking the candidate structure and channel scope"}
CONVERSATION_KEYS = {"id", "revision", "draftId", "draftRevision", "contentType", "state", "question", "snapshot", "objective", "createdAt", "updatedAt"}
RUN_KEYS = {"id", "conversationId", "draftId", "draftRevision", "inputHash", "requestId", "state", "progress",
            "createdAt", "updatedAt", "startedAt", "finishedAt", "skillBindings", "result", "resultHash", "error", "usage", "appliedDraftRevision"}
SAFE_FAILURES = {"generation_timeout", "codex_timeout", "output_size_limit", "codex_output_limit", "invalid_candidate",
                 "generation_failed", "codex_failed", "codex_unavailable", "codex_login_required", "codex_policy_unverified",
                 "generation_cancelled", "unsupported_codex_version", "invalid_model_output", "codex_protocol_error",
                 "invalid_agent_protocol", "agent_tool_request_blocked", "invalid_agent_output", "agent_request_failed",
                 "agent_result_missing", "agent_not_ready", "agent_policy_changed", "agent_input_too_large", "agent_cancelled",
                 "agent_timeout", "agent_diagnostic_limit", "agent_output_limit", "agent_process_failed",
                 "agent_plan_status_unhandled", "agent_patch_request_blocked", "agent_mcp_request_blocked", "agent_web_request_blocked",
                 "agent_usage_unavailable", "agent_authentication_failed", "agent_model_unavailable", "agent_schema_rejected", "agent_connection_failed"}
SAFE_FAILURE_MESSAGES = {
    "agent_usage_unavailable": "Codex reported a usage or rate limit. Check your Codex allowance before requesting a new run.",
    "agent_authentication_failed": "Codex rejected authentication. Check sign-in outside Studio; never paste credentials here.",
    "agent_model_unavailable": "The qualified model is unavailable to this Codex account. No alternate model was silently selected.",
    "agent_schema_rejected": "Codex rejected the required response schema. No candidate was applied.",
    "agent_connection_failed": "The Codex connection failed. No draft was changed and Studio will not automatically rerun this job.",
    "agent_plan_status_unhandled": "Codex returned a planning-status item not yet supported by this bridge. No draft was changed.",
    "agent_patch_request_blocked": "Codex requested a file operation; this content-only run was stopped. No draft was changed.",
    "agent_mcp_request_blocked": "Codex requested an external tool; this content-only run was stopped. No draft was changed.",
    "agent_web_request_blocked": "Codex requested web access; this content-only run was stopped. No draft was changed.",
    "agent_tool_request_blocked": "The content-only transport attempted an unsupported tool operation and was stopped. No candidate was applied.",
    "agent_policy_changed": "The bound editorial instructions changed. Review a fresh input before requesting generation again.",
    "agent_input_too_large": "The supplied input exceeded the bounded generation limit. Shorten the source or template before trying again.",
    "agent_not_ready": "The qualified Codex transport is unavailable. Check local readiness before making a new request.",
    "agent_timeout": "Generation reached its time limit. No draft was changed and this request will not retry automatically.",
    "agent_cancelled": "Generation was cancelled. No draft was changed and late output will not be applied.",
    "agent_request_failed": "Codex did not complete the request. Check your Codex login and usage before making a new request.",
    "agent_output_limit": "The generation exceeded its output limit. No candidate was applied; shorten the request before trying again.",
    "agent_diagnostic_limit": "The generation exceeded its diagnostic limit and was stopped. No candidate was applied.",
}


def _digest(value):
    return _hash(_json(value).encode("utf-8"))


def _uuid(value, field="requestId"):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise StudioError("invalid_" + field, f"{field} must be a canonical UUID.", 422) from None
    return value


def _id(value, field):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise StudioError("invalid_" + field, "Choose a saved local record with a valid identifier.", 422)
    return value


def _sha(value, field="hash"):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise StudioError("invalid_" + field, status=422)
    return value


def _bindings(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise StudioError("invalid_skill_bindings", status=422)
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "sha256"}:
            raise StudioError("invalid_skill_bindings", status=422)
        _text(item["name"], "skill_name", 200, True)
        sha = item["sha256"]
        if isinstance(sha, str):
            sha = sha.removeprefix("sha256:")
        _sha(sha)
        result.append({"name": item["name"], "sha256": sha})
    if len({item["name"] for item in result}) != len(result):
        raise StudioError("duplicate_skill_binding", status=422)
    return sorted(result, key=lambda item: item["name"])


def _has_source(value):
    return bool(re.sub(r"https?://\S+", "", value, flags=re.IGNORECASE).strip(" \t\r\n<>[]()\"'.,;:!?"))


def _question(conversation):
    snapshot = conversation["snapshot"]
    slot = ("source" if not _has_source(snapshot["source"]) else
            "angle" if not snapshot["angle"].strip() else "objective" if not conversation["objective"].strip() else None)
    return {"slot": slot, "prompt": QUESTIONS[slot]} if slot else None


def validate_candidate(value, channels):
    if not isinstance(value, dict) or set(value) != {"canonicalBrief", "variants", "warnings"}:
        raise StudioError("invalid_candidate", "The candidate contains unsupported fields.", 422)
    _text(value["canonicalBrief"], "canonicalBrief", 8000, True)
    variants, warnings = value["variants"], value["warnings"]
    if not isinstance(variants, list) or len(variants) != len(channels):
        raise StudioError("invalid_candidate", "The candidate must match every selected channel exactly.", 422)
    found = []
    for item in variants:
        if not isinstance(item, dict) or set(item) != {"channelId", "copy", "notes"}:
            raise StudioError("invalid_candidate", status=422)
        _text(item["channelId"], "channelId", 100, True)
        _text(item["copy"], "copy", 24000, True)
        _text(item["notes"], "notes", 2000)
        found.append(item["channelId"])
    if len(set(found)) != len(found) or set(found) != set(channels):
        raise StudioError("invalid_candidate", "A candidate cannot add, omit or duplicate channel destinations.", 422)
    if not isinstance(warnings, list) or len(warnings) > (21 if CAUTION in warnings else 20):
        raise StudioError("invalid_candidate", status=422)
    for warning in warnings:
        _text(warning, "warning", 1000, True)
    result = json.loads(_json(value))
    if CAUTION not in result["warnings"]:
        result["warnings"].append(CAUTION)
    if len(_json(result).encode()) > MAX_CANDIDATE_BYTES:
        raise StudioError("invalid_candidate", "The candidate exceeds its size limit.", 422)
    return result


def _usage(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"inputTokens", "outputTokens"}:
        raise StudioError("invalid_candidate", "Usage metadata was malformed.", 422)
    if any(type(item) is not int or not 0 <= item <= 1_000_000_000 for item in value.values()):
        raise StudioError("invalid_candidate", status=422)
    return dict(value)


def _put_run(db, run):
    db.execute("UPDATE studio_agent_runs SET data=? WHERE id=?", (_json(run), run["id"]))


def recover_agent_records(db):
    count = 0
    for row in db.execute("SELECT data FROM studio_agent_runs").fetchall():
        run = json.loads(row[0])
        if run["state"] in ACTIVE_STATES:
            run.update(state="interrupted", progress="Previous generation was interrupted; a new owner request is required.",
                       updatedAt=_now(), finishedAt=_now(), error={"code": "service_interrupted", "message": "Generation was interrupted. No automatic retry or draft change occurred."})
            _put_run(db, run)
            count += 1
    return count


class AgentService:
    def __init__(self, store, provider):
        self.store = store
        self.provider = provider
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.worker = None
        self.active_id = None
        self.closed = False
        self.recover_interrupted()

    def status(self):
        try:
            raw = self.provider.status()
            authentication = raw.get("authentication")
            if authentication not in {"ready", "login_required", "unavailable"}:
                authentication = "unavailable"
            version = _text(raw.get("version", ""), "version", 100)
            reason = _text(raw.get("reason", ""), "reason", 1000)
            limits = raw.get("limits", {})
            if set(limits) != {"timeoutSeconds", "maxOutputBytes"} or any(type(v) is not int or v < 1 for v in limits.values()):
                raise ValueError()
            return {"available": raw.get("available") is True and authentication == "ready" and not self.closed,
                    "transport": "codex_cli", "authentication": authentication, "version": version, "reason": reason,
                    "limits": dict(limits), "publishing": False}
        except Exception:
            return {"available": False, "transport": "codex_cli", "authentication": "unavailable", "version": "",
                    "reason": "The qualified Codex text transport is unavailable.",
                    "limits": {"timeoutSeconds": 180, "maxOutputBytes": MAX_CANDIDATE_BYTES}, "publishing": False}

    def recover_interrupted(self):
        with self.store.connection(write=True) as db:
            return recover_agent_records(db)

    def _conversation(self, db, conversation_id):
        _id(conversation_id, "conversationId")
        row = db.execute("SELECT data FROM studio_agent_conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise StudioError("conversation_not_found", "This guided conversation was not found.", 404)
        return json.loads(row[0])

    def _save_conversation(self, db, conversation):
        args = (conversation["id"], conversation["revision"], _json(conversation))
        db.execute("INSERT INTO studio_agent_conversation_versions VALUES (?,?,?)", args)
        db.execute("INSERT INTO studio_agent_conversations VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,data=excluded.data", args)

    def _check_draft(self, db, conversation):
        draft = self.store._draft(db, conversation["draftId"])
        if draft["archived"] or draft["revision"] != conversation["draftRevision"]:
            raise StudioError("stale_conversation", "The draft changed. Start a fresh guided conversation; previous answers remain saved.", 409)
        return draft

    def create_conversation(self, draft_id, expected_draft_revision, content_type):
        _id(draft_id, "draftId")
        _integer(expected_draft_revision, "expectedDraftRevision")
        if not isinstance(content_type, str) or content_type not in CONTENT_TYPES:
            raise StudioError("invalid_content_type", status=422)
        with self.store.connection(write=True) as db:
            draft = self.store._draft(db, draft_id)
            if draft["revision"] != expected_draft_revision or draft["archived"]:
                raise StudioError("draft_revision_conflict", "Save or reload a non-archived draft before starting a conversation.", 409)
            if not draft["channels"] or any(not draft["languages"].get(c, "").strip() or not draft["formats"].get(c, "").strip() for c in draft["channels"]):
                raise StudioError("native_choices_required", "Select at least one channel and save a language and native format for each selected channel.", 422)
            _text(draft["source"], "source", MAX_SOURCE_CHARS)
            _text(draft["angle"], "angle", 6000)
            now = _now()
            conversation = {"id": uuid.uuid4().hex, "revision": 1, "draftId": draft_id, "draftRevision": draft["revision"],
                            "contentType": content_type, "state": "awaiting_answer", "question": None,
                            "snapshot": {key: draft[key] for key in DRAFT_DEFAULTS}, "objective": "", "createdAt": now, "updatedAt": now}
            conversation["question"] = _question(conversation)
            self._save_conversation(db, conversation)
            self.store._activity(db, "agent_conversation_created", conversation["id"], "Guided local conversation started; no model request")
        return conversation

    def get_conversation(self, conversation_id):
        with self.store.connection() as db:
            return self._conversation(db, conversation_id)

    def list_conversations(self, draft_id):
        with self.store.connection() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_agent_conversations")]
        return sorted((row for row in values if row["draftId"] == draft_id), key=lambda row: row["createdAt"], reverse=True)

    def answer(self, conversation_id, expected_revision, slot, value):
        _integer(expected_revision, "expectedRevision")
        if not isinstance(slot, str) or slot not in QUESTIONS:
            raise StudioError("invalid_answer_slot", status=422)
        _text(value, slot, {"source": MAX_SOURCE_CHARS, "angle": 6000, "objective": 2000}[slot], True)
        if slot == "source" and not _has_source(value):
            raise StudioError("source_text_required", "Paste the source text; this bridge does not retrieve URLs.", 422)
        with self.store.connection(write=True) as db:
            conversation = self._conversation(db, conversation_id)
            self._check_draft(db, conversation)
            if conversation["revision"] != expected_revision:
                raise StudioError("conversation_revision_conflict", "This conversation changed. Reload its current question.", 409)
            if not conversation["question"] or conversation["question"]["slot"] != slot:
                raise StudioError("answer_out_of_order", "Answer only the current question.", 409)
            if slot == "objective":
                conversation["objective"] = value
            else:
                conversation["snapshot"][slot] = value
            conversation.update(revision=expected_revision + 1, updatedAt=_now())
            conversation["question"] = _question(conversation)
            conversation["state"] = "awaiting_answer" if conversation["question"] else "ready"
            self._save_conversation(db, conversation)
        return conversation

    def _review(self, db, conversation, bindings):
        self._check_draft(db, conversation)
        if conversation["state"] != "ready":
            raise StudioError("conversation_not_ready", "Complete the current guided question before reviewing generation.", 409)
        draft = json.loads(_json(conversation["snapshot"]))
        for key in ("copies", "languages", "formats"):
            draft[key] = {channel: draft[key].get(channel, "") for channel in draft["channels"]}
        _text(draft["source"], "source", MAX_SOURCE_CHARS, True)
        _text(draft["angle"], "angle", 6000, True)
        template = None
        if draft["templateId"]:
            row = db.execute("SELECT data FROM studio_templates WHERE id=? AND version=?", (draft["templateId"], draft["templateVersion"])).fetchone()
            if not row:
                raise StudioError("template_version_missing", status=409)
            template = json.loads(row[0])
            _text(template["body"], "template_body", MAX_TEMPLATE_CHARS, True)
        input = {"draftId": conversation["draftId"], "draftRevision": conversation["draftRevision"], "draft": draft,
                 "contentType": conversation["contentType"], "objective": conversation["objective"], "template": template}
        if len(_json(input).encode()) > MAX_INPUT_BYTES:
            raise StudioError("generation_input_limit", "The selected text exceeds the generation input limit. Shorten it before reviewing.", 413)
        input_hash = _digest({"input": input, "skillBindings": bindings, "conversationId": conversation["id"], "conversationRevision": conversation["revision"]})
        return {"conversation": conversation, "inputHash": input_hash, "input": input, "skillBindings": bindings, "usageNotice": USAGE_NOTICE}

    def review(self, conversation_id):
        bindings = _bindings(self.provider.bindings())
        with self.store.connection() as db:
            return self._review(db, self._conversation(db, conversation_id), bindings)

    def _run(self, db, run_id):
        _id(run_id, "runId")
        row = db.execute("SELECT data FROM studio_agent_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise StudioError("run_not_found", "This generation request was not found.", 404)
        return json.loads(row[0])

    def get_run(self, run_id):
        with self.store.connection() as db:
            return self._run(db, run_id)

    def list_runs(self, draft_id):
        with self.store.connection() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_agent_runs")]
        return sorted((row for row in values if row["draftId"] == draft_id), key=lambda row: row["createdAt"], reverse=True)

    def start_run(self, conversation_id, expected_revision, input_hash, request_id, consent):
        _integer(expected_revision, "expectedRevision")
        _uuid(request_id)
        _sha(input_hash, "inputHash")
        if consent is not True:
            raise StudioError("model_usage_consent_required", "Review this exact input and confirm model usage before generating.", 403)
        request_hash = _digest({"conversationId": conversation_id, "expectedRevision": expected_revision, "inputHash": input_hash, "requestId": request_id, "consent": True})
        with self.lock:
            with self.store.connection() as db:
                existing = db.execute("SELECT request_hash,data FROM studio_agent_runs WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing[0] != request_hash:
                    raise StudioError("generation_idempotency_conflict", "This request ID is already bound to different reviewed input.", 409)
                return json.loads(existing[1])
            if self.closed or self.worker and self.worker.is_alive():
                raise StudioError("generation_busy", "A generation is still running or stopping. Wait before starting another.", 409)
            if not self.status()["available"]:
                raise StudioError("codex_unavailable", "The qualified Codex text transport is not ready. No model request was made.", 409)
            bindings = _bindings(self.provider.bindings())
            with self.store.connection(write=True) as db:
                conversation = self._conversation(db, conversation_id)
                if conversation["revision"] != expected_revision:
                    raise StudioError("conversation_revision_conflict", status=409)
                review = self._review(db, conversation, bindings)
                if review["inputHash"] != input_hash:
                    raise StudioError("generation_input_changed", "The reviewed input or instructions changed. Review again before generating.", 409)
                if any(json.loads(row[0])["state"] in ACTIVE_STATES for row in db.execute("SELECT data FROM studio_agent_runs")):
                    raise StudioError("generation_busy", status=409)
                now = _now()
                run = {"id": uuid.uuid4().hex, "conversationId": conversation_id, "draftId": conversation["draftId"],
                       "draftRevision": conversation["draftRevision"], "inputHash": input_hash, "requestId": request_id,
                       "state": "queued", "progress": PROGRESS["queued"], "createdAt": now, "updatedAt": now,
                       "startedAt": None, "finishedAt": None, "skillBindings": bindings, "result": None,
                       "resultHash": None, "error": None, "usage": None, "appliedDraftRevision": None}
                db.execute("INSERT INTO studio_agent_runs VALUES (?,?,?,?,?,?)",
                           (run["id"], request_id, request_hash, _json(review["input"]), None, _json(run)))
                self.store._activity(db, "agent_generation_requested", run["id"], "Owner requested generation of the reviewed input")
            self.cancel_event = threading.Event()
            self.active_id = run["id"]
            self.worker = threading.Thread(target=self._generate, args=(run["id"], self.cancel_event), daemon=True, name="studio-editorial-generation")
            self.worker.start()
            return run

    def _progress(self, run_id, stage):
        if not isinstance(stage, str) or stage not in PROGRESS:
            return  # Never retain raw model events or arbitrary diagnostic text.
        with self.store.connection(write=True) as db:
            run = self._run(db, run_id)
            if run["state"] in ACTIVE_STATES:
                run.update(progress=PROGRESS[stage], updatedAt=_now())
                _put_run(db, run)

    def _generate(self, run_id, cancellation):
        try:
            with self.store.connection(write=True) as db:
                run = self._run(db, run_id)
                if cancellation.is_set() or run["state"] != "queued":
                    return
                input = json.loads(db.execute("SELECT input_json FROM studio_agent_runs WHERE id=?", (run_id,)).fetchone()[0])
                run.update(state="running", startedAt=_now(), updatedAt=_now(), progress=PROGRESS["preparing"])
                _put_run(db, run)
            generated = self.provider.generate(input, run["skillBindings"], lambda stage: self._progress(run_id, stage), cancellation.is_set)
            if cancellation.is_set():
                return
            if not isinstance(generated, dict) or set(generated) != {"candidate", "usage"}:
                raise StudioError("invalid_candidate")
            self._progress(run_id, "validating")
            result = validate_candidate(generated["candidate"], input["draft"]["channels"])
            usage = _usage(generated["usage"])
            with self.store.connection(write=True) as db:
                run = self._run(db, run_id)
                if cancellation.is_set() or run["state"] not in ACTIVE_STATES:
                    return
                run.update(state="needs_review", result=result, resultHash=_digest(result), usage=usage,
                           progress="Candidate ready for your review; the draft has not changed.", finishedAt=_now(), updatedAt=_now())
                _put_run(db, run)
                self.store._activity(db, "agent_candidate_ready", run_id, "Unverified editorial candidate ready for owner review")
        except Exception as exc:
            # The provider's static error code is enough; never persist its text.
            code = exc.code if isinstance(exc, StudioError) and exc.code in SAFE_FAILURES else "generation_failed"
            try:
                with self.store.connection(write=True) as db:
                    run = self._run(db, run_id)
                    if not cancellation.is_set() and run["state"] in ACTIVE_STATES:
                        run.update(state="failed", error={"code": code, "message": SAFE_FAILURE_MESSAGES.get(code, "Generation did not complete safely. No draft was changed; a new request requires your action.")},
                                   progress="Generation failed; your saved draft remains unchanged.", finishedAt=_now(), updatedAt=_now())
                        _put_run(db, run)
            except Exception:
                pass  # Restart recovery retains the durable unfinished state.

    def cancel(self, run_id):
        with self.lock:
            if run_id == self.active_id:
                self.cancel_event.set()
            with self.store.connection(write=True) as db:
                run = self._run(db, run_id)
                if run["state"] in ACTIVE_STATES:
                    run.update(state="cancelled", updatedAt=_now(), finishedAt=_now(), progress="Cancellation requested. Late output will be ignored.")
                    _put_run(db, run)
                    self.store._activity(db, "agent_generation_cancelled", run_id, "Generation cancelled; no candidate applied")
                return run

    def apply(self, run_id, expected_draft_revision, result_hash, channels):
        _integer(expected_draft_revision, "expectedDraftRevision")
        _sha(result_hash, "resultHash")
        if not isinstance(channels, list) or not channels or any(not isinstance(c, str) for c in channels) or len(channels) != len(set(channels)):
            raise StudioError("invalid_candidate_selection", status=422)
        request = {"expectedDraftRevision": expected_draft_revision, "resultHash": result_hash, "channels": sorted(channels)}
        with self.store.connection(write=True) as db:
            run = self._run(db, run_id)
            row = db.execute("SELECT input_json,apply_json FROM studio_agent_runs WHERE id=?", (run_id,)).fetchone()
            if row[1]:
                applied = json.loads(row[1])
                if applied["request"] != request:
                    raise StudioError("candidate_already_applied", "This candidate was already applied using a different selection.", 409)
                return {"run": run, "draft": applied["draft"]}
            if run["state"] != "needs_review" or run["resultHash"] != result_hash:
                raise StudioError("candidate_not_applicable", "Only this exact review-ready candidate can be applied.", 409)
            draft = self.store._draft(db, run["draftId"])
            if draft["archived"] or draft["revision"] != expected_draft_revision or draft["revision"] != run["draftRevision"]:
                raise StudioError("candidate_draft_stale", "The draft changed after generation. Start again from its current revision.", 409)
            input = json.loads(row[0])
            if not set(channels).issubset(input["draft"]["channels"]):
                raise StudioError("invalid_candidate_selection", "Only the reviewed channels may receive this candidate.", 422)
            candidate = validate_candidate(run["result"], input["draft"]["channels"])
            copies = dict(draft["copies"])
            copies.update({item["channelId"]: item["copy"] for item in candidate["variants"] if item["channelId"] in channels})
            validated = self.store._validate_draft({"copies": copies, "source": input["draft"]["source"], "angle": input["draft"]["angle"]}, db, draft)
            draft.update(validated)
            draft.update(revision=draft["revision"] + 1, updatedAt=_now())
            self.store._save(db, draft)
            run.update(state="applied", appliedDraftRevision=draft["revision"], updatedAt=_now(), progress="Selected copy applied to a local draft; nothing was published.")
            _put_run(db, run)
            db.execute("UPDATE studio_agent_runs SET apply_json=? WHERE id=?", (_json({"request": request, "draft": draft}), run_id))
            self.store._activity(db, "agent_candidate_applied", run_id, "Owner applied selected candidate copy to a local draft")
            return {"run": run, "draft": draft}

    def shutdown(self):
        with self.lock:
            self.closed = True
            self.cancel_event.set()
            with self.store.connection(write=True) as db:
                recover_agent_records(db)
            worker = self.worker
        if worker and worker is not threading.current_thread():
            # The qualified provider can spend up to 16 seconds in bounded
            # readiness checks, then up to 3 seconds reaping its tracked process.
            # Wait for that cleanup instead of abandoning a daemon subprocess.
            worker.join(timeout=SHUTDOWN_GRACE_SECONDS)


def validate_agent_records(store, db):
    """Known-schema restore validation; never initializes or calls a provider."""
    conversations = {}
    versions = {}
    for table in ("studio_agent_conversations", "studio_agent_conversation_versions"):
        for row in db.execute(f"SELECT id,revision,data FROM {table}"):
            item = json.loads(row[2])
            if (not isinstance(item, dict) or set(item) != CONVERSATION_KEYS or item["id"] != row[0]
                    or not ID_PATTERN.fullmatch(item["id"]) or item["revision"] != row[1] or item["contentType"] not in CONTENT_TYPES):
                raise StudioError("invalid_backup_conversation")
            _integer(item["revision"], "revision")
            _integer(item["draftRevision"], "draftRevision")
            _timestamp(item["createdAt"], "createdAt")
            _timestamp(item["updatedAt"], "updatedAt")
            if item["createdAt"] > item["updatedAt"]:
                raise StudioError("invalid_backup_agent_timestamp")
            _text(item["objective"], "objective", 2000)
            if not isinstance(item["snapshot"], dict) or set(item["snapshot"]) != set(DRAFT_DEFAULTS) or store._validate_draft(item["snapshot"], db) != item["snapshot"]:
                raise StudioError("invalid_backup_conversation_snapshot")
            _text(item["snapshot"]["source"], "source", MAX_SOURCE_CHARS)
            _text(item["snapshot"]["angle"], "angle", 6000)
            original = db.execute("SELECT data FROM studio_draft_versions WHERE id=? AND revision=?", (item["draftId"], item["draftRevision"])).fetchone()
            if not original:
                raise StudioError("backup_conversation_draft_missing")
            original = json.loads(original[0])
            snapshot = item["snapshot"]
            if (original["archived"] or not snapshot["channels"]
                    or any(not snapshot["languages"].get(c, "").strip() or not snapshot["formats"].get(c, "").strip() for c in snapshot["channels"])
                    or any(snapshot[key] != original[key] for key in DRAFT_DEFAULTS if key not in {"source", "angle"})):
                raise StudioError("backup_conversation_snapshot_mismatch")
            if item["revision"] == 1 and (item["objective"] != "" or any(snapshot[key] != original[key] for key in DRAFT_DEFAULTS)):
                raise StudioError("backup_initial_conversation_mismatch")
            if item["question"] != _question(item) or item["state"] != ("awaiting_answer" if item["question"] else "ready"):
                raise StudioError("invalid_backup_conversation_state")
            if table == "studio_agent_conversations":
                conversations[item["id"]] = item
            else:
                versions.setdefault(item["id"], []).append(item)
    if set(versions) != set(conversations):
        raise StudioError("backup_conversation_history_mismatch")
    for conversation_id, history in versions.items():
        history.sort(key=lambda item: item["revision"])
        if history[-1] != conversations[conversation_id] or any(item["revision"] != index for index, item in enumerate(history, 1)):
            raise StudioError("backup_conversation_history_mismatch")
        for prior, current in zip(history, history[1:]):
            question = prior["question"]
            if not question:
                raise StudioError("backup_conversation_changed_after_ready")
            slot = question["slot"]
            expected = json.loads(_json(prior))
            if slot == "objective":
                expected["objective"] = current["objective"]
            else:
                expected["snapshot"][slot] = current["snapshot"][slot]
            answer = current["objective"] if slot == "objective" else current["snapshot"][slot]
            if not answer.strip() or slot == "source" and not _has_source(answer):
                raise StudioError("backup_conversation_invalid_answer")
            expected.update(revision=current["revision"], updatedAt=current["updatedAt"], state=current["state"], question=current["question"])
            if expected != current or prior["updatedAt"] > current["updatedAt"]:
                raise StudioError("backup_conversation_answer_history_mismatch")
    active_count = 0
    for row in db.execute("SELECT id,request_id,request_hash,input_json,apply_json,data FROM studio_agent_runs"):
        run, input = json.loads(row[5]), json.loads(row[3])
        if not isinstance(run, dict) or set(run) != RUN_KEYS or run["id"] != row[0] or not ID_PATTERN.fullmatch(run["id"]) or run["state"] not in RUN_STATES:
            raise StudioError("invalid_backup_agent_run")
        _uuid(run["requestId"])
        _integer(run["draftRevision"], "draftRevision")
        if run["requestId"] != row[1] or run["conversationId"] not in conversations:
            raise StudioError("invalid_backup_agent_run")
        conversation = conversations[run["conversationId"]]
        bindings = _bindings(run["skillBindings"])
        if bindings != run["skillBindings"] or conversation["state"] != "ready":
            raise StudioError("invalid_backup_agent_bindings")
        if (not isinstance(input, dict) or set(input) != {"draftId", "draftRevision", "draft", "contentType", "objective", "template"}
                or run["draftId"] != conversation["draftId"] or run["draftRevision"] != conversation["draftRevision"]
                or input["draftId"] != run["draftId"] or input["draftRevision"] != run["draftRevision"]
                or input["contentType"] != conversation["contentType"] or input["objective"] != conversation["objective"]):
            raise StudioError("invalid_backup_agent_input")
        selected = json.loads(_json(conversation["snapshot"]))
        for key in ("copies", "languages", "formats"):
            selected[key] = {channel: selected[key].get(channel, "") for channel in selected["channels"]}
        if input["draft"] != selected or len(_json(input).encode()) > MAX_INPUT_BYTES:
            raise StudioError("invalid_backup_agent_input")
        template = None
        if selected["templateId"]:
            template = json.loads(db.execute("SELECT data FROM studio_templates WHERE id=? AND version=?", (selected["templateId"], selected["templateVersion"])).fetchone()[0])
        if input["template"] != template:
            raise StudioError("invalid_backup_agent_template")
        if template:
            _text(template["body"], "template_body", MAX_TEMPLATE_CHARS, True)
        expected_hash = _digest({"input": input, "skillBindings": bindings, "conversationId": conversation["id"], "conversationRevision": conversation["revision"]})
        request_hash = _digest({"conversationId": conversation["id"], "expectedRevision": conversation["revision"], "inputHash": expected_hash, "requestId": run["requestId"], "consent": True})
        if run["inputHash"] != expected_hash or row[2] != request_hash:
            raise StudioError("backup_agent_hash_mismatch")
        for key in ("createdAt", "updatedAt"):
            _timestamp(run[key], key)
        for key in ("startedAt", "finishedAt"):
            if run[key] is not None:
                _timestamp(run[key], key)
                if not run["createdAt"] <= run[key] <= run["updatedAt"]:
                    raise StudioError("invalid_backup_agent_timestamp")
        if (run["createdAt"] > run["updatedAt"] or run["startedAt"] and run["finishedAt"] and run["startedAt"] > run["finishedAt"]
                or run["state"] in ACTIVE_STATES and run["finishedAt"] is not None
                or run["state"] not in ACTIVE_STATES and run["finishedAt"] is None
                or run["state"] == "queued" and run["startedAt"] is not None
                or run["state"] in {"running", "needs_review", "applied"} and run["startedAt"] is None):
            raise StudioError("invalid_backup_agent_state_timestamps")
        active_count += run["state"] in ACTIVE_STATES
        if active_count > 1:
            raise StudioError("backup_multiple_active_generations")
        _text(run["progress"], "progress", 1000)
        _usage(run["usage"])
        if run["error"] is not None:
            if not isinstance(run["error"], dict) or set(run["error"]) != {"code", "message"}:
                raise StudioError("invalid_backup_agent_error")
            for key in ("code", "message"):
                _text(run["error"][key], key, 1000)
        if (run["state"] == "failed" and (run["error"] is None or run["error"]["code"] not in SAFE_FAILURES)
                or run["state"] == "interrupted" and (run["error"] is None or run["error"]["code"] != "service_interrupted")
                or run["state"] not in {"failed", "interrupted"} and run["error"] is not None
                or run["state"] not in {"needs_review", "applied"} and run["usage"] is not None):
            raise StudioError("invalid_backup_agent_error_state")
        if run["state"] in {"needs_review", "applied"}:
            result = validate_candidate(run["result"], selected["channels"])
            if result != run["result"] or run["resultHash"] != _digest(result):
                raise StudioError("backup_candidate_hash_mismatch")
        elif run["result"] is not None or run["resultHash"] is not None:
            raise StudioError("invalid_backup_agent_result")
        if run["state"] == "applied":
            applied = json.loads(row[4]) if row[4] else None
            if not isinstance(applied, dict) or set(applied) != {"request", "draft"} or run["appliedDraftRevision"] != run["draftRevision"] + 1:
                raise StudioError("invalid_backup_candidate_application")
            request = applied["request"]
            if not isinstance(request, dict) or set(request) != {"expectedDraftRevision", "resultHash", "channels"}:
                raise StudioError("invalid_backup_candidate_application")
            if (request["expectedDraftRevision"] != run["draftRevision"] or request["resultHash"] != run["resultHash"]
                    or not isinstance(request["channels"], list) or not request["channels"]
                    or not set(request["channels"]).issubset(selected["channels"]) or len(request["channels"]) != len(set(request["channels"]))):
                raise StudioError("invalid_backup_candidate_application")
            saved = db.execute("SELECT data FROM studio_draft_versions WHERE id=? AND revision=?", (run["draftId"], run["appliedDraftRevision"])).fetchone()
            if not saved or json.loads(saved[0]) != applied["draft"]:
                raise StudioError("backup_applied_revision_mismatch")
            original = json.loads(db.execute("SELECT data FROM studio_draft_versions WHERE id=? AND revision=?", (run["draftId"], run["draftRevision"])).fetchone()[0])
            expected = json.loads(_json(original))
            expected["copies"].update({item["channelId"]: item["copy"] for item in run["result"]["variants"] if item["channelId"] in request["channels"]})
            expected.update(source=selected["source"], angle=selected["angle"], revision=run["appliedDraftRevision"], updatedAt=applied["draft"]["updatedAt"])
            if expected != applied["draft"] or request["channels"] != sorted(request["channels"]):
                raise StudioError("backup_application_scope_mismatch")
        elif row[4] is not None or run["appliedDraftRevision"] is not None:
            raise StudioError("invalid_backup_candidate_application")

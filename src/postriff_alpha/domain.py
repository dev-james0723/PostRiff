"""Versioned, workspace-scoped local persistence and reviewed profile commands."""
import copy
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from .generation import FixtureAdapter, SAMPLE_TEXT, SAMPLE_FACTS, PLATFORMS, LANGUAGES, routes
from .templates import catalog, instances, validate_overrides
from . import learning, profiles, visuals

SCHEMA_VERSION = 1
MODES = ("personal", "niche", "business", "hybrid")
FAILURES = ("timeout", "cancelled", "malformed", "quota", "missing", "unauthenticated", "unsupported")


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


class AlphaError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def clean(value, limit=10000):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise AlphaError("Use plain text within the displayed size limit.")
    return value.strip()


def initial_state(workspace_id, sample=False):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "workspace": {"id": workspace_id, "name": "Sample agency" if sample else "My agency", "sample": sample, "visibility": "private-local", "createdAt": now()},
        "session": {"id": uid(), "step": 0, "answers": {}, "answerRecords": [], "completed": False},
        "brandHub": {"id": uid(), "purpose": "", "audience": "", "subject": "", "mode": "", "layers": [], "speaker": ""},
        "speaker": {"id": uid(), "label": "Author", "revisions": [], "activeRevision": None, "provisional": None},
        "sources": [], "brief": {"id": uid(), "revision": 1, "idea": "", "sourceIds": []},
        "variants": [], "preferences": [], "runs": [], "runtime": {"selected": None, "routes": routes()},
        "skillInstances": instances(), "savedAt": None, "importProposal": None,
        "research": {"phase0": "incomplete", "customerValidation": False, "pendingParticipants": ["P02", "P03", "P04", "P05"]},
        "profileSetup": profiles.defaults(),
        "learning": learning.initial(migrated_at=now()),
    }


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.samples = {}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise RuntimeError("Unsupported alpha data version; preserve this store and use the matching application version.")
            db.execute("CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL)")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, sample=False):
        workspace_id, token = uid(), secrets.token_urlsafe(32)
        state = initial_state(workspace_id, sample)
        if sample:
            self._apply(state, "mode", {"mode": "niche"})
            self._apply(state, "context", {"purpose": "Explore community learning", "audience": "Curious beginners", "subject": "Fictional seed swap"})
            self._apply(state, "source", {"kind": "sample"})
            source = state["sources"][0]
            self._apply(state, "approve_source", {"sourceId": source["id"], "factIds": [f["id"] for f in source["facts"]]})
            self._apply(state, "profile_propose", {"writing": "", "tone": "warm"})
            self._apply(state, "profile_decide", {"decision": "approve"})
            self._apply(state, "runtime", {"selected": FixtureAdapter.id})
            self._generate(state, {"platform": "LinkedIn", "language": "English"}, False)
            self._generate(state, {"platform": "Instagram", "language": "繁體中文"}, False)
            self._apply(state, "save", {})
            state.update({"account": None, "membership": None, "device": None, "trial": None, "socialConnections": []})
            self.samples[workspace_id] = {"secret_hash": hashlib.sha256(token.encode()).hexdigest(), "state": state, "revision": 1}
            return {"workspaceId": workspace_id, "token": token, "revision": 1, "state": copy.deepcopy(state)}
        with self.connect() as db:
            db.execute("INSERT INTO workspaces VALUES (?,?,?,?)", (workspace_id, hashlib.sha256(token.encode()).hexdigest(), 1, json.dumps(state)))
        return {"workspaceId": workspace_id, "token": token, "revision": 1, "state": state}

    def _row(self, db, workspace_id, token):
        row = db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        expected = row["secret_hash"] if row else "0" * 64
        supplied = hashlib.sha256(token.encode()).hexdigest() if isinstance(token, str) else "invalid"
        allowed = hmac.compare_digest(expected, supplied)
        if not allowed and row and db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alpha_devices'").fetchone():
            allowed = bool(db.execute("SELECT d.id FROM alpha_devices d JOIN alpha_memberships m ON m.workspace_id=d.workspace_id AND m.user_id=d.user_id WHERE d.workspace_id=? AND d.credential_hash=? AND d.status='active' AND m.status='active'", (workspace_id, supplied)).fetchone())
        if not allowed or not row:
            raise AlphaError("This workspace is not available with this local access key.", 403)
        return row

    def get(self, workspace_id, token):
        if workspace_id in self.samples:
            sample = self.samples[workspace_id]
            if not hmac.compare_digest(sample["secret_hash"], hashlib.sha256(token.encode()).hexdigest()):
                raise AlphaError("This sample is not available with this access key.", 403)
            return {"state": copy.deepcopy(sample["state"]), "revision": sample["revision"]}
        with self.connect() as db:
            row = self._row(db, workspace_id, token)
            state = json.loads(row["state"])
            profiles.ensure(state)
            return self._present(state, row["revision"])

    def _present(self, state, revision):
        shown = copy.deepcopy(state)
        visuals.ensure(shown)
        shown["profileVisuals"] = visuals.projection(shown)
        return {"state": shown, "revision": revision}

    def mutate(self, workspace_id, token, expected_revision, action, payload):
        if workspace_id in self.samples:
            self.get(workspace_id, token)
            raise AlphaError("This fictional sample is read-only and temporary. Create a local preview account before adding personal answers, imports or edits.", 403)
        if not isinstance(payload, dict):
            raise AlphaError("Expected a structured action.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, workspace_id, token)
            if type(expected_revision) is not int or expected_revision != row["revision"]:
                raise AlphaError("This idea changed in another tab. Reload the saved version; your unsent text is kept on this device.", 409)
            state = json.loads(row["state"])
            if state.get("workspace", {}).get("sample"):
                raise AlphaError("This fictional sample is read-only. Create a local preview account before adding personal content.", 403)
            self._apply(state, action, payload)
            revision = row["revision"] + 1
            db.execute("UPDATE workspaces SET state=?, revision=? WHERE id=?", (json.dumps(state), revision, workspace_id))
            return self._present(state, revision)

    def _answer(self, state, key, value):
        state["session"]["answers"][key] = value
        state["session"]["answerRecords"].append({"id": uid(), "key": key, "value": value, "confirmedAt": now()})

    def _source(self, state, source_id):
        source = next((s for s in state["sources"] if s["id"] == source_id), None)
        if not source:
            raise AlphaError("Choose a source in this workspace.", 404)
        return source

    def _variant(self, state, variant_id):
        variant = next((v for v in state["variants"] if v["id"] == variant_id), None)
        if not variant:
            raise AlphaError("Choose a variant in this workspace.", 404)
        return variant

    def _voice(self, state, profile, reason):
        revision = len(state["speaker"]["revisions"]) + 1
        record = {"revision": revision, "profile": copy.deepcopy(profile), "approvedAt": now(), "reason": reason}
        state["speaker"]["revisions"].append(record)
        state["speaker"]["activeRevision"] = revision
        for instance in state["skillInstances"]:
            instance["profileRevision"] = revision
        return revision

    def _profile(self, state):
        return next((r["profile"] for r in state["speaker"]["revisions"] if r["revision"] == state["speaker"]["activeRevision"]), None)

    def _mark_stale(self, state):
        for variant in state["variants"]:
            variant["needsReview"] = True
            variant["proposedUpdate"] = None
        state["savedAt"] = None

    def _apply(self, s, action, p):
        if not isinstance(action, str):
            raise AlphaError("Choose a supported local action.")
        learning.ensure(s, now())
        if action.startswith("you_"):
            try:
                visuals.apply(self, s, action, p)
                return
            except ValueError as e:
                raise AlphaError(str(e)) from e
        if action.startswith("profile_"):
            try:
                if profiles.apply(self, s, action, p):
                    return
            except ValueError as e:
                raise AlphaError(str(e)) from e
        if action == "step":
            step = p.get("step")
            if type(step) is not int or not 0 <= step <= 6:
                raise AlphaError("Choose a valid onboarding step.")
            if step >= 4 and not s["speaker"]["activeRevision"]:
                raise AlphaError("Review your provisional voice before continuing.")
            if step == 6 and len(s["variants"]) < 2:
                raise AlphaError("Create a second variant before finishing.")
            s["session"]["step"] = step
        elif action == "mode":
            mode = p.get("mode")
            if mode not in MODES:
                raise AlphaError("Choose one of the four starting points.")
            self._answer(s, "mode", mode)
            s["brandHub"]["mode"] = mode
            s["session"]["step"] = 1
        elif action == "context":
            mode = s["brandHub"]["mode"]
            if mode not in MODES:
                raise AlphaError("Choose a starting point first.")
            fields = {k: clean(p.get(k, ""), 1500) for k in ("purpose", "audience", "subject", "speaker")}
            if not fields["purpose"] or not fields["audience"]:
                raise AlphaError("Add your purpose and the people you hope to help.")
            if mode in ("niche", "business", "hybrid") and not fields["subject"]:
                raise AlphaError("Add the subject or business this agency should draw from.")
            layers = p.get("layers", [])
            if not isinstance(layers, list) or any(v not in ("voice", "niche", "business") for v in layers):
                raise AlphaError("Choose valid building blocks.")
            if mode == "hybrid" and (len(set(layers)) < 2 or not fields["speaker"]):
                raise AlphaError("Choose at least two building blocks and who speaks in the first post.")
            if mode != "hybrid":
                fields["speaker"] = "The business" if mode == "business" else "The author"
                layers = [mode]
            for key, value in {**fields, "layers": layers}.items():
                self._answer(s, key, value)
                s["brandHub"][key] = value
            s["speaker"]["label"] = fields["speaker"]
            s["session"]["step"] = 2
        elif action == "idea":
            idea = clean(p.get("idea", ""), 3000)
            if not idea:
                raise AlphaError("Add an idea to explore. A single sentence is enough.")
            if idea != s["brief"]["idea"]:
                s["brief"]["idea"] = idea
                s["brief"].pop("ideaSourceId", None)
                s["brief"]["revision"] += 1
                self._mark_stale(s)
            self._answer(s, "idea", idea)
        elif action == "source":
            kind = p.get("kind", "text")
            if kind not in ("idea", "text", "link", "document", "sample"):
                raise AlphaError("Choose a supported source type.")
            body, title = clean(p.get("text", ""), 20000), clean(p.get("title", "Source note"), 200)
            if kind == "sample":
                body, title = SAMPLE_TEXT, "Fictional community seed swap"
            if kind == "document" and (not title.lower().endswith((".txt", ".md"))):
                raise AlphaError("This alpha reads UTF-8 .txt and .md files, up to 20 KB. Export other documents as text first.")
            if kind == "document" and len(body.encode("utf-8")) > 20000:
                raise AlphaError("Source documents must be at most 20 KB of UTF-8 text.")
            if not body:
                raise AlphaError("Add source text before importing.")
            if kind == "link" and not re.match(r"^https?://[^\s]+$", body):
                raise AlphaError("Use an http or https link. It will be saved as an unverified reference.")
            fingerprint = hashlib.sha256((kind + body).encode()).hexdigest()
            if any(x.get("fingerprint") == fingerprint and x["active"] for x in s["sources"]):
                raise AlphaError("That source is already here. Review its facts below.")
            source_id = uid()
            chunks = [en for en, _ in SAMPLE_FACTS] if kind == "sample" else [line.strip() for line in re.split(r"\n+", body) if line.strip()]
            if kind in ("link", "idea"):
                chunks = []
            facts = [{"id": uid(), "text": text, "approved": False, "sourceId": source_id, "locator": f"paragraph {i + 1}", "fixture": kind == "sample"} for i, text in enumerate(chunks[:30])]
            s["sources"].append({"id": source_id, "kind": kind, "title": title, "text": body, "fingerprint": fingerprint, "visibility": "private-local", "active": True, "facts": facts, "createdAt": now(), "unknowns": ["Link contents were not fetched."] if kind == "link" else ["Only selected source statements are approved; missing details stay unknown."]})
            s["brief"]["sourceIds"].append(source_id)
            if not s["brief"]["idea"]:
                s["brief"]["idea"] = "Share the seed swap as a learning opportunity" if kind == "sample" else (body[:500] if kind == "idea" else title)
                s["brief"]["ideaSourceId"] = source_id
            s["brief"]["revision"] += 1
            self._mark_stale(s)
        elif action == "approve_source":
            source = self._source(s, p.get("sourceId"))
            if not source["active"]:
                raise AlphaError("This source was withdrawn.")
            selected = p.get("factIds", [])
            valid = {f["id"] for f in source["facts"]}
            if not isinstance(selected, list) or any(x not in valid for x in selected):
                raise AlphaError("Select facts from this source only.")
            for f in source["facts"]:
                f["approved"] = f["id"] in selected
            source["reviewedAt"] = now()
            s["brief"]["revision"] += 1
            self._mark_stale(s)
        elif action == "retract_source":
            source = self._source(s, p.get("sourceId"))
            source.update({"active": False, "text": "", "facts": [], "title": "Withdrawn source", "fingerprint": None, "withdrawnAt": now()})
            s["brief"]["sourceIds"] = [i for i in s["brief"]["sourceIds"] if i != source["id"]]
            if s["brief"].get("ideaSourceId") == source["id"]:
                s["brief"]["idea"] = "A new idea to develop"
                s["brief"].pop("ideaSourceId", None)
            # Prior text remains in local revision history only; export is blocked until affected drafts regenerate.
            for v in s["variants"]:
                if source["id"] in v["sourceIds"]:
                    v["blockedByRetraction"] = True
            s["brief"]["revision"] += 1
            self._mark_stale(s)
        elif action == "source_done":
            if not s["brief"]["idea"]:
                raise AlphaError("Add an idea or source first.")
            if s["brandHub"]["mode"] == "business" and not any(f["approved"] for x in s["sources"] if x["active"] for f in x["facts"]):
                raise AlphaError("For a business post, approve at least one source fact. Missing business details remain unknown.")
            s["session"]["step"] = 4 if s.get("profileSetup", {}).get("approved") else 3
        elif action == "profile_propose":
            sample = clean(p.get("writing", ""), 6000)
            tone = p.get("tone", "warm")
            if tone not in ("warm", "direct", "reflective"):
                raise AlphaError("Choose a supported starting tone.")
            observations = ["A " + tone + " starting tone (chosen by you).", "Use concrete language; preserve source attribution."]
            if sample:
                observations.append("A writing example is available for your own reference. No model has analyzed it.")
            s["speaker"]["provisional"] = {"tone": tone, "writingExample": sample, "observations": observations, "unknowns": ["Personal history, qualifications and results are unknown.", "Voice fit has not been tested with a model."], "preferences": []}
            self._answer(s, "writing", sample)
        elif action == "profile_decide":
            decision = p.get("decision")
            profile = s["speaker"]["provisional"]
            if decision == "reject":
                s["speaker"]["provisional"] = None
                s["speaker"]["activeRevision"] = None
                self._mark_stale(s)
            elif decision == "approve" and profile:
                profile = copy.deepcopy(profile)
                note = clean(p.get("note", ""), 1500)
                if note:
                    profile["observations"] = [note]
                self._voice(s, profile, "Explicit provisional-profile approval")
                s["speaker"]["provisional"] = None
                s["session"]["step"] = 4
                self._mark_stale(s)
            else:
                raise AlphaError("Review a provisional profile before approving it.")
        elif action == "runtime":
            selected = p.get("selected")
            if selected != FixtureAdapter.id:
                raise AlphaError("That real-agent route is not qualified in this alpha. Choose the deterministic preview; no provider will be called.", 422)
            if not s["speaker"]["activeRevision"]:
                raise AlphaError("Approve a provisional voice first.")
            s["runtime"]["selected"] = selected
            s["session"]["step"] = 5
        elif action in ("generate", "preview_update"):
            self._generate(s, p, action == "preview_update")
        elif action == "accept_update":
            v = self._variant(s, p.get("variantId"))
            candidate = v.get("proposedUpdate")
            if not candidate:
                raise AlphaError("Create and review a proposed replacement first.")
            if candidate["briefRevision"] != s["brief"]["revision"] or candidate["voiceRevision"] != s["speaker"]["activeRevision"] or candidate["baseVariantRevision"] != v["revision"]:
                raise AlphaError("This replacement is stale. Create a new preview against your current draft and profile.", 409)
            revision = v["revision"] + 1
            v.update({k: candidate[k] for k in ("text", "openings", "sourceIds", "warnings", "unknowns", "voiceRevision", "briefRevision", "runId")})
            v.update({"revision": revision, "customized": False, "needsReview": False, "blockedByRetraction": False, "proposedUpdate": None, "selectedOpening": 0})
            v.pop("rejected", None)
            v["revisions"].append({"revision": revision, "text": v["text"], "origin": "accepted-fixture-replacement", "at": now()})
            # Hosted Ideas candidates carry a pr_agent_runs id that is not in the local runs list.
            local_run = next((run for run in s["runs"] if run["id"] == v["runId"]), None)
            if local_run is not None:
                local_run["events"].append({"type": "replacement-accepted", "at": now()})
            s["savedAt"] = None
        elif action == "variant_edit":
            v = self._variant(s, p.get("variantId"))
            if p.get("variantRevision") != v["revision"]:
                raise AlphaError("This draft revision is stale. Reload before applying your edit.", 409)
            text = clean(p.get("text", ""), 20000)
            if not text:
                raise AlphaError("Keep some draft text, or choose a different opening.")
            v["text"] = text
            v["revision"] += 1
            v["customized"] = True
            v["revisions"].append({"revision": v["revision"], "text": text, "origin": "author-edit", "at": now()})
            # An edit keeps the draft, so it clears "don't use this" feedback. What the edit changed is a
            # learning signal for a later phase; nothing is proposed from a single edit any more.
            v.pop("rejected", None)
            s["savedAt"] = None
        elif action == "opening":
            v = self._variant(s, p.get("variantId"))
            index = p.get("index")
            if type(index) is not int or not 0 <= index <= 2:
                raise AlphaError("Choose one of the three openings, or edit your own.")
            v["text"] = v["openings"][index] + "\n\n" + v["text"].split("\n\n", 1)[-1]
            v["revision"] += 1
            v["customized"] = True
            v["selectedOpening"] = index
            v["revisions"].append({"revision": v["revision"], "text": v["text"], "origin": "chosen-opening", "at": now()})
            s["savedAt"] = None
        elif action == "preference":
            preference = next((x for x in s["preferences"] if x["id"] == p.get("preferenceId")), None)
            decision = p.get("decision")
            if not preference or decision not in ("remember", "post-only", "reject", "undo", "delete"):
                raise AlphaError("Choose a valid preference decision.")
            if decision in ("remember", "post-only", "reject") and preference["status"] != "proposed":
                raise AlphaError("This preference already has a decision. Undo or delete it first.")
            # Decision A1: a remembered preference is a style revision, never a voice revision, so the exact
            # text and voice bound into existing approvals stay valid (build_manifest, current()).
            if decision == "remember":
                try:
                    learning.remember(s, preference, now=now())
                except ValueError as e:
                    raise AlphaError(str(e)) from e
            elif decision in ("undo", "delete"):
                learning.retire(s, preference["id"], now(), decision)
            preference["status"] = {"remember": "remembered", "post-only": "post-only", "reject": "rejected", "undo": "undone", "delete": "deleted"}[decision]
            preference["decidedAt"] = now()
            variant = next((x for x in s["variants"] if x["id"] == preference.get("variantId")), None)
            if decision == "post-only":
                if variant is None:
                    raise AlphaError("This suggestion is not tied to a draft. Remember it for future drafts, or dismiss it.")
                variant["localPreferences"] = dict(learning.normalize_proposal(preference)["params"])
            if decision in ("undo", "delete") and variant is not None:
                variant["localPreferences"] = {}
            if decision in ("remember", "undo", "delete"):
                s["savedAt"] = None
        elif action == "template_config":
            template_id = p.get("templateId")
            try:
                overrides = validate_overrides(template_id, p.get("overrides"))
            except ValueError as e:
                raise AlphaError(str(e)) from e
            instance = next(x for x in s["skillInstances"] if x["templateId"] == template_id)
            instance["overrides"].update(overrides)
        elif action == "template_refresh":
            # Refresh public definition references without replacing any private overrides.
            versions = {t["id"]: t["version"] for t in catalog()}
            for instance in s["skillInstances"]:
                if instance["templateId"] in versions:
                    instance["templateVersion"] = versions[instance["templateId"]]
        elif action == "save":
            if len(s["variants"]) < 2:
                raise AlphaError("Create a second platform or language variant first.")
            if any(v["needsReview"] or v.get("blockedByRetraction") for v in s["variants"]):
                raise AlphaError("Review proposed draft updates before saving the final pack. Your edits are still stored locally.")
            if any(x["status"] == "proposed" for x in s["preferences"]):
                raise AlphaError("Choose what to do with the proposed preference first.")
            s["savedAt"] = now()
            s["session"].update({"completed": True, "step": 6})
        elif action == "import_propose":
            content = p.get("content")
            if not isinstance(content, dict) or content.get("format") != "postriff-profile-v1":
                raise AlphaError("Import the profile.json from a PostRiff export. Changes will require review.")
            profile = content.get("profile")
            if not isinstance(profile, dict) or profile.get("tone") not in ("warm", "direct", "reflective"):
                raise AlphaError("The imported profile has no supported tone.")
            observations = profile.get("observations", [])
            if not isinstance(observations, list) or len(observations) > 10:
                raise AlphaError("The imported observations are not valid.")
            # Deliberate allowlist: no tool authority, other workspace IDs, source files or opaque instruction fields.
            s["importProposal"] = {"tone": profile["tone"], "writingExample": clean(profile.get("writingExample", ""), 6000), "observations": [clean(v, 1500) for v in observations], "unknowns": ["Imported profile: review before use."], "preferences": []}
        elif action == "import_decide":
            if p.get("approve") is True and s["importProposal"]:
                self._voice(s, s["importProposal"], "Explicit portable-profile import approval")
                self._mark_stale(s)
            s["importProposal"] = None
        else:
            raise AlphaError("This action is not available in the founder alpha.", 404)

    def _generate(self, s, p, updating):
        if s["runtime"]["selected"] != FixtureAdapter.id or not s["speaker"]["activeRevision"]:
            raise AlphaError("Approve a voice and select the deterministic preview first.")
        v = self._variant(s, p.get("variantId")) if updating else None
        platform, language = (v["platform"], v["language"]) if v else (p.get("platform", "LinkedIn"), p.get("language", "English"))
        if platform not in PLATFORMS or language not in LANGUAGES:
            raise AlphaError("Select a supported platform and language.")
        failure = p.get("fixtureFailure")
        if failure and failure not in FAILURES:
            raise AlphaError("Unsupported fixture failure.")
        if not failure and not updating and any(x["platform"] == platform and x["language"] == language for x in s["variants"]):
            raise AlphaError("That version already exists. Edit it or review its proposed update.")
        run = {"id": uid(), "adapter": FixtureAdapter.id, "adapterVersion": FixtureAdapter.version, "voiceRevision": s["speaker"]["activeRevision"], "styleRevision": learning.revision(s), "briefRevision": s["brief"]["revision"], "speakerId": s["speaker"]["id"], "status": "failed" if failure else "completed", "events": [{"type": "started", "at": now()}], "artifacts": [], "createdAt": now()}
        if failure:
            run.update({"failure": failure, "message": f"Simulated {failure}. Your source, profile and existing drafts are safe. Retry the local preview or keep editing."})
            run["events"].append({"type": "cancelled" if failure == "cancelled" else "failed", "at": now()})
            s["runs"].append(run)
            return
        facts = [copy.deepcopy(f) for source in s["sources"] if source["active"] for f in source["facts"] if f["approved"]]
        if s["brandHub"]["mode"] == "business" and not facts:
            raise AlphaError("Approve a current business source fact before generating.")
        profile = self._profile(s)
        config = next(x["overrides"] for x in s["skillInstances"] if x["templateId"] == "content-craft")
        shortened = config.get("shortOpenings", False) or learning.flag(s, "shortOpenings", platform, language)
        if v:
            shortened = shortened or v.get("localPreferences", {}).get("shortOpenings", False)
        request = {"platform": platform, "language": language, "facts": facts, "idea": s["brief"]["idea"], "sample": bool(facts) and all(f.get("fixture") for f in facts), "shortOpenings": shortened, "tone": config.get("tone", profile["tone"])}
        artifact = FixtureAdapter().generate(request)
        if not isinstance(artifact.get("text"), str) or len(artifact.get("openings", [])) != 3:
            raise AlphaError("The adapter returned malformed output. No draft was applied.", 422)
        variant_id = v["id"] if v else uid()
        revision = v["revision"] + 1 if v else 1
        record = {"revision": revision, "text": artifact["text"], "origin": "fixture", "at": now()}
        values = {"id": variant_id, "platform": platform, "language": language, **artifact, "revision": revision, "voiceRevision": run["voiceRevision"], "styleRevision": run["styleRevision"], "speakerId": run["speakerId"], "briefRevision": run["briefRevision"], "runId": run["id"], "customized": False, "needsReview": False, "blockedByRetraction": False, "selectedOpening": 0}
        if v:
            v["proposedUpdate"] = {**artifact, "voiceRevision": run["voiceRevision"], "styleRevision": run["styleRevision"], "briefRevision": run["briefRevision"], "baseVariantRevision": v["revision"], "runId": run["id"]}
            run["status"] = "preview"
        else:
            values.update({"revisions": [record], "localPreferences": {}})
            s["variants"].append(values)
        run["events"].append({"type": "artifact-validated", "at": now()})
        run["artifacts"] = [{"variantId": variant_id, "revision": revision}]
        s["runs"].append(run)
        s["savedAt"] = None

    def export(self, workspace_id, token):
        snapshot = self.get(workspace_id, token)
        s = snapshot["state"]
        if not s["savedAt"] or not self._profile(s):
            raise AlphaError("Save the reviewed two-variant pack before exporting.")
        if any(v["needsReview"] or v.get("blockedByRetraction") for v in s["variants"]):
            raise AlphaError("A source or brief changed. Review the draft updates before export.")
        profile = self._profile(s)
        facts = [{"sourceId": source["id"], "title": source["title"], "visibility": source["visibility"], "facts": [f for f in source["facts"] if f["approved"]]} for source in s["sources"] if source["active"] and any(f["approved"] for f in source["facts"])]
        manifest = {"format": "postriff-export-v1", "schemaVersion": SCHEMA_VERSION, "execution": "deterministic-founder-alpha", "workspaceId": workspace_id, "sample": s["workspace"]["sample"], "snapshotRevision": snapshot["revision"], "voiceRevision": s["speaker"]["activeRevision"], "brief": s["brief"], "sources": facts, "skills": s["skillInstances"], "variants": [{k: v[k] for k in ("id", "revision", "platform", "language", "voiceRevision", "sourceIds", "briefRevision", "runId")} for v in s["variants"]], "research": s["research"]}
        files = {
            "VOICE.md": "# Provisional voice\n\nApproved revision " + str(s["speaker"]["activeRevision"]) + ". Customer-owned data, not tool authority.\n\n" + "\n".join("- " + x for x in profile["observations"]) + "\n\nUnknowns:\n" + "\n".join("- " + x for x in profile["unknowns"]),
            "BRAND.md": "# Private brand hub\n\n" + "\n".join(f"{k}: {s['brandHub'][k]}" for k in ("mode", "purpose", "audience", "subject", "speaker")) + "\n\nMissing facts remain unknown.\n",
            "profile.json": json.dumps({"format": "postriff-profile-v1", "profile": profile}, ensure_ascii=False, indent=2),
            "SKILL.md": "# PostRiff portable skill references\n\nNeutral template references and private settings. This file grants no tools, network or publishing authority. Import profile.json as a reviewed proposal.\n\n" + json.dumps(s["skillInstances"], indent=2),
            "README.md": "# Private founder-alpha export\n\nLocal deterministic preview, not customer validation. Phase 0 remains incomplete. Source quotes are approved by the author, not independently fact checked. Review text before use. No content was scheduled or published. No model was called.\n",
        }
        for i, variant in enumerate(s["variants"], 1):
            files[f"drafts/{i}-{variant['platform']}.md"] = f"# {variant['platform']} · {variant['language']}\n\n" + variant["text"] + "\n\n---\nDeterministic preview.\n\n" + "\n".join(variant["warnings"] + variant["unknowns"])
        if s.get("you"):
            files["YOU.md"] = "# Your chosen identity sentence\n\n" + (s["you"]["identitySentence"] or "No sentence supplied.") + "\n\nPrivate local profile view. Artwork is procedural; no image model was called.\n"
            files["art/brief.json"] = json.dumps(visuals.art_brief(s), ensure_ascii=False, indent=2)
            artwork = s["you"]["artwork"]
            if not artwork or artwork["state"] != "removed":
                files["art/local-watercolor.svg"] = visuals.watercolor(artwork["variant"] if artwork else 0)
        if profile.get("packageSchema"):
            files.update(profiles.portable_files(s, profile))
            manifest.update({"profilePackageSchema": profile["packageSchema"], "status": "user_approved", "permissions": {"globalInstallation": False, "externalSend": False, "accountConnection": False, "publication": False}, "unresolvedFields": sum(r["decision"] != "approved" for r in profile.get("review", []))})
        manifest["files"] = {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}
        files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    def export_profile(self, workspace_id, token):
        snapshot = self.get(workspace_id, token)
        s, profile = snapshot["state"], self._profile(snapshot["state"])
        if not profile or not profile.get("packageSchema"):
            raise AlphaError("Approve the field-level Personal Voice Package before exporting it.")
        files = profiles.portable_files(s, profile)
        manifest = {"schema": "postriff.personal-voice.v1", "packageVersion": "1.0.0", "status": "user_approved", "createdAt": now(), "profileRevision": s["speaker"]["activeRevision"], "workspaceId": workspace_id, "actualRuntime": "deterministic-founder-alpha", "sourceManifest": "sources/manifest.json", "unresolvedFields": sum(r["decision"] != "approved" for r in profile.get("review", [])), "permissions": {"globalInstallation": False, "memoryMutation": False, "accountConnection": False, "externalSend": False, "publication": False}, "files": {name: hashlib.sha256(body.encode()).hexdigest() for name, body in files.items()}}
        files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return buffer.getvalue()

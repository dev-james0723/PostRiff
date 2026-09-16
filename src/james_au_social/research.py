"""Immutable reviewed source observations and versioned atomic claim records.

This is a provenance ledger, not a truth detector. The trusted research caller
must read the source and explicitly judge support/contradiction. Text and URLs
are untrusted data; this module executes neither source instructions nor fetches.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .execution import instant, payload_hash, wire
from .news import assess_claim, canonical_url


class SourceLog:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS source_registry(id TEXT, version INTEGER, body TEXT,
                PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, body TEXT);
            CREATE TABLE IF NOT EXISTS claims(id TEXT, version INTEGER, body TEXT,
                state TEXT, PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS claim_artifacts(artifact TEXT, claim TEXT, version INTEGER,
                published INTEGER, state TEXT, PRIMARY KEY(artifact,claim,version));
            CREATE TABLE IF NOT EXISTS claim_events(seq INTEGER PRIMARY KEY, claim TEXT,
                version INTEGER, event TEXT, reason TEXT, reviewer TEXT, observed_at TEXT);
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

    def register(self, source):
        required = {"source_id", "registry_version", "publisher", "source_tier", "fact_authority",
                    "site_url", "reviewed_at", "enabled"}
        if not required <= source.keys() or not source["source_id"] or not source["publisher"]:
            raise ValueError("source_missing_fields")
        if source["source_tier"] not in {"primary_official", "primary_other", "reliable_secondary", "discovery_only"}:
            raise ValueError("source_tier_invalid")
        if type(source["registry_version"]) is not int or source["registry_version"] < 1:
            raise ValueError("registry_version_invalid")
        if type(source["enabled"]) is not bool or not isinstance(source["fact_authority"], list):
            raise ValueError("source_policy_invalid")
        instant(source["reviewed_at"])
        canonical_url(source["site_url"])
        with self.db() as db:
            old = db.execute("SELECT body FROM source_registry WHERE id=? AND version=?",
                             (source["source_id"], source["registry_version"])).fetchone()
            if old:
                if old[0] != wire(source):
                    raise ValueError("immutable_source_version")
                return
            db.execute("INSERT INTO source_registry VALUES(?,?,?)",
                       (source["source_id"], source["registry_version"], wire(source)))

    def observe(self, source_id, version, *, source_url, retrieved_at, content, evidence_location):
        canonical = canonical_url(source_url)
        instant(retrieved_at)
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 1_000_000 or not evidence_location:
            raise ValueError("bounded_evidence_required")
        with self.db() as db:
            row = db.execute("SELECT body FROM source_registry WHERE id=? AND version=?", (source_id, version)).fetchone()
            if not row:
                raise ValueError("reviewed_source_required")
            source = json.loads(row[0])
            if not source["enabled"]:
                raise ValueError("source_disabled")
            latest = db.execute("SELECT body FROM source_registry WHERE id=? ORDER BY version DESC LIMIT 1", (source_id,)).fetchone()
            if json.loads(latest[0])["registry_version"] != version:
                raise ValueError("stale_source_registry")
            if urlsplit(canonical).netloc != urlsplit(canonical_url(source["site_url"])).netloc:
                raise ValueError("unreviewed_source_host")
            body = {"source": source, "source_url": source_url, "canonical_url": canonical,
                    "retrieved_at": retrieved_at, "content": content,
                    "evidence_location": evidence_location, "content_hash": payload_hash({"content": content})}
            ref = payload_hash(body)
            db.execute("INSERT OR IGNORE INTO observations VALUES(?,?)", (ref, wire(body)))
            return ref

    def observation(self, ref):
        with self.db() as db:
            return self._observation(db, ref)

    @staticmethod
    def _observation(db, ref):
        row = db.execute("SELECT body FROM observations WHERE id=?", (ref,)).fetchone()
        if not row:
            raise ValueError("observation_not_found")
        return json.loads(row[0])

    def review_claim(self, claim_id, version, *, claim_text, claim_type, evidence, reviewer_ref,
                     reviewed_at, qualification, story_id):
        if not claim_id or type(version) is not int or version < 1 or not claim_text.strip() or not reviewer_ref or not story_id:
            raise ValueError("claim_review_required")
        if claim_type not in {"announcement", "specification", "price", "availability", "measured_result", "forecast", "allegation", "opinion"}:
            raise ValueError("claim_type_invalid")
        instant(reviewed_at)
        with self.db() as db:
            supporting, contradicting = [], []
            for binding in evidence:
                if binding.get("relation") not in {"supports", "contradicts", "context_only"}:
                    raise ValueError("explicit_evidence_relation_required")
                observation = self._observation(db, binding["observation_id"])
                if instant(observation["retrieved_at"]) > instant(reviewed_at):
                    raise ValueError("evidence_after_review")
                enriched = {"observation_id": binding["observation_id"], **observation}
                if binding["relation"] == "supports":
                    supporting.append(enriched)
                elif binding["relation"] == "contradicts":
                    contradicting.append(enriched)
            assessed = assess_claim(claim_type, supporting, contradictions=contradicting)
            # A source's opinion can only be attributed, never substituted for
            # James's view, even if registry authority was overbroad.
            if claim_type == "opinion":
                assessed.update(status="attributed" if supporting and not contradicting else "disputed" if contradicting else "unverified",
                                confidence="low", qualification_required=True,
                                usable_for_draft=bool(supporting) and not contradicting)
            if assessed["qualification_required"] and not qualification.strip():
                raise ValueError("qualification_required")
            body = {"claim_id": claim_id, "version": version, "claim_text": claim_text,
                    "claim_type": claim_type, "story_id": story_id, "evidence": evidence,
                    "qualification": qualification, "reviewer_ref": reviewer_ref,
                    "last_reviewed_at": reviewed_at, **assessed}
            old = db.execute("SELECT * FROM claims WHERE id=? ORDER BY version DESC LIMIT 1", (claim_id,)).fetchone()
            if old and version <= old["version"]:
                if version == old["version"] and wire(body) == old["body"]:
                    return {**json.loads(old["body"]), "lifecycle": old["state"]}
                raise ValueError("immutable_claim_version")
            if old:
                db.execute("UPDATE claims SET state='superseded' WHERE id=? AND state='current'", (claim_id,))
                self._invalidate(db, claim_id)
            db.execute("INSERT INTO claims VALUES(?,?,?,'current')", (claim_id, version, wire(body)))
            return {**body, "lifecycle": "current"}

    @staticmethod
    def _invalidate(db, claim_id):
        db.execute("UPDATE claim_artifacts SET state=CASE WHEN published=1 THEN 'correction_required' ELSE 'review_required' END WHERE claim=?", (claim_id,))

    def retract(self, claim_id, version, *, reason, reviewer_ref, now):
        instant(now)
        if not reason or not reviewer_ref:
            raise ValueError("retraction_review_required")
        with self.db() as db:
            row = db.execute("SELECT * FROM claims WHERE id=? AND version=?", (claim_id, version)).fetchone()
            if not row:
                raise ValueError("claim_not_found")
            db.execute("UPDATE claims SET state='retracted' WHERE id=? AND version=?", (claim_id, version))
            db.execute("INSERT INTO claim_events(claim,version,event,reason,reviewer,observed_at) VALUES(?,?,'retracted',?,?,?)",
                       (claim_id, version, reason, reviewer_ref, now))
            self._invalidate(db, claim_id)

    @staticmethod
    def _pack(db, bindings):
        if not bindings or len(set(bindings)) != len(bindings):
            raise ValueError("unique_claim_bindings_required")
        claims = []
        for claim_id, version in bindings:
            row = db.execute("SELECT * FROM claims WHERE id=? AND version=?", (claim_id, version)).fetchone()
            if not row:
                raise ValueError("claim_not_found")
            if row["state"] != "current":
                raise ValueError("claim_" + row["state"])
            body = json.loads(row["body"])
            if not body["usable_for_draft"]:
                raise ValueError("claim_not_usable")
            claims.append(body)
        return {"claims": claims, "fact_pack_hash": payload_hash({"claims": claims}), "establishes_james_view": False}

    def fact_pack(self, bindings):
        with self.db() as db:
            return self._pack(db, bindings)

    def bind_artifact(self, artifact_id, bindings, *, published):
        if type(published) is not bool or not artifact_id:
            raise ValueError("invalid_artifact")
        with self.db() as db:
            self._pack(db, bindings)
            for claim_id, version in bindings:
                db.execute("INSERT INTO claim_artifacts VALUES(?,?,?,?,'current')", (artifact_id, claim_id, version, int(published)))

    def artifact_status(self, artifact_id):
        with self.db() as db:
            states = {r[0] for r in db.execute("SELECT state FROM claim_artifacts WHERE artifact=?", (artifact_id,))}
        if not states:
            raise ValueError("artifact_not_found")
        return "correction_required" if "correction_required" in states else "review_required" if "review_required" in states else "current"

"""Release-gate persistence on a real disposable PostgreSQL database.

All users, attempts, browser verifiers and receipts here are SYNTHETIC TEST DATA.
This validates the persistence contract, never a live provider/browser release gate.
Application writes and reads use service_role; admin is used only for fixture users,
applying migrations, and checking schema/role behavior. No provider is called.

Remote: python scripts/postriff_pg_suite.py postgres_agent_release_gates
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import release_gates as gates  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
SHA = "a" * 40
PINS = {"registryDigest": "1" * 64, "assetsDigest": "2" * 64,
        "provider": "openai", "model": "synthetic-gate-test-model",
        "libraryHashes": {"consumer": "3" * 64, "founder": "4" * 64}}
SOURCE = "root = Card()"
SOURCE_HASH = hashlib.sha256(SOURCE.encode()).hexdigest()


def admin_connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def connection():
    db = admin_connection()
    db.execute("SET ROLE service_role")
    return db


class ReleaseGatePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with admin_connection() as db:
            for _ in range(2):
                for name in ("102_agent_ui_artifacts.sql", "111_agent_release_gates.sql"):
                    db.execute((ROOT / "migrations/postriff" / name).read_text())

    def setUp(self):
        self.now = float(int(time.time()))
        self.owner, self.other = str(uuid.uuid4()), str(uuid.uuid4())
        self.tokens = {"session-owner-" + uuid.uuid4().hex: self.owner,
                       "session-other-" + uuid.uuid4().hex: self.other}
        self.service = HostedWorkspaceService(connection, self.tokens.__getitem__, clock=lambda: self.now)
        with admin_connection() as db:
            with db.cursor() as cur:
                cur.executemany("INSERT INTO auth.users(id) VALUES(%s)", [(p,) for p in self.tokens.values()])
        self.wid, self.other_wid = [self.service.bootstrap(token, "studio")["workspaceId"] for token in self.tokens]
        with connection() as db:
            self.assertEqual(db.execute("SELECT current_user").fetchone()[0], "service_role")

    def receipt(self, profile="full", *, repaired=False, workspace=None):
        receipt = {"contract": gates.CONTRACT, "execution": "live-browser+database",
                   "workspaceId": workspace or self.wid, "releaseSha": SHA, "pins": copy.deepcopy(PINS),
                   "corpus": {"id": gates.CORPUS_ID, "sha256": gates.CORPUS_SHA},
                   "profile": profile, "policy": copy.deepcopy(gates.PROFILES[profile]),
                   "startedAt": self.now - 100, "finishedAt": self.now - 1, "runId": str(uuid.uuid4()),
                   "browserEvidenceSha256": "5" * 64, "deploymentEvidenceSha256": "6" * 64,
                   "cases": [{"caseId": case_id, "artifactId": str(uuid.uuid4()),
                              "attemptIds": [str(uuid.uuid4())], "firstPass": True,
                              "rendered": True, "functional": True, "sourceHash": SOURCE_HASH,
                              "manifestHash": gates.digest({}), "promptHash": "8" * 64,
                              "browserCaseSha256": "9" * 64} for case_id in gates.CASE_IDS]}
        if repaired:
            receipt["cases"][0]["firstPass"] = False
            receipt["cases"][0]["attemptIds"].append(str(uuid.uuid4()))
        return receipt

    def seed(self, receipt):
        """Real schema rows with explicitly synthetic provider fields; not evidence of a model call."""
        wid = receipt["workspaceId"]
        owner = self.owner if wid == self.wid else self.other
        usage = {"provider": PINS["provider"], "model": PINS["model"], "known": True,
                 "dispatched": True, "status": "ok", "inputTokens": 100, "outputTokens": 10,
                 "requestId": "synthetic-provider-request"}
        with connection() as db:
            conversation = db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) "
                                      "VALUES(%s,%s,'Synthetic release gate fixture') RETURNING id", (wid, owner)).fetchone()[0]
            for case in receipt["cases"]:
                scope = "founder" if case["caseId"].startswith("J09-") else "workspace"
                library = PINS["libraryHashes"]["founder" if scope == "founder" else "consumer"]
                parent = db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,"
                                    "context_digest,policy_epoch,idempotency_key,artifact) "
                                    "VALUES(%s,%s,%s,'completed','synthetic-gate','standard',%s,%s,%s,'{}') RETURNING id",
                                    (conversation, wid, owner, "a" * 64, "b" * 64, "gate-fixture:" + uuid.uuid4().hex)).fetchone()[0]
                db.execute("INSERT INTO public.pr_ui_artifacts(id,workspace_id,scope,conversation_id,parent_run_id,actor,surface,"
                           "revision,source_hash,generation_state,validation_state,library_hash,prompt_hash,manifest) "
                           "VALUES(%s,%s,%s,%s,%s,%s,'chat',1,%s,'ready','accepted',%s,%s,'{}')",
                           (case["artifactId"], wid, scope, conversation, parent, owner, SOURCE_HASH, library, case["promptHash"]))
                for index, ident in enumerate(case["attemptIds"]):
                    final = index == len(case["attemptIds"]) - 1
                    kind = "generate" if index == 0 else "repair"
                    db.execute("INSERT INTO public.pr_ui_attempts(id,artifact_id,workspace_id,kind,target_revision,state,retry_of,"
                               "idempotency_key,lease_owner,lease_expires_at,provider_attempts,usage,cost_usd_micro,cost_state,admitted_at,finished_at) "
                               "VALUES(%s,%s,%s,%s,1,%s,%s,%s,'synthetic-fixture',to_timestamp(%s),1,%s::jsonb,1,'known',"
                               "to_timestamp(%s),to_timestamp(%s))",
                               (ident, case["artifactId"], wid, kind, "ready" if final else "failed",
                                None if index == 0 else case["attemptIds"][0], "attempt-fixture:" + uuid.uuid4().hex,
                                self.now + 60, json.dumps(usage), self.now - 90 + index, self.now - 3 + index))
                    if final:
                        db.execute("INSERT INTO public.pr_ui_revisions(artifact_id,workspace_id,revision,kind,attempt_id,source,source_hash,"
                                   "validation,library_hash,prompt_hash) VALUES(%s,%s,1,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                                   (case["artifactId"], wid, kind, ident, SOURCE, SOURCE_HASH,
                                    json.dumps({"accepted": True, "sourceHash": SOURCE_HASH}), library, case["promptHash"]))

    def record(self, receipt, *, verifier=lambda _receipt: True):
        # The verifier is deliberately synthetic. The database path itself is real.
        with connection() as db, db.cursor() as cur:
            gates.record(cur, receipt, PINS, verifier=verifier, now=self.now)

    def ready(self, *, wid=None, sha=SHA, pins=None, now=None):
        with patch.object(gates, "pins", return_value=PINS if pins is None else pins):
            return gates.reader(connection, object(), clock=lambda: self.now if now is None else now)(wid or self.wid, sha)

    def pair(self):
        pair = self.receipt(), self.receipt("recommended_narrowed")
        for receipt in pair:
            self.seed(receipt)
            self.record(receipt)
        return pair

    def count(self):
        with connection() as db:
            return db.execute("SELECT count(*) FROM public.pr_agent_release_gates WHERE workspace_id=%s", (self.wid,)).fetchone()[0]

    def test_reapplied_schema_rls_and_least_privileges(self):
        with admin_connection() as db:
            row = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                             "WHERE oid='public.pr_agent_release_gates'::regclass").fetchone()
            self.assertEqual(row, (True, True))
            privileges = db.execute("SELECT has_table_privilege('service_role','public.pr_agent_release_gates','SELECT'),"
                                    "has_table_privilege('service_role','public.pr_agent_release_gates','INSERT'),"
                                    "has_table_privilege('service_role','public.pr_agent_release_gates','DELETE'),"
                                    "has_column_privilege('service_role','public.pr_agent_release_gates','receipt','UPDATE'),"
                                    "has_column_privilege('service_role','public.pr_agent_release_gates','revoked_at','UPDATE')").fetchone()
            self.assertEqual(privileges, (True, True, False, False, True))
        for role in ("anon", "authenticated"):
            with self.subTest(role=role), admin_connection() as db:
                db.execute("SET ROLE " + role)  # literal fixed-role allowlist above
                for sql in ("SELECT * FROM public.pr_agent_release_gates",
                            "INSERT INTO public.pr_agent_release_gates(run_id) VALUES(gen_random_uuid())",
                            "UPDATE public.pr_agent_release_gates SET revoked_at=now()",
                            "DELETE FROM public.pr_agent_release_gates"):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege), db.transaction():
                        db.execute(sql)

    def test_record_replay_and_independent_pair_reader(self):
        full = self.receipt(repaired=True)
        self.seed(full)
        self.record(full)
        self.record(full)
        self.assertEqual(self.count(), 1)
        self.assertFalse(self.ready())
        narrowed = self.receipt("recommended_narrowed")
        self.seed(narrowed)
        self.record(narrowed)
        self.assertTrue(self.ready())
        self.assertFalse(self.ready(wid=self.other_wid))
        self.assertFalse(self.ready(sha="b" * 40))
        self.assertFalse(self.ready(pins={**PINS, "model": "changed-model"}))
        self.assertFalse(self.ready(now=self.now + gates.MAX_AGE + 1))

    def test_untrusted_verifier_and_missing_attempts_write_nothing(self):
        receipt = self.receipt()
        with self.assertRaises(ValueError):
            self.record(receipt)
        self.seed(receipt)
        for verifier in (None, lambda _: False, lambda _: 1):
            with self.subTest(verifier=verifier), self.assertRaises(ValueError):
                self.record(receipt, verifier=verifier)
        self.assertEqual(self.count(), 0)

    def test_attempt_workspace_binding(self):
        receipt = self.receipt(workspace=self.other_wid)
        self.seed(receipt)
        receipt["workspaceId"] = self.wid
        with self.assertRaises(ValueError):
            self.record(receipt)
        self.assertEqual(self.count(), 0)

    def test_physical_rejection_and_transaction_rollback(self):
        receipt = self.receipt()
        self.seed(receipt)
        attempt = receipt["cases"][0]["attemptIds"][0]
        artifact = receipt["cases"][0]["artifactId"]
        with connection() as db:
            original = db.execute("SELECT usage FROM public.pr_ui_attempts WHERE id=%s", (attempt,)).fetchone()[0]
        changes = [("UPDATE public.pr_ui_attempts SET cost_state='unknown' WHERE id=%s", (attempt,),
                    "UPDATE public.pr_ui_attempts SET cost_state='known' WHERE id=%s", (attempt,)),
                   ("UPDATE public.pr_ui_attempts SET provider_attempts=0 WHERE id=%s", (attempt,),
                    "UPDATE public.pr_ui_attempts SET provider_attempts=1 WHERE id=%s", (attempt,)),
                   ("UPDATE public.pr_ui_attempts SET usage=%s::jsonb WHERE id=%s", (json.dumps({**original, "provider": "fixture"}), attempt),
                    "UPDATE public.pr_ui_attempts SET usage=%s::jsonb WHERE id=%s", (json.dumps(original), attempt)),
                   ("UPDATE public.pr_ui_revisions SET validation='{}' WHERE artifact_id=%s", (artifact,),
                    "UPDATE public.pr_ui_revisions SET validation='{" + '"accepted":true' + "}' WHERE artifact_id=%s", (artifact,))]
        for change, params, restore, restore_params in changes:
            with self.subTest(sql=change):
                with connection() as db:
                    db.execute(change, params)
                try:
                    with self.assertRaises(ValueError):
                        self.record(receipt)
                    self.assertEqual(self.count(), 0)
                finally:
                    with connection() as db:
                        db.execute(restore, restore_params)
        self.record(receipt)
        self.assertEqual(self.count(), 1)

    def test_extra_omitted_attempt_is_rejected(self):
        receipt = self.receipt()
        self.seed(receipt)
        case = receipt["cases"][0]
        with connection() as db:
            db.execute("INSERT INTO public.pr_ui_attempts(artifact_id,workspace_id,kind,target_revision,state,retry_of,idempotency_key,"
                       "lease_owner,lease_expires_at) VALUES(%s,%s,'retry',1,'failed',%s,%s,'synthetic-fixture',now())",
                       (case["artifactId"], self.wid, case["attemptIds"][0], "omitted-attempt:" + uuid.uuid4().hex))
        with self.assertRaises(ValueError):
            self.record(receipt)
        self.assertEqual(self.count(), 0)

    def test_receipt_identity_is_immutable_and_conflicting_replay_rolls_back(self):
        receipt = self.receipt()
        self.seed(receipt)
        self.record(receipt)
        changed = copy.deepcopy(receipt)
        changed["browserEvidenceSha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.record(changed)
        for column, value in (("receipt", "'{}'::jsonb"), ("receipt_hash", "'" + "0" * 64 + "'"),
                              ("release_sha", "'" + "b" * 40 + "'"), ("verified_at", "now()")):
            with self.subTest(column=column), connection() as db:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege), db.transaction():
                    db.execute(f"UPDATE public.pr_agent_release_gates SET {column}={value} WHERE run_id=%s", (receipt["runId"],))
        with connection() as db:
            self.assertEqual(db.execute("SELECT receipt_hash FROM public.pr_agent_release_gates WHERE run_id=%s",
                                        (receipt["runId"],)).fetchone()[0], gates.digest(receipt))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege), db.transaction():
                db.execute("DELETE FROM public.pr_agent_release_gates WHERE run_id=%s", (receipt["runId"],))

    def test_envelope_cannot_omit_required_fields(self):
        # SQL CHECK must reject NULL comparisons as well as explicitly wrong values.
        receipt = self.receipt()
        for field in ("contract", "execution", "runId", "workspaceId", "releaseSha", "profile"):
            missing = copy.deepcopy(receipt)
            missing.pop(field)
            with self.subTest(field=field), connection() as db:
                with self.assertRaises(psycopg.errors.CheckViolation), db.transaction():
                    db.execute("INSERT INTO public.pr_agent_release_gates(run_id,workspace_id,release_sha,profile,receipt_hash,receipt,verified_at) "
                               "VALUES(%s,%s,%s,%s,%s,%s::jsonb,now())",
                               (receipt["runId"], self.wid, SHA, receipt["profile"], gates.digest(missing), json.dumps(missing)))
        self.assertEqual(self.count(), 0)

    def test_revocation_is_monotonic_and_reader_fails_closed(self):
        full, _ = self.pair()
        self.assertTrue(self.ready())
        with connection() as db:
            db.execute("UPDATE public.pr_agent_release_gates SET revoked_at=to_timestamp(%s) WHERE run_id=%s",
                       (self.now, full["runId"]))
        self.assertFalse(self.ready())
        for value in ("NULL", "now()+interval '1 day'"):
            with self.subTest(value=value), connection() as db:
                with self.assertRaises(psycopg.Error), db.transaction():
                    db.execute("UPDATE public.pr_agent_release_gates SET revoked_at=" + value + " WHERE run_id=%s", (full["runId"],))
        self.assertFalse(self.ready())
        # Re-recording an identical receipt cannot clear its revocation.
        self.record(full)
        self.assertFalse(self.ready())

    def test_same_artifacts_relabelled_for_second_profile_do_not_open_gate(self):
        full = self.receipt()
        self.seed(full)
        self.record(full)
        narrowed = copy.deepcopy(full)
        narrowed.update(runId=str(uuid.uuid4()), profile="recommended_narrowed", policy=copy.deepcopy(gates.PROFILES["recommended_narrowed"]))
        self.record(narrowed)
        self.assertFalse(self.ready())


if __name__ == "__main__":
    unittest.main(verbosity=2)

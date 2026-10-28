"""Mutation tests: prove the Q-05 probe can SEE an isolation hole.

Each mutation disables or weakens one isolation control in a COPY of the source tree on
sys.path (via Q05_SRC_ROOT) — no tracked file is edited in place. The probe is then run
against the mutated app and must turn FAIL in the expected way. A mutation the probe does
NOT detect is a hole in the probe, not a pass.

Controls exercised (see docs/q05/RESULTS-LOCAL.md for the observed table):
  M1  workspace membership gate (PostgresWorkspaceRepository.transaction WHERE clause)
  M2  connection/credential -> workspace binding (every credential read on the path)
  M3  OAuth transaction -> workspace+member binding (discord complete + validate_context)
  M5  a silent cross-workspace write that commits then returns 404 (caught only DB-side)
  M4  (negative control) intra-workspace permission requirement -- NOT an isolation control,
      so the cross-tenant probe correctly does not flip; documents the probe's scope.

Skips cleanly without PostgreSQL 16 binaries / psycopg.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# The checkout under test (see tests/q05_backend.py): mutations patch a copy of ITS src/.
TARGET = Path(os.environ.get("Q05_TARGET_ROOT") or REPO)
sys.path.insert(0, str(REPO / "tests"))

try:
    import psycopg  # noqa: F401
    HAVE_PSYCOPG = True
except Exception:
    HAVE_PSYCOPG = False

from q05_backend import pg_available  # noqa: E402

SENDER = (TARGET / "src/postriff_phase2/discord/sender_names.py").exists()
REASON = "needs PostgreSQL 16 server binaries (POSTRIFF_PG_BIN or /usr/lib/postgresql/16/bin) and psycopg"

# Each mutation is a list of (relative source path, exact old text, replacement). The old text
# must appear verbatim in RC1; the test fails loudly if a hunk no longer matches (so a future
# refactor cannot silently turn a mutation into a no-op that looks like a pass).
MUTATIONS = {
    "M1_membership_gate": [
        ("postriff_phase2/hosted.py",
         "WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w",
         "WHERE w.id=%s AND (m.user_id=%s OR TRUE) AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w"),
    ],
    "M2_connection_workspace_binding": [
        ("postriff_phase2/oauth.py",
         'cur.execute("SELECT provider FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))',
         'cur.execute("SELECT provider FROM public.pr_encrypted_credentials WHERE connection_id=%s AND revoked_at IS NULL", (connection_id,))'),
        ("postriff_phase2/oauth.py",
         'cur.execute("SELECT access_ciphertext,key_id,scopes,authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider=\'discord\' AND revoked_at IS NULL FOR NO KEY UPDATE", (workspace_id, connection_id))',
         'cur.execute("SELECT access_ciphertext,key_id,scopes,authorization_generation::text FROM public.pr_encrypted_credentials WHERE connection_id=%s AND provider=\'discord\' AND revoked_at IS NULL FOR NO KEY UPDATE", (connection_id,))'),
        ("postriff_phase2/discord/oauth.py",
         'cur.execute("SELECT access_ciphertext,key_id,refresh_ciphertext,extract(epoch from access_expires_at),authorization_generation::text,scopes,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider=\'discord\' AND revoked_at IS NULL FOR NO KEY UPDATE", (workspace, connection))',
         'cur.execute("SELECT access_ciphertext,key_id,refresh_ciphertext,extract(epoch from access_expires_at),authorization_generation::text,scopes,provider_account_id FROM public.pr_encrypted_credentials WHERE connection_id=%s AND provider=\'discord\' AND revoked_at IS NULL FOR NO KEY UPDATE", (connection,))'),
        ("postriff_phase2/oauth.py",
         "        if cur is None:\n            if getattr(self.providers.get('discord'), 'connections_v2_enabled', False):\n                self.discord_connections.installation_identity(workspace_id, connection_id)",
         "        if cur is None:\n            if False:\n                self.discord_connections.installation_identity(workspace_id, connection_id)"),
        ("postriff_phase2/oauth.py",
         "        elif connections_enabled:\n            self.discord_connections.validate_installation(cur, workspace_id, envelope)",
         "        elif False:\n            self.discord_connections.validate_installation(cur, workspace_id, envelope)"),
    ],
    "M3_oauth_state_binding": [
        ("postriff_phase2/discord/oauth.py",
         '"SELECT id::text,member_id::text,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE workspace_id=%s AND provider=\'discord\' AND state_hash=%s FOR UPDATE", (workspace, hashlib.sha256(state_value.encode()).hexdigest())',
         '"SELECT id::text,member_id::text,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE provider=\'discord\' AND state_hash=%s FOR UPDATE", (hashlib.sha256(state_value.encode()).hexdigest(),)'),
        ("postriff_phase2/discord/oauth.py",
         "if not row or row[1] != actor or row[8]:",
         "if not row or row[8]:"),
        ("postriff_phase2/discord/oauth.py",
         "or context.get('workspaceId') != workspace or context.get('memberId') != actor",
         "or False"),
        ("postriff_phase2/discord/oauth.py",
         "            if actor != context['memberId']:\n                fail()",
         "            if False:\n                fail()"),
    ],
    "M5_silent_cross_workspace_write": [
        ("postriff_phase2/oauth.py",
         "            if channel is None:\n                raise AlphaError('Connection unavailable.', 404)\n            revoke_destination(state, channel, destination_id, principal, self.clock())",
         "            if channel is None:\n                with self.repository.connection_factory() as _sidedb:\n                    _sidedb.execute(\"UPDATE public.pr_encrypted_credentials SET revoked_at=now(),updated_at=now() WHERE connection_id=%s AND provider='discord'\", (connection_id,))\n                    _sidedb.commit()\n                raise AlphaError('Connection unavailable.', 404)\n            revoke_destination(state, channel, destination_id, principal, self.clock())"),
    ],
    # ---- customer Discord sender names (RC2; only on a checkout that has discord/sender_names.py) ----------------
    # S1: the bot-nickname authorizer check (only the member whose Discord account installed the bot may change it).
    "S1_sender_authorizer_check": [
        ("postriff_phase2/discord/sender_names.py",
         "        return bool(record) and record.get('authorizedBy') == actor",
         "        return True"),
    ],
    # S2: the webhook name made GLOBAL: a review freezes the most recently saved name of ANY workspace.
    "S2_sender_name_global": [
        ("postriff_phase2/discord/sender_names.py",
         "                channel['discordSenderName'] = name",
         "                channel['discordSenderName'] = name\n                globals()['_Q05_LAST_NAME'] = name"),
        ("postriff_phase2/discord/sender_names.py",
         "    return validate_name(channel['discordSenderName'], 'webhook')",
         "    return validate_name(globals().get('_Q05_LAST_NAME') or channel['discordSenderName'], 'webhook')"),
    ],
    # S3: single-installation nickname authority deleted (both the read-time and the final write-guard checks).
    "S3_nickname_authority": [
        ("postriff_phase2/discord/sender_names.py",
         "if kind == 'bot' and self.s.nickname_contenders(cur, self.workspace, self.connection, envelope['guild']):",
         "if False:"),
        ("postriff_phase2/discord/sender_names.py",
         "                if self.s.nickname_contenders(cur, self.workspace, self.connection, envelope['guild']):",
         "                if False:"),
    ],
    # S3b: only the final write guard's authority check deleted (the TOCTOU window between preflight and write).
    "S3b_nickname_authority_write_guard": [
        ("postriff_phase2/discord/sender_names.py",
         "                if self.s.nickname_contenders(cur, self.workspace, self.connection, envelope['guild']):",
         "                if False:"),
    ],
    # S4: the dispatch hold for a bot post whose server nickname changed after approval.
    "S4_nickname_hold": [
        ("postriff_phase2/discord/sender_names.py",
         "    if 'botNickname' not in evidence or evidence['botNickname'] != manifest.get('discordBotNickname'):",
         "    if False:"),
    ],
    # S5: the dispatch hold for a named webhook post while the master switch is off.
    "S5_switch_off_hold": [
        ("postriff_phase2/discord/sender_names.py",
         "    if manifest.get('senderKind') == 'webhook' and 'discordSenderName' in manifest and not names_enabled(values):",
         "    if False:"),
    ],
    # Negative control: weakening the intra-workspace permission requirement is NOT a cross-
    # tenant isolation control, so the probe must NOT flip. (Intra-workspace RBAC is covered
    # by tests/phase2/postgres_isolation.py section 4.)
    "M4_permission_requirement_noop": [
        ("postriff_phase2/permissions.py",
         "def require(membership, requirement):\n    if not membership.allows(requirement):\n        raise AlphaError(f\"This action needs the '{requirement}' permission in this workspace.\", 403)",
         "def require(membership, requirement):\n    if False and not membership.allows(requirement):\n        raise AlphaError(f\"This action needs the '{requirement}' permission in this workspace.\", 403)"),
    ],
}


def run_mutated(name, send=True, skip_probe=False):
    hunks = MUTATIONS[name]
    tmp = tempfile.mkdtemp(prefix="q05-mut-")
    try:
        src = Path(tmp) / "src"
        shutil.copytree(TARGET / "src", src)
        for rel, old, new in hunks:
            path = src / rel
            text = path.read_text()
            if old not in text:
                raise AssertionError(f"mutation {name}: hunk no longer matches {rel}; update the test")
            path.write_text(text.replace(old, new, 1))
        env = dict(os.environ, Q05_SRC_ROOT=str(src))
        cmd = [sys.executable, str(REPO / "tests/q05_backend.py"), "run", "--allow-writes"]
        if send:
            cmd += ["--allow-send-risk", "--victim-is-synthetic"]
        if skip_probe:
            cmd.append("--skip-probe")      # the send-level guards are exercised by the scenarios alone
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        assert proc.stdout, "backend produced no JSON. stderr tail:\n" + proc.stderr[-2000:]
        return json.loads(proc.stdout.splitlines()[-1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def failed_cases(result, prefix):
    return [c["case"] for c in result["cases"]
            if c["verdict"] == "FAIL" and c["case"].startswith(prefix)]


def run_mutated_readonly(name):
    """Like run_mutated but writes-on, send-risk OFF (so no send case runs) — for M1b counting."""
    return run_mutated(name, send=False)


@unittest.skipUnless(HAVE_PSYCOPG and pg_available(), REASON)
class Q05MutationDetection(unittest.TestCase):
    def test_m1_membership_gate(self):
        r = run_mutated("M1_membership_gate")
        self.assertEqual(r["status"], "ran")
        self.assertNotEqual(r["probeExit"], 0, "probe did not detect a disabled membership gate")
        self.assertTrue(failed_cases(r, "read."), "no READ case failed under M1")
        self.assertTrue(failed_cases(r, "write."), "no WRITE case failed under M1")

    def test_m1b_gate_removed_fails_every_workspace_scope_case(self):
        # M1b: with the membership gate removed, NO workspace-scope read or write may silently
        # PASS (the old bug: only 6 of 14 writes turned FAIL while the rest passed on object
        # checks). Every ws-scope case must be FAIL or INCONCLUSIVE — never PASS — and the run
        # must fail. Most turn FAIL; invite can land on a seat/validation limit (INCONCLUSIVE),
        # which is still a run failure, never a false deny. Send cases are gated off here.
        r = run_mutated_readonly("M1_membership_gate")
        self.assertEqual(r["status"], "ran")
        self.assertNotEqual(r["probeExit"], 0)
        ws = [c for c in r["cases"] if c.get("scope") == "ws_scope"
              and c["kind"] in ("read", "write") and c["blast"] != "send"]
        self.assertGreaterEqual(len(ws), 28, f"expected many ws-scope cases, saw {len(ws)}")
        passed = [c["case"] for c in ws if c["verdict"] == "PASS"]
        self.assertEqual(passed, [], f"ws-scope case(s) silently PASSED with the gate removed: {passed}")
        # not 6: the overwhelming majority must be hard FAIL, not merely inconclusive. Allowed INCONCLUSIVE:
        # invite (a seat/validation limit), and on a sender-name build the bot-nickname writes, which a second,
        # independent layer still refuses with the gate gone (only the installing member may write a nickname).
        plain = [c for c in ws if ".sender." not in c["case"]]
        failed = sum(1 for c in plain if c["verdict"] == "FAIL")
        self.assertGreaterEqual(failed, len(plain) - 2,
                                f"only {failed}/{len(plain)} ws-scope cases turned FAIL under M1b")
        other = [c["case"] for c in ws if c["verdict"] != "FAIL"
                 and not (c["verdict"] == "INCONCLUSIVE"
                          and (".invite." in c["case"] or (c["case"].startswith("write.sender.") and ".bot." in c["case"])))]
        self.assertEqual(other, [], "ws-scope cases neither FAIL nor an allowed INCONCLUSIVE under M1b")

    def test_m2_connection_workspace_binding(self):
        r = run_mutated("M2_connection_workspace_binding")
        self.assertEqual(r["status"], "ran")
        self.assertNotEqual(r["probeExit"], 0, "probe did not detect a broken connection->workspace binding")
        self.assertTrue(failed_cases(r, "read.idor.destinations"),
                        "destinations IDOR read did not fail under M2")

    def test_m3_oauth_state_binding(self):
        r = run_mutated("M3_oauth_state_binding")
        self.assertEqual(r["status"], "ran")
        self.assertNotEqual(r["probeExit"], 0, "probe did not detect a broken OAuth state binding")
        # Detected through the no-side-effect proof: the cross-tenant completion advances far
        # enough to commit a side effect (victim OAuth transaction consumed + an audit row).
        self.assertTrue(failed_cases(r, "snapshot."), "no-side-effect proof did not fire under M3")
        self.assertFalse(r["dbSideEffect"]["A"]["ok"] and r["dbSideEffect"]["B"]["ok"])

    def test_m5_silent_cross_workspace_write(self):
        r = run_mutated("M5_silent_cross_workspace_write")
        self.assertEqual(r["status"], "ran")
        self.assertNotEqual(r["probeExit"], 0,
                            "probe did not detect a silent cross-workspace write")
        # The HTTP status looked like a denial and the workspace STATE JSON was untouched, so the
        # API-level snapshot alone would miss it; the DB-level snapshot must catch the row change.
        self.assertFalse(r["dbSideEffect"]["A"]["ok"] and r["dbSideEffect"]["B"]["ok"],
                         "DB-level snapshot did not catch the silent write")

    def test_m4_permission_requirement_is_not_an_isolation_control(self):
        # Negative control: this mutation must NOT make any CROSS-TENANT case fail. On a sender-name build the
        # probe also carries same-workspace role cases (viewer/editor), and those, and only those, must see it.
        r = run_mutated("M4_permission_requirement_noop")
        self.assertEqual(r["status"], "ran")
        cross = [c["case"] for c in r["cases"] if c["verdict"] in ("FAIL", "INCONCLUSIVE")
                 and ("->" in c["direction"] or c["case"].startswith(("snapshot.", "matrix.")))]
        self.assertEqual(cross, [], "disabling intra-workspace RBAC unexpectedly changed a cross-tenant outcome; "
                                    "re-examine the isolation model")
        # Owner controls may only be throttled: with the permission check gone, same-workspace members spend the
        # connection's sender-name throttle (6 POSTs per 10 minutes) before the owner's own save/restore runs.
        controls = [(c["case"], c["observed"]) for c in r["cases"] if c["kind"] == "control"
                    and c["verdict"] != "PASS" and c["observed"] not in ("429", "-")]
        self.assertEqual(controls, [], "an owner control failed for a reason other than the throttle")
        if SENDER:
            flipped = [c["case"] for c in r["cases"] if c.get("scope") == "role" and c["verdict"] != "PASS"
                       and (".viewer." in c["case"] or ".editor." in c["case"])]
            self.assertTrue(flipped, "the same-workspace role cases did not see the removed permission check")
        else:
            self.assertEqual(r["probeExit"], 0)
            self.assertEqual(r["summary"]["failed"], 0)

    # ---- sender-name guards (S1-S5): each deleted guard must be detected --------------------------------
    def setUp(self):
        if self._testMethodName.startswith("test_s") and not SENDER:
            self.skipTest("the checkout under test has no customer sender-name feature")

    def failing_checks(self, r, scenario):
        sc = (r.get("scenarios") or {}).get(scenario) or {}
        self.assertTrue(sc.get("checks"), f"scenario {scenario} did not run: {sc.get('detail')}")
        return {k for k, v in sc["checks"].items() if not v}

    def test_s1_sender_authorizer_check(self):
        r = run_mutated("S1_sender_authorizer_check")
        self.assertEqual(r["status"], "ran")
        self.assertNotEqual(r["probeExit"], 0, "probe did not detect a deleted bot-nickname authorizer check")
        caught = [c["case"] for c in r["cases"] if c["case"].startswith(("read.sender.role.", "write.sender.role."))
                  and ".bot." in c["case"] and c["verdict"] in ("FAIL", "INCONCLUSIVE")]
        self.assertTrue(caught, "no bot-nickname role case caught the deleted authorizer check")

    def test_s2_sender_name_made_global(self):
        r = run_mutated("S2_sender_name_global", skip_probe=True)
        self.assertEqual(r["status"], "ran")
        self.assertFalse(r["scenarios"]["name_pollution"]["ok"])
        self.assertTrue(self.failing_checks(r, "name_pollution") & {"frozen_A", "own_username_A", "frozen_B", "own_username_B"})

    def test_s3_nickname_authority_deleted(self):
        r = run_mutated("S3_nickname_authority", skip_probe=True)
        self.assertEqual(r["status"], "ran")
        bad = self.failing_checks(r, "nickname_authority")
        self.assertTrue({"B_after_A_no_patch", "A_after_B_no_patch"} & bad, bad)

    def test_s3b_write_guard_authority_deleted(self):
        r = run_mutated("S3b_nickname_authority_write_guard", skip_probe=True)
        self.assertEqual(r["status"], "ran")
        bad = self.failing_checks(r, "nickname_authority")
        self.assertIn("race_before_write_guard_no_patch", bad, bad)

    def test_s4_nickname_hold_deleted(self):
        r = run_mutated("S4_nickname_hold", skip_probe=True)
        self.assertEqual(r["status"], "ran")
        self.assertTrue({"renamed_nickname_holds", "nothing_sent"} & self.failing_checks(r, "nickname_hold"))

    def test_s5_switch_off_hold_deleted(self):
        r = run_mutated("S5_switch_off_hold", skip_probe=True)
        self.assertEqual(r["status"], "ran")
        self.assertTrue({"held_named_A", "nothing_sent_A"} & self.failing_checks(r, "switch_off"))


if __name__ == "__main__":
    unittest.main()

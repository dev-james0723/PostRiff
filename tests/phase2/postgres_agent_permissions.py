"""Agent permission store and HTTP boundary on a disposable PostgreSQL database.

Every application operation uses the real HostedWorkspaceService repository with
SET ROLE service_role. Admin access is limited to synthetic user creation and
migration 102, which provides the real H4 activation tables. No model/provider
calls or production credentials are used.

Remote run: PYTHONPATH=src:tests python scripts/postriff_pg_suite.py postgres_agent_permissions
"""
from __future__ import annotations

import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import agent_permissions as store  # noqa: E402
from postriff_phase2.agent_runtime_v2 import agent_permissions_http, authz  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", f"host=127.0.0.1 port={os.environ.get('POSTRIFF_PG_PORT', '55438')} dbname=postgres")


def admin_connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def connection():
    db = admin_connection()
    db.execute("SET ROLE service_role")
    return db


class App:
    @staticmethod
    def _body(environ):
        return environ.get("body")

    @staticmethod
    def _query_str(environ, key):
        return environ.get("query", {}).get(key)

    @staticmethod
    def _query_int(environ, key, default):
        return int(environ.get("query", {}).get(key, default))


class AgentPermissionsPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with admin_connection() as db:
            db.execute((ROOT / "migrations/postriff/102_agent_ui_artifacts.sql").read_text())

    def setUp(self):
        self.now = float(int(time.time()))
        self.owner, self.editor, self.other = (str(uuid.uuid4()) for _ in range(3))
        self.owner_token, self.editor_token, self.other_token = ("session-" + uuid.uuid4().hex for _ in range(3))
        self.tokens = dict(zip((self.owner_token, self.editor_token, self.other_token), (self.owner, self.editor, self.other)))
        self.proof_at = self.now - 10

        def verify(token):
            if token not in self.tokens:
                raise AlphaError("Verified session required.", 401)
            return self.tokens[token]

        verify.session_id = lambda token, principal: "session-" + principal
        # A newly refreshed session cannot replace the signed AMR method time.
        verify.auth_time = lambda token, principal: self.now
        verify.method_time = lambda token, principal: ("password", self.proof_at)
        verify.aal = lambda token, principal: "aal2"
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: self.now)
        with admin_connection() as db:
            with db.cursor() as cur:
                cur.executemany("INSERT INTO auth.users(id) VALUES(%s)", [(uid,) for uid in self.tokens.values()])
        self.wid = self.service.bootstrap(self.owner_token, "studio")["workspaceId"]
        self.other_wid = self.service.bootstrap(self.other_token, "studio")["workspaceId"]
        self.service.bootstrap(self.editor_token, "studio")
        with connection() as db:
            self.assertEqual(db.execute("SELECT current_user").fetchone()[0], "service_role")
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.wid, self.editor))

    def route(self, method="GET", rest=(), *, payload=None, token=None, workspace=None, query=None, mode="shadow"):
        runtime = SimpleNamespace(service=self.service, cfg=SimpleNamespace(permissions_for=lambda wid: mode))
        status, body = agent_permissions_http._route(
            App(), {"body": payload, "query": query or {}}, runtime, token or self.owner_token,
            method, workspace or self.wid, list(rest),
        )
        self.assertEqual(status, 200)
        return body

    def one(self, sql, params=()):
        with connection() as db:
            return db.execute(sql, params).fetchone()

    def payload(self, preset="recommended", *, epoch=0, key=None, **extra):
        return {"preset": preset, "expectedEpoch": epoch, "consentVersion": store.CONSENT_VERSION,
                "copyDigest": store.COPY_DIGEST, "confirmed": True, "source": "settings",
                "idempotencyKey": key or uuid.uuid4().hex, **extra}

    def choose(self, preset="recommended", **kwargs):
        payload = kwargs.pop("payload", None) or self.payload(preset)
        return self.route("PUT", payload=payload, **kwargs)

    def revoke(self, *, payload=None, **kwargs):
        return self.route("POST", ["revoke"], payload=payload or {"all": True, "idempotencyKey": uuid.uuid4().hex}, **kwargs)

    def assert_denied(self, code, fn, status=None):
        with self.assertRaises(AlphaError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)
        if status is not None:
            self.assertEqual(caught.exception.status, status)

    def snapshot(self, workspace=None):
        wid = workspace or self.wid
        tables = ("pr_agent_permission_state", "pr_agent_consent_receipts", "pr_agent_grants",
                  "pr_agent_autopilot_policies", "pr_agent_permission_reminders", "pr_agent_workspace_policy",
                  "pr_ui_activations", "pr_audit_events")
        with connection() as db:
            saved = {table: [r[0] for r in db.execute(
                f"SELECT to_jsonb(t) FROM public.{table} t WHERE workspace_id=%s ORDER BY to_jsonb(t)::text", (wid,))]
                for table in tables}
            saved["workspace"] = db.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()
            return saved

    def activation(self, *, user=None, workspace=None, expired=False, used=False):
        user, wid = user or self.owner, workspace or self.wid
        activation = "act_" + uuid.uuid4().hex
        with connection() as db:
            conversation = db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Permission test') RETURNING id",
                                      (wid, user)).fetchone()[0]
            run = db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                             "VALUES(%s,%s,%s,'completed','rafii-agent','standard',%s,%s,%s,'{}') RETURNING id",
                             (conversation, wid, user, "a" * 64, "b" * 64, "permission-test:" + uuid.uuid4().hex)).fetchone()[0]
            artifact = db.execute("INSERT INTO public.pr_ui_artifacts(workspace_id,conversation_id,parent_run_id,actor,surface) VALUES(%s,%s,%s,%s,'chat') RETURNING id",
                                  (wid, conversation, run, user)).fetchone()[0]
            db.execute("INSERT INTO public.pr_ui_activations(id,workspace_id,principal,artifact_id,artifact_revision,action_id,input_digest,binding_version,expires_at,used_at) "
                       "VALUES(%s,%s,%s,%s,0,'draft_edit',%s,1,now()+(%s * interval '1 hour'),CASE WHEN %s THEN now()-interval '10 minutes' END)",
                       (activation, wid, user, artifact, "c" * 64, -1 if expired else 1, used))
        return activation

    def activation_state(self, activation):
        return self.one("SELECT used_at,expires_at FROM public.pr_ui_activations WHERE id=%s", (activation,))

    def autopilot(self, receipt, *, user=None, workspace=None, capability="context.page_summary"):
        user, wid = user or self.owner, workspace or self.wid
        with connection() as db:
            return str(db.execute("INSERT INTO public.pr_agent_autopilot_policies(workspace_id,user_id,capability_ids,constraints,limits,created_epoch,receipt_id,step_up_at,expires_at) "
                                  "VALUES(%s,%s,%s,'{}','{}',%s,%s,now(),now()+interval '1 hour') RETURNING id",
                                  (wid, user, [capability], receipt["epochAfter"], receipt["id"])).fetchone()[0])

    def test_legacy_and_repeated_reminders_keep_grants_untouched(self):
        before = self.route()
        self.assertEqual((before["state"]["source"], before["state"]["epoch"], before["state"]["needsChoice"]), ("legacy", 0, True))
        self.assertTrue(before["reminder"]["due"])
        first_time = self.now
        for offset, action in ((0, "shown"), (30, "shown"), (60, "not_now"), (90, "dismissed")):
            self.now = first_time + offset
            shown = self.route("POST", ["reminder"], payload={"action": action})
            self.assertEqual(shown["reminder"], {"due": False, "nextAt": first_time + store.REMINDER_SECONDS})
        row = self.one("SELECT prompts,last_response,extract(epoch from last_prompted_at) FROM public.pr_agent_permission_reminders WHERE workspace_id=%s AND user_id=%s", (self.wid, self.owner))
        self.assertEqual((row[0], row[1], float(row[2])), (1, "dismissed", first_time))
        self.now = first_time + store.REMINDER_SECONDS - 1
        self.assertFalse(self.route()["reminder"]["due"])
        self.now += 1
        self.assertTrue(self.route()["reminder"]["due"])
        self.route("POST", ["reminder"], payload={"action": "shown"})
        self.assertEqual(self.one("SELECT prompts,last_response FROM public.pr_agent_permission_reminders WHERE workspace_id=%s AND user_id=%s", (self.wid, self.owner)), (2, None))
        after = self.route()
        self.assertEqual(after["state"], before["state"])
        for table in ("pr_agent_permission_state", "pr_agent_grants", "pr_agent_consent_receipts"):
            self.assertEqual(self.one(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (self.wid,))[0], 0)

    def test_presets_require_confirmation_and_current_epoch_and_copy(self):
        self.choose("none")
        before = self.snapshot()
        self.assert_denied("confirmation_required", lambda: self.choose(payload=self.payload(epoch=1, confirmed=False)))
        self.assertEqual(self.snapshot(), before)
        saved = self.choose(payload=self.payload(epoch=1))
        self.assertEqual((saved["state"]["preset"], saved["state"]["epoch"], saved["receipt"]["widened"]), ("recommended", 2, True))
        self.assertEqual(self.one("SELECT count(*) FROM public.pr_agent_grants WHERE workspace_id=%s AND user_id=%s AND revoked_at IS NULL", (self.wid, self.owner))[0], len(store.preset_scopes("recommended")))
        before = self.snapshot()
        self.assert_denied("agent_permissions_changed", lambda: self.choose(payload=self.payload("none", epoch=1)), 409)
        self.assert_denied("agent_permissions_copy_stale", lambda: self.choose(payload=self.payload("none", epoch=2, copyDigest="0" * 64)))
        self.assertEqual(self.snapshot(), before)

    def test_full_requires_signed_fresh_proof_and_database_constraint(self):
        self.choose()
        before = self.snapshot()
        self.assert_denied("step_up_required", lambda: self.choose(payload=self.payload("full", epoch=1)))
        for proof_at in (self.now - 301, self.now + 1, 0, None):
            with self.subTest(proof_at=proof_at):
                self.proof_at = proof_at
                self.assert_denied("step_up_required", lambda: self.choose(payload=self.payload("full", epoch=1, stepUp=True)))
                self.assertEqual(self.snapshot(), before)
        self.proof_at = self.now - 10
        saved = self.choose(payload=self.payload("full", epoch=1, stepUp=True))
        self.assertEqual((saved["state"]["preset"], saved["state"]["spendConfirmation"], saved["receipt"]["stepUp"]), ("full", "none", True))
        proof = self.one("SELECT step_up FROM public.pr_agent_consent_receipts WHERE id=%s", (saved["receipt"]["id"],))[0]
        self.assertEqual(proof, {"method": "password", "at": self.proof_at, "aal": "aal2"})
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connection() as db:
                db.execute("UPDATE public.pr_agent_permission_state SET step_up_at=decided_at-interval '301 seconds' WHERE workspace_id=%s AND user_id=%s", (self.wid, self.owner))
        self.assertEqual(self.route()["state"]["epoch"], 2)

    def test_actor_and_workspace_scoped_idempotency_replay_and_conflict(self):
        payload = self.payload(key="same-browser-request-0001")
        first = self.choose(payload=payload)
        replay = self.choose(payload=payload)  # expectedEpoch=0 is stale but exact replay returns its receipt.
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(replay["state"]["epoch"], 1)
        before = self.snapshot()
        self.assert_denied("idempotency_conflict", lambda: self.choose(payload={**payload, "preset": "none"}), 409)
        self.assertEqual(self.snapshot(), before)
        editor = self.choose(payload=payload, token=self.editor_token)
        other = self.choose(payload=payload, token=self.other_token, workspace=self.other_wid)
        self.assertEqual(len({first["receipt"]["id"], editor["receipt"]["id"], other["receipt"]["id"]}), 3)
        self.assertEqual(self.one("SELECT count(*) FROM public.pr_agent_consent_receipts WHERE workspace_id=%s", (self.wid,))[0], 2)

    def test_shadow_records_choice_without_invalidating_activations_or_autopilot(self):
        choice = self.choose()
        activation = self.activation()
        policy = self.autopilot(choice["receipt"])
        activation_before = self.activation_state(activation)
        revoked = self.revoke(mode="shadow", payload={"scopes": ["capability:context.page_summary"], "idempotencyKey": uuid.uuid4().hex})
        self.assertEqual(revoked["state"]["preset"], "custom")
        self.assertEqual(revoked["receipt"]["invalidated"], {})
        self.assertEqual(self.activation_state(activation), activation_before)
        self.assertIsNone(self.one("SELECT revoked_at FROM public.pr_agent_autopilot_policies WHERE id=%s", (policy,))[0])

    def test_enforce_revokes_only_this_person_live_unused_activations(self):
        owner = self.choose()
        editor = self.choose(token=self.editor_token)
        other = self.choose(token=self.other_token, workspace=self.other_wid)
        mine = self.activation()
        theirs = self.activation(user=self.editor)
        foreign = self.activation(user=self.other, workspace=self.other_wid)
        expired = self.activation(expired=True)
        used = self.activation(used=True)
        untouched = {a: self.activation_state(a) for a in (theirs, foreign, expired, used)}
        policy = self.autopilot(owner["receipt"])
        editor_policy = self.autopilot(editor["receipt"], user=self.editor)
        foreign_policy = self.autopilot(other["receipt"], user=self.other, workspace=self.other_wid)
        revoked = self.revoke(mode="enforce")
        self.assertEqual(revoked["receipt"]["invalidated"]["ui_activations"], 1)
        self.assertEqual(revoked["receipt"]["invalidated"]["autopilot"], 1)
        self.assertIsNotNone(self.activation_state(mine)[0])
        for activation, before in untouched.items():
            self.assertEqual(self.activation_state(activation), before)
        self.assertEqual(self.one("SELECT revoke_reason FROM public.pr_agent_autopilot_policies WHERE id=%s", (policy,))[0], "permission_changed")
        for pid in (editor_policy, foreign_policy):
            self.assertIsNone(self.one("SELECT revoked_at FROM public.pr_agent_autopilot_policies WHERE id=%s", (pid,))[0])

    def test_workspace_wide_revocation_accepts_null_person_and_is_tenant_scoped(self):
        owner = self.choose()
        editor = self.choose(token=self.editor_token)
        other = self.choose(token=self.other_token, workspace=self.other_wid)
        mine, theirs = self.activation(), self.activation(user=self.editor)
        foreign = self.activation(user=self.other, workspace=self.other_wid)
        expired = self.activation(expired=True)
        owner_policy = self.autopilot(owner["receipt"])
        editor_policy = self.autopilot(editor["receipt"], user=self.editor)
        unrelated = self.autopilot(owner["receipt"], capability="context.memory_layers")
        foreign_policy = self.autopilot(other["receipt"], user=self.other, workspace=self.other_wid)
        event = store.RevocationEvent(self.wid, None, frozenset({"context.page_summary"}), "d" * 64, None, "workspace_consent_narrowed", 2)
        with self.service.repository.transaction(self.owner_token, self.wid) as (cur, _row, _principal):
            result = store._run_handlers(cur, event, mode="enforce")
        self.assertEqual(result, {"ui_activations": 2, "autopilot": 2})
        for activation in (mine, theirs):
            self.assertIsNotNone(self.activation_state(activation)[0])
        for activation in (foreign, expired):
            self.assertIsNone(self.activation_state(activation)[0])
        for pid in (owner_policy, editor_policy):
            self.assertEqual(self.one("SELECT revoked_epoch FROM public.pr_agent_autopilot_policies WHERE id=%s", (pid,))[0], 2)
        for pid in (unrelated, foreign_policy):
            self.assertIsNone(self.one("SELECT revoked_at FROM public.pr_agent_autopilot_policies WHERE id=%s", (pid,))[0])

    def test_handler_failure_rolls_back_activation_policy_receipt_grants_and_audit(self):
        saved = self.choose()
        self.activation()
        self.autopilot(saved["receipt"])
        before = self.snapshot()
        handlers = list(store.REVOCATION_HANDLERS)

        def fail_after_mutation(cur, event):
            cur.execute("UPDATE public.pr_workspaces SET revision=revision+1 WHERE id=%s", (event.workspace_id,))
            raise RuntimeError("synthetic revocation handler failure")

        store.register_revocation_handler("test_failure", fail_after_mutation)
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic revocation handler failure"):
                self.revoke(mode="enforce")
        finally:
            store.REVOCATION_HANDLERS[:] = handlers
        self.assertEqual(self.snapshot(), before)
        retried = self.revoke(mode="enforce")
        self.assertEqual(retried["state"]["epoch"], 2)
        self.assertEqual(retried["receipt"]["invalidated"]["ui_activations"], 1)

    def test_first_legacy_revoke_never_widens_and_retains_append_only_history(self):
        with self.service.repository.transaction(self.owner_token, self.wid) as (cur, row, principal):
            before = store.load(cur, self.wid, principal, now=self.now)
            member, state = self.service.ideas._member(row), self.service.ideas._state(row)
        revoked = self.revoke(payload={"scopes": ["capability:context.page_summary"], "idempotencyKey": uuid.uuid4().hex})
        self.assertEqual((revoked["state"]["preset"], revoked["state"]["baseline"], revoked["receipt"]["widened"]), ("custom", "legacy_v1", False))
        with connection() as db:
            after = store.load(db.cursor(), self.wid, self.owner, now=self.now)
        actor = authz.Actor("agent", self.owner)
        for cap in authz.catalogue():
            for surface in authz.capability_surfaces(cap):
                old = authz.decide(cap, surface=surface, member=member, grants=before, state=state, actor=actor, now=self.now)
                new = authz.decide(cap, surface=surface, member=member, grants=after, state=state, actor=actor, now=self.now)
                with self.subTest(capability=cap.capability_id, surface=surface.name):
                    if old.outcome == "deny":
                        self.assertEqual(new.outcome, "deny")
                    elif new.outcome != "deny":
                        self.assertGreaterEqual(authz.CONFIRMATIONS.index(new.required), authz.CONFIRMATIONS.index(old.required))
                    if cap.capability_id == "context.page_summary":
                        self.assertEqual(new.outcome, "deny")
        self.revoke()
        self.assertEqual(self.one("SELECT count(*),count(*) FILTER (WHERE revoked_at IS NULL) FROM public.pr_agent_grants WHERE workspace_id=%s AND user_id=%s", (self.wid, self.owner)), (len(after.scopes()), 0))
        self.assertEqual(len(self.route(rest=["history"])["items"]), 2)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with connection() as db:
                db.execute("UPDATE public.pr_agent_grants SET revoked_at=NULL WHERE workspace_id=%s AND user_id=%s", (self.wid, self.owner))

    def test_membership_end_is_atomic_idempotent_and_reinvite_starts_legacy(self):
        self.choose(token=self.editor_token)
        activation = self.activation(user=self.editor)
        with self.service.repository.transaction(self.owner_token, self.wid) as (cur, _row, principal):
            receipt = store.on_membership_ended(cur, self.wid, self.editor, actor=principal, now=self.now, mode="enforce")
            cur.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (self.wid, self.editor))
        self.assertIsNotNone(receipt)
        self.assertIsNotNone(self.activation_state(activation)[0])
        with self.assertRaises(AlphaError) as denied:
            self.route(token=self.editor_token)
        self.assertEqual(denied.exception.status, 403)
        before = self.snapshot()
        with self.service.repository.transaction(self.owner_token, self.wid) as (cur, _row, principal):
            self.assertIsNone(store.on_membership_ended(cur, self.wid, self.editor, actor=principal, now=self.now, mode="enforce"))
            self.assertIsNone(store.on_membership_ended(cur, self.wid, self.owner, actor=principal, now=self.now, mode="enforce"))
        self.assertEqual(self.snapshot(), before)
        with self.service.repository.transaction(self.owner_token, self.wid) as (cur, _row, _principal):
            cur.execute("UPDATE public.pr_memberships SET status='active' WHERE workspace_id=%s AND user_id=%s", (self.wid, self.editor))
        invited = self.route(token=self.editor_token)
        self.assertEqual((invited["state"]["source"], invited["state"]["ended"], invited["state"]["needsChoice"], invited["state"]["epoch"]), ("legacy", True, True, 2))
        self.assertEqual(len(self.route(rest=["history"], token=self.editor_token)["items"]), 2)
        chosen = self.choose(token=self.editor_token, payload=self.payload(epoch=2))
        self.assertEqual((chosen["state"]["source"], chosen["state"]["ended"], chosen["state"]["epoch"]), ("explicit", False, 3))

    def test_account_erasure_guard_and_database_privileges_preserve_other_tenant(self):
        self.route("POST", ["reminder"], payload={"action": "not_now"})
        saved = self.choose()
        self.autopilot(saved["receipt"])
        self.choose(token=self.other_token, workspace=self.other_wid)
        with connection() as db:
            db.execute("INSERT INTO public.pr_agent_workspace_policy(workspace_id,epoch,updated_by) VALUES(%s,1,%s)", (self.wid, self.owner))
        before, foreign = self.snapshot(), self.snapshot(self.other_wid)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with connection() as db:
                store.erase_workspace(db.cursor(), self.wid)
        for sql in ("DELETE FROM public.pr_agent_permission_state WHERE workspace_id=%s",
                    "DELETE FROM public.pr_agent_consent_receipts WHERE workspace_id=%s",
                    "UPDATE public.pr_agent_consent_receipts SET widened=false WHERE workspace_id=%s"):
            with self.subTest(sql=sql), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connection() as db:
                    db.execute(sql, (self.wid,))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with connection() as db:
                db.execute("DELETE FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s", (self.wid, self.owner))
        self.assertEqual(self.snapshot(), before)
        with self.service.repository.transaction(self.owner_token, self.wid) as (cur, _row, _principal):
            cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{accountDeletion}',jsonb_build_object('requestedAt',%s::double precision)) WHERE id=%s", (self.now, self.wid))
        with self.service.repository.transaction(self.owner_token, self.wid, allow_deleting=True) as (cur, _row, _principal):
            removed = store.erase_workspace(cur, self.wid)
        permission_tables = ("pr_agent_permission_state", "pr_agent_consent_receipts", "pr_agent_grants",
                             "pr_agent_autopilot_policies", "pr_agent_permission_reminders", "pr_agent_workspace_policy")
        self.assertEqual(removed, sum(len(before[table]) for table in permission_tables))
        for table in permission_tables:
            self.assertEqual(self.one(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (self.wid,))[0], 0)
        self.assertEqual(self.snapshot(self.other_wid), foreign)

    def test_history_pagination_and_http_member_and_tenant_authorization(self):
        receipts = []
        for epoch, preset in enumerate(("none", "recommended", "none")):
            self.now += 1
            receipts.append(self.choose(payload=self.payload(preset, epoch=epoch))["receipt"]["id"])
        editor = self.choose(token=self.editor_token)["receipt"]["id"]
        other = self.choose(token=self.other_token, workspace=self.other_wid)["receipt"]["id"]
        page = self.route(rest=["history"], query={"limit": 1})
        self.assertEqual(([x["id"] for x in page["items"]], page["next"]), ([receipts[-1]], receipts[-1]))
        rest = self.route(rest=["history"], query={"cursor": page["next"]})
        self.assertEqual([x["id"] for x in rest["items"]], list(reversed(receipts[:-1])))
        self.assertTrue(all(x["actorIsYou"] for x in rest["items"]))
        member_history = self.route(rest=["history"], query={"member": self.editor})
        self.assertEqual([x["id"] for x in member_history["items"]], [editor])
        self.assertFalse(member_history["items"][0]["actorIsYou"])
        for rest, query in ((["history"], {"member": self.owner}), (["members"], {})):
            with self.subTest(rest=rest), self.assertRaises(AlphaError) as denied:
                self.route(rest=rest, query=query, token=self.editor_token)
            self.assertEqual(denied.exception.status, 403)
        errors = []
        for wid in (self.wid, str(uuid.uuid4())):
            with self.assertRaises(AlphaError) as denied:
                self.route(token=self.other_token, workspace=wid)
            errors.append((denied.exception.status, str(denied.exception)))
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(self.route(rest=["history"], query={"member": self.other})["items"], [])
        self.assertEqual(self.route(rest=["history"], query={"cursor": other})["items"], [])
        members = self.route(rest=["members"])["members"]
        self.assertEqual({x["userId"] for x in members}, {self.owner, self.editor})

    def test_tool_context_cannot_write_and_off_http_is_unavailable(self):
        before = self.snapshot()
        with authz.in_tool():
            with self.assertRaises(AlphaError):
                self.choose()
            with self.assertRaises(AlphaError):
                self.revoke()
            with self.assertRaises(AlphaError):
                self.route("POST", ["reminder"], payload={"action": "not_now"})
        self.assert_denied("agent_permissions_unavailable", lambda: self.route(mode="off"), 404)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)

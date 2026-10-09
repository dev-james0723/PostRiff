"""rafii-genui/1 lane D: the guarded action dispatcher's rules, statement by statement (G06 G08 G09; D-A14 D-A15 D-A20).

A scripted cursor plays the database so each rule is pinned without a server: the stored receipt wins before anything
else (same key + digest → stored result, other digest → 409), the activation must match principal/artifact/revision/
binding/action/digest and be unused and unexpired, a domain refusal becomes a stored receipt after rolling the command
back, `verified` is only ever the executor's re-read of an applied change, a prepared change can never be reported as
applied, creates/prepares are deduplicated per view revision, and a paid two-phase action is deferred outside the lock.
The real-database version of the same flows (roles, tenants, concurrency) is tests/phase2/postgres_agent_ui_actions.py.
"""
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.agent_runtime_v2 import domain_tools, ui_actions, ui_capabilities, ui_contracts, ui_domain  # noqa: E402
from postriff_phase2.agent_runtime_v2.ui_http import UiAuth  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402

WS = "11111111-1111-4111-8111-111111111111"
ART = "33333333-3333-4333-8333-333333333333"
ME = "00000000-0000-0000-0000-000000000001"
KEY = "k_" + "a" * 30
ACT = "act_" + "b" * 43


class Script:
    """fetchone answers by statement prefix; every statement is recorded."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))
        self.rowcount = 1

    def fetchone(self):
        last = self.statements[-1][0]
        for prefix, answer in self.answers.items():
            if last.startswith(prefix):
                return answer() if callable(answer) else answer
        return None

    def fetchall(self):
        return []

    def ran(self, prefix):
        return [s for s, _ in self.statements if s.startswith(prefix)]


def auth(role="owner", principal=ME):
    return UiAuth(workspace_id=WS, principal=principal, member=Membership.from_row(role), role=role)


class Dispatcher(unittest.TestCase):
    def setUp(self):
        self.executed = []
        self.outcome = ui_domain.Receipt(outcome="applied", verified=True, receipt_ref="x:1", changed_refs=["x:1"], invalidation_keys=["drafts_list"])

        def execute(dctx, inputs, key):
            self.executed.append((inputs, key))
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

        confirm = lambda dctx, inputs: {"title": "T", "summary": ["s"]}  # noqa: E731
        self.bindings = {
            "t_edit": ui_domain.ActionBinding("t_edit", "J01", "Edit", "Edits", "MUTATE_REVERSIBLE", "edit", ui_domain.schema({"text": {"type": "string", "maxLength": 20}}),
                                              confirm, execute),
            "t_prepare": ui_domain.ActionBinding("t_prepare", "J01", "Prep", "Prepares", "PREPARE_EXTERNAL", "approve", ui_domain.schema({"text": {"type": "string", "maxLength": 20}}),
                                                 confirm, execute, prepare_only=True, dedupe="intent"),
            "t_paid": ui_domain.ActionBinding("t_paid", "J04", "Paid", "Paid", "MUTATE_REVERSIBLE", "owner", ui_domain.schema({"text": {"type": "string", "maxLength": 20}}),
                                              confirm, execute, two_phase=True),
        }
        ui_domain.ACTIONS.update(self.bindings)
        future = ui_contracts.now_iso().replace(str(time.gmtime().tm_year), "2999")
        member = auth().member
        self.manifest = {"manifestId": "mf_t", "bindingVersion": 1, "scope": "workspace", "scopeKey": "", "workspaceId": WS, "expiresAt": future,
                         "permissionRevision": ui_capabilities.permission_revision(member), "queries": [],
                         "actions": [{"actionId": a} for a in self.bindings], "actionTargets": {a: {"expiresAt": future} for a in self.bindings}}
        self.artifact = {"id": ART, "revision": 3, "source_hash": "c" * 64, "conversation_id": "c", "parent_run_id": "r"}

    def tearDown(self):
        for name in self.bindings:
            ui_domain.ACTIONS.pop(name, None)

    def request(self, action="t_edit", text="hello", key=KEY):
        return {"artifactId": ART, "artifactRevision": 3, "actionId": action, "inputs": {"text": text}, "idempotencyKey": key, "activationId": ACT}

    def activation_row(self, action="t_edit", text="hello", principal=ME, revision=3, version=1, expires=None, used=False):
        return (principal, ART, revision, action, ui_contracts.input_digest(action, {"text": text}), version, expires or time.time() + 30, used)

    def script(self, **extra):
        answers = {"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,activation_id,state,outcome": None,
                   "SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version": self.activation_row(),
                   "SELECT revision,state FROM public.pr_workspaces": (12, "{}"),
                   "SELECT coalesce(time_zone,'')": ("UTC",),
                   "SELECT idempotency_key,outcome FROM public.pr_ui_actions": None,
                   "INSERT INTO public.pr_auth_throttle": (1,)}
        answers.update(extra)
        return Script(answers)

    def run_action(self, cur, request=None, who=None):
        return ui_actions.execute_ui_action(cur, who or auth(), self.artifact, self.manifest, request or self.request(), runtime=SimpleNamespace(service=SimpleNamespace()))

    # --- the stored receipt wins ------------------------------------------------------------------------------------------
    def test_same_key_and_digest_returns_the_stored_result_and_runs_nothing(self):
        stored = {"actionId": "t_edit", "outcome": "applied", "verified": True}
        cur = self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,activation_id,state,outcome":
                             (ME, ART, 3, "t_edit", ui_contracts.input_digest("t_edit", {"text": "hello"}), ACT, "done", json.dumps(stored))})
        self.assertEqual(self.run_action(cur), stored)
        self.assertEqual(self.executed, [])
        self.assertEqual(cur.ran("UPDATE public.pr_ui_activations"), [])

    def test_same_key_with_other_inputs_is_a_conflict(self):
        cur = self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,activation_id,state,outcome":
                             (ME, ART, 3, "t_edit", ui_contracts.input_digest("t_edit", {"text": "other"}), ACT, "done", "{}")})
        with self.assertRaises(AlphaError) as conflict:
            self.run_action(cur)
        self.assertEqual((conflict.exception.status, conflict.exception.code), (409, "ui_idempotency_conflict"))
        self.assertEqual(self.executed, [])

    # --- the activation ------------------------------------------------------------------------------------------------------
    def test_the_activation_must_match_exactly_be_unused_and_unexpired(self):
        cases = {"ui_activation": [self.activation_row(text="different"), self.activation_row(principal="00000000-0000-0000-0000-000000000009"),
                                   self.activation_row(action="t_prepare"), None],
                 "ui_revision_stale": [self.activation_row(revision=2), self.activation_row(version=2)],
                 "ui_activation_used": [self.activation_row(used=True)],
                 "ui_activation_expired": [self.activation_row(expires=time.time() - 1)]}
        for code, rows in cases.items():
            for row in rows:
                with self.subTest(code=code, row=row):
                    cur = self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version": row})
                    with self.assertRaises(AlphaError) as refused:
                        self.run_action(cur)
                    self.assertEqual(refused.exception.code, code)
                    self.assertEqual(self.executed, [])
                    self.assertEqual(cur.ran("INSERT INTO public.pr_ui_actions"), [])

    def test_a_viewer_or_a_stale_view_never_reaches_the_command(self):
        with self.assertRaises(AlphaError) as viewer:
            self.run_action(self.script(), who=auth("viewer"))
        self.assertEqual((viewer.exception.status, viewer.exception.code), (403, "ui_forbidden"), "an offered control the role can't use is 403 (NC02)")
        with self.assertRaises(AlphaError) as never:
            self.run_action(self.script(), request={**self.request(), "actionId": "publish_now"}, who=auth("viewer"))
        self.assertEqual((never.exception.status, never.exception.code), (404, "ui_action"), "an id the view never offered stays 404")
        stale = {**self.request(), "artifactRevision": 2}
        with self.assertRaises(AlphaError) as old:
            self.run_action(self.script(), request=stale)
        self.assertEqual(old.exception.code, "ui_revision_stale")
        self.assertEqual(self.executed, [])

    # --- outcomes --------------------------------------------------------------------------------------------------------------
    def test_an_applied_change_is_stored_in_the_same_transaction_with_its_receipt(self):
        cur = self.script()
        result = self.run_action(cur)
        self.assertEqual(result["outcome"], "applied")
        self.assertTrue(result["verified"])
        self.assertEqual(result["idempotencyKey"], KEY)
        order = [s.split(" ")[0] + " " + s.split(" ")[1] for s, _ in cur.statements]
        self.assertLess(order.index("UPDATE public.pr_ui_activations"), order.index("INSERT INTO"))
        self.assertIn("SAVEPOINT ui_action_command", [s for s, _ in cur.statements])
        done = cur.ran("UPDATE public.pr_ui_actions SET state='done'")
        self.assertEqual(len(done), 1)

    def test_a_domain_refusal_is_rolled_back_and_stored_as_its_outcome(self):
        self.outcome = AlphaError("The draft changed.", 409, code="draft_revision_conflict")
        cur = self.script()
        result = self.run_action(cur)
        self.assertEqual(result["outcome"], "conflict")
        self.assertFalse(result["verified"])
        self.assertIn("ROLLBACK TO SAVEPOINT ui_action_command", [s for s, _ in cur.statements])
        self.assertEqual(len(cur.ran("UPDATE public.pr_ui_actions SET state='done'")), 1)

    def test_verified_comes_only_from_an_applied_re_read_and_prepared_is_never_applied(self):
        self.outcome = ui_domain.Receipt(outcome="failed", verified=True)
        self.assertFalse(self.run_action(self.script())["verified"])
        self.outcome = ui_domain.Receipt(outcome="applied", verified=True)
        with self.assertRaises(AlphaError) as shape:
            self.run_action(self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version":
                                           self.activation_row(action="t_prepare")}), request=self.request("t_prepare"))
        self.assertEqual(shape.exception.code, "ui_action_shape")
        self.outcome = ui_domain.Receipt(outcome="prepared", verified=True, proposal_ref="p1")
        prepared = self.run_action(self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version":
                                                  self.activation_row(action="t_prepare")}), request=self.request("t_prepare"))
        self.assertEqual((prepared["outcome"], prepared["verified"], prepared["proposalRef"]), ("prepared", False, "p1"))

    def test_a_second_tab_preparing_the_same_thing_gets_the_first_result(self):
        first = {"actionId": "t_prepare", "idempotencyKey": "k_first_000000000000", "outcome": "prepared", "verified": False, "proposalRef": "p1", "nextContext": {}}
        cur = self.script(**{"SELECT idempotency_key,outcome FROM public.pr_ui_actions": ("k_first_000000000000", json.dumps(first)),
                             "SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version": self.activation_row(action="t_prepare")})
        result = self.run_action(cur, request=self.request("t_prepare"))
        self.assertEqual(self.executed, [])
        self.assertEqual(result["proposalRef"], "p1")
        self.assertEqual(result["idempotencyKey"], KEY)
        self.assertEqual(result["nextContext"]["sameAs"], "k_first_000000000000")
        self.assertEqual(len(cur.ran("UPDATE public.pr_ui_activations")), 1, "the second tab's activation is consumed too")

    def test_a_paid_two_phase_action_is_deferred_outside_the_lock(self):
        cur = self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,binding_version": self.activation_row(action="t_paid")})
        deferred = self.run_action(cur, request=self.request("t_paid"))
        self.assertIsInstance(deferred, ui_actions.Deferred)
        self.assertFalse(deferred.reconcile)
        self.assertEqual(self.executed, [], "nothing paid runs while the workspace row is locked")
        self.assertEqual(len(cur.ran("INSERT INTO public.pr_ui_actions")), 1)
        pending = self.script(**{"SELECT principal::text,artifact_id::text,artifact_revision,action_id,input_digest,activation_id,state,outcome":
                                 (ME, ART, 3, "t_paid", ui_contracts.input_digest("t_paid", {"text": "hello"}), ACT, "pending", None)})
        again = self.run_action(pending, request=self.request("t_paid"))
        self.assertTrue(isinstance(again, ui_actions.Deferred) and again.reconcile, "a retry reconciles; it never calls the provider again")

    # --- NC18: a view this build cannot draw has no controls ------------------------------------------------------------
    def test_an_unsupported_library_version_is_refused_before_anything_runs(self):
        old = "e" * 64
        supported = {"workspace": {"a" * 64}, "founder": set()}
        artifact = {**self.artifact, "library_hash": old, "scope": "workspace"}
        for name, call in (("activate", lambda cur: ui_actions.activate_ui_action(cur, auth(), artifact, self.manifest,
                                                                                   {"artifactRevision": 3, "actionId": "t_edit", "inputs": {"text": "hello"}},
                                                                                   runtime=SimpleNamespace(service=SimpleNamespace()), supported=supported)),
                           ("execute", lambda cur: ui_actions.execute_ui_action(cur, auth(), artifact, self.manifest, self.request(),
                                                                                runtime=SimpleNamespace(service=SimpleNamespace()), supported=supported)),
                           ("execute_paid", lambda cur: ui_actions.execute_ui_action(cur, auth(), artifact, self.manifest, self.request("t_paid"),
                                                                                     runtime=SimpleNamespace(service=SimpleNamespace()), supported=supported))):
            with self.subTest(call=name):
                cur = self.script()
                with self.assertRaises(AlphaError) as refused:
                    call(cur)
                self.assertEqual((refused.exception.status, refused.exception.code), (409, "library_unsupported"))
                self.assertEqual(cur.statements, [], "no throttle, activation, receipt, savepoint or domain statement")
        self.assertEqual(self.executed, [])

    def test_a_supported_or_compatible_library_version_proceeds(self):
        current, compatible = "a" * 64, "b" * 64
        supported = {"workspace": {current, compatible}, "founder": set()}
        for library_hash in (current, compatible, ""):
            with self.subTest(library_hash=library_hash or "legacy"):
                artifact = {**self.artifact, "library_hash": library_hash, "scope": "workspace"}
                result = ui_actions.execute_ui_action(self.script(), auth(), artifact, self.manifest, self.request(),
                                                      runtime=SimpleNamespace(service=SimpleNamespace()), supported=supported)
                self.assertEqual(result["outcome"], "applied")
        founder_only = {"workspace": set(), "founder": {current}}
        with self.assertRaises(AlphaError) as other_scope:
            ui_actions.execute_ui_action(self.script(), auth(), {**self.artifact, "library_hash": current, "scope": "workspace"}, self.manifest, self.request(),
                                         runtime=SimpleNamespace(service=SimpleNamespace()), supported=founder_only)
        self.assertEqual(other_scope.exception.code, "library_unsupported", "a founder library hash never draws a consumer view")

    def test_the_rule_is_the_shared_store_rule(self):
        from postriff_phase2.agent_runtime_v2 import ui_store
        calls = []
        original = ui_store.compatibility

        def spy(record, supported=None):
            calls.append(record)
            return original(record, supported)
        ui_store.compatibility = spy
        try:
            ui_actions.execute_ui_action(self.script(), auth(), {**self.artifact, "library_hash": "a" * 64, "scope": "workspace"}, self.manifest, self.request(),
                                         runtime=SimpleNamespace(service=SimpleNamespace()), supported={"workspace": {"a" * 64}, "founder": set()})
        finally:
            ui_store.compatibility = original
        self.assertEqual(calls, [{"revision": 3, "libraryHash": "a" * 64, "scope": "workspace"}])

    def test_the_supported_set_is_cached_until_the_assets_or_the_override_change(self):
        import os
        from postriff_phase2.agent_runtime_v2 import ui_store
        reads = []
        original = ui_store.supported_library_hashes
        ui_store.supported_library_hashes = lambda *a, **k: reads.append(1) or original(*a, **k)
        previous = os.environ.get("RAFII_GENUI_COMPATIBLE_LIBRARIES")
        ui_capabilities._SUPPORTED[:] = [None, None]
        try:
            os.environ["RAFII_GENUI_COMPATIBLE_LIBRARIES"] = "c" * 64
            for _ in range(5):
                self.assertIn("c" * 64, ui_capabilities.supported_hashes()["workspace"])
            self.assertEqual(len(reads), 1)
            os.environ["RAFII_GENUI_COMPATIBLE_LIBRARIES"] = "d" * 64
            self.assertIn("d" * 64, ui_capabilities.supported_hashes()["workspace"])
            self.assertEqual(len(reads), 2)
        finally:
            ui_store.supported_library_hashes = original
            ui_capabilities._SUPPORTED[:] = [None, None]
            if previous is None:
                os.environ.pop("RAFII_GENUI_COMPATIBLE_LIBRARIES", None)
            else:
                os.environ["RAFII_GENUI_COMPATIBLE_LIBRARIES"] = previous

    def test_activation_copy_is_server_built_and_bounded(self):
        cur = self.script()
        out = ui_actions.activate_ui_action(cur, auth(), self.artifact, self.manifest, {"artifactRevision": 3, "actionId": "t_edit", "inputs": {"text": "hello"}},
                                            runtime=SimpleNamespace(service=SimpleNamespace()))
        self.assertTrue(ui_contracts.valid_activation_id(out["activationId"]))
        self.assertEqual(out["inputDigest"], ui_contracts.input_digest("t_edit", {"text": "hello"}))
        self.assertEqual(set(out["confirmation"]), {"required", "title", "summary", "target", "timeZone", "cost"})
        self.assertIn("ROLLBACK TO SAVEPOINT ui_activation_read", [s for s, _ in cur.statements], "building the copy changes nothing")
        stored = cur.ran("INSERT INTO public.pr_ui_activations")
        self.assertEqual(len(stored), 1)


class VoiceChoiceTest(unittest.TestCase):
    """D-A20: the voice the person chose reaches every writing call of the turn, like the writer."""

    def ctx(self, choice):
        return SimpleNamespace(voice_choice=choice)

    def test_choice_is_forwarded_exactly(self):
        base = {"text": "", "idea": "x"}
        self.assertEqual(domain_tools._with_voice_choice(self.ctx(None), base), base)
        self.assertEqual(domain_tools._with_voice_choice(self.ctx({"mode": "neutral", "sourceIds": ["s1"]}), base), {**base, "voiceMode": "neutral"})
        self.assertEqual(domain_tools._with_voice_choice(self.ctx({"mode": "personalized", "sourceIds": ["s1", "s2"]}), base),
                         {**base, "voiceMode": "personalized", "voiceSourceIds": ["s1", "s2"]})
        self.assertEqual(domain_tools._with_voice_choice(self.ctx({"mode": None, "sourceIds": ["s1"]}), base), {**base, "voiceMode": "personalized", "voiceSourceIds": ["s1"]})
        self.assertEqual(domain_tools._with_voice_choice(self.ctx({"mode": "shouting", "sourceIds": []}), base), base)
        self.assertEqual(domain_tools._with_voice_choice(self.ctx({"mode": "personalized", "sourceIds": []}), base), {**base, "voiceMode": "personalized"})

    def test_the_writing_call_carries_it(self):
        sent = []

        class Ideas:
            def turn(self, workspace_id, token, conversation_id, request):
                sent.append(request)
                return {"runId": "run-1"}

            def events(self, workspace_id, token, run_id):
                return {"status": "completed", "artifactHash": "h"}

            def apply(self, *args, **kwargs):
                return None

        repository = SimpleNamespace(get=lambda w, t: {"revision": 1, "state": {}})
        ctx = SimpleNamespace(service=SimpleNamespace(ideas=Ideas(), repository=repository), workspace_id=WS, token="t", conversation_id="c", writer_model="writer-x",
                              voice_choice={"mode": "personalized", "sourceIds": ["s1"]}, chip_fields={}, chips_forwarded=True, check_cancelled=lambda: None,
                              snapshot=lambda: {"state": {}}, ledger=SimpleNamespace(facts=[]))
        domain_tools._writing_run(ctx, {"text": "", "idea": "x"}, separate=True)
        self.assertEqual(sent[0]["model"], "writer-x")
        self.assertEqual(sent[0]["voiceMode"], "personalized")
        self.assertEqual(sent[0]["voiceSourceIds"], ["s1"])


if __name__ == "__main__":
    unittest.main()

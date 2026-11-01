"""Product event taxonomy (CONTRACTS §8.C, PRD §8.6) without a database: the best-effort writer, the state-diff effect
and every call site, each with a fake connection or repository.

Covered: ids/enums only (content is dropped before SQL), dedupe keys `<event>:<entity id>:<version>`, one SAVEPOINT per
batch, failure isolation (a failing event write never fails or rolls back the customer's own writes), the ten-minute
'not installed yet' back-off logged once by exception class, the repository effect, and the call sites in hosted
bootstrap, OAuth connect/disconnect/provider revocation, the publishing worker, automation runs, web research, the
research broker and the humanizer quality checks."""
import copy
import hashlib
import json
import sys
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import product_events as pe  # noqa: E402
from postriff_phase2.contracts import digest  # noqa: E402

WS = "00000000-0000-0000-0000-0000000000aa"
USER = "00000000-0000-0000-0000-000000000001"
RUN = "00000000-0000-0000-0000-0000000000bb"
TXN = "00000000-0000-0000-0000-0000000000cc"
NOW = 1_800_000_000.0
V1, V2, J1 = "a" * 32, "b" * 32, "c" * 32


class UndefinedTable(Exception):
    """Named like psycopg.errors.UndefinedTable: record() classifies failures by exception class name."""


class CheckViolation(Exception):
    pass


class Script:
    """A fake DB-API connection and cursor in one: records statements, answers reads from (substring -> rows) rules,
    raises on a configured statement, and models SAVEPOINT / ROLLBACK TO SAVEPOINT / RELEASE and commit so a test can
    see exactly which writes would persist."""

    def __init__(self, answers=(), fail=None):
        self.answers, self.fail = list(answers), fail
        self.statements, self.pending, self.committed, self.marks = [], [], [], {}
        self.rows, self.rowcount = [], 0

    def __enter__(self):
        return self

    def __exit__(self, kind, *_):
        if kind is None:
            self.commit()
        return False

    def cursor(self):
        return self

    def commit(self):
        self.committed.extend(self.pending)
        self.pending = []

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.statements.append((text, params))
        if self.fail and self.fail[0] in text:
            raise self.fail[1]
        if text.startswith("SAVEPOINT "):
            self.marks[text.split()[1]] = len(self.pending)
            return
        if text.startswith("ROLLBACK TO SAVEPOINT "):
            del self.pending[self.marks[text.split()[-1]]:]
            return
        if text.startswith("RELEASE SAVEPOINT "):
            self.marks.pop(text.split()[-1], None)
            return
        if not text.startswith("SELECT"):
            self.pending.append((text, params))
        rule = next((rows for key, rows in self.answers if key in text), None)
        self.rows = list(rule(params) if callable(rule) else rule or [])
        self.rowcount = len(params) // 5 if text.startswith("INSERT INTO public.pr_product_events") else 1

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    # -- helpers for assertions ---------------------------------------------------------------------------------------
    def events(self, committed=False):
        """[(event, dedupe, properties, user)] of product-event inserts (all statements, or only what would commit)."""
        source = self.committed if committed else [(text, params) for text, params in self.statements]
        out = []
        for text, params in source:
            if text.startswith("INSERT INTO public.pr_product_events"):
                for offset in range(0, len(params), 5):
                    workspace, user, event, properties, dedupe = params[offset:offset + 5]
                    out.append((event, dedupe, json.loads(properties), user))
        return out


def reset_writer():
    pe.reset()


class WriterTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def test_rows_carry_ids_and_enums_only(self):
        row = pe.row(WS, USER, "draft.created", V1, 1, {"feature": "agent", "voice": "Personalized voice!", "text": "My secret draft"})
        self.assertEqual(row, (WS, USER, "draft.created", '{"feature":"agent"}', f"draft.created:{V1}:1"))
        self.assertEqual(json.loads(pe.row(WS, None, "post.scheduled", J1, 1, {"platform": "Google Business Profile", "via": "person"})[3]),
                         {"platform": "Google Business Profile", "via": "person"})
        self.assertEqual(json.loads(pe.row(WS, None, "research.completed", "req-1", 1, {"source": "https://example.com/x", "outcome": "a@b.c"})[3]), {})
        self.assertIsNone(pe.row("workspace", USER, "draft.created", V1, 1), "workspace ids must be UUIDs")
        self.assertIsNone(pe.row(WS, USER, "draft.typed", V1, 1), "only taxonomy events")
        self.assertIsNone(pe.row(WS, USER, "draft.created", "has space", 1))
        self.assertIsNone(pe.row(WS, USER, "draft.created", V1, True), "a boolean is not a version")
        self.assertIsNone(pe.row(WS, "not-a-uuid", "voice.created", V1, 2)[1], "an invalid person id is dropped, the event is kept")
        long_entity = "x" * 119
        dedupe = pe.row(WS, USER, "automation.run_completed", long_entity, "source_unavailable", {"outcome": "source_unavailable"})[4]
        self.assertLessEqual(len(dedupe), 200)

    def test_one_insert_behind_one_savepoint(self):
        cur = Script()
        self.assertEqual(pe.record_many(cur, WS, USER, [("voice.created", V1, 3, {}), ("brand.created", V2, 1, None)]), 2)
        kinds = [text.split(" ")[0] + (" TO" if text.startswith("ROLLBACK") else "") for text, _ in cur.statements]
        self.assertEqual(kinds, ["SAVEPOINT", "INSERT", "RELEASE", "SAVEPOINT", "INSERT", "RELEASE"])
        journal = json.loads(cur.statements[4][1][2])
        self.assertEqual((journal['attempted'], journal['recorded'], journal['state'], journal['rows']), (2, 2, 'recorded', []))
        insert = cur.statements[1][0]
        self.assertTrue(insert.startswith("INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key) VALUES"))
        self.assertTrue(insert.endswith("ON CONFLICT DO NOTHING"))
        self.assertEqual([e[:2] for e in cur.events()], [("voice.created", f"voice.created:{V1}:3"), ("brand.created", f"brand.created:{V2}:1")])

    def test_a_failing_event_write_leaves_the_customer_write_committed_and_returns_normally(self):
        """Coordinator rule 1: the event insert fails inside the customer's transaction; only its savepoint rolls back."""
        cur = Script(fail=("pr_product_events", RuntimeError("boom")))
        cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind) VALUES(%s,%s,%s)", (WS, USER, "workspace.created"))
        with self.assertLogs("postriff.product_events", "WARNING"):
            self.assertFalse(pe.record(cur, WS, USER, "workspace.created", WS, 1, {"plan": "studio"}))
        cur.execute("UPDATE public.pr_workspaces SET revision=revision+1 WHERE id=%s", (WS,))
        cur.commit()
        self.assertEqual([text.split(" ")[0] + " " + text.split(" ")[2] for text, _ in cur.committed], ["INSERT public.pr_audit_events(workspace_id,actor,kind)", "INSERT public.pr_audit_events(workspace_id,actor,kind,subject,meta)", "UPDATE SET"])
        journal = json.loads(cur.committed[1][1][2])
        self.assertEqual((journal['state'], journal['recoverable'], journal['errorClass']), ('failed', True, 'RuntimeError'))
        self.assertEqual(journal['rows'][0][2], 'workspace.created')
        self.assertTrue(any(text.startswith("ROLLBACK TO SAVEPOINT product_event_") for text, _ in cur.statements))
        self.assertEqual(cur.events(committed=True), [])

    def test_not_installed_is_logged_once_and_skipped_for_ten_minutes(self):
        clock = [100.0]
        with mock.patch.object(pe, "_clock", lambda: clock[0]):
            for error in (UndefinedTable("relation \"public.pr_product_events\" does not exist"), CheckViolation("violates check")):
                reset_writer()
                cur = Script(fail=("pr_product_events", error))
                with self.assertLogs("postriff.product_events", "WARNING") as logs:
                    self.assertFalse(pe.record(cur, WS, USER, "voice.created", V1, 1))
                self.assertEqual(len(logs.output), 1)
                self.assertIn(type(error).__name__, logs.output[0])
                self.assertNotIn("pr_product_events", logs.output[0], "the class name only, never the message or SQL")
                self.assertNotIn(WS, logs.output[0])
                quiet = Script()
                self.assertFalse(pe.record(quiet, WS, USER, "voice.created", V1, 1))
                self.assertFalse(any('INSERT INTO public.pr_product_events' in sql for sql, _ in quiet.statements))
                self.assertEqual(json.loads(quiet.statements[1][1][2])['state'], 'suspended')
                self.assertEqual(pe.capture(quiet, WS, {}, {"speaker": {"id": V1, "activeRevision": 1}}, USER), 0)
                self.assertFalse(any('INSERT INTO public.pr_product_events' in sql for sql, _ in quiet.statements))
                clock[0] += pe.SUSPEND_SECONDS - 1
                self.assertFalse(pe.record(quiet, WS, USER, "voice.created", V1, 1))
                self.assertFalse(any('INSERT INTO public.pr_product_events' in sql for sql, _ in quiet.statements))
                clock[0] += 2
                second = Script(fail=("pr_product_events", type(error)("again")))
                with self.assertNoLogs("postriff.product_events", "WARNING"):
                    self.assertFalse(pe.record(second, WS, USER, "voice.created", V1, 1))   # tried again; logged once per process
                self.assertTrue(any(text.startswith("INSERT") for text, _ in second.statements))
                clock[0] += pe.SUSPEND_SECONDS + 1

    def test_other_failures_are_logged_and_never_suspend(self):
        with self.assertLogs("postriff.product_events", "WARNING") as logs:
            self.assertFalse(pe.record(Script(fail=("pr_product_events", RuntimeError("password=secret"))), WS, USER, "voice.created", V1, 1))
        self.assertNotIn("secret", "".join(logs.output))
        later = Script()
        self.assertTrue(pe.record(later, WS, USER, "voice.created", V1, 1))
        self.assertTrue(any(text.startswith("INSERT") for text, _ in later.statements))

    def test_malformed_calls_and_duplicate_keys_never_raise(self):
        cur = Script()
        self.assertEqual(pe.record_many(cur, WS, USER, [("voice.created", V1, 1, ["not", "a", "dict"]), ("voice.created", V1, 1, {})]), 1)
        self.assertEqual(len(cur.events()), 1, 'one row per (event, dedupe key) in a batch')
        with self.assertLogs("postriff.product_events", "WARNING"):
            self.assertEqual(pe.record_many(Script(), WS, USER, [("voice.created",)]), 0)
            self.assertEqual(pe.record_many(Script(), WS, USER, None), 0)

    def test_an_already_broken_transaction_is_reported_not_raised(self):
        with self.assertLogs("postriff.product_events", "WARNING"):
            self.assertFalse(pe.record(Script(fail=("SAVEPOINT", RuntimeError("current transaction is aborted"))), WS, USER, "voice.created", V1, 1))
        self.assertEqual(pe.record_many(Script(), WS, USER, []), 0)


# --- state-backed events (repository effect) --------------------------------------------------------------------------

def variant(identifier, revision=1, origin="ideas-candidate", **extra):
    return {"id": identifier, "revision": revision, "text": "The draft text that must never leave the workspace.",
            "revisions": [{"revision": number, "origin": origin if number == revision else "ideas-candidate", "text": "t"} for number in range(1, revision + 1)],
            "provenance": {"runId": RUN}, "sourceIds": [], "voiceBindings": [], **extra}


def manifest(variant_id=V1, revision=1, platform="LinkedIn"):
    return {"variantId": variant_id, "contentRevision": revision, "platform": platform, "channelId": "c" * 32, "actor": USER}


class DeriveTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def test_voice_brand_reviews_jobs_campaigns_automations_and_suggestions(self):
        before = {"speaker": {"id": "s" * 32, "activeRevision": None}, "brandHub": {"id": "h" * 32, "mode": ""},
                  "phase2": {"reviews": [{"id": "r1", "status": "needs_review", "manifest": manifest()}], "jobs": []},
                  "raffi": {"campaignPlanning": {"campaigns": [], "recurringTasks": [], "occurrences": [
                      {"id": "o1", "items": [{"key": "k1", "state": "ready_for_review", "variantId": V2}]}]},
                            "suggestions": [{"id": "g1", "kind": "unused_asset", "status": "open"}]}}
        after = copy.deepcopy(before)
        after["speaker"]["activeRevision"] = 2
        after["brandHub"]["mode"] = "business"
        after["phase2"]["reviews"][0].update(status="approved", jobId=J1)
        after["phase2"]["reviews"].append({"id": "r2", "status": "approved", "jobId": "d" * 32, "manifest": manifest(V2, 4)})
        after["phase2"]["jobs"] = [{"id": J1, "manifest": manifest()}, {"id": "d" * 32, "manifest": manifest(V2, 4, "Threads"), "automation": {"approvedVia": "owner_preauthorization"}}]
        planning = after["raffi"]["campaignPlanning"]
        planning["occurrences"][0]["items"][0].update(state="approved", approvedVia="human", decision={"decision": "approve", "variantRevision": 5})
        planning["campaigns"] = [{"id": "camp1", "kind": "campaign"}, {"id": "camp2", "kind": "automation"}]
        planning["recurringTasks"] = [{"id": "task1", "schedule": {"kind": "weekly"}}, {"id": "task2", "schedule": {"kind": "once"}}]
        after["raffi"]["suggestions"][0]["status"] = "accepted"
        after["raffi"]["suggestions"].append({"id": "g2", "kind": "held_draft", "status": "open"})
        events = {(event, str(entity), str(version)): props for event, entity, version, props in pe.state_events(WS, before, after)}
        self.assertEqual(events, {
            ("voice.created", "s" * 32, "2"): {},
            ("brand.created", "h" * 32, "1"): {},
            ("review.approved", V1, "1"): {"surface": "queue"},
            ("review.approved", V2, "5"): {"surface": "automation"},          # a person approved the automation post
            ("post.scheduled", J1, "1"): {"platform": "LinkedIn", "via": "person"},
            ("post.scheduled", "d" * 32, "1"): {"platform": "Threads", "via": "standing"},
            ("campaign.created", "camp1", "1"): {},                            # an automation's own brief is not a campaign
            ("automation.created", "task1", "1"): {"schedule": "weekly"},      # a one-time post is not an automation
            ("suggestion.accepted", "g1", "1"): {"kind": "unused_asset"},
            ("suggestion.shown", "g2", "1"): {"kind": "held_draft"},
        })
        self.assertEqual(pe.state_events(WS, after, after), [], "an unchanged state implies nothing")

    def test_draft_changes_and_their_features(self):
        before = {"variants": [variant(V1), variant(V2)], "sources": [{"id": "src-q", "origin": {"kind": "quick_start"}}]}
        after = copy.deepcopy(before)
        after["variants"][0] = variant(V1, 2, "author-edit")
        after["variants"][1]["rejected"] = True
        after["variants"] += [variant("e" * 32, automation={"taskId": "t"}), variant("f" * 32, sourceIds=["src-q"]),
                              variant("9" * 32, voiceBindings=[{"id": "vs"}]), variant("8" * 32, provenance={"runId": None})]
        changes = [(event, item["id"], version) for event, item, version in pe.draft_changes(before, after)]
        self.assertEqual(changes, [("draft.edited", V1, 2), ("draft.discarded", V2, 1), ("draft.created", "e" * 32, 1), ("draft.created", "f" * 32, 1),
                                   ("draft.created", "9" * 32, 1), ("draft.created", "8" * 32, 1)])
        features = {item["id"]: pe.draft_feature(after, item) for _, item, _ in pe.draft_changes(before, after)}
        self.assertEqual(features, {V1: "writer", V2: "writer", "e" * 32: "automation", "f" * 32: "quick_start", "9" * 32: "write_like_me", "8" * 32: "writer"})
        agent_run = {RUN: {"prefix": "agent-draft", "quickStart": False}}
        self.assertEqual(pe.draft_feature(after, after["variants"][4], agent_run), "agent")
        self.assertEqual(pe.draft_feature(after, after["variants"][0], {RUN: {"prefix": "run", "quickStart": True}}), "quick_start")
        regenerated = copy.deepcopy(after)
        regenerated["variants"][0] = variant(V1, 3, "accepted-fixture-replacement")
        self.assertEqual([event for event, _, _ in pe.draft_changes(after, regenerated)], [], "only a person's own edit is draft.edited")

    def test_capture_writes_one_batch_with_one_run_lookup_and_no_text(self):
        before = {"variants": []}
        after = {"variants": [variant(V1, voiceBindings=[{"id": "vs"}]), variant(V2)], "speaker": {"id": "s" * 32, "activeRevision": 1}}
        cur = Script(answers=[("FROM public.pr_agent_runs", [(RUN, "agent-draft", False)])])
        self.assertEqual(pe.capture(cur, WS, before, after, USER), 3)
        selects = [text for text, _ in cur.statements if text.startswith("SELECT")]
        self.assertEqual(len(selects), 1)
        self.assertIn("id=ANY(%s::uuid[])", selects[0])
        events = sorted(cur.events())
        self.assertEqual(events, sorted([("voice.created", f"voice.created:{'s' * 32}:1", {}, USER),
                                         ("draft.created", f"draft.created:{V1}:1", {"feature": "agent", "voice": "personalized"}, USER),
                                         ("draft.created", f"draft.created:{V2}:1", {"feature": "agent", "voice": "neutral"}, USER)]))
        self.assertNotIn("draft text", json.dumps([params for _, params in cur.statements], default=str))

    def test_capture_costs_nothing_when_nothing_changed_and_never_raises(self):
        quiet = Script()
        state = {"variants": [variant(V1)], "speaker": {"id": "s", "activeRevision": 1}}
        self.assertEqual(pe.capture(quiet, WS, state, copy.deepcopy(state), USER), 0)
        self.assertEqual(quiet.statements, [])
        # Malformed shapes are skipped, not raised: only the well-formed job is recorded.
        self.assertEqual(pe.capture(quiet, WS, {}, {"variants": "not-a-list", "speaker": "broken", "phase2": {"jobs": [{"id": J1, "manifest": "x"}]},
                                                    "raffi": {"campaignPlanning": {"occurrences": [{"id": "o", "items": ["bad"]}]}}}, USER), 1)
        self.assertEqual([event for event, *_ in quiet.events()], ["post.scheduled"])
        broken = mock.patch.object(pe, "state_events", side_effect=KeyError("boom"))
        with broken, self.assertLogs("postriff.product_events", "WARNING") as logs:
            self.assertEqual(pe.capture(Script(), WS, {}, {}, USER), 0)
        self.assertIn("capture_failed", logs.output[0])
        sample = Script()
        self.assertEqual(pe.capture(sample, WS, {}, {"workspace": {"sample": True}, "speaker": {"activeRevision": 1}}, USER), 0)
        self.assertEqual(sample.statements, [])

    def test_a_failing_run_lookup_still_records_the_drafts(self):
        cur = Script(fail=("FROM public.pr_agent_runs", RuntimeError("timeout")))
        with self.assertLogs("postriff.product_events", "WARNING"):
            pe.capture(cur, WS, {"variants": []}, {"variants": [variant(V1)]}, USER)
        self.assertEqual([(event, props) for event, _, props, _ in cur.events()], [("draft.created", {"feature": "writer", "voice": "neutral"})])


# --- call sites --------------------------------------------------------------------------------------------------------

class Repository:
    """The slice of PostgresWorkspaceRepository the call sites use, over one Script connection."""

    def __init__(self, script, state):
        self.script, self.state, self.revision = script, state, 1

    @contextmanager
    def transaction(self, token, workspace_id, **_):
        yield self.script, (self.revision, self.state, "owner", True, True, True, True), USER
        self.script.commit()   # like the real repository: the transaction commits when its block ends normally

    def get(self, workspace_id, token):
        return {"state": copy.deepcopy(self.state), "revision": self.revision}

    def command(self, workspace_id, token, revision, command, requirement="edit", after=None, **_):
        self.state = command(copy.deepcopy(self.state), USER)
        self.revision += 1
        if after:
            after(self.script, self.state, USER)
        self.script.commit()
        return {"state": self.state, "revision": self.revision}

    def mutate(self, *args, **kwargs):
        raise AlphaError("Channel unavailable.", 404)

    def assert_fresh(self, token, principal):
        return None

    @property
    def connection_factory(self):
        return lambda: self.script


class HostedCallSiteTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def bootstrap(self, state):
        from postriff_phase2.hosted import HostedWorkspaceService
        script = Script(answers=[("pr_auth_throttle", [(1,)]), ("SELECT public.pr_bootstrap", [(WS,)]),
                                 ("SELECT w.revision,w.state", [(1, state, "studio", NOW, NOW + 86400, 10, 0, 3, "owner", True, True, True, True)])])
        service = HostedWorkspaceService.__new__(HostedWorkspaceService)
        service.connection_factory, service.verify_session, service.public_base_url = (lambda: script), (lambda token: USER), ""
        service.commands = SimpleNamespace(present=lambda saved, revision: {"revision": revision})
        result = service.bootstrap("token", "studio")
        return script, result

    def test_bootstrap_records_workspace_created_once(self):
        script, result = self.bootstrap({})
        self.assertEqual(result["workspaceId"], WS)
        self.assertEqual(script.events(committed=True), [("workspace.created", f"workspace.created:{WS}:1", {"plan": "studio"}, USER)])
        replay, _ = self.bootstrap({"phase2": {}})
        self.assertEqual(replay.events(), [], "a returning person's existing workspace is not a new signup")

    def test_the_hosted_service_registers_the_effect_after_time_back(self):
        from postriff_phase2.hosted import HostedWorkspaceService
        service = HostedWorkspaceService(lambda: Script(), lambda token: USER, clock=lambda: NOW)
        effects = service.repository.effects
        self.assertIn(pe.capture, effects)
        self.assertGreater(effects.index(pe.capture), effects.index(service.time_savings.capture))


class Adapter:
    platform, capability_version, assisted_fallback, production_reviewed, native_schedule = "Mastodon", 1, True, False, False

    def capability_scopes(self, capability):
        return ["write"] if capability in ("publish", "schedule") else []

    def exchange(self, code, verifier, redirect):
        return {"accessToken": "AT", "scopes": ["write"], "expiresIn": 3600}

    def identity(self, access):
        return {"providerAccountId": "acct-1", "handle": "@me"}

    def capability_scopes(self, capability):
        return ["write"] if capability == "publish" else []

    def revoke(self, token):
        return True


class OAuthCallSiteTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def service(self, script, state):
        from postriff_phase2.hosted import HostedPhase2Commands
        from postriff_phase2.oauth import CredentialVault, OAuthService
        self.vault = CredentialVault(CredentialVault.generate_key())
        return OAuthService(Repository(script, state), HostedPhase2Commands(lambda: NOW), self.vault, {"mastodon": Adapter()}, "https://app.example", clock=lambda: NOW)

    @mock.patch("postriff_phase2.billing.require_plan_capacity", lambda *a, **k: None)
    def test_a_completed_connect_flow_records_channel_connected_with_its_transaction(self):
        from postriff_phase2.auth import initial_phase2_state
        script = Script()
        service = self.service(script, initial_phase2_state(WS, USER, "Owner", "studio", NOW))
        ciphertext, key_id = self.vault.encrypt("verifier")
        script.answers = [("FROM public.pr_oauth_transactions WHERE state_hash", [(TXN, USER, "mastodon", "publish", "https://app.example/cb", ["write"], ciphertext, key_id, NOW + 600, False)])]
        result = service.complete(WS, "token", "mastodon", "s" * 32, "CODE")
        connection = hashlib.sha256(b"mastodon:acct-1").hexdigest()[:32]
        self.assertEqual(result["connectionId"], connection)
        self.assertEqual(script.events(), [("channel.connected", f"channel.connected:{connection}:{TXN}", {"provider": "mastodon"}, USER)])

    def test_a_disconnect_records_channel_disconnected_paired_with_its_connection(self):
        from postriff_phase2.auth import initial_phase2_state
        state = initial_phase2_state(WS, USER, "Owner", "studio", NOW)
        connection = "f" * 32
        state["phase2"]["channels"].append({"id": connection, "platform": "Mastodon", "verifiedAt": NOW - 500.7})
        script = Script()
        service = self.service(script, state)
        ciphertext, key_id = self.vault.encrypt("AT")
        script.answers = [("SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials", [("mastodon", ciphertext, key_id)])]
        with mock.patch("postriff_phase2.growth.history_import.mark_for_purge", lambda *a: None), \
             mock.patch("postriff_phase2.growth.history_import.purge_after_disconnect", lambda *a: None):
            result = service.disconnect(WS, "token", connection)
        self.assertTrue(result["disconnected"])
        self.assertEqual(script.events(), [("channel.disconnected", f"channel.disconnected:{connection}:{int(NOW - 500.7)}", {"provider": "mastodon", "cause": "member"}, USER)])

    def test_a_provider_revocation_records_a_disconnection_nobody_chose(self):
        from postriff_phase2.hosted import HostedPhase2Commands
        from postriff_phase2.oauth import CredentialVault, OAuthService
        connection = "e" * 32
        state = {"phase2": {"channels": [{"id": connection, "platform": "Xiaohongshu", "verifiedAt": NOW - 60}], "reviews": [], "jobs": [], "trial": {"expiresAt": NOW + 86400}}}
        script = Script(answers=[("INSERT INTO public.pr_social_provider_events", [("evt-1",)]),
                                 ("FROM public.pr_encrypted_credentials WHERE provider='xiaohongshu'", [(WS, connection)]),
                                 ("SELECT state FROM public.pr_workspaces", [(json.dumps(state),)])])
        commands = HostedPhase2Commands(lambda: NOW)
        commands.engine.invalidate = lambda state: None
        adapter = SimpleNamespace(webhook_secret="secret", client_id="app-1")
        service = OAuthService(Repository(script, state), commands, CredentialVault(CredentialVault.generate_key()), {"xiaohongshu": adapter}, "https://app.example", clock=lambda: NOW)
        stamp = str(int(NOW * 1000))
        raw = json.dumps({"event_id": "evt-1", "event_type": "authorization_revoked", "event_time": int(stamp), "app_id": "app-1", "open_id": "open-1"}).encode()
        with mock.patch("postriff_phase2.wave4c_connectors.verify_xiaohongshu_webhook", lambda *a, **k: True):
            answer = service.xiaohongshu_webhook({"timestamp": stamp, "signature": "sig", "eventId": "evt-1", "eventType": "authorization_revoked"}, raw)
        self.assertEqual(answer, {"code": 0, "msg": "success"})
        version = hashlib.sha256(b"evt-1").hexdigest()[:16]
        self.assertEqual(script.events(committed=True), [("channel.disconnected", f"channel.disconnected:{connection}:{version}", {"cause": "provider", "provider": "xiaohongshu"}, None)])


class WorkerCallSiteTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def job(self, **extra):
        job = {"id": J1, "state": "submitting", "manifest": {**manifest(), "idempotencyKey": "k", "expiresAt": NOW + 3600}, "approvedBy": USER,
               "attempts": [{"number": 1}], "events": [], "leaseOwner": "w1", "leaseId": "L", "leaseUntil": NOW + 30}
        job["approvalDigest"] = digest(job["manifest"])
        job.update(extra)
        return job

    def complete(self, result):
        from postriff_phase2.hosted_worker import PostgresWorker
        state = {"phase2": {"jobs": [self.job()], "channels": []}}
        script = Script(answers=[("SELECT revision,state FROM public.pr_workspaces", [(1, json.dumps(state))])])
        worker = PostgresWorker(lambda: script, clock=lambda: NOW, worker_id="w1")
        self.assertTrue(worker.complete({"workspaceId": WS, "job": {"id": J1, "leaseId": "L"}, "reconciliation": False}, result))
        return script

    def test_verified_and_failed_jobs_record_publish_outcomes(self):
        verified = self.complete({"state": "verified", "confirmed": "Published", "reference": "post-1", "verification": "provider_lookup"})
        self.assertEqual(verified.events(committed=True), [("publish.verified", f"publish.verified:{J1}:1", {"platform": "LinkedIn"}, USER)])
        failed = self.complete({"state": "failed", "confirmed": "Rejected by the provider", "verification": "provider_lookup"})
        self.assertEqual([event[:3] for event in failed.events(committed=True)], [("publish.failed", f"publish.failed:{J1}:1", {"platform": "LinkedIn"})])
        held = self.complete({"state": "held", "confirmed": "Permission changed"})
        self.assertEqual(held.events(), [])

    @mock.patch("postriff_phase2.billing.require_publishing", lambda *a, **k: None)
    def test_the_bounded_retry_limit_records_publish_failed(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        job = self.job(state="scheduled", attempts=[{"number": 1}, {"number": 2}, {"number": 3}], leaseOwner=None, leaseUntil=0, nextAt=0)
        state = {"phase2": {"jobs": [job], "channels": []}}
        script = Script(answers=[("pg_try_advisory_xact_lock", [(True,)]), ("SELECT to_regclass", [('pr_worker_tenants',)]), ("SELECT w.id::text,w.revision,w.state FROM public.pr_workspaces", [(WS, 1, json.dumps(state))]),
                                 ("SELECT m.role,m.can_publish", [("owner", True)])])
        worker = PostgresWorker(lambda: script, clock=lambda: NOW, worker_id="w1")
        worker.commands.engine.invalidate = lambda state: None   # the engine's approval invalidation is not under test here
        self.assertIsNone(worker.claim())
        self.assertEqual([event[:3] for event in script.events(committed=True)], [("publish.failed", f"publish.failed:{J1}:3", {"platform": "LinkedIn"})])


class AutomationAndResearchCallSiteTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def test_an_automation_run_that_ended_records_run_completed(self):
        from postriff_phase2 import automation_runs
        occurrence = "0" * 32
        state = {"raffi": {"campaignPlanning": {"campaigns": [], "recurringTasks": [{"id": "t1"}], "occurrences": [{"id": occurrence, "taskId": "t1"}]}}}
        script = Script(answers=[("SELECT state FROM pr_workspaces", lambda params: [(copy.deepcopy(state),)])])
        service = SimpleNamespace(connection_factory=lambda: script)
        with mock.patch.object(automation_runs, "sync", lambda *a: None):
            automation_runs._update_run(service, WS, occurrence, USER, lambda s, occ, task, cur: {"lifecycle": "skipped", "occurrenceId": occ["id"]})
            automation_runs._update_run(service, WS, occurrence, USER, lambda s, occ, task, cur: {"lifecycle": "drafting"})
            automation_runs._update_run(service, WS, occurrence, USER, lambda s, occ, task, cur: occ.update(runId=RUN))
        self.assertEqual(script.events(committed=True), [("automation.run_completed", f"automation.run_completed:{occurrence}:skipped", {"outcome": "skipped"}, USER)])

    def test_web_research_records_an_opaque_research_completed(self):
        from postriff_phase2 import research
        from postriff_phase2.hosted import HostedPhase2Commands
        from postriff_phase2.ideas import IdeasService
        script = Script(answers=[("FROM public.pr_conversations", [("conv", "t", USER, NOW, NOW, False)])])
        ideas = IdeasService.__new__(IdeasService)
        ideas.repository, ideas.commands, ideas.clock = Repository(script, {"sources": []}), HostedPhase2Commands(lambda: NOW), lambda: NOW
        ideas.researcher = SimpleNamespace(run=lambda message, intent: {"pages": [], "query": "q", "searched": True, "warnings": [], "elapsed": 0.1})
        with mock.patch.object(research, "allowed", lambda state: True), mock.patch.object(research, "needs_research", lambda *a, **k: True):
            added, record = ideas._research(WS, "token", {"sourceIds": []}, "What changed in the 2026 tax rules?", {"intent": "research"}, "client-key-1", "conv")
        self.assertEqual(added, [])
        entity = pe.request_entity(WS, "client-key-1")
        self.assertEqual(script.events(committed=True), [("research.completed", f"research.completed:{entity}:1", {"outcome": "empty", "source": "web"}, USER)])
        params = json.dumps([p for text, p in script.statements if "pr_product_events" in text], default=str)
        self.assertNotIn("client-key-1", params)
        self.assertNotIn("tax rules", params)


class CoworkerCallSiteTests(unittest.TestCase):
    def setUp(self):
        reset_writer()
        self.addCleanup(reset_writer)

    def coworker(self, script, state):
        from postriff_phase2.coworker.service import CoworkerService
        from postriff_phase2.ideas import IdeasService
        service = CoworkerService.__new__(CoworkerService)
        repository = Repository(script, state)
        service.hosted = SimpleNamespace(repository=repository, ideas=SimpleNamespace(_member=IdeasService._member), notifications=None, connection_factory=lambda: script,
                                         commands=None)
        service.values, service.clock = {}, lambda: NOW
        service._require = lambda flag: None
        service._require_edit = lambda workspace_id, token: None
        return service, repository

    def test_a_completed_broker_search_records_research_completed(self):
        script = Script()
        service, _ = self.coworker(script, {})
        broker = SimpleNamespace(search_items=lambda query, options: {"status": "ok", "provider": "p", "errors": [], "items": [{"snippet": "s", "provenance": {}}]})
        service._broker = lambda state: broker
        service._store_evidence = lambda *a: "e1"
        service.research_search(WS, "token", "rafii pricing")
        events = [event for event in script.events(committed=True) if event[0] == "research.completed"]
        day = time.strftime("%Y%m%d", time.gmtime(NOW))
        self.assertEqual(events, [("research.completed", f"research.completed:{pe.request_entity(WS, 'research:search:' + hashlib.sha256(b'rafii pricing').hexdigest()[:16])}:{day}",
                                   {"outcome": "found", "source": "broker"}, USER)])
        failed = Script()
        service, _ = self.coworker(failed, {})
        service._broker = lambda state: SimpleNamespace(search_items=lambda q, o: {"status": "failed", "provider": None, "errors": [{}], "items": []})
        service._store_evidence = lambda *a: "e1"
        service.research_search(WS, "token", "rafii pricing")
        self.assertEqual([event for event in failed.events() if event[0] == "research.completed"], [])

    def test_the_weekly_quality_check_records_humanizer_applied(self):
        week = {"id": "w1", "state": "generating", "weekOf": "2026-09-28", "slots": [
            {"id": "s1", "status": "drafted", "variantId": V1, "sourceIds": [], "language": "en", "platform": "LinkedIn", "goal": "g"},
            {"id": "s2", "status": "drafted", "variantId": "missing", "sourceIds": [], "language": "en", "platform": "LinkedIn", "goal": "g"}]}
        state = {"variants": [variant(V1, 2, "author-edit")], "sources": [], "coworker": {"weekly": {"recipes": [], "weeks": [week], "revision": 1}}}
        script = Script()
        service, repository = self.coworker(script, state)

        def command_as(repo, workspace_id, token, fn, requirement, audit_kind, subject, meta, after=None):
            current = copy.deepcopy(repository.state)
            result = fn(current, USER)
            repository.state = current
            if after:
                after(script, current, USER)
            script.commit()
            return result
        service._command_as = command_as
        service._quality_and_settle(WS, "token", repository, {"timeZone": "UTC"}, "w1", USER, ["s1"])
        self.assertEqual([event for event in script.events(committed=True) if event[0] == "humanizer.applied"],
                         [("humanizer.applied", f"humanizer.applied:{V1}:2", {"outcome": "ready", "surface": "weekly"}, USER)])

    def test_the_source_campaign_quality_check_records_humanizer_applied(self):
        from postriff_phase2.coworker import service as module
        artifact = {"id": "art-1", "title": "Source", "text": "Rafii launched in 2026.", "format": "text", "provenance": {}}
        brief = {"goal": "Share", "audience": "Founders", "coreMessage": "Rafii launched", "cta": None}
        record_id = "sc_" + hashlib.sha256(json.dumps([WS, artifact["id"], "Share", "Founders", None], ensure_ascii=False).encode()).hexdigest()[:12]
        record = {"id": record_id, "campaignId": "camp1", "sourceId": "src-1", "status": "drafting", "drafts": [], "destinations": []}
        state = {"variants": [variant(V1)], "sources": [], "phase2": {"channels": [{"id": "ch1", "platform": "LinkedIn", "language": "en"}]},
                 "coworker": {"sourceCampaigns": [record]}}
        script = Script(answers=[("FROM pr_agent_runs", [(RUN, "completed", "hash")])])
        service, repository = self.coworker(script, state)
        service.hosted.ideas = SimpleNamespace(_member=service.hosted.ideas._member, create_conversation=lambda *a: {"conversationId": "conv"},
                                               turn=lambda *a, **k: {"runId": RUN}, apply=lambda *a, **k: {"variantIds": [{"variantId": V1, "platform": "LinkedIn", "language": "en"}]})

        def command(workspace_id, token, fn, requirement, audit_kind, subject="", meta=None, after=None):
            current = copy.deepcopy(repository.state)
            result = fn(current, USER)
            repository.state = current
            if after:
                after(script, current, USER)
            script.commit()
            return result
        service._command, service._store_evidence = command, (lambda *a: "e1")
        pack = {"id": "p1", "claims": [{"claimId": "c1", "text": "Rafii launched in 2026.", "usableForDraft": True}]}
        with mock.patch.object(module.flags, "enabled", lambda name: True), mock.patch.object(module.source_intake, "normalize", lambda *a, **k: artifact), \
             mock.patch.object(module.fact_pack, "build", lambda *a, **k: pack), mock.patch.object(module.fact_pack, "canonical_brief", lambda *a, **k: brief), \
             mock.patch.object(module.fact_pack, "angles", lambda *a, **k: []):
            service.source_campaign(WS, "token", {"format": "text", "text": "x", "goal": "Share", "audience": "Founders", "destinations": [{"channelId": "ch1"}]})
        applied = [event for event in script.events(committed=True) if event[0] == "humanizer.applied"]
        self.assertEqual([(event, props) for event, _, props, _ in applied], [("humanizer.applied", {"outcome": applied[0][2]["outcome"], "surface": "source_campaign"})])
        self.assertIn(applied[0][2]["outcome"], ("ready", "needs_revision"))


if __name__ == "__main__":
    unittest.main()


class TaxonomyRegistrationTests(unittest.TestCase):
    """Another product area adds its events to the one taxonomy and writer (one table, one dedupe shape)."""

    def setUp(self):
        self.saved = (dict(pe.TAXONOMY), set(pe.COUNTS))

    def tearDown(self):
        pe.TAXONOMY.clear()
        pe.TAXONOMY.update(self.saved[0])
        pe.COUNTS.clear()
        pe.COUNTS.update(self.saved[1])

    def test_registered_event_records_enums_and_bounded_counts_only(self):
        pe.register({"week.completed": {"outcome", "posts"}}, counts=("posts",))
        workspace = "11111111-2222-4333-8444-555555555555"
        params = pe.row(workspace, None, "week.completed", "week-1", 3,
                                    {"outcome": "done", "posts": 4, "title": "Launch week", "secret": "x"})
        self.assertIsNotNone(params)
        self.assertEqual(json.loads(params[3]), {"outcome": "done", "posts": 4})
        self.assertEqual(params[4], "week.completed:week-1:3")
        for bad in (-1, True, 1.5, "4", pe.MAX_COUNT + 1):
            row = pe.row(workspace, None, "week.completed", "week-1", 3, {"posts": bad})
            self.assertEqual(json.loads(row[3]), {}, bad)

    def test_same_registration_is_a_no_op_and_a_conflicting_one_is_refused(self):
        pe.register({"draft.accepted": {"surface"}})
        pe.register({"draft.accepted": {"surface"}})
        with self.assertRaises(ValueError):
            pe.register({"draft.accepted": {"surface", "kind"}})
        with self.assertRaises(ValueError):
            pe.register({"draft.created": {"plan"}})   # existing events cannot be redefined
        self.assertEqual(pe.TAXONOMY["draft.accepted"], frozenset({"surface"}))

    def test_invalid_names_are_refused_before_anything_changes(self):
        before = dict(pe.TAXONOMY)
        for events in ({"Draft.Accepted": set()}, {"draft": set()}, {"draft.accepted": {"Bad-Key"}}, {"x." + "a" * 60: set()}):
            with self.assertRaises(ValueError):
                pe.register({"brief.action": {"kind"}, **events})
        self.assertEqual(pe.TAXONOMY, before)
        with self.assertRaises(ValueError):
            pe.register({}, counts=("Posts",))

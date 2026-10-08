"""Lane F unit tests: the pure rules of ui_store (scope, selection memory, declared UI state, library fallback, lease shapes).

The database behaviour (CAS, leases, two producers, replay, reaping, tenants, RLS) is proven against real PostgreSQL in
tests/phase2/postgres_agent_ui_store.py; these tests pin the rules that do not need a database, and that every entry point
refuses bad input before it touches one.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import ui_contracts as contracts
from postriff_phase2.agent_runtime_v2 import ui_store as store

WID = "11111111-1111-4111-8111-111111111111"
ART = "22222222-2222-4222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
ME = "44444444-4444-4444-8444-444444444444"
HASH = "a" * 64


class Member:
    def __init__(self, role):
        self.role = role

    def allows(self, need):
        return {"read": True, "edit": self.role in ("owner", "admin", "editor")}.get(need, False)


def auth(role="owner", scope="workspace", scope_key=""):
    return SimpleNamespace(workspace_id=WID, principal=ME, member=Member(role), role=role, scope=scope, scope_key=scope_key,
                           allows=lambda need: Member(role).allows(need))


class NoDatabase:
    """A cursor that fails the test if anything reaches the database."""

    def execute(self, *_args, **_kwargs):
        raise AssertionError("input validation must happen before any SQL")

    def fetchone(self):
        raise AssertionError("no SQL expected")

    fetchall = fetchone


def record(**overrides):
    base = {"artifactId": ART, "workspaceId": WID, "scope": "workspace", "scopeKey": "", "conversationId": RUN, "runId": RUN, "messageId": RUN,
            "slot": "main", "actor": ME, "surface": "chat", "journeyIds": ["J06"], "revision": 1, "sourceHash": HASH, "generationState": "ready",
            "validationState": "accepted", "generationAttemptId": None, "reason": None, "contractVersion": contracts.CONTRACT_VERSION,
            "languageVersion": "0.3", "libraryVersion": "0.3.2", "libraryHash": "b" * 64, "promptHash": "c" * 64,
            "manifest": {"manifestId": "m1", "bindingVersion": 1, "queries": [{"name": "metrics_summary"}], "actions": [{"actionId": "draft_save"}]},
            "manifestId": "m1", "bindingVersion": 1, "fallbackText": "Native answer.", "safeState": {}, "stateRevision": 0, "nextSeq": 5,
            "asOf": None, "createdAt": "2026-10-08T00:00:00.000Z", "updatedAt": "2026-10-08T00:00:00.000Z", "runKey": "agent:k" * 3}
    base.update(overrides)
    return base


class ScopeRules(unittest.TestCase):
    def test_founder_scope_key_of_founder_runs_only(self):
        self.assertEqual(store.founder_scope_key("agent:founder:live:production:abc"), "founder:live:production")
        self.assertIsNone(store.founder_scope_key("agent:abc"))
        self.assertIsNone(store.founder_scope_key("agent:founder:live"))
        self.assertIsNone(store.founder_scope_key(None))

    def test_consumer_routes_never_see_founder_artifacts(self):
        founder_record = record(scope="founder", scopeKey="founder:live:production", runKey="agent:founder:live:production:k1")
        self.assertFalse(store.scope_allows(founder_record, auth()))
        self.assertTrue(store.scope_allows(founder_record, auth(scope="founder", scope_key="founder:live:production")))
        # A different founder namespace (Demo vs Live) is a different scope.
        self.assertFalse(store.scope_allows(founder_record, auth(scope="founder", scope_key="founder:demo:production")))

    def test_founder_runs_are_hidden_even_if_a_row_claims_workspace_scope(self):
        forged = record(scope="workspace", scopeKey="", runKey="agent:founder:live:production:k1")
        self.assertFalse(store.scope_allows(forged, auth()))

    def test_consumer_artifacts_are_hidden_from_founder_routes(self):
        self.assertFalse(store.scope_allows(record(runKey="agent:k1"), auth(scope="founder", scope_key="founder:live:production")))

    def test_client_scope_values_are_not_accepted(self):
        with self.assertRaises(AlphaError):
            store.effective_scope(SimpleNamespace(scope="admin", scope_key=""))
        # A workspace caller never carries a scope key, whatever it says.
        self.assertEqual(store.effective_scope(SimpleNamespace(scope="workspace", scope_key="founder:live:x")), ("workspace", ""))


class SelectionMemory(unittest.TestCase):
    def test_order_is_kept_and_duplicates_dropped(self):
        clean = store.clean_selection({"items": [{"type": "draft", "id": "d2", "title": "Second"}, {"type": "draft", "id": "d1"},
                                                 {"type": "draft", "id": "d2"}], "revision": 3})
        self.assertEqual([i["id"] for i in clean["items"]], ["d2", "d1"])
        self.assertEqual(clean["revision"], 3)

    def test_visible_list_keeps_order_without_titles(self):
        clean = store.clean_selection({"items": [{"type": "draft", "id": "d1"}], "visible": [{"type": "draft", "id": "d3", "title": "x"},
                                                                                              {"type": "draft", "id": "d1"}]})
        self.assertEqual(clean["visible"], [{"type": "draft", "id": "d3"}, {"type": "draft", "id": "d1"}])

    def test_invalid_selections_are_refused(self):
        for bad in ({"items": "d1"}, {"items": [{"type": "Draft", "id": "d1"}]}, {"items": [{"type": "draft", "id": "<script>"}]},
                    {"items": [], "extra": 1}, {"items": [{"type": "draft", "id": "d1", "url": "https://x"}]},
                    {"items": [{"type": "draft", "id": f"d{i}"} for i in range(store.SELECTION_MAX_ITEMS + 1)]}):
            with self.assertRaises(AlphaError, msg=str(bad)):
                store.clean_selection(bad)

    def test_note_names_ids_in_order_and_never_titles(self):
        refs = [{"type": "draft", "id": "d2", "title": "My private draft title"}, {"type": "draft", "id": "d1", "title": "Other"}]
        note = store.selection_note(refs, 2, visible=[{"type": "draft", "id": "d1"}, {"type": "draft", "id": "d2"}])
        self.assertIn("1. draft d2; 2. draft d1", note)
        self.assertIn("The list as shown then: 1. draft d1; 2. draft d2", note)
        self.assertNotIn("private", note)
        self.assertNotIn("Other", note)

    def test_selection_context_without_a_valid_reference_reads_nothing(self):
        self.assertIsNone(store.selection_context(NoDatabase(), auth(), None))
        self.assertIsNone(store.selection_context(NoDatabase(), auth(), {"artifactId": "nope"}))


class DeclaredState(unittest.TestCase):
    def test_only_declared_fields_are_kept(self):
        out = store.validate_state_fields({"$period": "30d", "filters": {"platform": {"value": "IG", "componentType": "Select"}}}, {"$period"}, {"filters"})
        self.assertEqual(out["$period"], "30d")
        with self.assertRaises(AlphaError):
            store.validate_state_fields({"$undeclared": 1}, {"$period"}, set())
        with self.assertRaises(AlphaError):
            store.validate_state_fields({"otherForm": {}}, set(), {"filters"})

    def test_secret_looking_fields_and_signed_urls_are_refused(self):
        for patch in ({"$password": "x"}, {"$apiKey": "x"}, {"$note": "https://s3.example/x?X-Amz-Signature=abc"},
                      {"$auth": "Bearer abcdefghijklmnopqrstuvwxyz"}):
            with self.assertRaises(AlphaError, msg=str(patch)):
                store.validate_state_fields(patch, {k for k in patch}, set())

    def test_null_removes_and_selection_is_reserved(self):
        out = store.validate_state_fields({"$period": None, store.SELECTION_KEY: {"items": [{"type": "draft", "id": "d1"}]}}, {"$period"}, set())
        self.assertIsNone(out["$period"])
        self.assertEqual(out[store.SELECTION_KEY]["items"][0]["id"], "d1")

    def test_depth_and_size_limits(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}}
        with self.assertRaises(AlphaError):
            store.validate_state_fields({"$deep": deep}, {"$deep"}, set())
        with self.assertRaises(AlphaError):
            store.validate_state_fields({"$long": "x" * (store.STATE_STRING_MAX + 1)}, {"$long"}, set())

    def test_persist_refuses_before_sql(self):
        viewer = auth("viewer")
        with self.assertRaises(AlphaError) as raised:
            store.persist_ui_state(NoDatabase(), viewer, ART, 0, {"$period": "7d"})
        self.assertEqual(raised.exception.status, 403)
        with self.assertRaises(AlphaError):
            store.persist_ui_state(NoDatabase(), auth(), ART, -1, {})


class LibraryFallback(unittest.TestCase):
    def test_supported_hashes_come_from_assets_and_explicit_compat_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openui-assets.json"
            path.write_text(json.dumps({"libraries": {"consumer": {"libraryHash": "b" * 64}, "founder": {"libraryHash": "d" * 64}}}))
            supported = store.supported_library_hashes(path, values={"RAFII_GENUI_COMPATIBLE_LIBRARIES": "e" * 64 + ",not-a-hash"})
        self.assertEqual(supported["workspace"], {"b" * 64, "e" * 64})
        self.assertEqual(supported["founder"], {"d" * 64, "e" * 64})

    def test_missing_assets_support_nothing(self):
        supported = store.supported_library_hashes(Path("/nonexistent/openui-assets.json"), values={})
        self.assertEqual(supported, {"workspace": set(), "founder": set()})

    def test_old_library_falls_back_natively(self):
        old = record(libraryHash="f" * 64)
        compat = store.compatibility(old, {"workspace": {"b" * 64}, "founder": set()})
        self.assertEqual(compat, {"supported": False, "reason": "library_unsupported"})
        display = store.display_for(old, None, compat, [])
        self.assertEqual(display["mode"], "fallback")
        self.assertEqual(display["reason"], "library_unsupported")

    def test_display_modes(self):
        ok = {"supported": True, "reason": None}
        self.assertEqual(store.display_for(record(), None, ok, [])["mode"], "generated")
        live = {"state": "streaming", "reason": None}
        self.assertTrue(store.display_for(record(), live, ok, [])["updating"])
        pending = record(revision=0, validationState="pending", generationState="streaming")
        self.assertEqual(store.display_for(pending, live, ok, [])["mode"], "pending")
        failed = record(revision=0, validationState="rejected", generationState="failed", reason="parse_rejected")
        self.assertEqual(store.display_for(failed, {"state": "failed", "reason": "parse_rejected"}, ok, []), {"mode": "fallback", "reason": "parse_rejected", "updating": False})


class Access(unittest.TestCase):
    def test_viewer_and_disabled_flags(self):
        ok = {"supported": True, "reason": None}
        flags = {"enabled": True, "actions": True, "edits": True}
        self.assertTrue(store.access_for(record(), auth(), flags, ok, [])["canAct"])
        viewer = store.access_for(record(), auth("viewer"), flags, ok, [])
        self.assertFalse(viewer["canAct"])
        self.assertFalse(viewer["canPersistState"])
        self.assertFalse(viewer["canEdit"])
        off = store.access_for(record(), auth(), {"enabled": False}, ok, [])
        self.assertFalse(off["canAct"] or off["canQuery"] or off["canPersistState"])

    def test_founder_views_never_act(self):
        founder = record(scope="founder", scopeKey="founder:live:production")
        access = store.access_for(founder, auth(scope="founder", scope_key="founder:live:production"), {"enabled": True, "actions": True}, {"supported": True}, [])
        self.assertFalse(access["canAct"])

    def test_unsupported_library_offers_no_controls_and_says_fallback(self):
        """NC18: a view this build cannot draw is the native fallback: no reads, actions, edits, retries or saved state."""
        flags = {"enabled": True, "actions": True, "edits": True}
        old = store.compatibility(record(libraryHash="f" * 64), {"workspace": {"b" * 64}, "founder": set()})
        display = store.display_for(record(libraryHash="f" * 64), None, old, [])
        access = store.access_for(record(libraryHash="f" * 64), auth(), flags, old, [], display)
        for key in ("canQuery", "canAct", "canEdit", "canRetry", "canPersistState", "live"):
            self.assertFalse(access[key], key)
        self.assertTrue(access["fallback"])
        # The same caller on a supported, generated view keeps every control.
        ok = {"supported": True, "reason": None}
        live = store.access_for(record(), auth(), flags, ok, [], store.display_for(record(), None, ok, []))
        self.assertTrue(live["canAct"] and live["canEdit"] and live["canPersistState"])
        self.assertFalse(live["fallback"])
        # A first generation that failed is a fallback too: nothing to act on.
        failed = record(revision=0, validationState="rejected", generationState="failed", reason="parse_rejected")
        refused = store.access_for(failed, auth(), flags, ok, [], store.display_for(failed, None, ok, []))
        self.assertFalse(refused["canAct"] or refused["canPersistState"])
        self.assertTrue(refused["fallback"] and refused["canRetry"])

    def test_declared_compatible_hashes_count_as_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openui-assets.json"
            path.write_text(json.dumps({"libraries": {"consumer": {"libraryHash": "b" * 64, "compatibleLibraryHashes": ["c" * 64]}}}))
            supported = store.supported_library_hashes(path, values={})
        self.assertEqual(supported["workspace"], {"b" * 64, "c" * 64})

    def test_expired_manifest_is_historical(self):
        expired = record(manifest={"expiresAt": "2020-01-01T00:00:00Z"})
        access = store.access_for(expired, auth(), {"enabled": True, "actions": True}, {"supported": True}, [])
        self.assertTrue(access["historical"])
        self.assertFalse(access["canAct"])


class LeaseShapes(unittest.TestCase):
    def test_lease_attempt_has_the_d_a33_fields(self):
        attempt = {"attemptId": ART, "artifactId": ART, "kind": "edit", "targetRevision": 2, "baseRevision": 1, "baseSourceHash": HASH, "state": "queued",
                   "reason": None, "leaseOwner": "pid:1", "leaseExpiresAt": None, "idempotencyKey": "k" * 20, "reservationId": None, "retryOf": None,
                   "instruction": "Add a chart", "providerAttempts": 0, "checkpointSource": "", "checkpointHash": None, "checkpointBytes": 0}
        shaped = store.lease_attempt(attempt)
        for key in ("attemptId", "kind", "targetRevision", "baseRevision", "baseSourceHash", "state", "leaseOwner", "idempotencyKey", "reservationId", "retryOf"):
            self.assertIn(key, shaped)
        self.assertIsNone(store.lease_attempt(None))

    def test_public_attempt_never_carries_lease_or_reservation(self):
        attempt = {"attemptId": ART, "kind": "generate", "state": "streaming", "reason": None, "targetRevision": 1, "baseRevision": None, "retryOf": None,
                   "providerAttempts": 1, "costState": "unknown", "leaseOwner": "secret-owner", "reservationId": "r1", "idempotencyKey": "k" * 20}
        shaped = store.public_attempt(attempt)
        self.assertNotIn("leaseOwner", shaped)
        self.assertNotIn("reservationId", shaped)
        self.assertNotIn("idempotencyKey", shaped)
        self.assertTrue(shaped["live"])

    def test_edit_base_is_validated(self):
        self.assertEqual(store._edit_base({"revision": 1, "sourceHash": HASH, "instruction": "  Add a chart "})["instruction"], "Add a chart")
        for bad in (None, {"revision": 0, "sourceHash": HASH, "instruction": "x"}, {"revision": 1, "sourceHash": "short", "instruction": "x"},
                    {"revision": 1, "sourceHash": HASH, "instruction": ""}, {"revision": 1, "sourceHash": HASH, "instruction": "x" * 2001}):
            with self.assertRaises(AlphaError):
                store._edit_base(bad)


class RefusedBeforeSql(unittest.TestCase):
    def call(self, **overrides):
        kwargs = {"surface": "chat", "manifest": {}, "projection": {}, "kind": "generate", "retry_of": None, "lease_owner": "pid:1"}
        kwargs.update(overrides)
        return store.create_or_resume_artifact(NoDatabase(), overrides.pop("auth", auth()), RUN, "main", overrides.pop("key", "k" * 20), **kwargs)

    def test_bad_inputs(self):
        for overrides in ({"kind": "rewrite"}, {"surface": "desktop"}, {"surface": "founder"}, {"lease_owner": ""}, {"retry_of": "nope"},
                          {"kind": "retry"}, {"kind": "edit", "base": None}):
            with self.assertRaises(AlphaError, msg=str(overrides)):
                self.call(**overrides)

    def test_viewer_cannot_create(self):
        with self.assertRaises(AlphaError) as raised:
            store.create_or_resume_artifact(NoDatabase(), auth("viewer"), RUN, "main", "k" * 20, surface="chat", manifest={}, projection={}, lease_owner="pid:1")
        self.assertEqual(raised.exception.status, 403)

    def test_bad_key(self):
        with self.assertRaises(AlphaError):
            store.create_or_resume_artifact(NoDatabase(), auth(), RUN, "main", "short", surface="chat", manifest={}, projection={}, lease_owner="pid:1")

    def test_heartbeats_are_never_persisted(self):
        with self.assertRaises(ValueError):
            store.append_event(NoDatabase(), ART, None, 0, "ui.heartbeat", {})
        with self.assertRaises(ValueError):
            store.append_event(NoDatabase(), ART, None, 0, "ui.unknown", {})
        with self.assertRaises(AlphaError):
            store.append_event(NoDatabase(), ART, None, 0, "ui.delta", {"text": "x" * (store.EVENT_PAYLOAD_BYTES + 1)})

    def test_finish_attempt_refuses_unknown_targets(self):
        for state in ("queued", "done", ""):
            with self.assertRaises(ValueError):
                store.finish_attempt(NoDatabase(), ART, state)

    def test_checkpoint_size_bound(self):
        with self.assertRaises(AlphaError):
            store.checkpoint(NoDatabase(), ART, "x" * (contracts.BOUNDS["sourceBytes"] + 1), lease_owner="pid:1")


if __name__ == "__main__":
    unittest.main()

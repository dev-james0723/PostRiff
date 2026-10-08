"""T01 — contracts, versions and purpose-aware access (acceptance A004–A007, A008 recheck path, A014 locators)."""
import unittest
import uuid

from library_intelligence_fakes import FakeCursor, ctx, grant, version
from postriff_alpha.domain import AlphaError
from postriff_phase2.library_intelligence import actions, contracts as c, policy, versions


def source(sid="src1", *, policy_name="rewrite_approval", approved=False, active=True, egress=("local",), sha="b" * 64, use_approvals=()):
    return {"id": sid, "kind": "document", "active": active, "sourcePolicy": policy_name, "egressConsent": list(egress), "useApprovals": list(use_approvals),
            "facts": [{"id": "f1", "text": "Concert on 12 October", "approved": approved}], "origin": {"kind": "library", "assetId": "a" * 32, "sha256": sha},
            "createdAt": 1789600000.0}


class Isolation(unittest.TestCase):
    def test_cross_workspace_denied(self):
        # The foreign workspace's row is invisible: the scoped query returns nothing, and the error matches a missing key.
        cur = FakeCursor().on(r"FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY", [])
        context = ctx(cur)
        with self.assertRaises(AlphaError) as foreign:
            versions.get(context, "d" * 32)
        with self.assertRaises(AlphaError) as missing:
            versions.get(context, "e" * 32)
        self.assertEqual((foreign.exception.status, str(foreign.exception), foreign.exception.code),
                         (missing.exception.status, str(missing.exception), missing.exception.code))
        self.assertEqual(foreign.exception.status, 404)
        sql, args = cur.executed[0]
        self.assertIn("workspace_id=%s", sql)
        self.assertEqual(args[0], context.workspace_id)

    def test_resolve_rejects_version_from_other_lineage_and_changed_hash(self):
        context = ctx(FakeCursor())
        context.caches["legacy"] = {}
        v = version("a" * 32, asset="f" * 32)
        original = versions.load
        versions.load = lambda ctx, keys: {"a" * 32: dict(v)}
        try:
            with self.assertRaises(AlphaError) as other:
                versions.resolve(context, {"assetId": "1" * 32, "versionId": "a" * 32, "sha256": "b" * 64})
            self.assertEqual(other.exception.status, 404)
            with self.assertRaises(AlphaError) as changed:
                versions.resolve(context, {"assetId": "f" * 32, "versionId": "a" * 32, "sha256": "9" * 64})
            self.assertEqual(changed.exception.code, "library_version_mismatch")
            self.assertEqual(versions.resolve(context, {"assetId": "f" * 32, "versionId": "a" * 32, "sha256": "b" * 64})["versionId"], "a" * 32)
        finally:
            versions.load = original


class Purposes(unittest.TestCase):
    def test_browse_does_not_grant_cloud(self):
        context = ctx()
        v = version()
        self.assertTrue(policy.authorize_source(context, v, "browse").allowed)
        cloud = policy.authorize_processing(context, v, "cloud", "embedding")
        self.assertFalse(cloud.allowed)
        self.assertEqual(cloud.reason, "processing_grant_required")
        for category in ("asr", "vision", "llm", "ocr"):
            self.assertFalse(policy.authorize_processing(context, v, "cloud", category).allowed)
        self.assertTrue(policy.authorize_processing(context, v, "local", "extract").allowed)
        answer = policy.authorize_source(context, v, "answer")
        self.assertEqual((answer.allowed, answer.reason), (False, "grant_required"))

    def test_unapproved_fact_can_only_be_attributed_in_private_answer(self):
        s = source(approved=False, egress=("local", "cloud"))
        context = ctx(state={"sources": [s], "phase2": {"assets": []}}, grants=[grant("answer")])
        v = version(source_id="src1")
        answer = policy.authorize_source(context, v, "answer")
        self.assertTrue(answer.allowed)
        self.assertTrue(answer.attribution_only, "a private answer attributes; it never approves facts")
        draft = policy.authorize_source(context, v, "draft_evidence")
        self.assertFalse(draft.allowed)
        self.assertEqual(draft.reason, "no_approved_facts")
        public = policy.authorize_source(context, v, "public_use")
        self.assertEqual((public.allowed, public.reason), (False, "public_use_requires_approval"))
        with self.assertRaises(AlphaError) as attempt:
            policy.grant(context, {"grantType": "purpose", "purpose": "public_use", "scope": {"kind": "workspace"}})
        self.assertEqual(attempt.exception.code, "library_use_source_review")

    def test_purposes_and_provider_grants_stay_separate(self):
        v = version()
        context = ctx(grants=[grant("answer"), grant(location="cloud", category="asr", gid="d" * 32)])
        self.assertTrue(policy.authorize_source(context, v, "answer").allowed)
        for purpose in ("memory", "voice"):
            self.assertFalse(policy.authorize_source(context, v, purpose).allowed, purpose)
        self.assertFalse(policy.authorize_processing(context, v, "cloud", "embedding").allowed)
        self.assertTrue(policy.authorize_processing(context, v, "cloud", "asr").allowed)
        cloud_answer = policy.authorize_source(context, v, "answer", {"location": "cloud", "category": "llm"})
        self.assertEqual((cloud_answer.allowed, cloud_answer.reason), (False, "processing_grant_required"))

    def test_memory_cloud_needs_workspace_memory_egress(self):
        v = version()
        context = ctx(grants=[grant("memory"), grant(location="cloud", category="llm", gid="d" * 32)], state={"sources": [], "phase2": {"assets": []}, "memoryEgress": {"cloud": False}})
        self.assertEqual(policy.authorize_source(context, v, "memory", {"location": "cloud", "category": "llm"}).reason, "memory_egress_required")
        context.state["memoryEgress"] = {"cloud": True}
        self.assertTrue(policy.authorize_source(context, v, "memory", {"location": "cloud", "category": "llm"}).allowed)

    def test_legacy_denials_preserved(self):
        for s, reason in ((source(policy_name="prohibited"), "legacy_denied"), (source(active=False), "retracted")):
            context = ctx(state={"sources": [s], "phase2": {"assets": []}}, grants=[grant("answer"), grant(location="cloud", category="llm", gid="d" * 32)])
            v = version(source_id="src1")
            self.assertTrue(policy.authorize_source(context, v, "browse").allowed)
            denied = policy.authorize_source(context, v, "answer")
            self.assertEqual((denied.allowed, denied.reason), (False, reason))
            self.assertFalse(policy.authorize_processing(context, v, "cloud", "llm").allowed)

    def test_existing_source_gates_decide_draft_and_public_use(self):
        s = source(approved=True, egress=("local", "cloud"), policy_name="public_quote")
        context = ctx(state={"sources": [s], "phase2": {"assets": []}})
        v = version(source_id="src1")
        self.assertTrue(policy.authorize_source(context, v, "draft_evidence").allowed)
        self.assertTrue(policy.authorize_source(context, v, "public_use").allowed)
        # A changed version is not the imported source any more.
        self.assertEqual(policy.authorize_source(context, version(source_id="src1", sha="9" * 64), "draft_evidence").reason, "not_imported_source")

    def test_collection_grant_snapshot_does_not_broaden(self):
        members = ["a" * 32]
        context = ctx(grants=[grant("answer", scope="collection", key="e" * 32, members=members)])
        self.assertTrue(policy.authorize_source(context, version("a" * 32), "answer").allowed)
        self.assertFalse(policy.authorize_source(context, version("b" * 32), "answer").allowed, "a later member is not covered")

    def test_unready_and_deleted_versions(self):
        context = ctx(grants=[grant("answer")])
        self.assertEqual(policy.authorize_source(context, version(status="processing"), "answer").reason, "not_ready")
        self.assertEqual(policy.authorize_source(context, version(status="deleting"), "browse").reason, "unavailable")

    def test_voice_grant_requires_owner_and_attestation(self):
        editor = ctx(role="editor")
        with self.assertRaises(AlphaError) as role:
            policy.grant(editor, {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "workspace"}, "attestation": {"authoredByMe": True}})
        self.assertEqual(role.exception.status, 403)
        owner = ctx(FakeCursor().on(r"SELECT grant_revision,index_generation", [(0, 1, 0)]))
        with self.assertRaises(AlphaError) as attest:
            policy.grant(owner, {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "workspace"}})
        self.assertEqual(attest.exception.code, "library_voice_attestation")


class Revocation(unittest.TestCase):
    def test_revocation_before_delivery(self):
        cur = FakeCursor()
        context = ctx(cur, grants=[grant("answer")], revision=3)
        v = version()
        decision = policy.authorize_source(context, v, "answer")
        self.assertTrue(decision.allowed)
        # A revoke commits between retrieval and delivery: the revision moved and the grant is gone.
        cur.on(r"SELECT grant_revision FROM public.pr_library_policy WHERE workspace_id=%s FOR SHARE", [(4,)])
        cur.on(r"FROM public.pr_library_grants", [])
        cur.on(r"SELECT grant_revision,index_generation,organization_revision", [(4, 1, 0)])
        original = versions.load
        versions.load = lambda ctx, keys: {v["versionId"]: dict(v)}
        try:
            fresh = policy.recheck(context, decision)
        finally:
            versions.load = original
        self.assertFalse(fresh.allowed)
        self.assertEqual(fresh.reason, "grant_required")
        self.assertTrue(cur.sql(r"FOR SHARE"), "the recheck serializes with a concurrent revoke")

    def test_unchanged_revision_keeps_decision(self):
        cur = FakeCursor().on(r"FOR SHARE", [(3,)])
        context = ctx(cur, grants=[grant("answer")], revision=3)
        decision = policy.authorize_source(context, version(), "answer")
        self.assertIs(policy.recheck(context, decision), decision)


class Contracts(unittest.TestCase):
    def test_locator_bounds(self):
        self.assertEqual(c.locator({"kind": "time", "startMs": 1000, "endMs": 5000}, duration_ms=6000)["endMs"], 5000)
        for bad, bounds in (({"kind": "time", "startMs": 1000, "endMs": 7000}, {"duration_ms": 6000}),
                            ({"kind": "time", "startMs": 5000, "endMs": 5000}, {}),
                            ({"kind": "page", "page": 0}, {}),
                            ({"kind": "page", "page": 4}, {"pages": 3}),
                            ({"kind": "text", "start": 10, "end": 500}, {"text_length": 100}),
                            ({"kind": "slide", "slide": -1}, {}),
                            ({"kind": "sheet", "sheetName": "Q4", "cellRange": "B4:;DROP"}, {}),
                            ({"kind": "imageRegion", "x": 0.8, "y": 0, "width": 0.5, "height": 0.2}, {}),
                            ({"kind": "page", "page": 2, "extra": 1}, {})):
            with self.assertRaises(AlphaError, msg=str(bad)):
                c.locator(bad, **bounds)
        self.assertEqual(c.locator_label({"kind": "text", "start": 0, "end": 40}), "characters 0–40", "no page number is invented")
        self.assertEqual(c.locator_label({"kind": "time", "startMs": 61000, "endMs": 65000}), "1:01–1:05")
        self.assertEqual(c.locator_label({"kind": "sheet", "sheetName": "Budget", "cellRange": "B4:C9"}), "Budget!B4:C9")

    def test_asset_key_single_adapter(self):
        u = uuid.uuid4()
        self.assertEqual(c.asset_key(u), u.hex)
        self.assertEqual(c.asset_key(str(u)), u.hex)
        self.assertEqual(c.asset_uuid(u.hex), u)
        with self.assertRaises(AlphaError):
            c.asset_key("../etc/passwd")

    def test_search_request_limits(self):
        req = c.search_request({"query": "  幾時開演奏會  ", "purpose": "answer", "limit": 100})
        self.assertEqual((req["query"], req["limit"], req["scope"]), ("幾時開演奏會", 100, {"kind": "workspace"}))
        for bad in ({"limit": 101}, {"limit": 0}, {"modes": ["sql"]}, {"purpose": "admin"}, {"scope": {"kind": "selection", "assetRefs": []}}, {"workspaceId": "x"}):
            with self.assertRaises(AlphaError, msg=str(bad)):
                c.search_request(bad)
        self.assertIn("visual", c.search_request({"similarTo": {"assetId": "a" * 32, "versionId": "a" * 32, "sha256": ""}})["modes"])

    def test_action_envelope_rejects_identity_and_unsafe_payload(self):
        base = {"actionId": "a1", "uiInstanceId": "ui1", "actionType": "collection.save", "targetRefs": [], "expectedRevision": 2,
                "idempotencyKey": "k" * 20, "payload": {"name": "Recital"}}
        self.assertEqual(c.action_envelope(base)["actionType"], "collection.save")
        for patch in ({"workspaceId": "x"}, {"actor": "x"}, {"actionType": "sql.run"}, {"idempotencyKey": "short"},
                      {"payload": {"url": "https://evil.example"}}, {"payload": {"name": "<script>alert(1)</script>"}},
                      {"payload": {"rule": "SELECT * FROM pr_library_assets"}}, {"payload": {"note": "see https://x.test"}}):
            with self.assertRaises(AlphaError, msg=str(patch)):
                c.action_envelope({**base, **patch})

    def test_register_artifact_only_final_private_storage(self):
        good = {"runId": "run1", "outputId": "out1", "contentSha256": "a" * 64, "storageRef": {"category": "file", "objectName": "b" * 32 + ".md"},
                "mime": "text/markdown", "displayTitle": "Script", "originalFilename": "script.md", "artifactRole": "final", "idempotencyKey": "run1:out1:final-registration"}
        self.assertEqual(c.register_artifact(good)["artifactRole"], "final")
        for patch in ({"artifactRole": "scratch"}, {"storageRef": {"category": "file", "objectName": "../tmp/x.md"}},
                      {"storageRef": {"category": "s3", "objectName": "b" * 32 + ".md"}}, {"storageRef": {"category": "file", "objectName": "tool-log.txt"}}):
            with self.assertRaises(AlphaError, msg=str(patch)):
                c.register_artifact({**good, **patch})


class ActionDispatch(unittest.TestCase):
    def test_forged_cross_workspace_target_denied(self):
        cur = FakeCursor().on(r"FROM public.pr_library_action_receipts", []).on(r"FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY", [])
        context = ctx(cur)
        context.caches["legacy"] = {}
        result = actions.apply(context, {"actionId": "a1", "uiInstanceId": "ui1", "actionType": "collection.save", "expectedRevision": 1,
                                         "targetRefs": [{"assetId": "d" * 32, "versionId": "d" * 32, "sha256": ""}], "idempotencyKey": "key-0000000000000001", "payload": {}})
        self.assertEqual(result["status"], "denied")
        self.assertNotIn("d" * 32, str(result["warnings"]))

    def test_replayed_key_with_different_request_denied(self):
        cur = FakeCursor().on(r"FROM public.pr_library_action_receipts", [(context_actor := "00000000-0000-0000-0000-000000000001", "0" * 64, "applied", {"status": "applied"})])
        context = ctx(cur)
        result = actions.apply(context, {"actionId": "a1", "uiInstanceId": "ui1", "actionType": "collection.save", "expectedRevision": 1,
                                         "targetRefs": [], "idempotencyKey": "key-0000000000000001", "payload": {"name": "x"}})
        self.assertEqual(result["status"], "denied")
        self.assertTrue(context_actor)

    def test_viewer_role_cannot_mutate(self):
        context = ctx(role="viewer")
        result = actions.apply(context, {"actionId": "a1", "uiInstanceId": "ui1", "actionType": "collection.save", "expectedRevision": 1,
                                         "targetRefs": [], "idempotencyKey": "key-0000000000000001", "payload": {}})
        self.assertEqual(result["status"], "denied")


if __name__ == "__main__":
    unittest.main()

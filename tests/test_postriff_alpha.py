"""Behavioral acceptance and privacy checks for the isolated founder alpha."""
import copy
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError, Store, FAILURES
from postriff_alpha.generation import FixtureAdapter, SAMPLE_FACTS
from postriff_alpha.server import make_server
from postriff_alpha.templates import PLAN_FIXTURES, catalog


class Journey:
    def __init__(self, store, sample=False):
        self.store = store
        self.created = store.create(sample)
        self.id, self.token = self.created["workspaceId"], self.created["token"]
        self.snapshot = self.created

    @property
    def state(self):
        return self.snapshot["state"]

    def act(self, action, **payload):
        self.snapshot = self.store.mutate(self.id, self.token, self.snapshot["revision"], action, payload)
        return self.state

    def setup(self, mode="personal", source=True):
        self.act("mode", mode=mode)
        self.act("context", purpose="Make community learning accessible", audience="Curious beginners", subject="Community workshops", speaker="My voice", layers=["voice", "business"] if mode == "hybrid" else [])
        if source:
            self.act("source", kind="sample")
            src = self.state["sources"][-1]
            self.act("approve_source", sourceId=src["id"], factIds=[f["id"] for f in src["facts"]])
        else:
            self.act("idea", idea="How might a shared learning space work?")
        self.act("source_done")
        self.act("profile_propose", writing="A small step can be a useful beginning.", tone="warm")
        self.act("profile_decide", decision="approve")
        self.act("runtime", selected=FixtureAdapter.id)
        return self

    def two(self):
        self.act("generate", platform="LinkedIn", language="English")
        self.act("generate", platform="Instagram", language="繁體中文")
        return self

    def edit(self, index=0, text="A shorter opening.\n\nA useful question to explore."):
        v = self.state["variants"][index]
        self.act("variant_edit", variantId=v["id"], variantRevision=v["revision"], text=text)
        return self.state["variants"][index]

    def propose(self, platform="LinkedIn", language="English", **overrides):
        """Server code proposes a preference (a chat instruction, later extraction from edits); the client only decides."""
        proposal = {"type": "writing_preference", "ruleKey": "opening.style", "polarity": "do", "scope": {"platform": platform, "language": language},
                    "statement": "Use shorter openings.", "params": {"shortOpenings": True}, "source": "chat", "variantId": self.state["variants"][0]["id"], **overrides}
        with self.store.connect() as db:
            row = db.execute("SELECT revision, state FROM workspaces WHERE id=?", (self.id,)).fetchone()
            state = json.loads(row["state"])
            record = learning.propose(state, proposal)
            db.execute("UPDATE workspaces SET state=?, revision=? WHERE id=?", (json.dumps(state), row["revision"] + 1, self.id))
        self.snapshot = self.store.get(self.id, self.token)
        return record


class DomainAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "alpha.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_four_modes_reach_reviewed_save_and_export(self):
        for mode in ("personal", "niche", "business", "hybrid"):
            with self.subTest(mode=mode):
                j = Journey(self.store).setup(mode).two()
                j.act("save")
                archive = zipfile.ZipFile(io.BytesIO(self.store.export(j.id, j.token)))
                self.assertTrue(j.state["session"]["completed"])
                self.assertEqual(j.state["brandHub"]["mode"], mode)
                self.assertEqual(j.state["research"]["phase0"], "incomplete")
                self.assertFalse(j.state["research"]["customerValidation"])
                self.assertEqual(j.state["research"]["pendingParticipants"], ["P02", "P03", "P04", "P05"])
                self.assertEqual(len([n for n in archive.namelist() if n.startswith("drafts/")]), 2)

    def test_hybrid_requires_two_layers_and_explicit_speaker(self):
        j = Journey(self.store)
        j.act("mode", mode="hybrid")
        for p in ({"layers": ["voice"], "speaker": "My voice"}, {"layers": ["voice", "business"], "speaker": ""}):
            with self.assertRaises(AlphaError):
                j.act("context", purpose="Teach", audience="Beginners", subject="Pottery", **p)
        j.act("context", purpose="Teach", audience="Beginners", subject="Pottery", layers=["voice", "business"], speaker="The business")
        self.assertEqual(j.state["speaker"]["label"], "The business")

    def test_back_and_restart_preserve_confirmed_answers_and_single_hub(self):
        j = Journey(self.store).setup()
        hub = j.state["brandHub"]["id"]
        for step in (1, 0, 2, 3, 4, 5):
            j.act("step", step=step)
        restarted = Store(self.path).get(j.id, j.token)
        self.assertEqual(restarted, j.snapshot)
        self.assertEqual(restarted["state"]["brandHub"]["id"], hub)
        self.assertEqual(len(restarted["state"]["speaker"]["revisions"]), 1)
        self.assertEqual(restarted["state"]["session"]["answers"]["purpose"], "Make community learning accessible")

    def test_business_blocks_unapproved_facts_and_sources_are_deduplicated(self):
        j = Journey(self.store)
        j.act("mode", mode="business")
        j.act("context", purpose="Teach", audience="Beginners", subject="Workshops")
        j.act("source", kind="document", title="offer.md", text="One beginner workshop is available.\nPrivate unpublished price: 999.")
        with self.assertRaises(AlphaError):
            j.act("source_done")
        src = j.state["sources"][0]
        j.act("approve_source", sourceId=src["id"], factIds=[src["facts"][0]["id"]])
        j.act("source_done")
        with self.assertRaises(AlphaError):
            j.act("source", kind="document", title="duplicate.md", text="One beginner workshop is available.\nPrivate unpublished price: 999.")
        self.assertEqual(len(j.state["sources"]), 1)

    def test_link_is_unfetched_and_not_converted_to_fact(self):
        j = Journey(self.store).setup(source=False)
        j.act("source", kind="link", text="https://example.com/unknown", title="Reference")
        source = j.state["sources"][0]
        self.assertEqual(source["facts"], [])
        self.assertIn("not fetched", source["unknowns"][0])
        j.act("generate")
        self.assertIn("No approved factual source", " ".join(j.state["variants"][0]["unknowns"]))

    def test_document_type_size_and_malformed_fields_are_rejected(self):
        j = Journey(self.store)
        for payload in ({"kind": "document", "title": "secret.pdf", "text": "hello"}, {"kind": "document", "title": "large.md", "text": "字" * 7000}, {"kind": "text", "text": ""}, {"kind": "text", "text": "bad\0text"}):
            with self.assertRaises(AlphaError):
                j.act("source", **payload)
        self.assertEqual(j.state["sources"], [])

    def test_profile_skip_edit_reject_and_revision_approval(self):
        j = Journey(self.store)
        j.act("profile_propose", writing="", tone="reflective")
        self.assertIsNone(j.state["speaker"]["activeRevision"])
        self.assertEqual(j.state["speaker"]["provisional"]["writingExample"], "")
        j.act("profile_decide", decision="reject")
        self.assertIsNone(j.state["speaker"]["provisional"])
        with self.assertRaises(AlphaError):
            j.act("profile_decide", decision="approve")
        j.act("profile_propose", writing="My supplied words", tone="warm")
        j.act("profile_decide", decision="approve", note="Use everyday language and room for reflection.")
        self.assertEqual(j.state["speaker"]["revisions"][0]["profile"]["observations"], ["Use everyday language and room for reflection."])
        self.assertEqual(j.state["speaker"]["activeRevision"], 1)

    def test_fixed_outputs_have_no_invented_biography_or_unsupported_claims(self):
        j = Journey(self.store).setup(source=False).two()
        output = " ".join(v["text"] for v in j.state["variants"])
        for claim in ("I have", "I founded", "my clients", "20 years", "certified", "guaranteed", "獲獎", "我的客戶"):
            self.assertNotIn(claim, output)
        self.assertIn("To develop", output)
        self.assertIn("待補充", output)
        self.assertTrue(all(v["sourceIds"] == [] for v in j.state["variants"]))

    def test_second_variant_is_native_and_source_linked_with_version_metadata(self):
        j = Journey(self.store).setup().two()
        a, b = j.state["variants"]
        self.assertNotEqual(a["text"], b["text"])
        self.assertIn("#社區", b["text"])
        self.assertNotIn("#社區", a["text"])
        self.assertIn(SAMPLE_FACTS[0][1], b["text"])
        self.assertEqual(a["sourceIds"], b["sourceIds"])
        self.assertEqual(a["voiceRevision"], 1)
        self.assertEqual(a["speakerId"], j.state["speaker"]["id"])
        self.assertEqual(len(a["openings"]), 3)
        self.assertEqual(j.state["runs"][0]["adapterVersion"], FixtureAdapter.version)

    def test_custom_text_is_quoted_and_translation_limit_is_explicit(self):
        j = Journey(self.store).setup(source=False)
        j.act("source", kind="text", text="A PRIVATE approved source quotation.")
        src = j.state["sources"][0]
        j.act("approve_source", sourceId=src["id"], factIds=[src["facts"][0]["id"]])
        j.act("generate", platform="Instagram", language="繁體中文")
        v = j.state["variants"][0]
        self.assertIn("來源原文：“A PRIVATE approved source quotation.”", v["text"])
        self.assertIn("translation needs review", " ".join(v["warnings"]))

    def test_variant_edits_do_not_overwrite_siblings_or_propose_anything(self):
        j = Journey(self.store).setup().two()
        sibling = copy.deepcopy(j.state["variants"][1])
        j.edit()
        j.edit(text="Another refinement.")
        self.assertEqual(j.state["variants"][1], sibling)
        self.assertEqual(j.state["preferences"], [], "nothing is proposed from a single edit")
        self.assertEqual([r["origin"] for r in j.state["variants"][0]["revisions"]], ["fixture", "author-edit", "author-edit"])
        j.act("save")
        self.assertTrue(j.state["savedAt"])

    def test_preference_remember_is_a_style_revision_and_undo_and_delete_work(self):
        j = Journey(self.store).setup().two()
        p = j.propose()
        j.act("preference", preferenceId=p["id"], decision="remember")
        self.assertEqual(j.state["speaker"]["activeRevision"], 1, "a learned preference never moves the voice revision")
        self.assertEqual(j.state["learning"]["revision"], 1)
        self.assertFalse(any(v["needsReview"] for v in j.state["variants"]))
        j.act("preview_update", variantId=j.state["variants"][0]["id"])
        self.assertTrue(j.state["variants"][0]["proposedUpdate"]["text"].startswith("A small start."))
        self.assertEqual(j.state["variants"][0]["proposedUpdate"]["styleRevision"], 1)
        j.act("generate", platform="Threads", language="English")
        self.assertFalse(j.state["variants"][-1]["text"].startswith("A small start."))
        self.assertEqual(j.state["variants"][-1]["styleRevision"], 1)
        j.act("preference", preferenceId=p["id"], decision="undo")
        self.assertEqual((j.state["learning"]["revision"], learning.active_items(j.state)), (2, []))
        self.assertEqual(j.state["learning"]["retired"][0]["retiredReason"], "undo")
        j.act("preference", preferenceId=p["id"], decision="delete")
        self.assertEqual(j.state["preferences"][0]["status"], "deleted")
        self.assertEqual(j.state["speaker"]["activeRevision"], 1)

    def test_post_only_and_rejection_do_not_change_voice_or_learning(self):
        for decision in ("post-only", "reject"):
            with self.subTest(decision=decision):
                j = Journey(self.store).setup().two()
                p = j.propose()
                j.act("preference", preferenceId=p["id"], decision=decision)
                self.assertEqual(j.state["speaker"]["activeRevision"], 1)
                self.assertEqual((j.state["learning"]["revision"], learning.active_items(j.state)), (0, []))
                self.assertEqual(bool(j.state["variants"][0].get("localPreferences")), decision == "post-only")
                j.act("save")

    def test_shared_updates_are_reviewable_candidates_and_stale_candidate_rejected(self):
        j = Journey(self.store).setup().two()
        j.edit(text="An important custom opening.")
        p = j.propose()
        j.act("preference", preferenceId=p["id"], decision="reject")
        original = j.state["variants"][0]["text"]
        j.act("idea", idea="A different approach to community learning")
        self.assertEqual(j.state["variants"][0]["text"], original)
        with self.assertRaises(AlphaError):
            j.act("accept_update", variantId=j.state["variants"][0]["id"])
        j.act("preview_update", variantId=j.state["variants"][0]["id"])
        self.assertTrue(j.state["variants"][0]["proposedUpdate"]["text"])
        self.assertEqual(j.state["variants"][0]["text"], original)
        j.edit(text="A later author edit")
        self.assertIsNone(j.state["variants"][0]["proposedUpdate"])
        with self.assertRaises(AlphaError) as caught:
            j.act("accept_update", variantId=j.state["variants"][0]["id"])
        self.assertEqual(caught.exception.status, 409)
        j.act("preview_update", variantId=j.state["variants"][0]["id"])
        j.act("accept_update", variantId=j.state["variants"][0]["id"])
        self.assertFalse(j.state["variants"][0]["needsReview"])
        self.assertTrue(j.state["variants"][1]["needsReview"])
        self.assertIn(original, [r["text"] for r in j.state["variants"][0]["revisions"]])

    def test_stale_workspace_and_variant_revision_fail_without_losing_edits(self):
        j = Journey(self.store).setup().two()
        rev = j.snapshot["revision"]
        j.act("idea", idea="A new angle")
        with self.assertRaises(AlphaError) as caught:
            self.store.mutate(j.id, j.token, rev, "idea", {"idea": "A stale overwrite"})
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(AlphaError):
            j.act("variant_edit", variantId=j.state["variants"][0]["id"], variantRevision=0, text="Overwrite")
        self.assertEqual(self.store.get(j.id, j.token)["state"]["brief"]["idea"], "A new angle")

    def test_all_fixture_failures_preserve_existing_work_and_no_network(self):
        j = Journey(self.store).setup().two()
        variants = copy.deepcopy(j.state["variants"])
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network is forbidden")):
            for failure in FAILURES:
                j.act("generate", platform="Threads", language="English", fixtureFailure=failure)
                self.assertEqual(j.state["variants"], variants)
                self.assertEqual(j.state["runs"][-1]["failure"], failure)
            j.act("generate", platform="Threads", language="English")
        self.assertEqual(j.state["runs"][-1]["status"], "completed")
        for route in ("codex", "claude", "google", "managed"):
            with self.assertRaises(AlphaError):
                j.act("runtime", selected=route)

    def test_malformed_adapter_output_never_applies_a_partial_draft(self):
        j = Journey(self.store).setup()
        revision = j.snapshot["revision"]
        with patch.object(FixtureAdapter, "generate", return_value={"text": None}):
            with self.assertRaises(AlphaError):
                j.act("generate")
        current = self.store.get(j.id, j.token)
        self.assertEqual(current["revision"], revision)
        self.assertEqual(current["state"]["variants"], [])

    def test_two_workspace_isolation_and_sample_does_not_copy_personal_profile(self):
        a = Journey(self.store).setup().two()
        a.act("profile_propose", writing="WORKSPACE_A_PRIVATE_CANARY", tone="direct")
        a.act("profile_decide", decision="approve")
        b = Journey(self.store, sample=True)
        self.assertNotIn("WORKSPACE_A_PRIVATE_CANARY", json.dumps(b.state))
        self.assertNotEqual(a.state["brandHub"]["id"], b.state["brandHub"]["id"])
        with self.assertRaises(AlphaError):
            self.store.get(a.id, b.token)
        with self.assertRaises(AlphaError):
            self.store.mutate(a.id, b.token, a.snapshot["revision"], "idea", {"idea": "cross tenant"})
        with self.assertRaises(AlphaError):
            self.store.export(a.id, b.token)
        with self.assertRaises(AlphaError):
            b.act("approve_source", sourceId=a.state["sources"][0]["id"], factIds=[])

    def test_neutral_templates_and_plan_parity_preserve_private_overrides_on_upgrade(self):
        released = catalog()
        for plan in PLAN_FIXTURES:
            self.assertEqual(catalog(plan), released)
        self.assertNotIn("james", json.dumps(released).lower())
        a, b = Journey(self.store), Journey(self.store)
        a.act("template_config", templateId="content-craft", overrides={"tone": "reflective", "shortOpenings": True})
        new = copy.deepcopy(released)
        for t in new:
            t["version"] = "1.1.0"
        with patch("postriff_alpha.domain.catalog", return_value=new):
            a.act("template_refresh")
        instance = a.state["skillInstances"][-1]
        self.assertEqual(instance["templateVersion"], "1.1.0")
        self.assertEqual(instance["overrides"], {"tone": "reflective", "shortOpenings": True})
        self.assertEqual(b.state["skillInstances"][-1]["overrides"], {})
        with self.assertRaises(AlphaError):
            a.act("template_config", templateId="content-craft", overrides={"publish": True})

    def test_export_contains_only_approved_current_workspace_material_and_hashes(self):
        j = Journey(self.store).setup(source=False)
        j.act("source", kind="text", text="APPROVED_CANARY\nUNAPPROVED_CANARY", title="Reviewed note")
        src = j.state["sources"][0]
        j.act("approve_source", sourceId=src["id"], factIds=[src["facts"][0]["id"]])
        j.two().act("save")
        blob = self.store.export(j.id, j.token)
        archive = zipfile.ZipFile(io.BytesIO(blob))
        all_text = " ".join(archive.read(name).decode() for name in archive.namelist())
        self.assertIn("APPROVED_CANARY", all_text)
        for secret in ("UNAPPROVED_CANARY", j.token, "james-au", "WORKSPACE_A_PRIVATE_CANARY", "secret_hash"):
            self.assertNotIn(secret, all_text)
        manifest = json.loads(archive.read("manifest.json"))
        for name, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
        self.assertEqual(manifest["voiceRevision"], 1)
        self.assertNotIn("revisions", manifest)

    def test_withdrawn_source_blocks_export_and_cannot_reenter_generated_or_exported_pack(self):
        j = Journey(self.store).setup(source=False)
        j.act("source", kind="text", title="Withdrawn reference", text="WITHDRAWN_CANARY")
        src = j.state["sources"][0]
        j.act("approve_source", sourceId=src["id"], factIds=[src["facts"][0]["id"]])
        j.two().act("save")
        j.act("retract_source", sourceId=src["id"])
        with self.assertRaises(AlphaError):
            self.store.export(j.id, j.token)
        self.assertEqual(j.state["sources"][0]["text"], "")
        for v in j.state["variants"]:
            j.act("preview_update", variantId=v["id"])
            j.act("accept_update", variantId=v["id"])
        j.act("save")
        archive = zipfile.ZipFile(io.BytesIO(self.store.export(j.id, j.token)))
        self.assertNotIn("WITHDRAWN_CANARY", " ".join(archive.read(n).decode() for n in archive.namelist()))

    def test_profile_import_is_proposal_only_and_discards_authority_fields(self):
        j = Journey(self.store).setup()
        old = copy.deepcopy(j.state["speaker"])
        content = {"format": "postriff-profile-v1", "profile": {"tone": "direct", "writingExample": "Provided text", "observations": ["Be concise"], "tools": ["publish"], "workspaceToken": "INJECTED_TOKEN", "preferences": [{"publish": True}]}}
        j.act("import_propose", content=content)
        self.assertEqual(j.state["speaker"], old)
        self.assertNotIn("INJECTED_TOKEN", json.dumps(j.state))
        self.assertEqual(j.state["importProposal"]["preferences"], [])
        j.act("import_decide", approve=False)
        self.assertEqual(j.state["speaker"], old)
        j.act("import_propose", content=content)
        j.act("import_decide", approve=True)
        self.assertEqual(j.state["speaker"]["activeRevision"], 2)

    def test_private_files_are_not_world_readable_and_unknown_schema_is_preserved(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        with self.store.connect() as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(RuntimeError):
            Store(self.path)


class HTTPAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "index.html").write_text("<h1>Private alpha</h1>")
        self.store = Store(self.root / "store/alpha.sqlite3")
        self.server = make_server(self.store, self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        default = {"Content-Type": "application/json", "X-PostRiff-Request": "founder-alpha"}
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers={**default, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read(), dict(res.headers)
        except urllib.error.HTTPError as e:
            result = e.code, e.read(), dict(e.headers)
            e.close()
            return result

    def test_loopback_health_static_policy_and_full_authenticated_roundtrip(self):
        status, body, headers = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["phase0"], "incomplete")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        status, body, _ = self.request("/api/auth/verify", {"provider": "google", "proof": "postriff-fixture-verified", "principalKey": "http-test-principal-0001", "requestId": "http-test-request-0001"})
        self.assertEqual(status, 200)
        created = json.loads(body)
        access = {"Authorization": "Bearer " + created["token"]}
        path = "/api/workspaces/" + created["workspaceId"]
        status, body, _ = self.request(path + "/actions", {"expectedRevision": created["revision"], "action": "mode", "payload": {"mode": "niche"}}, access)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["revision"], created["revision"] + 1)
        self.assertEqual(self.request(path)[0], 403)
        self.assertEqual(self.request(path, headers=access)[0], 200)
        self.assertEqual(self.request("/")[0], 200)

    def test_cross_origin_csrf_dns_rebinding_and_unavailable_side_effect_routes(self):
        self.assertEqual(self.request("/api/workspaces", {}, {"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/workspaces", {}, {"X-PostRiff-Request": ""})[0], 403)
        self.assertEqual(self.request("/api/health", headers={"Host": "attacker.example"})[0], 403)
        for path in ("/api/publish", "/api/schedule", "/api/billing", "/api/connect", "/api/agent/exec"):
            self.assertEqual(self.request(path, {})[0], 404)
        self.assertEqual(self.request("/../../etc/passwd")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)

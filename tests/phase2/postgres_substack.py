"""Real PostgreSQL/RLS regressions for the hosted Substack integration.

Run only through scripts/substack_pg_test.py. Sessions, feeds, and identities are
synthetic; storage, row locks, transactions, membership checks, RLS and audit are
real PostgreSQL. No Substack authorization or live-provider acceptance is implied.
"""
from __future__ import annotations

import json
import copy
import hashlib
import os
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import psycopg
from psycopg.conninfo import conninfo_to_dict

from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.substack_service import HostedSubstackService
from postriff_phase2.substack_notifications import EVENT_TYPE as SUBSTACK_NOTICE_TYPE, scan as scan_substack_notifications
from postriff_phase2.notifications.service import NotificationService


def private_connection():
    """Reject every DSN except the runner's own marked, private Unix socket."""
    cluster = Path(os.environ.get("RAFII_SUBSTACK_TEST_CLUSTER_DIR", "/nonexistent"))
    if cluster.parent != Path("/tmp") or not cluster.name.startswith("rafii-substack-pg-test-"):
        raise RuntimeError("A fresh disposable Substack test cluster is required")
    marker = cluster / ".rafii-substack-disposable"
    if not marker.is_file() or marker.read_text().strip() != str(cluster / "data"):
        raise RuntimeError("The disposable-cluster marker does not match")
    dsn = os.environ.get("POSTRIFF_TEST_DSN", "")
    parsed = conninfo_to_dict(dsn)
    if parsed.get("host") != str(cluster / "socket") or parsed.get("dbname") != "postgres" or parsed.get("user") != "rafii_substack_test":
        raise RuntimeError("Only the runner's private synthetic database may be used")
    return psycopg.connect(dsn, client_encoding="utf8")


class NoProviderWrites:
    def __init__(self):
        self.calls = []

    def submit(self, *_args, **_kwargs):
        self.calls.append("submit")
        raise AssertionError("Manual Substack work reached a provider writer")

    def reconcile(self, *_args, **_kwargs):
        self.calls.append("reconcile")
        raise AssertionError("Manual Substack work reached a provider reconciliation")


class NoOutboundNotifications:
    def __init__(self):
        self.calls = []

    def send(self, *_args, **_kwargs):
        self.calls.append("send")
        raise AssertionError("A Substack manual target reached an external notification transport")


class SubstackPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with private_connection() as db:
            cluster = Path(os.environ["RAFII_SUBSTACK_TEST_CLUSTER_DIR"])
            assert db.execute("SHOW data_directory").fetchone()[0] == str(cluster / "data")
            assert db.execute("SHOW listen_addresses").fetchone()[0] == ""
            assert db.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.pr_workspaces'::regclass").fetchone()[0]

    def setUp(self):
        self.clock = [time.time()]
        self.identities = {name: str(uuid.uuid4()) for name in ("owner", "foreign", "editor", "approver", "viewer")}

        def verify(token):
            if token not in self.identities:
                raise AlphaError("Verified test session required.", 401)
            return self.identities[token]

        verify.auth_time = lambda token, principal: self.clock[0]
        self.verify = verify
        with private_connection() as db:
            for principal in self.identities.values():
                db.execute("INSERT INTO auth.users(id) VALUES(%s)", (principal,))
                db.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s)", (principal,))
            self.wid = str(db.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.identities["owner"],)).fetchone()[0])
            self.foreign_wid = str(db.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.identities["foreign"],)).fetchone()[0])
            for role in ("editor", "approver", "viewer"):
                db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active')", (self.wid, self.identities[role], role))
            for wid, token in ((self.wid, "owner"), (self.foreign_wid, "foreign")):
                state = initial_phase2_state(wid, self.identities[token], "Synthetic Substack QA", "studio", self.clock[0])
                db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
        self.repository = PostgresWorkspaceRepository(private_connection, verify, clock=lambda: self.clock[0])
        self.feed_calls = []

        def fixture_feed(url):
            self.feed_calls.append(url)
            return {"publication_url": url, "provenance": "public_feed", "items": [{"title": "Synthetic feed", "excerpt": "Fixture only"}]}

        self.service = HostedSubstackService(self.repository, enabled=True, clock=lambda: self.clock[0], feed_fetcher=fixture_feed)

    def tearDown(self):
        # Remove this test's workspace data so global notification scans remain
        # independent. Profiles/auth users have deliberate restrictive FKs;
        # those synthetic identities disappear with the whole private cluster.
        with private_connection() as db:
            db.execute("DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])", ([self.wid, self.foreign_wid],))
            for table in ("pr_notification_preferences", "pr_push_subscriptions"):
                db.execute(f"DELETE FROM public.{table} WHERE user_id=ANY(%s::uuid[])", (list(self.identities.values()),))

    def notifications(self):
        outbound = NoOutboundNotifications()
        hosted = SimpleNamespace(repository=self.repository, substack=self.service, public_base_url="https://rafii.invalid")
        notifications = NotificationService(hosted, email_transport=outbound, push_transport=outbound, sms_transport=outbound, clock=lambda: self.clock[0])
        # Real store/planner/SQL, with transports explicitly available to prove
        # that the Substack event filter, not missing credentials, denies sends.
        notifications.enabled = lambda: True
        notifications.push_enabled = lambda: True
        hosted.notifications = notifications
        with private_connection() as db:
            for principal in self.identities.values():
                db.execute("""INSERT INTO public.pr_notification_preferences(user_id,scope_key,category,in_app,email_mode,push_mode,sms_mode)
                    VALUES(%s,'*','*',true,'immediate','immediate','important_only') ON CONFLICT(user_id,scope_key,category) DO NOTHING""", (principal,))
                db.execute("""INSERT INTO public.pr_push_subscriptions(user_id,endpoint_sha256,endpoint_ciphertext,p256dh_ciphertext,auth_ciphertext,key_id)
                    VALUES(%s,%s,'synthetic-only','synthetic-only','synthetic-only','synthetic-only') ON CONFLICT(endpoint_sha256) DO NOTHING""",
                    (principal, hashlib.sha256(principal.encode()).hexdigest()))
        return hosted, notifications, outbound

    def notice_rows(self, wid=None):
        with private_connection() as db:
            return db.execute("""SELECT e.workspace_id::text,e.actor::text,e.dedupe_key,e.payload,d.user_id::text,d.channel,d.status
                FROM public.pr_notification_events e JOIN public.pr_notification_deliveries d ON d.event_id=e.id
                WHERE e.workspace_id=%s AND e.event_type=%s ORDER BY d.user_id""", (wid or self.wid, SUBSTACK_NOTICE_TYPE)).fetchall()

    def due_draft(self):
        target = datetime.fromtimestamp(self.clock[0] - 60, timezone.utc).isoformat().replace("+00:00", "Z")
        return self.approve(self.draft(scheduledFor=target))

    def snap(self, token="owner", wid=None):
        return self.service.workspace(wid or self.wid, token)

    def body(self, token="owner", wid=None, **fields):
        return {"expectedRevision": self.snap(token, wid)["revision"], **fields}

    def add(self, url="https://rafii-qa.substack.com", token="owner", wid=None):
        result = self.service.connect(wid or self.wid, token, self.body(token, wid, publicationUrl=url, mode="public_feed", confirmed=True))
        return next(c for c in result["connections"] if c["publicationUrl"] == url.rstrip("/"))

    def draft(self, connection=None, token="owner", **fields):
        connection = connection or self.add()
        values = {"connectionId": connection["id"], "title": "Piano teaching note", "body": "A synthetic editorial draft.", **fields}
        result = self.service.save_draft(self.wid, token, self.body(token, **values))
        return result["drafts"][-1]

    def approve(self, draft, token="owner"):
        result = self.service.approve(self.wid, token, draft["id"], self.body(token, contentHash=draft["contentHash"], confirmed=True))
        return next(d for d in result["drafts"] if d["id"] == draft["id"])

    def persisted(self, wid=None):
        with private_connection() as db:
            row = db.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (wid or self.wid,)).fetchone()
            return {"revision": row[0], "state": row[1]}

    def deny(self, operation, status, code=None):
        with self.assertRaises(AlphaError) as raised:
            operation()
        self.assertEqual(raised.exception.status, status, str(raised.exception))
        if code:
            self.assertEqual(raised.exception.code, code)
        return raised.exception

    def member(self, token, **changes):
        allowed = {"role", "status", "can_publish", "can_manage_connections"}
        assert set(changes) <= allowed
        with private_connection() as db:
            for name, value in changes.items():
                db.execute(f"UPDATE public.pr_memberships SET {name}=%s WHERE workspace_id=%s AND user_id=%s", (value, self.wid, self.identities[token]))

    def test_feature_default_off_and_official_modes_fail_without_mutation(self):
        disabled = HostedSubstackService(self.repository)
        self.deny(lambda: disabled.workspace(self.wid, "owner"), 404, "feature_disabled")
        before = self.persisted()
        for mode in ("official_authorized", "official_mcp_analytics", "official_partnership"):
            with self.subTest(mode=mode):
                self.deny(lambda: self.service.connect(self.wid, "owner", self.body(mode=mode, confirmed=True)), 409, "requires_official_approval")
        self.assertEqual(self.persisted(), before)

    def test_public_feed_persists_without_authentication_or_ownership_claim(self):
        connection = self.add()
        stored = self.persisted()["state"]["substack"]["connections"][0]
        self.assertEqual(stored, connection)
        self.assertEqual(connection["mode"], "public_feed")
        for flag in ("ownershipVerified", "accountAuthenticated", "analyticsConnected", "publishingAuthorized"):
            self.assertIs(connection[flag], False)
        self.assertEqual(self.feed_calls, [])
        self.assertNotIn("credential", json.dumps(stored).lower())
        self.deny(lambda: self.service.connect(self.wid, "owner", self.body(publicationUrl="https://other.substack.com", confirmed=False)), 403, "substack_consent_required")

    def test_role_boundaries_use_current_database_memberships(self):
        connection = self.add()
        draft = self.draft(connection, token="editor")
        for role in ("viewer", "approver"):
            with self.subTest(edit=role):
                self.deny(lambda: self.service.save_draft(self.wid, role, self.body(role, connectionId=connection["id"], body="Denied")), 403)
        for role in ("editor", "viewer", "approver"):
            with self.subTest(connect=role):
                self.deny(lambda: self.service.connect(self.wid, role, self.body(role, publicationUrl="https://foreign.substack.com", confirmed=True)), 403)
        self.deny(lambda: self.service.approve(self.wid, "editor", draft["id"], self.body("editor", contentHash=draft["contentHash"], confirmed=True)), 403)
        self.member("viewer", can_publish=True, can_manage_connections=True)
        self.deny(lambda: self.service.approve(self.wid, "viewer", draft["id"], self.body("viewer", contentHash=draft["contentHash"], confirmed=True)), 403)
        self.assertEqual(self.approve(draft, "approver")["status"], "approved")

    def test_editor_with_explicit_publish_permission_can_approve_then_loses_it(self):
        draft = self.draft()
        self.member("editor", can_publish=True)
        self.approve(draft, "editor")
        self.member("editor", can_publish=False)
        before = self.persisted()
        self.deny(lambda: self.service.handoff(self.wid, "editor", draft["id"], self.body("editor", contentHash=draft["contentHash"])), 403)
        self.assertEqual(self.persisted(), before)

    def test_cross_tenant_and_nonexistent_workspaces_are_indistinguishable(self):
        missing = str(uuid.uuid4())
        foreign = self.deny(lambda: self.service.workspace(self.foreign_wid, "owner"), 403)
        ghost = self.deny(lambda: self.service.workspace(missing, "owner"), 403)
        self.assertEqual(str(foreign), str(ghost))
        self.deny(lambda: self.service.capabilities(self.foreign_wid, "owner"), 403)
        self.deny(lambda: self.service.workspace(self.wid, "forged-session"), 401)
        before = self.persisted(self.foreign_wid)
        self.deny(lambda: self.service.connect(self.foreign_wid, "owner", {"expectedRevision": before["revision"], "publicationUrl": "https://forged.substack.com", "confirmed": True}), 403)
        self.assertEqual(self.persisted(self.foreign_wid), before)

    def test_cross_tenant_connection_and_draft_ids_do_not_cross_bind(self):
        foreign = self.add("https://foreign.substack.com", "foreign", self.foreign_wid)
        self.deny(lambda: self.service.save_draft(self.wid, "owner", self.body(connectionId=foreign["id"], body="Forged destination")), 404)
        draft = self.draft()
        for method in (self.service.approve, self.service.handoff, self.service.cancel, self.service.delete_draft):
            with self.subTest(method=method.__name__):
                self.deny(lambda: method(self.foreign_wid, "foreign", draft["id"], self.body("foreign", self.foreign_wid, contentHash=draft["contentHash"], confirmed=True)), 404)

    def test_revoked_membership_denies_reads_and_mutations_immediately(self):
        draft = self.draft()
        self.member("editor", can_publish=True, can_manage_connections=True)
        revision = self.snap("editor")["revision"]
        self.member("editor", status="revoked")
        before = self.persisted()
        self.deny(lambda: self.service.workspace(self.wid, "editor"), 403)
        self.deny(lambda: self.service.save_draft(self.wid, "editor", {"expectedRevision": revision, "connectionId": draft["connectionId"], "body": "Forged after revocation"}), 403)
        self.deny(lambda: self.service.approve(self.wid, "editor", draft["id"], {"expectedRevision": revision, "contentHash": draft["contentHash"], "confirmed": True}), 403)
        self.assertEqual(self.persisted(), before)

    def test_stale_and_boolean_revisions_do_not_commit(self):
        connection = self.add()
        revision = self.snap()["revision"]
        self.draft(connection)
        before = self.persisted()
        for stale in (revision, True, "2", None):
            with self.subTest(revision=stale):
                self.deny(lambda: self.service.save_draft(self.wid, "owner", {"expectedRevision": stale, "connectionId": connection["id"], "body": "Must not commit"}), 409, "workspace_revision_conflict")
        self.assertEqual(self.persisted(), before)

    def test_concurrent_same_revision_allows_exactly_one_commit(self):
        connection = self.add()
        before = self.persisted()

        def save(number):
            try:
                self.service.save_draft(self.wid, "editor", {"expectedRevision": before["revision"], "connectionId": connection["id"], "body": f"Concurrent draft {number}"})
                return "saved"
            except AlphaError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, (1, 2)))
        self.assertCountEqual(outcomes, ["saved", "workspace_revision_conflict"])
        self.assertEqual(self.persisted()["revision"], before["revision"] + 1)
        self.assertEqual(len(self.snap()["drafts"]), 1)

    def test_approval_requires_exact_hash_confirmation_and_destination(self):
        first = self.draft()
        second_connection = self.add("https://second.substack.com")
        second = self.draft(second_connection)
        self.assertNotEqual(first["contentHash"], second["contentHash"])
        before = self.persisted()
        self.deny(lambda: self.service.approve(self.wid, "owner", first["id"], self.body(contentHash=first["contentHash"], confirmed="true")), 403)
        self.deny(lambda: self.service.approve(self.wid, "owner", first["id"], self.body(contentHash="0" * 64, confirmed=True)), 409)
        self.deny(lambda: self.service.approve(self.wid, "owner", second["id"], self.body(contentHash=first["contentHash"], confirmed=True)), 409)
        self.assertEqual(self.persisted(), before)

    def test_incomplete_articles_save_but_cannot_be_approved(self):
        connection = self.add()
        for values in ({"title": "", "body": "Body without article title"}, {"title": "Title only", "body": "   "}):
            with self.subTest(incomplete=values):
                draft = self.draft(connection, **values)
                before = self.persisted()
                self.deny(lambda: self.service.approve(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"], confirmed=True)), 400, "invalid_substack_draft")
                self.assertEqual(self.persisted(), before)
                self.assertEqual(self.snap()["queue"], [])
        note = self.draft(connection, title="", body="A complete short Note", contentType="note")
        self.assertEqual(self.approve(note)["status"], "approved")

    def test_invalid_unicode_and_multiline_titles_never_commit(self):
        connection = self.add()
        before = self.persisted()
        for fields in ({"title": "Broken \ud800 title"}, {"body": "Broken \udfff body"}, {"title": "First\nSecond"}, {"title": "First\rSecond"}, {"title": "First\tSecond"}):
            with self.subTest(field=next(iter(fields))):
                payload = {"connectionId": connection["id"], "title": "Valid", "body": "Valid", **fields}
                self.deny(lambda: self.service.save_draft(self.wid, "owner", self.body(**payload)), 400, "invalid_substack_draft")
                self.assertEqual(self.persisted(), before)

    def test_sample_workspace_remains_readable_but_cannot_mutate_or_fetch(self):
        connection = self.add()
        draft = self.draft(connection)
        with private_connection() as db:
            db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{workspace,sample}','true'::jsonb,true) WHERE id=%s", (self.wid,))
        before = self.persisted()
        self.assertEqual(self.snap()["drafts"][0]["id"], draft["id"])
        operations = (
            lambda: self.service.connect(self.wid, "owner", self.body(publicationUrl="https://new.substack.com", confirmed=True)),
            lambda: self.service.disconnect(self.wid, "owner", connection["id"], self.body()),
            lambda: self.service.refresh(self.wid, "owner", connection["id"], self.body()),
            lambda: self.service.save_draft(self.wid, "owner", self.body(connectionId=connection["id"], body="Blocked")),
            lambda: self.service.approve(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"], confirmed=True)),
            lambda: self.service.handoff(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"])),
            lambda: self.service.cancel(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"])),
            lambda: self.service.delete_draft(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"])),
        )
        for index, operation in enumerate(operations):
            with self.subTest(operation=index):
                self.deny(operation, 403, "sample_workspace")
                self.assertEqual(self.persisted(), before)
        self.assertEqual(self.feed_calls, [])

    def test_each_bound_editorial_change_invalidates_approval_and_queue(self):
        connection = self.add()
        second = self.add("https://different.substack.com")
        target = datetime.fromtimestamp(self.clock[0] + 300, timezone.utc).isoformat()
        for change in ({"title": "Different title"}, {"body": "Different body"}, {"contentType": "note"}, {"audience": "paid"}, {"scheduledFor": target}, {"connectionId": second["id"]}):
            with self.subTest(field=next(iter(change))):
                draft = self.approve(self.draft(connection))
                result = self.service.save_draft(self.wid, "editor", self.body("editor", **change), draft["id"])
                edited = next(d for d in result["drafts"] if d["id"] == draft["id"])
                self.assertEqual(edited["status"], "draft")
                self.assertIsNone(edited["approvedHash"])
                self.assertNotEqual(edited["contentHash"], draft["contentHash"])
                self.assertTrue(all(q["status"] == "canceled" for q in result["queue"] if q["draftId"] == draft["id"]))
                self.deny(lambda: self.service.handoff(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"])), 409)

    def test_repeated_approval_and_handoff_reuse_one_manual_receipt(self):
        draft = self.approve(self.draft())
        self.approve(draft)
        first = self.service.handoff(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"]))
        second = self.service.handoff(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"]))
        self.assertEqual(first["handoff"]["receiptId"], second["handoff"]["receiptId"])
        self.assertIs(second["handoff"]["autoPublished"], False)
        self.assertEqual(len(second["queue"]), 1)
        self.assertEqual(second["queue"][0]["status"], "handoff_prepared")
        self.assertEqual(self.persisted()["state"]["phase2"]["jobs"], [])

    def test_disconnect_cancels_queue_and_reconnect_does_not_restore_approval(self):
        connection = self.add()
        self.service.refresh(self.wid, "owner", connection["id"], self.body())
        draft = self.approve(self.draft(connection))
        result = self.service.disconnect(self.wid, "owner", connection["id"], self.body())
        self.assertEqual(result["connections"][0]["status"], "disconnected")
        self.assertEqual(result["queue"][0]["status"], "canceled")
        self.assertIsNone(result["drafts"][0]["approvedHash"])
        reconnected = self.add()
        self.assertEqual(reconnected["id"], connection["id"])
        self.assertEqual(reconnected["health"], "not_checked")
        self.assertEqual(reconnected["feedConsentVersion"], 1)
        self.assertIsNone(reconnected["lastCheckedAt"])
        self.assertEqual(len(self.snap()["connections"]), 1)
        self.deny(lambda: self.service.handoff(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"])), 409, "substack_approval_required")

    def test_due_manual_queue_is_not_a_provider_publish_job(self):
        target = datetime.fromtimestamp(self.clock[0] + 60, timezone.utc).isoformat()
        draft = self.approve(self.draft(scheduledFor=target))
        before = self.persisted()
        self.assertFalse(self.snap()["queue"][0]["due"])
        self.clock[0] += 120
        self.assertTrue(self.snap()["queue"][0]["due"])
        social = NoProviderWrites()
        worker = PostgresWorker(private_connection, social=social, clock=lambda: self.clock[0], worker_id="substack-private-test")
        self.assertFalse(worker.step())
        self.assertEqual(social.calls, [])
        after = self.persisted()
        self.assertEqual(after, before)
        self.assertEqual(after["state"]["phase2"]["jobs"], [])
        self.assertEqual(after["state"]["substack"]["queue"][0]["kind"], "manual_handoff")
        self.assertIs(after["state"]["substack"]["queue"][0]["autoPublished"], False)

    def test_cancel_then_delete_removes_content_and_queue(self):
        draft = self.approve(self.draft())
        self.deny(lambda: self.service.delete_draft(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"])), 409, "substack_cancel_required")
        self.service.cancel(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"]))
        result = self.service.delete_draft(self.wid, "editor", draft["id"], self.body("editor", contentHash=draft["contentHash"]))
        self.assertEqual(result["drafts"], [])
        self.assertEqual(result["queue"], [])
        self.assertNotIn(draft["body"], json.dumps(self.persisted()["state"]["substack"]))

    def test_failed_transaction_rolls_back_state_and_audit_together(self):
        connection = self.add()
        before = self.persisted()
        with private_connection() as db:
            count = db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s", (self.wid,)).fetchone()[0]

        def injected_failure(*_args):
            raise AlphaError("Injected transaction effect failure", 503)

        self.repository.effects.append(injected_failure)
        self.deny(lambda: self.service.save_draft(self.wid, "owner", self.body(connectionId=connection["id"], body="Must roll back")), 503)
        self.assertEqual(self.persisted(), before)
        with private_connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s", (self.wid,)).fetchone()[0], count)

    def test_browser_rls_hides_foreign_data_and_denies_direct_writes(self):
        draft = self.draft()
        with private_connection() as db:
            db.execute("SET LOCAL ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (self.identities["viewer"],))
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_workspaces WHERE id=%s", (self.foreign_wid,)).fetchone()[0], 0)
            own = db.execute("SELECT state->'substack' FROM public.pr_workspaces WHERE id=%s", (self.wid,)).fetchone()[0]
            self.assertEqual(own["drafts"][0]["id"], draft["id"])
        for sql in ("UPDATE public.pr_workspaces SET state='{}'::jsonb", "DELETE FROM public.pr_workspaces", "DELETE FROM public.pr_audit_events"):
            with self.subTest(sql=sql), private_connection() as db:
                db.execute("SET LOCAL ROLE authenticated")
                db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (self.identities["owner"],))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute(sql)
                db.rollback()
        self.member("viewer", status="revoked")
        with private_connection() as db:
            db.execute("SET LOCAL ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (self.identities["viewer"],))
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_workspaces WHERE id=%s", (self.wid,)).fetchone()[0], 0)

    def test_api_tokens_allow_only_read_and_authorized_drafts(self):
        connection = self.add()
        read = self.repository.api_tokens.create(self.wid, "owner", {"name": "Substack QA read", "scopes": ["read"], "expiresDays": 30})
        draft_token = self.repository.api_tokens.create(self.wid, "owner", {"name": "Substack QA draft", "scopes": ["read", "draft"], "expiresDays": 30})
        self.assertEqual(self.snap(read["secret"])["revision"], self.snap()["revision"])
        payload = self.body(connectionId=connection["id"], body="API draft only")
        self.deny(lambda: self.service.save_draft(self.wid, read["secret"], payload), 403, "token_scope_denied")
        created = self.service.save_draft(self.wid, draft_token["secret"], payload)["drafts"][-1]
        token = draft_token["secret"]
        for operation in (
            lambda: self.service.connect(self.wid, token, self.body(publicationUrl="https://new.substack.com", confirmed=True)),
            lambda: self.service.disconnect(self.wid, token, connection["id"], self.body()),
            lambda: self.service.refresh(self.wid, token, connection["id"], self.body()),
            lambda: self.service.approve(self.wid, token, created["id"], self.body(contentHash=created["contentHash"], confirmed=True)),
            lambda: self.service.handoff(self.wid, token, created["id"], self.body(contentHash=created["contentHash"])),
            lambda: self.service.cancel(self.wid, token, created["id"], self.body(contentHash=created["contentHash"])),
            lambda: self.service.delete_draft(self.wid, token, created["id"], self.body(contentHash=created["contentHash"])),
        ):
            self.deny(operation, 403, "token_scope_denied")
        self.deny(lambda: self.service.workspace(self.foreign_wid, token), 403)
        self.repository.api_tokens.revoke(self.wid, "owner", draft_token["item"]["tokenId"])
        self.deny(lambda: self.service.workspace(self.wid, token), 401, "api_token_invalid")
        self.assertEqual(self.feed_calls, [])

    def test_refresh_delivers_public_fixture_without_persisting_feed_contents(self):
        connection = self.add()
        result = self.service.refresh(self.wid, "viewer", connection["id"], self.body("viewer"))
        self.assertEqual(result["feed"]["items"][0]["excerpt"], "Fixture only")
        self.assertEqual(result["connections"][0]["health"], "public_feed_reachable")
        self.assertNotIn("Fixture only", json.dumps(self.persisted()))
        self.assertEqual(self.feed_calls, [connection["publicationUrl"]])

    def test_refresh_rechecks_revocation_before_delivering_result(self):
        connection = self.add()

        def revoke_during_fetch(url):
            self.member("viewer", status="revoked")
            return {"items": [{"excerpt": "MUST NOT LEAK"}]}

        self.service.feed_fetcher = revoke_during_fetch
        self.deny(lambda: self.service.refresh(self.wid, "viewer", connection["id"], self.body("viewer")), 403)
        self.assertIsNone(self.snap()["connections"][0]["lastCheckedAt"])
        self.assertNotIn("MUST NOT LEAK", json.dumps(self.persisted()))

    def test_refresh_rechecks_disconnect_and_revision_after_fetch(self):
        connection = self.add()

        def disconnect_during_fetch(url):
            self.service.disconnect(self.wid, "owner", connection["id"], self.body())
            return {"items": [{"excerpt": "STALE RESULT"}]}

        self.service.feed_fetcher = disconnect_during_fetch
        self.deny(lambda: self.service.refresh(self.wid, "viewer", connection["id"], self.body("viewer")), 409, "workspace_revision_conflict")
        self.assertEqual(self.snap()["connections"][0]["status"], "disconnected")
        self.assertNotIn("STALE RESULT", json.dumps(self.persisted()))

    def test_refresh_failure_returns_stable_error_and_audits_failure(self):
        connection = self.add()

        def fail_fetch(url):
            raise AlphaError("UNTRUSTED PROVIDER ERROR SECRET", 502)

        self.service.feed_fetcher = fail_fetch
        before = self.persisted()
        error = self.deny(lambda: self.service.refresh(self.wid, "owner", connection["id"], self.body()), 503, "substack_feed_unavailable")
        self.assertNotIn("SECRET", str(error))
        self.assertEqual(self.persisted(), before)
        with private_connection() as db:
            records = db.execute("SELECT kind,meta FROM public.pr_audit_events WHERE workspace_id=%s", (self.wid,)).fetchall()
        self.assertIn("substack.feed_refresh_failed", {r[0] for r in records})
        self.assertNotIn("UNTRUSTED", json.dumps(records))

    def test_refresh_rate_limit_prevents_the_eleventh_fetch(self):
        connection = self.add()
        for _ in range(10):
            self.service.refresh(self.wid, "owner", connection["id"], self.body())
        self.deny(lambda: self.service.refresh(self.wid, "owner", connection["id"], self.body()), 429)
        self.assertEqual(len(self.feed_calls), 10)

    def test_manual_notifications_are_in_app_only_current_approvers_and_deduplicated(self):
        draft = self.due_draft()
        self.member("editor", can_publish=True)
        self.member("viewer", can_publish=True)
        hosted, notifications, outbound = self.notifications()
        before = self.persisted()
        result = scan_substack_notifications(hosted, notifications)
        self.assertEqual(result["status"], "available", result)
        self.assertEqual(result["created"], 3, result)
        rows = self.notice_rows()
        self.assertEqual({r[4] for r in rows}, {self.identities[name] for name in ("owner", "approver", "editor")})
        for row in rows:
            self.assertEqual(row[0], self.wid)
            self.assertEqual(row[1], row[4], "a verified recipient is bound as the event actor")
            self.assertEqual(row[5:], ("in_app", "delivered"))
            self.assertIn(draft["contentHash"], row[2])
            self.assertEqual(row[3]["href"], "/app/channels?connect=substack&substackDraft=" + draft["id"])
            self.assertNotIn(draft["body"], json.dumps(row[3]))
            self.assertNotIn(draft["title"], json.dumps(row[3]))
            self.assertNotIn("rafii-qa.substack.com", json.dumps(row[3]))
        self.assertEqual(scan_substack_notifications(hosted, notifications)["created"], 0)
        self.assertEqual(self.notice_rows(), rows)
        self.assertEqual(self.notice_rows(self.foreign_wid), [])
        self.assertEqual(self.persisted(), before, "a reminder cannot mutate the durable manual queue")
        self.assertEqual(before["state"]["phase2"]["jobs"], [])
        self.assertEqual(outbound.calls, [])
        with private_connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_notification_deliveries WHERE workspace_id=%s AND channel<>'in_app'", (self.wid,)).fetchone()[0], 0)

    def test_manual_notifications_use_existing_delivery_rls_and_hide_after_membership_revocation(self):
        self.due_draft()
        hosted, notifications, _outbound = self.notifications()
        self.assertEqual(scan_substack_notifications(hosted, notifications)["created"], 2)

        def count_as(token):
            with private_connection() as db:
                db.execute("SET LOCAL ROLE authenticated")
                db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (self.identities[token],))
                return db.execute("SELECT count(*) FROM public.pr_notification_deliveries WHERE workspace_id=%s", (self.wid,)).fetchone()[0]

        self.assertEqual(count_as("owner"), 1)
        self.assertEqual(count_as("approver"), 1)
        self.assertEqual(count_as("viewer"), 0)
        self.assertEqual(count_as("foreign"), 0)
        self.member("approver", status="revoked")
        self.assertEqual(count_as("approver"), 0)

    def test_manual_notifications_skip_changed_bindings_disconnected_canceled_and_restricted_workspaces(self):
        self.due_draft()
        original = self.persisted()["state"]
        hosted, notifications, outbound = self.notifications()
        mutations = {
            "sample": lambda state: state["workspace"].update(sample=True),
            "workspace id": lambda state: state["workspace"].update(id=self.foreign_wid),
            "deleting": lambda state: state.update(accountDeletion={"status": "requested"}),
            "blocked": lambda state: state.update(accountBlock={"status": "active"}),
            "disconnected": lambda state: state["substack"]["connections"][0].update(status="disconnected"),
            "destination edited under same id": lambda state: state["substack"]["connections"][0].update(publicationUrl="https://another.substack.com"),
            "body edited under same hash": lambda state: state["substack"]["drafts"][0].update(body="Different unapproved content"),
            "approval revoked": lambda state: state["substack"]["drafts"][0].update(approvedHash=None),
            "draft canceled": lambda state: state["substack"]["drafts"][0].update(status="canceled"),
            "queue canceled": lambda state: state["substack"]["queue"][0].update(status="canceled"),
            "prepared": lambda state: state["substack"]["queue"][0].update(status="handoff_prepared"),
            "foreign destination": lambda state: state["substack"]["queue"][0].update(connectionId="sc_" + "f" * 32),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                state = copy.deepcopy(original)
                mutate(state)
                with private_connection() as db:
                    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), self.wid))
                result = scan_substack_notifications(hosted, notifications)
                self.assertEqual(result["failed"], 0, result)
                self.assertEqual(result["created"], 0, result)
                self.assertEqual(self.notice_rows(), [])
        with private_connection() as db:
            db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(original), self.wid))
        self.assertEqual(scan_substack_notifications(hosted, notifications)["created"], 2)
        self.assertEqual(outbound.calls, [])

    def test_manual_notifications_require_active_unblocked_profiles_and_approve_permission(self):
        self.due_draft()
        self.member("editor", role="admin")
        self.member("viewer", can_publish=True)
        hosted, notifications, outbound = self.notifications()
        with private_connection() as db:
            db.execute("UPDATE public.pr_profiles SET deleted_at=now() WHERE user_id=%s", (self.identities["owner"],))
            db.execute("""INSERT INTO public.pr_account_blocks(user_id,reason_code,approval_ref,blocked_by,block_action_id)
                VALUES(%s,'security','synthetic-substack-qa',%s,%s)""", (self.identities["approver"], self.identities["owner"], str(uuid.uuid4())))
        result = scan_substack_notifications(hosted, notifications)
        self.assertEqual(result["created"], 0, result)
        self.assertEqual(result["failed"], 0, result)
        self.assertEqual(self.notice_rows(), [])
        self.assertEqual(outbound.calls, [])

    def test_manual_notifications_obey_feature_flags_and_future_target_without_revision_change(self):
        target = datetime.fromtimestamp(self.clock[0] + 120, timezone.utc).isoformat().replace("+00:00", "Z")
        self.approve(self.draft(scheduledFor=target))
        hosted, notifications, outbound = self.notifications()
        before = self.persisted()
        self.assertEqual(scan_substack_notifications(hosted, notifications)["created"], 0)
        self.clock[0] += 121
        self.service.enabled = False
        self.assertEqual(scan_substack_notifications(hosted, notifications)["status"], "disabled")
        self.service.enabled = True
        notifications.enabled = lambda: False
        self.assertEqual(scan_substack_notifications(hosted, notifications)["status"], "disabled")
        notifications.enabled = lambda: True
        self.assertEqual(scan_substack_notifications(hosted, notifications)["created"], 2)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(outbound.calls, [])

    def test_manual_notifications_cold_scan_paginates_stale_first_workspace(self):
        self.due_draft()
        connection = self.add(url="https://foreign-qa.substack.com", token="foreign", wid=self.foreign_wid)
        target = datetime.fromtimestamp(self.clock[0] - 60, timezone.utc).isoformat().replace("+00:00", "Z")
        saved = self.service.save_draft(self.foreign_wid, "foreign", self.body("foreign", self.foreign_wid, connectionId=connection["id"], title="Foreign isolated draft", body="Synthetic only", scheduledFor=target))
        draft = saved["drafts"][0]
        self.service.approve(self.foreign_wid, "foreign", draft["id"], self.body("foreign", self.foreign_wid, contentHash=draft["contentHash"], confirmed=True))
        stale, valid = sorted((self.wid, self.foreign_wid))
        state = self.persisted(stale)["state"]
        state["substack"]["drafts"][0]["body"] = "Approval hash is now stale"
        with private_connection() as db:
            db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), stale))
        # A fresh service has no process-local scan cursor. An invalid first
        # candidate must not consume the only delivery slot on every cold start.
        hosted, notifications, outbound = self.notifications()
        result = scan_substack_notifications(hosted, notifications, limit=1, budget_seconds=5.0)
        self.assertEqual(result["created"], 1, result)
        self.assertEqual(result["failed"], 0, result)
        self.assertEqual(self.notice_rows(stale), [])
        self.assertEqual(len(self.notice_rows(valid)), 1)
        self.assertEqual(outbound.calls, [])

    def test_substack_audit_is_complete_content_free_and_tenant_scoped(self):
        draft = self.approve(self.draft())
        self.service.handoff(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"]))
        self.service.cancel(self.wid, "owner", draft["id"], self.body(contentHash=draft["contentHash"]))
        self.service.disconnect(self.wid, "owner", draft["connectionId"], self.body())
        with private_connection() as db:
            records = db.execute("SELECT kind,subject,meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'substack.%%'", (self.wid,)).fetchall()
        kinds = {r[0] for r in records}
        self.assertTrue({"substack.feed_added", "substack.draft_saved", "substack.draft_approved", "substack.handoff_prepared", "substack.draft_canceled", "substack.feed_disconnected"} <= kinds)
        self.assertNotIn(draft["body"], json.dumps(records))
        self.assertNotIn(draft["title"], json.dumps(records))
        with private_connection() as db:
            db.execute("SET LOCAL ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (self.identities["foreign"],))
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s", (self.wid,)).fetchone()[0], 0)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SubstackPostgresTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({
        "status": "pass" if result.wasSuccessful() else "fail",
        "execution": "real-disposable-postgresql-with-synthetic-provider",
        "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "liveProviderAcceptance": False, "driver": psycopg.__version__,
    }))
    raise SystemExit(0 if result.wasSuccessful() else 1)

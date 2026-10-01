"""G2-OUT customer business results against a disposable PostgreSQL (PRD R-OUT-01..03, AC16–AC19, AC28–AC30, AC36).

Run: RAFII_PG_PORT=55882 PYTHONPATH=src:tests python scripts/rafii_pg_private.py postgres_results
Synthetic only: the vault key, identities, DNS answers and the producer are local fixtures; nothing leaves the machine.
"""
import io
import json
import logging
import os
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import flags
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.results import model, signing
from postriff_phase2.results import service as results_service
from postriff_phase2.results.http import ensure

ROOT = Path(__file__).resolve().parents[2]
DSN = "host=127.0.0.1 port=55438 dbname=postgres"
MIGRATION = ROOT / "migrations/postriff/080_customer_results.sql"
TABLES = ("pr_result_connections", "pr_tracking_links", "pr_result_events", "pr_result_quarantine", "pr_link_clicks", "pr_result_mutations")
DAY = 86400
BROWSER = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

flags.attach({"RAFII_RESULTS_ENABLED": "1"})
CLOCK = [time.time()]
USERS = {}


def connection(**kwargs):
    return psycopg.connect(DSN, client_encoding="utf8", **kwargs)


def verify(token):
    if token not in USERS:
        raise AlphaError("Verified session required.", 401)
    return USERS[token]


verify.session_id = lambda token, principal: "results-" + principal
verify.auth_time = lambda token, principal: CLOCK[0]


def resolver(host, port, type=None):   # noqa: A002 - socket.getaddrinfo's keyword
    address = {"internal.example.org": "10.1.2.3"}.get(host, "93.184.216.34")
    return [(2, 1, 6, "", (address, port))]


SERVICE = HostedWorkspaceService(connection, verify, clock=lambda: CLOCK[0], vault=CredentialVault(CredentialVault.generate_key()),
                                 public_base_url="https://app.example.org")
RESULTS = ensure(SERVICE)
RESULTS.resolver = resolver
APP = HostedApplication(service=SERVICE, public_auth={})


def key():
    return "k-" + uuid.uuid4().hex


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def ev(event_id, **extra):
    return {"eventId": event_id, "type": "lead", "occurredAt": iso(CLOCK[0] - 60), **extra}


def user():
    ident = str(uuid.uuid4())
    with connection() as db:
        db.execute("INSERT INTO auth.users(id) VALUES(%s)", (ident,))
    USERS["t-" + ident] = ident
    return "t-" + ident, ident


def tenant(*roles):
    """A fresh workspace with its owner's session, plus one member session per extra role."""
    owner, _ = user()
    wid = SERVICE.bootstrap(owner, "studio")["workspaceId"]
    sessions = {"owner": owner}
    for role in roles:
        token, ident = user()
        with connection() as db:
            db.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (ident,))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active')", (wid, ident, role))
        sessions[role] = token
    return SimpleNamespace(wid=wid, **sessions)


def refusal(fn, *args):
    try:
        fn(*args)
    except AlphaError as error:
        return error.status, error.code
    raise AssertionError("expected a refusal")


def connect(t, **extra):
    out = RESULTS.create_connection(t.wid, t.owner, {"label": "Booking form", "producer": "booking", "idempotencyKey": key(), **extra})
    return out["connection"], out["secret"]


def deliver(connection_id, secret, event, at=None):
    raw = json.dumps(event).encode()
    out = RESULTS.ingest(connection_id, signing.sign(secret, CLOCK[0] if at is None else at, raw), raw)
    return out.status, out.body


def app_call(method, path, raw=b"", headers=None, session=None, query=""):
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "CONTENT_TYPE": "application/json", "HTTP_HOST": "app.example.org", "wsgi.url_scheme": "https", **(headers or {})}
    if session:
        environ.update({"HTTP_AUTHORIZATION": "Bearer " + session, "HTTP_X_POSTRIFF_REQUEST": "founder-alpha", "HTTP_ORIGIN": "https://app.example.org"})
    seen = {}

    def start_response(status, response_headers, exc_info=None):
        seen.update(status=int(status.split()[0]), headers=dict(response_headers))

    body = b"".join(APP(environ, start_response))
    return seen["status"], seen["headers"], body


class Base(unittest.TestCase):
    def setUp(self):
        CLOCK[0] = time.time()


class AC30MigrationTest(Base):
    def test_ac30_migration_reapplies_with_forced_rls_and_no_browser_writes(self):
        for _ in range(2):    # already applied by rls.sql; two more passes must be no-ops
            subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/psql", DSN, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(MIGRATION)],
                           check=True, stdout=subprocess.DEVNULL, env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})
        with connection() as db:
            for table in TABLES:
                self.assertEqual(db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (f"public.{table}",)).fetchone(), (True, True), table)
                policies = {r[0] for r in db.execute("SELECT policyname FROM pg_policies WHERE schemaname='public' AND tablename=%s", (table,)).fetchall()}
                self.assertEqual(policies, {"trusted_write"} if table == "pr_result_mutations" else {"trusted_write", "tenant_read"}, table)
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    self.assertFalse(db.execute("SELECT has_table_privilege('authenticated',%s,%s)", (f"public.{table}", privilege)).fetchone()[0], (table, privilege))
                self.assertFalse(db.execute("SELECT has_table_privilege('anon',%s,'SELECT')", (f"public.{table}",)).fetchone()[0], table)
            self.assertFalse(db.execute("SELECT has_table_privilege('authenticated','public.pr_result_mutations','SELECT')").fetchone()[0])
            for column in ("secret_ciphertext", "previous_ciphertext", "secret_key_id"):
                self.assertFalse(db.execute("SELECT has_column_privilege('authenticated','public.pr_result_connections',%s,'SELECT')", (column,)).fetchone()[0], column)
            self.assertTrue(db.execute("SELECT has_column_privilege('authenticated','public.pr_result_connections','last_error_code','SELECT')").fetchone()[0])
            indexes = {r[0] for r in db.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='pr_result_events'").fetchall()}
            self.assertTrue({"pr_result_events_occurred_idx", "pr_result_events_first_party_uidx", "pr_result_events_declared_uidx",
                             "pr_result_events_one_reversal_uidx"} <= indexes)
            self.assertEqual(db.execute("SELECT count(*) FROM pg_trigger WHERE tgrelid='public.pr_result_events'::regclass AND tgname='pr_result_events_append_only'").fetchone()[0], 1)


class AC16ProvenanceTest(Base):
    def test_ac16_classes_stay_apart_null_is_not_zero_and_currencies_never_add(self):
        t = tenant()
        empty = RESULTS.summary(t.wid, t.owner)
        self.assertEqual(empty["dataState"], "unavailable")
        self.assertEqual(empty["classes"], {"provider_native": None, "first_party_reported": None, "user_declared": None})
        self.assertIsNone(empty["clicks"])
        now = CLOCK[0]
        RESULTS.declare(t.wid, t.owner, {"type": "lead", "occurredAt": iso(now - 3600), "quantity": 2, "idempotencyKey": key()})
        RESULTS.declare(t.wid, t.owner, {"type": "sale", "occurredAt": iso(now - 3600), "amount": {"minor": 12000, "currency": "USD"}, "idempotencyKey": key()})
        RESULTS.declare(t.wid, t.owner, {"type": "sale", "occurredAt": iso(now - 3600), "amount": {"minor": 280000, "currency": "twd"}, "idempotencyKey": key()})
        self.assertEqual(refusal(RESULTS.declare, t.wid, t.owner, {"type": "lead", "occurredAt": iso(now), "amount": {"minor": 1, "currency": "usd"},
                                                                    "idempotencyKey": key()}), (400, "result_amount_not_allowed"))
        conn, secret = connect(t)
        status, body = deliver(conn["id"], secret, {"eventId": "bk-1", "type": "booking", "occurredAt": iso(now - 600),
                                                    "amount": {"minor": 5000, "currency": "usd"}})
        self.assertEqual((status, body["status"]), (200, "accepted"))
        summary = RESULTS.summary(t.wid, t.owner)
        declared, reported = summary["classes"]["user_declared"], summary["classes"]["first_party_reported"]
        self.assertEqual(declared["counts"], {"lead": 2, "sale": 2})
        self.assertEqual(declared["money"], {"usd": {"minor": 12000, "events": 1}, "twd": {"minor": 280000, "events": 1}})
        self.assertEqual(reported["counts"], {"booking": 1})
        self.assertEqual(reported["money"], {"usd": {"minor": 5000, "events": 1}})   # the same currency in another class is never added
        self.assertIsNone(summary["classes"]["provider_native"])
        self.assertEqual(summary["coverage"]["providerNative"], "not_connected")
        self.assertEqual((summary["dataState"], summary["period"]["open"]), ("partial", True))   # the current period can still change
        self.assertFalse({"total", "roi", "revenue"} & set(summary))
        past = RESULTS.summary(t.wid, t.owner, start=now - 90 * DAY, end=now - 60 * DAY)
        self.assertEqual(past["dataState"], "available")
        self.assertEqual(past["classes"], {"provider_native": None, "first_party_reported": None, "user_declared": None})
        # Declared and reported results are told apart row by row too.
        provenances = {item["provenance"] for item in RESULTS.events(t.wid, t.owner)["items"]}
        self.assertEqual(provenances, {"user_declared", "first_party_reported"})
        self.assertEqual(len(RESULTS.events(t.wid, t.owner, {"provenance": "first_party_reported"})["items"]), 1)


class AC17ReceiverTest(Base):
    def test_ac17_signed_booking_associates_with_its_own_campaign_link(self):
        t = tenant()
        link = RESULTS.create_link(t.wid, t.owner, {"destination": "https://example.org/book?utm_source=ig", "campaignRef": "spring-workshop",
                                                    "label": "Spring workshop", "idempotencyKey": key()})["link"]
        self.assertEqual(link["url"], "https://app.example.org/api/l/" + link["slug"])
        location = RESULTS.redirect(link["slug"], "GET", BROWSER)
        self.assertTrue(location.startswith(f"https://example.org/book?utm_source=ig&rafii_ref={link['slug']}."))
        ref = location.rsplit("rafii_ref=", 1)[1]
        conn, secret = connect(t)
        status, body = deliver(conn["id"], secret, {"eventId": "bk-1", "type": "booking", "occurredAt": iso(CLOCK[0] - 60), "rafii_ref": ref,
                                                    "email": "visitor@example.com", "name": "A Visitor"})
        self.assertEqual((status, body["attribution"]), (200, "associated"))
        item = RESULTS.events(t.wid, t.owner)["items"][0]
        self.assertEqual((item["linkId"], item["campaignRef"], item["attribution"], item["provenance"]),
                         (link["id"], "spring-workshop", "associated", "first_party_reported"))
        self.assertEqual(item["connection"], {"label": "Booking form", "producer": "booking"})
        listed = RESULTS.links(t.wid, t.owner)["items"][0]
        self.assertEqual((listed["associatedResults"], listed["clicks"]["counted"]), ({"first_party_reported": 1}, 1))
        with connection() as db:
            stored = db.execute("SELECT row_to_json(e)::text FROM public.pr_result_events e WHERE id=%s", (body["receiptId"],)).fetchone()[0]
        self.assertNotIn("visitor@example.com", stored)      # unknown fields are dropped, never stored
        self.assertNotIn("A Visitor", stored)
        reported = RESULTS.summary(t.wid, t.owner)["classes"]["first_party_reported"]
        self.assertEqual((reported["associated"], reported["unattributed"]), (1, 0))

    def test_ac17_bad_signature_stale_timestamp_missing_header_and_tampered_body(self):
        t = tenant()
        conn, secret = connect(t)
        event = ev("sig-1")
        raw = json.dumps(event).encode()
        cases = [(signing.sign(signing.new_secret(), CLOCK[0], raw), raw, "result_signature_invalid", "signature_mismatch"),
                 (signing.sign(secret, CLOCK[0] - signing.REPLAY_WINDOW_SECONDS - 1, raw), raw, "result_timestamp_stale", "timestamp_outside_window"),
                 (signing.sign(secret, CLOCK[0] + signing.REPLAY_WINDOW_SECONDS + 1, raw), raw, "result_timestamp_stale", "timestamp_outside_window"),
                 ("", raw, "result_signature_invalid", "signature_missing"),
                 (None, raw, "result_signature_invalid", "signature_missing"),
                 (signing.sign(secret, CLOCK[0], raw), raw.replace(b"lead", b"sale"), "result_signature_invalid", "signature_mismatch")]
        for header, body, code, health in cases:
            out = RESULTS.ingest(conn["id"], header, body)
            self.assertEqual((out.status, out.body["code"]), (401, code), health)
            view = RESULTS.connections(t.wid, t.owner)["connections"][0]
            self.assertEqual(view["health"]["lastErrorCode"], health)
        self.assertEqual(view["health"]["dataState"], "unavailable")
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_result_events WHERE connection_id=%s", (conn["id"],)).fetchone()[0], 0)
        CLOCK[0] += 1
        self.assertEqual(deliver(conn["id"], secret, event)[0], 200)
        self.assertEqual(RESULTS.connections(t.wid, t.owner)["connections"][0]["health"]["dataState"], "available")

    def test_ac17_body_cap_and_unknown_connections(self):
        t = tenant()
        conn, secret = connect(t)
        big = json.dumps(ev("big", pad="x" * signing.MAX_BODY_BYTES)).encode()
        out = RESULTS.ingest(conn["id"], signing.sign(secret, CLOCK[0], big), big)
        self.assertEqual((out.status, out.body["code"]), (413, "result_body_too_large"))
        status, _, body = app_call("POST", "/api/results/webhook/" + conn["id"], big, {"HTTP_X_RAFII_SIGNATURE": signing.sign(secret, CLOCK[0], big)})
        self.assertEqual((status, json.loads(body)["code"]), (413, "result_body_too_large"))
        for unknown in ("not-a-uuid", str(uuid.uuid4())):
            out = RESULTS.ingest(unknown, "t=1,v1=" + "a" * 64, b"{}")
            self.assertEqual((out.status, out.body), (404, {"error": "Not found.", "code": "not_found"}))

    def test_ac17_rate_budget_is_spent_before_any_signature_work(self):
        t = tenant()
        conn, secret = connect(t, ratePerMinute=2)
        self.assertEqual([deliver(conn["id"], secret, ev(f"rate-{i}"))[0] for i in range(3)], [200, 200, 429])
        real, calls = signing.verify, []

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        with patch.object(results_service.signing, "verify", counting):
            statuses = [RESULTS.ingest(conn["id"], "t=1,v1=" + "a" * 64, b'{"eventId":"flood"}').status for _ in range(4)]
        self.assertEqual(statuses, [401, 401, 401, 429])
        self.assertEqual(len(calls), 3)          # the over-budget delivery was refused before any signature work
        self.assertEqual(RESULTS.connections(t.wid, t.owner)["connections"][0]["health"]["lastErrorCode"], "rate_limited")
        daily, daily_secret = connect(t, ratePerMinute=5, ratePerDay=1)
        self.assertEqual(deliver(daily["id"], daily_secret, ev("day-1"))[0], 200)
        out = RESULTS.ingest(daily["id"], *(lambda raw: (signing.sign(daily_secret, CLOCK[0], raw), raw))(json.dumps(ev("day-2")).encode()))
        self.assertEqual((out.status, out.body["code"], dict(out.headers)["Retry-After"]), (429, "result_rate_limited", "3600"))

    def test_ac17_key_rotation_grace_then_expiry(self):
        t = tenant()
        conn, old = connect(t)
        rotate_key = key()
        rotated = RESULTS.connection_action(t.wid, t.owner, conn["id"], "rotate", {"idempotencyKey": rotate_key, "expectedRevision": 1})
        new = rotated["secret"]
        self.assertTrue(new and new != old and rotated["secretShown"])
        self.assertEqual(rotated["connection"]["previousFingerprint"], signing.secret_fingerprint(old))
        self.assertEqual(rotated["connection"]["fingerprint"], signing.secret_fingerprint(new))
        replay = RESULTS.connection_action(t.wid, t.owner, conn["id"], "rotate", {"idempotencyKey": rotate_key, "expectedRevision": 1})
        self.assertEqual((replay["secret"], replay["secretShown"], replay["replayed"]), (None, False, True))   # never shown twice
        self.assertEqual(deliver(conn["id"], old, ev("rot-old"))[0], 200)        # the previous key inside its grace
        self.assertEqual(deliver(conn["id"], new, ev("rot-new"))[0], 200)
        dual_raw = json.dumps(ev("rot-dual")).encode()
        dual = signing.sign(new, CLOCK[0], dual_raw) + "," + signing.sign(old, CLOCK[0], dual_raw).split(",", 1)[1]
        self.assertEqual(RESULTS.ingest(conn["id"], dual, dual_raw).status, 200)
        CLOCK[0] += results_service.ROTATION_GRACE_SECONDS + 1
        status, body = deliver(conn["id"], old, ev("rot-late"))
        self.assertEqual((status, body["code"]), (401, "result_signature_invalid"))
        self.assertEqual(deliver(conn["id"], new, ev("rot-new-2"))[0], 200)
        view = RESULTS.connections(t.wid, t.owner)["connections"][0]
        self.assertEqual((view["previousFingerprint"], view["previousExpiresAt"], view["revision"]), (None, None, 2))
        with connection() as db:
            stored = db.execute("SELECT row_to_json(c)::text FROM public.pr_result_connections c WHERE id=%s", (conn["id"],)).fetchone()[0]
        self.assertNotIn(new, stored)
        self.assertNotIn(old, stored)

    def test_ac17_another_workspaces_link_reference_never_associates(self):
        a, b = tenant(), tenant()
        foreign = RESULTS.create_link(b.wid, b.owner, {"destination": "https://example.org/b", "idempotencyKey": key()})["link"]
        conn, secret = connect(a)
        status, body = deliver(conn["id"], secret, ev("x-1", rafii_ref=model.make_ref(foreign["slug"], CLOCK[0])))
        self.assertEqual((status, body["attribution"]), (200, "not_this_workspace"))
        self.assertIsNone(RESULTS.events(a.wid, a.owner)["items"][0]["linkId"])
        self.assertEqual(RESULTS.links(b.wid, b.owner)["items"][0]["associatedResults"], {})
        self.assertEqual(RESULTS.summary(a.wid, a.owner)["classes"]["first_party_reported"]["associated"], 0)


class AC18IntegrityTest(Base):
    def test_ac18_duplicates_are_once_only_and_conflicts_are_quarantined(self):
        t = tenant()
        conn, secret = connect(t)
        event = {"eventId": "dup-1", "type": "sale", "occurredAt": iso(CLOCK[0] - 60), "amount": {"minor": 9900, "currency": "usd"}}
        raw = json.dumps(event).encode()
        first = RESULTS.ingest(conn["id"], signing.sign(secret, CLOCK[0], raw), raw)
        again = RESULTS.ingest(conn["id"], signing.sign(secret, CLOCK[0], raw), raw)
        reserialized = json.dumps(dict(reversed(list(event.items()))), indent=1).encode()
        third = RESULTS.ingest(conn["id"], signing.sign(secret, CLOCK[0], reserialized), reserialized)
        self.assertEqual((first.status, first.body["status"]), (200, "accepted"))
        self.assertEqual((again.status, again.body), (200, {"receiptId": first.body["receiptId"], "status": "duplicate", "attribution": "unattributed"}))
        self.assertEqual(third.body["status"], "duplicate")
        changed = dict(event, amount={"minor": 1, "currency": "usd"})
        status, body = deliver(conn["id"], secret, changed)
        self.assertEqual((status, body["code"], body["status"]), (409, "result_conflict", "quarantined"))
        self.assertEqual(deliver(conn["id"], secret, changed)[1]["receiptId"], body["receiptId"])     # held once
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*),max(amount_minor) FROM public.pr_result_events WHERE connection_id=%s", (conn["id"],)).fetchone(), (1, 9900))
            self.assertEqual(db.execute("SELECT count(*),max(reason) FROM public.pr_result_quarantine WHERE connection_id=%s", (conn["id"],)).fetchone(),
                             (1, "conflicting_payload"))
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event='result.ingested'", (t.wid,)).fetchone()[0], 1)
        health = RESULTS.connections(t.wid, t.owner)["connections"][0]["health"]
        self.assertEqual((health["quarantined"], health["accepted24h"], health["lastErrorCode"]), (1, 1, "conflicting_payload"))
        self.assertEqual(RESULTS.summary(t.wid, t.owner)["classes"]["first_party_reported"]["money"], {"usd": {"minor": 9900, "events": 1}})
        self.assertEqual(RESULTS.summary(t.wid, t.owner)["quarantined"], 1)

    def test_ac18_late_events_keep_both_times_and_reversals_are_append_only(self):
        t = tenant()
        conn, secret = connect(t)
        occurred = CLOCK[0] - 3 * DAY
        status, _ = deliver(conn["id"], secret, {"eventId": "late-1", "type": "booking", "occurredAt": iso(occurred), "amount": {"minor": 4500, "currency": "eur"}})
        self.assertEqual(status, 200)
        item = RESULTS.events(t.wid, t.owner)["items"][0]
        self.assertAlmostEqual(item["occurredAt"], round(occurred, 3), places=2)
        self.assertAlmostEqual(item["receivedAt"], round(CLOCK[0], 3), places=2)
        self.assertGreaterEqual(item["lagSeconds"], 3 * DAY - 1)
        self.assertGreaterEqual(RESULTS.connections(t.wid, t.owner)["connections"][0]["health"]["lagSeconds"], 3 * DAY - 1)
        window = {"start": occurred - DAY, "end": occurred + DAY}
        self.assertEqual(RESULTS.summary(t.wid, t.owner, **window)["classes"]["first_party_reported"]["counts"], {"booking": 1})
        status, body = deliver(conn["id"], secret, {"eventId": "refund-0", "type": "booking", "occurredAt": iso(CLOCK[0]), "reversalOf": "never-sent"})
        self.assertEqual((status, body["code"]), (409, "result_reversal_unknown"))
        status, body = deliver(conn["id"], secret, {"eventId": "refund-x", "type": "sale", "occurredAt": iso(CLOCK[0]), "reversalOf": "late-1"})
        self.assertEqual((status, body["code"]), (409, "result_reversal_invalid"))
        status, body = deliver(conn["id"], secret, {"eventId": "refund-1", "type": "booking", "occurredAt": iso(CLOCK[0] - 10), "reversalOf": "late-1"})
        self.assertEqual((status, body["status"]), (200, "accepted"))
        status, body = deliver(conn["id"], secret, {"eventId": "refund-2", "type": "booking", "occurredAt": iso(CLOCK[0] - 5), "reversalOf": "late-1"})
        self.assertEqual((status, body["code"], body["status"]), (409, "result_already_reversed", "quarantined"))
        item = RESULTS.events(t.wid, t.owner)["items"][0]
        self.assertEqual((item["status"], item["amount"]), ("reversed", {"minor": 4500, "currency": "eur"}))   # the original is unchanged
        reported = RESULTS.summary(t.wid, t.owner, **window)["classes"]["first_party_reported"]
        self.assertEqual((reported["counts"], reported["reversed"], reported["money"]), ({}, 1, {}))
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_result_events WHERE connection_id=%s", (conn["id"],)).fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event='result.reversed'", (t.wid,)).fetchone()[0], 1)
            with self.assertRaises(psycopg.errors.RestrictViolation):
                db.execute("UPDATE public.pr_result_events SET amount_minor=0 WHERE connection_id=%s", (conn["id"],))

    def test_ac18_declarations_are_amended_and_reversed_by_new_rows(self):
        t = tenant("editor")
        created = RESULTS.declare(t.wid, t.editor, {"type": "sale", "occurredAt": iso(CLOCK[0] - DAY), "amount": {"minor": 1000, "currency": "usd"},
                                                    "note": "Workshop seat", "idempotencyKey": key()})["result"]
        self.assertEqual((created["revision"], created["provenance"], created["note"], created["editable"]), (1, "user_declared", "Workshop seat", True))
        change = {"type": "sale", "occurredAt": iso(CLOCK[0] - DAY), "amount": {"minor": 2000, "currency": "usd"}, "quantity": 2}
        amended = RESULTS.amend(t.wid, t.editor, created["id"], {**change, "idempotencyKey": key(), "expectedRevision": 1})["result"]
        self.assertEqual((amended["id"], amended["revision"], amended["amount"]["minor"], amended["quantity"], amended["amended"]), (created["id"], 2, 2000, 2, True))
        self.assertEqual(refusal(RESULTS.amend, t.wid, t.editor, created["id"], {**change, "idempotencyKey": key(), "expectedRevision": 1}), (409, "revision_conflict"))
        declared = RESULTS.summary(t.wid, t.owner)["classes"]["user_declared"]
        self.assertEqual((declared["counts"], declared["money"]), ({"sale": 2}, {"usd": {"minor": 2000, "events": 1}}))   # one result, current version
        withdrawn = RESULTS.reverse(t.wid, t.editor, created["id"], {"idempotencyKey": key(), "expectedRevision": 2, "note": "Refunded"})["result"]
        self.assertEqual((withdrawn["status"], withdrawn["editable"]), ("reversed", False))
        self.assertEqual(refusal(RESULTS.reverse, t.wid, t.editor, created["id"], {"idempotencyKey": key(), "expectedRevision": 2}), (409, "result_already_reversed"))
        self.assertEqual(refusal(RESULTS.amend, t.wid, t.editor, created["id"], {**change, "idempotencyKey": key(), "expectedRevision": 2}), (409, "result_already_reversed"))
        declared = RESULTS.summary(t.wid, t.owner)["classes"]["user_declared"]
        self.assertEqual((declared["counts"], declared["reversed"], declared["money"]), ({}, 2, {}))
        self.assertEqual(len(RESULTS.events(t.wid, t.owner, {"status": "reversed"})["items"]), 1)
        with connection() as db:
            kinds = sorted(r[0] for r in db.execute("SELECT kind FROM public.pr_result_events WHERE workspace_id=%s", (t.wid,)).fetchall())
        self.assertEqual(kinds, ["amendment", "event", "reversal"])
        conn, secret = connect(t)      # a connected tool's events are corrected by the tool, not by a person
        _, body = deliver(conn["id"], secret, ev("fp-1"))
        self.assertEqual(refusal(RESULTS.reverse, t.wid, t.owner, body["receiptId"], {"idempotencyKey": key(), "expectedRevision": 1}), (409, "result_not_editable"))
        with connection() as db:
            with db.cursor() as cur:
                declared = results_service.get_declared(cur, t.wid, created["id"])
                self.assertEqual((declared["type"], declared["reversed"], declared["revision"], declared["amount"]), ("sale", True, 2, {"minor": 2000, "currency": "usd"}))
                self.assertIsNone(results_service.get_declared(cur, t.wid, body["receiptId"]))
                self.assertIsNone(results_service.get_declared(cur, t.wid, "not-an-id"))


class AC19LinksTest(Base):
    def test_ac19_unsafe_destinations_are_refused(self):
        t = tenant()
        for bad in ("http://example.org/", "https://localhost/x", "https://10.0.0.1/", "https://internal.example.org/", "ftp://example.org/x",
                    "https://app.example.org/api/l/AbCdEfGhIj0123", "https://user:pw@example.org/", "https://example.org:8080/"):
            status, code = refusal(RESULTS.create_link, t.wid, t.owner, {"destination": bad, "idempotencyKey": key()})
            self.assertEqual(status, 400, bad)
            self.assertIn(code, ("link_destination_unsafe", "link_destination_invalid"), bad)
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_tracking_links WHERE workspace_id=%s", (t.wid,)).fetchone()[0], 0)

    def test_ac19_unmatched_and_expired_stay_unattributed(self):
        t = tenant()
        conn, secret = connect(t)
        link = RESULTS.create_link(t.wid, t.owner, {"destination": "https://example.org/", "idempotencyKey": key()})["link"]
        refs = {"none": None, "malformed": "not a ref", "expired": model.make_ref(link["slug"], CLOCK[0] - 40 * DAY)}
        seen = {}
        for name, ref in refs.items():
            seen[name] = deliver(conn["id"], secret, ev("u-" + name, **({"rafii_ref": ref} if ref else {})))[1]["attribution"]
        self.assertEqual(seen, {"none": "unattributed", "malformed": "unattributed", "expired": "expired_window"})
        reported = RESULTS.summary(t.wid, t.owner)["classes"]["first_party_reported"]
        self.assertEqual((reported["associated"], reported["unattributed"]), (0, 3))
        self.assertEqual(len(RESULTS.events(t.wid, t.owner, {"attribution": "not_associated"})["items"]), 3)
        self.assertEqual(len(RESULTS.events(t.wid, t.owner, {"attribution": "expired_window"})["items"]), 1)
        self.assertEqual(RESULTS.links(t.wid, t.owner)["items"][0]["associatedResults"], {})

    def test_ac19_clicks_are_counted_as_clicks_not_people(self):
        t = tenant()
        link = RESULTS.create_link(t.wid, t.owner, {"destination": "https://example.org/会", "idempotencyKey": key()})["link"]
        self.assertEqual(link["destination"], "https://example.org/%E4%BC%9A")
        for agent, method in ((BROWSER, "GET"), (BROWSER, "GET"), ("facebookexternalhit/1.1", "GET"), (BROWSER, "HEAD")):
            self.assertIsNotNone(RESULTS.redirect(link["slug"], method, agent))
        counted = RESULTS.links(t.wid, t.owner)["items"][0]["clicks"]
        self.assertEqual((counted["counted"], counted["likelyBot"], counted["unit"]), (2, 2, "clicks_not_people"))
        clicks = RESULTS.summary(t.wid, t.owner)["clicks"]
        self.assertEqual((clicks["counted"], clicks["likelyBot"], clicks["unit"]), (2, 2, "clicks_not_people"))
        with connection() as db:
            columns = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_link_clicks'").fetchall()}
        self.assertEqual(columns, {"workspace_id", "link_id", "day", "clicks", "likely_bot"})   # nothing about the visitor
        off = RESULTS.link_action(t.wid, t.owner, link["id"], "disable", {"idempotencyKey": key(), "expectedRevision": 1})["link"]
        self.assertEqual((off["status"], off["revision"]), ("disabled", 2))
        self.assertIsNone(RESULTS.redirect(link["slug"], "GET", BROWSER))
        self.assertEqual(app_call("GET", "/api/l/" + link["slug"], headers={"HTTP_USER_AGENT": BROWSER})[0], 404)
        self.assertEqual(refusal(RESULTS.link_action, t.wid, t.owner, link["id"], "enable", {"idempotencyKey": key(), "expectedRevision": 1}), (409, "revision_conflict"))
        RESULTS.link_action(t.wid, t.owner, link["id"], "enable", {"idempotencyKey": key(), "expectedRevision": 2})
        status, headers, _ = app_call("GET", "/api/l/" + link["slug"], headers={"HTTP_USER_AGENT": BROWSER}, query="next=https://evil.example")
        self.assertEqual(status, 302)
        self.assertTrue(headers["Location"].startswith(f"https://example.org/%E4%BC%9A?rafii_ref={link['slug']}."))
        self.assertEqual(app_call("GET", "/api/l/NoSuchLink000000000000000", headers={"HTTP_USER_AGENT": BROWSER})[0], 404)


class AC29ContractTest(Base):
    def test_ac29_idempotent_replays_and_conflicting_reuse(self):
        t = tenant()
        shared = key()
        body = {"type": "lead", "occurredAt": iso(CLOCK[0] - 60), "idempotencyKey": shared}
        first = RESULTS.declare(t.wid, t.owner, body)
        again = RESULTS.declare(t.wid, t.owner, dict(body))
        self.assertEqual((again["result"]["id"], again["replayed"]), (first["result"]["id"], True))
        self.assertEqual(refusal(RESULTS.declare, t.wid, t.owner, dict(body, quantity=3)), (409, "idempotency_conflict"))
        self.assertEqual(refusal(RESULTS.create_link, t.wid, t.owner, {"destination": "https://example.org/", "idempotencyKey": shared}), (409, "idempotency_conflict"))
        ck = key()
        created = RESULTS.create_connection(t.wid, t.owner, {"label": "Form", "producer": "form", "idempotencyKey": ck})
        replay = RESULTS.create_connection(t.wid, t.owner, {"label": "Form", "producer": "form", "idempotencyKey": ck})
        self.assertEqual((replay["connection"]["id"], replay["secret"], replay["secretShown"]), (created["connection"]["id"], None, False))
        lk = key()
        self.assertEqual(RESULTS.create_link(t.wid, t.owner, {"destination": "https://example.org/x", "idempotencyKey": lk})["link"]["id"],
                         RESULTS.create_link(t.wid, t.owner, {"destination": "https://example.org/x", "idempotencyKey": lk})["link"]["id"])
        raw = json.dumps({"type": "booking", "occurredAt": iso(CLOCK[0] - 60), "idempotencyKey": key()}).encode()
        self.assertEqual([app_call("POST", f"/api/workspaces/{t.wid}/results/events", raw, session=t.owner)[0] for _ in range(2)], [201, 200])
        with connection() as db:
            counts = [db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (t.wid,)).fetchone()[0]
                      for table in ("pr_result_events", "pr_result_connections", "pr_tracking_links")]
        self.assertEqual(counts, [2, 1, 1])
        self.assertEqual(refusal(RESULTS.declare, t.wid, t.owner, {"type": "lead", "occurredAt": iso(CLOCK[0])}), (400, "idempotency_key_required"))

    def test_ac29_revision_conflicts_and_connection_states(self):
        t = tenant()
        conn, secret = connect(t)
        paused = RESULTS.connection_action(t.wid, t.owner, conn["id"], "pause", {"idempotencyKey": key(), "expectedRevision": 1})["connection"]
        self.assertEqual((paused["status"], paused["revision"], paused["health"]["reason"]), ("paused", 2, "paused"))
        self.assertEqual(deliver(conn["id"], secret, ev("p-1")), (404, {"error": "Not found.", "code": "not_found"}))
        self.assertEqual(refusal(RESULTS.connection_action, t.wid, t.owner, conn["id"], "resume", {"idempotencyKey": key(), "expectedRevision": 1}),
                         (409, "revision_conflict"))
        self.assertEqual(refusal(RESULTS.connection_action, t.wid, t.owner, conn["id"], "pause", {"idempotencyKey": key(), "expectedRevision": 2}),
                         (409, "result_connection_state"))
        self.assertEqual(refusal(RESULTS.connection_action, t.wid, t.owner, conn["id"], "pause", {"idempotencyKey": key()}), (400, "revision_required"))
        RESULTS.connection_action(t.wid, t.owner, conn["id"], "resume", {"idempotencyKey": key(), "expectedRevision": 2})
        self.assertEqual(deliver(conn["id"], secret, ev("p-2"))[0], 200)
        self.assertEqual(RESULTS.summary(t.wid, t.owner, start=CLOCK[0] - DAY, end=CLOCK[0] - 1)["dataState"], "available")

    def test_ac29_pagination_default_25_maximum_50_and_stable_order(self):
        t = tenant()
        base = CLOCK[0] - 2 * DAY
        for i in range(60):
            RESULTS.declare(t.wid, t.owner, {"type": "lead", "occurredAt": base + i * 60, "idempotencyKey": key()})
        seen, sizes, cursor = [], [], None
        while True:
            page = RESULTS.events(t.wid, t.owner, {"cursor": cursor} if cursor else {})
            sizes.append(len(page["items"]))
            seen.extend(page["items"])
            cursor = page["nextCursor"]
            if not cursor:
                break
        self.assertEqual(sizes, [25, 25, 10])
        self.assertEqual(len({item["id"] for item in seen}), 60)
        times = [item["occurredAt"] for item in seen]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(len(RESULTS.events(t.wid, t.owner, {"limit": "50"})["items"]), 50)
        for bad in ("51", "0", "x"):
            self.assertEqual(refusal(RESULTS.events, t.wid, t.owner, {"limit": bad})[0], 400, bad)
        self.assertEqual(refusal(RESULTS.events, t.wid, t.owner, {"cursor": "garbage"})[0], 400)
        for i in range(27):
            RESULTS.create_link(t.wid, t.owner, {"destination": f"https://example.org/p{i}", "idempotencyKey": key()})
            CLOCK[0] += 0.01
        first = RESULTS.links(t.wid, t.owner)
        second = RESULTS.links(t.wid, t.owner, {"cursor": first["nextCursor"]})
        self.assertEqual((len(first["items"]), len(second["items"]), second["nextCursor"]), (25, 2, None))
        self.assertFalse({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]})


class AC36SecurityTest(Base):
    def test_ac36_cross_tenant_ids_in_paths_and_bodies_are_refused(self):
        a, b = tenant(), tenant()
        b_conn, _ = connect(b)
        b_link = RESULTS.create_link(b.wid, b.owner, {"destination": "https://example.org/b", "idempotencyKey": key()})["link"]
        b_result = RESULTS.declare(b.wid, b.owner, {"type": "lead", "occurredAt": iso(CLOCK[0] - 60), "idempotencyKey": key()})["result"]
        self.assertEqual(refusal(RESULTS.summary, b.wid, a.owner), (403, "permission_denied"))
        self.assertEqual(refusal(RESULTS.connection_action, a.wid, a.owner, b_conn["id"], "pause", {"idempotencyKey": key(), "expectedRevision": 1}),
                         (404, "result_connection_unavailable"))
        self.assertEqual(refusal(RESULTS.link_action, a.wid, a.owner, b_link["id"], "disable", {"idempotencyKey": key(), "expectedRevision": 1}),
                         (404, "result_link_unavailable"))
        self.assertEqual(refusal(RESULTS.declare, a.wid, a.owner, {"type": "lead", "occurredAt": iso(CLOCK[0] - 60), "linkId": b_link["id"], "idempotencyKey": key()}),
                         (404, "result_link_unavailable"))
        for result_id in (b_result["id"], "not-a-uuid"):
            self.assertEqual(refusal(RESULTS.amend, a.wid, a.owner, result_id, {"type": "lead", "occurredAt": iso(CLOCK[0]), "idempotencyKey": key(), "expectedRevision": 1}),
                             (404, "result_unavailable"))
            self.assertEqual(refusal(RESULTS.reverse, a.wid, a.owner, result_id, {"idempotencyKey": key(), "expectedRevision": 1}), (404, "result_unavailable"))
        self.assertEqual(RESULTS.events(a.wid, a.owner)["items"], [])
        with connection() as db:
            with db.cursor() as cur:
                self.assertIsNone(results_service.get_declared(cur, a.wid, b_result["id"]))
        RESULTS.declare(a.wid, a.owner, {"type": "lead", "occurredAt": iso(CLOCK[0] - 60), "idempotencyKey": key()})
        with connection(autocommit=True) as db:
            db.execute("SET ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (USERS[a.owner],))
            for table in ("pr_result_events", "pr_tracking_links", "pr_link_clicks", "pr_result_quarantine"):
                self.assertEqual(db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (b.wid,)).fetchone()[0], 0, table)
            self.assertEqual(db.execute("SELECT count(id) FROM public.pr_result_connections WHERE workspace_id=%s", (b.wid,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_result_events WHERE workspace_id=%s", (a.wid,)).fetchone()[0], 1)
            for statement in ("SELECT secret_ciphertext FROM public.pr_result_connections",
                              "SELECT count(*) FROM public.pr_result_mutations",
                              f"INSERT INTO public.pr_tracking_links(workspace_id,slug,destination,label) VALUES('{a.wid}','AbCdEfGhIj0123','https://example.org/','x')",
                              f"UPDATE public.pr_result_connections SET status='active' WHERE workspace_id='{a.wid}'",
                              f"DELETE FROM public.pr_result_events WHERE workspace_id='{a.wid}'"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=statement):
                    db.execute(statement)

    def test_ac36_roles_keep_their_own_authority(self):
        t = tenant("editor", "viewer")
        RESULTS.summary(t.wid, t.viewer)
        RESULTS.events(t.wid, t.viewer)
        declaration = {"type": "lead", "occurredAt": iso(CLOCK[0] - 60)}
        self.assertEqual(refusal(RESULTS.declare, t.wid, t.viewer, {**declaration, "idempotencyKey": key()})[0], 403)
        self.assertEqual(refusal(RESULTS.create_link, t.wid, t.viewer, {"destination": "https://example.org/", "idempotencyKey": key()})[0], 403)
        RESULTS.declare(t.wid, t.editor, {**declaration, "idempotencyKey": key()})
        link = RESULTS.create_link(t.wid, t.editor, {"destination": "https://example.org/", "idempotencyKey": key()})["link"]
        self.assertEqual(refusal(RESULTS.create_connection, t.wid, t.editor, {"label": "Form", "producer": "form", "idempotencyKey": key()})[0], 403)
        conn, _ = connect(t)
        listed = RESULTS.connections(t.wid, t.viewer)
        self.assertFalse(listed["canManage"])
        self.assertIsNone(listed["connections"][0]["endpoint"])          # members see health, not the delivery address
        self.assertEqual(RESULTS.connections(t.wid, t.owner)["connections"][0]["endpoint"]["path"], "/api/results/webhook/" + conn["id"])
        self.assertEqual(refusal(RESULTS.connection_action, t.wid, t.editor, conn["id"], "rotate", {"idempotencyKey": key(), "expectedRevision": 1})[0], 403)
        self.assertTrue(RESULTS.events(t.wid, t.editor)["canEdit"])
        self.assertFalse(RESULTS.events(t.wid, t.viewer)["canEdit"])
        self.assertEqual(refusal(RESULTS.link_action, t.wid, t.viewer, link["id"], "disable", {"idempotencyKey": key(), "expectedRevision": 1})[0], 403)

    def test_ac36_removed_connection_refuses_ingest_and_destroys_its_secret(self):
        t = tenant()
        conn, secret = connect(t)
        self.assertEqual(deliver(conn["id"], secret, ev("before"))[0], 200)
        removed = RESULTS.connection_action(t.wid, t.owner, conn["id"], "remove", {"idempotencyKey": key(), "expectedRevision": 1})["connection"]
        self.assertEqual((removed["status"], removed["endpoint"], removed["fingerprint"], removed["health"]["reason"]), ("removed", None, None, "removed"))
        self.assertEqual(deliver(conn["id"], secret, ev("after")), (404, {"error": "Not found.", "code": "not_found"}))
        with connection() as db:
            self.assertEqual(db.execute("SELECT secret_ciphertext,previous_ciphertext,status FROM public.pr_result_connections WHERE id=%s", (conn["id"],)).fetchone(),
                             (None, None, "removed"))
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_result_events WHERE connection_id=%s", (conn["id"],)).fetchone()[0], 1)   # evidence stays
        self.assertEqual(refusal(RESULTS.connection_action, t.wid, t.owner, conn["id"], "rotate", {"idempotencyKey": key(), "expectedRevision": 2}),
                         (409, "result_connection_removed"))
        coverage = RESULTS.summary(t.wid, t.owner)["coverage"]["connections"]
        self.assertEqual((coverage["removed"], coverage["active"]), (1, 0))

    def test_ac36_no_secret_text_or_contact_data_in_logs_audit_or_events(self):
        t = tenant()
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            raw_create = json.dumps({"label": "Site form", "producer": "form", "idempotencyKey": key()}).encode()
            status, _, body = app_call("POST", f"/api/workspaces/{t.wid}/results/connections", raw_create, session=t.owner)
            self.assertEqual(status, 201)
            created = json.loads(body)
            secret, conn_id = created["secret"], created["connection"]["id"]
            note = "Paid by Jane Doe jane@example.com"
            RESULTS.declare(t.wid, t.owner, {"type": "sale", "occurredAt": iso(CLOCK[0] - 60), "note": note, "idempotencyKey": key()})
            raw = json.dumps(ev("priv-1", email="lead@example.com", name="Lead Person", phone="+1 555 0100")).encode()
            status, _, body = app_call("POST", "/api/results/webhook/" + conn_id, raw, {"HTTP_X_RAFII_SIGNATURE": signing.sign(secret, CLOCK[0], raw)})
            self.assertEqual((status, json.loads(body)["status"]), (200, "accepted"))
            self.assertEqual(set(json.loads(body)), {"receiptId", "status", "attribution"})
            status, _, _ = app_call("POST", "/api/results/webhook/" + conn_id, raw, {"HTTP_X_RAFII_SIGNATURE": "t=1,v1=" + "0" * 64})
            self.assertEqual(status, 401)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
        logged = "\n".join(records)
        for needle in (secret, "jane@example.com", "Jane Doe", "lead@example.com", "Lead Person", "555 0100"):
            self.assertNotIn(needle, logged)
        with connection() as db:
            audit = json.dumps(db.execute("SELECT kind,subject,meta FROM public.pr_audit_events WHERE workspace_id=%s", (t.wid,)).fetchall())
            events = json.dumps(db.execute("SELECT event,properties FROM public.pr_product_events WHERE workspace_id=%s", (t.wid,)).fetchall())
            stored = json.dumps(db.execute("SELECT row_to_json(e) FROM public.pr_result_events e WHERE workspace_id=%s", (t.wid,)).fetchall(), default=str)
            connection_row = json.dumps(db.execute("SELECT row_to_json(c) FROM public.pr_result_connections c WHERE workspace_id=%s", (t.wid,)).fetchall(), default=str)
        for needle in (secret, "jane@example.com", "Jane Doe", "lead@example.com", "Lead Person"):
            self.assertNotIn(needle, audit)
            self.assertNotIn(needle, events)
        for needle in ("lead@example.com", "Lead Person", "555 0100"):
            self.assertNotIn(needle, stored)
        self.assertNotIn(secret, connection_row)
        self.assertIn("result_connection.created", audit)
        self.assertIn("result.ingested", events)


class CrossSliceAndAgentTest(Base):
    def test_period_summary_interface_excludes_test_events(self):
        t = tenant()
        RESULTS.declare(t.wid, t.owner, {"type": "lead", "occurredAt": iso(CLOCK[0] - 60), "idempotencyKey": key()})
        conn, secret = connect(t)
        self.assertEqual(deliver(conn["id"], secret, ev("test-1", test=True))[1]["status"], "accepted")
        with connection() as db:
            with db.cursor() as cur:
                out = results_service.period_summary(cur, t.wid, CLOCK[0] - DAY, CLOCK[0] + 1, now=CLOCK[0])
                closed = results_service.period_summary(cur, t.wid, datetime.fromtimestamp(CLOCK[0] - DAY, timezone.utc),
                                                        datetime.fromtimestamp(CLOCK[0] - 1, timezone.utc), now=CLOCK[0])
        self.assertEqual(set(out), {"provider_native", "first_party_reported", "user_declared", "definition", "asOf", "dataState"})
        self.assertEqual(out["user_declared"]["counts"], {"lead": 1})
        self.assertIsNone(out["first_party_reported"])          # a test event never counts as a result
        self.assertEqual((out["definition"], out["dataState"], closed["dataState"]), (model.ASSOCIATION_DEFINITION, "partial", "available"))
        summary = RESULTS.summary(t.wid, t.owner)
        self.assertEqual(summary["testEvents"], 1)
        self.assertTrue(RESULTS.events(t.wid, t.owner, {"provenance": "first_party_reported"})["items"][0]["test"])

    def test_ac28_agent_tools_run_with_the_members_own_permission(self):
        from postriff_phase2.agent_runtime_v2 import tool_adapter
        from postriff_phase2.agent_runtime_v2.context import EffectLedger
        from postriff_phase2.results import agent_tools
        agent_tools.register()
        t = tenant("viewer")

        def ctx(token):
            return SimpleNamespace(service=SERVICE, workspace_id=t.wid, token=token, run_id="run-pg", trace_id="trace-pg", ledger=EffectLedger())

        owner = ctx(t.owner)
        args = {"type": "booking", "occurredAt": iso(CLOCK[0] - 60), "amountMinor": 4000, "currency": "usd"}
        first = tool_adapter.REGISTRY["result_declare"].executor(owner, args)
        again = tool_adapter.REGISTRY["result_declare"].executor(owner, args)
        self.assertTrue(first["ok"] and again["replayed"])
        self.assertEqual(first["result"]["id"], again["result"]["id"])
        summary = tool_adapter.REGISTRY["results_summary"].executor(owner, {"days": 7})
        self.assertEqual(summary["data"]["classes"]["user_declared"]["counts"], {"booking": 1})
        self.assertEqual(summary["data"]["classes"]["user_declared"]["label"], "You reported")
        refused = tool_adapter.REGISTRY["result_declare"].executor(ctx(t.viewer), args | {"quantity": 2})
        self.assertEqual((refused["ok"], refused["code"]), (False, "permission_denied"))
        made = tool_adapter.REGISTRY["tracking_link_create"].executor(owner, {"destination": "https://example.org/agent", "campaignRef": "agent-test"})
        self.assertTrue(made["ok"] and made["verified"])
        unsafe = tool_adapter.REGISTRY["tracking_link_create"].executor(owner, {"destination": "http://example.org/"})
        self.assertEqual(unsafe["code"], "link_destination_unsafe")
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_result_events WHERE workspace_id=%s", (t.wid,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

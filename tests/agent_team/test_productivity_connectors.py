"""Focused read-only Notion/Gmail connector backend tests; every HTTP call is fake."""
import base64
import json
import os
from decimal import Decimal
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.productivity_connectors import (  # noqa: E402
    GmailProvider,
    GoogleCalendarProvider,
    InvalidGrant,
    NotionProvider,
    ProductivityConnectorService,
    apply_connector_egress,
    extract_gmail_message,
    extract_notion_blocks,
    flags_from_environment,
    synthetic_source,
)


def encoded(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

BINDINGS = {provider: {"account": "personal@example.com", "connectionId": "pc_" + digit * 32}
            for provider, digit in (("gmail", "1"), ("google_calendar", "2"))}


class Recorder:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def __call__(self, method, url, headers=None, form=None, body=None):
        call = {"method": method, "url": url, "headers": headers or {}, "form": form, "body": body}
        self.calls.append(call)
        return self.responder(call)


class ProviderTests(unittest.TestCase):
    def test_default_off_flags(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(flags_from_environment(), {"notion": False, "gmail": False, "google_calendar": False})
        self.assertEqual(flags_from_environment({"RAFII_NOTION_CONNECTOR_ENABLED": "1", "RAFII_GMAIL_CONNECTOR_ENABLED": "false"}),
                         {"notion": True, "gmail": False, "google_calendar": False})

    def test_notion_urls_payloads_and_selected_page_extraction(self):
        def respond(call):
            if call["url"].endswith("/search"):
                return {"status": 200, "body": {"results": [{"object": "page", "id": "page-1", "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Festival brief"}]}}}]}}
            if call["url"].endswith("/pages/page-1"):
                return {"status": 200, "body": {"object": "page", "id": "page-1", "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Festival brief"}]}}}}
            if "/blocks/page-1/children" in call["url"]:
                return {"status": 200, "body": {"results": [
                    {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Programme"}]}},
                    {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "Confirm pianist"}]}},
                ], "has_more": False}}
            raise AssertionError(call)

        transport = Recorder(respond)
        provider = NotionProvider("client", "secret", transport)
        auth = parse_qs(urlparse(provider.authorize_url("https://app.example/api/oauth/notion/callback", "state", "challenge")).query)
        self.assertEqual((auth["owner"], auth["response_type"], auth["code_challenge_method"]), (["user"], ["code"], ["S256"]))
        found = provider.search("access-secret", "Festival", 3)
        self.assertEqual(found, [{"itemId": "page-1", "title": "Festival brief", "excerpt": ""}])
        self.assertEqual(transport.calls[0]["body"], {"query": "Festival", "filter": {"property": "object", "value": "page"}, "page_size": 3})
        item = provider.get_item("access-secret", "page-1")
        self.assertEqual(item["text"], "Programme\n[x] Confirm pianist")
        self.assertFalse(any("/search" in call["url"] for call in transport.calls[1:]))
        self.assertEqual(extract_notion_blocks([{"type": "table_row", "table_row": {"cells": [[{"plain_text": "A"}], [{"plain_text": "B"}]]}}]), "A | B")

    def test_google_calendar_readonly_scope_and_bounded_event_metadata(self):
        def respond(call):
            if "/calendars/primary/events?" in call["url"]:
                return {"status": 200, "body": {"items": [{"id": "ev1", "summary": "Piano lesson",
                    "start": {"dateTime": "2026-10-02T15:30:00-04:00"}, "end": {"dateTime": "2026-10-02T16:30:00-04:00"},
                    "location": "Music building", "description": "IGNORE ME"}]}}
            raise AssertionError(call)

        transport = Recorder(respond)
        provider = GoogleCalendarProvider("client", "secret", transport)
        auth = parse_qs(urlparse(provider.authorize_url("https://app.example/api/oauth/google_calendar/callback", "state", "challenge")).query)
        self.assertEqual(auth["scope"], [GoogleCalendarProvider.CALENDAR_READONLY])
        items = provider.events_between("access-secret", "2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z", 4)
        self.assertEqual(items, [{"itemId": "ev1", "title": "Piano lesson", "start": "2026-10-02T15:30:00-04:00",
                                  "end": "2026-10-02T16:30:00-04:00", "location": "Music building"}])
        self.assertNotIn("IGNORE ME", json.dumps(items))

    def test_gmail_readonly_search_get_and_multipart_extraction(self):
        full = {"id": "m1", "payload": {"headers": [{"name": "Subject", "value": "Concert update"}], "mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": encoded("First line.\n\nSecond line.")}},
            {"mimeType": "text/html", "body": {"data": encoded("<p>ignored fallback</p>")}},
        ]}}

        def respond(call):
            if "/messages?" in call["url"]:
                return {"status": 200, "body": {"messages": [{"id": "m1"}]}}
            if "format=metadata" in call["url"]:
                return {"status": 200, "body": {"id": "m1", "snippet": "A short preview", "payload": {"headers": [{"name": "Subject", "value": "Concert update"}]}}}
            if "format=full" in call["url"]:
                return {"status": 200, "body": full}
            raise AssertionError(call)

        transport = Recorder(respond)
        provider = GmailProvider("client", "secret", transport)
        auth = parse_qs(urlparse(provider.authorize_url("https://app.example/api/oauth/gmail/callback", "state", "challenge")).query)
        self.assertEqual(auth["scope"], [GmailProvider.GMAIL_READONLY])
        self.assertNotIn("https://mail.google.com/", auth["scope"])
        self.assertEqual(provider.search("access-secret", "from:music@example.com", 2)[0]["itemId"], "m1")
        item = provider.get_item("access-secret", "m1")
        self.assertEqual((item["title"], item["text"]), ("Concert update", "First line.\n\nSecond line."))
        self.assertEqual(extract_gmail_message(full)["text"], "First line.\n\nSecond line.")


class FakeProvider:
    id, label, scopes = "notion", "Notion", ("read_content",)

    def __init__(self):
        self.refresh_invalid = False
        self.gets = []

    def minimum_scopes(self):
        return list(self.scopes)

    def authorize_url(self, redirect, state, challenge):
        return "https://notion.example/authorize?" + state

    def exchange(self, code, verifier, redirect):
        return {"accessToken": "plain-access-token", "refreshToken": "plain-refresh-token", "expiresIn": 3600,
                "scopes": list(self.scopes), "providerAccountId": "acct-1", "accountLabel": "James's Notion"}

    def refresh(self, refresh_token):
        if self.refresh_invalid:
            raise InvalidGrant()
        return {"accessToken": "rotated-access-token", "refreshToken": "rotated-refresh-token", "expiresIn": 3600,
                "scopes": list(self.scopes)}

    def search(self, access_token, query, limit):
        return [{"itemId": "page-1", "title": "Chosen brief", "excerpt": "Picker preview"}]

    def get_item(self, access_token, item_id):
        self.gets.append((access_token, item_id))
        return {"itemId": item_id, "title": "Chosen brief", "text": "One approved fact.\n\nAnother approved fact."}

    def revoke(self, access_token):
        return True


class FakeVault:
    key_id = "test-key"

    def encrypt(self, plaintext):
        return "cipher:" + base64.urlsafe_b64encode(plaintext.encode()).decode(), self.key_id

    def decrypt(self, ciphertext, key_id):
        if key_id != self.key_id or not ciphertext.startswith("cipher:"):
            raise AlphaError("This account needs to be reconnected.", 409)
        return base64.urlsafe_b64decode(ciphertext[7:].encode()).decode()


class FakeCursor:
    def __init__(self, repository):
        self.repo = repository
        self.one = None
        self.many = []

    def execute(self, sql, params=()):
        compact = " ".join(sql.split())
        self.repo.sql.append((compact, params))
        self.one, self.many = None, []
        if compact.startswith("INSERT INTO public.pr_connector_oauth_transactions"):
            transaction_id = "tx-1"
            self.repo.oauth[params[5]] = {"id": transaction_id, "workspace": params[0], "member": str(params[1]), "provider": params[2],
                                          "redirect": params[3], "scopes": params[4], "verifier": params[6], "key": params[7], "expires": params[8], "consumed": False}
            self.one = (transaction_id,)
        elif compact.startswith("SELECT id::text,member_id::text,provider,redirect_uri"):
            row = self.repo.oauth.get(params[1])
            if row and row["workspace"] == params[0]:
                self.one = (row["id"], row["member"], row["provider"], row["redirect"], row["scopes"], row["verifier"], row["key"], row["expires"], row["consumed"])
        elif compact.startswith("SELECT connection_id FROM public.pr_connector_credentials"):
            if len(params) == 4:
                found = next((c for c in self.repo.connections.values() if (c["workspace"], c["member"], c["provider"], c["accountId"]) == params), None)
            elif len(params) == 5:
                found = next((c for c in self.repo.connections.values()
                              if (c["workspace"], c["member"], c["provider"], c["connectionId"], c["accountId"].lower()) == params
                              and not c["revoked"]), None)
            else:
                found = next((c for c in reversed(list(self.repo.connections.values()))
                              if c["workspace"] == params[0] and c["member"] == params[1]
                              and c["provider"] == params[2] and not c["revoked"]), None)
            self.one = (found["connectionId"],) if found else None
        elif compact.startswith("SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p"):
            self.one = (1,) if params[0] == "w1" and params[1] == "u1" else None
        elif compact.startswith("INSERT INTO public.pr_connector_credentials"):
            connection_id = params[1]
            self.repo.connections[connection_id] = {"workspace": params[0], "connectionId": connection_id, "member": params[2], "provider": params[3],
                "accountId": params[4], "account": params[5], "access": params[6], "refresh": params[7], "key": params[8],
                "scopes": list(params[9]), "expires": params[10], "revoked": False}
        elif compact.startswith("SELECT connection_id,provider,account_label,access_ciphertext"):
            connection = self.repo.connections.get(params[2])
            if connection and connection["workspace"] == params[0] and connection["member"] == params[1]:
                self.one = (connection["connectionId"], connection["provider"], connection["account"], connection["access"], connection["refresh"],
                            connection["key"], connection["scopes"], connection["expires"], connection["revoked"])
        elif compact.startswith("INSERT INTO public.pr_connector_selections"):
            self.repo.selections[params[2]] = {"workspace": params[0], "member": params[1], "referenceId": params[2], "connectionId": params[3],
                "provider": params[4], "itemId": params[5], "title": params[6], "excerpt": params[7], "expires": params[8]}
        elif compact.startswith("SELECT s.reference_id,s.connection_id,s.provider"):
            selection = self.repo.selections.get(params[2])
            connection = self.repo.connections.get(selection["connectionId"]) if selection else None
            if selection and connection and selection["workspace"] == params[0] and selection["member"] == params[1] and selection["expires"] > self.repo.now:
                self.one = (selection["referenceId"], selection["connectionId"], selection["provider"], selection["itemId"], selection["title"],
                            connection["account"], connection["access"], connection["refresh"], connection["key"], connection["scopes"], connection["expires"], connection["revoked"])
        elif compact.startswith("UPDATE public.pr_connector_selections SET title="):
            selection = self.repo.selections.get(params[5])
            if selection and selection["workspace"] == params[3] and selection["member"] == params[4]:
                selection.update(title=params[0], digest=params[1], excerpt=params[2])
        elif compact.startswith("INSERT INTO public.pr_connector_fetches"):
            self.repo.fetches.append({"workspace": params[0], "member": params[1], "digest": params[2], "references": params[3],
                                      "providers": params[4], "count": params[5]})
        elif compact.startswith("DELETE FROM public.pr_connector_selections WHERE workspace_id=%s AND member_id=%s"):
            doomed = [key for key, item in self.repo.selections.items() if item["workspace"] == params[0] and item["member"] == params[1] and item["expires"] <= self.repo.now]
            for key in doomed:
                del self.repo.selections[key]
        elif compact.startswith("DELETE FROM public.pr_connector_selections"):
            doomed = [key for key, item in self.repo.selections.items() if item["workspace"] == params[0] and item["connectionId"] == params[1]]
            for key in doomed:
                del self.repo.selections[key]
        elif compact.startswith("UPDATE public.pr_connector_credentials SET revoked_at"):
            connection = self.repo.connections.get(params[1])
            if connection and connection["workspace"] == params[0]:
                connection.update(revoked=True, access="", refresh=None)
        elif compact.startswith("UPDATE public.pr_connector_credentials SET access_ciphertext="):
            connection = self.repo.connections[params[6]]
            connection.update(access=params[0], refresh=params[1], key=params[2], scopes=list(params[3]), expires=params[4])
        elif compact.startswith("SELECT connection_id,provider,account_label,scopes"):
            self.many = [
                (
                    connection["connectionId"],
                    connection["provider"],
                    connection["account"],
                    connection["scopes"],
                    Decimal(str(connection["expires"])) if connection["expires"] is not None else None,
                    connection["revoked"],
                )
                for connection in self.repo.connections.values()
                if connection["workspace"] == params[0] and connection["member"] == params[1]
            ]
        elif compact.startswith("UPDATE public.pr_connector_oauth_transactions"):
            pass
        else:
            raise AssertionError(compact)

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class FakeDB:
    def __init__(self, repo):
        self.repo = repo
    @contextmanager
    def cursor(self):
        yield FakeCursor(self.repo)
    def commit(self):
        return None


class FakeRepository:
    def __init__(self, state, now=1000.0):
        self.state, self.now = state, now
        self.oauth, self.connections, self.selections, self.fetches, self.sql = {}, {}, {}, [], []
        self.membership = ("owner", True, True, True, True)

    @contextmanager
    def transaction(self, token, workspace_id):
        # The token is the verified principal in this deliberately tiny fake.
        yield FakeCursor(self), (1, self.state, *self.membership), token

    @contextmanager
    def connection_factory(self):
        yield FakeDB(self)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.repo = FakeRepository({})
        self.vault = FakeVault()
        self.service = ProductivityConnectorService(self.repo, self.vault, {"notion": self.provider}, "https://app.example",
                                                    flags={"notion": True, "gmail": False}, clock=lambda: self.repo.now)

    def complete_from_start(self):
        started = self.service.start("w1", "u1", "notion")
        state = started["authorizeUrl"].split("?", 1)[1]
        completed = self.service.complete("w1", "u1", "notion", state, "code")
        picked = self.service.picker_search("w1", "u1", completed["connectionId"], "festival")
        return started, completed, picked

    def test_ids_oauth_picker_and_no_token_leakage(self):
        started, completed, picked = self.complete_from_start()
        self.assertRegex(completed["connectionId"], r"^pc_[0-9a-f]{32}$")
        reference_id = picked["items"][0]["referenceId"]
        self.assertRegex(reference_id, r"^ci_[0-9a-f]{32}$")
        browser_objects = json.dumps([started, completed, picked])
        for secret in ("plain-access-token", "plain-refresh-token"):
            self.assertNotIn(secret, browser_objects)
        stored = self.repo.connections[completed["connectionId"]]
        self.assertNotIn("plain-access-token", stored["access"])

    def test_catalog_serializes_postgres_decimal_expiry(self):
        _, completed, _ = self.complete_from_start()
        catalog = self.service.catalog("w1", "u1")
        json.dumps(catalog)
        connection = next(item for item in catalog["connections"] if item["connectionId"] == completed["connectionId"])
        self.assertIsInstance(connection["expiresAt"], float)
        self.assertEqual(connection["expiresAt"], self.repo.connections[completed["connectionId"]]["expires"])

    def test_turn_refetch_fails_closed_for_foreign_stale_and_records_exact_digest(self):
        _, completed, picked = self.complete_from_start()
        reference_id = picked["items"][0]["referenceId"]
        request_digest = "a" * 64
        foreign = self.service.turn_refetch("w1", "u2", [reference_id], request_digest)
        self.assertEqual(foreign[reference_id]["reason"], "connector_unavailable")
        self.assertEqual(self.provider.gets, [])
        self.repo.selections[reference_id]["expires"] = self.repo.now - 1
        stale = self.service.turn_refetch("w1", "u1", [reference_id], request_digest)
        self.assertEqual(stale[reference_id]["reason"], "connector_unavailable")
        self.assertEqual(self.repo.fetches[-1], {"workspace": "w1", "member": "u1", "digest": request_digest,
                                                "references": [reference_id], "providers": [], "count": 0})
        self.assertIn(completed["connectionId"], self.repo.connections)

    def test_refetch_source_egress_shape_and_audit(self):
        _, _, picked = self.complete_from_start()
        reference_id = picked["items"][0]["referenceId"]
        result = self.service.turn_refetch("w1", "u1", [reference_id], "b" * 64)
        source = result[reference_id]["source"]
        self.assertEqual((source["sourcePolicy"], source["egressConsent"]), ("rewrite_approval", ["local"]))
        self.assertTrue(all(fact["approved"] for fact in source["facts"]))
        self.assertEqual(self.repo.fetches[-1]["count"], 1)
        self.assertEqual(self.repo.fetches[-1]["references"], [reference_id])
        apply_connector_egress(self.repo.state, "connector_egress", {"cloud": True, "confirmed": True}, "owner", self.repo.now)
        allowed = self.service.turn_refetch("w1", "u1", [reference_id], "c" * 64)[reference_id]["source"]
        self.assertEqual(allowed["egressConsent"], ["local", "cloud"])

    def test_invalid_grant_revokes_and_purges_selection(self):
        _, completed, picked = self.complete_from_start()
        connection = self.repo.connections[completed["connectionId"]]
        connection["expires"] = self.repo.now - 1
        self.provider.refresh_invalid = True
        reference_id = picked["items"][0]["referenceId"]
        result = self.service.turn_refetch("w1", "u1", [reference_id], "d" * 64)
        self.assertEqual(result[reference_id]["reason"], "connector_fetch_failed")
        self.assertTrue(connection["revoked"])
        self.assertEqual(self.repo.selections, {})

    def test_refresh_and_disconnect_are_safe_and_cleanup_receipts(self):
        _, completed, picked = self.complete_from_start()
        connection_id = completed["connectionId"]
        refreshed = self.service.refresh("w1", "u1", connection_id)
        self.assertEqual(refreshed["refreshed"], True)
        self.assertNotIn("rotated-access-token", json.dumps(refreshed))
        self.assertIn(picked["items"][0]["referenceId"], self.repo.selections)
        disconnected = self.service.disconnect("w1", "u1", connection_id)
        self.assertEqual(disconnected, {"connectionId": connection_id, "provider": "notion", "disconnected": True,
                                        "providerRevocationPending": False})
        self.assertEqual(self.repo.selections, {})
        self.assertTrue(self.repo.connections[connection_id]["revoked"])

    def test_connection_mutations_require_manage_connections(self):
        self.repo.membership = ("editor", False, False, False, False)
        with self.assertRaises(AlphaError) as caught:
            self.service.start("w1", "u1", "notion")
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.repo.oauth, {})

    def test_disabled_provider_stops_before_oauth_or_http(self):
        off = ProductivityConnectorService(self.repo, self.vault, {"notion": self.provider}, "https://app.example", flags={})
        with self.assertRaises(AlphaError) as caught:
            off.start("w1", "u1", "notion")
        self.assertEqual(caught.exception.code, "feature_disabled")
        self.assertEqual(self.repo.oauth, {})

    def test_internal_personal_reads_use_encrypted_connected_credentials_and_bounded_metadata(self):
        gmail_calls, calendar_calls = [], []

        def gmail_respond(call):
            gmail_calls.append(call)
            if call["url"].endswith("/profile"):
                return {"status": 200, "body": {"emailAddress": "personal@example.com"}}
            if "/messages?" in call["url"]:
                return {"status": 200, "body": {"messages": [{"id": "m1"}]}}
            if "format=metadata" in call["url"]:
                return {"status": 200, "body": {"id": "m1", "snippet": "Weekend recording confirmed",
                    "payload": {"headers": [
                        {"name": "Subject", "value": "Recording time"},
                        {"name": "From", "value": "Violinist <music@example.com>"},
                        {"name": "Date", "value": "Fri"},
                    ]}}}
            raise AssertionError(call)

        def calendar_respond(call):
            calendar_calls.append(call)
            if call["url"].endswith("/calendars/primary"):
                return {"status": 200, "body": {"id": "personal@example.com"}}
            if "/calendars/primary/events?" in call["url"]:
                return {"status": 200, "body": {"items": [{"id": "e1", "summary": "Lori lesson",
                    "start": {"dateTime": "2026-10-05T15:30:00-05:00"},
                    "end": {"dateTime": "2026-10-05T16:30:00-05:00"},
                    "location": "Studio", "description": "PRIVATE DESCRIPTION"}]}}
            raise AssertionError(call)

        gmail = GmailProvider("client", "secret", Recorder(gmail_respond))
        calendar = GoogleCalendarProvider("client", "secret", Recorder(calendar_respond))
        service = ProductivityConnectorService(
            self.repo, self.vault, {"gmail": gmail, "google_calendar": calendar},
            "https://app.example", flags={"gmail": True, "google_calendar": True}, clock=lambda: self.repo.now,
        )
        for connection_id, provider, token, scopes in (
            ("pc_" + "1" * 32, "gmail", "gmail-access-secret", gmail.minimum_scopes()),
            ("pc_" + "2" * 32, "google_calendar", "calendar-access-secret", calendar.minimum_scopes()),
        ):
            cipher, key = self.vault.encrypt(token)
            self.repo.connections[connection_id] = {
                "workspace": "w1", "connectionId": connection_id, "member": "u1", "provider": provider,
                "accountId": "personal@example.com", "account": provider, "access": cipher, "refresh": None,
                "key": key, "scopes": list(scopes), "expires": self.repo.now + 3600, "revoked": False,
            }

        mail = service.personal_gmail_search("w1", "u1", 'in:inbox "recording"', 4, account_bindings=BINDINGS)
        events = service.personal_calendar_range("w1", "u1", "America/Chicago", self.repo.now, self.repo.now + 7 * 86400, 8,
                                                 account_bindings=BINDINGS)
        found = service.personal_calendar_search("w1", "u1", "Lori", 4, account_bindings=BINDINGS)
        context = service.daily_brief_context("w1", "u1", "America/Chicago", account_bindings=BINDINGS)

        self.assertEqual(mail[0]["subject"], "Recording time")
        self.assertEqual(events[0]["title"], "Lori lesson")
        self.assertEqual(found[0]["title"], "Lori lesson")
        self.assertEqual(context["gmail"]["status"], "ok")
        self.assertEqual(context["calendar"]["status"], "ok")
        self.assertEqual(context["gmail"]["connectionId"], BINDINGS["gmail"]["connectionId"])
        self.assertEqual(context["calendar"]["account"], "personal@example.com")
        encoded = json.dumps({"mail": mail, "events": events, "search": found})
        self.assertNotIn("gmail-access-secret", encoded)
        self.assertNotIn("calendar-access-secret", encoded)
        self.assertNotIn("PRIVATE DESCRIPTION", encoded)
        self.assertTrue(any("Authorization" in call["headers"] for call in gmail_calls))
        self.assertTrue(any("Authorization" in call["headers"] for call in calendar_calls))
        personal_queries = [(sql, params) for sql, params in self.repo.sql
                            if sql.startswith("SELECT connection_id FROM public.pr_connector_credentials")]
        self.assertTrue(personal_queries)
        self.assertTrue(all("connection_id=%s AND lower(provider_account_id)=%s" in sql and len(params) == 5
                            for sql, params in personal_queries))

    def bound_personal_service(self, authenticated_account="personal@example.com"):
        provider = Mock(spec=GmailProvider)
        provider.authenticated_account.return_value = authenticated_account
        provider.minimum_scopes.return_value = list(GmailProvider.scopes)
        provider.search.return_value = []
        connection_id = BINDINGS["gmail"]["connectionId"]
        cipher, key = self.vault.encrypt("synthetic-personal-token")
        self.repo.connections[connection_id] = {
            "workspace": "w1", "member": "u1", "provider": "gmail", "connectionId": connection_id,
            "accountId": "personal@example.com", "account": "Personal Gmail", "access": cipher, "refresh": None,
            "key": key, "scopes": list(GmailProvider.scopes), "expires": self.repo.now + 3600, "revoked": False,
        }
        service = ProductivityConnectorService(self.repo, self.vault, {"gmail": provider}, "https://app.example",
                                               flags={"gmail": True}, clock=lambda: self.repo.now)
        return service, provider

    def test_personal_reads_reject_unbound_account_before_provider_access(self):
        service, provider = self.bound_personal_service()
        with self.assertRaises(AlphaError) as raised:
            service.personal_gmail_search("w1", "u1", "in:inbox")
        self.assertEqual(raised.exception.code, "briefing_identity_unbound")
        provider.authenticated_account.assert_not_called()
        provider.search.assert_not_called()

    def test_personal_provider_identity_mismatch_never_returns_work_email(self):
        service, provider = self.bound_personal_service("work@example.com")
        with self.assertRaises(AlphaError) as raised:
            service.personal_gmail_search("w1", "u1", "in:inbox", account_bindings=BINDINGS)
        self.assertEqual(raised.exception.code, "briefing_identity_mismatch")
        provider.search.assert_not_called()

    def test_missing_personal_connection_never_uses_another_available_connection(self):
        service, provider = self.bound_personal_service()
        bindings = {"gmail": {"account": "personal@example.com", "connectionId": "pc_" + "3" * 32}}
        with self.assertRaises(AlphaError) as raised:
            service.personal_gmail_search("w1", "u1", "in:inbox", account_bindings=bindings)
        self.assertEqual(raised.exception.code, "connector_not_connected")
        provider.authenticated_account.assert_not_called()
        provider.search.assert_not_called()

    def test_synthetic_source_has_no_secret_fields(self):
        source = synthetic_source("gmail", "ci_" + "1" * 32, "pc_" + "2" * 32,
                                  {"itemId": "m1", "title": "Mail", "text": "Body"}, cloud=False, now=1)
        self.assertEqual(source["sourcePolicy"], "rewrite_approval")
        self.assertNotRegex(json.dumps(source), r"(?i)access.?token|refresh.?token|secret")


if __name__ == "__main__":
    unittest.main()

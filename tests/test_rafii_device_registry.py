"""Rafii Account Protection v2, P1 item 1: the device registry tells a new session apart from a new browser.

The server mints an opaque `__Host-rafii_device` cookie after identity is verified and stores only an HMAC of it
(keyed, versioned, bound to the user id). observe_session (every session route) and the token verifier link each
session to its browser and write `session.observed` / `device.first_observed` to the append-only ledger. All of it is
behind RAFII_DEVICE_TRUST_V2 plus a configured key plus observe mode; off adds no statement, cookie or header.

Statement-level tests over a recording cursor, in the style of test_rafii_account_protection_p0. The SQL itself (FKs,
append-only trigger, grants, purge) is proven against a disposable PostgreSQL by tests/phase2/postgres_device_registry.py.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_phase2 import device_trust, hosted_app  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.hosted import observe_session  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SESSION = "session-device-0123456789"
KEY_2, KEY_1 = "k" * 32, "o" * 32
ON = {"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe", "RAFII_DEVICE_TRUST_V2": "1", "RAFII_DEVICE_COOKIE_KEYS": f"2:{KEY_2},1:{KEY_1}"}
COOKIE = "A" * 43
DEVICE = "11111111-1111-4111-8111-111111111111"


def statements(cursor, table):
    return [(sql, params) for sql, params in cursor.executed if table in sql]


def events(cursor):
    return [(params[3], params[4], json.loads(params[5])) for sql, params in statements(cursor, "pr_security_login_events")]


class Case(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)
        flags.attach(dict(ON))

    def request(self, cookie="", site="same-origin"):
        environ = {"HTTP_COOKIE": cookie, "HTTP_SEC_FETCH_SITE": site} if site else {"HTTP_COOKIE": cookie}
        binding = device_trust.bind(environ)
        self.addCleanup(device_trust.reset, binding)
        return device_trust.current()


class Flags(Case):
    def test_on_only_with_the_flag_a_valid_key_and_observe_mode(self):
        self.assertTrue(device_trust.active())
        for change in ({"RAFII_DEVICE_TRUST_V2": ""}, {"RAFII_DEVICE_COOKIE_KEYS": ""}, {"RAFII_ACCOUNT_PROTECTION_V2_MODE": "off"},
                       {"RAFII_DEVICE_COOKIE_KEYS": "2:short"}, {"RAFII_DEVICE_COOKIE_KEYS": f"x:{KEY_2}"}, {"RAFII_DEVICE_COOKIE_KEYS": f"2:{KEY_2},2:{KEY_1}"}):
            self.assertFalse(device_trust.active({**ON, **change}), change)
        self.assertEqual(device_trust.keys(), [(2, KEY_2.encode()), (1, KEY_1.encode())])

    def test_the_hash_is_keyed_and_bound_to_the_person(self):
        one = device_trust.token_hash(KEY_2.encode(), base.PRINCIPAL, COOKIE)
        self.assertRegex(one, r"^[0-9a-f]{64}$")
        self.assertNotIn(COOKIE, one)
        self.assertNotEqual(one, device_trust.token_hash(KEY_2.encode(), "22222222-2222-4222-8222-222222222222", COOKIE))
        self.assertNotEqual(one, device_trust.token_hash(KEY_1.encode(), base.PRINCIPAL, COOKIE))

    def test_only_a_well_formed_cookie_is_read(self):
        self.assertEqual(self.request(f"a=b; {device_trust.COOKIE}={COOKIE}").presented(), COOKIE)
        for bad in ("A" * 42, "A" * 44, "A" * 42 + "=", "<script>" + "A" * 35):
            self.assertIsNone(self.request(f"{device_trust.COOKIE}={bad}").presented(), bad)
        self.assertIsNone(self.request(f"rafii_device={COOKIE}").presented())


class Register(Case):
    def observe(self, cursor, fresh=True):
        return observe_session(cursor, base.PRINCIPAL, SESSION, "Safari on iPhone")

    def test_a_new_browser_gets_a_cookie_a_record_and_both_first_sightings(self):
        request = self.request()
        cursor = base.FakeCursor([((True,), 1), ((False,), 1), (None, 1), ((DEVICE, True), 1), (None, 1), (None, 1), (None, 1)])
        self.observe(cursor)
        self.assertRegex(request.issued, r"^[A-Za-z0-9_-]{43}$")
        [(insert, params)] = [s for s in statements(cursor, "pr_security_devices") if s[0].startswith("INSERT")]
        self.assertEqual(params[0], base.PRINCIPAL)
        self.assertEqual(params[1], device_trust.token_hash(KEY_2.encode(), base.PRINCIPAL, request.issued))
        self.assertEqual(params[2], 2)
        self.assertNotIn(request.issued, json.dumps(cursor.executed))
        self.assertEqual(events(cursor), [
            ("device.first_observed", f"device.first_observed:{DEVICE}", {"client": "Safari on iPhone"}),
            ("session.observed", f"session.observed:{SESSION}", {"client": "Safari on iPhone", "device": "new"}),
        ])
        [(link, link_params)] = statements(cursor, "pr_session_security")
        self.assertEqual(link_params, (base.PRINCIPAL, SESSION, DEVICE))
        self.assertIn("coalesce(public.pr_session_security.device_id,excluded.device_id)", link)
        name, value = device_trust.set_cookie_header()
        self.assertEqual(name, "Set-Cookie")
        self.assertEqual(value, f"__Host-rafii_device={request.issued}; Max-Age=34560000; Path=/; Secure; HttpOnly; SameSite=Lax")
        self.assertNotIn("Domain", value)

    def test_a_new_session_on_a_known_browser_is_a_new_session_only(self):
        request = self.request(f"{device_trust.COOKIE}={COOKIE}")
        cursor = base.FakeCursor([((True,), 1), ((False,), 1), (None, 1), ((DEVICE, 2, "observed", False), 1), (None, 1), (None, 1), (None, 1)])
        self.observe(cursor)
        self.assertIsNone(request.issued)
        self.assertIsNone(device_trust.set_cookie_header())
        self.assertEqual([e[0] for e in events(cursor)], ["session.observed"])
        self.assertEqual(events(cursor)[0][2]["device"], "known")
        lookup = statements(cursor, "pr_security_devices")[0][1]
        self.assertEqual(lookup[2], [device_trust.token_hash(KEY_2.encode(), base.PRINCIPAL, COOKIE), device_trust.token_hash(KEY_1.encode(), base.PRINCIPAL, COOKIE)])

    def test_a_match_under_the_old_key_is_rehashed_under_the_current_one(self):
        self.request(f"{device_trust.COOKIE}={COOKIE}")
        cursor = base.FakeCursor([((DEVICE, 1, "observed", False), 1), (None, 1)])
        self.assertEqual(device_trust.register(cursor, base.PRINCIPAL, SESSION), {"id": DEVICE, "new": False})
        sql, params = cursor.executed[1]
        self.assertIn("SET token_hash=%s,hmac_key_version=%s", sql)
        self.assertEqual(params, (device_trust.token_hash(KEY_2.encode(), base.PRINCIPAL, COOKIE), 2, base.PRINCIPAL, DEVICE))

    def test_a_revoked_browser_gets_a_new_token_and_record(self):
        request = self.request(f"{device_trust.COOKIE}={COOKIE}")
        cursor = base.FakeCursor([((DEVICE, 2, "revoked", False), 1), (("22222222-2222-4222-8222-222222222222", True), 1), (None, 1)])
        device = device_trust.register(cursor, base.PRINCIPAL, SESSION)
        self.assertEqual(device["new"], True)
        self.assertNotEqual(request.issued, COOKIE)
        self.assertEqual(cursor.executed[1][1][1], device_trust.token_hash(KEY_2.encode(), base.PRINCIPAL, request.issued))

    def test_a_browser_idle_past_the_inactivity_limit_is_registered_again(self):
        # RAP-138: the old record is revoked (kept as evidence) and the browser gets a new token and record.
        request = self.request(f"{device_trust.COOKIE}={COOKIE}")
        cursor = base.FakeCursor([((DEVICE, 2, "observed", True), 1), (None, 1), (None, 1), (("22222222-2222-4222-8222-222222222222", True), 1), (None, 1)])
        device = device_trust.register(cursor, base.PRINCIPAL, SESSION)
        self.assertEqual(device, {"id": "22222222-2222-4222-8222-222222222222", "new": True})
        self.assertEqual(cursor.executed[0][1][0], device_trust.INACTIVE_SECONDS)
        expire_sql, expire = cursor.executed[1]
        self.assertIn("state='revoked'", expire_sql)
        self.assertIn("revoke_reason='inactive'", expire_sql)
        self.assertEqual(expire, (base.PRINCIPAL, DEVICE))
        self.assertEqual(cursor.executed[2][1][3:5], ("device.revoked", f"device.revoked:{DEVICE}:inactive"))
        self.assertNotEqual(request.issued, COOKIE)

    def test_an_unknown_cookie_never_matches_another_persons_record(self):
        # The same browser cookie under a second account is looked up with that account's hashes only.
        self.request(f"{device_trust.COOKIE}={COOKIE}")
        other = "22222222-2222-4222-8222-222222222222"
        cursor = base.FakeCursor([(None, 1), ((DEVICE, True), 1), (None, 1)])
        device_trust.register(cursor, other, SESSION)
        self.assertEqual(cursor.executed[0][1][1], other)
        self.assertNotIn(device_trust.token_hash(KEY_2.encode(), base.PRINCIPAL, COOKIE), json.dumps(cursor.executed))

    def test_a_server_side_first_request_records_the_session_and_leaves_the_device_pending(self):
        request = self.request(site=None)
        cursor = base.FakeCursor([((True,), 1), ((False,), 1), (None, 1), (None, 1), (None, 1)])
        self.observe(cursor)
        self.assertIsNone(request.issued)
        self.assertEqual(statements(cursor, "pr_security_devices"), [])
        self.assertEqual(statements(cursor, "pr_session_security")[0][1], (base.PRINCIPAL, SESSION, None))
        self.assertEqual(events(cursor)[0][2]["device"], "pending")
        self.assertIsNone(device_trust.seen_marker())

    def test_outside_a_request_no_device_is_registered(self):
        self.assertIsNone(device_trust.current())
        self.assertIsNone(device_trust.register(base.FakeCursor(), base.PRINCIPAL, SESSION))


class Off(Case):
    def test_flag_off_adds_no_statement_and_no_cookie(self):
        for values in ({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe"}, {**ON, "RAFII_DEVICE_TRUST_V2": "0"}, {}):
            flags.attach(values)
            request = self.request()
            cursor = base.FakeCursor([((True,), 1), ((False,), 1), (None, 1)])
            observe_session(cursor, base.PRINCIPAL, SESSION, "Safari on iPhone")
            self.assertEqual(statements(cursor, "pr_security"), [], values)
            self.assertEqual(statements(cursor, "pr_session_security"), [], values)
            self.assertIsNone(request.issued)
            self.assertIsNone(device_trust.seen_marker())


class Wsgi(Case):
    class Service(base.FakeAccountService):
        def me(self, token, client_label=""):
            if device_trust.active():
                device_trust.current().issued = COOKIE
            return super().me(token, client_label)

    def call(self):
        captured = {}
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/me", "wsgi.input": None, "wsgi.url_scheme": "https", "HTTP_HOST": "postriff.example", "HTTP_AUTHORIZATION": base.AUTH["Authorization"]}
        app = HostedApplication(self.Service(), None, {"provider": "supabase"}, "c" * 24)
        b"".join(app(environ, lambda status, values: captured.update(status=status, headers=list(values))))
        return [value for name, value in captured["headers"] if name == "Set-Cookie"]

    def test_a_minted_cookie_is_set_on_the_response(self):
        self.assertEqual(self.call(), [f"__Host-rafii_device={COOKIE}; Max-Age=34560000; Path=/; Secure; HttpOnly; SameSite=Lax"])

    def test_flag_off_sets_no_cookie(self):
        flags.attach({})
        self.assertEqual(self.call(), [])


class VerifierSeenKey(Case):
    def test_a_session_first_seen_without_its_browser_is_observed_again_when_the_browser_arrives(self):
        self.request(site=None)
        self.assertIsNone(device_trust.seen_marker())
        self.request()
        self.assertEqual(device_trust.seen_marker(), "device")


class Migration(unittest.TestCase):
    SQL = (ROOT / "migrations" / "postriff" / "120_rapv2_device_registry.sql").read_text()

    def test_server_only_append_only_and_no_cascade(self):
        sql = re.sub(r"--[^\n]*", "", self.SQL).lower()
        for table in ("pr_security_devices", "pr_session_security", "pr_security_login_events"):
            self.assertIn(f"alter table public.{table} force row level security", sql)
            self.assertIn(f"create policy rapv2_service_only on public.{table} for all to service_role", sql)
        self.assertIn("revoke all on public.pr_security_devices, public.pr_session_security, public.pr_security_login_events from public, anon, authenticated", sql)
        self.assertNotIn("to authenticated", sql.replace("from public, anon, authenticated", ""))
        self.assertIn("grant select, insert on public.pr_security_login_events to service_role", sql)
        self.assertIn("before update or delete on public.pr_security_login_events", sql)
        self.assertIn("before truncate on public.pr_security_login_events", sql)
        self.assertNotIn("on delete cascade", sql)
        self.assertIn("foreign key (user_id, device_id) references public.pr_security_devices (user_id, id)", sql)
        self.assertIn("unique (user_id, id)", sql)
        self.assertIn("security definer set search_path = ''", sql)
        self.assertIn("revoke all on function public.pr_security_purge(uuid) from public, anon, authenticated", sql)

    def test_the_harness_applies_it(self):
        self.assertIn("120_rapv2_device_registry.sql", (ROOT / "tests" / "phase2" / "rls.sql").read_text())

    def test_account_deletion_purges_it_only_when_installed(self):
        source = (ROOT / "src" / "postriff_phase2" / "account_deletion.py").read_text()
        self.assertIn("to_regprocedure('public.pr_security_purge(uuid)')", source)
        self.assertLess(source.index("pr_account_tombstones(user_id,plan,trial_started_at)"), source.index("SELECT public.pr_security_purge(%s)"))

    def test_ssr_forwards_only_a_well_formed_device_cookie(self):
        source = (ROOT / "web" / "src" / "lib" / "workspace" / "server-bootstrap.ts").read_text()
        self.assertIn("/^[A-Za-z0-9_-]{43}$/.test(device)", source)
        self.assertTrue(re.search(r"__Host-rafii_device=\$\{device\}", source))


if __name__ == "__main__":
    unittest.main()

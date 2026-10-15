"""Rafii Account Protection v2, P1 item 2: deterministic risk policy and step-up on sensitive capabilities.

security_policy is pure (no I/O, no model) and versioned; security_gate applies it in front of creating API tokens,
connecting accounts, widening Agent permissions and exports, only under RAFII_ACCOUNT_PROTECTION_V2_MODE=enforce.
Step-up is a fresh independent second factor on an AAL2 session read from the signed `amr` claim: never the JWT `iat`,
never a same-inbox one-time code. Statement-level tests over a recording cursor.
"""
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import security_gate, security_policy as policy  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication  # noqa: E402

NOW = 1_800_000_000.0
SESSION = "session-risk-0123456789"
WORKSPACE = "00000000-0000-0000-0000-0000000000aa"
TOTP = policy.Proof("totp", NOW - 30, "aal2")
KNOWN = policy.Signals(device="known")


class Policy(unittest.TestCase):
    def test_a_known_browser_without_recent_changes_needs_no_extra_proof(self):
        for capability in policy.SENSITIVE:
            decision = policy.evaluate(KNOWN, policy.Proof(), NOW, capability)
            self.assertEqual((decision.outcome, decision.risk_level, decision.reasons), ("allow", "low", ()))

    def test_an_unknown_browser_must_step_up_for_each_sensitive_capability(self):
        for device in (None, "new"):
            for capability in policy.SENSITIVE:
                decision = policy.evaluate(policy.Signals(device=device), policy.Proof(), NOW, capability)
                self.assertEqual((decision.outcome, decision.enforcement, decision.risk_level, decision.reasons), ("step_up", "challenge", "medium", ("unknown_device",)))

    def test_only_a_fresh_independent_factor_on_aal2_counts(self):
        unknown = policy.Signals(device="new")
        self.assertEqual(policy.evaluate(unknown, TOTP, NOW, "exports").step_up_method, "totp")
        self.assertEqual(policy.evaluate(unknown, policy.Proof("mfa/webauthn", NOW - 5, "aal2"), NOW, "exports").step_up_method, "webauthn_mfa")
        refused = {
            "refreshed token (no amr method; iat is never read)": policy.Proof(None, 0, "aal2"),
            "same-inbox email one-time code": policy.Proof("otp", NOW - 5, "aal2"),
            "magic link": policy.Proof("magiclink", NOW - 5, "aal2"),
            "password": policy.Proof("password", NOW - 5, "aal2"),
            "oauth": policy.Proof("oauth", NOW - 5, "aal2"),
            "passkey sign-in (AAL1)": policy.Proof("passkey", NOW - 5, "aal1"),
            "totp on an aal1 token": policy.Proof("totp", NOW - 5, "aal1"),
            "stale totp": policy.Proof("totp", NOW - policy.STEP_UP_SECONDS - 1, "aal2"),
            "totp from the future": policy.Proof("totp", NOW + 120, "aal2"),
        }
        for name, proof in refused.items():
            self.assertEqual(policy.evaluate(unknown, proof, NOW, "api_tokens").outcome, "step_up", name)

    def test_a_recent_factor_or_sign_out_change_elevates(self):
        self.assertEqual(policy.assess(policy.Signals(device="known", recent_change=True)), ("medium", ("recent_account_change",)))
        self.assertEqual(policy.assess(policy.Signals(device=None, recent_change=True)), ("high", ("unknown_device", "recent_account_change")))
        self.assertEqual(policy.assess(policy.Signals(device="revoked")), ("high", ("revoked_device",)))
        self.assertEqual(policy.evaluate(policy.Signals(device="known", recent_change=True), policy.Proof(), NOW, "connections").outcome, "step_up")

    def test_revocation_wins_and_non_sensitive_capabilities_pass(self):
        self.assertEqual(policy.evaluate(policy.Signals(revoked=True, device="known"), TOTP, NOW, "exports").outcome, "revoked")
        self.assertEqual(policy.evaluate(policy.Signals(device=None, recent_change=True), policy.Proof(), NOW, "read_drafts").outcome, "allow")

    def test_deterministic_and_versioned(self):
        runs = {policy.evaluate(policy.Signals(device=None), policy.Proof("otp", NOW, "aal2"), NOW, "exports") for _ in range(5)}
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs.pop().body(), {"outcome": "step_up", "riskLevel": "medium", "reasonCodes": ["unknown_device"], "policyVersion": 1})

    def test_no_model_is_imported(self):
        source = (Path(policy.__file__)).read_text() + Path(security_gate.__file__).read_text()
        for name in ("anthropic", "openai", "llm", "gateway", "model_router"):
            self.assertNotIn(f"import {name}", source)


class Capabilities(unittest.TestCase):
    def test_sensitive_routes_map_and_protective_ones_do_not(self):
        cases = {
            ("POST", f"api/workspaces/{WORKSPACE}/tokens"): "api_tokens",
            ("POST", f"api/workspaces/{WORKSPACE}/channels/threads/oauth/start"): "connections",
            ("POST", f"api/workspaces/{WORKSPACE}/channels/threads/oauth/complete"): "connections",
            ("POST", f"api/workspaces/{WORKSPACE}/connectors/google_drive/oauth/start"): "connections",
            # Widening Agent permissions is checked inside apply_decision, only when the change widens (see AgentGrants).
            ("PUT", f"api/workspaces/{WORKSPACE}/agent/permissions"): None,
            ("GET", f"api/workspaces/{WORKSPACE}/export"): "exports",
            ("GET", f"api/workspaces/{WORKSPACE}/profile-export"): "exports",
            # Protective or read-only: never gated, so a person under challenge can still lock things down.
            ("DELETE", f"api/workspaces/{WORKSPACE}/tokens/abc"): None,
            ("GET", f"api/workspaces/{WORKSPACE}/tokens"): None,
            ("DELETE", f"api/workspaces/{WORKSPACE}/channels/threads"): None,
            ("POST", f"api/workspaces/{WORKSPACE}/agent/permissions/revoke"): None,
            ("GET", f"api/workspaces/{WORKSPACE}/agent/permissions"): None,
            ("POST", "api/auth/sessions/revoke-others"): None,
            ("GET", f"api/workspaces/{WORKSPACE}"): None,
        }
        for (method, path), expected in cases.items():
            self.assertEqual(security_gate.capability_for(method, path.split("/")), expected, (method, path))


class Gate(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce"})
        self.verified = []

    def service(self, cursor, proof=policy.Proof()):
        def verify(token):
            self.verified.append(token)
            return base.PRINCIPAL
        verify.session_id = lambda token, principal: SESSION
        verify.method_time = lambda token, principal: (proof.method, proof.at)
        verify.aal = lambda token, principal: proof.aal
        return SimpleNamespace(repository=SimpleNamespace(verify_session=verify), connection_factory=lambda: base.FakeDB(cursor), clock=lambda: NOW)

    def test_off_and_observe_run_nothing(self):
        for values in ({}, {"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe"}):
            flags.attach(values)
            cursor = base.FakeCursor()
            self.assertIsNone(security_gate.require(self.service(cursor), "t" * 40, "exports"))
            self.assertEqual((cursor.executed, self.verified), ([], []))

    def test_known_browser_is_allowed_and_the_decision_recorded(self):
        cursor = base.FakeCursor([((False, "known", False), 1), (None, 1)])
        decision = security_gate.require(self.service(cursor), "t" * 40, "exports")
        self.assertEqual(decision.outcome, "allow")
        signals_sql, params = cursor.executed[0]
        self.assertIn("pr_session_revocations", signals_sql)
        self.assertEqual(params[:5], (base.PRINCIPAL, SESSION, base.PRINCIPAL, SESSION, []))
        self.assertEqual(params[5], base.PRINCIPAL)
        update_sql, update = cursor.executed[1]
        self.assertIn("UPDATE public.pr_session_security", update_sql)
        self.assertEqual(update[:4], ("low", "allow", "[]", 1))
        self.assertEqual(len(cursor.executed), 2)

    def test_unknown_browser_without_fresh_factor_is_refused_with_no_effect(self):
        cursor = base.FakeCursor([((False, None, False), 1), (None, 1)])
        with self.assertRaises(AlphaError) as raised:
            security_gate.require(self.service(cursor, policy.Proof("otp", NOW - 5, "aal2")), "t" * 40, "api_tokens")
        self.assertEqual((raised.exception.status, raised.exception.code), (403, "security_step_up_required"))
        self.assertEqual(raised.exception.public_fields["nextAction"], "complete_mfa")
        self.assertEqual(raised.exception.public_fields["security"]["reasonCodes"], ["unknown_device"])
        self.assertEqual(cursor.executed[1][1][:2], ("medium", "challenge"))

    def test_fresh_totp_satisfies_and_is_recorded_once(self):
        cursor = base.FakeCursor([((False, "new", False), 1), (None, 1), (None, 1)])
        decision = security_gate.require(self.service(cursor, TOTP), "t" * 40, "connections")
        self.assertEqual((decision.outcome, decision.step_up_method), ("allow", "totp"))
        event_sql, event = cursor.executed[2]
        self.assertIn("pr_security_login_events", event_sql)
        self.assertEqual(event[3:5], ("session.step_up_verified", f"session.step_up_verified:{SESSION}:{int(TOTP.at)}"))
        self.assertIn("ON CONFLICT DO NOTHING", event_sql)

    def test_known_means_this_requests_cookie_matches_the_sessions_device(self):
        # A copied bearer without the browser's cookie (or with another one) never reads as a known browser: the
        # device lookup is constrained to the hashes of the cookie this request presents.
        from postriff_phase2 import device_trust
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce", "RAFII_DEVICE_COOKIE_KEYS": "1:" + "k" * 32})
        binding = device_trust.bind({"HTTP_COOKIE": f"{device_trust.COOKIE}={'A' * 43}"})
        self.addCleanup(device_trust.reset, binding)
        cursor = base.FakeCursor([((False, None, False), 1), (None, 1)])
        with self.assertRaises(AlphaError):
            security_gate.require(self.service(cursor), "t" * 40, "exports")
        sql, params = cursor.executed[0]
        self.assertIn("d.token_hash = ANY(%s)", sql)
        self.assertNotIn("LEFT JOIN public.pr_security_devices", sql)
        self.assertEqual(params[4], [device_trust.token_hash(b"k" * 32, base.PRINCIPAL, "A" * 43)])

    def test_api_tokens_cannot_use_sensitive_capabilities(self):
        cursor = base.FakeCursor()
        with self.assertRaises(AlphaError) as raised:
            security_gate.require(self.service(cursor), "prt_" + "x" * 40, "exports")
        self.assertEqual(raised.exception.code, "security_step_up_required")
        self.assertEqual((cursor.executed, self.verified), ([], []))

    def test_unreadable_security_state_fails_closed(self):
        class Broken(base.FakeCursor):
            def execute(self, sql, params=None):
                raise RuntimeError('relation "public.pr_session_security" does not exist')
        with self.assertRaises(AlphaError) as raised:
            security_gate.require(self.service(Broken()), "t" * 40, "exports")
        self.assertEqual((raised.exception.status, raised.exception.code), (503, "security_state_unavailable"))

    def test_a_revoked_session_is_unauthenticated(self):
        cursor = base.FakeCursor([((True, "known", False), 1), (None, 1)])
        with self.assertRaises(AlphaError) as raised:
            security_gate.require(self.service(cursor, TOTP), "t" * 40, "exports")
        self.assertEqual((raised.exception.status, raised.exception.code), (401, "session_revoked"))


class AgentGrants(unittest.TestCase):
    def test_only_a_widening_change_meets_the_gate(self):
        source = (Path(security_gate.__file__).parent / "agent_runtime_v2" / "agent_permissions.py").read_text()
        decide = source[source.index("def apply_decision"):source.index("def revoke(")]
        self.assertIn("if widened and on_widen is not None:\n        on_widen()", decide)
        self.assertLess(decide.index("on_widen()"), decide.index("receipt_id = _write("))
        http = (Path(security_gate.__file__).parent / "agent_runtime_v2" / "agent_permissions_http.py").read_text()
        self.assertIn('on_widen=lambda: security_require(service, token, "agent_grants")', http)


class Wsgi(Gate):
    def test_enforce_refuses_the_export_before_the_service_runs(self):
        cursor = base.FakeCursor([((False, None, False), 1), (None, 1)])
        service = self.service(cursor)
        service.export = lambda *args: self.fail("the export ran")
        app = HostedApplication(service, None, {"provider": "supabase"}, "c" * 24)
        status, body = base.invoke(app, "GET", f"/api/workspaces/{WORKSPACE}/export", headers=base.AUTH)
        self.assertEqual((status, body["code"], body["nextAction"]), (403, "security_step_up_required", "complete_mfa"))
        self.assertEqual(body["security"], {"outcome": "step_up", "riskLevel": "medium", "reasonCodes": ["unknown_device"], "policyVersion": 1})

    def test_off_leaves_error_bodies_unchanged(self):
        flags.attach({})
        app = HostedApplication(base.FakeAccountService(), None, {"provider": "supabase"}, "c" * 24)
        status, body = base.invoke(app, "GET", "/api/me")
        self.assertEqual(set(body), {"error", "code"})


if __name__ == "__main__":
    unittest.main()

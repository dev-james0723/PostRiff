"""Unit tests for the Q-05 probe that need no database.

Covers: the redirect-safe HTTP client (a 3xx is the observed status and Authorization is never
resent to the Location), the A!=B refusal, and the strict scope-based scoring + ws-scope
differential (via a fake client), including the INCONCLUSIVE classes.
"""
import json
import os
import sys
import threading
import unittest
from wsgiref.simple_server import WSGIServer, make_server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import q05_tenant_probe as probe  # noqa: E402


class _QuietWSGI(WSGIServer):
    def handle_error(self, *a):
        pass


class RedirectApp:
    """Records which paths were hit and whether each carried an Authorization header."""
    def __init__(self):
        self.seen = {}

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        self.seen[path] = bool(environ.get("HTTP_AUTHORIZATION"))
        if path == "/redirect-get":
            start_response("302 Found", [("Location", "http://other.invalid/sink"), ("Content-Length", "0")])
            return [b""]
        if path == "/redirect-post":
            start_response("303 See Other", [("Location", "http://other.invalid/sink"), ("Content-Length", "0")])
            return [b""]
        body = b'{"error":"Workspace unavailable.","code":"x"}'
        start_response("403 Forbidden", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]


class RedirectSafety(unittest.TestCase):
    def setUp(self):
        self.app = RedirectApp()
        self.httpd = make_server("127.0.0.1", 0, self.app, server_class=_QuietWSGI)
        self.port = self.httpd.server_port
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def client(self):
        cfg = probe.Config({"Q05_BASE_URL": f"http://127.0.0.1:{self.port}",
                            "Q05_TOKEN_A": "tok-a-aaaaaaaaaaaaaaaaaaaa", "Q05_TOKEN_B": "tok-b-bbbbbbbbbbbbbbbbbbbb",
                            "Q05_WORKSPACE_A": "wsa", "Q05_WORKSPACE_B": "wsb"})
        return probe.Client(cfg, probe.Budget(50), 0)

    def test_get_302_not_followed_and_auth_not_forwarded(self):
        status, _t, _o = self.client().request("GET", "/redirect-get", "A")
        self.assertEqual(status, 302)
        self.assertTrue(self.app.seen.get("/redirect-get"))      # Authorization WAS sent to our origin
        self.assertNotIn("/sink", self.app.seen)                 # the redirect target was never contacted

    def test_post_303_not_followed(self):
        status, _t, _o = self.client().request("POST", "/redirect-post", "A", body={}, mutation=True)
        self.assertEqual(status, 303)
        self.assertNotIn("/sink", self.app.seen)


class ABGuard(unittest.TestCase):
    def _run(self, env):
        base = {"Q05_BASE_URL": "http://127.0.0.1:1", "Q05_TOKEN_A": "a" * 30, "Q05_TOKEN_B": "b" * 30,
                "Q05_WORKSPACE_A": "ws-a", "Q05_WORKSPACE_B": "ws-b"}
        base.update(env)
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(base)
        try:
            # a high budget so only the A!=B guard can return 2 (not budget exhaustion); the
            # base URL is unreachable, so a distinct-tenant run fails later with exit 1.
            return probe.main(["--budget", "5000", "--delay", "0"])
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_same_workspace_refused(self):
        self.assertEqual(self._run({"Q05_WORKSPACE_B": "ws-a"}), 2)

    def test_same_sub_refused(self):
        import base64, json
        def jwt(sub, sig):
            payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
            return "h." + payload + "." + sig
        # two DIFFERENT tokens of the same user (two sessions): only the subject check can refuse them
        self.assertEqual(self._run({"Q05_TOKEN_A": jwt("same-user", "s1"), "Q05_TOKEN_B": jwt("same-user", "s2")}), 2)

    def test_identical_tokens_refused_even_when_opaque(self):
        self.assertEqual(self._run({"Q05_TOKEN_A": "opaque-token-1", "Q05_TOKEN_B": "opaque-token-1"}), 2)

    def test_distinct_tenants_pass_the_guard(self):
        # distinct workspaces + distinct subs: the guard does not refuse (the run then fails later
        # on the unreachable base URL, which is exit 1 or a transport error, not the guard's 2-with-message).
        import base64, json
        def jwt(sub):
            payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
            return "h." + payload + ".s"
        rc = self._run({"Q05_TOKEN_A": jwt("user-a"), "Q05_TOKEN_B": jwt("user-b")})
        self.assertNotEqual(rc, 2)


class FakeClient:
    """Returns a scripted (status, text, obj) by token_key, recording calls."""
    def __init__(self, by_token):
        self.by_token = by_token
        self.calls = []
        self.last_provider = None   # (calls, writes) when a local harness attributes them; None = unobservable

    def request(self, method, path, token_key, *, body=None, mutation=False):
        self.calls.append((token_key, path))
        return self.by_token[token_key]


def _disc():
    a, b = probe.Discovery("A", "wsa"), probe.Discovery("B", "wsb")
    return {"A": a, "B": b}


def gate_403():
    return (403, "", {"error": probe.GATE_DENY_BODY, "code": "x"})


def idor_404():
    return (404, "", {"error": "Connection unavailable.", "code": "x"})


class Scoring(unittest.TestCase):
    def score(self, scope, attacker_resp, owner_resp=None, differential=False):
        case = probe.Case("t", "GET", "/t", "A->B", "read", "", "/t", "A",
                          victim_key="B", scope=scope, differential=differential,
                          owner_token_key="B" if differential else None)
        by = {"A": attacker_resp}
        if owner_resp is not None:
            by["B"] = owner_resp
        probe.run_case(FakeClient(by), case, _disc(), probe.Flags(_Args()))
        return case.verdict

    def test_ws_scope_gate_403_with_differential_passes(self):
        self.assertEqual(self.score("ws_scope", gate_403(), owner_resp=idor_404(), differential=True), "PASS")

    def test_ws_scope_owner_also_gate_is_inconclusive(self):
        self.assertEqual(self.score("ws_scope", gate_403(), owner_resp=gate_403(), differential=True), "INCONCLUSIVE")

    def test_ws_scope_404_fails_gate_not_reached(self):
        self.assertEqual(self.score("ws_scope", idor_404()), "FAIL")

    def test_ws_scope_wrong_403_body_inconclusive(self):
        self.assertEqual(self.score("ws_scope", (403, "", {"error": "This action needs the 'x' permission.", "code": "y"})), "INCONCLUSIVE")

    def test_ws_scope_2xx_fails(self):
        self.assertEqual(self.score("ws_scope", (200, '{"ok":1}', {"ok": 1})), "FAIL")

    def test_ws_scope_redirect_inconclusive(self):
        self.assertEqual(self.score("ws_scope", (302, "", None)), "INCONCLUSIVE")

    def test_ws_scope_429_inconclusive(self):
        self.assertEqual(self.score("ws_scope", (429, "", {"error": "Too many", "code": "r"})), "INCONCLUSIVE")

    def test_idor_404_known_body_passes(self):
        self.assertEqual(self.score("idor", idor_404()), "PASS")

    def test_idor_404_unknown_body_inconclusive(self):
        self.assertEqual(self.score("idor", (404, "", {"error": "Not found", "code": "z"})), "INCONCLUSIVE")

    def test_idor_2xx_fails(self):
        self.assertEqual(self.score("idor", (200, "x", {"connectionId": "y"})), "FAIL")

    def test_idor_5xx_inconclusive(self):
        self.assertEqual(self.score("idor", (502, "<html>bad</html>", None)), "INCONCLUSIVE")


class _Args:
    allow_writes = allow_send_risk = victim_is_synthetic = smoke = True


class PathClient:
    """Scripted answers by PATH, with a scripted elapsed time and provider attribution per answer."""
    def __init__(self, by_path, elapsed=None, provider=None):
        self.by_path, self.elapsed, self.provider = by_path, elapsed or {}, provider or {}
        self.last_provider = self.last_elapsed = None
        self.calls = []

    def request(self, method, path, token_key, *, body=None, mutation=False):
        self.calls.append((method, path, body))
        self.last_provider = self.provider.get(path)
        self.last_elapsed = self.elapsed.get(path)
        return self.by_path[path]


SENDER = "/api/workspaces/wsa/channels/{}/discord-sender-name"


class SenderScoring(unittest.TestCase):
    """The sender-name additions: role profiles and accepted pairs, local-only role cases, the whole-body
    existence twin and the timing comparison, and the cross-tenant clear cases."""

    def run_role(self, role, kind, method, answer, provider=(0, 0)):
        pairs, twin, profile = probe.role_expect(role, kind, method, 2)
        path = SENDER.format("conn-" + kind)
        case = probe.Case("read.sender.role.x", method, "/t", "A:" + role, "read", "", path, "A.admin",
                          scope="role", expect_pairs=pairs, role_profile=profile, late=profile == "manager")
        probe.run_case(PathClient({path: answer}, provider={path: provider}), case, _disc(), probe.Flags(_Args()))
        return case

    def test_role_profiles(self):
        readonly = {"connectionId": "conn-bot", "editable": False, "observedAt": None,
                    "unavailable": [{"code": "not_authorizing_member"}]}
        editable = {"connectionId": "conn-webhook", "editable": True, "observedAt": 1.0, "unavailable": []}
        # a bot nickname is authorizer-only: the read-only answer passes, an offered edit fails
        self.assertEqual(self.run_role("admin", "bot", "GET", (200, "", readonly)).verdict, "PASS")
        self.assertEqual(self.run_role("admin", "bot", "GET", (200, "", dict(editable, connectionId="conn-bot")),
                                       provider=(3, 0)).verdict, "FAIL")
        # a read-only answer that read Discord fails
        self.assertEqual(self.run_role("admin", "bot", "GET", (200, "", dict(readonly, observedAt=2.0))).verdict, "FAIL")
        # a webhook name: any connection manager may edit (contract head); reads allowed, no write
        self.assertEqual(self.run_role("admin", "webhook", "GET", (200, "", editable), provider=(1, 0)).verdict, "PASS")
        self.assertEqual(self.run_role("admin", "webhook", "GET", (200, "", editable), provider=(1, 1)).verdict, "FAIL")
        # the profile of another connection is never acceptable
        self.assertEqual(self.run_role("admin", "webhook", "GET", (200, "", dict(editable, connectionId="other")),
                                       provider=(1, 0)).verdict, "FAIL")

    def test_role_pairs(self):
        stale = (409, "", {"error": probe.SENDER_STALE_BODY, "code": "discord_sender_name_required"})
        unavailable = (403, "", {"error": probe.UNAVAILABLE_BODY, "code": "discord_sender_name_unavailable"})
        self.assertEqual(self.run_role("admin", "webhook", "POST", stale).verdict, "PASS")
        self.assertEqual(self.run_role("admin", "bot", "POST", unavailable).verdict, "PASS")
        # the bot nickname must be refused by the authorizer rule, not merely by the fingerprint
        self.assertEqual(self.run_role("admin", "bot", "POST", stale).verdict, "INCONCLUSIVE")
        # a refused write that reached the provider fails
        self.assertEqual(self.run_role("admin", "bot", "POST", unavailable, provider=(1, 0)).verdict, "FAIL")

    def test_role_cases_without_a_role_token_are_local_only(self):
        config = probe.Config({"Q05_BASE_URL": "http://127.0.0.1:1", "Q05_TOKEN_A": "a", "Q05_TOKEN_B": "b",
                               "Q05_WORKSPACE_A": "wsa", "Q05_WORKSPACE_B": "wsb"})
        disc = probe._full_discovery(config)
        for d in disc.values():
            d.sender_contract = 2
        cases = [c for c in probe.build_sender_cases(disc, config) if ".role." in c.cid]
        self.assertTrue(cases)
        for c in cases:
            probe.run_case(None, c, disc, probe.Flags(_Args()))
            self.assertEqual((c.verdict, c.scope), ("NOT_RUN", "role"))
            self.assertTrue(c.note.startswith("local-only:"), c.note)
        summary = probe.summarize(cases)
        self.assertEqual((summary["local_only"], summary["undiscovered"], summary["exit"]), (len(cases), 0, 0))

    def twin_case(self, victim, twin, v_time=0.01, t_time=0.01):
        path, twin_path = SENDER.format("victim-conn"), SENDER.format("never-existed")
        case = probe.Case("read.sender.idor.webhook.A->B", "GET", "/t", "A->B", "read", "", path, "A",
                          victim_key="B", scope="idor", twin_path=twin_path)
        client = PathClient({path: victim, twin_path: twin}, elapsed={path: v_time, twin_path: t_time})
        probe.run_case(client, case, _disc(), probe.Flags(_Args()))
        return case

    def test_whole_body_twin(self):
        body = {"error": "This Discord connection is unavailable.", "code": "not_found"}
        self.assertEqual(self.twin_case((404, "", body), (404, "", dict(body))).verdict, "PASS")
        # same status, error and code, but an extra field only for the victim's id: an existence oracle
        self.assertEqual(self.twin_case((404, "", dict(body, retryAfterSeconds=7)), (404, "", body)).verdict, "FAIL")

    def test_timing_oracle_needs_dominance(self):
        body = {"error": "This Discord connection is unavailable.", "code": "not_found"}
        slow = self.twin_case((404, "", body), (404, "", dict(body)), v_time=0.090, t_time=0.010)
        self.assertEqual((slow.verdict, slow.note.startswith("timing oracle")), ("FAIL", True))
        jitter = self.twin_case((404, "", body), (404, "", dict(body)), v_time=0.030, t_time=0.010)
        self.assertEqual(jitter.verdict, "PASS")

    def test_cross_tenant_clear_cases_use_the_victims_real_fingerprint(self):
        config = probe.Config({"Q05_BASE_URL": "http://127.0.0.1:1", "Q05_TOKEN_A": "a", "Q05_TOKEN_B": "b",
                               "Q05_WORKSPACE_A": "wsa", "Q05_WORKSPACE_B": "wsb"})
        disc = probe._full_discovery(config)
        disc["B"].sender["B-webhook"]["fingerprint"] = "b" * 64
        cases = {c.cid: c for c in probe.build_sender_cases(disc, config)}
        for cid, scope in (("write.sender.ws_scope_clear.webhook.A->B", "ws_scope"),
                           ("write.sender.idor_clear.webhook.A->B", "idor")):
            c = cases[cid]
            self.assertEqual((c.scope, c.body), (scope, {"reset": True, "fingerprint": "b" * 64, "confirmed": True}))
            self.assertTrue(c.twin_path)
        self.assertNotIn("write.sender.ws_scope_clear.bot.A->B", cases)



class SeqClient:
    """Scripted answers in order (status, text, obj), recording (method, path, body) of every request."""
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
        self.last_provider = self.last_elapsed = None

    def request(self, method, path, token_key, *, body=None, mutation=False):
        self.calls.append((method, path, body))
        return self.answers.pop(0)


def _config():
    return probe.Config({"Q05_BASE_URL": "http://127.0.0.1:1", "Q05_TOKEN_A": "a", "Q05_TOKEN_B": "b",
                         "Q05_WORKSPACE_A": "wsa", "Q05_WORKSPACE_B": "wsb"})


MANIFEST = os.path.join(REPO, "docs", "q05", "case-manifest.tsv")


class ReviewRound2(unittest.TestCase):
    """Each test kills a probe weakening the second delta review found surviving (Q05R2-5), or pins a fix."""

    # ---- the case list itself: deleted, relabelled or faked cases (S01, S02, S04, S05) ----------------- #
    def test_the_committed_manifest_is_the_full_matrix(self):
        with open(MANIFEST) as fh:
            rows = [tuple((line.rstrip("\n").split("\t") + ["", "", ""])[:4]) for line in fh][1:]
        self.assertEqual(rows, [tuple(r) for r in probe.case_manifest(_config())],
                         "the matrix changed: regenerate docs/q05/case-manifest.tsv (--print-manifest) and have it reviewed")

    def test_blast_and_scope_are_pinned_by_case_family(self):
        import re
        for cid, kind, blast, scope in probe.case_manifest(_config()):
            self.assertEqual(blast == "send", cid.startswith("write.send."), cid)
            self.assertEqual(scope == "role", bool(re.match(r"^(read|write)\.sender\.role\.", cid)), cid)
            self.assertEqual(kind, cid.split(".")[0] if cid.split(".")[0] in ("read", "write") else "control", cid)

    def test_gated_reason_matrix(self):
        class F:
            def __init__(self, writes, send, synthetic):
                self.allow_writes, self.allow_send_risk, self.victim_is_synthetic, self.smoke = writes, send, synthetic, False
        cases = probe._full_matrix(_config())
        hosted = F(True, False, False)          # exactly the hosted run: writes on, no send declarations
        for c in cases:
            reason = probe.gated_reason(c, hosted)
            if c.blast == "send":
                self.assertTrue(reason and reason.startswith("gated:send"), c.cid)
            else:
                self.assertIsNone(reason, c.cid)
        for c in cases:
            if c.blast == "send":
                self.assertTrue(probe.gated_reason(c, F(True, True, False)).startswith("refused:send"), c.cid)
                self.assertIsNone(probe.gated_reason(c, F(True, True, True)), c.cid)
            if c.kind == "write":
                self.assertEqual(probe.gated_reason(c, F(False, False, False)), "gated:write (pass --allow-writes)")
        # a gated case sends nothing
        send = next(c for c in cases if c.blast == "send")
        client = SeqClient([])
        probe.run_case(client, send, _disc(), probe.Flags(type("A", (), {"allow_writes": True, "allow_send_risk": False,
                                                                          "victim_is_synthetic": False, "smoke": False})))
        self.assertEqual((send.verdict, client.calls), ("NOT_RUN", []))

    # ---- scoring weakenings (D04, D06, D07, D10, D11, D12, D15) -------------------------------------- #
    def attack(self, scope, answer, cid="read.idor.x", twin=None, markers=()):
        disc = _disc()
        disc["B"].markers = set(markers)
        path = "/api/workspaces/wsa/x"
        case = probe.Case(cid, "GET", "/t", "A->B", "read", "", path, "A", victim_key="B", scope=scope,
                          twin_path="/api/workspaces/wsa/never" if twin else None)
        by_path = {path: answer}
        if twin:
            by_path["/api/workspaces/wsa/never"] = twin
        probe.run_case(PathClient(by_path), case, disc, probe.Flags(_Args()))
        return case

    def test_a_victim_marker_in_a_deny_body_fails(self):                                   # D04
        body = {"error": "Connection unavailable.", "code": "not_found"}
        leaky = (404, json.dumps(dict(body, detail="owner victim-unique-marker-7")), dict(body, detail="owner victim-unique-marker-7"))
        self.assertEqual(self.attack("idor", leaky, markers={"victim-unique-marker-7"}).verdict, "FAIL")
        self.assertEqual(self.attack("idor", (404, json.dumps(body), body), markers={"victim-unique-marker-7"}).verdict, "PASS")

    def test_whole_body_twin_on_a_plain_case(self):                                         # D06
        body = {"error": "Connection unavailable.", "code": "not_found"}
        extra = dict(body, hint="exists")
        self.assertEqual(self.attack("idor", (404, "", extra), twin=(404, "", body)).verdict, "FAIL")
        self.assertEqual(self.attack("idor", (404, "", body), twin=(404, "", dict(body))).verdict, "PASS")

    def test_twin_status_must_match(self):                                                  # D07
        body = {"error": "Connection unavailable.", "code": "not_found"}
        self.assertEqual(self.attack("idor", (404, "", body), twin=(409, "", dict(body))).verdict, "FAIL")

    def control(self, answer, **kw):
        case = probe.Case("control.x.A", "POST", "/t", "control", "control", "", "/p", "A", mutation=True, **kw)
        probe.run_case(PathClient({"/p": answer}), case, _disc(), probe.Flags(_Args()))
        return case.verdict

    def test_a_plain_control_must_succeed(self):                                            # D10
        self.assertEqual(self.control((403, "", {"error": probe.GATE_DENY_BODY})), "FAIL")
        self.assertEqual(self.control((200, "", {"ok": True})), "PASS")

    def test_an_expected_refusal_control_must_match_exactly(self):                          # D11
        kw = {"expect_status": 409, "expect_body": {probe.SENDER_STALE_BODY}}
        self.assertEqual(self.control((200, "", {"ok": True}), **kw), "FAIL")
        self.assertEqual(self.control((409, "", {"error": "something else"}), **kw), "FAIL")
        self.assertEqual(self.control((409, "", {"error": probe.SENDER_STALE_BODY}), **kw), "PASS")

    def test_the_attackers_audit_must_not_hold_victim_data(self):                           # D12
        disc = _disc()
        disc["B"].markers, disc["A"].markers = {"victim-only-marker-9", "shared-marker-1"}, {"shared-marker-1"}
        for text, verdict in (('{"events": [{"subject": "victim-only-marker-9"}]}', "FAIL"),
                              ('{"events": [{"subject": "shared-marker-1"}]}', "PASS")):
            case = probe.Case("control.sender.audit_leak.A", "GET", "/t", "control", "control", "", "/a", "A",
                              scope="audit_leak", victim_key="B")
            probe.run_case(PathClient({"/a": (200, text, json.loads(text))}), case, disc, probe.Flags(_Args()))
            self.assertEqual(case.verdict, verdict, text)

    def test_a_transport_error_is_inconclusive_and_a_case_without_verdict_fails_the_run(self):  # D15
        self.assertEqual(self.attack("idor", (0, "transport_error:URLError", None)).verdict, "INCONCLUSIVE")
        ok = probe.Case("read.idor.ok", "GET", "/t", "A->B", "read", "", "/p", "A")
        ok.verdict = "PASS"
        silent = probe.Case("read.idor.silent", "GET", "/t", "A->B", "read", "", "/p", "A")
        summary = probe.summarize([ok, silent])
        self.assertEqual((summary["unscored"], summary["exit"]), (1, 1))

    def test_a_2xx_on_a_write_attack_fails(self):                                           # D03
        path = "/api/workspaces/wsb/actions"
        case = probe.Case("write.ws_scope.x.A->B", "POST", "/t", "A->B", "write", "state", path, "A",
                          mutation=True, victim_key="B", scope="ws_scope")
        probe.run_case(PathClient({path: (200, "{}", {})}), case, _disc(), probe.Flags(_Args()))
        self.assertEqual(case.verdict, "FAIL")

    def test_the_no_side_effect_snapshot_sees_a_change(self):                               # D13
        config = _config()
        def snap(revision, member_status):
            client = PathClient({
                "/api/workspaces/wsa": (200, "", {"revision": revision, "state": {"phase2": {}}}),
                "/api/workspaces/wsa/members": (200, "", {"members": [{"userId": "u", "role": "editor",
                                                                       "status": member_status}]}),
                "/api/workspaces/wsa/audit": (200, "", {"events": []})})
            return probe.snapshot(client, config, "A")
        (d1, b1), (d2, b2), (d3, b3) = snap(3, "active"), snap(3, "active"), snap(3, "revoked")
        self.assertEqual((d1 == d2, probe.snapshot_diff_groups(b1, b2)), (True, []))
        self.assertNotEqual(d1, d3)
        self.assertEqual(probe.snapshot_diff_groups(b1, b3), ["members"])

    # ---- deferred differential and the case list check (D09, D14) ------------------------------------- #
    def test_a_deferred_owner_differential_is_enforced(self):                               # D09
        for control_verdict, expected in (("PASS", "PASS"), ("FAIL", "INCONCLUSIVE"), (None, "INCONCLUSIVE")):
            attack = probe.Case("write.ws_scope.x.A->B", "POST", "/t", "A->B", "write", "state", "/p", "A",
                                scope="ws_scope", deferred="control.x.B")
            attack.verdict = "PASS"
            cases = [attack]
            if control_verdict:
                control = probe.Case("control.x.B", "POST", "/t", "control", "control", "", "/p", "B")
                control.verdict = control_verdict
                cases.append(control)
            probe.apply_deferred(cases)
            self.assertEqual(attack.verdict, expected, control_verdict)

    def test_a_missing_expected_case_is_a_failure(self):                                    # D14
        config = _config()
        full = probe._full_matrix(config)
        self.assertIsNone(probe.missing_cases_case(config, full))
        mc = probe.missing_cases_case(config, [c for c in full if c.cid != "write.ws_scope.invite.A->B"])
        self.assertEqual((mc.verdict, mc.cid), ("FAIL", "matrix.missing_cases"))
        self.assertIn("write.ws_scope.invite.A->B", mc.note)

    # ---- Q05R2-1: a webhook that never had a saved name is restored with "clear" ---------------------- #
    def sequence(self, saved, restore_answer):
        stale = (409, "", {"error": probe.SENDER_STALE_BODY, "code": "discord_sender_name_required"})
        prof = {"fingerprint": "f" * 64, "savedName": saved, "name": saved or "Rafii"}
        answers = [(200, "", prof),
                   (200, "", {"name": "Q05 renamed A", "savedName": "Q05 renamed A", "saved": True}),
                   stale,
                   (200, "", {"fingerprint": "e" * 64, "name": "Q05 renamed A", "savedName": "Q05 renamed A"}),
                   restore_answer]
        steps = []
        for step in ("save", "stale_replay", "restore"):
            c = probe.Case(f"control.sender.{step}.A", "POST", "/t", "control", "control", "state", "/s", "A",
                           mutation=True, scope="sequence")
            c.sequence_step = step
            steps.append(c)
        client = SeqClient(answers)
        probe.run_sender_sequence(client, steps, probe.Flags(_Args()))
        return steps[2].verdict, client.calls[-1][2]

    def test_an_unnamed_webhook_is_restored_with_clear(self):
        verdict, body = self.sequence(None, (200, "", {"name": "Rafii", "savedName": None, "saved": True, "reset": True}))
        self.assertEqual(body, {"reset": True, "fingerprint": "e" * 64, "confirmed": True})
        self.assertEqual(verdict, "PASS")
        # a restore that leaves an override behind is not a restore
        verdict, _ = self.sequence(None, (200, "", {"name": "Q05 renamed A", "savedName": "Q05 renamed A", "saved": True}))
        self.assertEqual(verdict, "FAIL")
        # a named webhook is restored to its name
        verdict, body = self.sequence("Acme Weekly", (200, "", {"name": "Acme Weekly", "savedName": "Acme Weekly"}))
        self.assertEqual((verdict, body["name"]), ("PASS", "Acme Weekly"))

    # ---- Q05R2-2: one named prerequisite instead of anonymous NOT RUN rows ----------------------------- #
    def test_the_sender_name_build_prerequisite(self):
        config = _config()
        def verdict(names_on=True, webhooks=True, smoke=False, served=True):
            disc = probe._full_discovery(config)
            for d in disc.values():
                d.sender_feature = True if served else False
                if not webhooks:
                    d.webhooks = []
                for prof in d.sender.values():
                    prof["namesOn"] = names_on
            pre = next(c for c in probe.build_sender_cases(disc, config) if c.cid == "prerequisite.sender_names")
            flags = probe.Flags(type("A", (), {"allow_writes": True, "allow_send_risk": False,
                                               "victim_is_synthetic": False, "smoke": smoke}))
            probe.run_case(None, pre, disc, flags)
            return pre.verdict, pre.note
        self.assertEqual(verdict()[0], "PASS")
        for kw in ({"names_on": False}, {"webhooks": False}):
            v, note = verdict(**kw)
            self.assertEqual(v, "FAIL", kw)
            self.assertTrue(note.startswith(probe.PREREQUISITE_NOTE), note)
        self.assertEqual(verdict(names_on=False, smoke=True)[0], "NOT_RUN")
        v, note = verdict(served=False)
        self.assertEqual((v, note.split(":")[0]), ("NOT_RUN", "not-applicable"))

    # ---- Q05R2-6: the receipt table survives a pipe in a cell ------------------------------------------- #
    def test_the_receipt_escapes_pipes(self):
        import tempfile
        c = probe.Case("read.idor.x", "GET", "/t", "A->B", "read", "", "/p", "A", expected=("403", "404"))
        c.verdict, c.observed, c.note = "PASS", "404", "a | b"
        out = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        out.close()
        self.addCleanup(os.unlink, out.name)
        probe.write_markdown(out.name, [c], probe.summarize([c]), probe.Flags(_Args()), _config())
        with open(out.name) as fh:
            row = next(line for line in fh if line.startswith("| read.idor.x |"))
        import re
        self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 11, row)
        self.assertIn("403/404", row)


if __name__ == "__main__":
    unittest.main()

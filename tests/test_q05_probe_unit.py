"""Unit tests for the Q-05 probe that need no database.

Covers: the redirect-safe HTTP client (a 3xx is the observed status and Authorization is never
resent to the Location), the A!=B refusal, and the strict scope-based scoring + ws-scope
differential (via a fake client), including the INCONCLUSIVE classes.
"""
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
        def jwt(sub):
            payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
            return "h." + payload + ".s"
        self.assertEqual(self._run({"Q05_TOKEN_A": jwt("same-user"), "Q05_TOKEN_B": jwt("same-user")}), 2)

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


if __name__ == "__main__":
    unittest.main()

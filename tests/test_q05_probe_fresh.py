"""The real probe against FRESH accounts, with no database.

A loopback fake of the hosted API for two just-signed-up accounts A and B: no Discord identity,
connection, job or review — the state of every run against today's rafii.io (c5fc1fd1) and of
any brand-new throwaway pair. It applies the real app's membership gate (403 "Workspace
unavailable." for a non-member and for an unknown workspace) and the owner-side answers the
probe's differentials rely on (stale revision -> 409, removing the owner -> 409). Members are
listed like the real app: ORDER BY role (text), user_id — so admin/approver/editor sort BEFORE
owner — with a "you" flag. Every DELETE and every member actually removed is recorded.

Covers review items N1 (control.identity_guilds needs a NOT RUN placeholder: a smoke run on fresh
accounts must exit 0, a gate run must fail as undiscovered, and matrix.missing_cases must never
fire), N2 (member_remove must target only the victim owner's own entry: a second member that sorts
before the owner must never be removed by the owner differential) and INFO (stale revision -1;
the smoke banner says inconclusive attacks fail too).

Set Q05_PROBE_PATH to run these tests against another copy of the probe (e.g. an older revision).
"""
import importlib.util
import json
import os
import shutil
import re
import tempfile
import threading
import unittest
from wsgiref.simple_server import WSGIServer, make_server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PATH = os.environ.get("Q05_PROBE_PATH") or os.path.join(REPO, "scripts", "q05_tenant_probe.py")


def load_probe():
    spec = importlib.util.spec_from_file_location("q05_probe_under_test", PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = {"error": "Workspace unavailable.", "code": "workspace_unavailable"}


class FreshHostedFake:
    def __init__(self, extra_members=None, jobs=False):
        self.ws = {"A": "11111111-1111-4111-8111-111111111111", "B": "22222222-2222-4222-8222-222222222222"}
        self.user = {"A": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "B": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
        self.token = {"A": "fresh-token-a-0123456789abcdef", "B": "fresh-token-b-0123456789abcdef"}
        self.revision = {"A": 3, "B": 3}
        self.members = {k: [{"userId": self.user[k], "status": "active", "role": "owner"}] for k in "AB"}
        for key, extra in (extra_members or {}).items():
            self.members[key].extend(extra)
        self.deletes = []          # (owner-of-workspace, caller, target user id)
        self.removed = []          # (workspace key, user id) actually removed by an authorized caller
        self.stale_revisions = []  # expectedRevision values that lost the compare-and-swap (owner side)
        self.lock = threading.Lock()
        self.jobs = jobs           # an approved job in each workspace (the send-blast cases become buildable)
        self.requests = []         # (caller, method, path) of every request the probe sent

    # -- helpers ------------------------------------------------------------ #
    def _who(self, environ):
        auth = environ.get("HTTP_AUTHORIZATION", "")
        for key, tok in self.token.items():
            if auth == "Bearer " + tok:
                return key
        return None

    def _owner_of(self, ws):
        return next((k for k, v in self.ws.items() if v == ws), None)

    def _member_list(self, key, caller):
        rows = sorted(self.members[key], key=lambda m: (m["role"], m["userId"]))  # ORDER BY m.role, m.user_id
        return [{**m, "you": m["userId"] == self.user[caller]} for m in rows]

    def _state(self, key):
        return {"revision": self.revision[key],
                "state": {"workspace": {"id": self.ws[key]},
                          "phase2": {"channels": [], "discordIdentityLinks": [],
                                     "jobs": ([{"id": f"job-{key.lower()}-0001", "approvalDigest": "d" * 64,
                                                "state": "scheduled"}] if self.jobs else []),
                                     "reviews": []},
                          "variants": []}}

    # -- WSGI --------------------------------------------------------------- #
    def __call__(self, environ, start_response):
        with self.lock:
            status, body = self.route(environ)
        raw = json.dumps(body).encode()
        start_response(f"{status} X", [("Content-Type", "application/json"), ("Content-Length", str(len(raw)))])
        return [raw]

    def route(self, environ):
        method = environ["REQUEST_METHOD"]
        parts = [p for p in environ.get("PATH_INFO", "").split("/") if p]
        caller = self._who(environ)
        self.requests.append((caller, method, "/" + "/".join(parts)))
        if caller is None:
            return 401, {"error": "Verified session required."}
        if len(parts) < 3 or parts[:2] != ["api", "workspaces"]:
            return 404, {"error": "Not found."}
        key = self._owner_of(parts[2])
        if key != caller:   # non-member or unknown workspace: the uniform membership gate
            return 403, GATE
        tail = parts[3:]
        if method == "GET":
            if not tail:
                return 200, self._state(key)
            if tail == ["members"]:
                return 200, {"members": self._member_list(key, caller), "membership": {"role": "owner"}}
            if tail == ["audit"]:
                return 200, {"events": []}
            if tail == ["invitations"]:
                return 200, {"invitations": []}
            if tail in (["export"], ["analytics", "summary"], ["memory"]):
                return 200, {}
            if tail == ["channels"]:
                return 200, {"channels": [], "providers": []}
            return 404, {"error": "Not found."}
        length = int(environ.get("CONTENT_LENGTH") or 0)
        payload = json.loads(environ["wsgi.input"].read(length) or b"{}") if length else {}
        if method == "POST" and tail == ["actions"]:
            if payload.get("expectedRevision") != self.revision[key]:
                self.stale_revisions.append(payload.get("expectedRevision"))
                return 409, {"error": "This workspace changed. Reload and try again.", "code": "stale_revision"}
            self.revision[key] += 1
            return 200, self._state(key)
        if method == "DELETE" and len(tail) == 2 and tail[0] == "members":
            self.deletes.append((key, caller, tail[1]))
            target = next((m for m in self.members[key] if m["userId"] == tail[1] and m["status"] == "active"), None)
            if target is None:
                return 404, {"error": "Member unavailable."}
            if target["role"] == "owner":
                return 409, {"error": "The owner cannot be removed."}
            target["status"] = "revoked"   # the real app: manage_members + fresh session -> removed
            self.removed.append((key, tail[1]))
            return 200, {"removed": True}
        return 404, {"error": "Not found."}


class _Quiet(WSGIServer):
    def handle_error(self, *a):
        pass


class FreshAccounts(unittest.TestCase):
    def serve(self, fake):
        httpd = make_server("127.0.0.1", 0, fake, server_class=_Quiet)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_port}"

    def run_probe(self, fake, *flags):
        probe = load_probe()
        base = self.serve(fake)
        out = tempfile.mkdtemp(prefix="q05-fresh-")
        self.addCleanup(shutil.rmtree, out, True)        # no leftover /tmp/q05-fresh-* (review Q05R2-13)
        env = {"Q05_BASE_URL": base, "Q05_TOKEN_A": fake.token["A"], "Q05_TOKEN_B": fake.token["B"],
               "Q05_WORKSPACE_A": fake.ws["A"], "Q05_WORKSPACE_B": fake.ws["B"]}
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            rc = probe.main(["--allow-writes", "--delay", "0", "--budget", "2000",
                             "--out-json", os.path.join(out, "cases.jsonl"),
                             "--out-md", os.path.join(out, "receipt.md"), *flags])
        finally:
            os.environ.clear()
            os.environ.update(saved)
        cases, summary = {}, None
        with open(os.path.join(out, "cases.jsonl")) as fh:
            for line in fh:
                obj = json.loads(line)
                if "summary" in obj:
                    summary = obj["summary"]
                else:
                    cases[obj["case"]] = obj
        with open(os.path.join(out, "receipt.md")) as fh:
            md = fh.read()
        return rc, cases, summary, md

    # ---- review Q05R2-5 (S06): the hosted configuration never sends ------------------------------- #
    def test_hosted_configuration_never_executes_a_job(self):
        """Writes ON, send flags OFF (exactly the hosted run's arguments), with an approved job discoverable in
        each workspace: the probe must not issue a single POST .../jobs/<id>/execute, and the send-blast cases
        must be reported gated."""
        fake = FreshHostedFake(jobs=True)
        rc, cases, summary, _md = self.run_probe(fake, "--smoke")
        executes = [r for r in fake.requests if r[1] == "POST" and r[2].endswith("/execute")]
        self.assertEqual(executes, [], "the hosted configuration sent a job-execute request")
        send = [c for c in cases.values() if c["blast"] == "send"]
        self.assertEqual(len(send), 4, send)
        for c in send:
            self.assertEqual((c["verdict"], c["note"].split(" ")[0]), ("NOT_RUN", "gated:send"), c)

    # ---- N1 ------------------------------------------------------------------ #
    def test_smoke_run_on_fresh_accounts_passes(self):
        rc, cases, summary, md = self.run_probe(FreshHostedFake(), "--smoke")
        self.assertNotIn("matrix.missing_cases", cases, cases.get("matrix.missing_cases"))
        for key in "AB":
            c = cases[f"control.identity_guilds.{key}"]
            self.assertEqual(c["verdict"], "NOT_RUN", c)
            self.assertTrue(c["note"].startswith("undiscovered:"), c)
        self.assertEqual(summary["failed"], 0, [c for c in cases.values() if c["verdict"] == "FAIL"])
        self.assertEqual(summary["inconclusive"], 0, [c for c in cases.values() if c["verdict"] == "INCONCLUSIVE"])
        self.assertEqual(rc, 0, summary)
        # every workspace-scope attack that could run was denied by the gate and confirmed by the owner
        ws = [c for c in cases.values() if c["scope"] == "ws_scope" and c["verdict"] != "NOT_RUN"]
        self.assertGreaterEqual(len(ws), 20)
        self.assertTrue(all(c["verdict"] == "PASS" for c in ws), [c for c in ws if c["verdict"] != "PASS"])
        # INFO: the smoke banner says an inconclusive ATTACK fails the run too
        self.assertIn("an attack as well as a control", md)

    def test_gate_run_on_fresh_accounts_fails_as_undiscovered_not_as_missing(self):
        rc, cases, summary, _md = self.run_probe(FreshHostedFake())
        self.assertNotIn("matrix.missing_cases", cases)
        self.assertEqual(cases["control.identity_guilds.A"]["verdict"], "NOT_RUN")
        self.assertGreater(summary["undiscovered"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(rc, 1, "a gate run on accounts without Discord objects must not pass")

    # ---- N2 ------------------------------------------------------------------ #
    def test_member_remove_never_targets_a_member_that_sorts_before_the_owner(self):
        # B has an admin (and an editor): ORDER BY role puts both BEFORE the owner.
        extra = {"B": [{"userId": "00000000-0000-4000-8000-0000000000ad", "status": "active", "role": "admin"},
                       {"userId": "00000000-0000-4000-8000-0000000000ed", "status": "active", "role": "editor"}],
                 "A": [{"userId": "00000000-0000-4000-8000-00000000a0ad", "status": "active", "role": "admin"}]}
        fake = FreshHostedFake(extra)
        rc, cases, summary, _md = self.run_probe(fake, "--smoke")
        self.assertEqual(fake.removed, [], "the owner differential removed a real member")
        targets = {t for (_ws, _caller, t) in fake.deletes}
        self.assertEqual(targets, {fake.user["A"], fake.user["B"]},
                         "member_remove must target only each victim owner's own entry")
        for arrow in ("A->B", "B->A"):
            self.assertEqual(cases[f"write.ws_scope.member_remove.{arrow}"]["verdict"], "PASS")
        self.assertEqual(rc, 0, summary)

    def test_member_remove_not_run_when_the_owner_entry_is_absent(self):
        probe = load_probe()
        d = probe.Discovery("B", "wsb")
        d.ok, d.members = True, ["someone-else"]       # no "you"+owner entry
        disc = {"A": probe.Discovery("A", "wsa"), "B": d}
        cfg = probe.Config({"Q05_BASE_URL": "http://127.0.0.1:1", "Q05_TOKEN_A": "a" * 30, "Q05_TOKEN_B": "b" * 30,
                            "Q05_WORKSPACE_A": "wsa", "Q05_WORKSPACE_B": "wsb"})
        case = next(c for c in probe.build_matrix(disc, cfg, probe._FullFlags())
                    if c.cid == "write.ws_scope.member_remove.A->B")
        self.assertTrue(case.needs, "without the victim owner's own entry the case must be a NOT RUN placeholder")
        self.assertIsNone(case.path)

    # ---- INFO: stale revision ------------------------------------------------- #
    def test_owner_differential_writes_use_revision_minus_one(self):
        fake = FreshHostedFake()
        self.run_probe(fake, "--smoke")
        self.assertTrue(fake.stale_revisions)
        self.assertEqual(set(fake.stale_revisions), {-1}, fake.stale_revisions)


if __name__ == "__main__":
    unittest.main()

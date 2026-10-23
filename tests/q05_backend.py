"""Local validation backend for the Q-05 cross-tenant isolation probe.

Stands up a throwaway PostgreSQL 16 cluster, loads the RC1 schema (tests/phase2/rls.sql
plus the Discord migrations rls.sql does not include), builds the REAL hosted application
(HostedWorkspaceService + HostedApplication) with stub authentication and a mock Discord
transport, creates two tenants A and B that each own a Discord identity link, a server
installation, an authorized destination and a scheduled Discord job, serves the app over
loopback HTTP, then runs scripts/q05_tenant_probe.py against it.

It adds two proofs the HTTP probe cannot make on its own:
  * a database-level snapshot of each tenant's rows before and after the attack set, so a
    silent write that returns a denial status but still changed a row is caught; and
  * an assertion that the mock Discord transport sent ZERO messages for the whole run, so
    no cross-tenant attempt (and no control) could cause an outbound provider message.

This module is NOT a test (its name does not match test_*.py). It is driven as a CLI by
tests/test_q05_tenant_probe_local.py and tests/test_q05_tenant_probe_mutations.py:

    python tests/q05_backend.py run [--allow-writes] [--allow-send-risk]

It prints one JSON object (the result) on stdout. The checkout under test is chosen by
Q05_TARGET_ROOT (default: this repository): its src/ is the application, and its tests/
(fixtures such as LifecycleWire, tests/phase2/rls.sql) and migrations/ build the schema, so
the source, fixtures and schema always come from the SAME commit. Point it at a detached
export (git archive <sha> src tests migrations) of another line, e.g. the RC2 integration
tip, never at a deployable working tree. Q05_SRC_ROOT overrides only src/, which lets the
mutation tests point it at a patched copy without editing any tracked file.
"""
import argparse
import copy
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from wsgiref.simple_server import WSGIServer, make_server

REPO_ROOT = Path(__file__).resolve().parents[1]
# The checkout under test (application + its own fixtures + its own schema). The probe script
# itself always comes from THIS repository (scripts/q05_tenant_probe.py).
TARGET_ROOT = Path(os.environ.get("Q05_TARGET_ROOT") or REPO_ROOT)
SRC_ROOT = Path(os.environ.get("Q05_SRC_ROOT") or (TARGET_ROOT / "src"))
TESTS_ROOT = TARGET_ROOT / "tests"
sys.path[:0] = [str(SRC_ROOT), str(TESTS_ROOT)]

PG_BIN = Path(os.environ.get("POSTRIFF_PG_BIN") or "/usr/lib/postgresql/16/bin")

DISCORD_MIGRATIONS = (
    "124_discord_rate_limits.sql", "125_discord_service_grants.sql",
    "126_discord_worker_projection.sql", "128_discord_lease_protocol_fence.sql",
    "131_discord_interactions.sql",
)


def pg_available():
    return (PG_BIN / "initdb").exists() and (PG_BIN / "postgres").exists()


def target_sha():
    """The commit the target checkout was exported from (SOURCE_SHA file written next to a
    detached export), or this repository's HEAD when testing in place."""
    marker = TARGET_ROOT / "SOURCE_SHA"
    if marker.exists():
        return marker.read_text().strip()
    try:
        return subprocess.run(["git", "-C", str(TARGET_ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


class Cluster:
    """A disposable loopback PostgreSQL 16 cluster in a temp directory."""

    def __init__(self):
        self.runas = ["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []
        self.tmp = tempfile.mkdtemp(prefix="q05-pg-", dir="/tmp")
        os.chmod(self.tmp, 0o755)
        if self.runas:
            shutil.chown(self.tmp, "postgres", "postgres")
        self.data = Path(self.tmp) / "data"
        self.sock = Path(self.tmp) / "sock"
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.dsn = f"host=127.0.0.1 port={self.port} dbname=postgres" + (" user=postgres" if self.runas else "")
        self._started = False

    def _run(self, *args):
        subprocess.run(self.runas + list(args), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def start(self):
        os.makedirs(self.sock)
        if self.runas:
            shutil.chown(self.sock, "postgres", "postgres")
        self._run(str(PG_BIN / "initdb"), "-D", str(self.data), "-A", "trust",
                  "--no-locale", "-E", "UTF8", *(["-U", "postgres"] if self.runas else []))
        self._run(str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-l", str(Path(self.tmp) / "pg.log"),
                  "-o", f"-k {self.sock} -p {self.port} -h 127.0.0.1", "-w", "-t", "30", "start")
        self._started = True

    def load_schema(self):
        phase2 = TARGET_ROOT / "tests/phase2"
        subprocess.run([str(PG_BIN / "psql"), "-X", self.dsn, "-v", "ON_ERROR_STOP=1", "-q",
                        "-f", str(phase2 / "rls.sql")], check=True, cwd=str(phase2),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        for mig in DISCORD_MIGRATIONS:
            subprocess.run([str(PG_BIN / "psql"), "-X", self.dsn, "-v", "ON_ERROR_STOP=1", "-q",
                            "-f", str(TARGET_ROOT / "migrations/postriff" / mig)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def stop(self):
        if self._started:
            subprocess.run(self.runas + [str(PG_BIN / "pg_ctl"), "-D", str(self.data),
                           "-m", "immediate", "-w", "-t", "20", "stop"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(self.tmp, ignore_errors=True)


# tenant-scoped tables whose per-workspace row counts are part of the DB snapshot.
WORKSPACE_TABLES = (
    "pr_encrypted_credentials", "pr_channel_capabilities", "pr_oauth_transactions",
    "pr_discord_interaction_links", "pr_memberships", "pr_invitations", "pr_audit_events",
)


def db_snapshot(connect, workspace):
    """Row counts per tenant-scoped table + the workspace revision + a projection of the
    state that a cross-tenant write would disturb. Used for the independent no-side-effect
    proof. Returns a plain dict (no secrets)."""
    snap = {"counts": {}}
    with connect() as db:
        rev = db.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (workspace,)).fetchone()
        snap["revision"] = rev[0] if rev else None
        state = rev[1] if rev and isinstance(rev[1], dict) else (json.loads(rev[1]) if rev else {})
        phase2 = (state or {}).get("phase2") or {}
        snap["projection"] = {
            "channels": sorted([(c.get("id"), bool(c.get("revoked")), c.get("discordAuthorizationGeneration"),
                                 len(c.get("discordDestinations", []) or []))
                                for c in phase2.get("channels", []) or [] if isinstance(c, dict)]),
            "identities": sorted([(x.get("id"), x.get("status"), x.get("authorizationGeneration"))
                                  for x in phase2.get("discordIdentityLinks", []) or [] if isinstance(x, dict)]),
            "jobs": sorted([(j.get("id"), j.get("state"), bool(j.get("cancelRequested")))
                            for j in phase2.get("jobs", []) or [] if isinstance(j, dict)]),
            "reviews": len(phase2.get("reviews", []) or []),
            "variants": len((state or {}).get("variants", []) or []),
        }
        snap["updated_at"] = {}
        snap["revoked"] = {}
        for table in WORKSPACE_TABLES:
            try:
                n = db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (workspace,)).fetchone()[0]
            except Exception:
                n = None
            snap["counts"][table] = n
            # updated_at / revoked_at are what a silent write (one that returns a denial status
            # but still touches a row) would move without changing row counts or the state JSON.
            try:
                snap["updated_at"][table] = float(db.execute(
                    f"SELECT extract(epoch from max(updated_at)) FROM public.{table} WHERE workspace_id=%s",
                    (workspace,)).fetchone()[0] or 0)
            except Exception:
                db.rollback()
            try:
                snap["revoked"][table] = db.execute(
                    f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s AND revoked_at IS NOT NULL",
                    (workspace,)).fetchone()[0]
            except Exception:
                db.rollback()
    return snap


def side_effect_report(before, after):
    """What changed between two DB snapshots. A legitimate owner `refresh` control bumps
    the workspace revision by one and rewrites identical state, so a revision delta of at
    most +1 with an unchanged projection and unchanged row counts is NOT a side effect."""
    issues = []
    if before["projection"] != after["projection"]:
        for group in ("channels", "identities", "jobs", "reviews", "variants"):
            if before["projection"].get(group) != after["projection"].get(group):
                issues.append("projection." + group)
    for table in WORKSPACE_TABLES:
        if before["counts"].get(table) != after["counts"].get(table):
            issues.append("rowcount." + table)
        if before.get("updated_at", {}).get(table) != after.get("updated_at", {}).get(table):
            issues.append("updated_at." + table)
        if before.get("revoked", {}).get(table) != after.get("revoked", {}).get(table):
            issues.append("revoked." + table)
    rev_delta = (after["revision"] or 0) - (before["revision"] or 0)
    if rev_delta < 0 or rev_delta > 1:
        issues.append(f"revision_delta={rev_delta}")
    return {"ok": not issues, "issues": issues, "revisionDelta": rev_delta}


class Backend:
    def __init__(self, cluster):
        self.cluster = cluster
        self.tenants = {}
        self.wire = None
        self.httpd = None
        self.thread = None
        self.base_url = None
        self.now = None

    def connect(self):
        import psycopg
        return psycopg.connect(self.cluster.dsn, client_encoding="utf8")

    def build(self):
        import psycopg  # noqa: F401 (ensure available early)
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.hosted import HostedWorkspaceService
        from postriff_phase2.hosted_worker import PostgresWorker
        from postriff_phase2.hosted_app import HostedApplication
        from postriff_phase2.oauth import CredentialVault
        from postriff_phase2.social_connectors import DiscordProvider
        from postriff_phase2.discord import authorization as dauth
        from test_discord_oauth_lifecycle import LifecycleWire
        from test_discord_publish_authorization import APP, GUILD, FIRST, fixture as pub_fixture

        with self.connect() as db:
            self.now = int(db.execute("SELECT extract(epoch from now())").fetchone()[0]) // 60 * 60
        now = self.now
        tokens = {}

        def verify(token):
            if token in tokens:
                return tokens[token]
            raise AlphaError("Verified session required.", 401)
        verify.session_id = lambda token, principal: "sess-" + principal.replace("-", "")[:16]
        verify.auth_time = lambda token, principal: now
        verify.aal = lambda token, principal: None

        self.wire = LifecycleWire()
        provider = DiscordProvider(APP, "synthetic-secret", "synthetic-bot",
                                   "https://rafii.example.invalid", transport=self.wire,
                                   production_reviewed=True)
        provider.authorization_v2_enabled = provider.connections_v2_enabled = True

        connect = self.connect
        service = HostedWorkspaceService(connect, verify, clock=lambda: now,
            vault=CredentialVault(CredentialVault.generate_key()),
            providers={"discord": provider}, public_base_url="https://rafii.example.invalid")
        worker = PostgresWorker(connect, social=None, clock=lambda: now + 301)
        oauth = service.oauth
        self.service = service

        def make_tenant(name):
            user = str(uuid4())
            token = "q05-token-" + name + "-" + uuid4().hex
            tokens[token] = user
            with self.connect() as db:
                db.execute("INSERT INTO auth.users(id) VALUES(%s)", (user,))
            ws = service.bootstrap(token, "studio")["workspaceId"]

            def start(purpose, **inputs):
                v = oauth.start(ws, token, "discord", "identity" if purpose == "identity" else "publish",
                                {"discordPurpose": purpose, **inputs})
                return parse_qs(urlsplit(v["authorizeUrl"]).query)["state"][0]

            st = start("identity", discoverGuilds=True)
            identity = oauth.complete(ws, token, "discord", st, "identity-code")["connectionId"]
            st = start("installation", identityConnectionId=identity, guildId=GUILD)
            conn = oauth.complete(ws, token, "discord", st, "install-" + GUILD)["connectionId"]
            oauth.choose_destination(ws, token, conn, FIRST)

            # a scheduled Discord job (p2_review + p2_approve), through the app's own code
            _, _, _, variant = pub_fixture()
            with self.connect() as db:
                state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (ws,)).fetchone()[0]
                state["variants"].append(copy.deepcopy(variant))
                db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s",
                           (json.dumps(state), ws))
            snap = service.repository.get(ws, token)
            destination = dauth.destination_id(ws, conn, GUILD, FIRST)
            snap = service.repository.mutate(ws, token, snap["revision"], "p2_review",
                {"variantId": "synthetic-draft", "channelId": conn, "destinationId": destination,
                 "localTime": datetime.fromtimestamp(now + 300, timezone.utc).strftime("%Y-%m-%dT%H:%M"),
                 "timeZone": "UTC", "acknowledgedWarnings": []})
            review = snap["state"]["phase2"]["reviews"][-1]
            service.repository.mutate(ws, token, snap["revision"], "p2_approve",
                {"reviewId": review["id"], "digest": review["digest"], "confirmed": True})

            # an un-consumed OAuth transaction, so the probe can test state-binding across tenants
            victim_state = start("identity", discoverGuilds=True)

            return {"user": user, "token": token, "ws": ws, "identity": identity,
                    "conn": conn, "oauth_state": victim_state}

        self.tenants["A"] = make_tenant("a")
        self.tenants["B"] = make_tenant("b")

        app = HostedApplication(service=service, worker=worker,
                                public_auth={"provider": "supabase"}, cron_secret="q05-cron-secret-abcdefgh")
        self.httpd = make_server("127.0.0.1", 0, app, server_class=_QuietServer)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def message_sends(self):
        """How many outbound Discord message sends the mock transport saw (must be 0)."""
        calls = list(getattr(self.wire, "calls", []))
        n = 0
        for entry in calls:
            method, path = entry[0], entry[1]
            if method == "POST" and (path.endswith("/messages") or path.startswith("/webhooks/")):
                n += 1
        return n

    def probe_env(self, extra=None):
        env = dict(os.environ)
        env["Q05_BASE_URL"] = self.base_url
        env["Q05_TOKEN_A"] = self.tenants["A"]["token"]
        env["Q05_TOKEN_B"] = self.tenants["B"]["token"]
        env["Q05_WORKSPACE_A"] = self.tenants["A"]["ws"]
        env["Q05_WORKSPACE_B"] = self.tenants["B"]["ws"]
        env["Q05_VICTIM_A_OAUTH_STATE"] = self.tenants["A"]["oauth_state"]
        env["Q05_VICTIM_B_OAUTH_STATE"] = self.tenants["B"]["oauth_state"]
        if extra:
            env.update(extra)
        return env

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()


class _QuietServer(WSGIServer):
    def handle_error(self, request, client_address):
        pass  # keep probe transport noise out of test output


def run_probe(backend, args):
    probe = str(REPO_ROOT / "scripts/q05_tenant_probe.py")
    out_json = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    out_json.close()
    cmd = [sys.executable, "-I", probe, "--budget", "600", "--delay", "0",
           "--out-json", out_json.name]
    if args.allow_writes:
        cmd.append("--allow-writes")
    if args.allow_send_risk:
        cmd.append("--allow-send-risk")
    if args.victim_is_synthetic:
        cmd.append("--victim-is-synthetic")
    proc = subprocess.run(cmd, env=backend.probe_env(), capture_output=True, text=True)
    records, summary = [], None
    with open(out_json.name) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "summary" in obj:
                summary = obj["summary"]
            else:
                records.append(obj)
    os.unlink(out_json.name)
    return proc.returncode, records, summary, proc.stderr


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run"])
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--allow-send-risk", action="store_true")
    parser.add_argument("--victim-is-synthetic", action="store_true")
    args = parser.parse_args(argv)

    if not pg_available():
        print(json.dumps({"status": "skipped", "reason": "PostgreSQL 16 binaries not found at " + str(PG_BIN)}))
        return 0

    cluster = Cluster()
    result = {"status": "error"}
    try:
        cluster.start()
        cluster.load_schema()
        backend = Backend(cluster)
        backend.build()
        try:
            before = {k: db_snapshot(backend.connect, backend.tenants[k]["ws"]) for k in ("A", "B")}
            sends_before = backend.message_sends()
            rc, records, summary, stderr = run_probe(backend, args)
            after = {k: db_snapshot(backend.connect, backend.tenants[k]["ws"]) for k in ("A", "B")}
            sends_after = backend.message_sends()
            db_effects = {k: side_effect_report(before[k], after[k]) for k in ("A", "B")}
            result = {
                "status": "ran",
                "targetRoot": str(TARGET_ROOT),
                "targetSha": target_sha(),
                "srcRoot": str(SRC_ROOT),
                "probeExit": rc,
                "summary": summary,
                "cases": records,
                "dbSideEffect": db_effects,
                "messageSendsDuringRun": sends_after - sends_before,
                "probeStderr": stderr[-2000:],
            }
        finally:
            backend.stop()
    finally:
        cluster.stop()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
import secrets
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


def sender_feature():
    """True when the checkout under test has the customer Discord sender-name feature (RC2)."""
    return (SRC_ROOT / "postriff_phase2" / "discord" / "sender_names.py").exists()


# Sender-name fixtures (used only when sender_feature()): distinct webhook ids per tenant, distinct,
# distinctive customer sender names, and the role principals added to each workspace.
WEBHOOK_IDS = {"A": "66110000001", "B": "66110000002"}
SENDER_NAMES = {"A": "Q05 Alpha Webhook Brand", "B": "Q05 Beta Webhook Brand"}
ROLE_PRINCIPALS = (   # (key, role, can_manage_connections)
    ("viewer", "viewer", False),
    ("editor", "editor", False),
    ("connmgr", "editor", True),    # holds connection-management, but did not authorize the connection
    ("admin", "admin", False),      # likewise not the authorizer
    ("removed", "admin", False),    # removed through the app before the probe runs
)


def rate_policy(now):
    """The checkout's own Discord admission policy builder (scripts/discord_rate_policy.py), as the
    RC2 lane fixtures use it: a one-day policy at the production app capacity."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("q05_discord_rate_policy", TARGET_ROOT / "scripts/discord_rate_policy.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return json.dumps(tool.build(now, days=1, revision="q05-local", app_capacity=25))


class ProviderAttribution:
    """WSGI middleware (local harness only). Adds X-Q05-Provider-Calls / X-Q05-Provider-Writes to every
    response: how many provider requests (and non-GET ones) the mock Discord saw while THIS HTTP
    request was served. wsgiref serves one request at a time and the app answers only after its work,
    so the window is exactly one request. A request carrying X-Q05-Phase (attack-start / attack-end)
    is answered here with 204 after snapshotting the database and the mock, so the harness brackets
    exactly the probe's attack phase."""

    def __init__(self, app, backend):
        self.app, self.backend = app, backend

    def __call__(self, environ, start_response):
        phase = environ.get("HTTP_X_Q05_PHASE")
        if phase in ("attack-start", "attack-end"):
            self.backend.mark_phase(phase)
            start_response("204 No Content", [])
            return [b""]
        wire = self.backend.wire
        calls, writes = wire.provider_calls(), wire.provider_writes()

        def sr(status, headers, exc_info=None):
            headers = list(headers) + [("X-Q05-Provider-Calls", str(wire.provider_calls() - calls)),
                                       ("X-Q05-Provider-Writes", str(wire.provider_writes() - writes))]
            return start_response(status, headers, exc_info) if exc_info else start_response(status, headers)
        return self.app(environ, sr)


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
            # incl. the customer sender-name fields: a cross-tenant rename (or a pending edit claim) is a
            # side effect even when nothing else on the connection moves.
            "channels": sorted([(c.get("id"), bool(c.get("revoked")), c.get("discordAuthorizationGeneration"),
                                 len(c.get("discordDestinations", []) or []), c.get("discordSenderName"),
                                 c.get("discordSenderRevision"), bool(c.get("discordSenderEdit")))
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


def side_effect_report(before, after, max_revision_delta=1):
    """What changed between two DB snapshots. Over the WHOLE run a legitimate owner `refresh`
    control bumps the workspace revision by one and rewrites identical state, so a revision delta
    of at most +1 with an unchanged projection and unchanged row counts is NOT a side effect.
    Bracketing exactly the attack phase (probe phase markers), nothing at all may change:
    max_revision_delta=0."""
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
    if rev_delta < 0 or rev_delta > max_revision_delta:
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
        self.phase = {}       # attack-start / attack-end snapshots taken on the probe's markers
        self.sender = False

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
        from test_discord_publish_authorization import APP, BOT, GUILD, FIRST, SECOND, USER, fixture as pub_fixture
        from q05_sender_wire import make_wire

        with self.connect() as db:
            self.now = int(db.execute("SELECT extract(epoch from now())").fetchone()[0]) // 60 * 60
        now = self.now
        tokens = {}
        self.tokens = tokens

        def verify(token):
            if token in tokens:
                return tokens[token]
            raise AlphaError("Verified session required.", 401)
        verify.session_id = lambda token, principal: "sess-" + principal.replace("-", "")[:16]
        verify.auth_time = lambda token, principal: now
        verify.aal = lambda token, principal: None

        # The customer sender-name feature (RC2): webhook connections, sender names, role members.
        self.sender = sender_feature()
        self.wire = make_wire(LifecycleWire, APP, BOT, GUILD, USER if self.sender else None)(nickname_bits=self.sender)
        provider = DiscordProvider(APP, "synthetic-secret", "synthetic-bot",
                                   "https://rafii.example.invalid", transport=self.wire,
                                   production_reviewed=True)
        provider.authorization_v2_enabled = provider.connections_v2_enabled = True
        if self.sender:
            # Contract v2 reads two server-side switches from the environment at request time, each on ONLY for
            # the exact string "true" (unset is off in every environment): the master switch and the bot-nickname
            # capability. Set explicitly (never inherited), so the nickname-authority rules are exercised.
            os.environ["POSTRIFF_DISCORD_SENDER_NAMES_ENABLED"] = "true"
            os.environ["POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED"] = "true"
            # The production wiring for this line: incoming webhooks on and the shared, durable admission
            # coordinator (P4). As in production (POSTRIFF_DISCORD_RATE_POLICY), the service itself attaches
            # SharedPostgresBudget over its own connection factory with this policy; the checkout's own builder.
            provider.webhook_v1_enabled = True
            provider.rate_v1_enabled = True
            provider.rate_policy_raw = rate_policy(now)
        self.provider = provider
        self.constants = {"APP": APP, "BOT": BOT, "GUILD": GUILD, "FIRST": FIRST, "SECOND": SECOND, "USER": USER}
        self.dauth, self.sender_names = dauth, dict(SENDER_NAMES)

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
            self.variant_template = copy.deepcopy(variant)
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

            tenant = {"user": user, "token": token, "ws": ws, "identity": identity,
                      "conn": conn, "oauth_state": victim_state}
            if self.sender:
                key = name.upper()
                # an incoming-webhook connection with its OWN webhook id/secret and channel, its destination
                # authorized, and a distinct customer sender name — all through the app's own code paths
                hook_id, channel = WEBHOOK_IDS[key], (FIRST if key == "A" else SECOND)
                self.wire.add_hook("webhook-" + name, hook_id, secrets.token_urlsafe(32), channel)
                st = start("webhook", channelId=channel)
                # (the v2 webhook context also binds the authorization issuer, as Discord's callback carries it)
                webhook = oauth.complete(ws, token, "discord", st, "webhook-" + name, iss="https://discord.com")["connectionId"]
                oauth.choose_destination(ws, token, webhook, channel)
                dc = oauth.discord_connections
                profile = dc.sender_profile(ws, token, webhook)
                dc.set_sender_name(ws, token, webhook, {"name": SENDER_NAMES[key],
                                                        "fingerprint": profile["fingerprint"], "confirmed": True})
                tenant.update(webhook=webhook, hook_id=hook_id, hook_channel=channel)
                # role principals in this workspace: viewer, editor (no flag), editor WITH the
                # connection-management flag, admin (both non-authorizers), and a member removed via the app
                roles = {}
                for role_key, role, manage in ROLE_PRINCIPALS:
                    uid, rtok = str(uuid4()), f"q05-token-{name}-{role_key}-" + uuid4().hex
                    tokens[rtok] = uid
                    with self.connect() as db:
                        db.execute("INSERT INTO auth.users(id) VALUES(%s)", (uid,))
                        db.execute("INSERT INTO public.pr_profiles(user_id,display_name) VALUES(%s,%s)",
                                   (uid, "Q05 " + role_key))
                        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,"
                                   "can_manage_connections) VALUES(%s,%s,%s,'active',%s)", (ws, uid, role, manage))
                    roles[role_key] = {"user": uid, "token": rtok}
                service.remove_member(ws, token, roles["removed"]["user"])   # -> status 'revoked'
                tenant["roles"] = roles
            return tenant

        self.tenants["A"] = make_tenant("a")
        self.tenants["B"] = make_tenant("b")

        app = HostedApplication(service=service, worker=worker,
                                public_auth={"provider": "supabase"}, cron_secret=secrets.token_urlsafe(24))
        # Per-request provider attribution + attack-phase markers (local harness only).
        app = ProviderAttribution(app, self)
        self.httpd = make_server("127.0.0.1", 0, app, server_class=_QuietServer)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def message_sends(self):
        """How many outbound Discord message sends (bot channel messages or webhook executes) the mock
        transport saw. Counted from the wire's own log of EVERY provider request."""
        with self.wire.q05_lock:
            return sum(1 for method, path in self.wire.q05_calls
                       if method == "POST" and (path.endswith("/messages") or path.startswith("/webhooks/")))

    def mark_phase(self, name):
        """Called by ProviderAttribution when the probe marks the start/end of its attack phase."""
        self.phase[name] = {"db": {k: db_snapshot(self.connect, self.tenants[k]["ws"]) for k in ("A", "B")},
                            "wire": self.wire.state()}

    def probe_env(self, extra=None):
        env = dict(os.environ)
        env["Q05_BASE_URL"] = self.base_url
        env["Q05_TOKEN_A"] = self.tenants["A"]["token"]
        env["Q05_TOKEN_B"] = self.tenants["B"]["token"]
        env["Q05_WORKSPACE_A"] = self.tenants["A"]["ws"]
        env["Q05_WORKSPACE_B"] = self.tenants["B"]["ws"]
        env["Q05_VICTIM_A_OAUTH_STATE"] = self.tenants["A"]["oauth_state"]
        env["Q05_VICTIM_B_OAUTH_STATE"] = self.tenants["B"]["oauth_state"]
        env["Q05_PHASE_MARKERS"] = "1"      # the probe marks its attack phase; the harness brackets it exactly
        for key in ("A", "B"):
            for role_key, info in (self.tenants[key].get("roles") or {}).items():
                env[f"Q05_TOKEN_{key}_{role_key.upper()}"] = info["token"]
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
    # mutation tests of the send-level guards need only the scenarios (they run after the probe otherwise)
    parser.add_argument("--skip-probe", action="store_true")
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
            if backend.sender:
                # The setup saved each webhook's sender name through the app a moment ago; the probe models a session
                # that starts later (the fixed 10-minute sender-name throttle windows have passed).
                with backend.connect() as db:
                    db.execute("DELETE FROM public.pr_auth_throttle")
            if args.skip_probe:
                rc, records, summary, stderr = None, [], None, ""
            else:
                rc, records, summary, stderr = run_probe(backend, args)
            after = {k: db_snapshot(backend.connect, backend.tenants[k]["ws"]) for k in ("A", "B")}
            sends_after = backend.message_sends()
            # send-level and same-server scenarios (sender-name builds), after the probe's own accounting
            scenarios = None
            if backend.sender and args.allow_writes:
                from q05_sender_scenarios import run_scenarios
                scenarios = run_scenarios(backend)
            whole_run = {k: side_effect_report(before[k], after[k]) for k in ("A", "B")}
            start, end = backend.phase.get("attack-start"), backend.phase.get("attack-end")
            attack = None
            if start and end:
                # EXACTLY the attack phase: nothing in either tenant may change (revision delta 0), and the
                # mock Discord must see no request at all — no read, no write, no send, no nickname change.
                attack = {
                    "dbSideEffect": {k: side_effect_report(start["db"][k], end["db"][k], max_revision_delta=0)
                                     for k in ("A", "B")},
                    "providerCalls": end["wire"]["calls"] - start["wire"]["calls"],
                    "providerWrites": end["wire"]["writes"] - start["wire"]["writes"],
                    "messageSends": end["wire"]["sent"] - start["wire"]["sent"],
                    "nicknameChanged": end["wire"]["nick"] != start["wire"]["nick"],
                }
            result = {
                "status": "ran",
                "targetRoot": str(TARGET_ROOT),
                "targetSha": target_sha(),
                "srcRoot": str(SRC_ROOT),
                "senderNames": backend.sender,
                "probeExit": rc,
                "summary": summary,
                "cases": records,
                # the attack-phase bracket when the probe marked its phases; else the whole run (+1 tolerated)
                "dbSideEffect": attack["dbSideEffect"] if attack else whole_run,
                "dbWholeRun": whole_run,
                "attackPhase": attack,
                "messageSendsDuringRun": sends_after - sends_before,
                "scenarios": scenarios,
                "scenariosOk": None if scenarios is None else all(v["ok"] for v in scenarios.values()),
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

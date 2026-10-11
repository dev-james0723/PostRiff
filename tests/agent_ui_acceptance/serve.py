"""Lane G acceptance harness server: the real hosted app on a disposable loopback PostgreSQL, for cloud CI only.

It runs `scripts/postriff_dev_hosted.py` unchanged (real HostedWorkspaceService, permissions, ledger, Agent Runtime, the real
UI routes) and adds, without editing any shared file:

* migration 102 (and 103 when A adds it) and 058 applied inline after tests/phase2/rls.sql, the D-A26 rule for UI tables;
* an expiring-login switch: a principal listed in `agent_ui_acceptance_expired` gets 401 from the identity verifier
  (NC05), exactly like a lapsed Supabase session;
* the fixture provider (fake_provider.py) as RAFII_AGENT_BASE_URL: lane B's real presenter/stream/metering code talks to a
  loopback OpenAI-compatible endpoint that streams deterministic valid source, counts provider requests and injects armed
  faults (malformed, truncated, unpriced, slow, failing). Nothing past the network boundary is replaced;
* the METERED Manager path: the runtime is built as in production (no RAFII_AGENT_HARNESS model factory), so a turn reserves,
  records usage and settles on the real ledger (`usage.billing == "metered"`), which is what lane D's eligibility and lane B's
  admission require. The fixture provider answers the Manager's and specialists' requests with the existing QA script
  (harness.manager_step), so turns stay deterministic. Budgets use the launch policy (POSTRIFF_BUDGET_POLICY), exactly as
  production approves them. `--scripted-manager` restores the unbilled ScriptedModel Manager (then no turn is eligible).
  Labelled fixture: never evidence of live model quality.

Refuses to run on Vercel, outside CI unless AGENT_UI_ACCEPTANCE_LOCAL=1, or with what looks like a real provider key.

    python tests/agent_ui_acceptance/serve.py --port 4538 --pg-port 55538 --provider-port 4540 --state-file $EVIDENCE/stack.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_KEY = "fixture-provider-placeholder-not-a-key"   # loopback only; RAFII_AGENT_BASE_URL is the fixture provider
FLAG_ENV = {"RAFII_GENUI_ENABLED": "1", "RAFII_GENUI_ACTIONS_ENABLED": "1", "RAFII_GENUI_EDITS_ENABLED": "1",
            "RAFII_GENUI_FOUNDER_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1", "POSTRIFF_RESEARCH": "0", "OPENUI_TELEMETRY_DISABLED": "1",
            "RAFII_AGENT_BASE_URL": "http://127.0.0.1:9/v1", "OPENAI_AGENTS_DISABLE_TRACING": "1", "RAFII_AGENT_OPENAI_TRACING": "0",
            "RAFII_SPECIALISTS_ENABLED": "1", "POSTRIFF_BUDGET_POLICY": "launch-2026-09-24", "RAFII_AGENT_PROVIDER": "openai"}


def refuse(reason: str) -> None:
    print(json.dumps({"status": "REFUSED", "reason": reason}), flush=True)
    raise SystemExit(64)


def guard_environment() -> None:
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        refuse("the acceptance harness never runs on a deployment")
    if os.environ.get("CI") != "true" and os.environ.get("AGENT_UI_ACCEPTANCE_LOCAL") != "1":
        refuse("cloud CI only (this Mac is a control plane); set CI=true on a CI runner")
    for name in ("OPENAI_API_KEY", "AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN"):
        if os.environ.pop(name, None):
            print(json.dumps({"note": f"{name} removed from the harness environment"}), flush=True)
    for name, value in FLAG_ENV.items():
        os.environ.setdefault(name, value)
    os.environ["RAFII_AGENT_BASE_URL"] = FLAG_ENV["RAFII_AGENT_BASE_URL"]


def load_dev_harness():
    spec = importlib.util.spec_from_file_location("postriff_dev_hosted", ROOT / "scripts/postriff_dev_hosted.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["postriff_dev_hosted"] = module
    spec.loader.exec_module(module)
    return module


def ui_migrations(founder: bool) -> list[Path]:
    base = ROOT / "migrations/postriff"
    files = [] if founder else [base / "058_founder_ai_usage.sql"]   # the founder fixture applies 054+ itself
    files.append(base / "102_agent_ui_artifacts.sql")
    files += sorted(p for p in base.glob("103_*.sql"))
    return [p for p in files if p.exists()]


FIXTURE_SQL = """
CREATE TABLE IF NOT EXISTS public.agent_ui_acceptance_expired(principal uuid primary key);
"""


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4538)
    parser.add_argument("--pg-port", type=int, default=55538)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--founder-fixture", action="store_true")
    parser.add_argument("--provider-port", type=int, default=4540)
    parser.add_argument("--provider-delay", type=float, default=0.35, help="seconds between fixture deltas (progressive rendering)")
    parser.add_argument("--scripted-manager", action="store_true", help="unbilled RAFII_AGENT_HARNESS Manager (no turn is UI-eligible)")
    args, rest = parser.parse_known_args(argv)
    guard_environment()
    if args.scripted_manager:
        os.environ["RAFII_AGENT_HARNESS"] = "1"
    else:
        os.environ.pop("RAFII_AGENT_HARNESS", None)
        os.environ["OPENAI_API_KEY"] = FIXTURE_KEY
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tests"))
    from agent_ui_acceptance import fake_provider   # noqa: E402
    _srv, provider_url, _state = fake_provider.start(args.provider_port, args.provider_delay)
    os.environ["RAFII_AGENT_BASE_URL"] = provider_url
    os.environ["AGENT_UI_ACCEPTANCE_STATE"] = str(args.state_file.resolve())
    dev = load_dev_harness()
    original_start = dev.start_postgres

    def start_postgres(port=args.pg_port):
        dsn, data = original_start(port)
        for path in ui_migrations(args.founder_fixture):
            subprocess.run([str(dev.PG / "psql"), dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(dev.PG / "psql"), dsn, "-v", "ON_ERROR_STOP=1", "-q", "-c", FIXTURE_SQL], check=True, stdout=subprocess.DEVNULL)
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        args.state_file.write_text(json.dumps({"dsn": dsn, "pgPort": port, "apiPort": args.port, "founder": args.founder_fixture, "providerUrl": provider_url,
                                               "migrations": [p.name for p in ui_migrations(args.founder_fixture)], "startedAt": time.time()}))
        return dsn, data

    dev.start_postgres = start_postgres
    install_expiring_verifier(dev)
    install_offline_weather()
    install_asset_skew(args.state_file.resolve().parent / "skew-assets.flag")
    sys.argv = ["postriff_dev_hosted.py", "--port", str(args.port), "--pg-port", str(args.pg_port)] + (["--founder-fixture"] if args.founder_fixture else []) + rest
    dev.main()


def install_asset_skew(flag: Path) -> None:
    """Deploy-skew fault injection: while `flag` exists, lane B reads a copy of the generated assets whose library hashes
    differ from what the deployed Node validator builds (an old Python bundle beside a new web build). The validator must
    answer library_unsupported and B must stop there: no repair, no second reservation."""
    import shutil
    import tempfile
    from postriff_phase2.agent_runtime_v2 import ui_presenter, ui_stream
    source = ROOT / "src/postriff_phase2/agent_runtime_v2/generated"
    if not (source / "openui-assets.json").exists():
        return
    skewed = Path(tempfile.mkdtemp(prefix="g-skew-assets-"))
    shutil.copytree(source, skewed, dirs_exist_ok=True)
    manifest = json.loads((skewed / "openui-assets.json").read_text(encoding="utf-8"))
    for library in (manifest.get("libraries") or {}).values():
        if isinstance(library, dict):
            library["libraryHash"] = "e" * 64
    (skewed / "openui-assets.json").write_text(json.dumps(manifest), encoding="utf-8")
    original = ui_stream._assets

    def assets(runtime):
        return ui_presenter.load_assets(str(skewed)) if flag.exists() else original(runtime)
    ui_stream._assets = assets


def install_offline_weather() -> None:
    """The weather tool's Open-Meteo calls use the QA stand-in (nothing leaves the runner)."""
    from postriff_phase2.agent_runtime_v2 import harness, live_tools
    original = live_tools.Weather.__init__

    def init(self, transport=None, *rest, **kw):
        original(self, transport or harness.weather_transport, *rest, **kw)
    live_tools.Weather.__init__ = init


def install_expiring_verifier(dev) -> None:
    base = dev.DevVerifier

    class ExpiringVerifier(base):
        """The dev identity, plus a lapse switch: a listed principal is no longer a verified session (401)."""

        def __call__(self, token):
            principal = super().__call__(token)
            with self.connection() as db:
                row = db.execute("SELECT 1 FROM public.agent_ui_acceptance_expired WHERE principal=%s", (principal,)).fetchone()
            if row:
                from postriff_alpha.domain import AlphaError
                raise AlphaError("Your session has expired. Sign in again.", 401, code="session_expired")
            return principal

    dev.DevVerifier = ExpiringVerifier


if __name__ == "__main__":
    main()

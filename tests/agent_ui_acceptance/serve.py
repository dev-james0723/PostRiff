"""Lane G acceptance harness server: the real hosted app on a disposable loopback PostgreSQL, for cloud CI only.

It runs `scripts/postriff_dev_hosted.py` unchanged (real HostedWorkspaceService, permissions, ledger, Agent Runtime with the
RAFII_AGENT_HARNESS scripted Manager, the real UI routes) and adds, without editing any shared file:

* migration 102 (and 103 when A adds it) and 058 applied inline after tests/phase2/rls.sql, the D-A26 rule for UI tables;
* an expiring-login switch: a principal listed in `agent_ui_acceptance_expired` gets 401 from the identity verifier
  (NC05), exactly like a lapsed Supabase session;
* provider fault injection at the presenter's output boundary (`ui_presenter.stream_presentation`): a row in
  `agent_ui_acceptance_faults` makes the next attempt for that workspace malformed, truncated, unpriced (no usage), slow or
  failing. ui_stream's own repair/metering/settlement logic is what is under test, so nothing past that boundary is replaced;
* a black-holed provider base URL so a code path that is not harness-routed fails fast instead of reaching the internet.

Refuses to run on Vercel, outside CI unless AGENT_UI_ACCEPTANCE_LOCAL=1, or with what looks like a real provider key.

    python tests/agent_ui_acceptance/serve.py --port 4538 --pg-port 55538 --state-file $EVIDENCE/stack.json [--founder-fixture]
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLAG_ENV = {"RAFII_AGENT_HARNESS": "1", "RAFII_GENUI_ENABLED": "1", "RAFII_GENUI_ACTIONS_ENABLED": "1", "RAFII_GENUI_EDITS_ENABLED": "1",
            "RAFII_GENUI_FOUNDER_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1", "POSTRIFF_RESEARCH": "0", "OPENUI_TELEMETRY_DISABLED": "1",
            "RAFII_AGENT_BASE_URL": "http://127.0.0.1:9/v1", "OPENAI_AGENTS_DISABLE_TRACING": "1"}


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
CREATE TABLE IF NOT EXISTS public.agent_ui_acceptance_faults(workspace_id uuid, fault text, remaining int, armed_at timestamptz default now());
"""


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4538)
    parser.add_argument("--pg-port", type=int, default=55538)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--founder-fixture", action="store_true")
    args, rest = parser.parse_known_args(argv)
    guard_environment()
    os.environ["AGENT_UI_ACCEPTANCE_STATE"] = str(args.state_file.resolve())
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tests"))
    dev = load_dev_harness()
    original_start = dev.start_postgres

    def start_postgres(port=args.pg_port):
        dsn, data = original_start(port)
        for path in ui_migrations(args.founder_fixture):
            subprocess.run([str(dev.PG / "psql"), dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(dev.PG / "psql"), dsn, "-v", "ON_ERROR_STOP=1", "-q", "-c", FIXTURE_SQL], check=True, stdout=subprocess.DEVNULL)
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        args.state_file.write_text(json.dumps({"dsn": dsn, "pgPort": port, "apiPort": args.port, "founder": args.founder_fixture,
                                               "migrations": [p.name for p in ui_migrations(args.founder_fixture)], "startedAt": time.time()}))
        return dsn, data

    dev.start_postgres = start_postgres
    install_expiring_verifier(dev)
    install_fault_injection()
    sys.argv = ["postriff_dev_hosted.py", "--port", str(args.port), "--pg-port", str(args.pg_port)] + (["--founder-fixture"] if args.founder_fixture else []) + rest
    dev.main()


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


def _take_fault(workspace_id):
    """One armed fault for this workspace, consumed atomically (None when nothing is armed)."""
    import psycopg
    state = json.loads(Path(os.environ["AGENT_UI_ACCEPTANCE_STATE"]).read_text()) if os.environ.get("AGENT_UI_ACCEPTANCE_STATE") else None
    if not state or not workspace_id:
        return None
    with psycopg.connect(state["dsn"], autocommit=True) as db:
        row = db.execute("UPDATE public.agent_ui_acceptance_faults SET remaining=remaining-1 WHERE workspace_id=%s AND remaining>0 RETURNING fault",
                         (str(workspace_id),)).fetchone()
    return row[0] if row else None


def _workspace_of(ctx, projection):
    for source in (ctx, projection):
        for name in ("workspace_id", "workspaceId"):
            value = getattr(source, name, None) if not isinstance(source, dict) else source.get(name)
            if value:
                return value
    return None


def _is_usage(item) -> bool:
    return isinstance(item, dict) and (item.get("kind") in ("usage", "final", "completed") or "usage" in item and len(item) <= 4)


def _with_text(item, text):
    out = dict(item)
    for key in ("delta", "text", "source", "chunk"):
        if key in out and isinstance(out[key], str):
            out[key] = text
            return out
    return out


def install_fault_injection() -> None:
    """Wrap the presenter's output stream (provider boundary). Unarmed calls pass through untouched."""
    from postriff_phase2.agent_runtime_v2 import ui_presenter
    real = ui_presenter.stream_presentation

    async def faulty(ctx, projection, artifact_id, attempt_id, **kwargs):
        fault = _take_fault(_workspace_of(ctx, projection))
        stream = real(ctx, projection, artifact_id, attempt_id, **kwargs)
        if not fault:
            async for item in stream:
                yield item
            return
        sent = 0
        async for item in stream:
            if _is_usage(item):
                if fault == "no_usage":
                    continue                      # the provider never reported usage: cost must stay unknown, never zero
                yield item
                continue
            sent += 1
            if fault == "malformed":
                yield _with_text(item, "root = RafiiRoot(\nchart = )\n@Run(\n")
                continue
            if fault == "unknown_component":
                yield _with_text(item, "root = NotAComponent([])\n")
                continue
            if fault == "truncated" and sent > 1:
                return                            # stream ends mid-source with no final record
            if fault == "error" and sent > 1:
                raise ConnectionResetError("injected provider reset")
            if fault == "slow":
                await asyncio.sleep(1.5)
            yield item

    ui_presenter.stream_presentation = faulty
    try:
        from postriff_phase2.agent_runtime_v2 import ui_stream
        if getattr(ui_stream, "stream_presentation", None) is real:
            ui_stream.stream_presentation = faulty
    except Exception:  # noqa: BLE001 — ui_stream may import lazily; the module-level patch above still applies
        pass


if __name__ == "__main__":
    main()

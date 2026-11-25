"""Local macOS Brand Brain browser validation: real app/API/SQL, synthetic identities/providers.

No installs, owner profiles, application credentials, cloud CI or paid model calls.
Use the pinned project venv. This runner makes one fresh local build, or explicitly
reuses a verified identical app build, then runs the existing browser journeys. --preflight checks prerequisites without building or starting services.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def source_identity():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    paths = ["src", "web", "scripts", "tests", "migrations", "skills", "runtime", "templates", "api",
             "requirements.txt", "requirements-dev.txt", "pyproject.toml", "package.json", ".python-version"]
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD", "--", *paths], cwd=ROOT)
    extra = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z", "--", *paths], cwd=ROOT)
    digest = hashlib.sha256(diff)
    for name in sorted(filter(None, extra.split(b"\0"))):
        path = ROOT / os.fsdecode(name)
        if path.is_symlink():
            raise RuntimeError("Untracked source symlink needs review: " + os.fsdecode(name))
        digest.update(name + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"head": head, "workingChangesSha256": digest.hexdigest()}


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence-dir", type=Path, required=True, help="New task-owned output directory; existing paths are refused")
    p.add_argument("--browser-cache", type=Path, required=True, help="Existing Playwright Chromium/WebKit cache for this lockfile")
    p.add_argument("--node", type=Path, default=Path(shutil.which("node") or "/missing/node"))
    p.add_argument("--pg-bin", type=Path, default=Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin")))
    p.add_argument("--api-port", type=int, default=4348)
    p.add_argument("--web-port", type=int, default=4448)
    p.add_argument("--pg-port", type=int, default=55448)
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--reuse-build-from", type=Path, help="Prior local run receipt with completed unchanged build and clean shutdown; test-only changes allowed")
    return p.parse_args()


def preflight(a):
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("This local runner requires unprivileged macOS; use the separate cloud runner elsewhere")
    expected = (ROOT / ".python-version").read_text().strip()
    actual = ".".join(str(x) for x in sys.version_info[:len(expected.split("."))])
    if actual != expected or sys.prefix == sys.base_prefix:
        raise RuntimeError("Use the pinned isolated Python venv")
    for folder in (ROOT, WEB):
        if any(p.name != ".env.example" for p in folder.glob(".env*")):
            raise RuntimeError("Use an isolated worktree without application .env files; no environment values were read")
    for name in ("initdb", "pg_ctl", "psql", "postgres"):
        if not os.access(a.pg_bin / name, os.X_OK):
            raise RuntimeError("Installed PostgreSQL tool missing: " + name)
    if not os.access(a.node, os.X_OK):
        raise RuntimeError("Node executable is missing")
    version = subprocess.check_output([str(a.node), "--version"], text=True).strip()
    if not version.startswith("v24."):
        raise RuntimeError("Use the project Node 24 runtime")
    for name in ("next", "playwright", "axe-core"):
        installed = WEB / "node_modules" / name / "package.json"
        if not installed.is_file():
            raise RuntimeError("Install exact web lockfile dependencies before browser validation")
    lock = json.loads((WEB / "package-lock.json").read_text())["packages"]
    for name in ("next", "playwright", "axe-core"):
        version = json.loads((WEB / "node_modules" / name / "package.json").read_text())["version"]
        if version != lock["node_modules/" + name]["version"]:
            raise RuntimeError("Dependency version differs from the task lockfile: " + name)
    paths = subprocess.check_output(
        [str(a.node), "-e", "const p=require('playwright');console.log(JSON.stringify([p.chromium.executablePath(),p.webkit.executablePath()]));"],
        cwd=WEB, text=True, env={"PATH": str(a.node.parent) + ":/usr/bin:/bin", "PLAYWRIGHT_BROWSERS_PATH": str(a.browser_cache)})
    for value in json.loads(paths):
        executable = Path(value).resolve()
        if not executable.is_relative_to(a.browser_cache.resolve()) or not executable.is_file():
            raise RuntimeError("Compatible Chromium/WebKit browser binaries are missing from the specified cache")
    ports = (a.api_port, a.web_port, a.pg_port)
    if len(set(ports)) != 3 or any(not 1024 <= p <= 65535 for p in ports):
        raise RuntimeError("Three distinct unprivileged loopback ports are required")
    for port in ports:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    if a.evidence_dir.exists():
        raise RuntimeError("Evidence directory already exists; select a new run directory")
    return {"python": sys.version.split()[0], "node": subprocess.check_output([str(a.node), "--version"], text=True).strip(),
            "postgres": subprocess.check_output([str(a.pg_bin / "postgres"), "--version"], text=True).strip()}



def verified_build_reuse(a, versions):
    if a.reuse_build_from is None:
        return None
    raw = a.reuse_build_from.read_bytes()
    prior = json.loads(raw)
    clean = hashlib.sha256(b"").hexdigest()
    ports = {str(p): True for p in (a.api_port, a.web_port, a.pg_port)}
    if (prior.get("execution") != "LOCAL-SYNTHETIC" or prior.get("platform") != "darwin"
            or prior.get("stage") not in ("browser", "complete") or not prior.get("buildId")
            or prior.get("cleanupComplete") is not True or prior.get("versions") != versions
            or prior.get("candidateFlags") != {"brandBrainV11": True, "allCreationPlatforms": True}
            or prior.get("sourceBefore") != prior.get("sourceAfter")
            or prior.get("sourceBefore", {}).get("workingChangesSha256") != clean
            or prior.get("cleanupChecks") != {"loopbackPortsFree": ports, "remainingOwnedPostgresPidFiles": []}):
        raise RuntimeError("Prior receipt does not prove a completed matching local build and clean shutdown")
    if subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT).strip():
        raise RuntimeError("Build reuse requires a clean committed worktree")
    build_head = prior.get("buildSourceSha") or prior["sourceBefore"]["head"]
    current = source_identity()["head"]
    if len(build_head) != 40 or any(c not in "0123456789abcdef" for c in build_head):
        raise RuntimeError("Invalid prior build source identity")
    allowed = {
        "scripts/local-brand-brain-browser.py",
        "tests/phase2/brand_brain_browser_fixture.py",
        "web/tests/brand-brain-browser.cjs", "web/tests/brand-brain-browser-mode.cjs",
        "web/tests/brand-brain-browser-mode.test.cjs", "web/tests/personal-writing-browser-journeys.cjs",
        "web/tests/personal-writing-learning-review.cjs",
        "docs/personal-writing-intelligence-20261124/LOCAL-BROWSER-VALIDATION.md",
    }
    changed = subprocess.check_output(["git", "diff", "--name-only", "-z", build_head, current], cwd=ROOT).split(b"\0")
    paths = sorted(os.fsdecode(path) for path in changed if path)
    if any(path not in allowed for path in paths):
        raise RuntimeError("App build inputs changed outside the explicit harness-only allowlist")
    if (WEB / ".next/BUILD_ID").read_text().strip() != prior["buildId"]:
        raise RuntimeError("The on-disk Next build is not the prior receipt's actual build")
    return {"receipt": str(a.reuse_build_from.resolve()), "receiptSha256": hashlib.sha256(raw).hexdigest(),
            "buildSourceSha": build_head, "harnessSourceSha": current, "buildId": prior["buildId"],
            "allowedChangedPaths": paths}


def main():
    a = arguments()
    a.node, a.pg_bin, a.browser_cache, a.evidence_dir = (p.absolute() for p in (a.node, a.pg_bin, a.browser_cache, a.evidence_dir))
    try:
        versions = preflight(a)
        reuse = verified_build_reuse(a, versions)
    except Exception as error:
        print(json.dumps({"status": "VALIDATION_UNAVAILABLE", "execution": "LOCAL-SYNTHETIC", "error": str(error)}))
        return 3
    if a.preflight:
        print(json.dumps({"status": "PREFLIGHT_READY", "execution": "LOCAL-SYNTHETIC", "versions": versions, "browserRunPerformed": False, "buildReuse": reuse}))
        return 0
    # One runner per worktree. This does not replace coordination with another general-purpose build.
    lock_dir = WEB / ".next-brand-brain-local"
    lock_dir.mkdir(exist_ok=True)
    with (lock_dir / "runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("validation_unavailable: another local Brand Brain runner owns this worktree")
            return 3
        a.evidence_dir.mkdir(parents=True, exist_ok=False)
        receipt = {"status": "FAIL", "execution": "LOCAL-SYNTHETIC", "platform": sys.platform,
                   "versions": versions, "paidModelCalls": 0, "productionChanges": False,
                   "realProviderE2E": False, "personalVoiceAcceptance": False, "physicalIPhone": False,
                   "humanScreenReader": False, "candidateFlags": {"brandBrainV11": True, "allCreationPlatforms": True}, "sourceBefore": source_identity(), "startedAt": time.time(), "stage": "build",
                   "buildKind": "reused" if reuse else "fresh", "buildReuse": reuse}
        owned, streams, process_names = [], [], {}
        cleanup_complete = True
        runtime = None
        try:
            runtime = tempfile.mkdtemp(prefix="local-runtime-", dir=a.evidence_dir)
            tmp = Path(runtime) / "tmp"
            tmp.mkdir()
            empty_pgpass, empty_pgservice = Path(runtime) / "postgres-passwords-empty", Path(runtime) / "postgres-service-empty"
            for empty in (empty_pgpass, empty_pgservice):
                empty.touch(mode=0o600)
            env = {"PATH": str(a.node.parent) + ":" + str(a.pg_bin) + ":/usr/bin:/bin",
                   "TMPDIR": str(tmp), "LC_ALL": "C", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(ROOT / "src") + ":" + str(ROOT / "tests"),
                   "BRAND_BRAIN_EXECUTION": "local", "PLAYWRIGHT_BROWSERS_PATH": str(a.browser_cache),
                   "BRAND_BRAIN_WEB_URL": f"http://127.0.0.1:{a.web_port}",
                   "BRAND_BRAIN_BROWSER_EVIDENCE_DIR": str(a.evidence_dir),
                   "POSTRIFF_PG_BIN": str(a.pg_bin), "POSTRIFF_RESEARCH": "0",
                   "POSTRIFF_DEV_WEB_ORIGIN": f"http://127.0.0.1:{a.web_port}",
                   "PGUSER": "postriff_test", "PGHOST": "127.0.0.1", "PGPORT": str(a.pg_port),
                   "PGDATABASE": "postgres", "PGCONNECT_TIMEOUT": "5", "PGPASSFILE": str(empty_pgpass), "PGSERVICEFILE": str(empty_pgservice),
                   "NODE_ENV": "production", "POSTRIFF_API_ORIGIN": f"http://127.0.0.1:{a.api_port}",
                   "POSTRIFF_DEV_SSR": "1", "NEXT_PUBLIC_APP_URL": f"http://127.0.0.1:{a.web_port}",
                   "NEXT_PUBLIC_SUPABASE_URL": "", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "",
                   "NEXT_PUBLIC_BRAND_BRAIN_V11": "1", "RAFII_CREATION_ALL_PLATFORMS_ENABLED": "1", "NEXT_PUBLIC_SENTRY_DISABLED": "1", "NEXT_TELEMETRY_DISABLED": "1"}
            def run(command, log_name, timeout):
                with (a.evidence_dir / log_name).open("w") as output:
                    process = subprocess.Popen(command, cwd=WEB, env=env, stdout=output,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        returncode = process.wait(timeout=timeout)
                        if returncode:
                            raise subprocess.CalledProcessError(returncode, command)
                    finally:
                        # This session belongs only to this invocation, including build/browser children.
                        try: os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError: pass
                        try: process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            try: os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError: pass
                            process.wait(timeout=5)
                        # A terminated parent may leave descendants; only this owned group is signalled.
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
            def start(command, log_name):
                output = (a.evidence_dir / log_name).open("w"); streams.append(output)
                process = subprocess.Popen(command, cwd=WEB, env=env, stdout=output, stderr=subprocess.STDOUT)
                owned.append(process); process_names[process.pid] = log_name
                return process
            try:
                # Webpack supports the task's shared read-only node_modules path without a Turbopack outside-root escape.
                if reuse is None:
                    run([str(a.node), "node_modules/next/dist/bin/next", "build", "--webpack"], "build.log", 900)
                else:
                    if verified_build_reuse(a, versions) != reuse:
                        raise RuntimeError("Build reuse provenance changed before startup")
                    (a.evidence_dir / "build-reuse.json").write_text(json.dumps(reuse, indent=2) + "\n")
                receipt["buildSourceSha"] = reuse["buildSourceSha"] if reuse else receipt["sourceBefore"]["head"]
                receipt["harnessSourceSha"] = receipt["sourceBefore"]["head"]
                if source_identity() != receipt["sourceBefore"]:
                    raise RuntimeError("Source changed during the local build; inspect changes and rerun at a frozen revision")
                manifest = json.loads((WEB / ".next/routes-manifest.json").read_text())
                rewrites = manifest.get("rewrites", {})
                entries = rewrites if isinstance(rewrites, list) else sum(rewrites.values(), [])
                expected = f"http://127.0.0.1:{a.api_port}/api/:path*"
                if not any(x.get("source") == "/api/:path*" and x.get("destination") == expected for x in entries):
                    raise RuntimeError("Selected build does not target the owned loopback API")
                receipt["buildId"] = (WEB / ".next/BUILD_ID").read_text().strip()
                receipt["stage"] = "startup"
                # A long build must not turn an earlier free-port check into stale authority.
                for port in (a.api_port, a.web_port, a.pg_port):
                    with socket.socket() as probe:
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        probe.bind(("127.0.0.1", port))
                start([sys.executable, str(ROOT / "tests/phase2/brand_brain_browser_fixture.py"),
                       "--port", str(a.api_port), "--pg-port", str(a.pg_port)], "fixture.log")
                start([str(a.node), "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", str(a.web_port)], "next.log")
                deadline = time.monotonic() + 120
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for url in (f"http://127.0.0.1:{a.api_port}/api/health", f"http://127.0.0.1:{a.web_port}/api/health",
                            f"http://127.0.0.1:{a.web_port}/auth/sign-in"):
                    while True:
                        if any(p.poll() is not None for p in owned):
                            raise RuntimeError("Owned local fixture exited before readiness; inspect local logs")
                        try:
                            with opener.open(url, timeout=2) as response:
                                if response.status == 200: break
                        except (OSError, TimeoutError): pass
                        if time.monotonic() >= deadline: raise RuntimeError("Owned local fixture readiness deadline exceeded")
                        time.sleep(0.25)
                receipt["stage"] = "browser"
                run([str(a.node), "tests/brand-brain-browser.cjs"], "browser.log", 600)
                proof = json.loads((a.evidence_dir / "LOCAL-SYNTHETIC-browser.json").read_text())
                if proof.get("status") != "PASS" or proof.get("executionMode") != "local":
                    raise RuntimeError("No passing explicitly local browser receipt")
                checks = proof.get("results", [])
                if len(checks) < 26 or not {("chromium", 1440), ("chromium", 375), ("webkit", 375)}.issubset(
                        {(x.get("engine"), x.get("width")) for x in checks}):
                    raise RuntimeError("Incomplete local browser engine/viewport coverage")
                if not {"zh-Hant-HK", "zh-Hans-CN"}.issubset({x.get("locale") for x in checks}):
                    raise RuntimeError("Incomplete local browser locale coverage")
                receipt.update(status="PASS", stage="complete", checkpoints=len(checks))
            finally:
                receipt["ownedProcessExits"] = []
                for process in reversed(owned):
                    requested = process.poll() is None
                    forced = False
                    if requested:
                        process.terminate()
                        try: process.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            forced = True
                            cleanup_complete = False
                            process.kill(); process.wait(timeout=5)
                    name = process_names[process.pid]
                    # Next 16.4.3's start-server cleanup explicitly exits 143 after SIGTERM.
                    # Accept it only for our Next child after we requested termination;
                    # listener/PID-file checks below must independently prove it is gone.
                    allowed = (0, -signal.SIGTERM, 143) if name == "next.log" and requested else (0, -signal.SIGTERM)
                    accepted = process.returncode in allowed and not forced
                    receipt["ownedProcessExits"].append({"name": name, "pid": process.pid,
                        "exitCode": process.returncode, "terminationRequested": requested,
                        "forcedKill": forced, "expectedShutdown": accepted})
                    if not accepted:
                        cleanup_complete = False
                for output in streams: output.close()
        except (Exception, KeyboardInterrupt) as error:
            receipt.update(status="FAIL", error=str(error) or type(error).__name__)
        remaining = [str(path) for path in Path(runtime).glob("tmp/postriff-dev-pg-*/data/postmaster.pid")] if runtime else []
        free_ports = {}
        for port in (a.api_port, a.web_port, a.pg_port):
            try:
                with socket.socket() as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind(("127.0.0.1", port))
                free_ports[str(port)] = True
            except OSError:
                free_ports[str(port)] = False
        receipt["cleanupChecks"] = {"loopbackPortsFree": free_ports, "remainingOwnedPostgresPidFiles": remaining}
        cleanup_complete = cleanup_complete and not remaining and all(free_ports.values())
        if runtime and cleanup_complete:
            shutil.rmtree(runtime)
        elif runtime:
            receipt["retainedRuntime"] = runtime
        receipt["sourceAfter"] = source_identity()
        receipt["cleanupComplete"] = cleanup_complete
        if receipt["sourceAfter"] != receipt["sourceBefore"] or not cleanup_complete:
            receipt["status"] = "FAIL"
            receipt["validationError"] = "Source changed during validation or owned-process cleanup was incomplete"
        receipt["finishedAt"] = time.time()
        (a.evidence_dir / "LOCAL-SYNTHETIC-run.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt))
        return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())

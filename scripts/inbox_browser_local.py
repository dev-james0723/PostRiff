"""Run the Inbox browser journey with owned loopback processes and disposable PostgreSQL."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PORTS = (4460, 4461, 55488)


def main():
    for port in PORTS:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                print(json.dumps({"status": "validation_unavailable", "reason": f"loopback port {port} occupied"}))
                return 3
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TERM", "POSTRIFF_PG_BIN", "BROWSER_EXECUTABLE")}
    env.update(LC_ALL="C", POSTRIFF_LOCAL_CLI="0", POSTRIFF_RESEARCH="0", POSTRIFF_DEV_WEB_ORIGIN="http://127.0.0.1:4461",
               POSTRIFF_API_ORIGIN="http://127.0.0.1:4460", POSTRIFF_DEV_SSR="1", NEXT_PUBLIC_APP_URL="http://127.0.0.1:4461",
               NEXT_PUBLIC_SUPABASE_URL="", NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="", NEXT_PUBLIC_SENTRY_DISABLED="1", NEXT_TELEMETRY_DISABLED="1")
    children = []
    with tempfile.TemporaryDirectory(prefix="rafii-inbox-browser-") as tmp:
        try:
            for name, command, cwd in [
                ("backend", [str(ROOT / ".venv/bin/python"), "scripts/postriff_dev_hosted.py", "--inbox-fixture", "--port", "4460", "--pg-port", "55488"], ROOT),
                ("frontend", ["npm", "run", "start", "--", "-p", "4461", "-H", "127.0.0.1"], ROOT / "web")
            ]:
                log = open(Path(tmp) / f"{name}.log", "w")
                child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                children.append((child, log))
            for port, path in ((4460, "/api/catalog"), (4461, "/auth/sign-in")):
                deadline = time.monotonic() + 80
                while time.monotonic() < deadline:
                    if any(child.poll() is not None for child, _ in children):
                        raise RuntimeError("A local server exited during startup")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        time.sleep(.3)
                else:
                    raise RuntimeError(f"Local server on {port} did not become ready")
            result = subprocess.run(["node", "web/tests/inbox-v1-browser.cjs"], cwd=ROOT, env=env, timeout=300)
            if result.returncode:
                for name, log_path in (("backend", Path(tmp) / "backend.log"), ("frontend", Path(tmp) / "frontend.log")):
                    print(name + " log tail:\n" + "\n".join(log_path.read_text(errors="replace").splitlines()[-35:]))
            return result.returncode
        except Exception as error:
            print(json.dumps({"status": "validation_unavailable", "reason": str(error), "logs": {name: "\n".join((Path(tmp) / f"{name}.log").read_text(errors="replace").splitlines()[-20:]) for name in ("backend", "frontend") if (Path(tmp) / f"{name}.log").exists()}}))
            return 2
        finally:
            for child, _ in children:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
            for child, log in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                log.close()


if __name__ == "__main__":
    sys.exit(main())

"""Open the local Studio after the rebuilt site and its workspace both respond."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
from staging_studio import STAGING_SITE, SUPABASE_URL, check_built_settings, public_settings


APP = Path(__file__).resolve().parent
IS_LOCAL = os.environ.get("RAFII_STUDIO_LOCAL") == "1"
WEB = APP.parent / "web" if IS_LOCAL else STAGING_SITE
SITE = "http://localhost:47632"
EDITOR = SITE + "/app/creative"
LOCAL_EDIT = SITE + "/local-studio"
LOCAL_VIEWS = {"sample", "local-edit"}
LOCAL = build_opener(ProxyHandler({}))


def read_url(url):
    with LOCAL.open(url, timeout=2) as response:
        return response.read()


class OtherListener(RuntimeError):
    pass


def listener_pid(port, directory):
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    if result.returncode == 1 and not result.stdout and not result.stderr:
        return None
    result.check_returncode()
    pids = set(result.stdout.split())
    if len(pids) != 1:
        raise OtherListener(f"Could not identify a single app on port {port}.")
    pid = pids.pop()
    cwd = subprocess.run(
        ["/usr/sbin/lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
        capture_output=True, text=True,
    )
    if f"n{directory}" not in cwd.stdout.splitlines():
        raise OtherListener(f"Port {port} is being used by another app.")
    return int(pid)


def build_manifest(directory):
    build_id = (directory / ".next/BUILD_ID").read_text().strip()
    path = f"{build_id}/_buildManifest.js"
    return f"{SITE}/_next/static/{path}", (directory / ".next/static" / path).read_bytes()


def is_local_workspace(config):
    return config.get("provider") == "dev" and config.get("execution") == "dev-synthetic"


def local_preview_pid():
    directory = APP.parent / "web"
    pid = listener_pid(47632, directory)
    if pid is None:
        return None
    url, expected = build_manifest(directory)
    if read_url(url) == expected:
        with LOCAL.open(EDITOR, timeout=3) as page:
            sample = page.geturl() == EDITOR and page.headers.get("X-Rafii-Studio-View") in LOCAL_VIEWS
        recognized = sample or is_local_workspace(json.loads(read_url(SITE + "/api/auth/config")))
        if recognized and listener_pid(47632, directory) == pid:
            return pid
    raise OtherListener("The app at the Studio address could not be identified as this local preview.")


def release_web_listener(pid, directory, identify, prompt):
    if not sys.stdin.isatty():
        raise RuntimeError("Open the Studio launcher in Finder to choose whether to switch the running Studio.")
    print(prompt)
    try:
        answer = input("Type yes to switch, or press Return to keep the current Studio: ")
    except EOFError:
        return False
    if answer.strip().lower() not in ("y", "yes"):
        return False
    current = identify()
    if current is None:
        return True
    if current != pid:
        raise OtherListener("The running Studio changed while you were choosing. Reopen Studio to try again.")
    # Stop only the confirmed web listener. Its original launcher handles its own children.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        raise RuntimeError(
            "The current Studio is still running. Save your work, then press Control-C in its original "
            "Terminal window and reopen this launcher."
        ) from error
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = listener_pid(47632, directory)
        if current is None:
            return True
        if current != pid:
            raise OtherListener("A different Studio took the address during the switch.")
        time.sleep(0.2)
    raise RuntimeError("The local preview is still closing. Reopen Studio when it has finished.")


def release_local_preview(pid):
    return release_web_listener(pid, APP.parent / "web", local_preview_pid,
                                "The local sample Studio is open. Switching to Supabase will close it "
                                "and may clear local sample edits.")


def has_local_editor():
    try:
        with LOCAL.open(LOCAL_EDIT, timeout=3) as page:
            return page.geturl() == LOCAL_EDIT and page.headers.get("X-Rafii-Studio-View") == "local-edit"
    except HTTPError as error:
        if error.code != 404:
            raise
        return False


def earlier_staging_pid():
    pid = listener_pid(47632, STAGING_SITE)
    if pid is None:
        return None
    manifest, expected = build_manifest(STAGING_SITE)
    config = json.loads(read_url(SITE + "/api/auth/config"))
    if (read_url(manifest) == expected and config.get("provider") == "supabase"
            and config.get("projectUrl") == SUPABASE_URL and not has_local_editor()
            and listener_pid(47632, STAGING_SITE) == pid):
        return pid
    raise OtherListener("The running Studio changed. Reopen the launcher to check its version.")


def wait_for_site(manifest, child):
    url, expected = manifest
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if child and child.poll() is not None:
            break
        try:
            if read_url(url) != expected:
                raise RuntimeError("Another Studio build is running at this address.")
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.3)
    raise RuntimeError("The Studio website could not start on port 47632.")


def wait_for_workspace(child):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if child and child.poll() is not None:
            return False
        try:
            if IS_LOCAL:
                read_url("http://127.0.0.1:4331/api/auth/config")
            config = json.loads(read_url(SITE + "/api/auth/config"))
            if IS_LOCAL:
                matches = is_local_workspace(config)
            else:
                matches = config.get("provider") == "supabase" and config.get("projectUrl") == SUPABASE_URL
            if not matches:
                raise RuntimeError("The site is connected to a different workspace.")
            with LOCAL.open(EDITOR, timeout=3) as page:
                if page.status == 200 and page.headers.get("X-Rafii-Studio-View") not in LOCAL_VIEWS:
                    return page.geturl().split("?")[0] in (EDITOR, SITE + "/auth/sign-in")
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.5)
    return False


def stop_workspace_cluster(scratch):
    # The harness normally shuts down its own database. It can be interrupted
    # during initialization, before its shutdown handler has been installed.
    pg_ctl = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin")) / "pg_ctl"
    for pidfile in scratch.glob("postriff-dev-pg-*/data/postmaster.pid"):
        command = [pg_ctl, "-D", pidfile.parent]
        if subprocess.run([*command, "status"], stdout=subprocess.DEVNULL).returncode == 0:
            subprocess.run([*command, "-m", "fast", "-w", "stop"], check=True)
    # Empty directories from failed initdb can be released; retain diagnostic files.
    for directory in scratch.glob("postriff-dev-pg-*"):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if not any(scratch.iterdir()):
        scratch.rmdir()


def start():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-open", action="store_true", help="Check startup without opening the browser")
    parser.add_argument("--edit", action="store_true", help="Open the media editor on this Mac")
    args = parser.parse_args()
    web_child = api_child = scratch = None
    try:
        # Serialize double-clicks, including the interval before either port is bound.
        with Path(__file__).open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = None
            try:
                web_running = listener_pid(47632, WEB)
            except OtherListener:
                if IS_LOCAL:
                    raise
                previous = local_preview_pid()
                web_running = None
            if previous and args.no_open:
                raise RuntimeError("The local sample Studio is open. Launch Studio normally to switch to Supabase.")
            if not (WEB / ".next/BUILD_ID").is_file() and not web_running:
                subprocess.run([APP / "Start Rafii Studio.command", "--build"], check=True)
            manifest = build_manifest(WEB)
            if previous:
                check_built_settings(public_settings())
                if not release_local_preview(previous):
                    print("Keeping the local Studio open.", flush=True)
                    return
            if args.edit and web_running and not has_local_editor():
                if IS_LOCAL or args.no_open:
                    raise RuntimeError("The earlier Studio is open. Save your edits and reopen "
                                       "‘Open Rafii Video Editor.command’ to switch versions.")
                if earlier_staging_pid() != web_running:
                    raise OtherListener("The Studio listener has changed. Reopen the launcher to check again.")
                check_built_settings(public_settings())
                subprocess.run([APP / "Start Rafii Studio.command", "--build-editor"], check=True)
                if not release_web_listener(web_running, STAGING_SITE, earlier_staging_pid,
                        "An earlier Studio is running. Save any open edits before restarting it for the new local video editor."):
                    print("Keeping the current Studio open.", flush=True)
                    return
                web_running = None
            api_running = IS_LOCAL and listener_pid(4331, APP.parent)
            if not web_running:
                web_child = subprocess.Popen([APP / "Start Rafii Studio.command", "--serve-web"])
            wait_for_site(manifest, web_child)
            if IS_LOCAL and not api_running and not args.edit:
                scratch = Path(tempfile.mkdtemp(prefix="rafii-studio-"))
                api_child = subprocess.Popen([APP / "Start Rafii Workspace.command", "--service"],
                                             env={**os.environ, "TMPDIR": str(scratch)},
                                             start_new_session=True)
            workspace = "local workspace" if IS_LOCAL else "Supabase staging workspace"
            print(f"Connecting Rafii Video Studio to its {workspace}…", flush=True)
            if args.edit:
                if not has_local_editor():
                    raise RuntimeError("The running Studio does not have the rebuilt local editor.")
                print(f"Rafii local video editor is ready at {LOCAL_EDIT}", flush=True)
            elif wait_for_workspace(api_child):
                print(f"Rafii Video Studio is ready at {EDITOR}", flush=True)
            elif IS_LOCAL:
                with LOCAL.open(EDITOR, timeout=3) as page:
                    view = page.headers.get("X-Rafii-Studio-View")
                    if view not in LOCAL_VIEWS:
                        raise RuntimeError("The local workspace is unavailable.")
                print(f"The local workspace is unavailable. Opening the local {'editor' if view == 'local-edit' else 'sample'} at {EDITOR}", flush=True)
            else:
                raise RuntimeError("Rafii's staging workspace could not be reached. Check the connection and reopen Studio.")
        if not args.no_open:
            subprocess.run(["/usr/bin/open", LOCAL_EDIT if args.edit else EDITOR], check=True)
        if web_child or (api_child and api_child.poll() is None):
            print("Keep this window open while using Studio. Press Control-C to close it.", flush=True)
            (web_child or api_child).wait()
    finally:
        if api_child and api_child.poll() is None:
            try:
                os.killpg(api_child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if web_child and web_child.poll() is None:
            web_child.terminate()
        for child in (api_child, web_child):
            if child:
                child.wait()
        if scratch:
            stop_workspace_cluster(scratch)


if __name__ == "__main__":
    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    try:
        start()
    except KeyboardInterrupt:
        sys.exit(0)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Studio could not open. {error}")

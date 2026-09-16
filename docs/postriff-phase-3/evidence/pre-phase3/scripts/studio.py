#!/usr/bin/env python3
"""Manage Studio and its local handoff worker. No external publishing transport."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_DATA = Path.home() / "Library/Application Support/JamesAuStudio"


def checked_path(path: Path) -> Path:
    """Normalize only macOS system aliases; reject application symlink paths."""
    path = Path(os.path.abspath(path))
    for alias in ("/var", "/tmp"):
        if ((str(path) == alias or str(path).startswith(alias + "/"))
                and Path(alias).is_symlink() and Path(alias).resolve() == Path("/private" + alias)):
            path = Path("/private" + str(path))
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ValueError("Studio paths must not contain application symbolic links")
    return path


def health(port: int) -> dict | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            result = json.loads(response.read(8192))
        return result if result.get("app") == "james-au-studio" else None
    except (URLError, OSError, ValueError):
        return None


def record_path(data: Path) -> Path:
    return data / "studio-service.json"


def read_record(data: Path) -> dict | None:
    data = checked_path(data)
    path = checked_path(record_path(data))
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                raise ValueError("Service record must be a bounded regular file")
            record = json.load(source)
        if (not isinstance(record, dict) or record.get("dataDir") != str(data)
                or record.get("root") != str(ROOT)):
            raise ValueError("Service record belongs to a different installation")
        if (type(record.get("pid")) is not int or record["pid"] <= 1
                or type(record.get("port")) is not int or not 1024 <= record["port"] <= 65535):
            raise ValueError("Service record has invalid process identity")
        return record
    except FileNotFoundError:
        return None


def matches_process(record: dict) -> bool:
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return False
    result = subprocess.run(["/bin/ps", "-ww", "-p", str(pid), "-o", "command="],
                            text=True, capture_output=True, check=False)
    command = result.stdout.strip()
    # Fail closed on stale/reused PIDs. Never kill a service merely because of its port.
    expected_tail = (f"{Path(__file__).resolve()} _serve "
                     f"--data-dir {record['dataDir']} --port {record['port']}")
    return result.returncode == 0 and command.endswith(" " + expected_tail)


def private_dir(path: Path) -> Path:
    path = checked_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    checked_path(path)
    path.chmod(0o700)
    return path


def private_append(path: Path, *, binary=False):
    """Open reserved lock/log files without following a final symlink."""
    path = checked_path(path)
    descriptor = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT
                         | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Studio lock/log files must be regular files")
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "ab" if binary else "a+")
    except BaseException:
        os.close(descriptor)
        raise


def write_record(data: Path, record: dict) -> None:
    """Atomic replacement never follows a record symlink or mutates a hardlink."""
    data = checked_path(data)
    path = checked_path(record_path(data))
    if path.exists() and not path.is_file():
        raise ValueError("Service record must be a regular file")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".studio-service-", suffix=".tmp", dir=data)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(json.dumps(record, indent=2) + "\n")
            output.flush()
            os.fsync(output.fileno())
        checked_path(path)
        os.replace(temporary, path)  # Atomic rename does not dereference the destination.
    finally:
        temporary.unlink(missing_ok=True)  # Only this call's private temporary record.


def serve(data: Path, port: int) -> None:
    from james_au_social.studio_api import create_app
    from james_au_social.studio_codex import CodexProvider
    from james_au_social.studio_worker import WorkerSupervisor
    from james_au_social.studio_connections import ConnectionBroker
    import uvicorn

    data = private_dir(data)
    lock_path = data / "studio-service.lock"
    checked_path(record_path(data))
    with private_append(lock_path) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("This workspace already has a running service") from error
        app = create_app(data_dir=data, project_root=ROOT, port=port, provider=CodexProvider(ROOT, data),
                         delivery_supervisor=WorkerSupervisor(ROOT, data, port),
                         connection_broker=ConnectionBroker(ROOT, data, port))
        record = {"pid": os.getpid(), "port": port, "root": str(ROOT),
                  "dataDir": str(data), "service": "workspace_and_local_handoff"}
        write_record(data, record)
        try:
            uvicorn.run(app, host="127.0.0.1", port=port, workers=1,
                        access_log=False, log_level="warning", proxy_headers=False)
        finally:
            # Keep a stopped record for diagnostics; do not remove user data.
            record["stopped"] = True
            write_record(data, record)


def worker(data: Path, parent_pid: int) -> None:
    from james_au_social.studio import StudioStore
    from james_au_social.studio_worker import run_worker

    if type(parent_pid) is not int or parent_pid <= 1 or os.getppid() != parent_pid:
        raise ValueError("Worker must be started by its owning Studio service")
    data = private_dir(data)
    with private_append(data / "studio-worker.lock") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("This workspace already has a delivery worker") from error
        run_worker(StudioStore(data, ROOT), parent_pid)


def start(data: Path, port: int) -> dict:
    if not (ROOT / "studio/web/dist/index.html").is_file():
        raise ValueError("Build the Studio interface first: cd studio/web && npm run build")
    data = private_dir(data)
    existing = read_record(data)
    if existing and not existing.get("stopped") and matches_process(existing):
        return {"status": "already_running", "url": f"http://127.0.0.1:{existing['port']}",
                "health": health(existing["port"])}
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError(f"Port {port} is occupied. No process was stopped")
    log_path = data / "studio-service.log"
    with private_append(log_path, binary=True) as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_serve",
                                  "--data-dir", str(data), "--port", str(port)],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=log, start_new_session=True)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise ValueError(f"Studio did not start. Inspect the local log: {log_path}")
        if health(port):
            return {"status": "running", "url": f"http://127.0.0.1:{port}",
                    "pid": child.pid, "dataDir": str(data), "publishing": "per_channel_approval_required"}
        time.sleep(0.15)
    raise ValueError("Startup is unresolved; inspect status/log before retrying")


def stop(data: Path) -> dict:
    record = read_record(data)
    if not record or record.get("stopped"):
        return {"status": "stopped", "data_preserved": True}
    if not matches_process(record):
        return {"status": "not_signalled", "reason": "No exact running Studio process matches the record",
                "data_preserved": True}
    os.kill(record["pid"], signal.SIGTERM)
    # Permit the editorial worker's bounded cancellation/child cleanup to finish.
    # Never SIGKILL the server or an unrelated process on a timeout.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not matches_process(record):
            return {"status": "stopped", "data_preserved": True}
        time.sleep(0.15)
    return {"status": "stopping", "data_preserved": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "status", "stop", "backup", "restore", "_serve", "_worker"])
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--port", type=int, default=4310)
    parser.add_argument("--output", type=Path, help="New backup ZIP path; never overwritten")
    parser.add_argument("--archive", type=Path, help="Backup ZIP to restore")
    parser.add_argument("--target", type=Path, help="New empty directory for restore")
    parser.add_argument("--open", action="store_true", help="Open the running local Studio in your browser")
    args = parser.parse_args()
    data = args.data_dir.absolute()
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged local port from 1024 to 65535")
    os.umask(0o077)
    try:
        data = checked_path(data)
        if args.command == "_serve":
            serve(data, args.port)
            return
        if args.command == "_worker":
            worker(data, args.parent_pid)
            return
        if args.command == "start":
            result = start(data, args.port)
        elif args.command == "stop":
            result = stop(data)
        elif args.command == "status":
            record = read_record(data)
            port = record["port"] if record else args.port
            result = {"status": "running" if record and matches_process(record) else "stopped",
                      "health": health(port), "url": f"http://127.0.0.1:{port}",
                      "dataDir": str(data), "scheduling": "tiktok_queue_requires_running_service", "publishing": "per_channel_approval_required",
                      "localHandoffWorker": "supervised_when_service_running"}
        elif args.command == "backup":
            if not args.output or args.output.exists() or args.output.is_symlink():
                raise ValueError("Provide a new --output backup file; existing files are never overwritten")
            if not (data / "studio.sqlite3").is_file():
                raise ValueError("No Studio database exists in this data directory")
            from james_au_social.studio import StudioStore
            archive = StudioStore(data, ROOT).backup()
            with args.output.open("xb") as output:
                output.write(archive)
            result = {"status": "backup_created", "path": str(args.output.absolute()), "bytes": len(archive)}
        else:
            if not args.archive or not args.target:
                raise ValueError("Restore requires --archive and a new empty --target directory")
            from james_au_social.studio import restore_new, MAX_BACKUP_BYTES
            if args.archive.stat().st_size > MAX_BACKUP_BYTES:
                raise ValueError("Backup archive exceeds the restore size limit")
            result = restore_new(args.archive.read_bytes(), args.target.absolute(), ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.open and args.command == "start" and result.get("url"):
            import webbrowser
            webbrowser.open(result["url"])
    except (ValueError, OSError) as error:
        print(f"Studio: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

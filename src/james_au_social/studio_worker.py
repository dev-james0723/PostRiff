"""Supervised local handoff worker. No model, credential or network transport."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid


class WorkerSupervisor:
    """Own one child handle; never discover or signal processes by a saved PID.

    The HTTP service owns lifecycle only. Every delivery transaction happens in
    the separate worker process. Its DB lease plus OS lock protect against double
    workers; a child exits when its parent changes, including abrupt parent exit.
    """

    def __init__(self, root: Path, data: Path, port: int):
        self.root, self.data, self.port = root, data, port
        self.stop_event = threading.Event()
        self.thread = None
        self.child = None

    def start(self):
        if self.thread is not None:
            raise RuntimeError("worker_supervisor_already_started")
        self.thread = threading.Thread(target=self._supervise, name="studio-delivery-supervisor", daemon=True)
        self.thread.start()

    def _spawn(self):
        # Fixed argv, no shell or owner API cookie. No arbitrary executor input.
        return subprocess.Popen(
            [sys.executable, str(self.root / "scripts/studio.py"), "_worker",
             "--data-dir", str(self.data), "--port", str(self.port),
             "--parent-pid", str(os.getpid())],
            cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )

    def _reap(self, child):
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=6)
        except subprocess.TimeoutExpired:
            # Only our still-owned local-only child, never the HTTP service, a
            # saved PID, a transport process or another application on the port.
            child.kill()
            child.wait(timeout=2)

    def _supervise(self):
        delay = 1
        try:
            while not self.stop_event.is_set():
                try:
                    self.child = self._spawn()
                except OSError:
                    # Do not log paths, content, environment or raw exceptions.
                    if self.stop_event.wait(delay):
                        break
                    delay = min(delay * 2, 30)
                    continue
                while not self.stop_event.wait(0.25):
                    if self.child.poll() is not None:
                        break
                self._reap(self.child)
                self.child = None
                if self.stop_event.wait(delay):
                    break
                delay = min(delay * 2, 30)
        finally:
            if self.child is not None:
                self._reap(self.child)
                self.child = None

    def shutdown(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise RuntimeError("worker_shutdown_unresolved")


def run_worker(store, parent_pid: int, *, interval: float = 1.0):
    """Run under the launcher's owner-only worker flock; no public tick endpoint."""
    if type(parent_pid) is not int or parent_pid <= 1 or os.getppid() != parent_pid:
        raise ValueError("worker_parent_mismatch")
    from .studio_delivery import DeliveryService

    service = DeliveryService(store)
    owner = uuid.uuid4().hex
    stopped = threading.Event()
    prior = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        prior[signum] = signal.signal(signum, lambda *_: stopped.set())
    try:
        while not stopped.is_set() and os.getppid() == parent_pid:
            # tick owns a bounded immediate DB transaction including pause,
            # current content validation, lease and due-window decisions.
            result = service.tick(owner)
            if not result["acquired"]:
                # Sleep/clock jumps can retire this process's token. It must not
                # loop forever with an expired identity or invent a new token
                # in-place. Exit; supervisor creates a fresh process and owner.
                break
            stopped.wait(interval)
    finally:
        try:
            service.release(owner)
        finally:
            for signum, handler in prior.items():
                signal.signal(signum, handler)

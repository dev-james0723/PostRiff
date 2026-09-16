"""Transport interface. Shipping tests use fake providers only."""
from __future__ import annotations

from typing import Protocol
from .execution import JobStore


class Driver(Protocol):
    def submit(self, job_id: str, payload: dict) -> dict: ...
    def inspect(self, job_id: str, payload: dict) -> dict | None: ...


def execute(store: JobStore, job_id: str, route: dict, driver: Driver, *, now: str) -> str:
    """Invoke a prequalified driver once; caller owns authentication of receipts."""
    if not store.begin(job_id, route, now=now):
        return store.get(job_id)["status"]
    try:
        driver.submit(job_id, store.get(job_id)["payload"])
    except Exception:
        # Any failure after begin is conservatively uncertain. Never retain raw
        # transport error bodies, which may include credentials or private URLs.
        store.finish(job_id, "ambiguous_after_submit", now=now)
        return "ambiguous"
    store.finish(job_id, "success", now=now)
    return "submitted"


def reconcile(store: JobStore, job_id: str, driver: Driver, *, now: str) -> str:
    try:
        evidence = driver.inspect(job_id, store.get(job_id)["payload"])
    except Exception:
        return "unresolved"
    if evidence is None:
        return "unresolved"
    return store.reconcile(job_id, evidence, now=now)

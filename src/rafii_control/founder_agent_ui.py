"""Lane F — founder-scoped Generative UI (J09) under /api/control/v2/agent/ui/* (A-DECISIONS D-A22).

Frozen entry point (dispatched by rafii_control.http.ControlApplication.founder, capability `copilot.use`):
- handle(consumer, principal, method, path, body, query, request_id, *, control) -> dict
  Routes: POST presentations | GET presentations/{id} | GET presentations/{id}/events?after= | POST presentations/{id}/cancel |
  POST presentations/{id}/edits | POST presentations/{id}/state | GET messages/{id} | POST queries.
  Founder transport is a blocking POST + polling replay of durable checkpoints (ControlApplication returns one JSON body).
  Founder scope only (`founder:<mode>:<env>` artifacts); read-only manifest; never accepts a client founder flag.
"""
from __future__ import annotations

from .auth import ControlError


def handle(consumer, principal, method, path, body, query, request_id, *, control):  # lane F
    raise ControlError('SOURCE_UNAVAILABLE', 503)

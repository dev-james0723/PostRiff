"""Lane B — presentation accounting (spec §9; G13). Reserve before each physical attempt inside the parent turn's combined
ceiling (ledger key 'agent:{parentRunId}:ui:{attemptId}', run_id = parent run), no hidden retries, settle known/unknown once.

Frozen entry points:
- reserve_attempt(runtime, cur, auth, artifact, attempt, route) -> dict  (raises AlphaError 402/429/503 -> native fallback, no call)
- settle_attempt(runtime, cur, auth, attempt, usage) -> dict            (idempotent; unknown keeps the hold, never assumed zero)
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def reserve_attempt(runtime, cur, auth, artifact, attempt, route):  # lane B
    _not_ready('reserve_attempt')


def settle_attempt(runtime, cur, auth, attempt, usage):  # lane B
    _not_ready('settle_attempt')

"""Speech-to-text provider boundary for raw audio intake (PRD R-FWR-04; DECISIONS D-014).

No transcription vendor is enrolled. `ROUTES` is empty, so `RAFII_TRANSCRIPTION_ROUTE` unset — or naming anything not
registered here — means audio is `unsupported` with reason `transcription_route_not_enabled`. A route James approves
later registers a factory here with its provider, model, per-call limits and cost ceiling; the service quotes and
reserves credits from that ceiling before any provider I/O and settles the actual cost (or keeps an unknown cost
pending for reconciliation). A route is an object with:

    name, provider, model, synthetic (bool), max_seconds, max_bytes, timeout_seconds
    max_cost_usd_micro(seconds) -> int        # the most one call can cost; what credits are reserved against
    typical_cost_usd_micro(seconds) -> int    # the usual cost, shown as an estimate
    transcribe(data, mime, seconds, *, timeout) -> {"text": str, "actualUsdMicro": int | None}

`transcribe` raises `TranscriptionFailed` only when the provider provably did no billable work (the attempt may be
retried under the same reservation); any other exception is an unknown outcome and is never retried automatically.

`SyntheticTranscriber` is a labelled test double: no network, every result marked synthetic. Only tests inject it;
no environment value selects it.
"""
from __future__ import annotations

import math

ROUTES = {}   # name -> factory(values) for approved provider routes; none is approved yet


class TranscriptionFailed(Exception):
    """A refusal before billable work (proven unbilled)."""

    def __init__(self, code="provider_refused"):
        super().__init__(code)
        self.code = code


def route_from_environment(values):
    """(route, None) for an approved, configured route, else (None, reason)."""
    name = str((values or {}).get("RAFII_TRANSCRIPTION_ROUTE") or "").strip()
    factory = ROUTES.get(name) if name else None
    if factory is None:
        return None, "transcription_route_not_enabled"
    return factory(values), None


class SyntheticTranscriber:
    """Labelled synthetic route for tests: deterministic text, deterministic cost, scripted failures."""
    name, provider, model, synthetic = "synthetic", "synthetic", "synthetic-transcriber-v1", True

    def __init__(self, script=None, *, usd_micro_per_minute=6_000, max_seconds=600, max_bytes=30_000_000, timeout_seconds=5, fail=None, cost_known=True):
        self.script = script if script is not None else "This is a synthetic transcript used in tests. It is not a real recording."
        self.per_minute, self.max_seconds, self.max_bytes, self.timeout_seconds = usd_micro_per_minute, max_seconds, max_bytes, timeout_seconds
        self.fail, self.cost_known, self.calls = fail, cost_known, []

    def max_cost_usd_micro(self, seconds):
        return max(1, math.ceil(float(seconds) / 60)) * self.per_minute

    def typical_cost_usd_micro(self, seconds):
        return max(1, math.ceil(float(seconds) / 60 * self.per_minute))

    def transcribe(self, data, mime, seconds, *, timeout):
        self.calls.append({"bytes": len(data), "mime": mime, "seconds": seconds, "timeout": timeout})
        if self.fail == "refused":
            raise TranscriptionFailed("provider_refused")
        if self.fail == "unknown":
            raise TimeoutError("synthetic: the provider did not answer after the audio was sent")
        text = f"[Synthetic transcript of a {round(float(seconds))}-second recording]\n{self.script}"
        return {"text": text, "actualUsdMicro": self.typical_cost_usd_micro(seconds) if self.cost_known else None}

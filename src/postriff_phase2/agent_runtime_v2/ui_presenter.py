"""Lane B — the restricted UI Presenter (spec §2.3). No business-write tools, no handoffs, no conversational output.

Frozen entry point:
- async stream_presentation(ctx, projection, artifact_id, attempt_id, *, mode='generate', base_source=None, instruction=None)
  -> AsyncIterator[dict]: yields provider source deltas and a final usage record. Uses the existing RuntimeConfig route
  (fast_language unless evidence says otherwise), AsyncOpenAI(max_retries=0), the generated prompt asset for the projection's
  journey component groups (agent_runtime_v2/generated/), timeout <= BOUNDS.generationTimeoutSeconds capped by the remaining
  turn/deployment budget. Exactly one automatic UI-only repair is decided by ui_stream from the server validator result.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


async def stream_presentation(ctx, projection, artifact_id, attempt_id, *, mode='generate', base_source=None, instruction=None):  # lane B
    _not_ready('stream_presentation')
    yield {}

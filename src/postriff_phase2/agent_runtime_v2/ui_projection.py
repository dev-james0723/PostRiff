"""Lane D — deterministic eligibility and the authorized UI projection (spec §2.2-2.3, §6.1; 02-CONTRACTS §3).

Frozen entry points:
- eligibility(result, request_text, modality, *, flags) -> dict UiTurnHandoffV1 {eligible, slot, reason, journeyIds}
  Pure and deterministic: greetings/plain answers/acknowledgements -> not eligible; compare/table/filter/chart/journey tool
  results -> eligible. Called by service._persist (A seam) and stored as result.ui.
- project_ui_context(cur, auth, verified_result, surface, selection_state) -> dict UiProjection {manifest_id, journey_ids,
  component_group_ids, data_bindings, action_bindings, allowed_context, fallback_text, egress_decision}. Only data refs, counts,
  kinds and opaque ids the Manager already saw; never media bytes, signed URLs, private text or secrets.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def eligibility(result, request_text, modality, *, flags):  # lane D
    _not_ready('eligibility')


def project_ui_context(cur, auth, verified_result, surface, selection_state):  # lane D
    _not_ready('project_ui_context')

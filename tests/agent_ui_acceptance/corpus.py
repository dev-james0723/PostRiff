"""The acceptance map: every 04-ACCEPTANCE gate and every "Minimum negative corpus" item, with the G harness part that
produces its evidence and the evidence kinds that may satisfy it.

This module is data. Tests import it to stay in step (a corpus item without an implemented check fails
`test_agent_ui_acceptance_release`), `release.py` reads `GATES[*]["kinds"]` to refuse mock/fixture/emulation evidence where a
gate needs a real provider, database, deployment or device, and the evidence matrix under
docs/design/openui-production-2026-10-08/evidence/g/ is generated from it.

Evidence kinds (an evidence record's `environment.kind`):
    contract              pure unit test of the frozen contract / A seam (no DB, no network)
    ci-harness            cloud CI: real WSGI app + real PostgreSQL 17 + real Node parser seam; synthetic identity/providers
    ci-browser-emulation  cloud CI Playwright (Chromium/WebKit) with emulated viewports/devices — labelled emulation
    preview-deployment    a Vercel preview deployment reached through approved access
    production-canary     production origin, allowlisted test workspace (RAFII_GENUI_WORKSPACES)
    production            production origin, intended eligible audience
    live-provider         a real model provider call recorded by the server's own attempt/ledger rows
    physical-device       a named physical device (e.g. iPhone Safari) driven by a person or device lab
    manual                a reproducible manual procedure with recorded steps (screen reader, keyboard)
    repository            git/CI metadata (SHA, PR, workflow run)
"""
from __future__ import annotations

EVIDENCE_KINDS = ("contract", "ci-harness", "ci-browser-emulation", "preview-deployment", "production-canary", "production", "live-provider",
                  "physical-device", "manual", "repository")
DEPLOYED = ("preview-deployment", "production-canary", "production")
PRODUCTION = ("production-canary", "production")

# kinds: a list of alternatives groups; every group needs one passing record of one of its kinds for the candidate SHA.
GATES = {
    "G01": {"owner": "A", "kinds": [("repository",)], "g": "release.py checks the frozen contract hash and ownership register are recorded"},
    "G02": {"owner": "A/C", "kinds": [("contract", "ci-harness")], "g": "contract + api corpus legacy-answer checks"},
    "G03": {"owner": "B/C", "kinds": [("live-provider",), PRODUCTION], "g": "scripts/agent_ui_live.py generate (30 normal cases)"},
    "G04": {"owner": "B/F", "kinds": [DEPLOYED], "g": "scripts/agent_ui_live.py stream (probe + real presentation, UTF-8 split, cancel)"},
    "G05": {"owner": "C/D", "kinds": [("ci-harness",), PRODUCTION], "g": "api corpus G05 + agent_ui_live.py filter (model-attempt delta 0)"},
    "G06": {"owner": "C/D", "kinds": [("ci-harness",)], "g": "api corpus + validator corpus (DB/audit before-and-after)"},
    "G07": {"owner": "D", "kinds": [("ci-harness",)], "g": "api corpus role matrix + second tenant + founder"},
    "G08": {"owner": "D", "kinds": [("ci-harness",)], "g": "api corpus approvals (digest/expiry/role/timezone; prepared != applied)"},
    "G09": {"owner": "D/F", "kinds": [("ci-harness",)], "g": "api corpus idempotency (double click, two tabs, same key, aborted response)"},
    "G10": {"owner": "C/F", "kinds": [("ci-harness",), ("live-provider",)], "g": "api corpus stale patch + agent_ui_live.py edit (9 journeys)"},
    "G11": {"owner": "F", "kinds": [("ci-harness",)], "g": "api corpus reopen/replay zero attempts + e2e history reload"},
    "G12": {"owner": "B/C/F", "kinds": [("ci-harness",)], "g": "api corpus fault injection + e2e native fallback"},
    "G13": {"owner": "B", "kinds": [("ci-harness",), PRODUCTION], "g": "api corpus ledger assertions + live runner server-recorded cost"},
    "G14": {"owner": "B/D", "kinds": [("contract", "ci-harness"), ("ci-browser-emulation",)], "g": "redaction + network allowlist in e2e"},
    "G15": {"owner": "C/F", "kinds": [("ci-browser-emulation",), ("physical-device",)], "g": "e2e viewports (emulation) + real iPhone Safari"},
    "G16": {"owner": "C/G", "kinds": [("ci-browser-emulation",), ("manual", "physical-device")], "g": "e2e axe/keyboard/locale + manual screen reader"},
    "G17": {"owner": "C/B", "kinds": [("ci-browser-emulation",), ("live-provider",)], "g": "e2e 100 warm interactions + live timings"},
    "G18": {"owner": "C/F", "kinds": [("ci-harness",), ("ci-browser-emulation",)], "g": "api bounds + e2e hidden/no-polling network log"},
    "G19": {"owner": "F", "kinds": [("ci-harness",)], "g": "api corpus voice uiContext + speakableSummary without DSL"},
    "G20": {"owner": "A/G", "kinds": [("ci-harness",)], "g": "agent_ui_validation.sh regression on the integrated SHA"},
    "G21": {"owner": "G", "kinds": [("ci-harness",), PRODUCTION], "g": "api corpus unknown != zero + unavailable states"},
    "G22": {"owner": "A", "kinds": [("ci-harness",), DEPLOYED], "g": "migration rehearsal + route smoke"},
    "G23": {"owner": "A/G", "kinds": [("preview-deployment",), PRODUCTION], "g": "kill-switch drill (api corpus disabled routes + deployed drill)"},
    "G24": {"owner": "A", "kinds": [("production",)], "g": "release receipt"},
    "G25": {"owner": "A/G", "kinds": [("repository",)], "g": "release.py over the final matrix"},
}
for _j in ("J01", "J02", "J03", "J04", "J05", "J06", "J07", "J08", "J09"):
    GATES[_j] = {"owner": "E/D/F", "kinds": [("ci-harness",), PRODUCTION], "g": f"api corpus {_j} normal/empty/denied/partial/failure + live journey"}

# The 04-ACCEPTANCE minimum negative corpus. `checks` name the executable tests (module.Class.test) that cover the item.
NEGATIVE_CORPUS = (
    {"id": "NC01", "item": "Forged tenant/resource/manifest/action IDs", "gates": ("G07", "G06"),
     "checks": ("api_corpus.Isolation.test_foreign_workspace_path_reveals_nothing", "api_corpus.Isolation.test_random_and_foreign_artifact_ids",
                "api_corpus.Isolation.test_forged_binding_and_action_ids", "test_agent_ui_acceptance_contract.Requests.test_privilege_keys_refused_everywhere")},
    {"id": "NC02", "item": "Viewer write", "gates": ("G07",), "checks": ("api_corpus.Roles.test_viewer_cannot_activate_or_execute",)},
    {"id": "NC03", "item": "Founder-scope injection", "gates": ("G07",),
     "checks": ("api_corpus.Isolation.test_founder_scope_injection", "api_corpus.Founder.test_consumer_and_founder_artifacts_do_not_cross",
                "test_agent_ui_acceptance_contract.Requests.test_privilege_keys_refused_everywhere")},
    {"id": "NC04", "item": "Revoked source", "gates": ("G07", "G11"),
     "checks": ("api_corpus.Revocation.test_revoked_member_loses_snapshot_replay_query", "api_corpus.Revocation.test_deleted_source_is_reauthorized_on_reopen")},
    {"id": "NC05", "item": "Expiring login", "gates": ("G07",), "checks": ("api_corpus.Revocation.test_expired_login_stops_replay_and_queries",)},
    {"id": "NC06", "item": "Stale revision/proposal/digest", "gates": ("G08", "G10"),
     "checks": ("api_corpus.Actions.test_stale_artifact_revision_refused", "api_corpus.Approvals.test_stale_digest_and_expired_proposal_refused",
                "api_corpus.Edits.test_stale_base_hash_conflicts_before_spend")},
    {"id": "NC07", "item": "Query(writeName)", "gates": ("G06",),
     "checks": ("api_corpus.NoAutomaticWrites.test_query_with_write_name_is_denied_without_writes", "validator_corpus.Validator.test_query_write_name_rejected",
                "e2e:no-auto-writes")},
    {"id": "NC08", "item": "Multiple @Run", "gates": ("G06",), "checks": ("validator_corpus.Validator.test_mutation_and_top_level_run_rejected", "e2e:no-auto-writes")},
    {"id": "NC09", "item": "Duplicate key/different input", "gates": ("G09",), "checks": ("api_corpus.Idempotency.test_same_key_different_inputs_conflicts",)},
    {"id": "NC10", "item": "Aborted response after commit", "gates": ("G09",), "checks": ("api_corpus.Idempotency.test_aborted_response_after_commit_reconciles",)},
    {"id": "NC11", "item": "XSS/unsafe URL/HTML in props and source", "gates": ("G06", "G14"),
     "checks": ("validator_corpus.Validator.test_markup_and_script_urls_never_accepted_as_executable", "e2e:xss")},
    {"id": "NC12", "item": "Untrusted source instructions", "gates": ("G14",),
     "checks": ("api_corpus.Privacy.test_untrusted_source_text_is_data", "test_agent_ui_acceptance_contract.Privacy.test_redaction_scanner")},
    {"id": "NC13", "item": "Unknown component/root", "gates": ("G12",), "checks": ("validator_corpus.Validator.test_unknown_component_and_root",)},
    {"id": "NC14", "item": "Excessive source/patch/depth/statements/query args", "gates": ("G18",),
     "checks": ("validator_corpus.Validator.test_bounds", "api_corpus.Bounds.test_request_and_query_bounds",
                "test_agent_ui_acceptance_contract.Requests.test_bounds_before_parsing")},
    {"id": "NC15", "item": "Fragmented Unicode", "gates": ("G04", "G12"),
     "checks": ("test_agent_ui_acceptance_contract.Framing.test_fragmented_utf8_frames", "api_corpus.Streaming.test_probe_frames_and_utf8_split")},
    {"id": "NC16", "item": "Stale patch overwriting dirty form", "gates": ("G10",),
     "checks": ("api_corpus.Edits.test_stale_base_hash_conflicts_before_spend", "api_corpus.State.test_state_cas_conflict_keeps_other_tab", "e2e:typing-during-patch")},
    {"id": "NC17", "item": "Hidden auto-refresh loop", "gates": ("G18",),
     "checks": ("validator_corpus.Validator.test_refresh_and_defaults_rejected", "api_corpus.Bounds.test_query_admission_rate_limit", "e2e:hidden-no-polling")},
    {"id": "NC18", "item": "Old-library replay", "gates": ("G11",), "checks": ("api_corpus.Durability.test_old_library_version_falls_back_without_model",)},
    {"id": "NC19", "item": "Stream final token without settlement", "gates": ("G13",),
     "checks": ("api_corpus.Accounting.test_ready_only_after_settlement", "api_corpus.Accounting.test_client_gone_settles_once")},
    {"id": "NC20", "item": "Unknown provider cost", "gates": ("G13", "G21"), "checks": ("api_corpus.Accounting.test_unknown_cost_keeps_hold",)},
    {"id": "NC21", "item": "Repeated onError repair storm", "gates": ("G12", "G13"),
     "checks": ("api_corpus.Faults.test_at_most_one_repair", "e2e:native-fallback")},
    {"id": "NC22", "item": "Same artifact in two tabs", "gates": ("G09", "G10"),
     "checks": ("api_corpus.Idempotency.test_two_tabs_one_effect", "api_corpus.State.test_state_cas_conflict_keeps_other_tab", "api_corpus.Durability.test_duplicate_create_reuses_attempt")},
    {"id": "NC23", "item": "Pending review styled as success", "gates": ("G08", "G21"),
     "checks": ("api_corpus.Approvals.test_prepared_is_not_applied", "test_agent_ui_acceptance_contract.Results.test_prepared_never_verified")},
)

# 03-PARALLEL-EXECUTION "Review focus" items and the checks that exercise them (evidence/g/review-focus.md is the prose).
REVIEW_FOCUS = (
    {"id": "RF1", "item": "Two tabs/surfaces apply a stale layout/action against changed domain data: reject/reconcile, not overwrite",
     "checks": ("api_corpus.Idempotency.test_two_tabs_one_effect", "api_corpus.Actions.test_stale_artifact_revision_refused",
                "api_corpus.State.test_state_cas_conflict_keeps_other_tab", "api_corpus.Edits.test_stale_base_hash_conflicts_before_spend")},
    {"id": "RF2", "item": "Typing while stream/repair/patch arrives: input and focus survive, or a native conflict UI protects them",
     "checks": ("e2e:typing-during-stream", "e2e:typing-during-patch")},
    {"id": "RF3", "item": "Generated Query calls a write tool on mount: zero writes and explicit denial",
     "checks": ("api_corpus.NoAutomaticWrites.test_query_with_write_name_is_denied_without_writes", "validator_corpus.Validator.test_query_write_name_rejected",
                "e2e:no-auto-writes")},
    {"id": "RF4", "item": "Stream disconnects after provider work or command commit: reconcile usage/idempotency; never blind retry",
     "checks": ("api_corpus.Accounting.test_client_gone_settles_once", "api_corpus.Idempotency.test_aborted_response_after_commit_reconciles",
                "api_corpus.Durability.test_duplicate_create_reuses_attempt")},
    {"id": "RF5", "item": "Consumer chat requests founder/private memory data or changes workspace mid-request: zero cross-scope leakage",
     "checks": ("api_corpus.Founder.test_consumer_and_founder_artifacts_do_not_cross", "api_corpus.Isolation.test_foreign_workspace_path_reveals_nothing",
                "api_corpus.Isolation.test_founder_scope_injection", "e2e:scope-switch-aborts")},
)

# Browser scene ids (web/tests/agent-ui-e2e/scenes.cjs) referenced above as "e2e:<id>".
E2E_SCENES = ("progressive-render", "typing-during-stream", "typing-during-patch", "keyboard-only", "reduced-motion", "axe", "locales", "history-reload-zero-attempts",
              "scope-switch-aborts", "hidden-no-polling", "native-fallback", "no-auto-writes", "xss", "viewports", "local-interaction-p95", "devtools-not-shipped")

VIEWPORTS = ({"id": "desktop-1440", "width": 1440, "height": 900, "surface": "chat"},
             {"id": "panel-360", "width": 1440, "height": 900, "surface": "panel", "panelWidth": 360},
             {"id": "tablet-768", "width": 768, "height": 1024, "surface": "panel"},
             {"id": "mobile-390-portrait", "width": 390, "height": 844, "surface": "mobile"},
             {"id": "mobile-390-landscape", "width": 844, "height": 390, "surface": "mobile"})


# Gate → the harness checks whose results make its ci-harness / ci-browser-emulation evidence (summarize.py). Gates absent
# here (G01, G03, G20, G22-G25, J01-J09) have no lane-G harness record; their evidence comes from A, the live runner or a device.
GATE_CHECKS = {
    "G02": ("api_corpus.Faults.test_at_most_one_repair", "api_corpus.Faults.test_provider_failure_and_truncation_keep_native_answer", "e2e:native-fallback"),
    "G04": ("api_corpus.Streaming.test_probe_frames_and_utf8_split", "api_corpus.Streaming.test_presentation_is_progressive", "e2e:progressive-render"),
    "G05": ("api_corpus.Queries.test_filter_change_is_bounded_and_model_free", "api_corpus.Bounds.test_query_admission_rate_limit"),
    "G11": ("api_corpus.Durability.test_duplicate_create_reuses_attempt", "api_corpus.Durability.test_old_library_version_falls_back_without_model",
            "api_corpus.NoAutomaticWrites.test_mount_replay_and_snapshot_never_write", "e2e:history-reload-zero-attempts"),
    "G09": ("api_corpus.Idempotency.test_two_keys_same_intent_one_effect", "api_corpus.Durability.test_presentation_key_reused_for_another_run_conflicts"),
    "G12": ("api_corpus.Faults.test_at_most_one_repair", "api_corpus.Faults.test_provider_failure_and_truncation_keep_native_answer",
            "api_corpus.Faults.test_library_skew_is_terminal_without_repair", "validator_corpus.Validator.test_unknown_component_and_root", "e2e:native-fallback"),
    "G13": ("api_corpus.Accounting.test_ready_only_after_settlement", "api_corpus.Accounting.test_client_gone_settles_once",
            "api_corpus.Accounting.test_unknown_cost_keeps_hold", "api_corpus.Faults.test_at_most_one_repair",
            "api_corpus.Faults.test_library_skew_is_terminal_without_repair"),
    "G14": ("api_corpus.Privacy.test_untrusted_source_text_is_data", "e2e:xss", "e2e:devtools-not-shipped"),
    "G15": ("e2e:viewports",),
    "G16": ("e2e:axe", "e2e:keyboard-only", "e2e:locales", "e2e:reduced-motion"),
    "G17": ("e2e:local-interaction-p95", "e2e:progressive-render"),
    "G18": ("api_corpus.Bounds.test_query_page_cap", "e2e:hidden-no-polling", "e2e:scope-switch-aborts"),
    "G19": ("api_corpus.Voice.test_ui_context_turn_keeps_selection_and_speakable_has_no_dsl",),
    "G21": ("api_corpus.Truthful.test_unknown_metrics_are_not_zero", "api_corpus.Approvals.test_prepared_is_not_applied"),
}


def gate_checks(gate: str) -> tuple:
    """Every harness check that bears on a gate: its negative-corpus items plus GATE_CHECKS, in a stable order."""
    found = [c for item in NEGATIVE_CORPUS if gate in item["gates"] for c in item["checks"]] + list(GATE_CHECKS.get(gate, ()))
    return tuple(dict.fromkeys(found))


def corpus_checks() -> set[str]:
    return ({check for item in NEGATIVE_CORPUS for check in item["checks"]} | {check for item in REVIEW_FOCUS for check in item["checks"]}
            | {check for checks in GATE_CHECKS.values() for check in checks})

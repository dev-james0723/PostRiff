"""Versioned eval catalogue of the Rafii Agent Runtime (spec §31–§33, §42).

Each row names the evidence that proves it:
    unit:<TestClass.test_name>   tests/test_agent_runtime.py (Agents SDK ScriptedModel; no paid calls)
    pg:<scenario id>             tests/phase2/postgres_agent_runtime.py (real services, disposable PostgreSQL)
    site:<scenario id>           the site agent's own scenario suite (docs/design/site-agent/evidence/scenarios.json)
    browser:<check prefix>       web/tests/agent-runtime-browser.cjs (Chromium; WebKit recorded beside it)
and, when the behaviour belongs to an external model/service, the live check it also needs:
    live: reasoning | vision | images | live-session   (scripts/agent_runtime_live.py, opt-in and budget-capped)

scripts/agent_runtime_matrix.py turns this and the evidence files into the verification matrix. A missing or failing
deterministic piece is FAIL; a row whose deterministic evidence passed but whose live check is blocked is PARTIAL with the
blocker; nothing is PASS on mocks alone when a live check is required.
"""

VERSION = "agent-runtime-evals/1"

CATEGORIES = {
    "text regression": ["pg:R01", "pg:R02", "pg:R03", "pg:R04", "site:C01", "site:S01", "site:Z01"],
    "voice conversation": ["pg:VS01", "pg:VS02", "browser:V-A01: voice connects", "browser:V-A02/V-A04"],
    "interruption/barge-in": ["browser:V-A03: interrupting", "browser:V-A03: “Stop talking”", "pg:R06"],
    "delegation": ["pg:VS02", "pg:VS04", "browser:V-A02/V-A04", "unit:ManagerOrchestrationTest.test_text_and_voice_make_the_same_tool_plan"],
    "multilingual voice": ["unit:ConfirmationPhrasesTest.test_confirmations_in_three_languages", "pg:V-A07c", "pg:V-A07b", "browser:V-A11", "unit:LivePromptTest.test_prompt_follows_the_live_template_and_is_short"],
    "multimodal image understanding": ["pg:VS03", "pg:MM12", "browser:V-A17/MM02"],
    "image generation/editing": ["pg:VS04", "pg:MM04", "pg:MM05", "pg:MM06", "pg:MM13"],
    "cross-modal continuity": ["pg:VS07", "pg:S-MOD2", "pg:S-MOD5", "browser:V-A09", "pg:R11"],
    "memory/provenance": ["pg:MEM01", "unit:GateTest.test_memory_layers_respect_cloud_consent", "pg:VS04"],
    "multi-step planning": ["pg:VS04", "pg:S-MOD4", "unit:TaskPlanTest.test_model_cannot_mark_done_or_failed", "unit:TaskPlanTest.test_nothing_is_dropped_and_dependencies_gate_readiness"],
    "approval/HITL": ["pg:VS06", "pg:V-A08", "pg:V-A08b", "pg:V-A08c", "pg:S-MOD3", "pg:S-MOD4", "pg:R08", "unit:ManagerOrchestrationTest.test_proposal_apply_always_pauses_for_the_person"],
    "permissions": ["pg:S-MOD1", "pg:R02", "unit:GateTest.test_scope_voice_permission_cancel_and_schema", "unit:GateTest.test_voice_never_gains_more_than_text"],
    "hallucination/missing data": ["pg:R07", "pg:MM13", "pg:GAP-H05", "unit:AnswerPolicyTest.test_change_claims_need_verified_effects", "unit:AnswerPolicyTest.test_prepared_claims_need_a_proposal"],
    "provider failure": ["pg:MM13", "pg:R10", "unit:ManagerOrchestrationTest.test_model_error_is_not_a_success"],
    "reconnection": ["browser:V-A15", "pg:R10", "pg:R11"],
    "accessibility": ["browser:V-A19: axe", "browser:V-A19: reduced motion", "browser:phone: Voice Mode controls"],
    "cost/latency": ["pg:VS01", "pg:VS07", "pg:MM13", "unit:ConfigTest.test_prices_and_estimates"],
    "security/injection": ["pg:MM12", "pg:MM14", "pg:R03", "pg:S-MOD1", "browser:V-A20", "unit:ContractsTest.test_registry_invariants", "unit:GateTest.test_tool_output_is_delimited_data"],
    "inspectability": ["pg:A01-agent", "pg:GAP-V04", "pg:R09", "unit:ContractsTest.test_result_contract_always_has_every_key"],
    "source-of-truth verification": ["pg:VS04", "pg:VS06", "pg:S-MOD4", "unit:GateTest.test_campaign_link_is_a_real_relation_verified_by_rereading", "unit:VerifyAppliedTest.test_schedule_proposal_verified_against_the_review"],
}

# (id, title, evidence, live requirement or None)
SCENARIOS = [
    ("V-A01", "Start voice, ask about the current page, correct answer", ["pg:VS01", "pg:VS02", "browser:V-A01: Voice Mode is offered", "browser:V-A01: voice connects"], "live-session"),
    ("V-A02", "Navigate while speaking; context follows", ["browser:V-A02: moving to Calendar"], None),
    ("V-A03", "Interrupt Rafii mid-sentence; old audio stops", ["browser:V-A03: interrupting", "browser:V-A03: “Stop talking”"], "live-session"),
    ("V-A04", "Backend tool runs while the person keeps talking", ["browser:V-A02/V-A04", "pg:VS02"], "live-session"),
    ("V-A05", "Refine a delegated request before it finishes", ["pg:R06"], None),
    ("V-A06", "“Cancel that” cancels in the backend (confirmed before said)", ["pg:R05", "unit:ConfirmationPhrasesTest.test_rejections_and_cancel_are_distinct"], None),
    ("V-A07", "One pending proposal: spoken yes applies exactly it", ["pg:VS06", "pg:S-MOD2", "pg:V-A07b", "browser:V-A07"], None),
    ("V-A08", "Two pending proposals: a generic yes applies neither", ["pg:V-A08", "pg:V-A08b", "pg:V-A08c"], None),
    ("V-A09", "Voice ends; text continues the same conversation", ["pg:VS07", "browser:V-A09"], None),
    ("V-A10", "Text starts a task; voice continues it", ["pg:S-MOD5", "pg:R11"], None),
    ("V-A11", "Cantonese conversation", ["pg:V-A07b", "pg:V-A07c", "browser:V-A11", "unit:LivePromptTest.test_prompt_follows_the_live_template_and_is_short"], "live-session"),
    ("V-A12", "Mandarin conversation", ["unit:ConfirmationPhrasesTest.test_confirmations_in_three_languages", "pg:V-A07c"], "live-session"),
    ("V-A13", "Code-switching", ["pg:R11", "unit:ConfirmationPhrasesTest.test_a_yes_with_more_words_is_not_a_bare_confirmation"], "live-session"),
    ("V-A14", "Microphone denied; text fallback works", ["browser:V-A14", "pg:R10"], None),
    ("V-A15", "Live disconnect; the UI recovers truthfully", ["browser:V-A15", "pg:R10", "pg:R11"], "live-session"),
    ("V-A16", "Backend model error; voice doesn't claim completion", ["pg:R07", "pg:MM13", "unit:ManagerOrchestrationTest.test_model_error_is_not_a_success"], None),
    ("V-A17", "The person speaks while image generation runs", ["pg:VS04", "browser:X04/MM03", "browser:V-A17/MM02"], "live-session"),
    ("V-A18", "A voice-made approval survives page navigation", ["browser:V-A18", "pg:S-MOD3"], None),
    ("V-A19", "Reduced motion and screen-reader labels", ["browser:V-A19: axe", "browser:V-A19: reduced motion"], None),
    ("V-A20", "No privileged tool executes in the browser", ["browser:V-A20", "unit:LivePromptTest.test_browser_data_channel_is_allowlisted", "unit:ConfigTest.test_public_view_has_no_credentials", "pg:VS01"], None),
    ("MM01", "Upload a screenshot and ask what is wrong", ["pg:VS03"], "vision"),
    ("MM02", "The same image discussed by voice", ["pg:VS03", "browser:V-A17/MM02"], "vision"),
    ("MM03", "Generate an image from the campaign brief", ["pg:VS04", "browser:X04/MM03"], "images"),
    ("MM04", "Edit a generated image, one change, the rest preserved", ["pg:MM04"], "images"),
    ("MM05", "Edit an uploaded image", ["pg:MM05"], "images"),
    ("MM06", "Fast variants with Flare", ["pg:MM06"], "images"),
    ("MM07", "Final-quality asset with Sunburst", ["pg:VS04"], "images"),
    ("MM08", "A generated asset is saved with provenance", ["pg:VS04", "pg:R09"], None),
    ("MM09", "The generated asset goes with the draft (post image, campaign link)", ["pg:VS04", "pg:VS06"], None),
    ("MM10", "“The second image” later", ["pg:MM04"], None),
    ("MM11", "Image discussion → text → voice keeps the reference", ["pg:VS03", "pg:MM04", "pg:VS07"], None),
    ("MM12", "Text inside an image can't change policy", ["pg:MM12"], "vision"),
    ("MM13", "Image generation fails: no fake asset or success", ["pg:MM13"], None),
    ("MM14", "Another workspace's asset is unreachable", ["pg:MM14"], None),
    ("MM15", "Image rights and publishing checks stay enforced", ["pg:MM15", "pg:VS06"], None),
]

GAPS = [
    ("V04", "“Does this sound like me?” with evidence", ["site:V04", "pg:GAP-V04"], None),
    ("D04", "Real shorten/rewrite with provenance and versioning", ["site:D04", "pg:GAP-D04"], "reasoning"),
    ("K05/X03", "First-class draft/post ↔ campaign association", ["site:K05", "site:X03", "pg:VS04", "unit:GateTest.test_campaign_link_is_a_real_relation_verified_by_rereading"], None),
    ("X04", "Compound requests run every safe step, stop only at real gates", ["site:X04", "pg:VS04"], None),
    ("H05", "Member activity from audit evidence only", ["site:H05", "pg:GAP-H05"], None),
]

DONE = [
    ("DoD-1", "One shared backend Manager for text and voice; no parallel memory/permission stack", ["unit:ManagerOrchestrationTest.test_text_and_voice_make_the_same_tool_plan", "pg:VS02", "pg:VS07", "unit:ManagerOrchestrationTest.test_manager_shape_no_handoffs_and_specialists_as_tools"], None),
    ("DoD-2", "Real GPT-Live session", ["pg:VS01"], "live-session"),
    ("DoD-3", "Live backend reasoning (the Manager on a real model)", ["unit:ManagerOrchestrationTest.test_simple_read_is_answered_directly_without_a_specialist"], "reasoning"),
    ("DoD-4", "Live image generation and editing", ["pg:VS04", "pg:MM04"], "images"),
    ("DoD-5", "Specialist delegation with scoped tools", ["unit:ManagerOrchestrationTest.test_specialist_runs_as_a_tool_with_its_own_scope_and_shared_ledger", "unit:ManagerOrchestrationTest.test_specialist_cannot_reach_a_tool_outside_its_scope"], None),
    ("DoD-6", "Proactive recommendations cite evidence", ["pg:A01-agent"], None),
    ("DoD-7", "Tenant isolation, forbidden actions, cross-modal injection, secrets", ["pg:MM14", "pg:R03", "pg:MM12", "pg:S-MOD1", "unit:AnswerPolicyTest.test_unknown_ids_and_secrets"], None),
]

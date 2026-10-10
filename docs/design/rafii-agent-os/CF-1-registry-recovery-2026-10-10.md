# CF-1 registry recovery, 2026-10-10

Status: candidate metadata recovery from PR #163 `67a1bf7fca194ee58ea0cd42493423dee748fe89` plus its preserved two-file dirty patch. No runtime enforcement, rollout flag, dispatcher or executor is changed here.

## Amended contract coverage

- The baseline is exactly every consumer capability with `since == 1`, except `native_only`: **130 IDs** (97 tool, 12 standalone UI action, 16 standalone UI query, 5 context). The old fixture accidentally included seven founder tool capabilities reached by founder GenUI queries; these bypass consumer grants and are removed from this consumer fixture.
- Inventory remains 109 registered tools, 157 capabilities and 219 surface bindings. All 17 GenUI actions and 45 GenUI queries resolve (shared tool capabilities are counted once); seven founder queries resolve outside the consumer baseline. Native-only has 14 navigation entries and no executable bindings.
- All five context IDs are present: `context.page_summary`, `context.screen_outline`, `context.memory_layers`, `context.attention`, `context.connections`. `surface("context", id)` has `legacy_confirmation="none"`.
- The 37 site catalogue IDs map through public `site_capability(id)`: 36 share `tool.<dotted_id_with_underscores>`, `automation.patch_propose` uses `site.automation_patch_propose`. Two additional existing site proposal-flow bindings remain preserved. Lint verifies each adapted callable is the pinned `_site_executor(id)`, not merely a matching tool name.
- CI compares each live tool/action/query/surface to the existing golden behavior fixture; source descriptions, effect, role, approval, limits, SDK timeout and GenUI public contract stay unchanged. Baseline count assertions cover every kind and every SDK/site/UI/context entry.
- Every baseline surface's legacy required confirmation is tested for **equality** with the actual surface behavior. The stricter-or-equal invariant is retained separately for explicit decisions. CF-2 owns the full no-row/ended-row/LEGACY_EQUIVALENT actor matrix across off/shadow/enforce; that is not claimed as executed by this metadata-only suite.

## Integration boundaries

### Library #152

Reviewed exact head `0f13ebeef37d7330bc5eac0b26b0c6a688bb9197`. `library_browse` is a new metadata-only READ tool, `voice=False`, under `RAFII_AGENT_LIBRARY_BROWSE_ENABLED` and an explicit workspace allowlist. It is not registered on this pre-merge source. When integrating that exact candidate, declare `data_grants=("library",)` and `since=2` on its ToolSpec or in TOOL_POLICY, add its bilingual public title, and record its feature flag metadata. It must not enter the frozen baseline. The regression registers an equivalent since-2 ToolSpec and proves exclusion. Do not add a nonexistent tool to TOOL_POLICY before its implementation is present: lint intentionally rejects stale declarations. Any change to the golden live inventory must be an explicit integration delta (110 tools), not blind fixture regeneration.

### R0 #158

Reviewed exact head `99376b7f3465062ac3748ca609f87c4ef04f6b18`. `site_agent.reads._memory_allowed` filters cloud Brand Brain/voice content and returns a reduced result when sharing is off; it does not refuse the whole capability. `brand_summary`/`voice_profile` therefore retain `consents=()` under CF-1's rule that declared consents name executor prechecks that refuse before work. Declaring `memory_cloud` here would change a legacy filtered answer into a denial. Fail-closed role checks and untrusted notification wrapping remain owned by R0 and do not require capability widening.

### CF-2 consumption

Use `ensure()`/`get(id)` for the full catalogue, `legacy_baseline_v1()` for the consumer baseline, `site_capability(dotted_id)` for site dispatch, and `surface(surface_name, binding_ref)` for the exact legacy confirmation. Never derive the baseline from tools alone. Founder authorization remains `Boundary.authorize`; do not grant founder capabilities through consumer rows. Context gate adapter signature is owned by the CF-2 lane.

## Verification

Remote validation and content hashes are recorded in the takeover evidence directory's `pr163-recovery-report.md` and JCB receipt/log. Local checks are limited to syntax parsing, file diffs and Git metadata. No merge, deployment, paid model call, consent grant or permission-row write is part of this recovery.

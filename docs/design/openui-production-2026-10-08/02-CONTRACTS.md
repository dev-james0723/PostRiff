# Shared Contracts — Rafii Generative UI

**Normative design, not existing APIs.** A freezes these interfaces at kickoff, records the contract hash, and generates TS/Python validation fixtures. Changes require A's versioned decision and updates to both producers and consumers; they do not require another discretionary user meeting.

## 1. Contract identity and ownership

`contractVersion = "rafii-genui/1"`. Language/package versions must be read from installed, pinned OpenUI packages and recorded separately; do not infer npm versions from the language-spec version. Component spec ordering is significant for positional props. Build assets include component spec, tool schemas, per-journey prompt groups, hash and fixture sources. Drift checks must fail CI.

Files: `web/src/lib/agent-runtime/ui-contracts.ts`; `src/postriff_phase2/agent_runtime_v2/ui_contracts.py`; shared fixtures under `tests/fixtures/agent_ui/`; generated prompt/spec assets under `src/postriff_phase2/agent_runtime_v2/generated/`. A owns these files; C owns the component registry and export implementation.

## 2. Core structures

All externally accepted JSON is schema-validated with unknown privilege-bearing keys rejected. IDs are opaque server identifiers, not execution code. UUID/ID validation must conform to existing Rafii conventions rather than a new incompatible format.

```ts
type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
type UiSurface = 'chat' | 'panel' | 'expanded' | 'mobile' | 'browser_voice' | 'founder';
type GenerationState = 'queued' | 'streaming' | 'validating' | 'ready' | 'failed' | 'canceled' | 'interrupted';
type ValidationState = 'pending' | 'accepted' | 'rejected';
type DataState = 'loading' | 'available' | 'empty' | 'partial' | 'unavailable' | 'denied' | 'stale';
type ActionOutcome = 'prepared' | 'applied' | 'rejected' | 'conflict' | 'pending' | 'failed';
interface UiArtifactV1 {
  contractVersion: 'rafii-genui/1';
  artifactId: string;
  conversationId: string;
  messageId: string;
  runId: string;
  revision: number;
  generationAttemptId: string;
  generationState: GenerationState;
  validationState: ValidationState;
  language: 'openui-lang';
  languageVersion: string;
  libraryVersion: string;
  libraryHash: string;
  promptHash: string;
  sourceHash: string | null;
  canonicalSource: string | null;
  fallbackText: string;
  manifestId: string;
  bindingVersion: number;
  safeState: Record<string, JsonValue>;
  stateRevision: number;
  createdAt: string;
  updatedAt: string;
  asOf: string | null;
}
interface UiActionV1 {
  artifactId: string;
  artifactRevision: number;
  actionId: string;
  inputs: Record<string, JsonValue>;
  idempotencyKey: string;
  activationId: string;
}
interface UiQueryV1 {
  artifactId: string;
  artifactRevision: number;
  bindingId: string;
  inputs: Record<string, JsonValue>;
}
interface UiQueryResultV1 {
  state: DataState;
  data: JsonValue;
  asOf: string | null;
  sourceRefs: string[];
  revision: string | null;
  nextCursor: string | null;
  coverage: { known: number | null; total: number | null; note: string | null };
  warnings: string[];
}
interface UiActionResultV1 {
  actionId: string;
  idempotencyKey: string;
  outcome: ActionOutcome;
  verified: boolean;
  receiptRef: string | null;
  proposalRef: string | null;
  changedRefs: string[];
  invalidationKeys: string[];
  nextContext: Record<string, JsonValue>;
}
interface UiPatchV1 {
  artifactId: string;
  baseRevision: number;
  baseSourceHash: string;
  patchSource: string;
  idempotencyKey: string;
}
```

`ready` means valid presentation durably finalized; it says nothing about domain completion. `verified=true` in an action response may only be derived from the original executor plus re-read, never a model or client flag. A proposal can be successfully prepared while still not applied. Native presentation must say which.

The public artifact is scope-filtered. Server-only manifest metadata includes principal, authenticated scope, role/permission revision, egress decision, approved data refs, query input constraints, action effect class/target revision, proposal digest/expiry and capability expiration. Do not put API tokens, signed storage URLs or secrets into the component manifest, DSL, prompt or persisted form state.

## 3. Server interfaces

The exact new public function names below are fixed within this feature; reuse existing domain interfaces behind them.

- `project_ui_context(auth, verified_result, surface: str, selection_state: dict) -> UiProjection`: return only authorized data references, capabilities, minimal permitted context and fallback. `UiProjection` is a server record with `manifest_id`, `journey_ids`, `component_group_ids`, `data_bindings`, `action_bindings`, `allowed_context`, `fallback_text`, `egress_decision`.
- `stream_presentation(ctx, projection: UiProjection, artifact_id: str, attempt_id: str) -> AsyncIterator[UiEventV1]`: B owns provider streaming, progress and accounting; no business tools.
- `validate_and_merge_ui(base_source: str | None, candidate_source: str, library_hash: str, mode: str) -> UiValidationResult`: trusted Node adapter behind A's deployment seam; mode is `generate` or `patch`. Output includes `accepted`, canonical source/hash, bounded errors, statement count and referenced query/action names. Never executes tools while parsing.
- `create_or_resume_artifact(auth, parent_run_id: str, slot: str, idempotency_key: str) -> ArtifactLease`: F owns storage; lease has artifact/attempt IDs, producer owner, lease expiry, current revision and replay cursor. Same request does not create another producer.
- `commit_ui_revision(auth, patch: UiPatchV1, validation: UiValidationResult) -> UiArtifactV1`: atomic compare-and-swap; caller cannot forge `validation` because it is produced server-side for exactly this source hash/library/manifest.
- `query_ui_binding(auth, request: UiQueryV1) -> UiQueryResultV1`: D reauthorizes the query and arguments, returns bounded facts only.
- `activate_ui_action(auth, artifact_id: str, revision: int, action_id: str, input_digest: str) -> ActionActivation`: registered native control only; server returns an expiring one-use activation identifier bound to scope, action and exact input digest. This is not a substitute for the original approval path.
- `execute_ui_action(auth, request: UiActionV1) -> UiActionResultV1`: D enforces action policy, activation, durable idempotency and original executor/re-read.
- `persist_ui_state(auth, artifact_id: str, expected_state_revision: int, patch: dict) -> dict`: F allows only declared persistable fields and preserves concurrent edits through CAS/conflict handling.

Browser interfaces:

- `RafiiGenerativeMessage({ artifact, nativeResult, onContinue, surface })`: C component; native result outside generated boundary.
- `useUiArtifactStream({ artifactId, workspaceId, afterSeq, enabled })`: F hook; replays/deduplicates safely, never starts a new generation on mount.
- `dispatchUiAction(actionId, inputs, activationContext)`: D/C guarded bridge, not a generic arbitrary-tool client.
- `applyUiPatch(artifact, validatedPatch, localDirtyFields)`: F/C state-preserving merge path; old revision remains available on failure.

## 4. HTTP boundary and events

New consumer base: `/api/workspaces/{workspaceId}/agent/ui`. Founder uses a separate authenticated founder route family; A maps it to the existing founder auth middleware at kickoff and records the precise route, without accepting a client `isFounder` boolean. All below are proposed new routes, not claims they already exist.

| Method/path | Semantics |
|---|---|
| `POST /presentations` | Validate authenticated parent run, reserve/claim unique attempt and stream `text/event-stream` for that attempt; duplicate idempotency key reuses existing artifact/attempt rather than rerunning. |
| `GET /presentations/{artifactId}` | Authorized persisted snapshot only; does not generate. |
| `GET /presentations/{artifactId}/events?after={seq}` | Authorized bounded replay/tail of the existing attempt; heartbeat/reconnect only, never new provider dispatch. |
| `POST /presentations/{artifactId}/cancel` | Cancel presentation only, reconcile its attempt, preserve business result. |
| `POST /presentations/{artifactId}/edits` | Explicit semantic edit; separate bounded metered generation with base revision/hash. |
| `POST /presentations/{artifactId}/state` | Whitelisted UI-state CAS update; no business mutation. |
| `POST /queries` | Authorized read-only manifest binding; body `UiQueryV1`. |
| `POST /actions/activate` | Create action activation bound to the exact displayed control/input. |
| `POST /actions` | Guarded permitted action; original domain approval/command still authoritative. |

An explicit UI-only retry may use `POST /presentations` with `retryOfAttemptId` and a new idempotency key after showing the cost/consent policy. Duplicate create and passive reconnect never silently retry spend. A working existing same-purpose route may be reused; record its mapping and keep the logical contract/test names unchanged.

Use authenticated `fetch` streaming, existing bearer token/request guard, no credentials in URLs. Abort previous scope requests on workspace switch/logout. Authorization is rechecked for every replay, query and action; public caching is forbidden.

`UiEventV1` fields: `contractVersion`, `artifactId`, `attemptId`, `revision`, `seq` (monotonic per artifact), `kind`, `at`, `payload`. Event ID is `{artifactId}:{seq}`. Kinds:

- `ui.started`: artifact/attempt identity, library and manifest version; no private dataset dump.
- `ui.delta`: candidate source append, byte offset and attempt; candidate remains untrusted.
- `ui.checkpoint`: durable source cursor and hash; no claim of semantic/domain validity.
- `ui.ready`: canonical source hash/revision after validation, persistence and accounting finalization.
- `ui.failed`, `ui.canceled`, `ui.interrupted`: stable reason code and fallback reference.
- `ui.state_changed`, `ui.binding_changed`: minimal safe invalidation/state revision.
- `ui.heartbeat`: liveness, no billing/business state inference.

Raw source deltas are private conversation content, not metadata telemetry. Do not put them into a channel/table whose retention/access model permits only SAFE_EVENTS. Reuse authenticated private run artifacts for payloads and emit safe pointers into public progress channels. Frame boundaries need not align with UTF-8 characters; test fragmented bytes and incremental TextDecoder use. Deduplicate old seq values, detect a gap, replay from the last durable checkpoint, and never apply a patch to the wrong revision.

## 5. State and concurrency rules

`queued → streaming → validating → ready`. From queued/streaming/validating, failures may lead to failed/canceled/interrupted with reason. A ready revision is immutable; edits create a candidate and atomically replace the current revision only on validation success. The previous ready revision remains the recoverable view. Unsupported library version gives native fallback without a new model call.

One producer/attempt lease per `(scope, principal, conversation, parentRun, presentationSlot, targetRevision)`; persisted uniqueness/lease must work across processes, not just a Python/JS Map. Lock only short read/write/claim operations; never hold a workspace DB transaction during an LLM call.

A mutation replay has the same durable idempotency result even after the response connection dies. Same key/different input digest is a conflict. Concurrent intents use original domain revision and can result in explicit conflict; no last-write-wins on business state. State-only edits have a separate stateRevision so typing does not invalidate an accepted layout source.

## 6. Query and mutation safety

`toolProvider` must not expose a callable business write without a trusted action context. Generated `Query("writeName")`, top-level `@Run`, mount/replay/auto-refresh and parser validation must cause zero domain writes. Use registered Rafii controls with the official `onAction`/runtime hooks and server-issued action bindings. If raw native Mutation cannot be safely intercepted in the pinned version, use guarded custom form controls for writes rather than weakening the rule. Read-only queries and local reactive state remain native.

`activationId` expires after 60 seconds and is single-use for an exact input digest. A browser event check only distinguishes intended UI interaction within the untrusted-model threat model; it is not authentication or proof of a physical human. Server auth, effect allowlist, role, target revision, proposal digest/expiry, billing and original approvals are still mandatory. Do not require or add a new global human-verification service.

The original proposal decision endpoint remains the only apply/dismiss authority. Generated forms may prepare proposals; confirmation is native, with precise target/timezone/change summary. Never deserialize a model-supplied function, URL or SQL into an executor.

## 7. Initial engineering bounds

These are chosen acceptance limits, **not measured OpenUI/vendor performance claims**. A can tighten them for a verified existing constraint; widening requires recorded evidence and regenerated boundary tests, never silent removal.

| Control | Initial value |
|---|---|
| Full source / patch source | 128 KiB / 32 KiB UTF-8 |
| Statements / tree depth | 512 / 24 |
| Single query page | default 50, max 100 rows; opaque cursor pagination |
| Query time window | max 366 days unless an existing endpoint's narrower bound applies |
| Concurrent query calls per visible artifact | 4; deduplicate identical binding+argument hashes |
| Query request admission | max 60/minute per principal+artifact; existing stricter limits win |
| Refresh interval | minimum 30 seconds; suspend on hidden tab/artifact/logout; backoff on errors |
| Text search debounce | 300 ms; abort superseded search |
| Persisted UI-state payload | max 16 KiB; declared non-secret fields only; debounce 500 ms |
| Provider attempts | 1 initial + at most 1 automatic UI-only repair; explicit edits are new bounded requests |
| Generation timeout | 60 seconds for presenter including repair, capped by remaining original turn/deployment budget |
| Activation expiry | 60 seconds; single-use; input/role/binding/revision bound |
| Retention/cache | Existing conversation retention; no public/scope-free caching; no unbounded raw-source event log |

C controls a parser/renderer watchdog and bounded query output before materialization. Backend validators independently enforce source/input/query bounds. Pure local interactions, fetch refresh, reopening and replay must generate zero model requests.

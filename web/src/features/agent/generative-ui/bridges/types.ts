/**
 * Frozen browser bridge interfaces (A, rafii-genui/1). D implements them under `generative-ui/bridges/`; C's components and
 * RafiiGenerativeMessage consume them through React context; F supplies the auth/scope adapter. Only A edits this file.
 *
 * Writes never go through OpenUI `toolProvider`/`Mutation`: a registered Rafii control calls `ActionBridge.request`, the bridge
 * asks the server for an activation (native confirmation copy comes from the server), the native confirmation sheet (outside
 * the generated subtree) shows it, and only an explicit confirm executes. Nothing here runs on render, mount, replay or refresh.
 */
import type {
  JsonValue,
  UiActionResultV1,
  UiActivationV1,
  UiPublicManifestV1,
  UiQueryResultV1,
} from '@/lib/agent-runtime/ui-contracts';

/** How a bridge reaches the server for one scope. Consumer: Bearer + guard header; founder: cookie + CSRF (F builds both). */
export interface UiTransport {
  /** `consumer` → `/api/workspaces/{id}/agent/ui`; `founder` → `/api/control/v2/agent/ui`. */
  base: string;
  scope: 'workspace' | 'founder';
  /** Stable key of the signed-in principal + workspace; a change aborts everything in flight and clears caches. */
  scopeKey: string;
  fetch(path: string, init: { method: 'GET' | 'POST'; body?: JsonValue; signal?: AbortSignal }): Promise<Response>;
}

export interface UiBridgeArtifact {
  artifactId: string;
  revision: number;
  /** True only for a server-accepted revision with current bindings; false while streaming/validating/rejected. */
  accepted: boolean;
  /** Historical message: serve persisted as-of data until the person explicitly goes live. */
  historical: boolean;
  manifest: UiPublicManifestV1;
}

export type BindingStatus = UiQueryResultV1['state'];

export interface QueryBridge {
  /** OpenUI `toolProvider` (MCP-like `callTool`) exposing read bindings only; `null` unless `artifact.accepted`. */
  toolProvider(): { callTool(call: { name: string; arguments?: Record<string, JsonValue> }): Promise<unknown> } | null;
  /** Direct read for Rafii ToolBound* components (same limiter, cache, scope and authorization as `toolProvider`). */
  read(bindingName: string, inputs: Record<string, JsonValue>, options?: { cursor?: string | null; signal?: AbortSignal }): Promise<UiQueryResultV1>;
  /** Per-binding status (OpenUI 0.3.2 has no per-query loading hook). */
  status(bindingName: string): BindingStatus | undefined;
  subscribe(listener: () => void): () => void;
  /** Visibility/collapse/historical gating: hidden or inactive artifacts make zero network calls and no polling. */
  setActive(active: boolean): void;
  /** Invalidate cached reads after a verified action (`UiActionResultV1.invalidationKeys`). */
  invalidate(keys: string[]): void;
  dispose(): void;
}

export type ActionPhase = 'idle' | 'activating' | 'confirming' | 'executing' | 'done' | 'error';

export interface ActionRequest {
  actionId: string;
  /** statementId of the control that was clicked (for focus return and audit). */
  controlId?: string;
  inputs: Record<string, JsonValue>;
}

export interface ActionState {
  phase: ActionPhase;
  request: ActionRequest | null;
  activation: UiActivationV1 | null;
  result: UiActionResultV1 | null;
  /** Sanitized, human-readable; never raw server/DSL text. */
  error: string | null;
}

export interface ActionBridge {
  /** Writes are possible at all for this artifact (flags on, accepted revision, binding present, role allows). */
  writesEnabled(actionId: string): boolean;
  /** Server manifest entry for a control (label/effect/summary come from the server, never model text). */
  binding(actionId: string): UiPublicManifestV1['actions'][number] | undefined;
  /** Called by a registered control's trusted click; obtains an activation and opens the native confirmation. */
  request(request: ActionRequest): void;
  /** Native confirmation sheet → confirm/cancel. Confirm executes once with a durable idempotency key. */
  confirm(): Promise<UiActionResultV1 | null>;
  cancel(): void;
  state(): ActionState;
  subscribe(listener: () => void): () => void;
  dispose(): void;
}

/** Follow-up from a generated control (`continue_conversation`), sent through the existing turn path with uiContext. */
export interface ContinueRequest {
  message: string;
  artifactId: string;
  artifactRevision: number;
  stateRevision: number;
}

export interface UiBridges {
  query: QueryBridge;
  action: ActionBridge;
  onContinue(request: ContinueRequest): void;
}

/** D exports `createUiBridges` from `bridges/index.ts` with exactly this signature. */
export type CreateUiBridges = (options: {
  transport: UiTransport;
  artifact: UiBridgeArtifact;
  onContinue: (request: ContinueRequest) => void;
  now?: () => number;
}) => UiBridges;

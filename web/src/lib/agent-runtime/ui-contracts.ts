/**
 * Shared contract of Rafii Generative UI (`rafii-genui/1`), browser side.
 *
 * Frozen by the release coordinator (role A). Mirrors `src/postriff_phase2/agent_runtime_v2/ui_contracts.py`; both are
 * checked against `tests/fixtures/agent_ui/contracts/contract-manifest.json` (web/tests/agent-ui-contracts.test.cjs and
 * tests/test_agent_ui_contracts.py). Only A edits this file.
 *
 * Nothing here is authority. `ready` is presentation state; `verified` comes only from the server's executor + re-read.
 */
import { z } from 'zod';

export const CONTRACT_VERSION = 'rafii-genui/1' as const;
export const LANGUAGE = 'openui-lang' as const;

export const UI_SURFACES = ['chat', 'panel', 'expanded', 'mobile', 'browser_voice', 'founder'] as const;
export const GENERATION_STATES = ['queued', 'streaming', 'validating', 'ready', 'failed', 'canceled', 'interrupted'] as const;
export const TERMINAL_GENERATION_STATES = ['ready', 'failed', 'canceled', 'interrupted'] as const;
export const VALIDATION_STATES = ['pending', 'accepted', 'rejected'] as const;
export const DATA_STATES = ['loading', 'available', 'empty', 'partial', 'unavailable', 'denied', 'stale'] as const;
export const ACTION_OUTCOMES = ['prepared', 'applied', 'rejected', 'conflict', 'pending', 'failed'] as const;
export const EVENT_KINDS = [
  'ui.started',
  'ui.delta',
  'ui.checkpoint',
  'ui.ready',
  'ui.failed',
  'ui.canceled',
  'ui.interrupted',
  'ui.state_changed',
  'ui.binding_changed',
  'ui.heartbeat',
] as const;
export const TERMINAL_EVENT_KINDS = ['ui.ready', 'ui.failed', 'ui.canceled', 'ui.interrupted'] as const;
export const ATTEMPT_KINDS = ['generate', 'repair', 'edit', 'retry'] as const;
export const REVISION_KINDS = ['generate', 'repair', 'edit'] as const;
export const SCOPES = ['workspace', 'founder'] as const;
export const SLOTS = ['main'] as const;
export const JOURNEYS = ['J01', 'J02', 'J03', 'J04', 'J05', 'J06', 'J07', 'J08', 'J09'] as const;
export const UI_ACTION_EFFECTS = ['CREATE_DRAFT', 'MUTATE_REVERSIBLE', 'PREPARE_EXTERNAL'] as const;

export const TRANSITIONS: Record<GenerationState, readonly GenerationState[]> = {
  queued: ['streaming', 'failed', 'canceled', 'interrupted'],
  streaming: ['validating', 'failed', 'canceled', 'interrupted'],
  validating: ['ready', 'failed', 'canceled', 'interrupted'],
  ready: [],
  failed: [],
  canceled: [],
  interrupted: [],
};

export const REASON_CODES = [
  'not_eligible',
  'disabled',
  'budget',
  'price_unknown',
  'no_model_route',
  'egress_denied',
  'provider_error',
  'provider_timeout',
  'parse_rejected',
  'validation_unavailable',
  'source_too_large',
  'repair_exhausted',
  'canceled_by_user',
  'client_gone',
  'lease_expired',
  'superseded',
  'library_unsupported',
  'revision_conflict',
  'internal_error',
] as const;

/** 02-CONTRACTS §7. Chosen acceptance limits, not vendor measurements. Tighten with evidence; never widen silently. */
export const BOUNDS = {
  sourceBytes: 128 * 1024,
  patchBytes: 32 * 1024,
  founderPatchBytes: 24 * 1024,
  statements: 512,
  treeDepth: 24,
  queryPageDefault: 50,
  queryPageMax: 100,
  queryWindowDays: 366,
  queryConcurrentPerArtifact: 4,
  queryPerMinute: 60,
  refreshMinSeconds: 30,
  searchDebounceMs: 300,
  stateBytes: 16 * 1024,
  stateDebounceMs: 500,
  providerAttempts: 2,
  generationTimeoutSeconds: 60,
  activationSeconds: 60,
  requestBodyBytes: 160 * 1024,
  inputBytes: 16 * 1024,
  inputDepth: 8,
  heartbeatSeconds: 10,
  replayTailSeconds: 30,
  replayPageEvents: 500,
  checkpointBytes: 4 * 1024,
  checkpointMs: 1000,
  validatorTimeoutSeconds: 8,
} as const;

export const FLAGS = [
  'RAFII_GENUI_ENABLED',
  'RAFII_GENUI_ACTIONS_ENABLED',
  'RAFII_GENUI_EDITS_ENABLED',
  'RAFII_GENUI_FOUNDER_ENABLED',
] as const;
export const CANARY_ENV = 'RAFII_GENUI_WORKSPACES' as const;

export const ROUTES = {
  consumerBase: '/api/workspaces/{workspaceId}/agent/ui',
  founderBase: '/api/control/v2/agent/ui',
  presentations: 'POST {base}/presentations',
  snapshot: 'GET {base}/presentations/{artifactId}',
  events: 'GET {base}/presentations/{artifactId}/events?after={seq}',
  cancel: 'POST {base}/presentations/{artifactId}/cancel',
  edits: 'POST {base}/presentations/{artifactId}/edits',
  state: 'POST {base}/presentations/{artifactId}/state',
  queries: 'POST {base}/queries',
  activate: 'POST {base}/actions/activate',
  actions: 'POST {base}/actions',
  byMessage: 'GET {base}/messages/{messageId}',
  probe: 'GET {base}/diagnostics/stream',
  validator: 'POST /internal/agent-ui/validate',
} as const;

export const PUBLIC_ARTIFACT_KEYS = [
  'contractVersion',
  'artifactId',
  'conversationId',
  'messageId',
  'runId',
  'revision',
  'generationAttemptId',
  'generationState',
  'validationState',
  'language',
  'languageVersion',
  'libraryVersion',
  'libraryHash',
  'promptHash',
  'sourceHash',
  'canonicalSource',
  'fallbackText',
  'manifestId',
  'bindingVersion',
  'safeState',
  'stateRevision',
  'createdAt',
  'updatedAt',
  'asOf',
] as const;

export type UiSurface = (typeof UI_SURFACES)[number];
export type GenerationState = (typeof GENERATION_STATES)[number];
export type ValidationState = (typeof VALIDATION_STATES)[number];
export type DataState = (typeof DATA_STATES)[number];
export type ActionOutcome = (typeof ACTION_OUTCOMES)[number];
export type UiEventKind = (typeof EVENT_KINDS)[number];
export type ReasonCode = (typeof REASON_CODES)[number];
export type JourneyId = (typeof JOURNEYS)[number];
export type UiActionEffect = (typeof UI_ACTION_EFFECTS)[number];

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

const jsonValue: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([z.null(), z.boolean(), z.number(), z.string(), z.array(jsonValue), z.record(z.string(), jsonValue)]),
);
const uuid = z.string().regex(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/);
const name = z.string().regex(/^[a-z][a-z0-9_]{1,63}$/);
const sha = z.string().regex(/^[0-9a-f]{64}$/);
export const IDEMPOTENCY_KEY = /^[A-Za-z0-9_-]{16,80}$/;
export const ACTIVATION_ID = /^act_[A-Za-z0-9_-]{32,64}$/;

export const uiArtifactSchema = z.object({
  contractVersion: z.literal(CONTRACT_VERSION),
  artifactId: uuid,
  conversationId: uuid,
  messageId: uuid.nullable(),
  runId: uuid,
  revision: z.number().int().nonnegative(),
  generationAttemptId: uuid.nullable(),
  generationState: z.enum(GENERATION_STATES),
  validationState: z.enum(VALIDATION_STATES),
  language: z.literal(LANGUAGE),
  languageVersion: z.string(),
  libraryVersion: z.string(),
  libraryHash: z.string(),
  promptHash: z.string(),
  sourceHash: sha.nullable(),
  canonicalSource: z.string().max(BOUNDS.sourceBytes).nullable(),
  fallbackText: z.string(),
  manifestId: z.string(),
  bindingVersion: z.number().int().nonnegative(),
  safeState: z.record(z.string(), jsonValue),
  stateRevision: z.number().int().nonnegative(),
  createdAt: z.string(),
  updatedAt: z.string(),
  asOf: z.string().nullable(),
});
export type UiArtifactV1 = z.infer<typeof uiArtifactSchema>;

export interface UiActionV1 {
  artifactId: string;
  artifactRevision: number;
  actionId: string;
  inputs: Record<string, JsonValue>;
  idempotencyKey: string;
  activationId: string;
}

export interface UiActivationRequestV1 {
  artifactId: string;
  artifactRevision: number;
  actionId: string;
  inputs: Record<string, JsonValue>;
  controlId?: string;
}

export const uiActivationSchema = z.object({
  activationId: z.string().regex(ACTIVATION_ID),
  inputDigest: sha,
  expiresAt: z.string(),
  /** Native confirmation copy built by the server from the manifest + current record — never model text. */
  confirmation: z.object({
    required: z.boolean(),
    title: z.string(),
    summary: z.array(z.string()).max(12),
    target: z.string().nullable(),
    timeZone: z.string().nullable(),
    cost: z.string().nullable(),
  }),
});
export type UiActivationV1 = z.infer<typeof uiActivationSchema>;

export interface UiQueryV1 {
  artifactId: string;
  artifactRevision: number;
  bindingId: string;
  inputs: Record<string, JsonValue>;
  cursor?: string | null;
}

export const uiQueryResultSchema = z.object({
  state: z.enum(DATA_STATES),
  data: jsonValue,
  asOf: z.string().nullable(),
  sourceRefs: z.array(z.string()),
  revision: z.string().nullable(),
  nextCursor: z.string().nullable(),
  coverage: z.object({ known: z.number().nullable(), total: z.number().nullable(), note: z.string().nullable() }),
  warnings: z.array(z.string()),
});
export type UiQueryResultV1 = z.infer<typeof uiQueryResultSchema>;

export const uiActionResultSchema = z.object({
  actionId: z.string(),
  idempotencyKey: z.string(),
  outcome: z.enum(ACTION_OUTCOMES),
  verified: z.boolean(),
  receiptRef: z.string().nullable(),
  proposalRef: z.string().nullable(),
  changedRefs: z.array(z.string()),
  invalidationKeys: z.array(z.string()),
  nextContext: z.record(z.string(), jsonValue),
});
export type UiActionResultV1 = z.infer<typeof uiActionResultSchema>;

/** Server-internal patch record. A browser never sends DSL: an edit request carries the person's instruction. */
export interface UiPatchV1 {
  artifactId: string;
  baseRevision: number;
  baseSourceHash: string;
  patchSource: string;
  idempotencyKey: string;
}

export interface UiEditRequestV1 {
  baseRevision: number;
  baseSourceHash: string;
  instruction: string;
  idempotencyKey: string;
  selection?: Record<string, JsonValue> | null;
}

export interface UiPresentationRequestV1 {
  parentRunId: string;
  slot?: (typeof SLOTS)[number];
  surface?: Exclude<UiSurface, 'founder'>;
  idempotencyKey: string;
  retryOfAttemptId?: string | null;
  conversationId?: string | null;
}

export const uiEventSchema = z.object({
  contractVersion: z.literal(CONTRACT_VERSION),
  artifactId: uuid,
  attemptId: uuid.nullable(),
  revision: z.number().int().nonnegative(),
  seq: z.number().int().nonnegative(),
  kind: z.enum(EVENT_KINDS),
  at: z.string(),
  payload: z.record(z.string(), jsonValue),
});
export type UiEventV1 = z.infer<typeof uiEventSchema>;

export const publicManifestSchema = z.object({
  manifestId: z.string(),
  bindingVersion: z.number().int().nonnegative(),
  journeyIds: z.array(z.enum(JOURNEYS)),
  componentGroups: z.array(z.string()),
  queries: z.array(
    z.object({
      name,
      description: z.string(),
      argsSchema: jsonValue,
      refreshMinSeconds: z.number().int().nullable(),
      pageSize: z.number().int().nullable(),
    }),
  ),
  actions: z.array(
    z.object({
      actionId: name,
      label: z.string(),
      effect: z.enum(UI_ACTION_EFFECTS),
      requiresConfirmation: z.boolean(),
      inputSchema: jsonValue,
      summary: z.string().nullable(),
    }),
  ),
  expiresAt: z.string().nullable(),
});
export type UiPublicManifestV1 = z.infer<typeof publicManifestSchema>;

/** `uiContext` on an agent turn: which artifact the person is looking at. The server re-resolves selections itself. */
export interface UiTurnContextV1 {
  artifactId: string;
  artifactRevision: number;
  stateRevision: number;
}

/** The handoff the server stores on a completed turn (`result.ui`). */
export const uiTurnHandoffSchema = z.object({
  eligible: z.boolean(),
  slot: z.enum(SLOTS),
  reason: z.string(),
  journeyIds: z.array(z.enum(JOURNEYS)),
});
export type UiTurnHandoffV1 = z.infer<typeof uiTurnHandoffSchema>;

/** A message's artifact references (`body.agent.uiArtifacts`). */
export interface UiArtifactRefV1 {
  artifactId: string;
  slot: (typeof SLOTS)[number];
}

export function canTransition(current: GenerationState, next: GenerationState): boolean {
  return TRANSITIONS[current].includes(next);
}

export function isTerminalEvent(kind: UiEventKind): boolean {
  return (TERMINAL_EVENT_KINDS as readonly string[]).includes(kind);
}

export function eventId(artifactId: string, seq: number): string {
  return `${artifactId}:${seq}`;
}

export function parseEventId(value: string | null | undefined): number | null {
  if (!value || !value.includes(':')) return null;
  const tail = value.slice(value.lastIndexOf(':') + 1);
  return /^\d{1,9}$/.test(tail) ? Number(tail) : null;
}

/**
 * Canonical JSON (sorted keys, no whitespace, integral numbers as integers). Mirrors the Python helper so fixtures agree;
 * the server's digest remains the only authority for activations and idempotency.
 */
export function canonicalJson(value: JsonValue): string {
  const walk = (v: JsonValue, depth: number): string => {
    if (depth > BOUNDS.inputDepth) throw new Error('ui_input_depth');
    if (v === null || typeof v === 'boolean' || typeof v === 'string') return JSON.stringify(v);
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) throw new Error('ui_input_number');
      return JSON.stringify(v);
    }
    if (Array.isArray(v)) return `[${v.map((x) => walk(x, depth + 1)).join(',')}]`;
    const keys = Object.keys(v).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${walk(v[k] as JsonValue, depth + 1)}`).join(',')}}`;
  };
  return walk(value, 0);
}

/** Everything both languages must agree on; compared with the fixture in tests. */
export function contractManifest() {
  return {
    contractVersion: CONTRACT_VERSION,
    language: LANGUAGE,
    surfaces: [...UI_SURFACES],
    generationStates: [...GENERATION_STATES],
    terminalGenerationStates: [...TERMINAL_GENERATION_STATES],
    validationStates: [...VALIDATION_STATES],
    dataStates: [...DATA_STATES],
    actionOutcomes: [...ACTION_OUTCOMES],
    eventKinds: [...EVENT_KINDS],
    terminalEventKinds: [...TERMINAL_EVENT_KINDS],
    attemptKinds: [...ATTEMPT_KINDS],
    revisionKinds: [...REVISION_KINDS],
    scopes: [...SCOPES],
    slots: [...SLOTS],
    journeys: [...JOURNEYS],
    uiActionEffects: [...UI_ACTION_EFFECTS],
    transitions: Object.fromEntries(Object.entries(TRANSITIONS).map(([k, v]) => [k, [...v]])),
    reasonCodes: [...REASON_CODES],
    bounds: { ...BOUNDS },
    flags: [...FLAGS],
    canaryEnv: CANARY_ENV,
    routes: { ...ROUTES },
    publicArtifactKeys: [...PUBLIC_ARTIFACT_KEYS],
  };
}

/**
 * Safety rules for the Library's generated task surfaces (UI spec §8; A069, A070): what may render, when a generated
 * control may write, and how a stream may change the screen.
 *
 *   - only allowlisted components with validated props; at most 100 components and nesting depth 12;
 *   - at most 5 read actions per render cycle; no parallel mutations; one parser-repair attempt; no automatic retry;
 *   - a mutation needs a fresh user activation while the result is live — never during hydration, replay or streaming;
 *   - every target must be a ref the server issued in this result; a stale expected revision is a conflict;
 *   - each activation gets its own idempotency key, reused only by an explicit retry of that same activation;
 *   - a stream never resets scope, selection or the person's draft.
 *
 * No imports: web/tests/library-intelligence-openui.test.cjs transpiles this module on its own. The component props
 * themselves are validated by `parseLibraryProps` (openui-schemas.ts), injected where needed.
 */

export const OPENUI_LIMITS = {
  maxComponents: 100,
  maxDepth: 12,
  maxReadsPerCycle: 5,
  maxRepairs: 1,
  automaticMutationRetry: false
} as const;

export interface TaskNode {
  component: string;
  props?: unknown;
  children?: unknown;
}

export interface ValidatedTaskNode {
  component: string;
  props: Record<string, unknown>;
  children: ValidatedTaskNode[];
  /** Stable position in the result ("0.2.1"), used as a React key and for focus return. */
  path: string;
}

export type PropsParser = (name: string, props: unknown) => { ok: true; props: Record<string, unknown> } | { ok: false; error: string } | null;

export interface TreeValidation {
  ok: boolean;
  nodes: ValidatedTaskNode[];
  errors: string[];
  count: number;
  depth: number;
}

/**
 * Validate a task result. Any unknown component, invalid props or exceeded cap makes the whole result invalid: limits
 * surface as a recoverable error, never as silently truncated content.
 */
export function validateTaskTree(input: unknown, parse: PropsParser, limits: { maxComponents: number; maxDepth: number } = OPENUI_LIMITS): TreeValidation {
  const errors: string[] = [];
  let count = 0;
  let deepest = 0;
  const visit = (raw: unknown, depth: number, path: string): ValidatedTaskNode | null => {
    deepest = Math.max(deepest, depth);
    if (depth > limits.maxDepth) {
      errors.push(`Nesting deeper than ${limits.maxDepth} levels`);
      return null;
    }
    count += 1;
    if (count > limits.maxComponents) {
      if (count === limits.maxComponents + 1) errors.push(`More than ${limits.maxComponents} components`);
      return null;
    }
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) || typeof (raw as TaskNode).component !== 'string') {
      errors.push('A part of the result is not a component');
      return null;
    }
    const node = raw as TaskNode;
    const parsed = parse(node.component, node.props ?? {});
    if (parsed === null) {
      errors.push(`Unknown component “${node.component.slice(0, 40)}”`);
      return null;
    }
    if (!parsed.ok) {
      errors.push(parsed.error);
      return null;
    }
    const rawChildren = node.children === undefined ? [] : node.children;
    if (!Array.isArray(rawChildren)) {
      errors.push('Children must be a list');
      return null;
    }
    const children: ValidatedTaskNode[] = [];
    rawChildren.forEach((child, index) => {
      const valid = visit(child, depth + 1, `${path}.${index}`);
      if (valid) children.push(valid);
    });
    return { component: node.component, props: parsed.props, children, path };
  };
  const roots = Array.isArray(input) ? input : input === null || input === undefined ? [] : [input];
  const nodes: ValidatedTaskNode[] = [];
  roots.forEach((root, index) => {
    const valid = visit(root, 1, String(index));
    if (valid) nodes.push(valid);
  });
  const unique = [...new Set(errors)];
  return { ok: unique.length === 0, nodes: unique.length === 0 ? nodes : [], errors: unique, count, depth: deepest };
}

export function walkNodes(nodes: readonly ValidatedTaskNode[], visit: (node: ValidatedTaskNode) => void) {
  for (const node of nodes) {
    visit(node);
    walkNodes(node.children, visit);
  }
}

/* --- identities issued by the server -------------------------------------------------------------------------------- */

export interface RefLike {
  assetId: string;
  versionId: string;
  sha256?: string;
}

/** Version identity of a ref; an empty versionId means "the version the server holds for this asset id". */
export function refKey(ref: RefLike): string {
  return `${ref.assetId}:${ref.versionId || ref.assetId}`;
}

function isRef(value: unknown): value is RefLike {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return typeof record.assetId === 'string' && typeof record.versionId === 'string' && 'sha256' in record;
}

/** Every AssetRef inside the validated result: the only targets a generated control may act on. */
export function collectServerRefs(nodes: readonly ValidatedTaskNode[]): Set<string> {
  const refs = new Set<string>();
  const scan = (value: unknown) => {
    if (Array.isArray(value)) for (const item of value) scan(item);
    else if (value && typeof value === 'object') {
      if (isRef(value)) refs.add(refKey(value));
      for (const item of Object.values(value)) scan(item);
    }
  };
  walkNodes(nodes, (node) => scan(node.props));
  return refs;
}

export interface IssuedEnvelopeLike {
  actionId: string;
  uiInstanceId: string;
  actionType: string;
  targetRefs: RefLike[];
  expectedRevision: number | null;
  payload: Record<string, unknown>;
}

/** The server-issued envelopes in the result, by actionId. A control can only name one of these. */
export function collectIssuedActions(nodes: readonly ValidatedTaskNode[]): Map<string, IssuedEnvelopeLike> {
  const issued = new Map<string, IssuedEnvelopeLike>();
  walkNodes(nodes, (node) => {
    const actions = node.props.actions;
    if (!Array.isArray(actions)) return;
    for (const action of actions) {
      const envelope = action && typeof action === 'object' ? (action as { envelope?: IssuedEnvelopeLike }).envelope : undefined;
      if (envelope && typeof envelope.actionId === 'string') issued.set(envelope.actionId, envelope);
    }
  });
  return issued;
}

/* --- reads ---------------------------------------------------------------------------------------------------------- */

/** At most `max` read actions per render cycle; `reset` starts the next cycle. */
export function createReadBudget(max: number = OPENUI_LIMITS.maxReadsPerCycle) {
  let used = 0;
  return {
    take() {
      if (used >= max) return false;
      used += 1;
      return true;
    },
    reset() {
      used = 0;
    },
    get used() {
      return used;
    }
  };
}

/* --- writes --------------------------------------------------------------------------------------------------------- */

/** Live: complete and validated. Streaming results are read-only; hydration and replay never write. */
export type SurfacePhase = 'live' | 'streaming' | 'hydrating' | 'replaying';

export interface ActivationToken {
  id: string;
}

export type ActivationResult = { ok: true; token: ActivationToken } | { ok: false; reason: 'hydration' | 'replay' | 'streaming' | 'no-user-activation' };

export interface ActionResultLike {
  status: string;
  revision?: number;
  result?: unknown;
  warnings?: readonly string[];
  replayed?: boolean;
}

export type DispatchOutcome =
  | { status: 'applied'; result?: unknown; revision?: number; replayed: boolean; message?: string }
  | { status: 'requires_confirmation' | 'conflict' | 'denied'; message: string; local?: boolean; retryable: false }
  | { status: 'failed'; message: string; retryable: boolean }
  | { status: 'busy' | 'refused'; message: string; retryable: false };

const WARNING: Record<string, string> = {
  requires_confirmation: 'This needs your confirmation first.',
  conflict: 'This changed since the result was made. Refresh it, then try again.',
  denied: 'Not allowed for your role or these items.'
};

export function outcomeFromResult(result: ActionResultLike | null | undefined): DispatchOutcome {
  const warning = result?.warnings?.find(Boolean);
  const status = result?.status;
  if (status === 'applied') {
    return { status: 'applied', result: result?.result, revision: result?.revision, replayed: Boolean(result?.replayed), message: result?.replayed ? 'Already done' : warning };
  }
  if (status === 'requires_confirmation' || status === 'conflict' || status === 'denied') {
    return { status, message: warning ?? WARNING[status], retryable: false };
  }
  return { status: 'failed', message: warning ?? 'No result came back.', retryable: true };
}

/**
 * The single gate between a generated control and the server. `send` is the host's transport (api.libraryAction);
 * `newKey` makes a fresh idempotency key. Nothing here loops: a failure is reported, and only an explicit retry of
 * the same activation sends again, with the same key.
 */
export function createLibraryDispatcher(deps: { send: (envelope: IssuedEnvelopeLike & { idempotencyKey: string }) => Promise<ActionResultLike>; newKey: () => string; readOnlyTypes?: readonly string[] }) {
  const readOnly = new Set(deps.readOnlyTypes ?? []);
  const records = new Map<string, { key: string; digest: string; state: 'sent' | 'failed' | 'settled' }>();
  let inFlight: string | null = null;
  let activations = 0;
  const refuse = (message: string): DispatchOutcome => ({ status: 'refused', message, retryable: false });

  function activate({ userActivation, phase }: { userActivation: boolean; phase: SurfacePhase }): ActivationResult {
    if (phase === 'hydrating') return { ok: false, reason: 'hydration' };
    if (phase === 'replaying') return { ok: false, reason: 'replay' };
    if (phase === 'streaming') return { ok: false, reason: 'streaming' };
    if (!userActivation) return { ok: false, reason: 'no-user-activation' };
    activations += 1;
    return { ok: true, token: { id: `activation-${activations}` } };
  }

  async function dispatch(
    envelope: IssuedEnvelopeLike,
    options: { token: ActivationToken | null; serverRefs: ReadonlySet<string>; knownRevision?: number | null; retry?: boolean; readBudget?: { take(): boolean } }
  ): Promise<DispatchOutcome> {
    const reading = readOnly.has(envelope.actionType);
    if (reading) {
      if (options.readBudget && !options.readBudget.take()) return refuse('Too many lookups at once. Try again in a moment.');
    } else if (!options.token) {
      return refuse('Changes need a press from you on a finished result.');
    }
    for (const ref of envelope.targetRefs) {
      if (!options.serverRefs.has(refKey(ref))) return { status: 'denied', message: 'One of these items isn’t part of this result.', local: true, retryable: false };
    }
    if (typeof options.knownRevision === 'number' && typeof envelope.expectedRevision === 'number' && envelope.expectedRevision < options.knownRevision) {
      return { status: 'conflict', message: WARNING.conflict, local: true, retryable: false };
    }
    const id = options.token?.id ?? `read-${envelope.actionId}`;
    const digest = JSON.stringify(envelope);
    const record = records.get(id);
    if (!reading) {
      if (record && !options.retry) return refuse('That press was already used. Press again to repeat it.');
      if (options.retry && (!record || record.state !== 'failed')) return refuse('There is nothing to retry.');
      if (options.retry && record && record.digest !== digest) return refuse('The action changed. Press it again.');
      if (inFlight) return { status: 'busy', message: 'Another change is still being saved.', retryable: false };
    }
    const key = !reading && record ? record.key : deps.newKey();
    if (!reading) {
      records.set(id, { key, digest, state: 'sent' });
      inFlight = id;
    }
    try {
      const result = await deps.send({ ...envelope, idempotencyKey: key });
      if (!reading) records.set(id, { key, digest, state: 'settled' });
      return outcomeFromResult(result);
    } catch (error) {
      if (!reading) records.set(id, { key, digest, state: 'failed' });
      const message = error && typeof error === 'object' && 'message' in error && typeof (error as { message: unknown }).message === 'string' ? (error as { message: string }).message : 'The request didn’t finish.';
      return { status: 'failed', message, retryable: !reading };
    } finally {
      if (!reading && inFlight === id) inFlight = null;
    }
  }

  return {
    activate,
    dispatch,
    /** The key an activation used (tests and diagnostics). */
    keyOf: (token: ActivationToken) => records.get(token.id)?.key ?? null,
    get busy() {
      return inFlight !== null;
    }
  };
}

/* --- streaming ------------------------------------------------------------------------------------------------------ */

export interface TaskSurfaceState {
  /** Owned by the host and never replaced by a stream. */
  scope: { kind: 'workspace' | 'collection' | 'selection'; collectionId?: string; selectedCount?: number };
  selection: string[];
  drafts: Record<string, string>;
  /** The last valid result; kept while a later frame is invalid. */
  nodes: ValidatedTaskNode[];
  status: 'idle' | 'streaming' | 'complete' | 'repairing' | 'error';
  repairs: number;
  errors: string[];
}

export interface StreamFrame {
  nodes?: unknown;
  final: boolean;
  /** The renderer or validator could not parse this frame at all. */
  parseError?: boolean;
}

export function initialSurfaceState(scope: TaskSurfaceState['scope'], selection: string[] = []): TaskSurfaceState {
  return { scope, selection, drafts: {}, nodes: [], status: 'idle', repairs: 0, errors: [] };
}

/**
 * Apply one stream frame. Scope, selection and drafts pass through untouched. A parse failure gets one repair attempt;
 * a second failure (or any invalid frame) is an error that keeps the last valid result for the deterministic fallback.
 */
export function applyStreamFrame(state: TaskSurfaceState, frame: StreamFrame, parse: PropsParser, maxRepairs: number = OPENUI_LIMITS.maxRepairs): TaskSurfaceState {
  if (frame.parseError) {
    if (state.repairs < maxRepairs) return { ...state, status: 'repairing', repairs: state.repairs + 1 };
    return { ...state, status: 'error', errors: ['The result could not be read after one repair attempt.'] };
  }
  const validation = validateTaskTree(frame.nodes, parse);
  if (!validation.ok) return { ...state, status: 'error', errors: validation.errors };
  return { ...state, nodes: validation.nodes, status: frame.final ? 'complete' : 'streaming', errors: [] };
}

export function canRepair(state: TaskSurfaceState, maxRepairs: number = OPENUI_LIMITS.maxRepairs) {
  return state.status === 'repairing' && state.repairs <= maxRepairs;
}

export function surfacePhase(state: TaskSurfaceState, { hydrated, replay }: { hydrated: boolean; replay: boolean }): SurfacePhase {
  if (!hydrated) return 'hydrating';
  if (replay) return 'replaying';
  return state.status === 'complete' ? 'live' : 'streaming';
}

/* --- deterministic fallback ----------------------------------------------------------------------------------------- */

export interface FallbackItem {
  ref: RefLike;
  title: string;
  component: string;
  path: string;
}

/**
 * The plain browsing view of a validated result: every titled item it names, once, in order. Used when no renderer is
 * mounted or the renderer fails; it needs nothing but the same validated server data.
 */
export function fallbackItems(nodes: readonly ValidatedTaskNode[]): FallbackItem[] {
  const seen = new Set<string>();
  const items: FallbackItem[] = [];
  const add = (ref: unknown, title: unknown, node: ValidatedTaskNode) => {
    if (!isRef(ref) || typeof title !== 'string') return;
    const key = refKey(ref);
    if (seen.has(key)) return;
    seen.add(key);
    items.push({ ref, title, component: node.component, path: node.path });
  };
  walkNodes(nodes, (node) => {
    const props = node.props as Record<string, unknown>;
    add(props.assetRef, props.title, node);
    add((props.sourceRef as { assetRef?: unknown } | undefined)?.assetRef, props.title, node);
    for (const listName of ['evidence', 'style', 'sources', 'candidates', 'after']) {
      const list = props[listName];
      if (!Array.isArray(list)) continue;
      for (const entry of list) {
        if (!entry || typeof entry !== 'object') continue;
        const record = entry as Record<string, unknown>;
        add(record.assetRef ?? (record.sourceRef as { assetRef?: unknown } | undefined)?.assetRef, record.title, node);
      }
    }
    for (const side of ['before', 'after']) {
      const value = props[side] as { ref?: unknown } | undefined;
      if (value && !Array.isArray(value)) add(value.ref, `${typeof props.title === 'string' ? props.title : 'Version'} · ${side === 'before' ? 'earlier version' : 'newer version'}`, node);
    }
  });
  return items;
}

/** Selection survives every frame; only an explicit host change (or a server denial) removes an id. */
export function keepSelection(previous: readonly string[], next: readonly string[] | undefined): string[] {
  return next === undefined ? [...previous] : [...next];
}

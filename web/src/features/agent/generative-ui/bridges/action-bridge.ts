/**
 * Lane D — the guarded action bridge of a generated view (rafii-genui/1, D-A12/D-A14/D-A15/D-A29).
 *
 * The only browser path from a generated control to a write:
 *   registered Rafii control (trusted click) → `request()` → POST …/actions/activate (server checks role, revision,
 *   inputs, target and returns the native confirmation copy) → native confirmation sheet OUTSIDE the generated subtree
 *   → `confirm()` → POST …/actions with a durable idempotency key + the one-use activation.
 *
 * Nothing here runs on render, mount, replay or refresh. Labels and summaries come from the server manifest, never model
 * text. `verified` is whatever the server's executor + re-read said; the bridge never upgrades an outcome. A lost reply
 * is reconciled by re-sending the SAME key and activation (the server returns the stored receipt; a second domain
 * effect is impossible), never by minting a new key.
 */
import {
  type JsonValue,
  type UiActionResultV1,
  type UiActivationV1,
  uiActionResultSchema,
  uiActivationSchema,
} from '@/lib/agent-runtime/ui-contracts';
import type { ActionBridge, ActionRequest, ActionState, UiBridgeArtifact, UiTransport } from './types';

type ActionEntry = UiBridgeArtifact['manifest']['actions'][number];

export interface ActionBridgeOptions {
  transport: UiTransport;
  artifact: UiBridgeArtifact;
  now?: () => number;
  /** Called with every server result (the query bridge invalidates `invalidationKeys`). */
  onResult?: (result: UiActionResultV1) => void;
  /** Delay between reconciliation attempts after a lost reply (ms). Tests shorten it. */
  reconcileDelays?: number[];
  sleep?: (ms: number) => Promise<void>;
}

const IDLE: ActionState = { phase: 'idle', request: null, activation: null, result: null, error: null };

/** Fixed, person-facing messages per server code; raw server/DSL text is never shown. */
const CODE_MESSAGES: Record<string, string> = {
  ui_action: 'This action is not available here.',
  ui_forbidden: 'Your role in this workspace can’t do this.',
  ui_disabled: 'Interactive actions are turned off right now.',
  ui_revision_stale: 'This view changed since you opened it. Reload it and try again.',
  ui_not_accepted: 'This view is still being prepared.',
  ui_activation: 'This confirmation is no longer valid. Confirm again.',
  ui_activation_used: 'This confirmation was already used. Confirm again.',
  ui_activation_expired: 'This confirmation expired. Confirm again.',
  ui_idempotency_conflict: 'This request was already used for a different change.',
  ui_action_pending: 'This action is still being processed. Check again in a moment.',
  ui_capability_expired: 'This view’s actions have expired. Ask Rafii again for a fresh view.',
  ui_input: 'Some of these values aren’t accepted. Check them and try again.',
  ui_args: 'Some of these values aren’t accepted. Check them and try again.',
};

const STATUS_MESSAGES: Record<number, string> = {
  400: 'Some of these values aren’t accepted. Check them and try again.',
  403: 'Your role in this workspace can’t do this.',
  404: 'This action is not available here.',
  409: 'This changed since you opened it. Reload and try again.',
  413: 'This is too large to save here.',
  429: 'Too many attempts. Wait a minute and try again.',
};

const LOST_REPLY =
  'Rafii couldn’t confirm whether this was saved. Nothing will be repeated: check the item, or confirm again to re-check.';

function hasOwn(object: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function base64url(bytes: Uint8Array): string {
  let text = '';
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** `uia_` + 32 random base64url characters: matches the contract's IDEMPOTENCY_KEY pattern. */
export function newIdempotencyKey(): string {
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  return `uia_${base64url(bytes)}`;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    const code = body && typeof body === 'object' ? (body as { code?: unknown }).code : undefined;
    if (typeof code === 'string' && hasOwn(CODE_MESSAGES, code)) return CODE_MESSAGES[code];
  } catch {
    // fall through to the status message
  }
  return STATUS_MESSAGES[response.status] ?? 'Rafii couldn’t complete this right now.';
}

function plainInputs(value: unknown): Record<string, JsonValue> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  try {
    // A structural copy: functions, symbols and prototypes never travel; the exact same object is sent twice.
    return JSON.parse(JSON.stringify(value)) as Record<string, JsonValue>;
  } catch {
    return null;
  }
}

export function createActionBridge(options: ActionBridgeOptions): ActionBridge {
  const { transport, artifact } = options;
  const now = options.now ?? (() => Date.now());
  const delays = options.reconcileDelays ?? [1000, 3000];
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>((resolve) => globalThis.setTimeout(resolve, ms)));
  const scopeKey = transport.scopeKey;

  const bindings: Record<string, ActionEntry> = Object.create(null) as Record<string, ActionEntry>;
  for (const entry of artifact.manifest.actions) {
    if (typeof entry?.actionId === 'string' && /^[a-z][a-z0-9_]{1,63}$/.test(entry.actionId)) bindings[entry.actionId] = entry;
  }

  let state: ActionState = IDLE;
  let disposed = false;
  let idempotencyKey: string | null = null;
  let sentInputs: Record<string, JsonValue> | null = null;
  let activationController: AbortController | null = null;
  const listeners = new Set<() => void>();

  const set = (next: ActionState) => {
    state = next;
    for (const listener of [...listeners]) {
      try {
        listener();
      } catch {
        // A listener error never breaks the bridge.
      }
    }
  };

  const binding = (actionId: string): ActionEntry | undefined =>
    typeof actionId === 'string' && hasOwn(bindings, actionId) ? bindings[actionId] : undefined;

  const usable = () => !disposed && artifact.accepted && transport.scopeKey === scopeKey;

  const fail = (request: ActionRequest | null, error: string, activation: UiActivationV1 | null = null) =>
    set({ phase: 'error', request, activation, result: null, error });

  const activate = async (request: ActionRequest, inputs: Record<string, JsonValue>) => {
    const controller = new AbortController();
    activationController = controller;
    try {
      const body: JsonValue = {
        artifactId: artifact.artifactId,
        artifactRevision: artifact.revision,
        actionId: request.actionId,
        inputs,
        ...(typeof request.controlId === 'string' && request.controlId.length <= 80 ? { controlId: request.controlId } : {}),
      };
      const response = await transport.fetch(`${transport.base}/actions/activate`, { method: 'POST', body, signal: controller.signal });
      if (!usable() || activationController !== controller) return;
      if (!response.ok) {
        fail(request, await errorMessage(response));
        return;
      }
      let parsed: ReturnType<typeof uiActivationSchema.safeParse>;
      try {
        parsed = uiActivationSchema.safeParse(await response.json());
      } catch {
        fail(request, 'Rafii received a confirmation it could not read.');
        return;
      }
      if (!parsed.success) {
        fail(request, 'Rafii received a confirmation it could not read.');
        return;
      }
      const activation = parsed.data;
      idempotencyKey = newIdempotencyKey();
      sentInputs = inputs;
      set({ phase: 'confirming', request: { ...request, inputs }, activation, result: null, error: null });
      if (!activation.confirmation.required) {
        // A reversible, server-declared direct action: the person's click was the confirmation.
        await confirm();
      }
    } catch {
      if (activationController === controller && usable()) fail(request, 'Rafii couldn’t reach the server. Nothing was changed.');
    } finally {
      if (activationController === controller) activationController = null;
    }
  };

  const send = async (activation: UiActivationV1, request: ActionRequest): Promise<Response> => {
    const body: JsonValue = {
      artifactId: artifact.artifactId,
      artifactRevision: artifact.revision,
      actionId: request.actionId,
      inputs: sentInputs ?? {},
      idempotencyKey: idempotencyKey ?? '',
      activationId: activation.activationId,
    };
    return transport.fetch(`${transport.base}/actions`, { method: 'POST', body });
  };

  async function confirm(): Promise<UiActionResultV1 | null> {
    const current = state;
    if (!usable() || !current.activation || !current.request || !idempotencyKey) return null;
    if (current.phase !== 'confirming' && current.phase !== 'error') return null;
    const { activation, request } = current;
    const reChecking = current.phase === 'error';
    const expires = Date.parse(activation.expiresAt);
    if (!reChecking && Number.isFinite(expires) && expires <= now()) {
      fail(request, CODE_MESSAGES.ui_activation_expired, activation);
      return null;
    }
    set({ phase: 'executing', request, activation, result: null, error: null });
    const attempts = [0, ...delays];
    for (let attempt = 0; attempt < attempts.length; attempt += 1) {
      if (attempts[attempt] > 0) await sleep(attempts[attempt]);
      if (!usable()) return null;
      let response: Response;
      try {
        response = await send(activation, request);
      } catch {
        continue; // lost reply or network: reconcile with the SAME key and activation
      }
      if (!usable()) return null;
      if (response.status >= 500 || response.status === 0) continue;
      if (!response.ok) {
        fail(request, await errorMessage(response), activation);
        return null;
      }
      let parsed: ReturnType<typeof uiActionResultSchema.safeParse>;
      try {
        parsed = uiActionResultSchema.safeParse(await response.json());
      } catch {
        continue;
      }
      if (!parsed.success || parsed.data.idempotencyKey !== idempotencyKey || parsed.data.actionId !== request.actionId) {
        fail(request, 'Rafii received a result it could not read. Check the item before trying again.', activation);
        return null;
      }
      const result = parsed.data;
      set({ phase: 'done', request, activation, result, error: null });
      try {
        options.onResult?.(result);
      } catch {
        // invalidation is best effort; the receipt above is the truth
      }
      return result;
    }
    // Still unknown: keep the key and activation so "confirm again" re-checks instead of repeating.
    fail(request, LOST_REPLY, activation);
    return null;
  }

  return {
    writesEnabled(actionId: string) {
      return usable() && binding(actionId) !== undefined;
    },
    binding,
    request(request: ActionRequest) {
      if (!request || typeof request !== 'object') return;
      if (state.phase === 'activating' || state.phase === 'executing' || state.phase === 'confirming') return; // one at a time; a double click is ignored
      if (!usable() || !binding(request.actionId)) {
        fail(request, CODE_MESSAGES.ui_action);
        return;
      }
      const inputs = plainInputs(request.inputs ?? {});
      if (!inputs) {
        fail(request, CODE_MESSAGES.ui_input);
        return;
      }
      idempotencyKey = null;
      sentInputs = null;
      set({ phase: 'activating', request: { ...request, inputs }, activation: null, result: null, error: null });
      void activate(request, inputs);
    },
    confirm,
    cancel() {
      if (state.phase === 'executing') return; // the server may already be applying it; the receipt will say
      activationController?.abort();
      activationController = null;
      idempotencyKey = null;
      sentInputs = null;
      set(IDLE);
    },
    state() {
      return state;
    },
    subscribe(listener: () => void) {
      if (disposed) return () => undefined;
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      activationController?.abort();
      activationController = null;
      set(IDLE);
      listeners.clear();
    },
  };
}

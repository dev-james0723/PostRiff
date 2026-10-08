'use client';
/**
 * The only place journey components touch the runtime around them (lane E):
 *   - lane C's OpenUI facade (`core/openui.ts`, the single importer of @openuidev/react-lang, D-A3) for reactive
 *     `$bindings` and the streaming flag;
 *   - lane D's bridge context (`bridges/context.tsx`, D-A29) for the per-binding query status and the guarded action path.
 *
 * Writes: a journey control never calls the server itself. It asks the action bridge, which fetches a server-built
 * activation, shows the native confirmation outside the generated view and executes only on an explicit confirm. A
 * request is ignored unless it comes from a trusted user event, the view's revision is accepted (not streaming) and the
 * manifest holds the action. Nothing here runs on render, mount, replay or refresh.
 */
import { createContext, createElement, useCallback, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import type { JsonValue, UiPublicManifestV1 } from '@/lib/agent-runtime/ui-contracts';
import { useIsStreaming, useStateField } from '../core/openui';
import { useRafiiActionBridge, useRafiiQueryBridge } from '../bridges/context';
import type { ActionState, BindingStatus } from '../bridges/types';
import { journeyCopy, type JourneyCopy, type JourneyLocale } from './copy';

// --- locale and zone ---------------------------------------------------------------------------------------------------
export interface JourneyEnvironment {
  locale: JourneyLocale;
  /** The person's IANA zone; record times keep their own zone and are labelled with it. */
  timeZone: string;
}

const JourneyEnvironmentContext = createContext<JourneyEnvironment>({ locale: 'en', timeZone: 'UTC' });

export function JourneyEnvironmentProvider({ value, children }: { value: JourneyEnvironment; children: ReactNode }) {
  return createElement(JourneyEnvironmentContext.Provider, { value }, children);
}

export function useJourneyEnvironment(): JourneyEnvironment & { copy: JourneyCopy } {
  const env = useContext(JourneyEnvironmentContext);
  return { ...env, copy: journeyCopy(env.locale) };
}

// --- reactive bindings -------------------------------------------------------------------------------------------------
/**
 * A `$binding` prop (selection, filter, period). With a `$variable` it reads and writes that variable in the view's
 * local store (no model call, no network unless a Query depends on it); with a literal it keeps local field state.
 */
export function useBound<T>(name: string, prop: unknown): { value: T | undefined; set: (value: T) => void; bound: boolean } {
  const field = useStateField(name, prop as never) as { value: unknown; setValue: (value: unknown) => void; isReactive: boolean };
  const value = field.value === null ? undefined : (field.value as T | undefined);
  return { value, set: (next: T) => field.setValue(next), bound: field.isReactive };
}

export function useStreaming(): boolean {
  return useIsStreaming();
}

// --- query status ------------------------------------------------------------------------------------------------------
const noStatus = () => undefined;
const noSubscribe = () => () => undefined;

/** Per-binding status from the query bridge (OpenUI 0.3.2 has no per-query loading hook). */
export function useBindingStatus(binding: string): BindingStatus | undefined {
  const bridge = useRafiiQueryBridge();
  const subscribe = useMemo(() => (bridge ? (listener: () => void) => bridge.subscribe(listener) : noSubscribe), [bridge]);
  const read = useCallback(() => (bridge ? bridge.status(binding) : undefined), [bridge, binding]);
  return useSyncExternalStore(subscribe, read, noStatus);
}

// --- guarded actions ---------------------------------------------------------------------------------------------------
export interface JourneyAction {
  /** The server manifest's entry (label, effect, summary); undefined when this view may not offer the action. */
  binding: UiPublicManifestV1['actions'][number] | undefined;
  /** Accepted revision, flags on, role allows, not streaming. */
  enabled: boolean;
  /** This control's own request is in flight / confirming / done. */
  state: ActionState | null;
  /** Ask for the action. Ignored without a trusted user event or when disabled. */
  request(inputs: Record<string, JsonValue>, event: { isTrusted?: boolean } | null | undefined): void;
}

const idleState: ActionState = { phase: 'idle', request: null, activation: null, result: null, error: null };

export function useJourneyAction(actionId: string | undefined, controlId: string | undefined): JourneyAction {
  const bridge = useRafiiActionBridge();
  const streaming = useIsStreaming();
  const subscribe = useMemo(() => (bridge ? (listener: () => void) => bridge.subscribe(listener) : noSubscribe), [bridge]);
  // The bridge returns the same ActionState object until it changes (useSyncExternalStore needs a stable snapshot).
  const read = useCallback(() => (bridge ? bridge.state() : idleState), [bridge]);
  const state = useSyncExternalStore(subscribe, read, () => idleState);
  const binding = actionId && bridge ? bridge.binding(actionId) : undefined;
  const enabled = Boolean(actionId && bridge && binding && !streaming && bridge.writesEnabled(actionId));
  const request = useCallback(
    (inputs: Record<string, JsonValue>, event: { isTrusted?: boolean } | null | undefined) => {
      if (!event || event.isTrusted !== true) return;
      if (!actionId || !bridge || !enabled) return;
      bridge.request({ actionId, controlId, inputs });
    },
    [actionId, bridge, controlId, enabled],
  );
  const mine = state.request && state.request.actionId === actionId && (controlId === undefined || state.request.controlId === controlId) ? state : null;
  return { binding, enabled, state: mine, request };
}

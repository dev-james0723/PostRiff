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
import { useCallback } from 'react';
import type { JsonValue, UiPublicManifestV1 } from '@/lib/agent-runtime/ui-contracts';
import { useIsStreaming, useStateField } from '../core/openui';
import { useGenUiLocale, type GenUiLocale } from '../core/locale';
import { useBindingStatus as useBridgeBindingStatus, useRafiiActionBridge, useRafiiActionState } from '../bridges/context';
import type { ActionState, BindingStatus } from '../bridges/types';
import { useRecordSelection } from '../state/selection';
import { journeyCopy, type JourneyCopy, type JourneyLocale } from './copy';

// --- locale and zone ---------------------------------------------------------------------------------------------------
export interface JourneyEnvironment {
  /** Language of Rafii's own labels (lane C's GenUiLocale.language). */
  language: JourneyLocale;
  /** BCP 47 tag numbers and dates are formatted with (the person's preference). */
  locale: string;
  /** The person's IANA zone; record times keep their own zone and are labelled with it. */
  timeZone: string;
  copy: JourneyCopy;
  /** Lane C's formatter for the person's locale (numbers, dates; unknown → "Not available", never 0). */
  l: GenUiLocale;
}

/** Journey copy and formatting from lane C's single locale context (no second locale context). */
export function useJourneyEnvironment(): JourneyEnvironment {
  const l = useGenUiLocale();
  return { language: l.language, locale: l.locale, timeZone: l.timeZone, copy: journeyCopy(l.language), l };
}

// --- reactive bindings -------------------------------------------------------------------------------------------------
/**
 * A `$binding` prop (selection, filter, period). With a `$variable` it reads and writes that variable in the view's
 * local store (no model call, no network unless a Query depends on it); with a literal it keeps local field state.
 */
export function useBound<T>(name: string, prop: unknown): { value: T | undefined; set: (value: T) => void; bound: boolean } {
  const field = useStateField<unknown>(name, prop);
  const value = field.value === null ? undefined : (field.value as T | undefined);
  return { value, set: (next: T) => field.setValue(next), bound: field.isReactive };
}

export function useStreaming(): boolean {
  return useIsStreaming();
}

// --- selection memory --------------------------------------------------------------------------------------------------
export interface SelectedRef {
  type: string;
  id: string;
  title?: string;
}

/**
 * Report an ordered selection to lane F's view state (`@selection`), so a follow-up such as "the second draft" resolves
 * against the order shown when the person picked, not a later re-sorted list. Ids come from bound data; titles are
 * display text kept with the view (never sent to a model). No-op outside a generated view.
 */
export function useSelectionRecorder(listId: string): (picked: SelectedRef[], visible: SelectedRef[]) => void {
  const record = useRecordSelection();
  return useCallback(
    (picked: SelectedRef[], visible: SelectedRef[]) =>
      record(
        listId,
        picked.slice(0, 50).map((r) => ({ type: r.type, id: r.id, ...(r.title ? { title: r.title.slice(0, 120) } : {}) })),
        visible.slice(0, 50).map((r) => ({ type: r.type, id: r.id })),
      ),
    [listId, record],
  );
}

// --- query status ------------------------------------------------------------------------------------------------------
/** Per-binding status from the query bridge (OpenUI 0.3.2 has no per-query loading hook). */
export function useBindingStatus(binding: string): BindingStatus | undefined {
  return useBridgeBindingStatus(binding);
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

export function useJourneyAction(actionId: string | undefined, controlId: string | undefined): JourneyAction {
  const bridge = useRafiiActionBridge();
  const streaming = useIsStreaming();
  const state: ActionState = useRafiiActionState();
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

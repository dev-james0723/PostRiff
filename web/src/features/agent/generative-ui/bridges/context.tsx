'use client';

/**
 * Lane D — React context for the generative-UI bridges (rafii-genui/1, D-A29/D-A40).
 *
 * The provider sits in RafiiGenerativeMessage OUTSIDE the generated subtree; Rafii-owned components (ActionButton, Form,
 * ToolBound*) read the bridges through these hooks. Outside a provider every hook returns `null` and never throws, so a
 * control rendered without a bridge simply shows as unavailable.
 */
import { createContext, type JSX, type ReactNode, useContext, useSyncExternalStore } from 'react';
import type { ActionBridge, ActionState, BindingStatus, QueryBridge, UiBridges } from './types';

const UiBridgesContext = createContext<UiBridges | null>(null);

export function UiBridgesProvider(props: { bridges: UiBridges; children: ReactNode }): JSX.Element {
  return <UiBridgesContext.Provider value={props.bridges}>{props.children}</UiBridgesContext.Provider>;
}

/** The bridges of the nearest generated view, or `null` outside one. */
export function useUiBridges(): UiBridges | null {
  return useContext(UiBridgesContext);
}

export function useRafiiActionBridge(): ActionBridge | null {
  return useContext(UiBridgesContext)?.action ?? null;
}

export function useRafiiQueryBridge(): QueryBridge | null {
  return useContext(UiBridgesContext)?.query ?? null;
}

const noop = () => () => undefined;
const IDLE: ActionState = { phase: 'idle', request: null, activation: null, result: null, error: null };

/** The action bridge's state, re-rendering on change (the native confirmation sheet reads this). */
export function useRafiiActionState(): ActionState {
  const bridge = useRafiiActionBridge();
  return useSyncExternalStore(
    bridge ? bridge.subscribe : noop,
    () => (bridge ? bridge.state() : IDLE),
    () => IDLE,
  );
}

/** One read binding's status (`loading` while in flight, otherwise the server's own state); undefined before any read. */
export function useBindingStatus(bindingName: string): BindingStatus | undefined {
  const bridge = useRafiiQueryBridge();
  return useSyncExternalStore(
    bridge ? bridge.subscribe : noop,
    () => (bridge ? bridge.status(bindingName) : undefined),
    () => undefined,
  );
}

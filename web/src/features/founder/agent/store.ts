'use client';

/**
 * Founder Rafii's panel state, outside React so page changes and the mode switch never lose it (CONTRACTS §6,
 * mirroring `features/site-agent/store.ts` under the `rafii.founder.panel.*` namespace): whether the panel is open,
 * the conversation per data mode and environment, the thread shown in this tab, and whether a turn is in flight.
 *
 * Persistence: the open state in localStorage (docked layouts only restore it), the conversation id per
 * `mode:environment` in sessionStorage. The thread itself stays in memory: Demo and Live conversations never share
 * a key, so switching modes shows a different thread, and a reload continues the conversation id on the server.
 */
import { useSyncExternalStore } from 'react';
import type { FounderPageRegistration } from '@/lib/founder/page-context';
import type { FounderAgentTurnResponse, FounderEnvironment, FounderMode } from '@/lib/founder/types';

export interface FounderThreadItem {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  at: number;
  /** Assistant items: the turn response once it arrived. */
  response?: FounderAgentTurnResponse | null;
  pending?: boolean;
  runId?: string | null;
  /** A failed turn keeps its key and words so "Try again" resends the same request. */
  error?: string | null;
  retryKey?: string | null;
  retryText?: string | null;
}

/** "Ask Rafii about this": the words, plus the page context the asking page wants the next turn to carry. */
export interface FounderPrefill {
  text: string;
  context?: FounderPageRegistration | null;
}

export interface FounderPanelState {
  open: boolean;
  /** Shown as a sheet above another dialog (docked layouts only; never remembered). */
  above: boolean;
  conversations: Record<string, string | null>;
  threads: Record<string, FounderThreadItem[]>;
  busy: Record<string, boolean>;
  prefill: FounderPrefill | null;
}

const OPEN_KEY = 'rafii.founder.panel.open';
const CONVERSATION_PREFIX = 'rafii.founder.panel.conversation.';
const SERVER: FounderPanelState = { open: false, above: false, conversations: {}, threads: {}, busy: {}, prefill: null };
const EMPTY_THREAD: FounderThreadItem[] = [];

let state: FounderPanelState = SERVER;
const listeners = new Set<() => void>();

function set(patch: Partial<FounderPanelState>) {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Conversations are namespaced by data mode and environment (PRD §6.2): Demo and Live never share one. */
export function conversationKey(mode: FounderMode, environment: FounderEnvironment | null): string {
  return `${mode}:${environment ?? 'unknown'}`;
}

function readConversation(key: string): string | null {
  try {
    return sessionStorage.getItem(CONVERSATION_PREFIX + key);
  } catch {
    return null;
  }
}

export const founderPanelStore = {
  get: () => state,
  subscribe,
  restore(docked: boolean) {
    if (!docked) return;
    try {
      if (localStorage.getItem(OPEN_KEY) === '1' && !state.open) set({ open: true });
    } catch {
      /* a convenience only */
    }
  },
  setOpen(open: boolean) {
    if (open === state.open) return;
    set({ open });
    try {
      localStorage.setItem(OPEN_KEY, open ? '1' : '0');
    } catch {
      /* a convenience only */
    }
  },
  toggle() {
    founderPanelStore.setOpen(!state.open);
  },
  setAbove(above: boolean) {
    if (above !== state.above) set({ above });
  },
  /** Open with a question typed in ("Ask Rafii about this"); the person still sends it, with the given context. */
  ask(text: string, context?: FounderPageRegistration | null) {
    set({ prefill: { text, context: context ?? null } });
    founderPanelStore.setOpen(true);
  },
  takePrefill(): FounderPrefill | null {
    const value = state.prefill;
    if (value !== null) set({ prefill: null });
    return value;
  },
  load(key: string) {
    if (key in state.conversations) return;
    set({ conversations: { ...state.conversations, [key]: readConversation(key) } });
  },
  setConversation(key: string, conversationId: string | null) {
    const patch: Partial<FounderPanelState> = { conversations: { ...state.conversations, [key]: conversationId } };
    if (conversationId === null) patch.threads = { ...state.threads, [key]: [] };
    set(patch);
    try {
      if (conversationId) sessionStorage.setItem(CONVERSATION_PREFIX + key, conversationId);
      else sessionStorage.removeItem(CONVERSATION_PREFIX + key);
    } catch {
      /* a convenience only */
    }
  },
  thread(key: string): FounderThreadItem[] {
    return state.threads[key] ?? EMPTY_THREAD;
  },
  append(key: string, item: FounderThreadItem) {
    set({ threads: { ...state.threads, [key]: [...founderPanelStore.thread(key), item] } });
  },
  update(key: string, id: string, patch: Partial<FounderThreadItem>) {
    set({ threads: { ...state.threads, [key]: founderPanelStore.thread(key).map((item) => (item.id === id ? { ...item, ...patch } : item)) } });
  },
  setBusy(key: string, busy: boolean) {
    set({ busy: { ...state.busy, [key]: busy } });
  }
};

export function useFounderPanel<T>(selector: (s: FounderPanelState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(SERVER)
  );
}

export function useFounderThread(key: string): FounderThreadItem[] {
  return useFounderPanel((s) => s.threads[key] ?? EMPTY_THREAD);
}

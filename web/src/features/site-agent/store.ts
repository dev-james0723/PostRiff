'use client';

/**
 * The Rafii panel's state, outside React so the app gate, the preferences re-key and page changes never
 * lose it: whether the panel is open, the conversation it is continuing in each workspace, the context
 * the current page registered, and the live progress of runs started from the panel.
 *
 * Persistence: the open state in localStorage (docked layouts only restore it), the conversation per
 * workspace in sessionStorage (a refresh continues it; a new tab starts clean). Nothing here is
 * workspace data: the conversation itself lives on the server and is re-read from there.
 */
import { useSyncExternalStore } from 'react';
import type { SafeEvent } from '@/lib/api/types';
import type { SiteAgentPageContext } from '@/lib/site-agent/types';

export interface LiveRun {
  events: SafeEvent[];
  composing: boolean;
}

export interface PanelState {
  open: boolean;
  /** Shown as a sheet above another dialog (a docked layout only; never remembered). */
  above: boolean;
  conversations: Record<string, string | null>;
  page: Pick<SiteAgentPageContext, 'selectedEntity' | 'visibleState'> | null;
  live: Record<string, LiveRun>;
  busy: Record<string, boolean>;
  prefill: string | null;
}

const OPEN_KEY = 'rafii.panel.open';
const CONVERSATION_PREFIX = 'rafii.panel.conversation.';
const SERVER: PanelState = { open: false, above: false, conversations: {}, page: null, live: {}, busy: {}, prefill: null };
/** Sent when Rafii applied a change to an automation, so a page showing it can re-read it. */
export const AUTOMATION_CHANGED = 'rafii:automation-changed';

let state: PanelState = SERVER;
const registrations: { key: string; page: NonNullable<PanelState['page']> }[] = [];
const listeners = new Set<() => void>();

function set(patch: Partial<PanelState>) {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function readConversation(workspaceId: string): string | null {
  try {
    return sessionStorage.getItem(CONVERSATION_PREFIX + workspaceId);
  } catch {
    return null;
  }
}

export const panelStore = {
  get: () => state,
  subscribe,
  /** Restore the docked panel's open state after a reload (never opens a sheet over a phone screen). */
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
    panelStore.setOpen(!state.open);
  },
  setAbove(above: boolean) {
    if (above !== state.above) set({ above });
  },
  /** Open with a question typed in (for "Ask Rafii about this" links); the person still sends it. */
  ask(text: string) {
    set({ prefill: text });
    panelStore.setOpen(true);
  },
  takePrefill(): string | null {
    const value = state.prefill;
    if (value !== null) set({ prefill: null });
    return value;
  },
  /** Read the conversation this tab was continuing in a workspace (once per workspace). */
  load(workspaceId: string) {
    if (workspaceId in state.conversations) return;
    set({ conversations: { ...state.conversations, [workspaceId]: readConversation(workspaceId) } });
  },
  setConversation(workspaceId: string, conversationId: string | null) {
    set({ conversations: { ...state.conversations, [workspaceId]: conversationId } });
    try {
      if (conversationId) sessionStorage.setItem(CONVERSATION_PREFIX + workspaceId, conversationId);
      else sessionStorage.removeItem(CONVERSATION_PREFIX + workspaceId);
    } catch {
      /* a convenience only */
    }
  },
  /**
   * Pages (and panels inside them, like Queue → Drafts) register what is selected; the most specific recent
   * registration wins, and removing one uncovers the one below it.
   */
  register(key: string, page: NonNullable<PanelState['page']> | null) {
    const index = registrations.findIndex((item) => item.key === key);
    if (index >= 0) registrations.splice(index, 1);
    if (page) registrations.push({ key, page });
    // A registration that selects something is more specific than a page's plain view values (React mounts a
    // panel's effects before its page's), so it wins; otherwise the latest wins.
    const top = registrations.findLast((item) => item.page.selectedEntity)?.page ?? registrations.at(-1)?.page ?? null;
    if (JSON.stringify(top) !== JSON.stringify(state.page)) set({ page: top });
  },
  setLive(runId: string, live: LiveRun | null) {
    const next = { ...state.live };
    if (live) next[runId] = live;
    else delete next[runId];
    set({ live: next });
  },
  setBusy(workspaceId: string, busy: boolean) {
    set({ busy: { ...state.busy, [workspaceId]: busy } });
  }
};

export function usePanel<T>(selector: (s: PanelState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(SERVER)
  );
}

'use client';

import { useSyncExternalStore } from 'react';

/**
 * The running walkthrough, outside React: a guide opens another page first, and the panel's answers show whether
 * their guide is the one running. Each start gets a new run id, so "Show me" again restarts from step 1.
 */

export interface GuideRun {
  id: number;
  guideId: string;
}

export interface GuideState {
  run: GuideRun | null;
}

const SERVER: GuideState = { run: null };
let state: GuideState = SERVER;
let lastId = 0;
const listeners = new Set<() => void>();

function set(next: GuideState) {
  state = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const guideStore = {
  get: () => state,
  subscribe,
  start(guideId: string): GuideRun {
    lastId += 1;
    const run = { id: lastId, guideId };
    set({ run });
    return run;
  },
  /** Stop whatever is running (Stop, Escape, the person went elsewhere, another tour started). */
  stop() {
    if (state.run) set({ run: null });
  },
  /** A run that ended by itself; a newer run that replaced it is left alone. */
  finish(id: number) {
    if (state.run?.id === id) set({ run: null });
  }
};

export function useGuideStore<T>(selector: (s: GuideState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(SERVER)
  );
}

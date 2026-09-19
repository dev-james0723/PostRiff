'use client';

import { useSyncExternalStore } from 'react';

/**
 * Onboarding state that must outlive a page: the app template re-mounts on every
 * navigation, so the overlay cannot keep the running tour in React state. A small
 * external store holds it, and per-person progress is remembered in localStorage under a
 * key that carries the signed-in user's id (two people sharing a browser keep their own).
 *
 * Progress is a per-browser convenience for now. When the profile API grows an
 * `onboarding` field (`PATCH /api/me`), `readProgress` / `writeProgress` are the two
 * seams to swap; nothing else needs to change.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface TourProgress {
  /** Tour id → epoch ms when the person reached the end. */
  completed: Record<string, number>;
  /** Tour id → epoch ms when the person closed it early or declined it. */
  dismissed: Record<string, number>;
  /** Tour id → epoch ms of the one-time "see how this page works" nudge. */
  nudged: Record<string, number>;
}

export interface TourState {
  active: { tourId: string; index: number } | null;
  /** Set while a step's route is being opened, so the overlay on the next page carries on. */
  hop: { route: string; tourId: string; index: number } | null;
  /** The last spotlight rectangle (viewport px); the next page morphs from it instead of popping. */
  lastRect: Rect | null;
  progress: TourProgress;
  /** False until the signed-in person is known and their progress has been read. */
  progressReady: boolean;
  /** Sidebar sections the tour opened to reach a link; closed again when the tour ends. */
  openedGroups: string[];
}

const LEGACY_KEY = 'postriff-onboarding';
const keyFor = (userId: string) => `${LEGACY_KEY}:${userId}`;
const EMPTY_PROGRESS: TourProgress = { completed: {}, dismissed: {}, nudged: {} };

function parse(raw: string | null): TourProgress | null {
  try {
    const parsed = JSON.parse(raw ?? 'null') as Partial<TourProgress> | null;
    if (!parsed || typeof parsed !== 'object') return null;
    return { completed: parsed.completed ?? {}, dismissed: parsed.dismissed ?? {}, nudged: parsed.nudged ?? {} };
  } catch {
    return null;
  }
}

function readProgress(userId: string): TourProgress {
  try {
    const own = parse(localStorage.getItem(keyFor(userId)));
    if (own) return own;
    // One-time move from the first release, which kept a single key for the whole browser.
    const legacy = parse(localStorage.getItem(LEGACY_KEY));
    if (legacy) {
      localStorage.setItem(keyFor(userId), JSON.stringify(legacy));
      localStorage.removeItem(LEGACY_KEY);
      return legacy;
    }
  } catch {
    /* storage blocked: every tip shows as new, which costs a nudge and nothing else */
  }
  return EMPTY_PROGRESS;
}

const SERVER_STATE: TourState = {
  active: null,
  hop: null,
  lastRect: null,
  progress: EMPTY_PROGRESS,
  progressReady: false,
  openedGroups: []
};

let state: TourState = SERVER_STATE;
let userId: string | null = null;

const listeners = new Set<() => void>();

function set(patch: Partial<TourState>) {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function save(progress: TourProgress) {
  if (!userId) return;
  try {
    localStorage.setItem(keyFor(userId), JSON.stringify(progress));
  } catch {
    /* a per-browser convenience; losing it costs one extra nudge */
  }
}

export const tourStore = {
  get: () => state,
  subscribe,
  /** Read the signed-in person's progress; a different person ends any running tour. */
  bindUser(next: string | null) {
    if (next === userId && state.progressReady) return;
    userId = next;
    if (!next) {
      set({ active: null, hop: null, lastRect: null, progress: EMPTY_PROGRESS, progressReady: false, openedGroups: [] });
      return;
    }
    set({ active: null, hop: null, lastRect: null, progress: readProgress(next), progressReady: true });
  },
  start(tourId: string, index = 0) {
    set({ active: { tourId, index }, hop: null });
  },
  goTo(index: number) {
    if (!state.active) return;
    set({ active: { ...state.active, index } });
  },
  /** Remember that a route is being opened for this step; cleared once its target is found. */
  hopTo(route: string) {
    if (!state.active) return;
    set({ hop: { route, tourId: state.active.tourId, index: state.active.index } });
  },
  clearHop() {
    if (state.hop) set({ hop: null });
  },
  setLastRect(rect: Rect | null) {
    set({ lastRect: rect });
  },
  rememberOpenedGroup(label: string) {
    if (!state.openedGroups.includes(label)) set({ openedGroups: [...state.openedGroups, label] });
  },
  /** The sections to close again; empties the list. */
  takeOpenedGroups(): string[] {
    const groups = state.openedGroups;
    if (groups.length) set({ openedGroups: [] });
    return groups;
  },
  end(reason: 'completed' | 'dismissed') {
    const active = state.active;
    if (!active) return;
    const progress: TourProgress = {
      ...state.progress,
      [reason]: { ...state.progress[reason], [active.tourId]: Date.now() }
    };
    save(progress);
    set({ active: null, hop: null, lastRect: null, progress });
  },
  dismissWithoutStarting(tourId: string) {
    const progress: TourProgress = { ...state.progress, dismissed: { ...state.progress.dismissed, [tourId]: Date.now() } };
    save(progress);
    set({ progress });
  },
  markNudged(tourId: string) {
    const progress: TourProgress = { ...state.progress, nudged: { ...state.progress.nudged, [tourId]: Date.now() } };
    save(progress);
    set({ progress });
  },
  /** Forget every completion, dismissal and nudge for this person (the "Reset tips" action). */
  reset() {
    save(EMPTY_PROGRESS);
    set({ active: null, hop: null, lastRect: null, progress: EMPTY_PROGRESS });
  }
};

export function useTourStore<T>(selector: (s: TourState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(SERVER_STATE)
  );
}

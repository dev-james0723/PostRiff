'use client';

/**
 * What a founder page tells Rafii (PRD §6.2, CONTRACTS §6): the section, an opaque selected entity, the chart in
 * view (its id, view version and query receipt), the period, the filters and an incident id. Pages register while
 * mounted; the most specific recent registration wins, exactly like the site agent's page context. The route itself
 * comes from the address, the outline from the screen (labels only, never typed values), and the mode from `?mode=`.
 */
import { useEffect, useId, useSyncExternalStore } from 'react';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { readPageOutline } from '@/features/site-agent/use-page-context';
import type { PageOutlineItem } from '@/lib/site-agent/types';
import { FOUNDER_MODES, type FounderChartContext, type FounderEnvironment, type FounderMode, type FounderPageContext } from './types';

export interface FounderPageRegistration {
  section?: string;
  selectedEntity?: { type: string; id: string } | null;
  chart?: FounderChartContext | null;
  period?: string | null;
  filters?: Record<string, string | number | boolean | string[]>;
  incidentId?: string | null;
}

/** What the panel can do with an answer: open a `/founder/…` page, or open the evidence drawer on a receipt. */
export const FOUNDER_UI_CAPABILITIES = ['navigate', 'open_evidence'] as const;

const registrations: { key: string; page: FounderPageRegistration }[] = [];
const listeners = new Set<() => void>();
let current: FounderPageRegistration | null = null;

function emit() {
  for (const listener of listeners) listener();
}

export const founderPageContext = {
  get: () => current,
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** A registration that selects something (an entity, a chart, an incident) is more specific than a page's plain values. */
  register(key: string, page: FounderPageRegistration | null) {
    const index = registrations.findIndex((item) => item.key === key);
    if (index >= 0) registrations.splice(index, 1);
    if (page) registrations.push({ key, page });
    const specific = registrations.findLast((item) => item.page.selectedEntity || item.page.chart || item.page.incidentId)?.page;
    const top = specific ?? registrations.at(-1)?.page ?? null;
    if (JSON.stringify(top) !== JSON.stringify(current)) {
      current = top;
      emit();
    }
  }
};

export function useFounderPageContext(context: FounderPageRegistration | null) {
  const id = useId();
  const key = JSON.stringify(context ?? null);
  useEffect(() => {
    founderPageContext.register(id, JSON.parse(key));
    return () => founderPageContext.register(id, null);
  }, [id, key]);
}

export function useRegisteredFounderContext(): FounderPageRegistration | null {
  return useSyncExternalStore(founderPageContext.subscribe, founderPageContext.get, () => null);
}

/** `/founder` is the Overview; `/founder/<section>` names its section; anything else is unknown. */
export function sectionFromPathname(pathname: string): string {
  if (pathname === '/founder' || pathname === '/founder/') return 'overview';
  const match = /^\/founder\/([a-z-]+)/.exec(pathname);
  return match ? match[1] : 'unknown';
}

/** The page context one turn carries; the outline is a hint and the turn goes without it when the screen can't be read. */
export function currentFounderPageContext(route: string, mode: FounderMode, environment: FounderEnvironment | null): FounderPageContext {
  const registered = founderPageContext.get();
  let outline: PageOutlineItem[] = [];
  try {
    outline = readPageOutline(document);
  } catch {
    /* the outline is a hint */
  }
  return {
    route,
    section: registered?.section ?? sectionFromPathname(route),
    mode,
    environment,
    selectedEntity: registered?.selectedEntity ?? null,
    chart: registered?.chart ?? null,
    period: registered?.period ?? null,
    filters: registered?.filters ?? {},
    incidentId: registered?.incidentId ?? null,
    uiCapabilities: [...FOUNDER_UI_CAPABILITIES],
    ...(outline.length ? { outline } : {})
  };
}

const modeParser = parseAsStringLiteral(FOUNDER_MODES).withDefault('live');

/** The data mode from the address (`?mode=demo`); Live is the default and Demo is never a fallback for it. */
export function useFounderMode(): [FounderMode, (mode: FounderMode) => void] {
  const [mode, setMode] = useQueryState('mode', modeParser);
  return [mode, (next) => void setMode(next === 'live' ? null : next)];
}

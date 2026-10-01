import type { ComponentType } from 'react';

/**
 * Registry of the founder domain sections (CONTRACTS §6). `app/founder/[section]/page.tsx` (web-shell) resolves a
 * section id to its lazily imported module; each module's default export is the section's client component.
 * Kept minimal on purpose: the shell owns routing, the sections own their content.
 */
export const FOUNDER_SECTIONS = ['customers', 'revenue', 'product', 'ai-cost', 'operations', 'support', 'settings', 'advanced'] as const;

export type FounderSection = (typeof FOUNDER_SECTIONS)[number];

/** What a page hands the founder Rafii panel when someone presses "Ask Rafii" (PRD §6.2 page context). */
export interface FounderAskRequest {
  prompt: string;
  section: FounderSection;
  /** An opaque id the server re-reads; never the record itself. */
  selectedEntity?: { type: string; id: string } | null;
  chart?: string;
  period?: string;
  filters?: Record<string, string>;
  incidentId?: string;
}

export interface FounderSectionProps {
  /**
   * Routes an Ask Rafii request to the founder panel store. When the shell passes nothing, the section dispatches a
   * `rafii:founder-ask` CustomEvent on `window` with the same request as `detail` so the panel can subscribe instead.
   */
  onAsk?: (request: FounderAskRequest) => void;
}

export function isFounderSection(value: string): value is FounderSection {
  return (FOUNDER_SECTIONS as readonly string[]).includes(value);
}

export const SECTIONS: Record<FounderSection, () => Promise<{ default: ComponentType<FounderSectionProps> }>> = {
  customers: () => import('./customers'),
  revenue: () => import('./revenue'),
  product: () => import('./product'),
  'ai-cost': () => import('./ai-cost'),
  operations: () => import('./operations'),
  support: () => import('./support'),
  settings: () => import('./settings'),
  advanced: () => import('./advanced')
};

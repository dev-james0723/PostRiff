'use client';

/** How Rafii talks to this person. Stub until the style slice lands; keeps the exported shape stable. */
import { DEFAULT_STYLE, type AgentStyle, type AgentStylePatch } from './style';

export function useAgentStyle(): { style: AgentStyle; save: (patch: AgentStylePatch) => Promise<void>; loading: boolean } {
  return { style: DEFAULT_STYLE, save: async () => undefined, loading: false };
}

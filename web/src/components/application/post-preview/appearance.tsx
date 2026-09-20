'use client';

import { createContext, useContext, useEffect } from 'react';

/** The reader's phone appearance. Always-dark apps (short-video players, Discord) keep one palette. */
export type Appearance = 'light' | 'dark';

interface AppearanceValue {
  appearance: Appearance;
  /** A template with a sourced dark palette says so, and the preview offers the light/dark switch. */
  declareDark: () => void;
}

export const AppearanceContext = createContext<AppearanceValue | null>(null);

/**
 * The palette for the reader's appearance, for templates whose dark colours come from the app's own tokens (see
 * docs/postriff-post-preview-templates.md). Templates without a sourced dark palette never call this, so the
 * preview does not offer a dark version it would have to invent.
 */
export function usePalette<T>(palettes: { light: T; dark: T }): T {
  const value = useContext(AppearanceContext);
  const declare = value?.declareDark;
  useEffect(() => declare?.(), [declare]);
  return palettes[value?.appearance ?? 'light'];
}

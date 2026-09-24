'use client';

/**
 * Person-level display preferences: the time zone schedules are written in and the language
 * dates and numbers are formatted with. Saved on the profile (`GET /api/me` → preferences);
 * empty means "follow this device". Mounted once inside the app gate, so everything that
 * formats a time reads the same choice.
 */

import { createContext, Fragment, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { useMe } from '@/lib/api/hooks';
import { setTimeDefaults } from '@/lib/time';

export interface Preferences {
  timeZone: string;
  locale: string;
  browserTimeZone: string;
  browserLocale: string;
  /** Where each value came from: a saved choice, or the browser. */
  timeZoneSource: 'profile' | 'browser';
  localeSource: 'profile' | 'browser';
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function browserLocale(): string {
  return typeof navigator !== 'undefined' && navigator.language ? navigator.language : 'en';
}

function resolve(saved?: { timeZone: string; locale: string }, hydrated = true): Preferences {
  const tz = hydrated ? browserTimeZone() : 'UTC';
  const loc = hydrated ? browserLocale() : 'en';
  return {
    timeZone: saved?.timeZone || tz,
    locale: saved?.locale || loc,
    browserTimeZone: tz,
    browserLocale: loc,
    timeZoneSource: saved?.timeZone ? 'profile' : 'browser',
    localeSource: saved?.locale ? 'profile' : 'browser'
  };
}

const subscribe = () => () => {};
const clientReady = () => true;
const serverReady = () => false;

const PreferencesContext = createContext<Preferences | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const me = useMe();
  const saved = me.data?.preferences;
  const hydrated = useSyncExternalStore(subscribe, clientReady, serverReady);
  const value = useMemo(() => resolve(saved, hydrated), [saved, hydrated]);
  // The formatting helpers read module defaults, and children format dates while rendering, so the
  // defaults are set here, before the subtree renders, rather than in an effect that would run after.
  // A changed choice re-keys the subtree so dates already on screen are formatted again.
  if (typeof window !== 'undefined') setTimeDefaults({ timeZone: value.timeZone, locale: value.locale });
  return (
    <PreferencesContext.Provider value={value}>
      <Fragment key={`${value.timeZone}|${value.locale}`}>{children}</Fragment>
    </PreferencesContext.Provider>
  );
}

/** Outside the provider (a standalone preview page) the browser's own settings apply. */
export function usePreferences(): Preferences {
  return useContext(PreferencesContext) ?? resolve();
}

/** The zone schedules and times should be written in for this person. */
export function useTimeZone(): string {
  return usePreferences().timeZone;
}

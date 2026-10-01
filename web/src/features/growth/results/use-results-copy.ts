'use client';

import { usePreferences } from '@/lib/preferences';
import { COPY, pickLanguage } from './present';

/** The panel's words in the person's saved language (Traditional Chinese or English), and the locale for numbers. */
export function useResultsCopy() {
  const { locale } = usePreferences();
  const lang = pickLanguage(locale);
  return { copy: COPY[lang], lang, locale };
}

'use client';

import { usePreferences } from '@/lib/preferences';
import { COPY, seriesLocale, type SeriesCopy } from './series-copy';

/** The series words in the person's chosen language (English or Traditional Chinese). */
export function useSeriesCopy(): SeriesCopy {
  return COPY[seriesLocale(usePreferences().locale)];
}

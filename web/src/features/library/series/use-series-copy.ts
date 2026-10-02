'use client';

import { usePreferences } from '@/lib/preferences';
import { COPY, seriesLocale, type SeriesCopy, type SeriesLocale } from './series-copy';

/** The series words in the person's chosen language (English or Traditional Chinese). */
export function useSeriesCopy(): SeriesCopy {
  return COPY[seriesLocale(usePreferences().locale)];
}

/** The `lang` for containers that show the series words (screen readers, CJK line breaking and fonts follow it). */
export function useSeriesLang(): SeriesLocale {
  return seriesLocale(usePreferences().locale);
}

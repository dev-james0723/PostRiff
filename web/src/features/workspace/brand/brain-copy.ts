'use client';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { traitLabel } from '@/lib/voice-import/labels';
/** The existing app preferences locale; authored content is never translated. */
export function useBrainCopy() {
  const locale = useGenUiLocale();
  return (en: string, hant: string, hans: string) => locale.language === 'zh-Hant' ? hant : locale.language === 'zh-Hans' ? hans : en;
}
/** A trait's readable name in the person's language, never the raw id (`sentence_length` reads "Sentence length"). */
export function useTraitLabel() {
  const locale = useGenUiLocale();
  return (id: string, dimension?: string | null) => traitLabel(id, locale.language, dimension);
}

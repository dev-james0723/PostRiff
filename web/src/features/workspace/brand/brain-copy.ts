'use client';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
/** The existing app preferences locale; authored content is never translated. */
export function useBrainCopy() {
  const locale = useGenUiLocale();
  return (en: string, hant: string, hans: string) => locale.language === 'zh-Hant' ? hant : locale.language === 'zh-Hans' ? hans : en;
}

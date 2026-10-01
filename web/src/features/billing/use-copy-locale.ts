'use client';

import { usePreferences } from '@/lib/preferences';
import { billingCopy, copyLocale, type BillingCopy, type CopyLocale } from './billing-mode-copy';

/**
 * The language for Pricing v2 billing copy: Traditional Chinese only when the person saved a Traditional Chinese
 * language on their profile (the app's own copy is English; a browser default alone does not switch it).
 */
export function useCopyLocale(): CopyLocale {
  const prefs = usePreferences();
  return prefs.localeSource === 'profile' ? copyLocale(prefs.locale) : 'en';
}

export function useBillingCopy(): BillingCopy {
  return billingCopy(useCopyLocale());
}

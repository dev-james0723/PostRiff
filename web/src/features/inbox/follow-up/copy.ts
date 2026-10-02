import { errorCode, errorMessage } from '@/lib/growth-v2/request';
import { followUpCopy, followUpLocale, isConflict, type FollowUpCopy, type FollowUpLocale } from '@/lib/growth-v2/relationships-model';
import { formatDateTime, timeDefaults } from '@/lib/time';

export interface FollowUpProblem {
  message: string;
  /** Someone changed the follow-up meanwhile: offer to reload it. */
  conflict: boolean;
  /** Our own wording is in the person's language; a server refusal is English. */
  lang: string;
}

/** A refused change in words: conflicts and refused "won" results in the person's language, anything else as the
 * server said it (English, marked so), and our own fallback when the server said nothing. */
export function describeProblem(cause: unknown, copy: FollowUpCopy = currentCopy(), conflict = copy.conflict): FollowUpProblem {
  const code = errorCode(cause);
  if (isConflict(code)) return { message: conflict, conflict: true, lang: currentLang() };
  if (code === 'result_required') return { message: copy.wonRefused, conflict: false, lang: currentLang() };
  const message = errorMessage(cause, '');
  return message ? { message, conflict: false, lang: 'en' } : { message: copy.failed, conflict: false, lang: currentLang() };
}

/**
 * Follow-up wording in the person's language: the same preference that writes their dates and numbers
 * (`PreferencesProvider` → `setTimeDefaults`). Traditional Chinese or English.
 */
export function currentCopy(): FollowUpCopy {
  return followUpCopy(timeDefaults().locale);
}

/** The `lang` of that wording, set on every follow-up container (and on toasts and portalled panels) so assistive
 * technology reads Traditional Chinese as Chinese inside an English page, and English as English. */
export function currentLang(): FollowUpLocale {
  return followUpLocale(timeDefaults().locale);
}

/**
 * An instant in the person's language ("1 Nov 2026, 01:30"): in `zone` when given (a due time reads in the zone it was
 * chosen in), otherwise in the person's own zone.
 */
export function when(epoch: number | null | undefined, zone?: string | null): string {
  if (!zone || !epoch) return formatDateTime(epoch ?? null);
  try {
    return new Intl.DateTimeFormat(timeDefaults().locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: zone }).format(new Date(epoch * 1000));
  } catch {
    return formatDateTime(epoch);
  }
}

/** DOM id of a thread's reply composer area, so "Reply" on a follow-up can move focus to it. */
export function composerAnchor(threadId: string): string {
  return `inbox-composer-${threadId}`;
}

/** Scroll to a thread's composer and focus its text field (reduced motion: no smooth scrolling). */
export function focusComposer(threadId: string): boolean {
  const anchor = typeof document === 'undefined' ? null : document.getElementById(composerAnchor(threadId));
  if (!anchor) return false;
  const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  anchor.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  const field = anchor.querySelector<HTMLTextAreaElement>('textarea:not([readonly])');
  field?.focus({ preventScroll: true });
  return Boolean(field);
}

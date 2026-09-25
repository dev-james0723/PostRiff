import type { TimeSavingsBaselineSource, TimeSavingsConfidence, TimeSavingsRange, TimeSavingsTaskKind } from '@/lib/api/types';

/**
 * Time back words and formats (docs/raffi-time-back/ENGINEERING.md §11-13), shared by the Overview stat and the
 * Analytics section. An estimate is never called exact: "Time back" is the headline, "estimated time saved" the
 * explanation. Minutes come from the server already allocated so a breakdown adds up to its total.
 */

/** "8h 42m", "42m", "2h". Whole minutes only; never seconds. */
export function formatMinutes(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes));
  if (whole < 60) return `${whole}m`;
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

/** The same duration for a screen reader: "8 hours 42 minutes". */
export function spokenMinutes(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes));
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  const parts = [hours ? `${hours} ${hours === 1 ? 'hour' : 'hours'}` : '', rest || !hours ? `${rest} ${rest === 1 ? 'minute' : 'minutes'}` : ''];
  return parts.filter(Boolean).join(' ');
}

export function completedLabel(count: number) {
  return `${count} completed ${count === 1 ? 'workflow' : 'workflows'}`;
}

export const RANGE_OPTIONS: { value: TimeSavingsRange; label: string }[] = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'year', label: 'This year' },
  { value: 'all', label: 'All time' }
];

/** One line per task kind: what was completed, in the plural the count needs. */
export const TASK: Record<TimeSavingsTaskKind, { one: string; many: string; question: string; setting: string }> = {
  draft: { one: 'post drafted', many: 'posts drafted', question: 'writing a post like this', setting: 'Writing a post' },
  adapt: { one: 'version for another platform', many: 'versions for other platforms', question: 'rewriting a post for another platform', setting: 'A version for another platform' },
  publish: { one: 'post published', many: 'posts published', question: 'posting on a platform yourself', setting: 'Posting on a platform' },
  campaign_plan: { one: 'campaign planned', many: 'campaigns planned', question: 'planning a campaign', setting: 'Planning a campaign' },
  recurring_setup: { one: 'automation set up', many: 'automations set up', question: 'setting up a recurring post plan', setting: 'Setting up an automation' }
};

export function taskLine(kind: TimeSavingsTaskKind, count: number) {
  return `${count} ${count === 1 ? TASK[kind].one : TASK[kind].many}`;
}

/** Badge words and their one-line meaning (§12). */
export const CONFIDENCE: Record<TimeSavingsConfidence, { badge: string; meaning: string; phrase: string }> = {
  estimated: { badge: 'Estimated', meaning: 'Estimated with Rafii’s defaults', phrase: 'estimated with Rafii’s defaults' },
  personalized: { badge: 'Personalized', meaning: 'Personalized from your answers', phrase: 'personalized from your answers' },
  measured: { badge: 'Measured', meaning: 'Measured from your active time in Rafii', phrase: 'measured from your active time in Rafii' }
};

export const BASELINE_SOURCE: Record<TimeSavingsBaselineSource, string> = {
  raffi_default: 'Rafii’s estimate',
  personalized: 'from your answers',
  user_override: 'your setting'
};

/** "Before Rafii, about how long would this usually take you?" answers, in minutes. */
export const CALIBRATION_CHOICES = [5, 10, 15, 20, 30, 45, 60];
/** Shown after "More than 1 hour", so a long task is recorded as the person says, not guessed. */
export const LONGER_CHOICES = [90, 120, 180, 240];

export function minutesLabel(minutes: number) {
  if (minutes < 60) return `${minutes} min`;
  if (minutes === 90) return '1½ hours';
  return minutes === 60 ? '1 hour' : `${minutes / 60} hours`;
}

/** "How is this calculated?" — every point the spec requires, in plain words. */
export const HOW_IT_WORKS = [
  { title: 'Completed work only', description: 'A draft you approve for publishing, each extra platform version, a post the platform confirmed, and an automation you switch on. Unused drafts, suggestions and failed posts count for nothing.' },
  { title: 'Typical time, minus your time', description: 'Each task counts a typical time for doing it without Rafii, minus the time you actively spent on it here when that was measured.' },
  { title: 'Inactive time is left out', description: 'Active time counts only while Rafii is on screen and you typed, clicked, scrolled or touched in the last 75 seconds. Idle tabs and writing that runs in the background are not counted.' },
  { title: 'Your own estimates', description: 'Answer a quick question after finishing a task, or set your own times below. After three answers, your typical time replaces Rafii’s estimate for future work.' },
  { title: 'Counted once', description: 'Each piece of work is counted once, even if it is retried or confirmed again. Views, likes and other platform numbers are separate and never part of this total.' }
];

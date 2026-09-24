/**
 * Pure helpers for Automations: weekday schedules, next-run previews, run and status wording, and the
 * budget ceiling. The server (`campaigns.next_occurrence`) is the authority for when a run happens; the
 * preview here follows the same rules so the builder can show the next runs before anything is saved:
 * the first local time strictly after "now" across the chosen weekdays; a skipped wall time (spring)
 * moves to the next valid minute; a repeated one (autumn) uses its first, earlier-offset instance.
 */

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;
export type Weekday = (typeof WEEKDAYS)[number];
export const WEEKDAY_SHORT: Record<Weekday, string> = { Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed', Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun' };

export type ScheduleKind = 'weekly' | 'monthly' | 'countdown' | 'on_new_source' | 'on_strong_post';
export type TriggerKind = 'on_new_source' | 'on_strong_post';
export const SOURCE_KINDS = [
  { value: 'idea', label: 'Ideas' },
  { value: 'text', label: 'Notes' },
  { value: 'link', label: 'Links' },
  { value: 'document', label: 'Documents' }
] as const;
export type MonthDay = number | 'last';

export interface ScheduleValue {
  /** Absent means weekly (the original shape). */
  kind?: ScheduleKind | string;
  weekdays?: string[];
  weekday?: string;
  /** Monthly: 1–31 or "last"; a day a month lacks runs on its last day. */
  monthDays?: MonthDay[];
  /** Countdown: the event date (YYYY-MM-DD) and the days before it that get a run. */
  eventDate?: string;
  daysBefore?: number[];
  /** Triggers: what starts a run, and at most how many runs a day. */
  sourceKinds?: string[];
  maxPerDay?: number;
  withinDays?: number;
  /** Absent for triggers. */
  localTime?: string;
  timeZone: string;
}

const KNOWN: ScheduleKind[] = ['monthly', 'countdown', 'on_new_source', 'on_strong_post'];
export const kindOf = (schedule: Pick<ScheduleValue, 'kind'>): ScheduleKind => (KNOWN.includes(schedule.kind as ScheduleKind) ? (schedule.kind as ScheduleKind) : 'weekly');
export const isTrigger = (schedule: Pick<ScheduleValue, 'kind'>): boolean => schedule.kind === 'on_new_source' || schedule.kind === 'on_strong_post';

export function monthDaysOf(schedule: Pick<ScheduleValue, 'monthDays'>): MonthDay[] {
  const valid = (schedule.monthDays ?? []).filter((d): d is MonthDay => d === 'last' || (Number.isInteger(d) && (d as number) >= 1 && (d as number) <= 31));
  return Array.from(new Set(valid)).toSorted((a, b) => (a === 'last' ? 32 : a) - (b === 'last' ? 32 : b));
}

export function daysBeforeOf(schedule: Pick<ScheduleValue, 'daysBefore'>): number[] {
  return Array.from(new Set((schedule.daysBefore ?? []).filter((d) => Number.isInteger(d) && d >= 0 && d <= 90))).toSorted((a, b) => b - a);
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
function parseDate(value: string | undefined): { year: number; month: number; day: number } | null {
  const match = ISO_DATE.exec(value ?? '');
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const probe = new Date(Date.UTC(year, month - 1, day));
  return probe.getUTCMonth() === month - 1 && probe.getUTCDate() === day ? { year, month, day } : null;
}

const SHORT_INDEX: Record<string, number> = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
const formatters = new Map<string, Intl.DateTimeFormat>();

/** Weekday names of a schedule in Monday-first order; the legacy single `weekday` counts as one. */
export function weekdaysOf(schedule: Pick<ScheduleValue, 'weekdays' | 'weekday'>): Weekday[] {
  const raw = Array.isArray(schedule.weekdays) ? schedule.weekdays : schedule.weekday ? [schedule.weekday] : [];
  const wanted = new Set(raw.map((day) => String(day).toLowerCase()));
  return WEEKDAYS.filter((day) => wanted.has(day.toLowerCase()));
}

export function parseTime(value: string): { hour: number; minute: number } | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return hour <= 23 && minute <= 59 ? { hour, minute } : null;
}

export function validTimeZone(timeZone: string): boolean {
  if (!timeZone) return false;
  try {
    return Boolean(new Intl.DateTimeFormat('en-US', { timeZone }).resolvedOptions().timeZone);
  } catch {
    return false;
  }
}

function formatter(timeZone: string): Intl.DateTimeFormat {
  let found = formatters.get(timeZone);
  if (!found) {
    found = new Intl.DateTimeFormat('en-US', { timeZone, hourCycle: 'h23', weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    formatters.set(timeZone, found);
  }
  return found;
}

interface WallParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  weekday: number;
}

function wallAt(ms: number, timeZone: string): WallParts {
  const parts: Record<string, string> = {};
  for (const part of formatter(timeZone).formatToParts(new Date(ms))) parts[part.type] = part.value;
  return { year: Number(parts.year), month: Number(parts.month), day: Number(parts.day), hour: Number(parts.hour) % 24, minute: Number(parts.minute), second: Number(parts.second), weekday: SHORT_INDEX[parts.weekday] ?? 0 };
}

/** Local wall time as a comparable number (the wall clock read as if it were UTC). */
const wallNumber = (p: Pick<WallParts, 'year' | 'month' | 'day' | 'hour' | 'minute' | 'second'>) => Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);

/** The instant for a local wall time, or null when that wall time does not exist in the zone (a spring gap). */
function instantFor(year: number, month: number, day: number, hour: number, minute: number, timeZone: string): number | null {
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  // Try the offsets in force a day either side; the earlier instant first, so a repeated time uses its first occurrence.
  const candidates = [wall - 36 * 3600_000, wall + 36 * 3600_000].map((probe) => wall - (wallNumber(wallAt(probe, timeZone)) - Math.floor(probe / 1000) * 1000));
  for (const instant of candidates.toSorted((a, b) => a - b)) {
    const back = wallAt(instant, timeZone);
    if (back.year === year && back.month === month && back.day === day && back.hour === hour && back.minute === minute) return instant;
  }
  return null;
}

function nextForWeekday(now: WallParts, weekday: number, hour: number, minute: number, timeZone: string): number | null {
  const days = (weekday - now.weekday + 7) % 7;
  let date = new Date(Date.UTC(now.year, now.month - 1, now.day + days));
  let wall = { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate(), hour, minute, second: 0 };
  if (wallNumber(wall) <= wallNumber(now)) {
    date = new Date(Date.UTC(wall.year, wall.month - 1, wall.day + 7));
    wall = { ...wall, year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() };
  }
  // A skipped wall time moves to the next valid local minute (at most three hours later).
  for (let step = 0; step < 180; step += 1) {
    const at = new Date(Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute + step));
    const instant = instantFor(at.getUTCFullYear(), at.getUTCMonth() + 1, at.getUTCDate(), at.getUTCHours(), at.getUTCMinutes(), timeZone);
    if (instant !== null) return instant;
  }
  return null;
}

/** The first valid instant at or after a wall time (a skipped wall time moves to the next valid minute). */
function validInstant(year: number, month: number, day: number, hour: number, minute: number, timeZone: string): number | null {
  for (let step = 0; step < 180; step += 1) {
    const at = new Date(Date.UTC(year, month - 1, day, hour, minute + step));
    const instant = instantFor(at.getUTCFullYear(), at.getUTCMonth() + 1, at.getUTCDate(), at.getUTCHours(), at.getUTCMinutes(), timeZone);
    if (instant !== null) return instant;
  }
  return null;
}

/** The next run strictly after `afterMs`, as epoch milliseconds, or null for an incomplete or finished schedule. */
export function nextRun(schedule: ScheduleValue, afterMs: number): number | null {
  if (isTrigger(schedule)) return null;
  const time = parseTime(schedule.localTime ?? '');
  if (!time || !validTimeZone(schedule.timeZone)) return null;
  const now = wallAt(afterMs, schedule.timeZone);
  const kind = kindOf(schedule);
  if (kind === 'monthly') {
    const days = monthDaysOf(schedule);
    if (!days.length) return null;
    let year = now.year;
    let month = now.month;
    for (let i = 0; i < 14; i += 1) {
      const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
      const dates = Array.from(new Set(days.map((d) => (d === 'last' ? last : Math.min(d, last))))).toSorted((a, b) => a - b);
      for (const day of dates) {
        if (wallNumber({ year, month, day, hour: time.hour, minute: time.minute, second: 0 }) > wallNumber(now)) return validInstant(year, month, day, time.hour, time.minute, schedule.timeZone);
      }
      [year, month] = month === 12 ? [year + 1, 1] : [year, month + 1];
    }
    return null;
  }
  if (kind === 'countdown') {
    const event = parseDate(schedule.eventDate);
    const before = daysBeforeOf(schedule);
    if (!event || !before.length) return null;
    for (const days of before) {
      const date = new Date(Date.UTC(event.year, event.month - 1, event.day - days));
      const wall = { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate(), hour: time.hour, minute: time.minute, second: 0 };
      if (wallNumber(wall) > wallNumber(now)) return validInstant(wall.year, wall.month, wall.day, time.hour, time.minute, schedule.timeZone);
    }
    return null;
  }
  const days = weekdaysOf(schedule);
  if (!days.length) return null;
  const runs = days.map((day) => nextForWeekday(now, WEEKDAYS.indexOf(day), time.hour, time.minute, schedule.timeZone)).filter((run): run is number => run !== null);
  return runs.length ? Math.min(...runs) : null;
}

/** The next `count` runs after `afterMs`. */
export function nextRuns(schedule: ScheduleValue, afterMs: number, count = 3): number[] {
  const out: number[] = [];
  let cursor = afterMs;
  for (let i = 0; i < count; i += 1) {
    const run = nextRun(schedule, cursor);
    if (run === null) break;
    out.push(run);
    cursor = run + 1000;
  }
  return out;
}

/** "Every day", "Weekdays", "Weekends", "Mondays", "Mon, Wed and Fri". */
export function daysLabel(schedule: Pick<ScheduleValue, 'weekdays' | 'weekday'>): string {
  const days = weekdaysOf(schedule);
  if (days.length === 7) return 'Every day';
  if (days.length === 5 && days.every((day) => WEEKDAYS.indexOf(day) < 5)) return 'Weekdays';
  if (days.length === 2 && days[0] === 'Saturday' && days[1] === 'Sunday') return 'Weekends';
  if (days.length === 1) return `${days[0]}s`;
  const short = days.map((day) => WEEKDAY_SHORT[day]);
  return short.length ? `${short.slice(0, -1).join(', ')} and ${short.at(-1)}` : 'No days chosen';
}

/** "09:00" as the viewer's clock format, e.g. "9:00 AM" or "09:00". */
export function timeLabel(localTime: string, locale?: string): string {
  const time = parseTime(localTime);
  if (!time) return localTime;
  return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }).format(new Date(Date.UTC(2000, 0, 3, time.hour, time.minute)));
}

/** "Asia/Hong_Kong" → "Hong Kong". */
export function zoneLabel(timeZone: string): string {
  const last = timeZone.split('/').at(-1) ?? timeZone;
  return last.replaceAll('_', ' ');
}

const ordinal = (n: number) => `${n}${n % 10 === 1 && n % 100 !== 11 ? 'st' : n % 10 === 2 && n % 100 !== 12 ? 'nd' : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th'}`;

/** "Monthly on the 1st and 15th", "Monthly on the last day". */
export function monthDaysLabel(schedule: Pick<ScheduleValue, 'monthDays'>): string {
  const days = monthDaysOf(schedule).map((d) => (d === 'last' ? 'last day' : ordinal(d)));
  return days.length ? `Monthly on the ${days.length > 1 ? `${days.slice(0, -1).join(', ')} and ${days.at(-1)}` : days[0]}` : 'No days chosen';
}

/** "Countdown to 18 Oct: 14, 7, 1 days before and on the day". */
export function countdownLabel(schedule: Pick<ScheduleValue, 'eventDate' | 'daysBefore'>, locale?: string): string {
  const event = parseDate(schedule.eventDate);
  if (!event) return 'Countdown (choose the event date)';
  const date = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(event.year, event.month - 1, event.day)));
  const before = daysBeforeOf(schedule);
  const steps = before.filter((d) => d > 0);
  const parts = [steps.length ? `${steps.join(', ')} day${steps.length === 1 && steps[0] === 1 ? '' : 's'} before` : '', before.includes(0) ? 'on the day' : ''].filter(Boolean);
  return `Countdown to ${date}${parts.length ? `: ${parts.join(' and ')}` : ''}`;
}

/** "When you add an idea or a link · up to 3 a day" for triggers. */
export function triggerLabel(schedule: ScheduleValue): string {
  const perDay = schedule.maxPerDay ?? 1;
  const limit = `up to ${perDay} run${perDay === 1 ? '' : 's'} a day`;
  if (schedule.kind === 'on_strong_post') return `After a post gets more replies or comments than usual (last ${schedule.withinDays ?? 7} days) · ${limit}`;
  const names = SOURCE_KINDS.filter((k) => (schedule.sourceKinds ?? SOURCE_KINDS.map((s) => s.value)).includes(k.value)).map((k) => k.label.toLowerCase().replace(/s$/, ''));
  const what = names.length > 1 ? `${names.slice(0, -1).join(', ')} or ${names.at(-1)}` : (names[0] ?? 'item');
  return `When you add a new ${what} to Ideas · ${limit}`;
}

/** "Mondays and Thursdays at 9:00 AM · Hong Kong time" style summary, for every schedule kind. */
export function scheduleSummary(schedule: ScheduleValue, locale?: string): string {
  if (isTrigger(schedule)) return triggerLabel(schedule);
  const kind = kindOf(schedule);
  const days = kind === 'monthly' ? monthDaysLabel(schedule) : kind === 'countdown' ? countdownLabel(schedule, locale) : daysLabel(schedule);
  return `${days} at ${timeLabel(schedule.localTime ?? '', locale)} · ${zoneLabel(schedule.timeZone)} time`;
}

/** A run instant as "Wed 4 Mar, 9:00 AM" in the given zone. */
export function runLabel(ms: number, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(ms));
}

/** Runs in an average week: one per chosen weekday. */
export function runsPerWeek(schedule: Pick<ScheduleValue, 'weekdays' | 'weekday'>): number {
  return weekdaysOf(schedule).length;
}

/**
 * The most runs a schedule can have, and over what: a calendar month for weekly (a month can hold five of a
 * weekday) and monthly schedules, the whole countdown for a countdown.
 */
export function maxRuns(schedule: ScheduleValue): { runs: number; per: 'month' | 'countdown' } {
  if (isTrigger(schedule)) return { runs: (schedule.maxPerDay ?? 1) * 31, per: 'month' };
  const kind = kindOf(schedule);
  if (kind === 'monthly') return { runs: monthDaysOf(schedule).length, per: 'month' };
  if (kind === 'countdown') return { runs: daysBeforeOf(schedule).length, per: 'countdown' };
  return { runs: weekdaysOf(schedule).length * 5, per: 'month' };
}

/** The budget ceiling: the per-run limit times the most runs (a month, or the whole countdown). */
export function ceilingMicro(maxCostUsdMicro: number | undefined, schedule: ScheduleValue): number {
  return Math.max(0, maxCostUsdMicro ?? 0) * maxRuns(schedule).runs;
}

export function ceilingText(maxCostUsdMicro: number | undefined, schedule: ScheduleValue): string {
  const { runs, per } = maxRuns(schedule);
  const total = usd(ceilingMicro(maxCostUsdMicro, schedule));
  return per === 'countdown' ? `${runs} run${runs === 1 ? '' : 's'} in total · at most ${total} for the whole countdown` : `up to ${runs} run${runs === 1 ? '' : 's'} a month · at most ${total} a month`;
}

export function usd(micro: number): string {
  const dollars = micro / 1_000_000;
  return `$${dollars.toFixed(dollars > 0 && dollars < 0.1 ? 3 : 2)}`;
}

/** The most an automation can spend in a week: its per-run limit times the runs a week. */
export function weeklyCeilingMicro(maxCostUsdMicro: number | undefined, schedule: Pick<ScheduleValue, 'weekdays' | 'weekday'>): number {
  return Math.max(0, maxCostUsdMicro ?? 0) * runsPerWeek(schedule);
}

const HELD: Record<string, string> = {
  writer_failed_or_unavailable: 'The writer was unavailable, so no drafts were made.',
  new_preview_required: 'The automation needs a new review before it can run.',
  owner_authority_unavailable: 'The owner who activated it no longer has access.',
  destinations_unavailable: 'None of its accounts is connected any more.'
};

/** Plain words for one run: a short state and, when useful, why. */
export function runText(run: { state: string; reason?: string }): { label: string; detail?: string; tone: 'quiet' | 'success' | 'attention' | 'failure' } {
  switch (run.state) {
    case 'completed':
      return { label: 'Drafts ready', tone: 'success' };
    case 'running':
      return { label: 'Writing now', tone: 'quiet' };
    case 'pending':
      return { label: 'Queued', tone: 'quiet' };
    case 'held':
      return { label: 'Held', detail: HELD[run.reason ?? ''] ?? 'Rafii held this run for review.', tone: 'attention' };
    case 'missed':
      return { label: 'Missed', detail: 'The run was more than a day late, so it was skipped.', tone: 'attention' };
    case 'cancelled':
      return { label: 'Cancelled', detail: run.reason === 'definition_changed' ? 'The automation was edited before this run.' : 'The automation was paused or cancelled before this run.', tone: 'quiet' };
    case 'failed':
      return { label: 'Failed', detail: 'The run did not finish.', tone: 'failure' };
    default:
      return { label: run.state, tone: 'quiet' };
  }
}

const PAUSED: Record<string, string> = {
  destinations_unavailable: 'Paused: none of its accounts is connected. Edit it to choose new destinations.',
  new_preview_required: 'Paused: it needs a new review. Edit and save it, then activate it again.',
  campaign_changed: 'Paused: its brief changed. Edit and save it, then activate it again.'
};

/** The automation's status in words; `needsOwner` when only an owner can move it forward. */
export function statusText(task: { status: string; pauseReason?: string }): { label: string; detail: string; needsOwner: boolean; needsEdit: boolean } {
  switch (task.status) {
    case 'active':
      return { label: 'Active', detail: 'Preparing drafts on schedule.', needsOwner: false, needsEdit: false };
    case 'draft':
      return { label: 'Draft', detail: 'Waiting for the workspace owner to activate it.', needsOwner: true, needsEdit: false };
    case 'paused':
      return task.pauseReason
        ? { label: 'Needs review', detail: PAUSED[task.pauseReason] ?? 'Paused until it is reviewed again.', needsOwner: false, needsEdit: true }
        : { label: 'Paused', detail: 'No drafts are prepared until it is resumed.', needsOwner: true, needsEdit: false };
    case 'cancelled':
      return { label: 'Cancelled', detail: 'No further drafts will be prepared.', needsOwner: false, needsEdit: false };
    default:
      return { label: task.status, detail: '', needsOwner: false, needsEdit: false };
  }
}

/** Mirrors `campaigns.missing_facts`: an event brief needs its date and venue before it can be activated. */
const EVENT_WORDS = ['concert', 'event', 'festival', 'recital', '音樂會', '演奏會', '活動', '音樂節'];
export function missingFacts(goal: string, facts: Record<string, string>): string[] {
  const lower = goal.toLocaleLowerCase();
  if (!EVENT_WORDS.some((word) => lower.includes(word))) return [];
  return (['date', 'venue'] as const).filter((key) => !facts[key]?.trim());
}

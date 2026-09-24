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

export interface ScheduleValue {
  weekdays?: string[];
  weekday?: string;
  localTime: string;
  timeZone: string;
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

/** The next run strictly after `afterMs`, as epoch milliseconds, or null for an incomplete schedule. */
export function nextRun(schedule: ScheduleValue, afterMs: number): number | null {
  const time = parseTime(schedule.localTime);
  const days = weekdaysOf(schedule);
  if (!time || !days.length || !validTimeZone(schedule.timeZone)) return null;
  const now = wallAt(afterMs, schedule.timeZone);
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

/** "Mondays and Thursdays at 9:00 AM · Hong Kong time" style summary. */
export function scheduleSummary(schedule: ScheduleValue, locale?: string): string {
  return `${daysLabel(schedule)} at ${timeLabel(schedule.localTime, locale)} · ${zoneLabel(schedule.timeZone)} time`;
}

/** A run instant as "Wed 4 Mar, 9:00 AM" in the given zone. */
export function runLabel(ms: number, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone, weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(ms));
}

/** Runs in an average week: one per chosen weekday. */
export function runsPerWeek(schedule: Pick<ScheduleValue, 'weekdays' | 'weekday'>): number {
  return weekdaysOf(schedule).length;
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

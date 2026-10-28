import { WORKSPACE_HOURLY_CEILING, type DiscordCopy } from './discord-copy';

/**
 * The Discord hourly ceiling (owner decision, reply 16; docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md): a
 * workspace may have at most `WORKSPACE_HOURLY_CEILING` approved Discord posts scheduled within any one hour, and the
 * approval that would make the next one is refused with `409` and this `code`. It is a conflict with the workspace's
 * own plan, not throttling: there is no retry time, so nothing here counts down or sends the request again. The person
 * changes the plan (another time, fewer posts in that hour) and approves again.
 */
export const HOURLY_CEILING_CODE = 'discord_workspace_hourly_ceiling';

/** The places a person meets the refusal; each says in its own words what was and was not approved. */
export type CeilingPlace = 'single' | 'bulk' | 'decision' | 'reply';

/** Branch on the code, never on the English text. */
export function isHourlyCeiling(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { code?: unknown }).code === HOURLY_CEILING_CODE;
}

const LIMIT_MAX = 1_000_000;

/**
 * The number to write into the text. The refusal's own `limit` when the response carried it (`ApiError.body`, which the
 * sender-name editor already reads), else the one constant. Anything that is not a plain positive whole number is ignored.
 */
export function hourlyCeilingLimit(error: unknown): number {
  const body = typeof error === 'object' && error !== null ? (error as { body?: unknown }).body : undefined;
  const sent = typeof body === 'object' && body !== null ? (body as { limit?: unknown }).limit : undefined;
  return typeof sent === 'number' && Number.isSafeInteger(sent) && sent >= 1 && sent <= LIMIT_MAX ? sent : WORKSPACE_HOURLY_CEILING;
}

const STATE = {
  single: 'hourlyCeilingNothingApproved',
  bulk: 'hourlyCeilingBulkNone',
  decision: 'hourlyCeilingDecision',
  reply: 'hourlyCeilingReply'
} as const satisfies Record<CeilingPlace, keyof DiscordCopy>;

/** What is left undone at this place: nothing was approved, and where the post still waits. */
export function hourlyCeilingState(copy: DiscordCopy, place: CeilingPlace): string {
  return copy[STATE[place]];
}

/**
 * When the scheduler's queue attempts ran out, the post's reason is the server's English sentence ("It couldn't be
 * queued: This hour is full: a workspace can have at most N approved Discord posts ..."), with no code beside it.
 * Recognize that sentence and answer in the person's language; any other reason is left to the caller (null).
 */
const QUEUE_FAILURE = /This hour is full:\s+a workspace can have at most\s+(\d{1,7})\s+approved Discord posts/i;

export function queueFailureText(copy: DiscordCopy, reason: string | null | undefined): string | null {
  const found = typeof reason === 'string' ? QUEUE_FAILURE.exec(reason) : null;
  if (!found) return null;
  const sent = Number(found[1]);
  const limit = Number.isSafeInteger(sent) && sent >= 1 ? sent : WORKSPACE_HOURLY_CEILING;
  return copy.hourlyCeilingQueueFailed.replace('{limit}', String(limit));
}

/**
 * The Calendar's day view for the day an instant falls on in `timeZone`, which must be the zone the Calendar places
 * posts in (the browser's). The Calendar has no per-hour view, so the day is the closest honest destination.
 */
export function calendarDayHref(whenMs: number | null | undefined, timeZone: string | null | undefined): string {
  if (typeof whenMs !== 'number' || !Number.isFinite(whenMs) || !timeZone) return '/app/calendar';
  try {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
        .formatToParts(whenMs)
        .map((part) => [part.type, part.value])
    );
    return `/app/calendar?view=day&date=${parts.year}-${parts.month}-${parts.day}`;
  } catch {
    return '/app/calendar';
  }
}

/** The Queue's Drafts view with the draft open, where a new time can be chosen. Null when the post has no draft id. */
export function draftHref(variantId: string | null | undefined): string | null {
  return variantId ? `/app/queue?view=drafts&draft=${encodeURIComponent(variantId)}` : null;
}

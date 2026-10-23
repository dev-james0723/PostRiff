/**
 * Customer-set Discord sender names: the limits and validation rules the server applies, and the states the
 * editor can be in. No React and no `@/` imports, so the node tests load it directly.
 *
 * The server (`sender_names.validate_name`) is the authority. These rules are a copy of it so a person sees the
 * problem before saving; `tests/test_discord_sender_name_ui_contract.py` checks the shared verdict fixture against
 * the real validator and `tests/discord-sender-name.test.cjs` checks this file against the same fixture.
 */

export type SenderKind = 'webhook' | 'bot';

/** Characters allowed, counted in Unicode code points (Python `len`), as the backend counts them. */
export const SENDER_LIMIT: Record<SenderKind, number> = { webhook: 80, bot: 32 };

/** Webhook names may not contain these after case folding (Discord refuses them for webhook usernames). */
export const RESERVED_WEBHOOK_WORDS = ['discord', 'clyde'] as const;

export type SenderNameIssue = 'empty' | 'surrounding_space' | 'too_long' | 'not_nfc' | 'control_character' | 'reserved_word';

/** Order the server tests them in; the editor lists every one that applies. */
export const SENDER_NAME_ISSUES: readonly SenderNameIssue[] = ['empty', 'surrounding_space', 'too_long', 'not_nfc', 'control_character', 'reserved_word'];

/** Number of Unicode code points (a lone surrogate counts as one, as in Python). */
export function codePointLength(text: string): number {
  return Array.from(text).length;
}

// Python `str.strip()` removes characters for which `str.isspace()` is true. JavaScript `trim()` differs at U+FEFF
// (trimmed by JS only) and U+001C to U+001F and U+0085 (stripped by Python only); every one of those is a control or
// format character that the server rejects anyway, so the verdict is the same and only the label can differ.
const PYTHON_SPACE = '\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const ONLY_SPACE = new RegExp(`^[${PYTHON_SPACE}]*$`);
const EDGE_SPACE = new RegExp(`^[${PYTHON_SPACE}]|[${PYTHON_SPACE}]$`);
/** Unicode category C* (control, format, surrogate, private use, unassigned) plus the line and paragraph separators. */
const CONTROL_OR_FORMAT = new RegExp('[\\p{C}\\u2028\\u2029]', 'u');

/**
 * Case folding as Python's `casefold()` applies it to the two reserved words. Lower-casing matches it for every
 * character that can complete "discord" or "clyde" except the long s (U+017F), which folds to "s"; the dotted
 * capital I folds to "i" plus a combining dot in both, so it does not match, and the dotless i stays itself.
 */
export function foldForReserved(text: string): string {
  return text.toLowerCase().replace(/ſ/g, 's');
}

export interface SenderNameCheck {
  /** Length in code points. */
  length: number;
  limit: number;
  /** Every rule the name breaks; empty means the server would accept it. */
  issues: SenderNameIssue[];
  /** Characters over the limit, 0 when within it. */
  over: number;
}

export function checkSenderName(name: string, kind: SenderKind, limit: number = SENDER_LIMIT[kind]): SenderNameCheck {
  const length = codePointLength(name);
  const issues: SenderNameIssue[] = [];
  if (ONLY_SPACE.test(name)) issues.push('empty');
  else if (EDGE_SPACE.test(name)) issues.push('surrounding_space');
  if (length > limit) issues.push('too_long');
  if (name.normalize('NFC') !== name) issues.push('not_nfc');
  if (CONTROL_OR_FORMAT.test(name)) issues.push('control_character');
  if (kind === 'webhook') {
    const folded = foldForReserved(name);
    if (RESERVED_WEBHOOK_WORDS.some((word) => folded.includes(word))) issues.push('reserved_word');
  }
  return { length, limit, issues, over: Math.max(0, length - limit) };
}

export const senderNameAcceptable = (check: SenderNameCheck) => check.issues.length === 0;

// ---------------------------------------------------------------------------------------------------------------
// Availability: why the name can or cannot be changed.
// ---------------------------------------------------------------------------------------------------------------

/**
 * Every state the editor can show. `ready` is the editable form; the rest explain why it is not. The order is the
 * order the copy lists them in the documentation. Unknown server reasons never get a state of their own: they render
 * as `failed` (generic) so the UI never invents a cause.
 */
export const SENDER_STATES = [
  'ready',
  'feature_disabled',
  'bot_nickname_disabled',
  'not_authorizing_member',
  'member_lacks_manage_nicknames',
  'bot_lacks_change_nickname',
  'nickname_managed_elsewhere',
  'edit_pending',
  'stale',
  'step_up_required',
  'reconnect_required',
  'permission_unclear',
  'failed'
] as const;

export type SenderStateKey = (typeof SENDER_STATES)[number];

/** The reasons the backend names (docs/sender-name/UI-NEEDS.md section 3.1). */
export const SERVER_REASONS = [
  'feature_disabled',
  'bot_nickname_disabled',
  'not_authorizing_member',
  'member_lacks_manage_nicknames',
  'bot_lacks_change_nickname',
  'nickname_managed_elsewhere',
  'reconnect_required',
  'edit_pending',
  'stale'
] as const;

export type SenderServerReason = (typeof SERVER_REASONS)[number];

export interface SenderState {
  key: SenderStateKey;
  /** Epoch seconds when a pending change can be re-checked, when the server says. */
  retryAt: number | null;
  /** The person must sign in again (the dialog offers the button); a global step-up screen handles the other kind. */
  signInAgain: boolean;
}

export const READY: SenderState = { key: 'ready', retryAt: null, signInAgain: false };

/** What the UI reads from a refused request: the fields of `ApiError`, nothing else. */
export interface SenderRefusal {
  status?: number;
  code?: string;
  reason?: string;
  retryAt?: number;
  message?: string;
}

const isReason = (value: unknown): value is SenderServerReason => typeof value === 'string' && (SERVER_REASONS as readonly string[]).includes(value);
const finite = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** A server-sent step-up: a code from a current server, or the sign-in message from an older deployment. */
export function isFreshSignInRefusal(error: SenderRefusal): boolean {
  return error.code === 'step_up_required' || (!error.code && error.status === 403 && /sign in again/i.test(error.message ?? ''));
}

export function isGlobalStepUpRefusal(error: SenderRefusal): boolean {
  return error.status === 403 && error.code === 'security_step_up_required';
}

/**
 * The state a refused request leaves the editor in. A named `reason` always wins; then the known codes; then the
 * coarse status of the current backend (403 means permission, anything else cannot be told apart and is `failed`,
 * which only offers a reload, never a retry).
 */
export function classifySenderRefusal(error: SenderRefusal): SenderState {
  if (isGlobalStepUpRefusal(error)) return { key: 'step_up_required', retryAt: null, signInAgain: false };
  if (isFreshSignInRefusal(error)) return { key: 'step_up_required', retryAt: null, signInAgain: true };
  const retryAt = finite(error.retryAt);
  if (error.code === 'discord_sender_edit_pending') return { key: 'edit_pending', retryAt, signInAgain: false };
  if (error.code === 'discord_sender_name_stale') return { key: 'stale', retryAt: null, signInAgain: false };
  if (isReason(error.reason)) return { key: error.reason, retryAt: error.reason === 'edit_pending' ? retryAt : null, signInAgain: false };
  if (error.status === 401) return { key: 'step_up_required', retryAt: null, signInAgain: true };
  if (error.status === 403) return { key: 'permission_unclear', retryAt: null, signInAgain: false };
  // The connection is gone or revoked: nothing to edit until it is connected again.
  if (error.status === 404) return { key: 'reconnect_required', retryAt: null, signInAgain: false };
  return { key: 'failed', retryAt: null, signInAgain: false };
}

/** The `availability` block of a 200 profile; a profile without one is editable (the current backend). */
export interface SenderAvailability {
  editable: boolean;
  reason?: string;
  retryAt?: number;
}

export function classifySenderProfile(profile: { availability?: SenderAvailability | null }): SenderState {
  const availability = profile.availability;
  if (!availability || availability.editable !== false) return READY;
  if (isReason(availability.reason)) {
    return { key: availability.reason, retryAt: availability.reason === 'edit_pending' ? finite(availability.retryAt) : null, signInAgain: false };
  }
  // The server said "not editable" but gave no reason we know: say so without guessing.
  return { key: 'failed', retryAt: null, signInAgain: false };
}

/** Provider-level switches (UI-NEEDS 3.3). Absent means unknown: the GET decides. */
export interface SenderNameModes {
  webhook?: { enabled: boolean; reason?: string };
  bot?: { enabled: boolean; reason?: string };
}

export function classifySenderModes(modes: SenderNameModes | null | undefined, kind: SenderKind): SenderState | null {
  const mode = modes?.[kind];
  if (!mode || mode.enabled !== false) return null;
  if (mode.reason === 'feature_disabled') return { key: 'feature_disabled', retryAt: null, signInAgain: false };
  // A bot switched off with no named reason is the isolation switch; a webhook switched off is the whole feature.
  return { key: kind === 'bot' ? 'bot_nickname_disabled' : 'feature_disabled', retryAt: null, signInAgain: false };
}

/** States in which the person can usefully press "Check again" (a read, never a second write). */
export function canCheckAgain(key: SenderStateKey): boolean {
  return !['ready', 'feature_disabled', 'bot_nickname_disabled', 'nickname_managed_elsewhere', 'step_up_required'].includes(key);
}

/** Epoch seconds as a short local time, or null when unknown. */
export function formatRetryTime(retryAt: number | null, locale: string, timeZone?: string): string | null {
  if (retryAt === null) return null;
  try {
    return new Intl.DateTimeFormat(locale || 'en', { hour: 'numeric', minute: '2-digit', ...(timeZone ? { timeZone } : {}) }).format(new Date(retryAt * 1000));
  } catch {
    return null;
  }
}

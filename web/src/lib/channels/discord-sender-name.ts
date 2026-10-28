/**
 * Customer-set Discord sender names: the limits and name rules the server applies (contract v2,
 * docs/sender-name/UI-API-CONTRACT.md) and the states the editor can be in. No React and no `@/` imports, so the node
 * tests load it directly.
 *
 * The server (`sender_names.name_problem`) is the authority and reports one stable `reason`. These rules are a copy of
 * it so a person sees every problem before saving; `tests/test_discord_sender_name_ui_contract.py` checks the shared
 * verdict fixture against the real validator and `web/tests/discord-sender-name.test.cjs` checks this file against the
 * same fixture. Messages are chosen by `reason`, never by parsing the server's English `error` text.
 */

export type SenderKind = 'webhook' | 'bot';

/** Webhook 80, bot nickname 32. The server keeps BOTH the code point count and the UTF-16 length within it. */
export const SENDER_LIMIT: Record<SenderKind, number> = { webhook: 80, bot: 32 };

/** Substrings the server refuses (mentions, channels, emoji syntax, code fences, Discord's own username rules). */
export const FORBIDDEN_CHARACTERS: readonly string[] = ['@', '#', ':', '```', '<', '>'];

/**
 * Reserved after folding case, accents, width, look-alike letters, separators and digit substitutions. A webhook name
 * follows Discord's own username rule plus the product's names; a bot nickname only the product's names (Discord
 * restricts usernames, not server nicknames), and no whole name is reserved for it.
 */
export const RESERVED_PARTS: Record<SenderKind, readonly string[]> = { webhook: ['discord', 'clyde', 'rafii', 'postriff'], bot: ['rafii', 'postriff'] };
export const RESERVED_WHOLE: Record<SenderKind, readonly string[]> = { webhook: ['everyone', 'here'], bot: [] };

/** The stable `reason` values of `discord_sender_name_invalid`, in the order the server tests them. */
export type SenderNameIssue =
  | 'empty'
  | 'surrounding_space'
  | 'not_normalized'
  | 'too_long'
  | 'control_or_format'
  | 'spacing'
  | 'invisible'
  | 'forbidden_character'
  | 'url_like'
  | 'reserved_word';

export const SENDER_NAME_ISSUES: readonly SenderNameIssue[] = [
  'empty',
  'surrounding_space',
  'not_normalized',
  'too_long',
  'control_or_format',
  'spacing',
  'invisible',
  'forbidden_character',
  'url_like',
  'reserved_word'
];

export const isSenderNameIssue = (value: unknown): value is SenderNameIssue => typeof value === 'string' && (SENDER_NAME_ISSUES as readonly string[]).includes(value);

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
const CONTROL_CHARACTER = new RegExp('^[\\p{C}\\u2028\\u2029]$', 'u');
const ZERO_WIDTH_NON_JOINER = '\u200c';
const ZERO_WIDTH_JOINER = '\u200d';
const VARIATION_SELECTORS = new Set(['\ufe0e', '\ufe0f']);
/** Symbol (other) and modifier symbol: the characters of an emoji sequence, skin tones included. */
const JOIN_SYMBOL = new RegExp('^[\\p{So}\\p{Sk}]$', 'u');
const LETTER_OR_MARK = new RegExp('^[\\p{L}\\p{M}]$', 'u');

/**
 * The server's `_joiner_allowed`: the two zero width joiners real text needs, and nothing else invisible. A ZWJ only
 * inside an emoji sequence (a symbol on both sides; variation selectors before it are skipped), a ZWNJ only between
 * letters or marks of a script above U+024F that needs it (Persian, Indic and so on), never between Latin letters,
 * where it could only hide a word. Works on code points, as Python does.
 */
function joinerAllowed(characters: string[], index: number): boolean {
  let beforeIndex = index - 1;
  while (beforeIndex >= 0 && VARIATION_SELECTORS.has(characters[beforeIndex])) beforeIndex -= 1;
  const before = beforeIndex >= 0 ? characters[beforeIndex] : '';
  const after = index + 1 < characters.length ? characters[index + 1] : '';
  if (!before || !after) return false;
  if (characters[index] === ZERO_WIDTH_JOINER) return JOIN_SYMBOL.test(before) && JOIN_SYMBOL.test(after);
  return (
    characters[index] === ZERO_WIDTH_NON_JOINER &&
    (before.codePointAt(0) ?? 0) > 0x24f &&
    (after.codePointAt(0) ?? 0) > 0x24f &&
    LETTER_OR_MARK.test(before) &&
    LETTER_OR_MARK.test(after)
  );
}

/** Any control, format, private use, unassigned or separator character, except a joiner where the server allows one. */
function hasControlOrFormat(name: string): boolean {
  const characters = Array.from(name);
  return characters.some(
    (character, index) =>
      CONTROL_CHARACTER.test(character) &&
      !((character === ZERO_WIDTH_JOINER || character === ZERO_WIDTH_NON_JOINER) && joinerAllowed(characters, index))
  );
}
/** A Z-category character that is not the plain space. */
const ODD_SPACE = new RegExp('(?! )\\p{Z}', 'u');
const HAS_VISIBLE = new RegExp('[\\p{L}\\p{N}\\p{S}\\p{P}]', 'u');
const MARKS = new RegExp('\\p{M}', 'gu');
const URL_LIKE = /(^|[^a-z0-9])www\./i;
/** Characters that draw as nothing although they are letters or symbols (Hangul fillers, Braille blank, and so on). */
const BLANKS = new Set(['ᅟ', 'ᅠ', 'ㅤ', 'ﾠ', '⠀', '឴', '឵', '͏', '᠎']);
/** Look-alike letters of other scripts, applied only to the reserved-word comparison (the server's table, verbatim). */
const HOMOGLYPHS: Record<string, string> = {
  'ø': 'o', 'đ': 'd', 'ı': 'i', 'ł': 'l', 'ɡ': 'g', 'α': 'a', 'ε': 'e', 'ι': 'i',
  'κ': 'k', 'ν': 'v', 'ο': 'o', 'ρ': 'p', 'τ': 't', 'а': 'a', 'в': 'b', 'г': 'r',
  'е': 'e', 'к': 'k', 'м': 'm', 'н': 'h', 'о': 'o', 'р': 'p', 'с': 'c', 'т': 't',
  'у': 'y', 'х': 'x', 'ѕ': 's', 'і': 'i', 'ј': 'j', 'ӏ': 'l', 'ԁ': 'd'
};
const LEET: readonly Record<string, string>[] = [
  { '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't' },
  { '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's', '7': 't' }
];

/**
 * The server's reserved-word skeletons: compatibility-decomposed, marks removed, case folded, look-alikes mapped to
 * Latin, everything but a-z and 0-9 dropped, then each digit-substitution reading. Upper-casing and then lower-casing
 * equals Python's `casefold()` for every character that can end up as a-z or 0-9 here (it also folds the German sharp
 * s to "ss" and the Cyrillic letters of the Extended-C block to their base letters, and the capital sharp s, which
 * it leaves as a lower case sharp s, is folded to "ss" explicitly); the dotless i, which it turns into "i", is in the
 * look-alike table anyway.
 */
export function reservedSkeletons(name: string): string[] {
  const folded = name.normalize('NFKD').replace(MARKS, '').toUpperCase().toLowerCase().replace(/ß/g, 'ss');
  let mapped = '';
  for (const character of folded) mapped += HOMOGLYPHS[character] ?? character;
  const plain = mapped.replace(/[^a-z0-9]/g, '');
  return LEET.map((table) => plain.replace(/[0-9]/g, (digit) => table[digit] ?? digit));
}

export function isReservedName(name: string, kind: SenderKind): boolean {
  const skeletons = reservedSkeletons(name);
  return skeletons.some((skeleton) => RESERVED_PARTS[kind].some((part) => skeleton.includes(part)) || RESERVED_WHOLE[kind].includes(skeleton));
}

export interface SenderNameCheck {
  /** The binding length: UTF-16 units, which is never less than the code points (an emoji counts 2). */
  length: number;
  codePoints: number;
  limit: number;
  /** Every rule the name breaks, in the server's order, so the first is the `reason` the server would give. */
  issues: SenderNameIssue[];
  /** Characters over the limit, 0 when within it. */
  over: number;
}

export interface SenderNameOptions {
  /** The limit the server sent (`maxLength`); defaults to the kind's. */
  limit?: number;
  /** The forbidden substrings the server sent (`rules.forbiddenCharacters`); defaults to the documented list. */
  forbidden?: readonly string[];
}

export function checkSenderName(name: string, kind: SenderKind, options: SenderNameOptions = {}): SenderNameCheck {
  const limit = options.limit ?? SENDER_LIMIT[kind];
  const forbidden = options.forbidden ?? FORBIDDEN_CHARACTERS;
  const codePoints = codePointLength(name);
  const length = Math.max(codePoints, name.length);
  const issues: SenderNameIssue[] = [];
  // Nothing typed (or only spaces): that is the whole message; the other rules have nothing to say about it.
  if (ONLY_SPACE.test(name)) return { length, codePoints, limit, issues: ['empty'], over: 0 };
  if (EDGE_SPACE.test(name)) issues.push('surrounding_space');
  if (name.normalize('NFC') !== name) issues.push('not_normalized');
  if (length > limit) issues.push('too_long');
  if (hasControlOrFormat(name)) issues.push('control_or_format');
  if (name.includes('  ') || ODD_SPACE.test(name)) issues.push('spacing');
  if (Array.from(name).some((character) => BLANKS.has(character)) || !HAS_VISIBLE.test(name)) issues.push('invisible');
  if (forbidden.some((part) => name.includes(part))) issues.push('forbidden_character');
  if (name.includes('://') || URL_LIKE.test(name)) issues.push('url_like');
  if (isReservedName(name, kind)) issues.push('reserved_word');
  return { length, codePoints, limit, issues, over: Math.max(0, length - limit) };
}

export const senderNameAcceptable = (check: SenderNameCheck) => check.issues.length === 0;

// ---------------------------------------------------------------------------------------------------------------
// Availability: why the name can or cannot be changed.
// ---------------------------------------------------------------------------------------------------------------

/**
 * Every state the editor can show. `ready` is the editable form; the rest explain why it is not. Ten are the
 * contract's `unavailable[].code` values, the others are the honest answers to a refused or unreadable request. A code
 * the UI does not know renders as `failed`: it never invents a cause.
 */
export const SENDER_STATES = [
  'ready',
  'sender_names_disabled',
  'bot_nickname_disabled',
  'provider_unavailable',
  'not_authorizing_member',
  'session_reverification_required',
  'person_missing_manage_nicknames',
  'person_role_below_bot',
  'bot_missing_change_nickname',
  'nickname_authority_other_workspace',
  'edit_pending',
  'stale',
  'reconnect_required',
  'write_unconfirmed',
  'write_refused',
  'write_rate_limited',
  'evidence_invalid',
  'rate_limited',
  'rate_delayed',
  'upstream_unavailable',
  'workspace_permission',
  'failed'
] as const;

export type SenderStateKey = (typeof SENDER_STATES)[number];
export type BlockedSenderState = Exclude<SenderStateKey, 'ready'>;

/** `unavailable[].code` / `reasons[].code` values that name a state directly. */
export const UNAVAILABLE_CODES = [
  'sender_names_disabled',
  'bot_nickname_disabled',
  'provider_unavailable',
  'not_authorizing_member',
  'session_reverification_required',
  'person_missing_manage_nicknames',
  'person_role_below_bot',
  'bot_missing_change_nickname',
  'nickname_authority_other_workspace',
  'edit_pending'
] as const;

export interface SenderState {
  key: SenderStateKey;
  /** Seconds the server asked to wait (a held change, a throttle); null when it gave none. */
  retryAfterSeconds: number | null;
  /** Epoch milliseconds when Rafii may be asked again, counted from when the answer arrived; null without a wait. */
  retryAtMs: number | null;
  /** The person must sign in again (the dialog offers the button); a global step-up screen handles the other kind. */
  signInAgain: boolean;
}

export type BlockedState = SenderState & { key: BlockedSenderState };

export const READY: SenderState = { key: 'ready', retryAfterSeconds: null, retryAtMs: null, signInAgain: false };

const isUnavailableCode = (value: unknown): value is (typeof UNAVAILABLE_CODES)[number] => typeof value === 'string' && (UNAVAILABLE_CODES as readonly string[]).includes(value);
const seconds = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null);

function blocked(key: BlockedSenderState, nowMs: number, options: { wait?: unknown; signInAgain?: boolean } = {}): BlockedState {
  const wait = seconds(options.wait);
  return { key, retryAfterSeconds: wait, retryAtMs: wait === null ? null : nowMs + wait * 1000, signInAgain: options.signInAgain === true };
}

/** One entry of `unavailable` (GET) or `reasons` (POST refusal). */
export interface SenderReason {
  code: string;
  retryAfterSeconds?: number;
}

function fromReason(reason: SenderReason, nowMs: number): BlockedState {
  if (!reason || !isUnavailableCode(reason.code)) return blocked('failed', nowMs);
  if (reason.code === 'edit_pending') return blocked('edit_pending', nowMs, { wait: reason.retryAfterSeconds });
  // A pre-emptive "session too old" is the same state as a refused save: sign in again.
  return blocked(reason.code, nowMs, { signInAgain: reason.code === 'session_reverification_required' });
}

function distinct(states: BlockedState[]): BlockedState[] {
  return states.filter((state, index) => states.findIndex((other) => other.key === state.key) === index);
}

/** What the UI reads from a refused request: the fields of `ApiError`, nothing else. */
export interface SenderRefusal {
  status?: number;
  code?: string;
  reason?: string;
  reasons?: SenderReason[];
  retryAfterSeconds?: number;
  message?: string;
}

/** A server-sent step-up: a code from a current server, or the sign-in message from an older deployment. */
export function isFreshSignInRefusal(error: SenderRefusal): boolean {
  return error.code === 'step_up_required' || (!error.code && error.status === 403 && /sign in again/i.test(error.message ?? ''));
}

export function isGlobalStepUpRefusal(error: SenderRefusal): boolean {
  return error.status === 403 && error.code === 'security_step_up_required';
}

/**
 * The states a refused request leaves the editor in (more than one when the server lists several reasons). A named
 * reason always wins; then the contract's codes; then the HTTP status. Anything else is `failed`, which only offers a
 * reload and never a retry of a write.
 */
export function classifySenderRefusal(error: SenderRefusal, nowMs: number = Date.now()): BlockedState[] {
  if (isGlobalStepUpRefusal(error)) return [blocked('session_reverification_required', nowMs)];
  if (isFreshSignInRefusal(error)) return [blocked('session_reverification_required', nowMs, { signInAgain: true })];
  if (error.code === 'discord_sender_name_unavailable' && Array.isArray(error.reasons) && error.reasons.length > 0) {
    return distinct(error.reasons.map((reason) => fromReason(reason, nowMs)));
  }
  if (error.code === 'discord_sender_edit_pending') return [blocked('edit_pending', nowMs, { wait: error.retryAfterSeconds })];
  // Discord's shared request capacity has no room (not Rafii's own throttle): its own state, with the wait it named.
  if (error.code === 'discord_rate_delayed') return [blocked('rate_delayed', nowMs, { wait: error.retryAfterSeconds })];
  // Discord answered the write itself with a rate limit: unchanged, nothing waits, and not a permission problem.
  if (error.code === 'discord_sender_write_rate_limited') return [blocked('write_rate_limited', nowMs, { wait: error.retryAfterSeconds })];
  if (error.code === 'rate_limited' || error.status === 429) return [blocked('rate_limited', nowMs, { wait: error.retryAfterSeconds })];
  if (error.code === 'discord_sender_name_required' && error.status === 409) return [blocked('stale', nowMs)];
  if (error.code === 'discord_sender_write_unconfirmed') return [blocked('write_unconfirmed', nowMs)];
  // Discord answered the write with a refusal: the nickname is unchanged and nothing waits.
  if (error.code === 'discord_sender_write_refused') return [blocked('write_refused', nowMs)];
  // Discord's answer about the server, roles or permissions was not usable; nothing was written.
  if (error.code === 'discord_sender_evidence_invalid') return [blocked('evidence_invalid', nowMs)];
  // The shared request coordinator failed after the readiness check passed: Rafii's side, temporary.
  if (error.code === 'discord_rate_coordinator_unavailable') return [blocked('provider_unavailable', nowMs)];
  // 409: the stored authorization no longer matches (reconnect). 503: Discord connections are paused for the whole provider, which a reconnect cannot fix.
  if (error.code === 'discord_connection_required') return [blocked(error.status === 503 ? 'provider_unavailable' : 'reconnect_required', nowMs)];
  if (error.code === 'permission_denied') return [blocked('workspace_permission', nowMs)];
  if (error.code === 'unauthenticated' || error.status === 401) return [blocked('session_reverification_required', nowMs, { signInAgain: true })];
  if (error.status === 404) return [blocked('reconnect_required', nowMs)];
  // 502 and 503 are Discord (or Rafii) not answering; no status at all is a network failure. Nothing changed either way.
  if (error.status === undefined || error.status === 502 || error.status === 503 || error.status === 504) return [blocked('upstream_unavailable', nowMs)];
  return [blocked('failed', nowMs)];
}

/** The slice of a 200 profile that says whether the name can be changed. */
export interface SenderAvailabilityFields {
  editable?: boolean;
  unavailable?: SenderReason[] | null;
}

/** The states a readable profile reports. Empty means editable; a profile without the v2 fields is editable. */
export function classifySenderProfile(profile: SenderAvailabilityFields, nowMs: number = Date.now()): BlockedState[] {
  if (profile.editable !== false) return [];
  const listed = Array.isArray(profile.unavailable) ? profile.unavailable : [];
  const states = distinct(listed.map((reason) => fromReason(reason, nowMs)));
  // "Not editable" with no reason we know: say so without guessing.
  return states.length > 0 ? states : [blocked('failed', nowMs)];
}

/**
 * The provider view's per-mode flags (`providers[discord].discordModes`): `bot.nickname.enabled` and
 * `webhook.senderName.enabled`. They fold the two switches together with whether Rafii is ready to make Discord
 * requests. Every switch is off unless the server sets it to the exact string "true", so at the opening the answer is
 * no for everyone.
 */
export interface SenderProviderModes {
  bot?: { nickname?: { enabled?: boolean } };
  webhook?: { senderName?: { enabled?: boolean } };
}

/**
 * Whether the card may show the sender-name control at all. Only a flag that says yes counts: a flag that is false, or
 * a provider view that does not carry it, shows nothing (no editor, no button, no note), as the contract asks.
 */
export function senderProviderOffers(modes: SenderProviderModes | null | undefined, kind: SenderKind): boolean {
  if (!modes) return false;
  return kind === 'bot' ? modes.bot?.nickname?.enabled === true : modes.webhook?.senderName?.enabled === true;
}

/** What a preview can say about a bot's nickname, from `ChannelView.discordBotNickname` or `Manifest.discordBotNickname`. */
export interface BotNicknameView {
  /** The nickname to draw as the author, or null when there is none to show. */
  name: string | null;
  /** `observed`: the last nickname Rafii read (before approval). `approved`: the one recorded in an approval. */
  source: 'observed' | 'approved' | 'bot_username' | 'unknown';
  /** Whether it is known that the post is held when Discord shows another nickname when it is due. */
  hold: 'pending' | 'approved' | undefined;
}

/**
 * A string is a recorded nickname, `null` means the bot had none (Discord shows its own username), and absent means
 * nothing is or would be recorded, so the preview claims neither a name nor a hold.
 */
export function botNicknameView(value: string | null | undefined, stage: 'channel' | 'manifest'): BotNicknameView {
  if (value === undefined) return { name: null, source: 'unknown', hold: undefined };
  const hold = stage === 'manifest' ? 'approved' : 'pending';
  if (value === null || value === '') return { name: null, source: 'bot_username', hold };
  return { name: value, source: stage === 'manifest' ? 'approved' : 'observed', hold };
}

/** States in which the person can usefully press "Check again" (a read, never a second write). */
export function canCheckAgain(key: SenderStateKey): boolean {
  return !['ready', 'sender_names_disabled', 'bot_nickname_disabled', 'not_authorizing_member', 'session_reverification_required', 'workspace_permission'].includes(key);
}

/** Epoch milliseconds as a short local time, or null when unknown. */
export function formatRetryTime(atMs: number | null, locale: string, timeZone?: string): string | null {
  if (atMs === null || !Number.isFinite(atMs)) return null;
  try {
    return new Intl.DateTimeFormat(locale || 'en', { hour: 'numeric', minute: '2-digit', ...(timeZone ? { timeZone } : {}) }).format(new Date(atMs));
  } catch {
    return null;
  }
}

/** "90 seconds" / "2 minutes" in the reader's language: the wait the server asked for, rounded up to whole minutes past 90 s. */
export function formatWait(waitSeconds: number, locale: string): string {
  const minutes = waitSeconds >= 90;
  const value = minutes ? Math.ceil(waitSeconds / 60) : Math.max(1, Math.round(waitSeconds));
  try {
    return new Intl.NumberFormat(locale || 'en', { style: 'unit', unit: minutes ? 'minute' : 'second', unitDisplay: 'long' }).format(value);
  } catch {
    return `${value} ${minutes ? 'min' : 's'}`;
  }
}

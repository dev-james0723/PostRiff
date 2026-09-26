/**
 * The `@` trigger and query (chat-context SPEC §4.3). Pure functions over the textarea's value and caret; the
 * composer hook feeds them `input` events. No `@/` imports (node --test transpiles it).
 *
 * - Opens only on typed input (`insertText`/`insertCompositionText`) whose data ends in `@` or `＠`, never on paste,
 *   drop or replacement text, and never inside an email address, a URL or a handle like `threads.com/@name`.
 * - The query runs from the anchor to the caret and ends at whitespace, another `@`, a newline, CJK or ASCII
 *   punctuation (other than `_ - .`) or 40 code points. When it ends, the list closes and the text stays.
 * - A dismissed anchor never reopens: reopening needs a newly typed `@`.
 */

export const QUERY_MAX = 40;
const AT = new Set(['@', '＠']);
const OPENING_INPUTS = new Set(['insertText', 'insertCompositionText']);
const WORDISH = /[A-Za-z0-9_/:.]/;
// CJK punctuation that ends a query.
const CJK_PUNCT = /[，。、！？；：「」『』（）【】《》…]/u;
// ASCII punctuation other than `_ - .` also ends it.
const ASCII_PUNCT = /[!-,/:-?[-^`{-~]/;

/** The anchor index (where the `@` is) when this input event opens the list; otherwise null. */
export function triggerFrom(
  inputType: string,
  data: string | null | undefined,
  value: string,
  caret: number
): number | null {
  if (!OPENING_INPUTS.has(inputType) || !data) return null;
  const last = Array.from(data).pop() ?? '';
  if (!AT.has(last)) return null;
  const anchor = caret - last.length;
  if (anchor < 0 || !AT.has(value.slice(anchor, caret))) return null;
  const before = Array.from(value.slice(0, anchor)).pop() ?? '';
  if (before && WORDISH.test(before)) return null;
  // The whitespace-delimited token around the `@` must not be a URL or a web address.
  const tokenStart = value.slice(0, anchor).search(/\S*$/u);
  const tokenEndRel = value.slice(caret).search(/\s|$/u);
  const token = value.slice(tokenStart, caret + tokenEndRel).toLowerCase();
  if (token.includes('://') || token.includes('www.')) return null;
  return anchor;
}

function ends(ch: string): boolean {
  return (
    /\s/u.test(ch) ||
    AT.has(ch) ||
    CJK_PUNCT.test(ch) ||
    (ASCII_PUNCT.test(ch) && !'_-.'.includes(ch))
  );
}

export interface MentionQuery {
  query: string;
  /** True when the query ran into a terminator or the length cap: the list closes and the text stays. */
  ended: boolean;
}

/** The query typed after the `@` at `anchor`, up to the caret. */
export function queryAt(value: string, anchor: number, caret: number): MentionQuery {
  if (anchor < 0 || caret <= anchor || !AT.has(value.slice(anchor, anchor + 1)))
    return { query: '', ended: true };
  const points = Array.from(value.slice(anchor + 1, caret));
  const out: string[] = [];
  for (const ch of points) {
    if (ends(ch)) return { query: out.join(''), ended: true };
    out.push(ch);
    if (out.length > QUERY_MAX) return { query: out.slice(0, QUERY_MAX).join(''), ended: true };
  }
  return { query: out.join(''), ended: false };
}

export interface MentionState {
  anchor: number | null;
  query: string;
  dismissed: readonly number[];
}

export const CLOSED: MentionState = { anchor: null, query: '', dismissed: [] };

export type MentionEvent =
  | { type: 'input'; inputType: string; data: string | null; value: string; caret: number }
  | { type: 'selection'; value: string; caret: number }
  | { type: 'dismiss' }
  | { type: 'picked' };

/** The list's state after one event. Selection changes can only close it; a dismissed anchor never reopens. */
export function reduceMention(state: MentionState, event: MentionEvent): MentionState {
  if (event.type === 'dismiss')
    return state.anchor === null
      ? state
      : { anchor: null, query: '', dismissed: [...state.dismissed, state.anchor] };
  if (event.type === 'picked') return { ...state, anchor: null, query: '' };
  if (event.type === 'selection') {
    if (state.anchor === null) return state;
    const { query, ended } = queryAt(event.value, state.anchor, event.caret);
    return ended || query !== state.query ? { ...state, anchor: null, query: '' } : state;
  }
  const opened = triggerFrom(event.inputType, event.data, event.value, event.caret);
  if (opened !== null && !state.dismissed.includes(opened))
    return { ...state, anchor: opened, query: '' };
  if (state.anchor === null) return state;
  const { query, ended } = queryAt(event.value, state.anchor, event.caret);
  return ended ? { ...state, anchor: null, query: '' } : { ...state, query };
}

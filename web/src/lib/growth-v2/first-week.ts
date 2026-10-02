import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import type { ContinuationImport, FirstWeekView, HandoffState } from './first-week-types';

/** Typed client for `/api/workspaces/{id}/first-week/…`. Every mutation carries the journey revision it was read at. */
export function createFirstWeekApi(getToken: TokenSource) {
  const r = createRequester(getToken);
  const base = (w: string) => `${ws(w)}/first-week`;
  return {
    view: (w: string) => r.get<FirstWeekView>(base(w)),
    importContinuation: (w: string, body: { idempotencyKey: string; consent: true; platform: string; language: string; items: { kind: string; text: string }[] }) =>
      r.send<ContinuationImport>('POST', `${base(w)}/continuations`, body),
    start: (w: string, body: { idempotencyKey: string; consent: true; text: string; platform: string; language: string }) =>
      r.send<ContinuationImport>('POST', `${base(w)}/start`, body),
    setContext: (w: string, body: { purpose: string; audience: string; mode?: string; subject?: string; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/context`, body),
    accept: (w: string, body: { variantId: string; variantRevision: number; expectedRevision: number }) => r.send<FirstWeekView>('POST', `${base(w)}/accept`, body),
    plan: (w: string, body: { platform?: string; channelId?: string | null; postsPerWeek: number; timeZone: string; language?: string; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/plan`, body),
    scope: (w: string, body: { slotIds: string[]; reason?: string; expectedRevision: number }) => r.send<FirstWeekView>('POST', `${base(w)}/scope`, body),
    draft: (w: string, body: { confirmed: true; maxCredits?: number; expectedRevision: number }) =>
      r.send<{ prepare: { advanced: boolean; drafted: number; draftedSlotIds: string[] }; journey: FirstWeekView }>('POST', `${base(w)}/draft`, body, 150_000),
    write: (w: string, slotId: string, body: { weekId: string; text: string; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/slots/${seg(slotId)}/write`, body),
    handoff: (w: string, slotId: string, body: { weekId: string; action: HandoffState | 'undo'; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/slots/${seg(slotId)}/handoff`, body)
  };
}

export type FirstWeekApi = ReturnType<typeof createFirstWeekApi>;

/* ---------- pure helpers for the first-week panel ---------- */

/** The languages a first-week draft is saved in (`first_week/service.py LANGUAGES`). */
export const DRAFT_LANGUAGES = ['en', 'zh-HK', 'zh-TW', 'zh-CN', 'other'] as const;
export type DraftLanguage = (typeof DRAFT_LANGUAGES)[number];

export const LANGUAGE_LABELS: Record<DraftLanguage, string> = {
  en: 'English',
  'zh-HK': '繁體中文（香港）',
  'zh-TW': '繁體中文（台灣）',
  'zh-CN': '简体中文',
  other: 'Another language'
};

// Common characters written differently in Simplified and Traditional Chinese: enough to tell a draft's script.
const SIMPLIFIED = new Set('这们说时会为来个对过后么还没发学问题实现让经关开国东车长门见头话认识从样点气体进动种爱书买卖写读钱练习乐听讲课师边总给办专业让'.split(''));
const TRADITIONAL = new Set('這們說時會為來個對過後麼還沒發學問題實現讓經關開國東車長門見頭話認識從樣點氣體進動種愛書買賣寫讀錢練習樂聽講課師邊總給辦專業讓'.split(''));
const ENGLISH = /\b(the|and|to|of|is|are|you|your|for|in|with|my|it|this|that|on|i|we|a|an|be|not|but|how|what)\b/gi;

/**
 * The language a pasted draft is written in: the text decides first (Chinese script, Simplified or Traditional;
 * Japanese and Korean are "other"), then the person's own language tag, never a fixed English default.
 */
/** A person's language tag as a draft language (`zh-Hant-HK`, `yue` → zh-HK; `zh-TW` → zh-TW; `zh-Hans`, `zh` → zh-CN). */
export function languageFromTag(preferred?: string | null): DraftLanguage {
  const tag = (preferred ?? '').trim().toLowerCase();
  if (!tag || /^en\b/.test(tag)) return 'en';
  if (/^zh-(hant-)?tw\b/.test(tag)) return 'zh-TW';
  if (/^(zh-(hant|hk|mo)|yue)\b/.test(tag)) return 'zh-HK';
  if (/^zh\b/.test(tag)) return 'zh-CN';
  return 'other';
}

export function draftLanguage(text: string, preferred?: string | null): DraftLanguage {
  const own = languageFromTag(preferred);
  const chars = Array.from(text);
  if (/[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(text)) return 'other';
  const han = chars.filter((c) => /\p{Script=Han}/u.test(c)).length;
  const latin = chars.filter((c) => /\p{Script=Latin}/u.test(c)).length;
  if (han > 0 && han * 2 >= latin) {
    const simplified = chars.filter((c) => SIMPLIFIED.has(c)).length;
    const traditional = chars.filter((c) => TRADITIONAL.has(c)).length;
    if (simplified > traditional) return 'zh-CN';
    if (traditional > simplified) return own === 'zh-TW' ? 'zh-TW' : 'zh-HK';
    return own === 'zh-CN' || own === 'zh-TW' ? own : 'zh-HK';
  }
  if (latin === 0) return own;   // nothing written yet (or no letters): the person's own language
  const words = text.split(/\s+/).filter(Boolean).length;
  const english = (text.match(ENGLISH) ?? []).length;
  if (english >= Math.max(1, Math.round(words * 0.08))) return 'en';
  // Latin script without English function words: another language for someone whose own language is neither
  // English nor Chinese; otherwise English (Rafii's draft languages offer no other Latin-script choice).
  return own === 'other' ? 'other' : 'en';
}

/**
 * True when a request ended without the server's answer (the client timeout, an abort or a dropped connection): the
 * server may still be working, so the UI must check again instead of saying it stopped.
 */
export function unknownOutcome(error: unknown): boolean {
  const name = error instanceof Error || (typeof DOMException !== 'undefined' && error instanceof DOMException) ? (error as Error).name : '';
  return name === 'TimeoutError' || name === 'AbortError' || name === 'TypeError';
}

/** The server's note on a post whose writer was still running when its drafting call ended (coworker `_draft_slot`). */
export const WRITER_STILL_WORKING = 'The writer is still working on this post.';
/** The API's own time limit (vercel.json `maxDuration`): a drafting call has ended by then, answered or not. */
export const DRAFT_CALL_LIMIT_MS = 300_000;
/** One drafting call drafts at most this many posts (`draft_week` → `weekly_prepare(max_slots=2)`). */
export const DRAFTS_PER_CALL = 2;

/** A drafting request that ended without an answer: when it was sent and the posts that call works on. */
export interface UnansweredDraft {
  sentAt: number;
  batch: string[];
}

type SlotState = { id: string; committed: boolean; status: string; reason?: string | null };

/** The posts one drafting call works on: the first committed posts still planned, in week order, two at most. */
export function draftBatch(slots: SlotState[]): string[] {
  return slots.filter((s) => s.committed && s.status === 'planned').slice(0, DRAFTS_PER_CALL).map((s) => s.id);
}

/**
 * M6: whether an unanswered drafting call may still be running, as a read of the journey taken at `readAt` shows it.
 * The call is over once nothing is left to draft, once every post it was drafting has an outcome (drafted, a question,
 * or the writer's still-working note), or once the API's time limit had passed when the read was taken. Then the posts
 * that remain can be drafted again: a call drafts at most two, so "nothing left" is not the only way it ends.
 */
export function draftingMayContinue(unanswered: UnansweredDraft, slots: SlotState[], readAt: number): boolean {
  const open = slots.filter((s) => s.committed && s.status === 'planned');
  if (open.length === 0 || readAt >= unanswered.sentAt + DRAFT_CALL_LIMIT_MS) return false;
  return open.some((s) => unanswered.batch.includes(s.id) && s.reason !== WRITER_STILL_WORKING);
}

/**
 * L11: whether a new journey step takes keyboard focus. Only when the person's own control went with the old step —
 * focus was last in this panel, that element is gone and focus fell back to the page. A background refetch (another tab,
 * Queue, a stale cached view replaced on load) announces the step but never pulls focus from where the person is.
 */
export function stepTakesFocus(active: unknown, body: unknown, lastFocused: { isConnected: boolean } | null): boolean {
  return (active === null || active === body) && lastFocused !== null && !lastFocused.isConnected;
}

/** What a slot will cost or cost, in words (R-FWR-02: every slot shows its cost state). Null: nothing to say. */
export function slotCostText(
  slot: { costState: string | null; status: string; committed: boolean; draft: { origin: string | null } | null },
  billingMode: 'free_preview' | 'managed_credits' | 'legacy_allowances'
): string | null {
  if (slot.costState === 'requires_upgrade') return 'Free: write it yourself, or upgrade to have it drafted';
  if (slot.costState === 'over_limit') return 'Over this week’s credit limit';
  if (slot.costState === 'insufficient_credits') return 'Not enough credits; nothing was charged';
  if (slot.draft) {
    const origin = slot.draft.origin ?? '';
    return origin.startsWith('continuation:') || origin.startsWith('first_week:') ? 'Your words · no cost' : 'Drafted by Rafii';
  }
  if (!slot.committed || slot.status !== 'planned') return null;
  if (billingMode === 'managed_credits') return 'Drafting uses credits within this week’s limit';
  if (billingMode === 'legacy_allowances') return 'Drafting uses your plan’s writing allowance';
  return 'Free: write it yourself, or upgrade to have it drafted';
}

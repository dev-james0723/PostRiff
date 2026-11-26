/**
 * The rules behind one-click tone and polish edits in the draft editor: which text a click applies to, what the
 * request carries, which candidate still belongs to the draft on screen, and every word the control shows.
 * Pure on purpose (type imports only), so `tests/tone-edit-contract.test.mjs` runs it without a browser.
 *
 * Offsets: a textarea reports UTF-16 offsets; the server takes code-point offsets into the stored text. A selection
 * is widened to whole characters as people see them (an emoji with its joiners, a letter with its marks) before it
 * is converted, so a rewritten passage can never leave half a character behind.
 */
import type { SnapshotVariant } from '@/lib/api/types';
import type { DraftEditRecord, DraftEditRequest, DraftEditResult, DraftEditSelection, DraftEditTone, DraftVoiceMode } from '@/lib/api/draft-edits';

export type ToneLocale = 'en' | 'zh-Hant';
export type ToneId = DraftEditTone;
export type PresetToneId = Exclude<ToneId, 'custom'>;
/** What a click asks for. A custom tone also sends the person's own instruction. */
export type EditChoice = { mode: 'tone'; tone: ToneId } | { mode: 'polish' };

/**
 * Typed copy of `tones` and `modes` in `skills/rafii-editorial-core/contract.json` (ids and labels, in order). The
 * contract is shared with the writer; the test compares the two so a preset is never invented here.
 */
export const EDIT_TONES: readonly { id: ToneId; label: string }[] = [
  { id: 'warm', label: 'Warm' },
  { id: 'professional', label: 'Professional' },
  { id: 'direct', label: 'Direct' },
  { id: 'playful', label: 'Playful' },
  { id: 'custom', label: 'Custom' }
];
export const EDIT_MODES: readonly { id: 'polish' | 'tone'; label: string }[] = [
  { id: 'polish', label: 'Polish wording' },
  { id: 'tone', label: 'Change tone' }
];
export const PRESET_TONE_IDS = EDIT_TONES.map((tone) => tone.id).filter((id): id is PresetToneId => id !== 'custom');

/** Server limits (spec 5.4), in characters: a custom tone instruction, and the text one edit may rewrite. */
export const INSTRUCTION_MAX = 200;
export const EDIT_TEXT_MAX = 6000;

/* ---------- feature off ---------- */

/**
 * One-click edits are offered only when the writer catalogue (`GET /api/ideas/models`) carries
 * `draftEdits.enabled: true`. Absent means off, as for the catalogue's other optional entries.
 */
export function draftEditsEnabled(catalog: unknown): boolean {
  const entry = (catalog as { draftEdits?: unknown } | null | undefined)?.draftEdits;
  return typeof entry === 'object' && entry !== null && (entry as { enabled?: unknown }).enabled === true;
}

/* ---------- selection ---------- */

/** UTF-16 offsets into a string, as a textarea reports them. */
export interface TextRange {
  start: number;
  end: number;
}

const WHITE = /\s/;
let graphemes: Intl.Segmenter | null | undefined;

function segmenter(): Intl.Segmenter | null {
  if (graphemes === undefined) graphemes = typeof Intl !== 'undefined' && 'Segmenter' in Intl ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null;
  return graphemes;
}

const highSurrogate = (unit: number) => unit >= 0xd800 && unit <= 0xdbff;
const lowSurrogate = (unit: number) => unit >= 0xdc00 && unit <= 0xdfff;
/** True when `index` sits between the two halves of one code point. */
const insidePair = (text: string, index: number) => lowSurrogate(text.charCodeAt(index)) && highSurrogate(text.charCodeAt(index - 1));

/** The start of the character that holds the unit at `index`. */
function characterStart(text: string, index: number): number {
  if (index <= 0 || index >= text.length) return Math.max(0, Math.min(index, text.length));
  const clusters = segmenter();
  if (clusters) return clusters.segment(text).containing(index).index;
  return insidePair(text, index) ? index - 1 : index;
}

/** The end of the character that holds the unit before `index`. */
function characterEnd(text: string, index: number): number {
  if (index <= 0 || index >= text.length) return Math.max(0, Math.min(index, text.length));
  const clusters = segmenter();
  if (clusters) {
    const part = clusters.segment(text).containing(index - 1);
    return part.index + part.segment.length;
  }
  return insidePair(text, index) ? index + 1 : index;
}

const integer = (value: number) => (Number.isFinite(value) ? Math.trunc(value) : 0);

/**
 * The passage a selection names: white space at either end is left outside (so spacing and paragraph breaks are
 * never part of what is rewritten), and each end moves outward to a whole character. Null when nothing is left,
 * which means the whole draft.
 */
export function snapSelection(text: string, from: number, to: number): TextRange | null {
  let start = Math.max(0, Math.min(integer(Math.min(from, to)), text.length));
  let end = Math.max(0, Math.min(integer(Math.max(from, to)), text.length));
  while (start < end && WHITE.test(text[start])) start += 1;
  while (end > start && WHITE.test(text[end - 1])) end -= 1;
  if (start >= end) return null;
  start = characterStart(text, start);
  end = characterEnd(text, end);
  return start < end ? { start, end } : null;
}

export function codePointLength(text: string): number {
  let count = 0;
  for (let index = 0; index < text.length; index += 1) {
    count += 1;
    if (highSurrogate(text.charCodeAt(index)) && lowSurrogate(text.charCodeAt(index + 1))) index += 1;
  }
  return count;
}

/** A textarea's `selectionStart` / `selectionEnd` as the code-point offsets the server takes; null for the whole draft. */
export function toCodePointRange(text: string, from: number, to: number): DraftEditSelection | null {
  const range = snapSelection(text, from, to);
  if (!range) return null;
  const start = codePointLength(text.slice(0, range.start));
  return { start, end: start + codePointLength(text.slice(range.start, range.end)) };
}

/**
 * Saving can change the text around a selection (the server trims the ends). Finds the same passage in the saved
 * text: at its shifted offset when the saved text is the typed text without its ends, else at its single exact
 * match. Null when it cannot be placed for certain; the caller asks for a new selection instead of guessing.
 */
export function relocateSelection(before: string, range: TextRange, after: string): TextRange | null {
  const passage = before.slice(range.start, range.end);
  if (!passage) return null;
  const lead = before.indexOf(after);
  if (lead >= 0) {
    const start = range.start - lead;
    if (start >= 0 && after.slice(start, start + passage.length) === passage) return { start, end: start + passage.length };
  }
  const first = after.indexOf(passage);
  if (first >= 0 && after.indexOf(passage, first + 1) < 0) return { start: first, end: first + passage.length };
  return null;
}

/**
 * The writer reads at most 6,000 characters at once. A longer draft is rewritten one selected passage at a time,
 * and a selected passage has the same limit; the server refuses either with `draft_too_long_for_edit`, so the
 * request is not sent. `range` is the selection (already snapped), or null for the whole draft as it would be saved.
 */
export function tooLongToEdit(text: string, range: TextRange | null): boolean {
  return codePointLength(range ? text.slice(range.start, range.end) : text.trim()) > EDIT_TEXT_MAX;
}

/**
 * The voice a tone or polish edit is written in. Samples this writer may read: the person's own voice, as on every
 * drafting surface. Otherwise an approved profile without samples (one the person wrote, or one built from imported
 * posts) carries over only to a draft that was written in it, and only where its consent rules allow it
 * (`manualVoiceAvailable`); everything else stays neutral.
 */
export function editVoiceMode(input: { eligibleSamples: number; writtenInApprovedVoice: boolean; profileUsable: boolean }): 'neutral' | 'personalized' {
  if (input.eligibleSamples > 0) return 'personalized';
  return input.writtenInApprovedVoice && input.profileUsable ? 'personalized' : 'neutral';
}

/* ---------- showing a change ---------- */

/** How far a trimmed context may move to end on a word instead of inside one. */
const WORD_REACH = 24;

/** The end of unchanged text before a change: at most `limit` characters, whole ones, starting on a word when one is near. */
export function contextTail(text: string, limit: number): string {
  if (codePointLength(text) <= limit) return text;
  let cut = text.length;
  for (let kept = 0; kept < limit && cut > 0; kept += 1) cut -= insidePair(text, cut - 1) ? 2 : 1;
  cut = characterStart(text, cut);
  // Already on a word? Otherwise drop the cut-off word when the next one starts nearby.
  if (cut > 0 && !WHITE.test(text[cut - 1])) {
    const space = text.slice(cut, cut + WORD_REACH).search(WHITE);
    if (space >= 0 && cut + space + 1 < text.length) cut += space + 1;
  }
  return `…${text.slice(cut)}`;
}

/** The start of unchanged text after a change: the mirror of `contextTail`. */
export function contextHead(text: string, limit: number): string {
  if (codePointLength(text) <= limit) return text;
  let cut = 0;
  for (let kept = 0; kept < limit && cut < text.length; kept += 1) cut += highSurrogate(text.charCodeAt(cut)) && lowSurrogate(text.charCodeAt(cut + 1)) ? 2 : 1;
  cut = characterEnd(text, cut);
  if (cut < text.length && !WHITE.test(text[cut])) {
    const near = text.slice(Math.max(0, cut - WORD_REACH), cut);
    const space = near.search(/\s\S*$/);
    if (space > 0) cut = cut - near.length + space;
  }
  return `${text.slice(0, cut)}…`;
}

/* ---------- which candidate belongs to the draft on screen ---------- */

type DraftRef = Pick<SnapshotVariant, 'id' | 'revision' | 'proposedUpdate'>;
type ProposedUpdate = NonNullable<SnapshotVariant['proposedUpdate']>;
/** A tone or polish candidate waiting on a draft. */
export type PendingEdit = ProposedUpdate & { edit: DraftEditRecord };

/** What the server answered, with the draft revision the request was made against. */
export interface EditOutcome {
  revision: number;
  edit: Pick<DraftEditResult, 'status' | 'variantId'> & Partial<DraftEditResult>;
}

/**
 * The tone or polish candidate waiting on this draft, read from the draft itself so it is still there after a
 * reload. A regenerated version (no `edit`) is not one, and neither is a candidate written for an older revision.
 */
export function pendingEdit(variant: Pick<SnapshotVariant, 'revision' | 'proposedUpdate'>): PendingEdit | null {
  const update = variant.proposedUpdate;
  if (!update?.edit || update.baseVariantRevision !== variant.revision) return null;
  return update as PendingEdit;
}

/**
 * Whether an answer still describes the draft on screen. It stops matching when the draft has a newer revision,
 * when its candidate was discarded or replaced, or when the answer was for another draft; an unmatched answer is
 * never shown and never accepted.
 */
export function editMatches(outcome: EditOutcome | null | undefined, variant: DraftRef): boolean {
  if (!outcome || outcome.edit.variantId !== variant.id || outcome.revision !== variant.revision) return false;
  if (outcome.edit.status !== 'candidate') return true;
  const pending = pendingEdit(variant);
  if (!pending) return false;
  return !outcome.edit.runId || !pending.runId || pending.runId === outcome.edit.runId;
}

/** The revision this draft had just before its current one: what Undo restores. Null when there is none. */
export function previousRevision(variant: Pick<SnapshotVariant, 'revision' | 'revisions'>): number | null {
  let previous: number | null = null;
  for (const item of variant.revisions ?? []) {
    if (item.revision < variant.revision && (previous === null || item.revision > previous)) previous = item.revision;
  }
  return previous;
}

/* ---------- the request ---------- */

export interface EditRequestInput {
  choice: EditChoice;
  /** The person's own tone; sent only for a custom tone. */
  instruction: string;
  variantRevision: number;
  expectedRevision: number;
  /** Code-point offsets into the stored text, or null for the whole draft. */
  selection: DraftEditSelection | null;
  voiceMode: DraftVoiceMode;
  /** Named only when the person pinned a writer; otherwise the server uses the workspace default. */
  model?: string;
  idempotencyKey: string;
}

/**
 * The body of `POST …/drafts/{id}/edits`. A tone change on the whole draft starts from the wording before the last
 * accepted edit (`base: original`), so a second tone never builds on the first. A polish keeps the tone the draft
 * has now, and a selection's offsets index the current text, so both start from the current text. No depth is sent:
 * the server's default applies.
 */
export function editRequest(input: EditRequestInput): DraftEditRequest {
  const { choice } = input;
  const tone = choice.mode === 'tone' ? choice.tone : null;
  return {
    variantRevision: input.variantRevision,
    mode: choice.mode,
    ...(tone ? { tone } : {}),
    ...(tone === 'custom' ? { instruction: input.instruction.trim() } : {}),
    ...(input.selection ? { selection: input.selection } : {}),
    base: tone && !input.selection ? 'original' : 'current',
    voiceMode: input.voiceMode,
    ...(input.model ? { model: input.model } : {}),
    idempotencyKey: input.idempotencyKey,
    expectedRevision: input.expectedRevision
  };
}

/** What was asked, without the key or the workspace revision: the same question after a lost answer reuses its key. */
export function requestSignature(variantId: string, request: DraftEditRequest): string {
  return JSON.stringify([variantId, request.variantRevision, request.mode, request.tone ?? null, request.instruction ?? null, request.selection?.start ?? null, request.selection?.end ?? null, request.base ?? null, request.voiceMode ?? null, request.model ?? null]);
}

/* ---------- copy ---------- */

/**
 * Everything the control says, in English and Traditional Chinese (Hong Kong written Chinese). The editor dialog is
 * English-only today, so the panel renders `en`; passing another locale to it switches every string at once.
 * Functions only place their arguments: callers pass text that is already in the right language and case.
 */
export interface ToneCopy {
  title: string;
  intro: string;
  tones: Record<ToneId, string>;
  polish: string;
  customLabel: string;
  customPlaceholder: string;
  customApply: string;
  customMissing: string;
  scopeLabel: string;
  scopeDraft: string;
  scopeSelection: string;
  scopeHint: string;
  characters: (count: number) => string;
  tooLong: string;
  selectionLost: string;
  saving: string;
  rewritingTone: (tone: string) => string;
  rewritingCustom: string;
  polishing: string;
  untouched: string;
  accepting: string;
  discarding: string;
  undoing: string;
  ready: (name: string) => string;
  suggestionTitle: string;
  current: string;
  suggested: string;
  changedPrefix: string;
  removedPrefix: string;
  fidelityTitle: string;
  fidelityClear: string;
  voicePersonalized: string;
  voiceNeutral: string;
  basedOn: (base: string) => string;
  baseOriginal: (revision: number) => string;
  baseCurrent: string;
  use: string;
  discard: string;
  tryAnother: string;
  unsavedNote: string;
  noChange: string;
  failed: string;
  newDraft: string;
  gone: string;
  conflict: string;
  lost: string;
  saveFailed: string;
  acceptFailed: string;
  discardFailed: string;
  appliedNote: string;
  undo: string;
  applied: (name: string) => string;
  restored: string;
  restoreFailed: string;
  restoreStale: string;
  names: { tone: (tone: string) => string; custom: string; polish: string; unknown: string };
  /** The draft details sheet: restore a version, discard a proposed update. */
  sheet: {
    restoreVersion: string;
    restoreVersionOf: (what: string) => string;
    restoring: string;
    restoredTitle: string;
    restoredDetail: string;
    restoreFailed: string;
    discard: string;
    discarding: string;
    discardedTitle: string;
    discardFailed: string;
    changed: string;
    proposedEdit: (name: string, scope: string) => string;
    scheduling: string;
  };
}

const CONTRACT_TONES = Object.fromEntries(EDIT_TONES.map((tone) => [tone.id, tone.label])) as Record<ToneId, string>;

export const TONE_COPY: Record<ToneLocale, ToneCopy> = {
  en: {
    title: 'Tone for this draft',
    intro: 'Change the tone or polish the wording in one click. You compare the result before it replaces anything.',
    tones: CONTRACT_TONES,
    polish: EDIT_MODES[0].label,
    customLabel: 'Your own tone',
    customPlaceholder: 'For example: calm and encouraging',
    customApply: 'Apply',
    customMissing: 'Describe the tone you want first.',
    scopeLabel: 'Applies to:',
    scopeDraft: 'Whole draft',
    scopeSelection: 'Selected text',
    scopeHint: 'Select text in the draft to change only that part.',
    characters: (count) => `${count} ${count === 1 ? 'character' : 'characters'}`,
    tooLong: 'This draft is too long to rewrite in one go. Select a passage of up to 6,000 characters.',
    selectionLost: 'Your changes are saved. Select the passage again, then choose a tone.',
    saving: 'Saving your changes first…',
    rewritingTone: (tone) => `Rewriting in a ${tone} tone…`,
    rewritingCustom: 'Rewriting in your tone…',
    polishing: 'Polishing the wording…',
    untouched: 'Your draft stays as it is until you choose Use this.',
    accepting: 'Putting the new wording in your draft…',
    discarding: 'Discarding the suggestion…',
    undoing: 'Bringing back your earlier wording…',
    ready: (name) => `${name}: a suggestion is ready to review.`,
    suggestionTitle: 'Suggested wording',
    current: 'Current',
    suggested: 'Suggested',
    changedPrefix: 'Changed wording: ',
    removedPrefix: 'Removed wording: ',
    fidelityTitle: 'Check before you use it',
    fidelityClear: 'The check for changed facts found nothing. Read both versions anyway.',
    voicePersonalized: 'Voice: your approved voice',
    voiceNeutral: 'Voice: neutral',
    basedOn: (base) => `Rewritten from ${base}.`,
    baseOriginal: (revision) => `your version ${revision}`,
    baseCurrent: 'the current draft',
    use: 'Use this',
    discard: 'Discard',
    tryAnother: 'For a different tone, choose another one above. It starts from the same text.',
    unsavedNote: 'You changed the draft after this was written. Choose a tone again to rewrite your latest text.',
    noChange: 'This already reads well; nothing changed.',
    failed: 'Rafii couldn’t rewrite this draft. Nothing changed.',
    newDraft: 'This draft is already scheduled, so the new wording was saved as a separate draft.',
    gone: 'That suggestion is no longer available. Choose a tone again.',
    conflict: 'The draft or your voice profile changed in the meantime. The latest version is loaded; choose a tone again.',
    lost: 'Rafii didn’t answer in time. Choose the same option again to pick up the result.',
    saveFailed: 'Your changes couldn’t be saved, so nothing was rewritten.',
    acceptFailed: 'The new wording couldn’t be put in your draft. Nothing changed.',
    discardFailed: 'The suggestion couldn’t be discarded.',
    appliedNote: 'The new wording is in your draft.',
    undo: 'Undo',
    applied: (name) => `${name} applied`,
    restored: 'Your earlier wording is back',
    restoreFailed: 'Couldn’t bring back your earlier wording',
    restoreStale: 'The draft changed since then, so nothing was restored.',
    names: { tone: (tone) => `${tone} tone`, custom: 'Your tone', polish: 'Polished wording', unknown: 'New tone' },
    sheet: {
      restoreVersion: 'Restore this version',
      restoreVersionOf: (what) => `Restore this version: ${what}`,
      restoring: 'Restoring…',
      restoredTitle: 'Version restored',
      restoredDetail: 'It is the current text again. Review it before scheduling.',
      restoreFailed: 'Couldn’t restore this version',
      discard: 'Discard',
      discarding: 'Discarding…',
      discardedTitle: 'Proposed update discarded',
      discardFailed: 'Couldn’t discard the proposed update',
      changed: 'Something changed. The latest version is loaded; try again.',
      proposedEdit: (name, scope) => `${name} · ${scope}.`,
      scheduling: 'Scheduling uses this version.'
    }
  },
  'zh-Hant': {
    title: '這份草稿的語調',
    intro: '一按即可改變語調或潤飾文字。你可以先比較結果，才決定是否取代原文。',
    tones: { warm: '親切', professional: '專業', direct: '直接', playful: '輕鬆風趣', custom: '自訂' },
    polish: '潤飾文字',
    customLabel: '你自己的語調',
    customPlaceholder: '例如：平靜而帶鼓勵',
    customApply: '套用',
    customMissing: '請先描述你想要的語調。',
    scopeLabel: '套用範圍：',
    scopeDraft: '整份草稿',
    scopeSelection: '選取的文字',
    scopeHint: '在草稿中選取文字，就可以只更改該部分。',
    characters: (count) => `${count} 個字元`,
    tooLong: '這份草稿太長，無法一次過改寫。請選取不多於 6,000 個字元的段落。',
    selectionLost: '你的更改已儲存。請重新選取該段文字，然後再選擇語調。',
    saving: '正在先儲存你的更改…',
    rewritingTone: (tone) => `正在以「${tone}」語調改寫…`,
    rewritingCustom: '正在以你的語調改寫…',
    polishing: '正在潤飾文字…',
    untouched: '在你選擇「採用」之前，草稿會保持不變。',
    accepting: '正在把新文字放入草稿…',
    discarding: '正在捨棄建議…',
    undoing: '正在還原你先前的文字…',
    ready: (name) => `${name}：建議已準備好，請審閱。`,
    suggestionTitle: '建議文字',
    current: '目前',
    suggested: '建議',
    changedPrefix: '更改的用語：',
    removedPrefix: '移除的用語：',
    fidelityTitle: '採用前請檢查',
    fidelityClear: '檢查沒有發現事實有變。仍請細閱兩個版本。',
    voicePersonalized: '風格：你已批准的風格',
    voiceNeutral: '風格：中性',
    basedOn: (base) => `根據${base}改寫。`,
    baseOriginal: (revision) => `你的第 ${revision} 版`,
    baseCurrent: '目前的草稿',
    use: '採用',
    discard: '捨棄',
    tryAnother: '想試其他語調？請在上方另選一個，會由同一段文字開始改寫。',
    unsavedNote: '這個建議寫好之後，你更改過草稿。請再選一次語調，以改寫最新的文字。',
    noChange: '這份草稿已經寫得很好，沒有作出更改。',
    failed: 'Rafii 未能改寫這份草稿，內容沒有改動。',
    newDraft: '這份草稿已排程，所以新文字已另存為一份新草稿。',
    gone: '這個建議已不再可用，請再選一次語調。',
    conflict: '草稿或你的風格設定剛剛有變。已載入最新版本，請再選一次語調。',
    lost: 'Rafii 未能及時回應。請再選一次相同的選項，以取回結果。',
    saveFailed: '未能儲存你的更改，所以沒有進行改寫。',
    acceptFailed: '未能把新文字放入草稿，內容沒有改動。',
    discardFailed: '未能捨棄這個建議。',
    appliedNote: '新文字已放入你的草稿。',
    undo: '復原',
    applied: (name) => `已套用${name}`,
    restored: '已還原你先前的文字',
    restoreFailed: '未能還原你先前的文字',
    restoreStale: '草稿其後有變，所以沒有還原任何內容。',
    names: { tone: (tone) => `「${tone}」語調`, custom: '你的語調', polish: '潤飾後的文字', unknown: '新語調' },
    sheet: {
      restoreVersion: '還原此版本',
      restoreVersionOf: (what) => `還原此版本：${what}`,
      restoring: '正在還原…',
      restoredTitle: '已還原版本',
      restoredDetail: '這個版本已再次成為目前的文字。排程前請先審閱。',
      restoreFailed: '未能還原此版本',
      discard: '捨棄',
      discarding: '正在捨棄…',
      discardedTitle: '已捨棄更新建議',
      discardFailed: '未能捨棄更新建議',
      changed: '內容剛剛有變。已載入最新版本，請再試一次。',
      proposedEdit: (name, scope) => `${name} · ${scope}（建議）。`,
      scheduling: '排程時會採用這個版本。'
    }
  }
};

/** "Warm tone", "Your tone", "Polished wording": what a candidate or an applied edit is called. An id the web does not know is never shown raw. */
export function choiceName(choice: { mode: string; tone?: string | null }, locale: ToneLocale = 'en'): string {
  const copy = TONE_COPY[locale];
  if (choice.mode === 'polish') return copy.names.polish;
  if (choice.tone === 'custom') return copy.names.custom;
  const label = choice.tone ? (copy.tones as Record<string, string | undefined>)[choice.tone] : undefined;
  return label ? copy.names.tone(label) : copy.names.unknown;
}

/** What the writer is doing right now, for the status line. */
export function rewritingText(choice: EditChoice, locale: ToneLocale = 'en'): string {
  const copy = TONE_COPY[locale];
  if (choice.mode === 'polish') return copy.polishing;
  if (choice.tone === 'custom') return copy.rewritingCustom;
  const label = copy.tones[choice.tone];
  return copy.rewritingTone(locale === 'en' ? label.toLowerCase() : label);
}

/** "your version 3" when the edit started from the wording before the last accepted edit; else "the current draft". */
export function baseLabel(base: { kind?: string | null; revision?: number | null } | null | undefined, locale: ToneLocale = 'en'): string {
  const copy = TONE_COPY[locale];
  return base?.kind === 'original' && typeof base.revision === 'number' ? copy.baseOriginal(base.revision) : copy.baseCurrent;
}

/**
 * Each code the deterministic check can report (spec 5.4: the fifteen of the meaning check plus links, quotations
 * and language), as [English, Traditional Chinese]: what looks different, then what to do. Reminders, not verdicts.
 */
const FIDELITY: Record<string, readonly [string, string]> = {
  number_changed: ['A number changed. Check it against your original.', '有數字改了。請與原文核對。'],
  number_added: ['A number was added that your original did not have. Check that it is right.', '加入了原文沒有的數字。請確認是否正確。'],
  date_changed: ['A date or time changed. Check it against your original.', '有日期或時間改了。請與原文核對。'],
  name_changed: ['A name changed or is missing. Check it against your original.', '有名稱改了或不見了。請與原文核對。'],
  name_added: ['A name was added that your original did not have. Check that it belongs.', '加入了原文沒有的名稱。請確認是否應該出現。'],
  negation_lost: ['A “not” or “no” may be missing, which can reverse the meaning. Read that sentence again.', '「不」、「沒有」等否定字眼可能不見了，意思或會相反。請再讀一次該句。'],
  hedge_removed: ['A “might”, “about” or “so far” was dropped, so a claim reads as more certain. Check that you can stand behind it.', '「可能」、「大約」、「暫時」等字眼被刪去，說法變得更肯定。請確認你能為此負責。'],
  certainty_added: ['A claim now sounds more certain than you wrote it. Check that you can stand behind it.', '有說法比你原本寫的更肯定。請確認你能為此負責。'],
  attribution_lost: ['It is less clear who said or did something. Check that the right person is named.', '誰說過或做過某件事，變得不夠清楚。請確認提到的人正確。'],
  scope_changed: ['A word such as “some”, “all” or “only” changed, so a claim covers more or less than before. Check it against your original.', '「部分」、「全部」、「只有」等字眼改了，說法涵蓋的範圍與之前不同。請與原文核對。'],
  status_changed: ['Something planned or in progress now reads as done. Check that it has happened.', '計劃中或進行中的事，現在讀起來像已經完成。請確認是否已經發生。'],
  causal_added: ['A cause-and-effect claim was added that your original did not make. Check that it is true.', '加入了原文沒有的因果說法。請確認是否屬實。'],
  anecdote_added: ['A personal story was added that your original did not contain. Remove it unless it happened.', '加入了原文沒有的個人經歷。如非真有其事，請刪去。'],
  feeling_added: ['A feeling was added that your original did not state. Keep it only if it is yours.', '加入了原文沒有表達的感受。只有確實是你的感受才保留。'],
  brand_term_changed: ['One of your approved terms was changed or removed. Check it against your original.', '你已核准的用語被更改或刪去。請與原文核對。'],
  url_changed: ['A link, handle or hashtag changed. Check it against your original.', '有連結、帳號名稱或主題標籤改了。請與原文核對。'],
  quote_changed: ['Quoted words changed. Check them against your original.', '引述的文字改了。請與原文核對。'],
  language_changed: ['The language or script is different from your original. Check that this is what you want.', '語言或繁簡字體與原文不同。請確認這是你想要的。']
};
const FIDELITY_OTHER: readonly [string, string] = ['Something that should stay the same may have changed. Compare the two versions.', '有些應該保持不變的內容可能改了。請比較兩個版本。'];

export const FIDELITY_CODES: readonly string[] = Object.keys(FIDELITY);

/** One plain sentence for a fidelity code; a code this build does not know still reads as a reminder. */
export function fidelityMessage(code: string, locale: ToneLocale = 'en'): string {
  const pair = Object.prototype.hasOwnProperty.call(FIDELITY, code) ? FIDELITY[code] : FIDELITY_OTHER;
  return pair[locale === 'zh-Hant' ? 1 : 0];
}

/**
 * The values a check names (the number, the name, the term), read out of the server's note so they can be shown
 * beside the sentence: quoted items of a bracketed list, or words in curly quotes. A note that names nothing gives
 * nothing, and the note itself is never shown.
 */
export function violationValues(detail: string | null | undefined): string[] {
  if (!detail) return [];
  const values: string[] = [];
  const add = (raw: string) => {
    const value = raw.replace(/\\(.)/g, '$1').trim();
    if (value && value.length <= 60 && !values.includes(value)) values.push(value);
  };
  for (const list of detail.matchAll(/\[([^\]]*)\]/g)) {
    for (const item of list[1].matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)) add(item[1] ?? item[2] ?? '');
  }
  for (const quoted of detail.matchAll(/“([^”]*)”/g)) add(quoted[1]);
  return values.slice(0, 5);
}

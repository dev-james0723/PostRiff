/**
 * Suggestions, usage and voice in plain words (suggestions.py, usage.py, voice.py; PRD R11, R14, R15; A048, A054–A058).
 *
 *   - suggestions are a quiet in-app list: their cap and in-app-only delivery are stated, critical warnings can be
 *     dismissed or snoozed but never switched off, and nothing promises any other channel;
 *   - usage describes where an item appeared; a missing metric reads "unknown" (never 0) with its source time, and
 *     nothing claims an effect on results;
 *   - a voice example is one passage the owner attests to — never the whole file — and there is no score.
 *
 * No imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

/* --- suggestions ----------------------------------------------------------------------------------------------------- */

export const SUGGESTION_CATEGORY_LABEL: Record<string, string> = {
  outdated_source: 'A newer version exists',
  unused_relevant: 'Relevant and not used yet',
  missing_input: 'Something is missing',
  failed_processing: 'Processing failed',
  organization: 'Organizing idea',
  permission: 'Permission warning',
  source_integrity: 'Source warning'
};

export const SNOOZE_DEFAULT_DAYS = 7;

export function clampSnoozeDays(value: unknown): number {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return SNOOZE_DEFAULT_DAYS;
  return Math.min(90, Math.max(1, Math.round(number)));
}

export interface SuggestionLike {
  id: string;
  category: string;
  critical: boolean;
  actions: readonly string[];
}

export type SuggestionStateAction = 'dismiss' | 'snooze' | 'apply' | 'disable_category';

/**
 * The suggestion.set_state envelope for one press, or null when the item doesn't allow it. A critical warning can never
 * be switched off; apply exists only on organization proposals; snooze carries whole days from 1 to 90.
 */
export function suggestionEnvelope(item: SuggestionLike, action: SuggestionStateAction, options: { snoozeDays?: number; actionId: string }) {
  if (!item.actions.includes(action)) return null;
  if (action === 'disable_category' && item.critical) return null;
  if (action === 'apply' && item.category !== 'organization') return null;
  const payload: Record<string, unknown> = { suggestionId: item.id, action };
  if (action === 'snooze') payload.snoozeDays = clampSnoozeDays(options.snoozeDays ?? SNOOZE_DEFAULT_DAYS);
  return { actionId: options.actionId, uiInstanceId: 'library-suggestions', actionType: 'suggestion.set_state' as const, targetRefs: [], expectedRevision: null, payload };
}

/** The cap and delivery, as the server states them. */
export function capLine(inbox: { cap: { noncriticalPerDay: number; shownToday: number }; delivery: { channels: string[]; external: boolean } }): string {
  const { noncriticalPerDay, shownToday } = inbox.cap;
  const where = inbox.delivery.external || inbox.delivery.channels.some((channel) => channel !== 'in_app') ? '' : ' Shown only here in Rafii.';
  return `At most ${noncriticalPerDay} new ${noncriticalPerDay === 1 ? 'suggestion' : 'suggestions'} a day (${shownToday} today); permission and source warnings always show.${where}`;
}

export function affectedLabel(entry: { kind: string; key?: string; name?: string; itemCount?: number }): string {
  if (entry.kind === 'proposal') return `Proposed collection “${entry.name ?? 'Untitled'}”${typeof entry.itemCount === 'number' ? ` · ${entry.itemCount} ${entry.itemCount === 1 ? 'item' : 'items'}` : ''}`;
  const noun: Record<string, string> = { draft: 'Draft', post: 'Post', source_pack: 'Source pack', idea: 'Imported source', asset: 'Library item' };
  return noun[entry.kind] ?? entry.kind;
}

/* --- usage ------------------------------------------------------------------------------------------------------------ */

export interface MetricLike {
  value: number | null;
  display?: string;
  observedAt: number | null;
}

/** A missing or unreadable value is "unknown" — never 0. Real zeros stay zeros. */
export function metricValue(reading: MetricLike | null | undefined): string {
  if (!reading || typeof reading.value !== 'number' || !Number.isFinite(reading.value)) return 'unknown';
  return reading.value.toLocaleString('en-US');
}

export function metricName(name: string): string {
  const words = name.replace(/_/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : name;
}

export const USAGE_TYPE_LABEL: Record<string, string> = {
  source_pack: 'Added to a source pack',
  draft_attached: 'Attached to a draft',
  post_scheduled: 'Scheduled in a post',
  post_published: 'Published in a post',
  agent_answer: 'Cited in a Rafii answer',
  downloaded: 'Downloaded',
  post_job: 'Prepared in a post',
  post_review: 'In a post waiting for review',
  draft_cites_source: 'An Ideas draft uses it as a source',
  used_in: 'Cited'
};

export function usageLabel(entry: { type: string; source: string; kind?: string; status?: string }): string {
  if (entry.source === 'citation') {
    const noun: Record<string, string> = { draft: 'a draft', post: 'a post', source_pack: 'a source pack', idea: 'an imported source' };
    return `Cited by ${noun[entry.kind ?? ''] ?? 'other work'}${entry.status === 'stale' ? ' (an older version)' : ''}`;
  }
  return USAGE_TYPE_LABEL[entry.type] ?? entry.type.replace(/_/g, ' ');
}

/** Wording a usage view must never use: usage is correlation, not causation, and nothing is ranked. */
export const CAUSAL_WORDING = /\b(caused|causes|because of this|drove|boosted|led to|best[- ]performing|top[- ]performing|performed best|winning)\b/i;

/* --- voice ------------------------------------------------------------------------------------------------------------ */

export const VOICE_LOCATOR_KINDS = ['text', 'time', 'page', 'slide'] as const;
export const VOICE_SEGMENT_KINDS = ['text', 'page', 'slide', 'transcript', 'note'] as const;
const PERSONA = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/;
const LANGUAGE = /^[a-z]{2,3}(-[A-Za-z]{2,4})?$/;
export const LOCAL_ANALYSIS_ROUTE = 'local-rules';
export const MANAGED_WRITER_ROUTE = 'cloud:vercel-ai-gateway:*';

export interface SegmentLike {
  id: string;
  kind: string;
  text: string;
  locator?: (Record<string, unknown> & { kind: string }) | null;
  origin?: string;
  language?: string | null;
}

/** Passages that can become voice examples: one text, page, slide or transcript passage at a time. */
export function voicePassages<T extends SegmentLike>(segments: readonly T[]): T[] {
  return segments.filter(
    (segment) =>
      (VOICE_SEGMENT_KINDS as readonly string[]).includes(segment.kind) &&
      Boolean(segment.locator) &&
      (VOICE_LOCATOR_KINDS as readonly string[]).includes(segment.locator!.kind) &&
      segment.text.trim().length > 0
  );
}

export interface VoiceDraft {
  passage: SegmentLike | null;
  polarity: 'positive' | 'negative';
  personaId: string;
  language: string;
  attested: boolean;
  method: 'written_by_me' | 'spoken_by_me' | 'published_by_me';
  localAnalysis: boolean;
  writer: boolean;
  grantVoice: boolean;
  approveGeneratedText: boolean;
}

export type VoiceRequest = { ok: true; payload: Record<string, unknown> } | { ok: false; reason: string };

/** The voice.approve_span payload: exactly one passage's locator, an explicit attestation, explicit persona and language. */
export function voiceApproval(draft: VoiceDraft, totalPassages: number): VoiceRequest {
  if (!draft.passage || !draft.passage.locator) return { ok: false, reason: 'Choose one passage. Only the passages you choose teach your voice.' };
  if (!(VOICE_LOCATOR_KINDS as readonly string[]).includes(draft.passage.locator.kind)) return { ok: false, reason: 'Choose a text passage, a page, a slide or a spoken moment.' };
  if (totalPassages < 1) return { ok: false, reason: 'This item has no passages to choose from yet.' };
  if (!draft.attested) return { ok: false, reason: 'Confirm that you wrote or said this yourself.' };
  if (!PERSONA.test(draft.personaId)) return { ok: false, reason: 'Name the persona with letters, numbers or - _ . : (default is your workspace voice).' };
  if (!LANGUAGE.test(draft.language)) return { ok: false, reason: 'Give the passage’s language, such as yue, zh-Hant or en.' };
  const uses = [
    ...(draft.localAnalysis ? [{ purpose: 'analysis', route: LOCAL_ANALYSIS_ROUTE }] : []),
    ...(draft.writer ? [{ purpose: 'generation', route: MANAGED_WRITER_ROUTE }] : [])
  ];
  if (draft.polarity === 'positive' && uses.length === 0) return { ok: false, reason: 'Choose how this example may be used.' };
  const payload: Record<string, unknown> = {
    locator: draft.passage.locator,
    personaId: draft.personaId,
    language: draft.language,
    polarity: draft.polarity,
    attestation: { authoredByMe: true, method: draft.method },
    confirmed: true
  };
  if (draft.polarity === 'positive') payload.uses = uses;
  if (draft.grantVoice) payload.grantVoice = true;
  if (draft.approveGeneratedText) payload.approveGeneratedText = true;
  return { ok: true, payload };
}

/** voice.revoke: one example, confirmed, at the revision the person saw. */
export function voiceRevocation(sample: { sampleId: string; revision: number; assetRef: { assetId: string; versionId: string; sha256: string } }, actionId: string) {
  return { actionId, uiInstanceId: 'library-voice', actionType: 'voice.revoke' as const, targetRefs: [sample.assetRef], expectedRevision: sample.revision, payload: { sampleId: sample.sampleId, confirmed: true } };
}

/** Provenance and coverage only: counts, never a percentage or score. */
export function voiceCoverage(samples: readonly { status: string }[], negatives: readonly { status: string }[]): string {
  const approved = samples.filter((sample) => sample.status === 'approved').length;
  const avoid = negatives.filter((sample) => sample.status === 'approved').length;
  return `${approved} ${approved === 1 ? 'voice example' : 'voice examples'} · ${avoid} “don’t write like this” ${avoid === 1 ? 'example' : 'examples'} from this item`;
}

export const METHOD_LABEL: Record<string, string> = { written_by_me: 'I wrote it', spoken_by_me: 'I said it', published_by_me: 'I published it' };

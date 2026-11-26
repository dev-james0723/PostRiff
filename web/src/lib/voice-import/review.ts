/**
 * Reading a voice proposal that was built from imported posts (`analysisMethod: 'voice_import'`). Such a proposal
 * cites posts by id and holds none of their text; the review shows excerpts by loading them, and offers four quick
 * corrections per trait. Pure functions, so the rules can be tested without a browser.
 */
import type { VoiceProfile } from '../api/types';
import { languageName, pick, platformName } from './labels';
import type { Language } from './labels';

export type ReviewTrait = NonNullable<VoiceProfile['dimensions']>[number];
export type Correction = 'sounds_like_me' | 'not_me' | 'only_scope' | 'old_style';

export function isImportProfile(profile: Pick<VoiceProfile, 'analysisMethod'> | null | undefined): boolean {
  return profile?.analysisMethod === 'voice_import';
}

const whole = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0);

/** The posts a trait cites (the proposal stores at most twelve ids), how many posts show it and how many do not. */
export function traitEvidence(trait: ReviewTrait): { postIds: string[]; count: number; counter: number } {
  const postIds = Array.isArray(trait.evidence?.postIds) ? trait.evidence.postIds.filter((id): id is string => typeof id === 'string' && id !== '') : [];
  return { postIds, count: Math.max(whole(trait.evidence?.count), postIds.length), counter: whole(trait.evidence?.counter) };
}

/**
 * Whether a trait can go forward as it stands: it has evidence, or it is the person's own rule, or it is already out
 * of the voice (rejected, historical, or without enough examples to be used).
 */
export function traitSettled(trait: ReviewTrait): boolean {
  if (trait.decision === 'reject' || trait.status === 'historical') return true;
  if (trait.evidenceLevel === 'insufficient' || trait.evidenceLevel === 'user-defined' || trait.userAuthored) return true;
  return traitEvidence(trait).count > 0;
}

/** Which of the four corrections already hold, read from the proposal the workspace returned. */
export function correctionState(trait: ReviewTrait): { soundsLikeMe: boolean; notMe: boolean; oldStyle: boolean; onlyFor: string[] } {
  return {
    soundsLikeMe: trait.decision === 'accept' && trait.status !== 'historical',
    notMe: trait.decision === 'reject',
    oldStyle: trait.status === 'historical',
    onlyFor: (trait.scope?.platforms ?? []).map((platform) => platform.toLowerCase())
  };
}

/** Platforms a trait can be limited to: its own scope first, then every platform posts were imported from. At most four. */
export function scopePlatforms(trait: ReviewTrait, corpus: string[]): string[] {
  const seen = new Set<string>();
  for (const platform of [...(trait.scope?.platforms ?? []), ...corpus]) {
    const id = platform.trim().toLowerCase();
    if (id) seen.add(id);
  }
  return [...seen].slice(0, 4);
}

/** The payload of `brand_brain_trait_correct`. Limiting a trait to a platform keeps any language or account limit it already has. */
export function correctionPayload(trait: ReviewTrait, proposalDigest: string | null, correction: Correction, platform?: string): Record<string, unknown> {
  return {
    proposalDigest,
    traitId: trait.id,
    correction,
    ...(correction === 'only_scope' && platform ? { scope: { ...trait.scope, platforms: [platform.toLowerCase()] } } : {})
  };
}

/** Where a trait applies, as short labels: "Only on LinkedIn", "Only in Cantonese", "Only for <account>". */
export function scopeLabels(trait: ReviewTrait, language: Language): string[] {
  const labels: string[] = [];
  for (const platform of trait.scope?.platforms ?? []) labels.push(pick(language, [`Only on ${platformName(platform)}`, `只限 ${platformName(platform)}`, `仅限 ${platformName(platform)}`]));
  for (const tag of trait.scope?.languages ?? []) labels.push(pick(language, [`Only in ${languageName(tag, 'en')}`, `只限${languageName(tag, 'zh-Hant')}`, `仅限${languageName(tag, 'zh-Hans')}`]));
  for (const account of trait.scope?.accounts ?? []) labels.push(pick(language, [`Only for ${account}`, `只限帳戶 ${account}`, `仅限账户 ${account}`]));
  return labels;
}

/** How a trait was reached. A person's own rule is never presented as something learned. */
export function basisLabel(trait: ReviewTrait, language: Language): string {
  if (trait.userAuthored || trait.evidenceLevel === 'user-defined' || trait.basis === 'user') return pick(language, ['Your own rule', '你自己的規則', '你自己的规则']);
  if (trait.basis === 'model') return pick(language, ['Read by AI from your posts', '由 AI 從你的貼文解讀', '由 AI 从你的帖子解读']);
  return pick(language, ['Measured in your posts', '從你的貼文量度', '从你的帖子测量']);
}

/**
 * The review's identity. Quick corrections change the proposal's digest; within one import proposal the review
 * stays mounted so typed wording survives them, and a newly built proposal (a new `proposedAt`) starts fresh.
 * Any other proposal keeps the digest as its key, as before.
 */
export function reviewKey(proposal: Pick<VoiceProfile, 'analysisMethod' | 'proposedAt'> | null | undefined, digest: string | null): string {
  if (isImportProfile(proposal) && proposal?.proposedAt !== undefined && proposal.proposedAt !== '') return `voice-import:${proposal.proposedAt}`;
  return digest ?? 'none';
}

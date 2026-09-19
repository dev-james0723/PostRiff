/**
 * Pure reads over the workspace snapshot for Brand & voice. Every value comes from the snapshot;
 * `null` means the snapshot did not carry it, which the page shows as "Unavailable", never as 0.
 */
import type { BrandMode, SnapshotState, Speaker, VoiceProfile } from '@/lib/api/types';

export type VoiceRevision = Speaker['revisions'][number];

/** Job states the scheduler holds when the voice or brand context changes (store.invalidate). */
const BOUND_JOB_STATES = new Set(['scheduled', 'approved', 'claimed']);

export const MODE_LABELS: Record<BrandMode, string> = {
  personal: 'A personal brand',
  niche: 'A niche or expertise',
  business: 'A business',
  hybrid: 'A mix'
};

export const TONE_LABELS: Record<string, { label: string; note: string }> = {
  warm: { label: 'Warm', note: 'Friendly, encouraging, first person.' },
  direct: { label: 'Direct', note: 'Short sentences, clear claims, no hedging.' },
  reflective: { label: 'Reflective', note: 'Thoughtful, slower, asks questions.' }
};

export function toneLabel(tone: string | undefined | null) {
  if (!tone) return null;
  return TONE_LABELS[tone]?.label ?? tone;
}

export type VoiceStatus =
  | { kind: 'unavailable' }
  | { kind: 'active'; revision: number; record: VoiceRevision | null; waiting: boolean }
  | { kind: 'waiting' }
  | { kind: 'none'; earlier: number };

export function voiceStatus(state: SnapshotState | undefined): VoiceStatus {
  const speaker = state?.speaker;
  if (!speaker || !Array.isArray(speaker.revisions)) return { kind: 'unavailable' };
  const active = speaker.activeRevision;
  if (active) {
    const record = speaker.revisions.find((r) => r.revision === active) ?? null;
    return { kind: 'active', revision: active, record, waiting: Boolean(speaker.provisional) };
  }
  if (speaker.provisional) return { kind: 'waiting' };
  return { kind: 'none', earlier: speaker.revisions.length };
}

export function activeProfile(state: SnapshotState | undefined): VoiceProfile | null {
  const speaker = state?.speaker;
  if (!speaker?.activeRevision) return null;
  return speaker.revisions.find((r) => r.revision === speaker.activeRevision)?.profile ?? null;
}

/**
 * The profile download (`GET /profile-export`) only succeeds for a voice approved field by field
 * (`packageSchema`, hosted.export_profile). A voice from the setup on this page never carries one.
 */
export function canExportPackage(profile: VoiceProfile | null) {
  return Boolean(profile && (profile as { packageSchema?: unknown }).packageSchema);
}

export interface VoiceCounts {
  /** Every draft in the workspace. */
  drafts: number | null;
  /** Drafts written with the active revision (scheduling needs this match, store.py). */
  onVoice: number | null;
  /** Drafts written with an earlier voice or none. */
  earlier: number | null;
  /** Posts approved or scheduled and not yet out; a voice change holds them. */
  bound: number | null;
}

export function voiceCounts(state: SnapshotState | undefined): VoiceCounts {
  const variants = Array.isArray(state?.variants) ? state.variants : null;
  const jobs = Array.isArray(state?.phase2?.jobs) ? state.phase2.jobs : null;
  const active = state?.speaker?.activeRevision ?? null;
  return {
    drafts: variants ? variants.length : null,
    onVoice: variants && active ? variants.filter((v) => v.voiceRevision === active).length : null,
    earlier: variants && active ? variants.filter((v) => v.voiceRevision !== active).length : null,
    bound: jobs ? jobs.filter((j) => BOUND_JOB_STATES.has(j.state)).length : null
  };
}

/** ISO `approvedAt` → epoch seconds for the shared time helpers; null when it cannot be read. */
export function isoToEpoch(value: string | undefined | null) {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms / 1000;
}

/** The server writes one of two reasons (domain.profile_decide, visuals.you_restore_voice); anything else is shown as written. */
export function reasonLabel(reason: string | undefined | null) {
  if (!reason) return null;
  if (reason === 'Explicit provisional-profile approval') return 'Approved from a proposal';
  const restore = /^Explicit restore of voice revision (\d+)$/.exec(reason);
  if (restore) return `Restored from revision ${restore[1]}`;
  return reason;
}

function list(value: unknown): string[] | null {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : null;
}

function countPhrase(added: number, removed: number) {
  const parts = [];
  if (added) parts.push(`${added} added`);
  if (removed) parts.push(`${removed} removed`);
  return parts.join(', ');
}

/**
 * What differs between two stored voice profiles, in plain words. Revisions store the whole profile,
 * so this compares real data. Returns null when either side is missing: the page then says nothing
 * about changes rather than guessing. An empty list means the two are the same.
 */
export function describeChanges(previous: VoiceProfile | null | undefined, next: VoiceProfile | null | undefined): string[] | null {
  if (!previous || !next) return null;
  const changes: string[] = [];

  if (previous.tone !== next.tone) {
    changes.push(`Tone ${toneLabel(previous.tone) ?? 'not set'} → ${toneLabel(next.tone) ?? 'not set'}`);
  }

  const beforeObs = list(previous.observations);
  const afterObs = list(next.observations);
  if (beforeObs && afterObs) {
    const added = afterObs.filter((item) => !beforeObs.includes(item)).length;
    const removed = beforeObs.filter((item) => !afterObs.includes(item)).length;
    if (added || removed) changes.push(`Observations: ${countPhrase(added, removed)}`);
  }

  const beforeSample = typeof previous.writingExample === 'string' ? previous.writingExample.trim() : '';
  const afterSample = typeof next.writingExample === 'string' ? next.writingExample.trim() : '';
  if (!beforeSample && afterSample) changes.push('Sample added');
  else if (beforeSample && !afterSample) changes.push('Sample removed');
  else if (beforeSample !== afterSample) changes.push('Sample replaced');

  const beforeUnknowns = list(previous.unknowns);
  const afterUnknowns = list(next.unknowns);
  if (beforeUnknowns && afterUnknowns) {
    const added = afterUnknowns.filter((item) => !beforeUnknowns.includes(item)).length;
    const removed = beforeUnknowns.filter((item) => !afterUnknowns.includes(item)).length;
    if (added || removed) changes.push(`Unknowns: ${countPhrase(added, removed)}`);
  }

  const beforeFields = (previous as { fields?: unknown }).fields;
  const afterFields = (next as { fields?: unknown }).fields;
  if ((beforeFields !== undefined || afterFields !== undefined) && JSON.stringify(beforeFields ?? null) !== JSON.stringify(afterFields ?? null)) {
    changes.push('Profile answers changed');
  }

  return changes;
}

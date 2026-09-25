/**
 * Turning an agent's schedule plan into scheduled jobs (design §4.4).
 *
 * The chat never publishes. Approving a plan replays, per destination, exactly the
 * steps a person takes by hand in the Queue: apply the candidate → accept a pending
 * update → confirm unknowns stay out → freeze an exact review → approve every review
 * at once (`p2_approve_many`, one scheduleId, one job per destination).
 */
import type { PostRiffApi } from '@/lib/api/client';
import type { Run, Snapshot, SnapshotState, SnapshotVariant } from '@/lib/api/types';
import { locales } from '@/lib/locales';

export interface PlanRow {
  platform: string;
  language: string;
  /** Naive local ISO string, as the `datetime-local` input produces. */
  localTime: string;
  channelId: string;
  assetId?: string;
  alt?: string;
}

export interface ApproveResult {
  revision: number;
  jobs: number;
  scheduleId: string | null;
  snapshot: Snapshot;
}

/** Which part of the chain a progress message belongs to: the apply, one row (by index in `rows`), or the final approve. */
export type ApproveStep = { id: 'apply' } | { id: 'row'; index: number } | { id: 'approve' };

/** The variant `apply` created (or updated) for this run and destination. */
export function variantForRow(state: SnapshotState, run: Run, row: { platform: string; language: string; channelId?: string }): SnapshotVariant | undefined {
  const owned = (state.variants ?? []).filter((v) => v.platform === row.platform && locales.same(v.language, row.language) && !v.blockedByRetraction && (v.provenance?.runId === run.runId || v.proposedUpdate?.runId === run.runId));
  const exact = owned.filter((v) => (v.channelId ?? undefined) === (row.channelId ?? undefined));
  if (exact.length === 1) return exact[0];
  // Legacy platform-only drafts can be deliberately assigned, but never borrow another account/run.
  if (row.channelId && owned.length === 1 && !owned[0].channelId) return owned[0];
  return undefined;
}

export async function approvePlan(input: {
  api: PostRiffApi;
  workspaceId: string;
  run: Run;
  snapshot: Snapshot;
  rows: PlanRow[];
  timeZone: string;
  onProgress?: (message: string, step?: ApproveStep) => void;
}): Promise<ApproveResult> {
  const { api, workspaceId, run, rows, timeZone, onProgress } = input;
  let snapshot = input.snapshot;
  const act = async (action: string, payload: Record<string, unknown>) => {
    snapshot = await api.act(workspaceId, snapshot.revision, action, payload);
    return snapshot;
  };

  if (run.status !== 'applied') {
    if (!run.artifactHash) throw new Error('This candidate has no reviewable text yet.');
    onProgress?.('Saving drafts…', { id: 'apply' });
    await api.applyRun(workspaceId, run.runId, snapshot.revision, run.artifactHash);
    snapshot = await api.snapshot(workspaceId);
  }

  const reviews: { reviewId: string; digest: string }[] = [];
  for (const [index, row] of rows.entries()) {
    const step: ApproveStep = { id: 'row', index };
    let variant = variantForRow(snapshot.state, run, row);
    // Thrown before this row's first progress message, so the error names its step for progress displays.
    if (!variant) throw Object.assign(new Error(`No ${row.platform} draft was created for this run.`), { step });
    const activeVoice = snapshot.state.speaker?.activeRevision ?? null;
    if (variant.proposedUpdate && variant.proposedUpdate.voiceRevision === activeVoice) {
      onProgress?.(`Accepting the updated ${row.platform} draft…`, step);
      await act('accept_update', { variantId: variant.id });
      variant = variantForRow(snapshot.state, run, row) ?? variant;
    }
    if (variant.needsReview || variant.unknowns.length > 0) {
      onProgress?.(`Checking ${row.platform} unknowns…`, step);
      await act('p2_variant_review', {
        variantId: variant.id,
        variantRevision: variant.revision,
        confirmed: true,
        excludedUnknowns: variant.unknowns
      });
      variant = snapshot.state.variants?.find((v) => v.id === variant!.id) ?? variant;
    }
    onProgress?.(`Preparing ${row.platform}…`, step);
    await act('p2_review', {
      variantId: variant.id,
      channelId: row.channelId,
      assetId: row.assetId || undefined,
      alt: row.alt?.trim() ?? '',
      rightsConfirmed: true,
      localTime: row.localTime,
      timeZone,
      acknowledgedWarnings: variant.warnings
    });
    const review = snapshot.state.phase2?.reviews.at(-1);
    if (!review) throw new Error(`The ${row.platform} review was not created.`);
    reviews.push({ reviewId: review.id, digest: review.digest });
  }

  onProgress?.(`Approving ${reviews.length} destination${reviews.length === 1 ? '' : 's'}…`, { id: 'approve' });
  const before = new Set((snapshot.state.phase2?.jobs ?? []).map((job) => job.id));
  await act('p2_approve_many', { reviews, confirmed: true });
  const created = (snapshot.state.phase2?.jobs ?? []).filter((job) => !before.has(job.id));
  const scheduleId = (created[0] as { scheduleId?: string } | undefined)?.scheduleId ?? null;
  return { revision: snapshot.revision, jobs: created.length, scheduleId, snapshot };
}

/** Naive local ISO ("2026-09-16T16:00") → epoch seconds in the browser's zone (display only). */
export function localTimeToDate(localTime: string): Date | null {
  const parsed = new Date(localTime);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

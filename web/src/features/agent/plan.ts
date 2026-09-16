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

/** The variant `apply` created (or updated) for this run and destination. */
export function variantForRow(state: SnapshotState, run: Run, row: { platform: string; language: string }): SnapshotVariant | undefined {
  const matches = (state.variants ?? []).filter((v) => v.platform === row.platform && v.language === row.language && !v.blockedByRetraction);
  return (
    matches.find((v) => v.provenance?.runId === run.runId) ??
    matches.find((v) => v.proposedUpdate?.runId === run.runId) ??
    matches[matches.length - 1]
  );
}

export async function approvePlan(input: {
  api: PostRiffApi;
  workspaceId: string;
  run: Run;
  snapshot: Snapshot;
  rows: PlanRow[];
  timeZone: string;
  onProgress?: (message: string) => void;
}): Promise<ApproveResult> {
  const { api, workspaceId, run, rows, timeZone, onProgress } = input;
  let snapshot = input.snapshot;
  const act = async (action: string, payload: Record<string, unknown>) => {
    snapshot = await api.act(workspaceId, snapshot.revision, action, payload);
    return snapshot;
  };

  if (run.status !== 'applied') {
    if (!run.artifactHash) throw new Error('This candidate has no reviewable text yet.');
    onProgress?.('Adding the candidates to your drafts…');
    await api.applyRun(workspaceId, run.runId, snapshot.revision, run.artifactHash);
    snapshot = await api.snapshot(workspaceId);
  }

  const reviews: { reviewId: string; digest: string }[] = [];
  for (const row of rows) {
    let variant = variantForRow(snapshot.state, run, row);
    if (!variant) throw new Error(`No ${row.platform} draft was created for this run.`);
    const activeVoice = snapshot.state.speaker?.activeRevision ?? null;
    if (variant.proposedUpdate && variant.proposedUpdate.voiceRevision === activeVoice) {
      onProgress?.(`Accepting the updated ${row.platform} draft…`);
      await act('accept_update', { variantId: variant.id });
      variant = variantForRow(snapshot.state, run, row) ?? variant;
    }
    if (variant.needsReview || variant.unknowns.length > 0) {
      onProgress?.(`Confirming unknowns stay out of the ${row.platform} draft…`);
      await act('p2_variant_review', {
        variantId: variant.id,
        variantRevision: variant.revision,
        confirmed: true,
        excludedUnknowns: variant.unknowns
      });
      variant = snapshot.state.variants?.find((v) => v.id === variant!.id) ?? variant;
    }
    onProgress?.(`Preparing the exact ${row.platform} review…`);
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

  onProgress?.(`Approving ${reviews.length} destination${reviews.length === 1 ? '' : 's'}…`);
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

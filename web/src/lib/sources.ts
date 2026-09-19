import type { SnapshotSource, SnapshotState, SnapshotVariant } from '@/lib/api/types';
import { WAITING } from './jobs';

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

export function activeSources(state: SnapshotState): SnapshotSource[] {
  return (state.sources ?? []).filter((source) => source.active);
}

export function draftsUsing(state: SnapshotState, sourceId: string): SnapshotVariant[] {
  return (state.variants ?? []).filter((variant) => (variant.sourceIds ?? []).includes(sourceId));
}

/** `retract_source` resets the brief's idea when the retracted source is the one the idea came from (`domain.py`). */
export function isIdeaSource(state: SnapshotState, sourceId: string) {
  const brief = state.brief as { ideaSourceId?: string } | undefined;
  return brief?.ideaSourceId === sourceId;
}

/** Consequences for drafts and waiting posts that cite this source. */
export interface RetractionImpact {
  /** Drafts that list this source. */
  using: number;
  /** Of those, the ones not blocked yet. */
  newlyBlocked: number;
  /** Replacement drafts waiting to be accepted; they are discarded. */
  pendingUpdates: number;
  /** Posts waiting in the Queue (scheduled, approved or claimed); they are held until approved again. */
  heldPosts: number;
  /** The current idea came from this source and is reset. */
  resetsIdea: boolean;
}

export function retractionImpact(state: SnapshotState, sourceId: string): RetractionImpact {
  const using = draftsUsing(state, sourceId);
  return {
    using: using.length,
    newlyBlocked: using.filter((variant) => !variant.blockedByRetraction).length,
    pendingUpdates: using.filter((variant) => variant.proposedUpdate != null).length,
    heldPosts: (state.phase2?.jobs ?? []).filter((job) => WAITING.has(job.state) && using.some((variant) => variant.id === job.manifest.variantId)).length,
    resetsIdea: isIdeaSource(state, sourceId)
  };
}

/** One sentence per consequence, in the order they matter. Shared by the preview list and the success toast. */
export function retractionLines(impact: RetractionImpact): string[] {
  const lines: string[] = [];
  const { using, newlyBlocked, pendingUpdates, heldPosts } = impact;
  const alreadyBlocked = using - newlyBlocked;
  if (using === 0) lines.push('No draft uses this source, so none is blocked by it.');
  else if (newlyBlocked === 0)
    lines.push(
      `${using === 1 ? 'The draft that uses this source is already blocked and stays' : `All ${using} drafts that use this source are already blocked and stay`} blocked until drafted again.`
    );
  else if (alreadyBlocked > 0)
    lines.push(
      `${plural(using, 'draft')} ${using === 1 ? 'uses' : 'use'} this source: ${newlyBlocked} will be newly blocked (${alreadyBlocked} already ${alreadyBlocked === 1 ? 'is' : 'are'}) until drafted again. They keep their text.`
    );
  else
    lines.push(
      `${plural(using, 'draft')} ${using === 1 ? 'uses' : 'use'} this source and will be blocked until drafted again. ${using === 1 ? 'It keeps its' : 'They keep their'} text.`
    );
  if (pendingUpdates > 0) lines.push(`${plural(pendingUpdates, 'proposed update')} waiting to be accepted will be discarded.`);
  if (heldPosts > 0) lines.push(`${plural(heldPosts, 'post')} waiting in the Queue will be held until approved again.`);
  if (impact.resetsIdea) lines.push("The current idea came from this source and will be reset.");
  return lines;
}

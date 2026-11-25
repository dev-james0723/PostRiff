import type { SnapshotState } from '@/lib/api/types';

export interface SuggestionDraft {
  text: string;
  channelId: string;
  platform: string;
  account: string;
  sourceIds: string[];
}

/** The URL carries only an opaque id; content comes from the authenticated snapshot.
 * Loading re-runs the server's accept action, which rechecks current evidence.
 */
export function suggestionDraft(state: SnapshotState | undefined, workspaceId: string, suggestionId: string | null, draftable: readonly string[]): SuggestionDraft | null {
  if (!state || !suggestionId || (state.workspace?.id && state.workspace.id !== workspaceId)) return null;
  const suggestion = state.raffi?.suggestions?.find((item) => item.id === suggestionId);
  const ref = suggestion?.actionRef;
  if (suggestion?.status !== 'accepted' || suggestion.kind !== 'missing_variant' ||
      ref?.authority !== 'open_for_review' || ref.type !== 'draft_intent' ||
      ref.workspaceId !== workspaceId || ref.targetType !== 'channel' || !ref.targetId) return null;
  const brief = state.brief as { idea?: unknown; revision?: unknown; sourceIds?: unknown } | undefined;
  if (typeof brief?.idea !== 'string' || !brief.idea.trim() || ref.targetRevision !== brief.revision) return null;
  const channel = state.phase2?.channels.find((item) => item.id === ref.targetId && !item.revoked);
  if (!channel || !draftable.includes(channel.platform)) return null;
  const activeSources = new Set((state.sources ?? []).filter((source) => source.active && source.kind !== 'voice_sample').map((source) => source.id));
  return { text: brief.idea, channelId: channel.id, platform: channel.platform, account: channel.account,
    sourceIds: Array.isArray(brief.sourceIds) ? brief.sourceIds.filter((id): id is string => typeof id === 'string' && activeSources.has(id)) : [] };
}

/** A suggestion never overwrites a different unfinished idea or its attachments. */
export function canLoadSuggestion(currentText: string, suggestion: SuggestionDraft, attachmentCount: number): boolean {
  return attachmentCount === 0 && (!currentText.trim() || currentText === suggestion.text);
}

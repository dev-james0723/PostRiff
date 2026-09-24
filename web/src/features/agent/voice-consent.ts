import type { ModelOption, SnapshotSource } from '@/lib/api/types';

/** UI eligibility follows the exact route issued by the server catalogue. */
export function eligibleVoiceSources(sources: SnapshotSource[], model: ModelOption | undefined): string[] {
  if (!model?.qualified || !model.voiceRoute) return [];
  return sources.filter((source) => source.kind === 'voice_sample' && source.active && source.selected && source.useGrants?.some((grant) => grant.purpose === 'generation' && grant.route === model.voiceRoute)).map((source) => source.id);
}

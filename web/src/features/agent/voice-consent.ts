import type { ModelOption, SnapshotSource } from '@/lib/api/types';

/** A writing grant covers this writer when it names its exact route, or the class the server lists for it
 * (voiceRouteClass: every model Rafii's managed writer offers). Drafts still record the exact route they used. */
function covers(route: string, model: ModelOption): boolean {
  return route === model.voiceRoute || (Boolean(model.voiceRouteClass) && route === model.voiceRouteClass);
}

/** UI eligibility follows the routes issued by the server catalogue. */
export function eligibleVoiceSources(sources: SnapshotSource[], model: ModelOption | undefined): string[] {
  if (!model?.qualified || !model.voiceRoute) return [];
  return sources.filter((source) => source.kind === 'voice_sample' && source.active && source.selected && source.useGrants?.some((grant) => grant.purpose === 'generation' && covers(grant.route, model))).map((source) => source.id);
}

/** The voice a draft is written in: the person's own choice, else writing like them whenever this writer may read a
 * sample they approved. Neutral when none is eligible, as the server falls back too; consent itself is unchanged. */
export function effectiveVoiceMode(choice: 'neutral' | 'personalized' | null, eligible: number): 'neutral' | 'personalized' {
  return eligible > 0 ? (choice ?? 'personalized') : 'neutral';
}

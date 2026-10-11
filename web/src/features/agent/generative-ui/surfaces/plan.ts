/**
 * Surface mapping and the presentation plan of one answer (lane F; A-DECISIONS D-A19, D-A21). Pure, so every surface agrees and
 * tests can prove the rule that matters most: passive reopening never starts (or charges for) a generation.
 */
import type { UiArtifactRefV1, UiSurface, UiTurnHandoffV1 } from '@/lib/agent-runtime/ui-contracts';

/** D-A21: dock, above-dialog and tablet sheet → panel; phone overlay → mobile; /app/agent → chat; dialog → expanded. */
export function surfaceFor(frame: { kind: 'dock' | 'above' | 'overlay' | 'chat' | 'expanded' | 'founder' | 'voice'; wide?: boolean }): UiSurface {
  switch (frame.kind) {
    case 'dock':
    case 'above':
      return 'panel';
    case 'overlay':
      return frame.wide ? 'panel' : 'mobile';
    case 'chat':
      return 'chat';
    case 'expanded':
      return 'expanded';
    case 'founder':
      return 'founder';
    case 'voice':
      return 'browser_voice';
    default:
      return 'panel';
  }
}

/** Expanding is offered where there is room to gain; on a phone the panel is already the full screen (render in place). */
export function canExpand(surface: UiSurface): boolean {
  return surface === 'panel' || surface === 'chat';
}

export type PresentationPlan =
  | { kind: 'none' }
  /** The answer already has views: read their snapshots (zero provider attempts). */
  | { kind: 'load'; artifacts: UiArtifactRefV1[] }
  /** A turn answered in this tab: start its one presentation with the run's stable key. */
  | { kind: 'post' }
  /** An eligible answer without a view (reloaded before it was built, or a spoken turn): offer an explicit, person-started build. */
  | { kind: 'offer' };

export function presentationPlan(input: {
  enabled: boolean;
  handoff: UiTurnHandoffV1 | null | undefined;
  artifacts: UiArtifactRefV1[] | null | undefined;
  runId: string | null | undefined;
  fresh: boolean;
  latest: boolean;
  surface: UiSurface;
  modality?: string | null;
}): PresentationPlan {
  // The kill switch means native answers only: no view loads, no query runs, nothing is generated (D-A25, G23).
  if (!input.enabled || input.surface === 'browser_voice') return { kind: 'none' };
  const refs = (input.artifacts ?? []).filter((ref) => ref && typeof ref.artifactId === 'string');
  if (refs.length) return { kind: 'load', artifacts: refs };
  if (!input.handoff?.eligible || !input.runId) return { kind: 'none' };
  if (input.fresh && input.modality !== 'voice') return { kind: 'post' };
  return input.latest ? { kind: 'offer' } : { kind: 'none' };
}

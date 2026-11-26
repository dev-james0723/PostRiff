/**
 * Where a link into the Brand page lands. Brand Brain used to read only `section=identity|boundaries` and the
 * `#manual-writing-samples` hash, so the link the generated voice view writes (`?section=teach&step=review`) and
 * a link to the import receipt were dropped. Anything unrecognised still lands on the overview.
 */
export type BrainArea = 'overview' | 'teach' | 'identity' | 'preferences' | 'sources' | 'versions' | 'advanced';
export type BrainStep = 'sources' | 'analysis' | 'review' | 'preview';

const STEPS: readonly string[] = ['sources', 'analysis', 'review', 'preview'];

/** The review of a proposed voice. On a build without Brand Brain v1.1 the same page shows the proposal card. */
export const REVIEW_HREF = '/app/workspace/brand?section=teach&step=review';
/** The three-question voice setup that needs no writing samples. */
export const MANUAL_SETUP_HREF = '/app/workspace/brand?section=teach&setup=manual';

export interface BrainLanding {
  area?: BrainArea;
  step?: BrainStep;
  /** Open the setup that needs no samples. */
  manualSetup?: boolean;
}

export function brainLanding(search: string, hash = ''): BrainLanding {
  const params = new URLSearchParams(search);
  const section = params.get('section');
  if (section === 'boundaries' || section === 'identity') return { area: 'identity' };
  if (section === 'sources') return { area: 'sources' };
  if (section === 'teach') {
    if (params.get('setup') === 'manual') return { area: 'teach', step: 'sources', manualSetup: true };
    const step = params.get('step') ?? '';
    return STEPS.includes(step) ? { area: 'teach', step: step as BrainStep } : { area: 'teach' };
  }
  if (hash === '#manual-writing-samples') return { area: 'teach', step: 'sources' };
  return {};
}

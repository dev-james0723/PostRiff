import { z } from 'zod';

// Server-authoritative readiness shared by Growth Studio and Trends
// (src/postriff_phase2/feature_readiness.py). The browser renders it; it never
// decides access. canRun only chooses which controls render — every action is
// still checked on the server.

export const READINESS_STATES = [
  'feature_disabled',
  'unsupported',
  'not_entitled',
  'setup_required',
  'temporarily_unavailable',
  'insufficient_data',
  'ready'
] as const;
export const NEXT_STEP_KINDS = ['connect', 'consent', 'plan', 'retry', 'wait', 'contact_owner', 'none'] as const;

export type ReadinessState = (typeof READINESS_STATES)[number];
export type NextStepKind = (typeof NEXT_STEP_KINDS)[number];

const reasonCode = z.string().regex(/^[a-z][a-z0-9_]{1,63}$/);
const inAppHref = z.string().regex(/^\/app(?:\/[a-z0-9_-]+)*\/?(?:[?#][A-Za-z0-9=&_.-]*)?$/);

export const featureReadinessSchema = z
  .object({
    state: z.enum(READINESS_STATES),
    reasonCodes: z.array(reasonCode).max(8),
    canRead: z.boolean(),
    canRun: z.boolean(),
    lastSuccessfulReadAt: z.iso.datetime({ offset: true }).nullable(),
    nextStep: z.object({ kind: z.enum(NEXT_STEP_KINDS), href: inAppHref.optional() }).nullable()
  })
  .refine((value) => !(value.canRun && !value.canRead), { message: 'canRun requires canRead' })
  .refine((value) => value.state !== 'ready' || value.reasonCodes.length === 0, { message: 'ready has no reasons' })
  .refine(
    (value) =>
      value.state !== 'temporarily_unavailable' ||
      !value.nextStep ||
      ['retry', 'wait', 'none'].includes(value.nextStep.kind),
    { message: 'an outage never asks for setup' }
  );

export type FeatureReadiness = z.infer<typeof featureReadinessSchema>;

// Used when the server answer is missing or malformed: nothing runs, nothing is
// implied about the workspace, and the person can only retry.
export const READINESS_UNVERIFIED: FeatureReadiness = {
  state: 'temporarily_unavailable',
  reasonCodes: ['readiness_unverified'],
  canRead: false,
  canRun: false,
  lastSuccessfulReadAt: null,
  nextStep: { kind: 'retry' }
};

export function parseReadiness(value: unknown): FeatureReadiness | null {
  const parsed = featureReadinessSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function readinessOrUnverified(value: unknown): FeatureReadiness {
  return parseReadiness(value) ?? READINESS_UNVERIFIED;
}

// State-level copy. Feature-specific reason copy lives with each feature
// (growth / trends) so the two pages can evolve without editing this file.
export const STATE_COPY: Record<ReadinessState, { title: string; detail: string; live: 'polite' | 'assertive' }> = {
  feature_disabled: {
    title: 'This feature is switched off.',
    detail: 'It is not available on this service right now. Nothing you do here will change that.',
    live: 'polite'
  },
  unsupported: {
    title: 'Not supported here yet.',
    detail: 'The sources or platforms this needs are not supported for this workspace yet.',
    live: 'polite'
  },
  not_entitled: {
    title: 'Not available for this workspace yet.',
    detail: 'This workspace is not part of the group that can use this right now.',
    live: 'polite'
  },
  setup_required: {
    title: 'One step before you can use this.',
    detail: 'Finish the step below and this will start working for this workspace.',
    live: 'polite'
  },
  temporarily_unavailable: {
    title: 'Temporarily unavailable.',
    detail: 'A service this depends on is not responding. Your settings are unchanged; try again shortly.',
    live: 'assertive'
  },
  insufficient_data: {
    title: 'Not enough evidence yet.',
    detail: 'Rafii only shows results it can back with real readings. More data has to arrive first.',
    live: 'polite'
  },
  ready: { title: 'Ready.', detail: '', live: 'polite' }
};

export const NEXT_STEP_LABEL: Record<NextStepKind, string> = {
  connect: 'Connect an account',
  consent: 'Review and allow',
  plan: 'See plans',
  retry: 'Try again',
  wait: 'Check back later',
  contact_owner: 'Ask the workspace owner',
  none: ''
};

export function readinessCopy(
  readiness: FeatureReadiness,
  reasons: Record<string, { title?: string; detail?: string }> = {}
) {
  const base = STATE_COPY[readiness.state];
  const reason = readiness.reasonCodes.map((code) => reasons[code]).find(Boolean);
  return {
    title: reason?.title ?? base.title,
    detail: reason?.detail ?? base.detail,
    live: base.live,
    action: readiness.nextStep ? NEXT_STEP_LABEL[readiness.nextStep.kind] : ''
  };
}

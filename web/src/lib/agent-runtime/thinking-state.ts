import { isThinkingOp, type ThinkingOp } from '@/components/agents/thinking/thinking-op';

export interface ThinkingProgressEvent {
  type?: string;
  stage?: string;
  thinkingOp?: unknown;
  thinkingSource?: unknown;
  reasonCode?: unknown;
}

export function thinkingOpFromEvent(event: ThinkingProgressEvent | null | undefined): ThinkingOp | null {
  if (!event || event.type !== 'progress.updated') return null;
  if (isThinkingOp(event.thinkingOp)) return event.thinkingOp;
  return legacyStageToThinkingOp(event.stage);
}

export function legacyStageToThinkingOp(stage: string | null | undefined): ThinkingOp {
  if (stage === 'writing' || stage === 'drafting') return 'composing';
  if (stage === 'image_generation') return 'shaping';
  return 'working';
}

export function latestThinkingOp(events: readonly ThinkingProgressEvent[] | null | undefined, fallback: ThinkingOp = 'working'): ThinkingOp {
  if (!events?.length) return fallback;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const op = thinkingOpFromEvent(events[index]);
    if (op) return op;
  }
  return fallback;
}


export function thinkingOrbsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_RAFII_THINKING_ORBS !== '0';
}

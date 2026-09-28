import type { Speaker, VoiceState } from '@/lib/agent-runtime/voice-session';

export type RafiiAvatarMode = 'idle' | 'listening' | 'thinking' | 'speaking' | 'interrupted';

export interface RafiiAvatarStateInput {
  state: VoiceState;
  speaker: Speaker;
  outputMuted: boolean;
  hasRunningDelegation: boolean;
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/**
 * Derive the avatar's visual state from Voice Mode's existing authoritative state.
 * No timers or synthetic backend state are introduced here.
 */
export function resolveRafiiAvatarMode(input: RafiiAvatarStateInput): RafiiAvatarMode {
  if (input.state === 'connecting' || input.state === 'reconnecting' || input.state === 'ending') return 'thinking';
  if (input.state !== 'live') return 'idle';

  // "Stop talking" sets outputMuted immediately in the real voice session. Treat it
  // as stronger than a stale speaker sample so the mouth never keeps animating.
  if (input.outputMuted) return 'interrupted';
  if (input.speaker === 'user') return 'listening';
  if (input.speaker === 'rafii') return 'speaking';
  if (input.hasRunningDelegation) return 'thinking';
  return 'idle';
}

export interface MouthTargetInput {
  mode: RafiiAvatarMode;
  level: number;
  outputMuted: boolean;
}

/**
 * Convert the real outgoing WebRTC level into a mouth-open target. This is an
 * amplitude-driven v1 lip sync signal, not a claim of phoneme-perfect visemes.
 */
export function targetMouthOpen(input: MouthTargetInput): number {
  if (input.outputMuted || input.mode !== 'speaking') return 0;

  const level = clamp01(input.level);
  const noiseGate = 0.015;
  if (level <= noiseGate) return 0;
  return clamp01((level - noiseGate) * 1.45);
}

/**
 * Fast attack with an intentionally immediate release to zero. Immediate release
 * is critical for interruption: Stop talking must visually stop in the same tick.
 */
export function smoothMouth(current: number, target: number, deltaSeconds: number): number {
  const safeCurrent = clamp01(current);
  const safeTarget = clamp01(target);
  if (safeTarget <= 0) return 0;

  const dt = Math.min(0.1, Math.max(0, Number.isFinite(deltaSeconds) ? deltaSeconds : 0));
  const blend = 1 - Math.exp(-18 * dt);
  return clamp01(safeCurrent + (safeTarget - safeCurrent) * blend);
}

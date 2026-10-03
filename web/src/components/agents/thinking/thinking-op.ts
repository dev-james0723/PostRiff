import type { OrbState } from 'thinking-orbs';

export type ThinkingOp =
  | 'working'
  | 'searching'
  | 'solving'
  | 'listening'
  | 'connecting'
  | 'weaving'
  | 'composing'
  | 'breathing'
  | 'shaping'
  | 'acting';

export const THINKING_OPS: readonly ThinkingOp[] = [
  'working',
  'searching',
  'solving',
  'listening',
  'connecting',
  'weaving',
  'composing',
  'breathing',
  'shaping',
  'acting'
] as const;

export const THINKING_LABELS: Record<ThinkingOp, string> = {
  working: 'Working…',
  searching: 'Searching…',
  solving: 'Thinking through it…',
  listening: 'Listening…',
  connecting: 'Connecting…',
  weaving: 'Pulling it together…',
  composing: 'Writing…',
  breathing: 'Ready',
  shaping: 'Shaping…',
  acting: 'Taking action…'
};

export const OFFICIAL_ORB_STATE: Record<Exclude<ThinkingOp, 'acting'>, OrbState> = {
  working: 'working',
  searching: 'searching',
  solving: 'solving',
  listening: 'listening',
  connecting: 'connecting',
  weaving: 'weaving',
  composing: 'composing',
  breathing: 'breathing',
  shaping: 'shaping'
};

export function isThinkingOp(value: unknown): value is ThinkingOp {
  return typeof value === 'string' && (THINKING_OPS as readonly string[]).includes(value);
}

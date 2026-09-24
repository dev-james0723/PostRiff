/**
 * Reasoning preference ↔ what a model route actually accepts (Rafii v9 brief C; DNA v8 §15.3–15.4;
 * PROGRESS decision D6).
 *
 * The person keeps one preference per model on the five-step ladder below (the CLI's own effort
 * levels, of which Low/Medium/High/Max are the four the bars visualise; `xhigh` reads as "High+").
 * A route exposes its real `reasoning` options; this module maps the preference onto them without
 * inventing anything: the segment labels come from the ladder, the value that is sent is always one
 * of the route's own option ids, and a route with one option or none gets "Not applied by this
 * provider" while the stored preference survives for other models.
 */

export const REASONING_LADDER = ['low', 'medium', 'high', 'xhigh', 'max'] as const;
export type ReasoningLevel = (typeof REASONING_LADDER)[number];

/** The four generic levels the bar indicator names (DNA §15.4). */
export const REASONING_GENERIC: readonly ReasoningLevel[] = ['low', 'medium', 'high', 'max'];

export const REASONING_LABELS: Record<ReasoningLevel, string> = { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'High+', max: 'Max' };

/** Lit bars out of four; 3.5 lights the fourth bar half-way (the CLI's `xhigh` sits between High and Max). */
export const REASONING_BARS: Record<ReasoningLevel, number> = { low: 1, medium: 2, high: 3, xhigh: 3.5, max: 4 };

export const NOT_APPLIED = 'Not applied by this provider';

export interface ReasoningOption {
  id: string;
  available: boolean;
  detail?: string;
}

export interface ReasoningSegment {
  /** The option id the route accepts; this is what a run sends. */
  id: string;
  level: ReasoningLevel;
  label: string;
  bars: number;
  detail: string;
}

export interface ReasoningMapping {
  /** False when the route offers fewer than two options: the control shows greyed and nothing is chosen. */
  applied: boolean;
  segments: ReasoningSegment[];
  /** The segment in use: the preference itself, or the nearest lower level the route offers. */
  selected: ReasoningSegment | null;
  /** The preference on the ladder (stored or defaulted), kept even when not applied. */
  preference: ReasoningLevel;
  /** Whether `preference` came from a stored choice rather than the route's default. */
  stored: boolean;
  /** The option id to send with a run; null when the route lists nothing at all. */
  effective: string | null;
  /** Copy for beneath the control. */
  summary: string;
}

/** Option ids the runtimes use today (cli_runtime.effort, model_runtime, the fixture) and their level. */
const KNOWN: Record<string, ReasoningLevel> = {
  low: 'low',
  minimal: 'low',
  quick: 'low',
  medium: 'medium',
  standard: 'medium',
  default: 'medium',
  high: 'high',
  deep: 'high',
  xhigh: 'xhigh',
  'extra-high': 'xhigh',
  extra_high: 'xhigh',
  max: 'max',
  maximum: 'max'
};

/** A ladder level or a known option id → its level; anything else → null. */
export function normaliseLevel(value: unknown): ReasoningLevel | null {
  if (typeof value !== 'string') return null;
  return KNOWN[value.trim().toLowerCase()] ?? null;
}

/** The level an option represents; unknown vocabularies are read by rank from the bottom. */
export function levelOf(id: string, index: number, count: number): ReasoningLevel {
  const known = normaliseLevel(id);
  if (known) return known;
  const ladder = count > REASONING_GENERIC.length ? REASONING_LADDER : REASONING_GENERIC;
  return ladder[Math.min(Math.max(0, index), ladder.length - 1)];
}

function rank(level: ReasoningLevel) {
  return REASONING_LADDER.indexOf(level);
}

function segment(id: string, level: ReasoningLevel, detail = ''): ReasoningSegment {
  return { id, level, label: REASONING_LABELS[level], bars: REASONING_BARS[level], detail };
}

/**
 * Map a stored preference onto a route's options. `preference` may be a ladder level or an option
 * id (the composer's existing `chooseReasoning` passes option ids); `modelLabel` is only used in copy.
 */
export function mapReasoning(preference: string | null | undefined, options: readonly ReasoningOption[] | undefined, modelLabel: string): ReasoningMapping {
  const available = (options ?? []).filter((option) => option && option.available && typeof option.id === 'string');
  const segments = available.map((option, index) => segment(option.id, levelOf(option.id, index, available.length), option.detail ?? ''));
  const wanted = normaliseLevel(preference);
  const stored = wanted !== null;
  const level = wanted ?? segments[0]?.level ?? 'low';

  if (segments.length < 2) {
    return {
      applied: false,
      segments: REASONING_GENERIC.map((generic) => segment(generic, generic)),
      selected: null,
      preference: level,
      stored,
      effective: segments[0]?.id ?? null,
      summary: NOT_APPLIED
    };
  }

  const target = rank(level);
  const selected = segments.toReversed().find((item) => rank(item.level) <= target) ?? segments[0];
  const nearest = selected.level !== level ? ` (nearest to ${REASONING_LABELS[level]})` : '';
  const summary = stored ? `Effective for ${modelLabel}: ${selected.id}${nearest}` : `Provider default for ${modelLabel}: ${selected.id}`;
  return { applied: true, segments, selected, preference: level, stored, effective: selected.id, summary };
}

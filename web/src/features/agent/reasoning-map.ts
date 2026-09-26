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
 *
 * Levels (the second half of this file) are the model picker's vocabulary since the per-model catalogue: a
 * managed writer lists Auto, the gateway efforts it supports and Thorough, each with a label and what it
 * sends; the person's choice is stored verbatim per model id (or per Auto) and falls back to Auto when the
 * writer does not offer it. This file stays import-free: the unit tests transpile it on its own.
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

/* ---------- Levels: Auto, the gateway efforts a writer supports, Thorough ---------- */

/** Rafii decides (the self-checked standard pass on a managed writer). Never sent: requests omit `reasoning`. */
export const AUTO_LEVEL = 'auto';
/** Draft, then a critique-and-revise pass. The only level Auto offers besides itself. */
export const THOROUGH_LEVEL = 'thorough';

/** Names for levels the catalogue sends without a label (the fixture and CLI routes, older servers). */
export const LEVEL_LABELS: Record<string, string> = {
  auto: 'Auto',
  none: 'Off',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra high',
  max: 'Max',
  thorough: 'Thorough (draft, then revise)',
  quick: 'Quick',
  standard: 'Standard',
  deep: 'Deep'
};

/** Lit bars out of four. Auto has none: the dialog says "Auto" in words instead. */
export const LEVEL_BARS: Record<string, number> = { none: 0, minimal: 0.5, low: 1, medium: 2, high: 3, xhigh: 3.5, max: 4, thorough: 4, quick: 1, standard: 2, deep: 4 };

/** A reasoning item as the catalogue sends it (`ReasoningItem` in lib/api/types.ts, kept structural here). */
export interface LevelSource {
  id: string;
  available: boolean;
  detail?: string;
  label?: string;
  kind?: string;
  sends?: string | null;
  typicalMilliCredits?: number | null;
  ceilingMilliCredits?: number | null;
}

export interface Level {
  id: string;
  label: string;
  available: boolean;
  detail: string;
  /** `route` for an option without a kind (fixture, CLI, older servers). */
  kind: 'auto' | 'effort' | 'pass' | 'route';
  /** What the accessible name says the level sends ("High: sends high"): the catalogue's `sends`, else the id. */
  sends: string;
  /** Null for Auto. */
  bars: number | null;
  typicalMilliCredits: number | null;
  ceilingMilliCredits: number | null;
}

function validItems(items: readonly LevelSource[] | null | undefined): LevelSource[] {
  return (Array.isArray(items) ? items : []).filter((item): item is LevelSource => Boolean(item) && typeof item.id === 'string' && item.id !== '' && typeof item.available === 'boolean');
}

const milli = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

function toLevel(item: LevelSource): Level {
  const kind = item.kind === 'auto' || item.kind === 'effort' || item.kind === 'pass' ? item.kind : 'route';
  return {
    id: item.id,
    label: item.label || LEVEL_LABELS[item.id] || item.id,
    available: item.available,
    detail: item.detail ?? '',
    kind,
    sends: item.sends || item.id,
    bars: item.id === AUTO_LEVEL ? null : (LEVEL_BARS[item.id] ?? null),
    typicalMilliCredits: milli(item.typicalMilliCredits),
    ceilingMilliCredits: milli(item.ceilingMilliCredits)
  };
}

/** A managed writer's list has an Auto level; the fixture's and the CLI routes' lists have none. */
export function hasAutoLevel(items: readonly LevelSource[] | null | undefined): boolean {
  return validItems(items).some((item) => item.kind === 'auto');
}

/**
 * The levels to offer, in catalogue order. `autoOnly` (the writer is Auto, so the model can change under the person)
 * keeps only Auto and Thorough, which every managed writer lists.
 */
export function levelsFor(items: readonly LevelSource[] | null | undefined, autoOnly = false): Level[] {
  const clean = validItems(items);
  return (autoOnly ? clean.filter((item) => item.id === AUTO_LEVEL || item.id === THOROUGH_LEVEL) : clean).map(toLevel);
}

/**
 * The level a run uses. A stored level counts only when offered and available. Otherwise a managed writer uses Auto
 * and any other route its first available option (today's rule: the fixture sends `quick`, a CLI `low`).
 */
export function chooseLevel(levels: readonly Level[], stored: string | null | undefined, managed: boolean): Level | null {
  const wanted = stored ? levels.find((level) => level.id === stored && level.available) : undefined;
  if (wanted) return wanted;
  const auto = managed ? levels.find((level) => level.id === AUTO_LEVEL && level.available) : undefined;
  return auto ?? levels.find((level) => level.available) ?? null;
}

/** Old (v1) ladder values on a managed writer stood for pass modes: only the old High meant the revise pass. */
const MANAGED_FROM_V1: Record<ReasoningLevel, string> = { low: AUTO_LEVEL, medium: AUTO_LEVEL, high: THOROUGH_LEVEL, xhigh: AUTO_LEVEL, max: AUTO_LEVEL };

/**
 * One-time move of the v1 preferences (`postriff-agent-reasoning`, ladder levels per model id) to the v2 vocabulary.
 * Managed ids ("maker/model") map to Auto or Thorough, CLI ids keep their effort, anything else (the fixture) is
 * dropped. The v1 key itself is never rewritten, so a tab still running the old bundle keeps working.
 */
export function migrateReasoningPreferences(v1: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!v1 || typeof v1 !== 'object' || Array.isArray(v1)) return out;
  for (const [modelId, value] of Object.entries(v1 as Record<string, unknown>)) {
    const level = normaliseLevel(value);
    if (!level) continue;
    if (modelId.startsWith('claude-code:') || modelId.startsWith('codex:')) out[modelId] = level;
    else if (modelId.includes('/')) out[modelId] = MANAGED_FROM_V1[level];
  }
  return out;
}

/** v2 preferences as stored: level ids verbatim per model id (or per Auto); anything else is ignored. */
export function readReasoningPreferences(raw: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === 'string' && value.trim()) out[key] = value.trim();
  }
  return out;
}

const creditText = (value: number) => (value / 1000).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/**
 * The cost line under the reasoning control. Credits only where the workspace pays in credits (the catalogue's
 * reference request, never provider dollars); elsewhere how the level's ceiling compares with Auto's, or nothing.
 */
export function levelHint(level: Level | null, auto: Level | null | undefined, creditsBilling: boolean): string | null {
  if (!level) return null;
  if (creditsBilling) {
    if (level.typicalMilliCredits === null || level.ceilingMilliCredits === null) return null;
    return `about ${creditText(level.typicalMilliCredits)} credits · up to ${creditText(level.ceilingMilliCredits)} for a large request`;
  }
  if (level.id === AUTO_LEVEL || !auto?.ceilingMilliCredits || level.ceilingMilliCredits === null) return null;
  const ratio = level.ceilingMilliCredits / auto.ceilingMilliCredits;
  const rounded = ratio >= 2 ? Math.round(ratio) : Math.round(ratio * 10) / 10;
  return rounded === 1 ? 'about the same as Auto' : `about ${rounded}× Auto`;
}

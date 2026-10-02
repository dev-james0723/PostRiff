import type { OverviewTrend } from '@/lib/founder/types';

export type FounderStatusState = 'busy' | 'reading' | 'error' | 'idle';

export interface FounderDynamicStatusInput {
  founderFetching: number;
  founderMutating: number;
  agentBusy: boolean;
  sessionStatus: 'loading' | 'ready' | 'error' | string;
}

export function deriveFounderDynamicStatus(input: FounderDynamicStatusInput): { state: FounderStatusState; label: string; tone: string; busy: boolean } {
  if (input.sessionStatus === 'error') return { state: 'error', label: 'Session check failed', tone: 'text-destructive', busy: false };
  if (input.agentBusy) return { state: 'busy', label: 'Rafii working', tone: 'text-foreground', busy: true };
  if (input.founderMutating > 0) return { state: 'busy', label: 'Saving change', tone: 'text-foreground', busy: true };
  if (input.founderFetching > 0 || input.sessionStatus === 'loading') return { state: 'reading', label: 'Reading records', tone: 'text-muted-foreground', busy: false };
  return { state: 'idle', label: 'No active founder task', tone: 'text-muted-foreground', busy: false };
}

export type TrendRow = { t: string } & Record<string, number | null | string>;

export function founderTrendRows(trend: OverviewTrend | null | undefined): TrendRow[] {
  if (!trend) return [];
  const rows = new Map<string, TrendRow>();
  for (const series of Array.isArray(trend.series) ? trend.series : []) {
    for (const point of series.points ?? []) {
      const row = rows.get(point.t) ?? { t: point.t };
      row[series.id] = typeof point.value === 'number' && Number.isFinite(point.value) ? point.value : null;
      rows.set(point.t, row);
    }
  }
  return [...rows.values()].toSorted((a, b) => a.t.localeCompare(b.t));
}

export function reconcileTrendIndex(length: number, requested: number): number {
  if (length <= 0) return 0;
  if (!Number.isFinite(requested)) return length - 1;
  return Math.max(0, Math.min(length - 1, Math.trunc(requested)));
}

export interface DonutInput {
  id: string;
  label: string;
  value: number | null | undefined;
}

export function normalizeDonutItems(items: readonly DonutInput[]) {
  const valid = items
    .filter((item) => typeof item.value === 'number' && Number.isFinite(item.value) && item.value >= 0)
    .map((item) => ({ id: String(item.id), label: String(item.label), value: item.value as number }));
  const rejected = items
    .filter((item) => !(typeof item.value === 'number' && Number.isFinite(item.value) && item.value >= 0))
    .map((item) => ({ id: String(item.id), label: String(item.label), reason: 'unsupported_value' as const }));
  const total = valid.reduce((sum, item) => sum + item.value, 0);
  if (!Number.isFinite(total)) return { valid: [], rejected: items.map(item => ({ id: String(item.id), label: String(item.label), reason: 'unsupported_value' as const })), total: 0 };
  return { valid, rejected, total };
}

const ABSENT = Symbol('absent');

function valueOf(object: Record<string, unknown> | null | undefined, key: string): unknown | typeof ABSENT {
  return object && Object.prototype.hasOwnProperty.call(object, key) ? object[key] : ABSENT;
}

function equalValue(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function safeDiffDisplay(value: unknown | typeof ABSENT): string {
  if (value === ABSENT) return 'Absent';
  if (value === null) return 'Explicit null';
  if (value === undefined) return 'Undefined';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (typeof value === 'object') {
    try {
      const text = JSON.stringify(value, (key, item) => /^(password|secret|token|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|authorization|cookie)$/i.test(key) ? '[redacted]' : item);
      return text.length > 1000 ? `${text.slice(0, 997)}… (truncated)` : text;
    } catch { return 'Value cannot be displayed safely'; }
  }
  return String(value);
}

export function buildDiffRows(before: Record<string, unknown> | null | undefined, after: Record<string, unknown> | null | undefined) {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].toSorted();
  return keys.map((key) => {
    const previous = valueOf(before, key);
    const next = valueOf(after, key);
    const status = previous === ABSENT ? 'added' : next === ABSENT ? 'removed' : equalValue(previous, next) ? 'unchanged' : 'changed';
    return { key, before: safeDiffDisplay(previous), after: safeDiffDisplay(next), status };
  });
}

function textHash(text: string): string {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

export interface DraftRevision {
  text: string;
  hash: string;
}

export interface DraftSuggestion {
  revision: DraftRevision;
  text: string;
  source: 'local' | 'agent';
}

export interface AppliedDraftSuggestion {
  revision: DraftRevision;
  previous: string;
  text: string;
}

export function createDraftRevision(text: string): DraftRevision {
  return { text, hash: textHash(text) };
}

export function makeLocalDraftSuggestion(text: string): DraftSuggestion | null {
  if (!text.trim()) return null;
  const tightened = text
    .split('\n')
    .map((line) => line.replace(/[ \t]+$/g, ''))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n');
  return { revision: createDraftRevision(text), text: tightened, source: 'local' };
}

export function createAgentRevisionPrompt(text: string): string {
  return [
    'Please revise this founder draft for clarity and brevity while preserving factual meaning, formatting, links, IDs, quoted text, and approval boundaries.',
    'Return only the revised draft text plus any caveats if facts are missing.',
    '',
    text
  ].join('\n');
}

export function applyDraftSuggestion(current: string, suggestion: DraftSuggestion): AppliedDraftSuggestion | null {
  if (current !== suggestion.revision.text || createDraftRevision(current).hash !== suggestion.revision.hash) return null;
  return { revision: createDraftRevision(suggestion.text), previous: current, text: suggestion.text };
}

export function undoDraftSuggestion(current: string, applied: AppliedDraftSuggestion | null): string | null {
  if (!applied || current !== applied.revision.text || createDraftRevision(current).hash !== applied.revision.hash) return null;
  return applied.previous;
}

export function createSingleDispatchGuard() {
  let dispatched = false;
  return (allowed: boolean, dispatch: () => void): boolean => {
    if (!allowed || dispatched) return false;
    dispatched = true;
    dispatch();
    return true;
  };
}
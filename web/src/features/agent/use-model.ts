'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ModelCatalog, ModelOption } from '@/lib/api/types';
import { mapReasoning, normaliseLevel, type ReasoningLevel } from './reasoning-map';

const STORAGE_KEY = 'postriff-agent-model';
/** Reasoning preference per model id (`{ [modelId]: 'low' | 'medium' | 'high' | 'xhigh' | 'max' }`). */
const REASONING_KEY = 'postriff-agent-reasoning';

export const FIXTURE_MODEL = 'deterministic-preview';

/** Human names for the CLI routes the API can drive (`route` on a model option). */
export const ROUTE_LABELS: Record<string, string> = { 'claude-code': 'Claude Code', codex: 'Codex CLI' };

/** Short pill label: "Claude Code · sonnet", "Codex · default", "Deterministic preview". */
export function shortLabel(option: ModelOption | undefined, id: string) {
  const route = option?.route;
  if (route && ROUTE_LABELS[route]) {
    const alias = id.startsWith(`${route}:`) ? id.slice(route.length + 1) : id;
    return `${route === 'codex' ? 'Codex' : ROUTE_LABELS[route]} · ${alias || 'default'}`;
  }
  if (id === FIXTURE_MODEL) return 'Deterministic preview';
  return option?.label ?? id;
}

function readPreferences(): Record<string, ReasoningLevel> {
  const out: Record<string, ReasoningLevel> = {};
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(REASONING_KEY) ?? '{}');
    if (raw && typeof raw === 'object') {
      for (const [modelId, value] of Object.entries(raw as Record<string, unknown>)) {
        const level = normaliseLevel(value);
        if (level) out[modelId] = level;
      }
    }
  } catch {
    /* private mode or an old shape: start without preferences */
  }
  return out;
}

/**
 * Which model writes the next turn, and how hard it should think. The model is remembered per
 * browser and falls back to the first qualified model when the remembered one is unavailable
 * (signed out CLI, other host). The reasoning preference is remembered per model id
 * (`postriff-agent-reasoning`); `reasoning` is always an option id the chosen route accepts
 * (see `reasoning-map.ts`), so the composer keeps sending exactly what the API lists.
 */
export function useModelChoice(catalog: ModelCatalog | undefined) {
  const [stored, setStored] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<Record<string, ReasoningLevel>>({});
  useEffect(() => {
    try {
      setStored(localStorage.getItem(STORAGE_KEY));
    } catch {
      /* private mode: stay with the default */
    }
    setPreferences(readPreferences());
  }, []);

  const options = useMemo(() => catalog?.models ?? [], [catalog]);
  const model = useMemo(() => {
    const wanted = options.find((m) => m.id === stored && m.qualified);
    return (wanted ?? options.find((m) => m.qualified) ?? options[0])?.id ?? FIXTURE_MODEL;
  }, [options, stored]);

  const choose = useCallback((id: string) => {
    setStored(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  /** Remember a preference (a ladder level or an option id) for one model. */
  const setReasoningFor = useCallback((modelId: string, value: string) => {
    const level = normaliseLevel(value);
    if (!level) return;
    setPreferences((current) => {
      if (current[modelId] === level) return current;
      const next = { ...current, [modelId]: level };
      try {
        localStorage.setItem(REASONING_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  /** The remembered preference for a model, or null when the person has not chosen one. */
  const reasoningFor = useCallback((modelId: string): ReasoningLevel | null => preferences[modelId] ?? null, [preferences]);

  const chooseReasoning = useCallback((value: string) => setReasoningFor(model, value), [model, setReasoningFor]);

  const option = options.find((m) => m.id === model);
  const reasoningSource = option?.reasoning ?? catalog?.reasoning ?? [];
  const reasoningOptions = reasoningSource.filter((item) => item.available);
  const reasoningMapping = mapReasoning(preferences[model] ?? null, reasoningSource, shortLabel(option, model));
  const reasoning = reasoningMapping.effective ?? 'quick';
  return {
    model,
    option,
    options,
    choose,
    /** The option id sent with a run (never a level the route does not list). */
    reasoning,
    reasoningOptions,
    /** How the stored preference maps onto the chosen model's real options (for the dialog and honest copy). */
    reasoningMapping,
    reasoningFor,
    setReasoningFor,
    /** Existing composer callback: accepts an option id or a ladder level for the current model. */
    chooseReasoning,
    saved: stored,
    label: shortLabel(option, model)
  };
}

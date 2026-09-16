'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ModelCatalog, ModelOption } from '@/lib/api/types';

const STORAGE_KEY = 'postriff-agent-model';

export const FIXTURE_MODEL = 'deterministic-preview';

/** Short pill label: "Claude Code · sonnet", "Deterministic preview". */
export function shortLabel(option: ModelOption | undefined, id: string) {
  if (option?.route === 'claude-code') return `Claude Code · ${id.split(':')[1] ?? 'default'}`;
  if (id === FIXTURE_MODEL) return 'Deterministic preview';
  return option?.label ?? id;
}

/**
 * Which model writes the next turn. Remembered per browser; falls back to the first
 * qualified model when the remembered one is unavailable (signed out CLI, other host).
 */
export function useModelChoice(catalog: ModelCatalog | undefined) {
  const [stored, setStored] = useState<string | null>(null);
  useEffect(() => {
    try {
      setStored(localStorage.getItem(STORAGE_KEY));
    } catch {
      /* private mode: stay with the default */
    }
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

  const option = options.find((m) => m.id === model);
  return { model, option, options, choose, label: shortLabel(option, model) };
}

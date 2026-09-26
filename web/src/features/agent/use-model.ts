'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ModelCatalog, ModelOption } from '@/lib/api/types';
import { chooseLevel, hasAutoLevel, levelsFor, mapReasoning, migrateReasoningPreferences, readReasoningPreferences, type Level } from './reasoning-map';

const STORAGE_KEY = 'postriff-agent-model-v2';
/** Before 2026-09-25 the fixture was often the only writer offered, so a saved fixture there is not a choice of templates. */
const LEGACY_STORAGE_KEY = 'postriff-agent-model';
/** v1 reasoning preferences (`{ [modelId]: 'low' | 'medium' | 'high' | 'xhigh' | 'max' }`): read once for the move to v2, never written. */
const REASONING_KEY_V1 = 'postriff-agent-reasoning';
/** Level ids verbatim per model id, or per AUTO_MODEL (`{ 'openai/gpt-6-sol': 'high', auto: 'thorough' }`). */
const REASONING_KEY = 'postriff-agent-reasoning-v2';

export const FIXTURE_MODEL = 'deterministic-preview';
/** The writer choice that follows the workspace default (else the deployment's). Stored in this browser, never sent. */
export const AUTO_MODEL = 'auto';
/**
 * The level id meaning "Rafii decides" (reasoning-map's AUTO_LEVEL). Repeated here because the unit tests load this
 * file with './reasoning-map' stubbed, so the pure helpers below must not read anything from it.
 */
const AUTO_REASONING = 'auto';

/** Human names for the CLI routes the API can drive (`route` on a model option). */
export const ROUTE_LABELS: Record<string, string> = { 'claude-code': 'Claude Code', codex: 'Codex CLI' };

/** Short pill label: "Claude Code · sonnet", "Codex · default", "Templates (no AI model)". */
export function shortLabel(option: ModelOption | undefined, id: string) {
  const route = option?.route;
  if (route && ROUTE_LABELS[route]) {
    const alias = id.startsWith(`${route}:`) ? id.slice(route.length + 1) : id;
    return `${route === 'codex' ? 'Codex' : ROUTE_LABELS[route]} · ${alias || 'default'}`;
  }
  if (id === FIXTURE_MODEL) return 'Templates (no AI model)';
  return option?.label ?? id;
}

/** A writer's name in copy: the managed display name ("gpt-6-sol"), else the short label. */
export function modelName(option: ModelOption | undefined, id: string) {
  return option?.displayName ?? shortLabel(option, id);
}

/** Where Auto looks: the owner's workspace default (snapshot `writerDefaults.model`) and the deployment's (`catalog.defaultModel`). */
export interface AutoDefaults {
  workspace?: string | null;
  deployment?: string | null;
}

/** A workspace default counts only while it is offered, available and priced (the server's rule: owned and priced). */
function usableDefault(option: ModelOption) {
  return option.qualified && option.priced !== false;
}

/**
 * Which model writes the next turn. The model is remembered per browser; nothing stored (or Auto) follows the
 * workspace default, else the deployment's default writer, else today's rule: the first qualified paid managed
 * writer, then templates, then anything qualified. A remembered id always wins, even when unavailable: drafting
 * waits for the person to choose again (no silent paid fallback). Always a concrete catalogue id, or '' before the
 * catalogue arrives (the server then uses its default writer).
 */
export function resolveModelChoice(options: readonly ModelOption[], stored: string | null, auto?: AutoDefaults): string {
  // A remembered unavailable writer is an explicit choice, never permission to substitute another.
  if (stored && stored !== AUTO_MODEL) return stored;
  const workspace = auto?.workspace ? options.find((m) => m.id === auto.workspace && usableDefault(m)) : undefined;
  if (workspace) return workspace.id;
  const deployment = auto?.deployment ? options.find((m) => m.id === auto.deployment) : undefined;
  if (deployment) return deployment.id;
  const cloud = options.find((m) => m.qualified && m.costClass === 'paid' && (!m.route || m.route === 'managed'));
  // With no catalogue yet, no model at all: the server then uses its default writer (the managed one when mounted),
  // never templates the person did not choose.
  return (cloud ?? options.find((m) => m.qualified && m.id === FIXTURE_MODEL) ?? options.find((m) => m.qualified))?.id ?? '';
}

/** What Auto writes with right now, whether that is the workspace's or the deployment's default, and why when it fell back. */
export function resolveAuto(options: readonly ModelOption[], auto?: AutoDefaults): { model: string; source: 'workspace' | 'deployment'; note: string | null } {
  const model = resolveModelChoice(options, null, auto);
  const workspace = Boolean(auto?.workspace) && options.some((m) => m.id === auto?.workspace && usableDefault(m));
  const note =
    auto?.workspace && !workspace && options.length > 0
      ? `The workspace default writer ${auto.workspace} is no longer offered, so Rafii uses ${modelName(options.find((m) => m.id === model), model)}.`
      : null;
  return { model, source: workspace ? 'workspace' : 'deployment', note };
}

/**
 * The model and reasoning fields a request carries. A managed writer on Auto sends no model (the server resolves the
 * workspace default itself) and Auto reasoning sends no level, so no "auto" marker ever reaches a request body. Other
 * routes (templates, CLIs, catalogues from before per-model levels) keep today's rule: the model id and an explicit
 * level are always sent.
 */
export function requestFieldsFor(choice: { auto: boolean; managed: boolean; model: string; level: string | null }): { model?: string; reasoning?: string } {
  if (choice.managed) {
    return {
      ...(choice.auto || !choice.model ? {} : { model: choice.model }),
      ...(choice.level && choice.level !== AUTO_REASONING ? { reasoning: choice.level } : {})
    };
  }
  return { ...(choice.model ? { model: choice.model } : {}), reasoning: choice.level ?? 'quick' };
}

/**
 * The remembered writer: the current key, else a legacy one unless it is the fixture. Templates were often the
 * only writer offered before a managed one existed, so an old saved fixture counts as no choice; choosing
 * "Templates (no AI model)" now is saved under the current key and kept.
 */
export function storedModelChoice(current: string | null, legacy: string | null): string | null {
  if (current) return current;
  return legacy && legacy !== FIXTURE_MODEL ? legacy : null;
}

/** v2 preferences; on first use they are moved from v1 once (v1 itself is left as it was). */
function loadPreferences(): Record<string, string> {
  try {
    const current = localStorage.getItem(REASONING_KEY);
    if (current !== null) return readReasoningPreferences(JSON.parse(current));
    const moved = migrateReasoningPreferences(JSON.parse(localStorage.getItem(REASONING_KEY_V1) ?? '{}'));
    localStorage.setItem(REASONING_KEY, JSON.stringify(moved));
    return moved;
  } catch {
    /* private mode or an old shape: start without preferences */
    return {};
  }
}

/**
 * The browser's writer choice. `model` is always the concrete id a run uses (on Auto: the workspace default, else
 * the deployment's); `selection` is what the person chose (AUTO_MODEL or an id) and `requestFields` what a request
 * carries. The reasoning level is remembered per model id, or per Auto (`postriff-agent-reasoning-v2`); a level the
 * writer does not offer, or marks unavailable, falls back to Auto (managed writers) or the route's first option.
 */
export function useModelChoice(catalog: ModelCatalog | undefined, workspaceDefault?: string | null) {
  const [stored, setStored] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<Record<string, string>>({});
  useEffect(() => {
    try {
      setStored(storedModelChoice(localStorage.getItem(STORAGE_KEY), localStorage.getItem(LEGACY_STORAGE_KEY)));
    } catch {
      /* private mode: stay with the default */
    }
    setPreferences(loadPreferences());
  }, []);

  const options = useMemo(() => catalog?.models ?? [], [catalog]);
  const deployment = catalog?.defaultModel ?? null;
  const workspace = workspaceDefault ?? null;
  const model = useMemo(() => resolveModelChoice(options, stored, { workspace, deployment }), [options, stored, workspace, deployment]);
  const autoWriter = useMemo(() => {
    const resolved = resolveAuto(options, { workspace, deployment });
    return { ...resolved, option: options.find((m) => m.id === resolved.model) };
  }, [options, workspace, deployment]);
  const auto = !stored || stored === AUTO_MODEL;
  const selection: string = !stored || auto ? AUTO_MODEL : stored;

  const choose = useCallback((id: string) => {
    setStored(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  /** Remember a level id for one model id (or for AUTO_MODEL), verbatim; it is checked against the writer when used. */
  const setReasoningFor = useCallback((modelId: string, value: string) => {
    const level = typeof value === 'string' ? value.trim() : '';
    if (!modelId || !level) return;
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

  /** The remembered level for a model id (or AUTO_MODEL), or null when the person has not chosen one. */
  const reasoningFor = useCallback((modelId: string): string | null => preferences[modelId] ?? null, [preferences]);

  const preferenceKey = auto ? AUTO_MODEL : model;
  const chooseReasoning = useCallback((value: string) => setReasoningFor(preferenceKey, value), [preferenceKey, setReasoningFor]);

  const option = options.find((m) => m.id === model);
  const reasoningSource = option?.reasoning ?? catalog?.reasoning ?? [];
  const managed = hasAutoLevel(option?.reasoning);
  // On Auto the model can change under the person, so only Auto and Thorough (listed by every managed writer) are offered.
  const levels: Level[] = levelsFor(reasoningSource, auto && managed);
  const level = chooseLevel(levels, preferences[preferenceKey] ?? null, managed);
  const levelId = level?.id ?? null;
  const requestFields = useMemo(() => requestFieldsFor({ auto, managed, model, level: levelId }), [auto, managed, model, levelId]);
  const reasoningOptions = levels.filter((item) => item.available).map((item) => ({ id: item.id, available: true, detail: item.detail, label: item.label }));
  const reasoningMapping = mapReasoning(preferences[model] ?? null, reasoningSource, shortLabel(option, model));
  const dialogValue = useMemo(() => ({ model: selection, reasoning: levelId ?? AUTO_REASONING }), [selection, levelId]);
  const applyDialog = useCallback(
    (next: { model: string; reasoning: string }) => {
      choose(next.model);
      setReasoningFor(next.model, next.reasoning);
    },
    [choose, setReasoningFor]
  );

  return {
    /** The concrete catalogue id a run uses (on Auto, the id Auto resolves to). */
    model,
    available: Boolean(option?.qualified) && option?.priced !== false,
    option,
    options,
    choose,
    /** True when the person follows Auto (nothing stored, or AUTO_MODEL). */
    auto,
    /** AUTO_MODEL or the stored id: what pickers show as chosen. */
    selection,
    /** On Auto, whose default it followed; null for an explicit pick. */
    autoSource: auto ? autoWriter.source : null,
    /** On Auto, why the workspace default was not used; null otherwise. */
    autoNote: auto ? autoWriter.note : null,
    /** What Auto resolves to, whatever is chosen now (the pickers' Auto row). */
    autoWriter,
    /** Spread into every request body: no model on managed Auto, no reasoning on Auto level. */
    requestFields,
    /** The levels offered for the current selection, and the one in effect. */
    levels,
    level,
    /** True when the writer lists an Auto level (a managed writer on the per-model catalogue). */
    managed,
    /** The level id in effect (never a level the route does not list); 'quick' only when the route lists none. */
    reasoning: levelId ?? 'quick',
    reasoningOptions,
    /** The legacy ladder view of the stored preference (CLI routes); pickers read `levels` and `level`. */
    reasoningMapping,
    reasoningFor,
    setReasoningFor,
    /** Existing composer callback: a level id for the current selection. */
    chooseReasoning,
    /** The model dialog's committed value and its apply: Auto stays Auto instead of pinning the id it resolves to. */
    dialogValue,
    applyDialog,
    saved: stored,
    label: auto ? (model ? `Auto · ${modelName(option, model)}` : 'Auto') : shortLabel(option, model)
  };
}

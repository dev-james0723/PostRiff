'use client';
/**
 * ActionButton — the only generated control that can lead to a saved change (D-A12, D-A14, spec §6.3).
 *
 * It never acts on render, mount, replay or refresh. On a trusted click it validates the enclosing Form locally, collects
 * the inputs its server binding declares (from the Form's fields and its bound `inputs`), and hands them to lane D's action
 * bridge. The bridge asks the server for an activation; the native confirmation sheet (outside the generated subtree,
 * `core/action-confirmation.tsx`) shows the server's copy; only the person's confirm executes, with a durable
 * idempotency key. Its label and summary come from the server manifest, never from generated text. It is disabled while
 * the view streams or validates, for a revision the server has not accepted, and when the binding or role does not allow it.
 */
import { z } from 'zod';
import { Button as UiButton } from '@/components/ui/button';
import type { JsonValue } from '@/lib/agent-runtime/ui-contracts';
import { useRafiiActionBridge, useRafiiActionState } from '../../bridges/context';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { useGenUiLocale } from '../../core/locale';
import { useFormName, useIsStreaming } from '../../core/openui';
import { safeProps } from '../../core/props';
import { useGenUiRuntime } from '../../core/runtime-context';
import { useFormValues, useRafiiForm } from './inputs';
import { Unrenderable } from './shared';

const ACTION_ID = /^[a-z][a-z0-9_]{1,63}$/;
const MAX_INPUT_KEYS = 32;

const actionProps = z.object({
  actionId: z.string().regex(ACTION_ID),
  formName: z.string().max(64).optional(),
  inputs: z.record(z.string(), z.unknown()).optional(),
});

/** JSON-safe copy (functions, cycles beyond depth and non-finite numbers dropped). */
function toJson(value: unknown, depth = 0): JsonValue | undefined {
  if (depth > 8) return undefined;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value as JsonValue;
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (Array.isArray(value)) return value.map((v) => toJson(v, depth + 1)).filter((v): v is JsonValue => v !== undefined).slice(0, 200);
  if (typeof value === 'object') {
    const out: Record<string, JsonValue> = {};
    for (const [key, inner] of Object.entries(value as Record<string, unknown>).slice(0, MAX_INPUT_KEYS)) {
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
      const safe = toJson(inner, depth + 1);
      if (safe !== undefined) out[key] = safe;
    }
    return out;
  }
  return undefined;
}

/** The keys the server binding accepts (`inputSchema.properties`), or null when it does not list them. */
function declaredKeys(inputSchema: unknown): Set<string> | null {
  if (!inputSchema || typeof inputSchema !== 'object') return null;
  const properties = (inputSchema as { properties?: unknown }).properties;
  if (!properties || typeof properties !== 'object') return null;
  return new Set(Object.keys(properties as Record<string, unknown>));
}

export function collectActionInputs(options: {
  inputSchema: unknown;
  formValues: Record<string, unknown>;
  bound: Record<string, unknown> | undefined;
}): Record<string, JsonValue> {
  const allowed = declaredKeys(options.inputSchema);
  const out: Record<string, JsonValue> = {};
  const add = (key: string, value: unknown) => {
    if (allowed && !allowed.has(key)) return;
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') return;
    const safe = toJson(value);
    if (safe !== undefined) out[key] = safe;
  };
  for (const [key, value] of Object.entries(options.formValues)) add(key, value);
  for (const [key, value] of Object.entries(options.bound ?? {})) add(key, value);
  return out;
}

export const ActionButton: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(actionProps, props);
  const l = useGenUiLocale();
  const runtime = useGenUiRuntime();
  const bridge = useRafiiActionBridge();
  const state = useRafiiActionState();
  const streaming = useIsStreaming();
  const contextForm = useFormName();
  const form = useRafiiForm();
  const formValues = useFormValues();
  if (!p.ok) return <Unrenderable component="ActionButton" />;
  const binding = bridge?.binding(p.value.actionId);
  if (!bridge || !binding) {
    return (
      <p data-genui="ActionButton" data-statement-id={statementId} className="text-xs text-muted-foreground">
        {l.t('actionUnavailable')}
      </p>
    );
  }
  const busy = state.request?.controlId === statementId && (state.phase === 'activating' || state.phase === 'executing');
  const enabled = runtime.accepted && !streaming && bridge.writesEnabled(binding.actionId) && state.phase !== 'confirming' && !busy;
  const formName = p.value.formName ?? contextForm;
  const sameForm = form && formName === form.name ? form : null;
  return (
    <UiButton
      data-genui="ActionButton"
      data-statement-id={statementId}
      data-genui-control={statementId ?? binding.actionId}
      type="button"
      size="sm"
      variant="default"
      disabled={!enabled}
      aria-busy={busy || undefined}
      onClick={(event: { nativeEvent?: { isTrusted?: boolean } }) => {
        if (event.nativeEvent?.isTrusted === false) return;
        if (sameForm && !sameForm.validateAll()) return;
        const values = sameForm ? formValues(formName, sameForm.fields()) : {};
        bridge.request({
          actionId: binding.actionId,
          controlId: statementId,
          inputs: collectActionInputs({ inputSchema: binding.inputSchema, formValues: values, bound: p.value.inputs }),
        });
      }}
      className="w-fit"
    >
      <span dir="auto">{busy ? l.t('working') : binding.label}</span>
    </UiButton>
  );
};

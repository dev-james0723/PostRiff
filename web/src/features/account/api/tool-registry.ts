'use client';

import { useTools } from '@/lib/api/hooks';
export type { ToolBounds, ToolDefinition, ToolIsolation, ToolRegistry } from '@/lib/api/types';

export function useToolRegistry() {
  const query = useTools();
  return { available: true, query };
}

export type ToolRegistryState = ReturnType<typeof useToolRegistry>;

const EFFECT_LABELS: Record<string, string> = {
  read: 'Reads',
  creative_write: 'Writes drafts',
  workspace_mutation: 'Changes the workspace',
  paid_generation: 'Paid generation'
};

const COST_LABELS: Record<string, string> = {
  none: 'No cost',
  metered: 'Metered',
  paid: 'Paid'
};

export function effectLabel(effect: string) {
  return EFFECT_LABELS[effect] ?? effect.replace(/_/g, ' ');
}

export function costLabel(cost: string) {
  return COST_LABELS[cost] ?? cost.replace(/_/g, ' ');
}

'use client';

import { useQuery } from '@tanstack/react-query';
import { useWorkspace } from '@/lib/workspace/provider';

/**
 * The versioned tool registry `GET /api/tools` returns (`postriff_phase2/tools.py: catalog()` and
 * `isolation_status()`). These types are local until the shared API types carry them.
 */
export interface ToolBounds {
  maxSeconds: number;
  maxInputBytes: number;
  maxOutputBytes: number;
  network: string;
  files: string;
}

export interface ToolDefinition {
  id: string;
  version: string;
  effect: string;
  cost: string;
  purpose: string;
  bounds: ToolBounds;
  releaseId: string;
  state: string;
}

export interface ToolIsolation {
  isolated: boolean;
  runner: string;
  detail: string;
  publicInvokeEnabled: boolean;
}

export interface ToolRegistry {
  tools: ToolDefinition[];
  isolation: ToolIsolation;
}

/** The client method this page needs; absent until `lib/api/client.ts` exposes it. */
type ToolsClient = { tools?: () => Promise<ToolRegistry> };

/**
 * Reads the tool registry through the shared API client when the client offers a `tools()` method.
 * Until it does, `available` is false and the page says Unavailable instead of calling the API
 * another way.
 */
export function useToolRegistry() {
  const { api } = useWorkspace();
  const client = api as unknown as ToolsClient;
  const available = typeof client.tools === 'function';
  const query = useQuery({
    queryKey: ['tools'],
    queryFn: () => {
      if (typeof client.tools !== 'function') throw new Error('The tool registry cannot be read here yet.');
      return client.tools();
    },
    enabled: available,
    staleTime: 10 * 60_000
  });
  return { available, query };
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

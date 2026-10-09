'use client';

import { NATIVE_CURRENCY_METRIC_IDS } from './metric-policy';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { founderFetch, founderKeys, type FounderApi } from '@/lib/founder/api';
import { periodInterval, type PeriodKey } from './period';
import { recordsQueryBody } from './records';
import type {
  AuditEvent,
  BriefingScheduleInput,
  ContactPolicy,
  ControlFailure,
  Envelope,
  FounderMode,
  Incident,
  MetricQuery,
  MetricResult,
  Receipt,
  RecordsData,
  RecordsQueryInput,
  SourceHealthRow,
  UnknownUsageRow
} from './types';

/**
 * React Query hooks for the domain pages over the founder api client (CONTRACTS §6: `web/src/lib/founder/api.ts`,
 * owned by web-shell). The shell's `FounderSessionProvider` supplies the one client, the data mode from `?mode=`,
 * and the control session (environment, capabilities, CSRF). Keys reuse `founderKeys` where the shell defines one
 * so the evidence drawer, the overview and these pages share a cache; `founderFetch` covers the routes the typed
 * client does not name. Hooks return what the server sent; no totals, deltas or rates are derived here.
 */

export type { ControlFailure };

export function useFounderMode(): FounderMode {
  return useFounderSession().mode;
}

export interface FounderScope {
  api: FounderApi;
  mode: FounderMode;
  environment: string;
  capabilities: string[];
  /** The session answered, so the environment is known and the client holds a CSRF token for POSTs. */
  ready: boolean;
  key: (...parts: unknown[]) => readonly unknown[];
}

export function useFounderScope(): FounderScope {
  const { api, mode, environment, capabilities, sessionStatus } = useFounderSession();
  return useMemo(() => {
    const env = environment ?? 'unknown';
    return { api, mode, environment: env, capabilities, ready: sessionStatus === 'ready' && environment !== null, key: (...parts: unknown[]) => ['founder', mode, env, ...parts] as const };
  }, [api, mode, environment, capabilities, sessionStatus]);
}

export function useCapability(name: string): boolean {
  return useFounderSession().can(name);
}

/* ---------- metrics ---------- */

export interface MetricSpec {
  id: string;
  period: PeriodKey;
  groupBy?: string[];
  filters?: MetricQuery['filters'];
  comparison?: MetricQuery['comparison'];
  limit?: number;
  enabled?: boolean;
}

/**
 * Metrics whose catalog `currency_policy` is `native_currency_separate`: the server refuses them unless the query groups
 * by currency, because amounts in different currencies are never added together. `tests/founder-metric-policy.test.cjs`
 * keeps this list equal to the catalog (`src/rafii_control/pack/catalogs/metrics.json` and `metrics.d/*.json`).
 */
export const NATIVE_CURRENCY_METRICS: ReadonlySet<string> = new Set(NATIVE_CURRENCY_METRIC_IDS);

/** The groupBy a metric needs: the page's dimensions, plus currency for native-currency metrics. */
export function metricGroupBy(id: string, groupBy: readonly string[] = []): string[] {
  return NATIVE_CURRENCY_METRICS.has(id) && !groupBy.includes('currency') ? ['currency', ...groupBy] : [...groupBy];
}

export function metricQueryBody(spec: MetricSpec, now = new Date()): MetricQuery {
  return {
    metricIds: [spec.id],
    interval: periodInterval(spec.period, now),
    groupBy: metricGroupBy(spec.id, spec.groupBy),
    filters: spec.filters ?? [],
    comparison: spec.comparison ?? 'none',
    limit: spec.limit ?? 1000
  };
}

/** A KPI tile's default comparison (PRD §3.4 #1): the previous equal window, or the previous complete month for month to date. */
export function tileComparison(period: PeriodKey): MetricQuery['comparison'] {
  return period === 'mtd' ? 'previous_complete' : 'previous_equal_elapsed';
}

/**
 * One metric over one period through the receipt path (`POST /metrics/query`). The key is the spec, not the body,
 * because the interval's end moves with the clock; the server picks the buckets.
 */
export function useMetric(spec: MetricSpec) {
  const scope = useFounderScope();
  const groupBy = metricGroupBy(spec.id, spec.groupBy);
  const filters = spec.filters ?? [];
  return useQuery({
    queryKey: scope.key('metric', spec.id, spec.period, groupBy.join('|'), JSON.stringify(filters), spec.comparison ?? 'none'),
    enabled: scope.ready && spec.enabled !== false,
    staleTime: 60_000,
    queryFn: ({ signal }): Promise<MetricResult> => scope.api.metricsQuery(metricQueryBody(spec), scope.mode, { signal })
  });
}

/** `useMetric` for a KPI tile: every tile asks for its comparison window unless the page names one, so it can show a delta. */
export function useTileMetric(spec: MetricSpec) {
  return useMetric({ ...spec, comparison: spec.comparison ?? tileComparison(spec.period) });
}

export function useRenameLiveWorkspace() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: ({ workspaceId, name, revision }: { workspaceId: string; name: string; revision: number }) => {
      if (!scope.ready || scope.mode !== 'live') throw new Error('Select Live before changing an approved test workspace.');
      return scope.api.liveWorkspaceRename(workspaceId, name, revision);
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: scope.key('records') }),
        client.invalidateQueries({ queryKey: founderKeys.workspace('live', scope.environment) })
      ]);
    }
  });
}

/* ---------- records (customers, workspaces, subscriptions, payments, usage, tickets) ---------- */

export function useRecords(input: RecordsQueryInput | null) {
  const scope = useFounderScope();
  const body = input ? recordsQueryBody(scope.mode, input) : null;
  return useQuery<Envelope<RecordsData>>({
    queryKey: scope.key('records', body),
    enabled: scope.ready && body !== null,
    // Pagination can keep a prior page; a different mode, environment or collection cannot.
    // An inline callback also prevents QueryObserver from reusing an earlier placeholder callback's result.
    placeholderData: (previous, previousQuery) => {
      const previousBody = previousQuery?.queryKey[4];
      const sameCollection = previousBody && typeof previousBody === 'object' && 'collection' in previousBody && previousBody.collection === body?.collection;
      return scope.ready && body && sameCollection && previous?.environment === scope.environment && previous.data.mode === scope.mode &&
        previousQuery?.queryKey[1] === scope.mode && previousQuery.queryKey[2] === scope.environment
        ? previous : undefined;
    },
    queryFn: async ({ signal }) => {
      const result = await founderFetch<Envelope<RecordsData>>(`/workspace/${scope.mode}/query`, { method: 'POST', body, signal });
      const data = result.data;
      if (data.mode !== scope.mode || !Array.isArray(data.rows) || !Array.isArray(data.workspaces) || typeof data.total !== 'number') {
        throw new Error('Record response could not be verified. Retry the search.');
      }
      return result;
    }
  });
}

/* ---------- incidents ---------- */

export function useIncidents() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: founderKeys.incidents(scope.mode, scope.environment),
    enabled: scope.ready,
    refetchInterval: 60_000,
    queryFn: async ({ signal }) => {
      const result = await scope.api.incidents(scope.mode, { signal });
      return { ...result, incidents: (result.data.incidents ?? []) as Incident[] };
    }
  });
}

export function useAcknowledgeIncident() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => scope.api.ackIncident(id, version, scope.mode),
    onSuccess: () => client.invalidateQueries({ queryKey: founderKeys.incidents(scope.mode, scope.environment) })
  });
}

/* ---------- contact policy, schedules, test call ---------- */

export function useContactPolicy() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: founderKeys.contactPolicy(scope.environment),
    enabled: scope.ready,
    queryFn: async ({ signal }) => {
      const result = await scope.api.contactPolicy({ signal });
      return { ...result, policy: (result.data.policy ?? null) as ContactPolicy | null };
    }
  });
}

export function useSaveContactPolicy() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (policy: ContactPolicy) => scope.api.saveContactPolicy(policy),
    onSuccess: () => client.invalidateQueries({ queryKey: founderKeys.contactPolicy(scope.environment) })
  });
}

export function useBriefingSchedules() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: founderKeys.briefingSchedules(scope.environment),
    enabled: scope.ready,
    queryFn: async ({ signal }) => {
      const result = await scope.api.briefingSchedules({ signal });
      return { ...result, schedules: result.data.schedules ?? [] };
    }
  });
}

export function useCreateBriefingSchedule() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: BriefingScheduleInput) => scope.api.createBriefingSchedule(input),
    onSuccess: () => client.invalidateQueries({ queryKey: founderKeys.briefingSchedules(scope.environment) })
  });
}

export function useDeleteBriefingSchedule() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => scope.api.deleteBriefingSchedule(id),
    onSuccess: () => client.invalidateQueries({ queryKey: founderKeys.briefingSchedules(scope.environment) })
  });
}

/** Always answers 409 `POLICY_DISABLED` in this release (CONTRACTS §3); the page shows that refusal as the result. */
export function useTestCall() {
  const scope = useFounderScope();
  return useMutation({ mutationFn: (requestId: string) => scope.api.testCall({ requestId }) });
}

/* ---------- usage reconcile queue, source health, audit, receipts ---------- */

export function useUnknownUsage() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: founderKeys.usageUnknown(scope.mode, scope.environment),
    enabled: scope.ready,
    queryFn: async ({ signal }) => {
      const result = await scope.api.usageUnknown(scope.mode, { signal });
      const rows: UnknownUsageRow[] = (result.data.rows ?? []).map((row, index) => ({ ...row, id: typeof row.id === 'string' ? row.id : `row-${index}` }));
      return { ...result, rows };
    }
  });
}

export function useSourceHealth() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('sources-health'),
    enabled: scope.ready,
    refetchInterval: 60_000,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<Envelope<{ sources?: SourceHealthRow[] } | SourceHealthRow[]>>('/sources/health', { signal });
      const data = result.data;
      return { ...result, sources: Array.isArray(data) ? data : (data.sources ?? []) };
    }
  });
}

export function useAudit() {
  const scope = useFounderScope();
  // `GET /audit` needs audit.read; without it the tab says so instead of sending a request that can only be refused.
  const allowed = useCapability('audit.read');
  return useQuery({
    queryKey: scope.key('audit'),
    enabled: scope.ready && allowed,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<Envelope<{ events?: AuditEvent[]; limit?: number }>>('/audit', { signal });
      return { ...result, events: result.data.events ?? [], limit: result.data.limit ?? null };
    }
  });
}

/** Shares the evidence drawer's key and query, so looking a receipt up here warms the drawer. */
export function useReceipt(id: string | null) {
  const scope = useFounderScope();
  return useQuery({
    queryKey: founderKeys.receipt(scope.environment, id ?? ''),
    enabled: scope.ready && Boolean(id),
    retry: false,
    queryFn: async ({ signal }) => {
      const result = await scope.api.receipt(id as string, { signal });
      return { ...result, receipt: (result.data.receipt ?? null) as Receipt | null };
    }
  });
}

/** The fixed copy and code of a failed call; provider bodies never reach the page. */
export function failureOf(error: unknown): ControlFailure {
  if (error && typeof error === 'object') {
    const { message, code, status } = error as { message?: unknown; code?: unknown; status?: unknown };
    return {
      message: typeof message === 'string' && message ? message : 'Control request could not be completed. Review its evidence and retry.',
      code: typeof code === 'string' ? code : undefined,
      status: typeof status === 'number' ? status : undefined
    };
  }
  return { message: 'Control request could not be completed. Review its evidence and retry.' };
}

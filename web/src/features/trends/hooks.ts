'use client';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { coworkerKeys, useCoworkerApi } from '@/lib/coworker/hooks';
import type { TrendFlag, TrendFlags } from '@/lib/coworker/trend-types';
import { trendBetaStatusSchema } from '@/lib/coworker/trend-types';
import { createTrendApi, type TrendApi } from './api';

export function flagsFrom(value: object | undefined): TrendFlags {
  return (value ?? {}) as TrendFlags;
}
export function radarEnabled(flags: TrendFlags) {
  return (
    flags.RAFII_TREND_INTELLIGENCE_ENABLED === true && flags.RAFII_TREND_RADAR_ENABLED === true
  );
}
export function useTrendContext() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const coworker = useCoworkerApi();
  const status = useQuery({
    queryKey: coworkerKeys.status(coworker.w),
    queryFn: () => coworker.api.status(coworker.w),
    enabled: coworker.enabled,
    retry: false,
    staleTime: 0,
    refetchInterval: 30_000
  });
  const flags = flagsFrom(status.isError ? undefined : status.data?.flags);
  const parsed = trendBetaStatusSchema.safeParse(status.isError ? undefined : status.data?.trend_beta);
  const beta = parsed.success ? parsed.data : undefined;
  const api = useMemo(() => createTrendApi(getToken), [getToken]);
  return {
    api,
    w: workspaceId ?? '',
    flags,
    status,
    beta,
    enabled: Boolean(workspaceId) && radarEnabled(flags) && beta?.radar_available === true
  };
}
export function useTrendQuery<T>(
  key: readonly unknown[],
  read: (api: TrendApi, w: string, signal: AbortSignal) => Promise<T>,
  enabled = true,
  flag?: TrendFlag
) {
  const context = useTrendContext();
  return useQuery({
    queryKey: ['trends', context.w, ...key],
    queryFn: ({ signal }) => read(context.api, context.w, signal),
    enabled: context.enabled && enabled && (!flag || context.flags[flag] === true),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: 'always',
    refetchInterval: 30_000,
    refetchIntervalInBackground: false
  });
}
/** Expiry removes claims while a drawer stays open, even without another network response. */
export function useExpired(expiresAt: string | null | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!expiresAt) return;
    const remaining = Date.parse(expiresAt) - Date.now();
    if (remaining <= 0) return;
    const timer = window.setTimeout(
      () => setNow(Date.now()),
      Math.min(remaining + 10, 2_147_483_647)
    );
    return () => window.clearTimeout(timer);
  }, [expiresAt]);
  return !expiresAt || Date.parse(expiresAt) <= now;
}

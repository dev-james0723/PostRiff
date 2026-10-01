'use client';

/**
 * Which Product Growth features this deployment has switched on (`GET /api/workspaces/{id}/growth-features`, one
 * request per workspace, from each slice's own flag). Shared pages (Library, Inbox, Analytics, Weekly, Automations)
 * mount a slice only when its feature is on, so a switched-off feature is never asked for (its 404 would be console
 * noise on every visit). Loading, unknown or failed: off, never guessed on.
 */
import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { createRequester, ws } from './request';

export type GrowthFeature = 'firstWeek' | 'sourceUploads' | 'relationships' | 'results' | 'series' | 'visualPacks' | 'briefs' | 'proof';
export type GrowthFeatures = Partial<Record<GrowthFeature, boolean>>;

export const growthFeaturesKey = (w: string) => ['growth-v2', w, 'features'] as const;

export function useGrowthFeatures() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const requester = useMemo(() => createRequester(getToken), [getToken]);
  const w = workspaceId as string;
  return useQuery({
    queryKey: growthFeaturesKey(w),
    queryFn: async () => (await requester.get<{ features: GrowthFeatures }>(`${ws(w)}/growth-features`)).features,
    enabled: Boolean(workspaceId),
    staleTime: 5 * 60_000,
    retry: 1
  });
}

/** True only when the server says this feature is on. */
export function useGrowthFeature(feature: GrowthFeature): boolean {
  return useGrowthFeatures().data?.[feature] === true;
}

/** Renders its children only while the feature is on; nothing (and no request) otherwise. */
export function GrowthFeatureGate({ feature, children }: { feature: GrowthFeature; children: ReactNode }) {
  return useGrowthFeature(feature) ? <>{children}</> : null;
}
